"""Desktop-thread state adapter and compact Settings controls."""
import queue
import threading
from concurrent.futures import Future, TimeoutError
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
    QLabel, QListWidget, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from .lan_auth import APIError, PairingStore
from .lan_catalog import Catalog
from .lan_server import LANServer, addresses
from .manga_state import ReaderStore


def integer(body, key, maximum):
    value = body.get(key)
    if type(value) is not int or not 0 <= value <= maximum:
        raise APIError(400, 'invalid_' + key)
    return value


def boolean(body, key):
    if type(body.get(key)) is not bool:
        raise APIError(400, 'invalid_' + key)
    return body[key]


def apply_state(window, data_dir, scope, route, body):
    """Called only on Qt's owning thread, after rechecking device + scope."""
    catalog = Catalog(window.db, window.manga_store, scope, data_dir)
    if len(route) != 3:
        raise APIError(404, 'route_not_found')
    try:
        identity = int(route[1])
    except ValueError:
        raise APIError(404, 'route_not_found')
    kind, action = route[0], route[2]
    if kind == 'media' and action == 'progress':
        row = catalog.media(identity)
        if row['kind'] != 'episode':
            raise APIError(400, 'episode_required')
        if not body or set(body) - {'position_ms', 'watched', 'automatic'}:
            raise APIError(400, 'invalid_progress')
        automatic = boolean(body, 'automatic') if 'automatic' in body else False
        position = integer(body, 'position_ms', 7 * 24 * 3600 * 1000) if 'position_ms' in body else None
        watched = boolean(body, 'watched') if 'watched' in body else None
        if automatic and watched is False:
            raise APIError(400, 'automatic_cannot_unwatch')
        if position is not None and not (automatic and row['watched']):
            window.db.set_resume_position(identity, position)
        if watched is not None:
            if automatic:
                window.db.set_watched_through(identity)
            else:
                window.db.set_watched(identity, watched)
            window._maybe_sync_anilist_progress(row['anime_id'], 'LAN playback' if automatic else 'LAN explicit', allow_decrease=not automatic)
    elif kind == 'manga-items' and action == 'progress':
        row = catalog.manga_item(identity)
        if not body or set(body) - {'page', 'total_pages', 'finished', 'automatic'}:
            raise APIError(400, 'invalid_progress')
        automatic = boolean(body, 'automatic') if 'automatic' in body else False
        finished = boolean(body, 'finished') if 'finished' in body else None
        if automatic and finished is False:
            raise APIError(400, 'automatic_cannot_unfinish')
        page = total = None
        if 'page' in body or 'total_pages' in body:
            page = integer(body, 'page', 1000000)
            total = integer(body, 'total_pages', 1000000)
            if not 1 <= page <= total:
                raise APIError(400, 'invalid_page')
        previous = window.db.connection.execute('SELECT * FROM manga_reader_state WHERE identity=?', (row['reader_identity'],)).fetchone()
        if page is not None and not (automatic and previous and (previous['completed'] or previous['current_page'] > page)):
            store = ReaderStore(window.db)
            store.open(row['path'], scope, row['source_type'], total, row['reader_identity'])
            store.save(row['reader_identity'], page, total, finished is True)
        if finished is not None:
            window.manga_store.set_item_finished(identity, finished)
    elif kind in {'anime', 'manga'} and action in {'favorite', 'status'}:
        row = catalog.anime(identity) if kind == 'anime' else catalog.series(identity)
        key = 'favorite' if action == 'favorite' else 'status'
        if set(body) != {key}:
            raise APIError(400, 'invalid_state')
        if action == 'favorite':
            favorite = boolean(body, key)
            if kind == 'anime':
                window.db.set_favorite(identity, favorite)
            else:
                window.manga_store.set_favorite(identity, favorite)
        else:
            status = body['status']
            if status not in {None, 'Watching', 'Completed', 'Planning', 'Paused', 'Dropped'}:
                raise APIError(400, 'invalid_status')
            if kind == 'anime':
                key = window.db.set_manual_status(status, scope, anime_id=identity)
            else:
                key = window.manga_store.set_status(identity, status)
            window.manual_status_changed.emit(scope, key, status)
    else:
        raise APIError(404, 'route_not_found')
    window._library_cache_dirty = True
    window._invalidate_discover_page_cache(scope)
    return {'ok': True}


