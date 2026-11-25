"""Compact in-app airing notifications; no download service or private content."""
import time
from datetime import datetime, timezone
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QCheckBox, QComboBox, QFrame
from .airing_updates import AiringUpdates, fetch_vault_airing, availability_text
from .organization import metadata, display_title


class AiringUpdatesMixin:
    def _init_airing_updates(self):
        self.airing_updates = AiringUpdates(self.db)
        self._airing_check_busy = False
        self._airing_check_after = 0
        self._airing_check_message = 'Checks official airing times, not confirmed download availability.'
        self._airing_auto_timer = QTimer(self)
        self._airing_auto_timer.timeout.connect(self.check_airing_updates)
        self._configure_airing_timer()
        self._refresh_airing_bell()
        QTimer.singleShot(15000, lambda: self.check_airing_updates() if not self._closing and self.db.setting('airing_auto', '1') == '1' else None)

    def _configure_airing_timer(self):
        try: minutes = max(15, min(1440, int(self.db.setting('airing_interval', '60'))))
        except ValueError: minutes = 60
        self._airing_auto_timer.setInterval(minutes*60000)
        if self.db.setting('airing_auto', '1') == '1': self._airing_auto_timer.start()
        else: self._airing_auto_timer.stop()

    def _refresh_airing_bell(self):
        if not hasattr(self, 'airing_updates'): return
        count = sum(r['availability']=='missing' for r in self.airing_updates.vault_titles())
        from .icons import outline_icon
        self.airing_bell.setIcon(outline_icon('bell', bool(count)))
        self.airing_bell.setText(str(count) if count else '')
        self.airing_bell.setToolTip(f'Airing in your vault · {count} titles with newer aired episodes')
        self.airing_bell.setAccessibleName('Airing Updates')
        self.airing_bell.setVisible(not self._is_restricted_view())
        home=self.stack.currentWidget().findChild(QPushButton,'homeAiringUpdates') if self.stack.currentWidget() else None
        if home:home.setText(f'Airing in your vault · {count} titles with new episodes')

    def check_airing_updates(self, manual=False):
        if self._closing or self._airing_check_busy: return
        now = int(time.time())
        if now < max(self._airing_check_after, self._discover_cooldown_until):
            if manual: self.statusBar().showMessage('Please wait before checking airing updates again.', 4000)
            return
        identifiers = list(self.airing_updates.local_titles())
        self._refresh_airing_bell()
        if not identifiers:
            self._airing_check_message = 'No identified anime in your normal vault. Match a title to AniList to check its airing status.'
            if manual: self.statusBar().showMessage(self._airing_check_message, 6000)
            if self.current_view == 'airing_updates': self.show_airing_updates()
            return
        self._airing_check_busy = True; self._airing_check_after = now+60
        self._airing_check_message = 'Checking official episode schedules…'
        if manual: self.statusBar().showMessage(self._airing_check_message, 5000)
        def loaded(result):
            self._airing_check_busy = False
            prior_blocked=self.airing_updates.blocked_ids()
            self.airing_updates.apply_catalog(result['catalog'])
            added = self.airing_updates.ingest(result['schedules'])
            self._library_cache_dirty=True
            self._refresh_airing_card_markers()
            if self.airing_updates.blocked_ids()-prior_blocked:
                self.context_rail.clear();self.global_suggestions.dismiss();self.global_suggestions.results=[];self.global_suggestions.clear();self.global_search.clear()
                if not self._is_restricted_view() and self.current_view not in {'airing_updates','airing_history'}:self.show_home()
            self.db.set_setting('airing_last_check', int(time.time()))
            self._airing_check_message = f'Checked {datetime.now().strftime("%d %b, %H:%M")} · {added} new airing updates.'
            self._refresh_airing_bell()
            if self.current_view == 'airing_updates': self.show_airing_updates()
            elif self.current_view=='airing_history':self.show_airing_history()
            self.statusBar().showMessage(self._airing_check_message, 5000)
        def failed(error):
            self._airing_check_busy = False
            retry = getattr(error, 'retry_after', None)
            if getattr(error,'status_code',None)==429:self._discover_cooldown_until=max(self._discover_cooldown_until,time.time()+int(retry or 60))
            self._airing_check_after = int(time.time()) + max(300, int(retry or 0))
            self._airing_check_message = 'Airing check unavailable. Your saved notifications are preserved. Try again later.'
            if self.current_view == 'airing_updates': self.show_airing_updates()
            self.statusBar().showMessage(self._airing_check_message, 6000)
        try:last=int(self.db.setting('airing_last_check',str(now)))
        except ValueError:last=now
        after=max(0,min(now-30*86400,last-2*86400))
        self._submit_discover_job('airing-updates', lambda: fetch_vault_airing(identifiers, now, after=after), loaded, failed)

    def _airing_follow_button(self, item):return None

    def _add_airing_follow_menu(self, menu, item, scope):pass

    def _add_airing_card_menu(self, card, item):pass

    def _decorate_airing_card(self, card, identifiers, scope, snapshot=None):
        badge=getattr(card,'_airing_badge',None)
        if snapshot is None:snapshot={r['media_id']:r for r in self.airing_updates.vault_titles()} if hasattr(self,'airing_updates') else {}
        local={r['id']:identifier for identifier,members in self.airing_updates.local_titles().items() for r,_ in members} if snapshot and scope=='normal' else {}
        matches=[snapshot[local[i]] for i in identifiers if local.get(i) in snapshot] if scope=='normal' else []
        if not matches:
            if badge:badge.hide()
            return
        chosen=next((r for r in matches if r['availability']=='missing'),matches[0])
        if badge is None:
            badge=QLabel(card);badge.setObjectName('airingBadge');badge.setAttribute(Qt.WA_TransparentForMouseEvents);card._airing_badge=badge
        badge.setText(chosen['badge']);badge.setStyleSheet('background:#93294e;color:white;border-radius:6px;padding:2px 6px;font-size:11px;font-weight:600;')
        badge.setToolTip('New episode aired; download availability is not confirmed.' if chosen['availability']=='missing' else 'Currently airing in your vault.')
        badge.adjustSize();badge.move(11,10);badge.raise_();badge.show()

    def _refresh_airing_card_markers(self):
        snapshot={r['media_id']:r for r in self.airing_updates.vault_titles()}
        seen=set()
        from shiboken6 import isValid
        for (scope,key),references in self._status_card_refs.items():
            for ref in references:
                card=ref()
                if card is None or not isValid(card) or id(card) in seen:continue
                seen.add(id(card));ids=card.property('franchiseLocalIds') or ([card.anime_id] if hasattr(card,'anime_id') else [])
                if ids:self._decorate_airing_card(card,ids,scope,snapshot)

    def show_airing_updates(self):
        if self._is_restricted_view():return
        self.current_view='airing_updates';self.current_anime_id=None;self._set_active_nav('airing')
        page=QWidget();page.setProperty('transientPage',True);outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18)
        heading=QLabel('Airing in Your Vault');heading.setObjectName('title');outer.addWidget(heading)
        hint=QLabel('Your currently airing anime and the latest episodes in your library.');hint.setWordWrap(True);hint.setObjectName('muted');outer.addWidget(hint)
        controls=QHBoxLayout();check=QPushButton('Check updates');check.setEnabled(not self._airing_check_busy);check.clicked.connect(lambda:self.check_airing_updates(True));controls.addWidget(check)
        history=QPushButton('Episode history');history.clicked.connect(self.show_airing_history);controls.addWidget(history);controls.addStretch();outer.addLayout(controls)
        status=QLabel(self._airing_check_message);status.setObjectName('muted');status.setWordWrap(True);outer.addWidget(status)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();rows=QVBoxLayout(body);rows.setAlignment(Qt.AlignTop)
        titles=self.airing_updates.vault_titles()
        if not titles:
            empty=QLabel('No currently airing titles found in your vault. Check updates to refresh AniList status.');empty.setWordWrap(True);rows.addWidget(empty)
        for record in titles:
            card=QFrame();card.setObjectName('vaultAiringRow');line=QHBoxLayout(card);line.setContentsMargins(8,8,8,8)
            art=QLabel();art.setFixedSize(42,60);line.addWidget(art)
            item=record['item'];cover=item.get('cover_path')
            if cover:
                from PySide6.QtGui import QPixmap
                art.setPixmap(QPixmap(cover).scaled(42,60,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            elif (item.get('coverImage') or {}).get('large'):self._load_remote_artwork(item['coverImage']['large'],art,42,60,'normal')
            copy=QVBoxLayout();name=QLabel(display_title(item));name.setTextFormat(Qt.PlainText);name.setWordWrap(True);name.setStyleSheet('font-weight:600');copy.addWidget(name)
            local=f"{record['local_count']} local files"+(f" · latest numbered episode: {record['local_latest']}" if record['local_latest'] else '')
            text=availability_text(record['availability'],record['episode']) if record['episode'] else 'No recent aired episode data yet.'
            if record['episode']:text=f"Episode {record['episode']} has aired. "+text
            detail=QLabel(local+'\n'+text);detail.setObjectName('muted');detail.setWordWrap(True);copy.addWidget(detail);line.addLayout(copy,1)
            button=QPushButton('Open title');button.clicked.connect(lambda _,r=record:self.show_detail(r['local_ids'][0]));line.addWidget(button);rows.addWidget(card)
        scroll.setWidget(body);outer.addWidget(scroll,1);self.replace(page);self._refresh_airing_bell()

    def _airing_settings(self, layout):
        heading = QLabel('Airing Updates'); heading.setObjectName('section'); layout.addWidget(heading)
        auto = QCheckBox('Automatically check official episode airing schedules')
        auto.setChecked(self.db.setting('airing_auto', '1') == '1'); layout.addWidget(auto)
        row = QHBoxLayout(); row.addWidget(QLabel('Check interval'))
        interval = QComboBox(); interval.addItems(['15', '30', '60', '120', '360', '1440'])
        interval.setCurrentText(self.db.setting('airing_interval', '60')); row.addWidget(interval)
        row.addWidget(QLabel('minutes')); row.addStretch(); layout.addLayout(row)
        check = QPushButton('Check for Airing Updates'); check.clicked.connect(lambda: self.check_airing_updates(True)); layout.addWidget(check, 0, Qt.AlignLeft)
        def changed():
            self.db.set_setting('airing_auto', int(auto.isChecked())); self.db.set_setting('airing_interval', interval.currentText()); self._configure_airing_timer()
        auto.toggled.connect(changed); interval.currentTextChanged.connect(changed)

    def show_airing_history(self):
        if self._is_restricted_view(): return
        self.current_view = 'airing_history'; self.current_anime_id = None; self._set_active_nav('airing')
        page = QWidget(); page.setProperty('transientPage', True)
        outer = QVBoxLayout(page); outer.setContentsMargins(22, 18, 22, 18)
        title = QLabel('Episode History'); title.setObjectName('title'); outer.addWidget(title)
        hint = QLabel(self._airing_check_message); hint.setWordWrap(True); hint.setObjectName('muted'); outer.addWidget(hint)
        row = QHBoxLayout()
        check = QPushButton('Check for Airing Updates'); check.setEnabled(not self._airing_check_busy)
        check.clicked.connect(lambda: self.check_airing_updates(True)); row.addWidget(check)
        all_read = QPushButton('Mark all as read'); all_read.clicked.connect(lambda: self._airing_mark()); row.addWidget(all_read)
        seasonal = QPushButton('Current season'); seasonal.clicked.connect(self.show_airing); row.addWidget(seasonal)
        row.addStretch(); unread = QCheckBox('Unread only'); unread.setChecked(getattr(self, '_airing_unread_only', False)); row.addWidget(unread)
        def filter_changed(value): self._airing_unread_only = value; self.show_airing_history()
        unread.toggled.connect(filter_changed); outer.addLayout(row)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); body = QWidget(); rows = QVBoxLayout(body); rows.setAlignment(Qt.AlignTop); rows.setSpacing(8)
        records = self.airing_updates.history(unread.isChecked())
        if not records:
            empty = QLabel('No unread airing updates.' if unread.isChecked() else 'No episode history yet. Your airing vault titles are monitored automatically.'); empty.setWordWrap(True); rows.addWidget(empty)
        day = None
        for record in records:
            item = metadata(record['metadata_json']); date = datetime.fromtimestamp(record['airing_at'],timezone.utc).astimezone()
            if date.date() != day:
                day = date.date(); label = QLabel(date.strftime('%A, %d %B %Y')); label.setObjectName('section'); rows.addWidget(label)
            card = QFrame(); card.setObjectName('airingUpdateCard'); card.setStyleSheet('QFrame#airingUpdateCard {background:#111723;border:1px solid #303747;border-radius:10px;}')
            line = QHBoxLayout(card); line.setContentsMargins(10, 10, 10, 10)
            art = QLabel(''); art.setFixedSize(48, 68); line.addWidget(art)
            url = (item.get('coverImage') or {}).get('large')
            if url: self._load_remote_artwork(url, art, 48, 68, 'normal')
            copy = QVBoxLayout(); copy.setAlignment(Qt.AlignVCenter); copy.setSpacing(4); name = QLabel(('● ' if not record['is_read'] else '')+display_title(item)); name.setTextFormat(Qt.PlainText); name.setWordWrap(True); name.setStyleSheet('font-weight:600'); copy.addWidget(name)
            detail = QLabel(f"Episode {record['episode']} aired · {date.strftime('%d %b %Y, %H:%M %Z')}\n"+availability_text(record['availability'], record['episode'])); detail.setWordWrap(True); detail.setObjectName('muted'); copy.addWidget(detail); line.addLayout(copy, 1)
            controls = QVBoxLayout()
            for text, action in [('Open title', lambda r=record: self._open_airing_update(r)), ('Mark as read', lambda r=record: self._airing_mark(r)), ('Dismiss', lambda r=record: self._airing_mark(r, True))]:
                button = QPushButton(text); button.setFixedHeight(28); button.setStyleSheet('padding:3px 9px'); button.clicked.connect(lambda _, f=action: f()); controls.addWidget(button)
            line.addLayout(controls); rows.addWidget(card)
        scroll.setWidget(body); outer.addWidget(scroll, 1); self.replace(page); self._refresh_airing_bell()

    def _airing_mark(self, record=None, dismiss=False):
        if record: self.airing_updates.mark(record['media_id'], record['episode'], dismiss)
        else: self.airing_updates.mark()
        self._refresh_airing_bell(); self.show_airing_history()

    def _open_airing_update(self, record):
        if self._is_restricted_view() or not self.airing_updates.allowed(metadata(record['metadata_json'])): return
        self.airing_updates.mark(record['media_id'], record['episode']); self._refresh_airing_bell()
        entity = self.organization('normal').resolve('anilist:'+str(record['media_id']), metadata(record['metadata_json']))
        if entity: self._open_hub_entity(entity)