class DesktopServer(QObject):
    completed = Signal(str, bool)

    def __init__(self, window, data_dir, log):
        super().__init__(window)
        self.window, self.data_dir, self.log = window, data_dir, log
        self.auth = PairingStore(data_dir / 'lan-devices.json', log)
        self.requests = queue.Queue(maxsize=16)
        self.server = LANServer(window.db_path, data_dir, self.auth, self.submit, log)
        self.busy = False
        self.message = 'Stopped'
        self.closing = False
        self.completed.connect(self._completed)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.drain)
        self.timer.start()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.refresh_desktop)
        QTimer.singleShot(0, self.restore)

    def restore(self):
        if not self.closing and self.window.db.setting('lan_enabled', '0') == '1':
            try:
                self.start(self.window.db.setting('lan_host', '127.0.0.1'), int(self.window.db.setting('lan_port', '8765')))
            except (ValueError, OSError):
                self.server.state='Error';self.server.last_error='Invalid saved address or port; choose a current LAN address and port'

    def submit(self, identity, scope, route, body, guard):
        future = Future()
        try:
            self.requests.put_nowait((future, identity, scope, route, body, guard))
        except queue.Full:
            raise APIError(503, 'desktop_busy')
        try:
            return future.result(timeout=6)
        except TimeoutError:
            future.cancel()
            raise APIError(503, 'desktop_busy')

    def drain(self):
        for _ in range(4):
            try:
                future, identity, scope, route, body, guard = self.requests.get_nowait()
            except queue.Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if self.closing or self.window._closing:
                    raise APIError(503, 'desktop_closing')
                with self.auth.lock:
                    guard()
                    if scope == 'restricted' and self.window.db.setting('restricted_unlocked', '0') != '1':
                        raise APIError(403, 'restricted_locked')
                    result = apply_state(self.window, self.data_dir, scope, route, body)
                future.set_result(result)
                self.refresh_timer.start()
            except Exception as exc:
                future.set_exception(exc)

    def refresh_desktop(self):
        w = self.window
        if w._closing or w.player_page is not None or w.manga_reader_page is not None:
            return
        if w.current_view in {'detail','restricted_anime_detail'} and w.current_anime_id:
            w.show_detail(w.current_anime_id)
        elif w.current_view == 'library':
            w.show_library(**w.library_context)
        elif w.current_view == 'home':
            w.show_home()
        elif w.current_view in {'manga_detail','restricted_manga_detail'} and w.current_manga_id:
            w.show_manga_detail(w.current_manga_id)
        elif w.current_view in {'manga_library','restricted_manga_library'}:
            w.show_manga_library(**w.manga_context)
        elif w.current_view in {'favorites','restricted_favorites'}:
            w.show_favorites('restricted' if w.current_view.startswith('restricted') else 'normal')
        elif w.current_view in {'status_list','restricted_status_list'}:
            w.show_status_list(w.current_status_name,w.current_collection_scope)
        elif w.current_view in {'collection_detail','restricted_collection_detail'}:
            w.show_collection_detail(w.current_collection_id,w.current_collection_scope)

    def _completed(self, message, success):
        self.busy = False
        self.message = message

    def start(self, host, port):
        if self.busy or self.server.http or self.closing:
            return
        if not self.auth.available:
            self.server.state='Error';self.server.last_error='Device store unreadable; original file preserved in diagnostics folder'
            return
        if not 1024 <= port <= 65535:
            raise ValueError('Port must be between 1024 and 65535')
        self.busy = True
        self.message = 'Starting…'
        self.server.state='Starting';self.server.last_error=''
        self.window.db.set_setting('lan_host', host)
        self.window.db.set_setting('lan_port', port)
        self.window.db.set_setting('lan_enabled', '1')
        def run():
            try:
                self.server.start(host, port)
                if self.closing:
                    self.server.stop()
                self.completed.emit('On' if not self.closing else 'Off', True)
            except Exception as exc:
                self.server.state='Error'
                if not self.server.last_error:self.server.last_error=str(exc)
                self.completed.emit(self.server.last_error, False)
        threading.Thread(target=run, daemon=True, name='AniVault-LAN-start').start()

    def stop(self):
        if self.busy:
            return
        self.window.db.set_setting('lan_enabled', '0')
        self.busy = True
        self.message = 'Stopping…'
        self.server.state='Stopping'
        def run():
            self.server.stop()
            self.completed.emit('Off', True)
        threading.Thread(target=run, daemon=True, name='AniVault-LAN-stop').start()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        self.refresh_timer.stop()
        self.auth.lock_archive()
        threading.Thread(target=self.server.stop, daemon=True).start()

    def settings(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QLabel('AniVault Server')
        heading.setObjectName('section')
        layout.addWidget(heading)
        explanation = QLabel('LAN only • Off by default. Pair only trusted devices on a trusted private network. HTTP direct streaming; no internet access or port forwarding. Use the address below to connect.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        row = QHBoxLayout()
        host = QComboBox()
        host.setMinimumContentsLength(8)
        host.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        host.setObjectName('lanHost')
        host.addItems(addresses())
        saved = self.window.db.setting('lan_host')
        if saved in addresses():
            host.setCurrentText(saved)
        port = QSpinBox()
        port.setObjectName('lanPort')
        port.setRange(1024, 65535)
        try:
            port.setValue(int(self.window.db.setting('lan_port', '8765')))
        except ValueError:
            port.setValue(8765)
        row.addWidget(QLabel('Address'))
        row.addWidget(host)
        row.addWidget(QLabel('Port'))
        row.addWidget(port)
        layout.addLayout(row)
        status = QLabel()
        status.setWordWrap(True)
        status.setObjectName('lanStatus')
        status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(status)
        row = QHBoxLayout()
        start, stop, copy = QPushButton('Start'), QPushButton('Stop'), QPushButton('Copy address')
        for button in (start, stop, copy):
            row.addWidget(button)
        layout.addLayout(row)
        start.clicked.connect(lambda: self.start(host.currentText(), port.value()))
        stop.clicked.connect(self.stop)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.server.url))
        pair = QPushButton('Pair new device')
        code = QLabel()
        code.setWordWrap(True)
        code.setObjectName('lanPairingCode')
        code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        expires = [0.0]
        def pairing():
            import time
            code.setText('Pairing code (expires in 2 minutes): ' + self.auth.new_code())
            expires[0] = time.monotonic() + 120
        pair.clicked.connect(pairing)
        layout.addWidget(pair)
        layout.addWidget(code)
        devices = QListWidget()
        devices.setMaximumHeight(120)
        devices.setObjectName('lanDevices')
        layout.addWidget(devices)
        revoke, grant = QPushButton('Revoke selected device'), QPushButton('Grant Restricted until lock')
        layout.addWidget(revoke)
        layout.addWidget(grant)
        ids = []
        def selected():
            index = devices.currentRow()
            return ids[index] if 0 <= index < len(ids) else None
        def revoking():
            identity = selected()
            if identity:
                self.auth.revoke(identity)
        def granting():
            identity = selected()
            if identity and self.window.db.setting('restricted_unlocked', '0') == '1':
                self.auth.set_open(True)
                self.auth.grant(identity)
                self.window.statusBar().showMessage('Restricted LAN access granted until lock or restart.', 5000)
        revoke.clicked.connect(revoking)
        grant.clicked.connect(granting)
        def refresh():
            import time
            active = bool(self.server.http)
            info=self.server.status_info()
            status.setText(info['state'] + (' • ' + info['address'] if info['address'] else '') + ('\n'+info['error'] if info['error'] else ''))
            start.setEnabled(not self.busy and not active)
            stop.setEnabled(not self.busy and active)
            host.setEnabled(not active and not self.busy)
            port.setEnabled(not active and not self.busy)
            copy.setEnabled(active)
            pair.setEnabled(active and not self.busy)
            grant.setEnabled(active and self.window.db.setting('restricted_unlocked', '0') == '1')
            if time.monotonic() > expires[0] or not self.auth.pairing:
                code.clear()
            records = self.auth.listing()
            new_ids = [r['id'] for r in records]
            displays=[r['name']+(' • Expired — pair again' if r['expires_at']<=time.time() else '') for r in records]
            if ids != new_ids or [devices.item(i).text() for i in range(devices.count())]!=displays:
                prior=selected()
                ids[:] = new_ids
                devices.clear()
                devices.addItems(displays)
                if prior in ids:devices.setCurrentRow(ids.index(prior))
            from datetime import datetime
            for index,record in enumerate(records):
                paired=datetime.fromtimestamp(record['paired_at']).strftime('%Y-%m-%d %H:%M')
                expiry=datetime.fromtimestamp(record['expires_at']).strftime('%Y-%m-%d')
                seen=datetime.fromtimestamp(record['last_seen_at']).strftime('%Y-%m-%d %H:%M') if record.get('last_seen_at') else 'Not connected this session'
                devices.item(index).setToolTip(f"Device: {record['id']}\nPaired: {paired}\nExpires: {expiry}\nLast connected: {seen}")
        timer = QTimer(panel)
        timer.setInterval(300)
        timer.timeout.connect(refresh)
        timer.start()
        refresh()
        return panel
