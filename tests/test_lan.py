import hashlib
import http.client
import json
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QCoreApplication
from anime_hub.database import Database
from anime_hub.lan_auth import APIError, PairingStore, local_address
from anime_hub.lan_catalog import Catalog, snapshot
from anime_hub.lan_desktop import DesktopServer, apply_state
from anime_hub.lan_server import LANServer, byte_range
from anime_hub.manga_library import MangaStore


class WindowStub:
    def __init__(self, db, manga):
        self.db, self.manga_store, self.db_path = db, manga, db.path
        self._closing = False
        self._library_cache_dirty = False
        self.synced = []
        self.manual_status_changed = SimpleNamespace(emit=lambda *args: None)

    def _invalidate_discover_page_cache(self, scope):
        pass

    def _maybe_sync_anilist_progress(self, *args, **kwargs):
        self.synced.append((args, kwargs))


@pytest.fixture
def vault(tmp_path):
    db = Database(tmp_path / 'vault.db')
    manga = MangaStore(db)
    ids = []
    art = tmp_path / 'cache' / 'artwork'
    art.mkdir(parents=True)
    for adult in (False, True):
        folder = tmp_path / ('Secret' if adult else 'Show')
        folder.mkdir()
        aid = db.upsert_anime(str(adult), folder.name, '', 'Other', str(folder), folder.name, folder.name)
        poster = art / (folder.name + '.png')
        poster.write_bytes(b'private-poster' if adult else b'public-poster')
        db.set_metadata(aid, 11 if adult else 10, {'id': 11 if adult else 10,
            'title': {'english': folder.name}, 'isAdult': adult, 'cover_path': str(poster),
            'relations': {'edges': [{'node': {'title': 'SHOULD_NOT_LEAK'}}]}})
        for i in (1, 2):
            path = folder / f'{i}.mp4'
            path.write_bytes(bytes(range(256)) * 256)
            db.upsert_media(aid, SimpleNamespace(path=path, kind='episode', season=1, episode=i))
        db.connection.commit()
        ids.append(aid)
    root = tmp_path / 'Manga'
    root.mkdir()
    rid = manga.add_root(root)
    db.connection.execute('INSERT INTO manga_series(identity,title,root_path,root_id,scope) VALUES(?,?,?,?,?)', ('m', 'Book', str(root), rid, 'normal'))
    sid = db.connection.execute('SELECT id FROM manga_series').fetchone()[0]
    path = root / 'v1.cbz'
    path.write_bytes(b'archive')
    db.connection.execute('INSERT INTO manga_items(series_id,path,path_key,source_type,display_name,reader_identity) VALUES(?,?,?,?,?,?)', (sid, str(path), str(path), 'cbz', 'Volume 1', 'reader1'))
    db.connection.commit()
    auth = PairingStore(tmp_path / 'devices.json')
    token = auth.pair(auth.new_code(), 'test', '127.0.0.1')
    window = WindowStub(db, manga)
    def mutate(identity, scope, route, body, guard):
        # Network tests do not mutate SQLite off-thread; DesktopServer integration below covers writes.
        raise APIError(503, 'use_desktop_bridge')
    logs = []
    server = LANServer(db.path, tmp_path, auth, mutate, logs.append)
    server.start('127.0.0.1', 0)
    yield SimpleNamespace(db=db, manga=manga, auth=auth, token=token, server=server,
        tmp=tmp_path, normal=ids[0], secret=ids[1], sid=sid, window=window, logs=logs)
    server.stop()
    db.connection.close()


def request(vault, path='/api/v1/anime', method='GET', body=None, headers=None, authenticated=True):
    port = vault.server.http.server_address[1]
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    hdr = {'Authorization': 'Bearer ' + vault.token['token']} if authenticated else {}
    if headers:
        hdr.update(headers)
    if body is not None:
        body = json.dumps(body)
        hdr['Content-Type'] = 'application/json'
    connection.request(method, path, body, hdr)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


@pytest.mark.parametrize('route', ['info', 'library', 'anime', 'manga', 'favorites', 'collections', 'statuses', 'continue-watching', 'continue-reading', 'recently-added', 'progress', 'franchises'])
def test_read_endpoints_are_scoped(vault, route):
    status, headers, payload = request(vault, '/api/v1/' + route)
    assert status == 200
    assert b'Secret' not in payload and b'cover_path' not in payload and b'root_path' not in payload
    assert b'SHOULD_NOT_LEAK' not in payload
    assert str(vault.tmp).encode() not in payload
    json.loads(payload)


def test_details_and_safe_artwork(vault):
    for kind, identity in [('anime', vault.normal), ('manga', vault.sid)]:
        assert request(vault, f'/api/v1/{kind}/{identity}')[0] == 200
    assert request(vault, f'/api/v1/anime/{vault.normal}/artwork/poster')[2] == b'public-poster'
    assert request(vault, f'/api/v1/anime/{vault.secret}')[0] == 404
    assert request(vault, f'/api/v1/anime/{vault.secret}/artwork/poster')[0] == 404
    db = vault.db
    info = json.loads(db.anime(vault.normal)['metadata_json'])
    info['cover_path'] = str(db.path)
    db.set_metadata(vault.normal, 10, info)
    assert request(vault, f'/api/v1/anime/{vault.normal}/artwork/poster')[0] == 404


def test_shared_private_artwork_is_blocked(vault):
    secret = json.loads(vault.db.anime(vault.secret)['metadata_json'])
    normal = json.loads(vault.db.anime(vault.normal)['metadata_json'])
    normal['cover_path'] = secret['cover_path']
    vault.db.set_metadata(vault.normal, 10, normal)
    assert request(vault, f'/api/v1/anime/{vault.normal}/artwork/poster')[0] == 404


@pytest.mark.parametrize('headers,authenticated', [({}, False), ({'Authorization': 'Bearer invalid'}, True), ({'Origin': 'https://evil.example'}, True), ({'Host': 'evil.example'}, True), ({'X-Forwarded-For': '127.0.0.1'}, True)])
def test_auth_and_browser_boundaries(vault, headers, authenticated):
    assert request(vault, headers=headers, authenticated=authenticated)[0] in {401, 403}


def test_restricted_grant_lock_restart_and_revoke(vault):
    route = f'/api/v1/restricted/anime/{vault.secret}'
    assert request(vault, route)[0] == 403
    vault.auth.set_open(True)
    vault.auth.grant(vault.token['device_id'])
    assert request(vault, route)[0] == 200
    vault.auth.lock_archive()
    vault.auth.set_open(True)
    assert request(vault, route)[0] == 403
    reloaded = PairingStore(vault.auth.path)
    assert reloaded.authenticate(vault.token['token']) == vault.token['device_id']
    with pytest.raises(APIError):
        reloaded.check(vault.token['device_id'], 'restricted')
    assert vault.token['token'] not in vault.auth.path.read_text()
    vault.auth.revoke(vault.token['device_id'])
    assert request(vault)[0] == 401


def test_pairing_endpoint_cookie_and_limits(vault):
    code = vault.auth.new_code()
    status, headers, body = request(vault, '/pair', 'POST', {'code': code, 'name': 'Phone'}, authenticated=False)
    assert status == 200 and 'HttpOnly' in headers['Set-Cookie']
    assert request(vault, authenticated=False, headers={'Cookie': headers['Set-Cookie'].split(';')[0]})[0] == 200
    assert request(vault, '/pair', 'POST', {'code': code}, authenticated=False)[0] == 401
    for i in range(5):
        status = request(vault, '/pair', 'POST', {'code': 'wrong'}, authenticated=False)[0]
    assert status == 429
    assert vault.token['token'] not in '\n'.join(vault.logs)


@pytest.mark.parametrize('value,expected', [('bytes=3-9', (3, 9)), ('bytes=100-', (100, 65535)), ('bytes=-10', (65526, 65535)), ('bytes=0-999999', (0, 65535))])
def test_network_ranges_and_source_unchanged(vault, value, expected):
    row = vault.db.media(vault.normal)[0]
    path = Path(row['path'])
    original = path.read_bytes()
    before = path.stat().st_mtime_ns
    status, headers, body = request(vault, f'/api/v1/media/{row["id"]}', headers={'Range': value})
    assert status == 206
    start, end = expected
    assert body == original[start:end + 1]
    assert headers['Content-Range'] == f'bytes {start}-{end}/{len(original)}'
    assert int(headers['Content-Length']) == len(body)
    assert path.read_bytes() == original and path.stat().st_mtime_ns == before


@pytest.mark.parametrize('value', ['bytes=999999-', 'bytes=10-2', 'bytes=-0', 'bytes=0-1,3-4', 'items=0-1', 'bytes=a-b'])
def test_invalid_ranges(vault, value):
    row = vault.db.media(vault.normal)[0]
    status, headers, _ = request(vault, f'/api/v1/media/{row["id"]}', headers={'Range': value})
    assert status == 416 and headers['Content-Range'] == 'bytes */65536'


def test_head_missing_and_restricted_media(vault):
    normal = vault.db.media(vault.normal)[0]
    secret = vault.db.media(vault.secret)[0]
    status, headers, body = request(vault, f'/api/v1/media/{normal["id"]}', 'HEAD')
    assert status == 200 and len(body) == 0 and int(headers['Content-Length']) == 65536
    assert request(vault, f'/api/v1/media/{secret["id"]}')[0] == 404
    Path(normal['path']).unlink()
    assert request(vault, f'/api/v1/media/{normal["id"]}')[0] == 404
    assert request(vault, '/api/v1/media/../../vault.db')[0] == 404
    assert request(vault, '/api/v1/media/1?token=secret')[0] == 400


def test_read_only_snapshot(vault):
    with snapshot(vault.db.path) as (db, manga):
        with pytest.raises(Exception, match='readonly'):
            db.set_setting('injected', '1')
    assert vault.db.setting('injected') == ''


def test_progress_business_rules(vault):
    media = vault.db.media(vault.normal)
    route = ['media', str(media[1]['id']), 'progress']
    apply_state(vault.window, vault.tmp, 'normal', route, {'watched': True, 'automatic': True})
    assert vault.db.anime_progress(vault.normal)[0] == 2
    assert vault.window.synced[-1][1]['allow_decrease'] is False
    with pytest.raises(APIError):
        apply_state(vault.window, vault.tmp, 'normal', route, {'watched': False, 'automatic': True})
    apply_state(vault.window, vault.tmp, 'normal', route, {'watched': False, 'position_ms': 1234})
    assert vault.db.anime_progress(vault.normal)[0] == 1
    assert vault.window.synced[-1][1]['allow_decrease'] is True
    assert vault.db.media_by_id(media[1]['id'])['resume_position_ms'] == 1234
    with pytest.raises(APIError):
        apply_state(vault.window, vault.tmp, 'normal', ['media', str(vault.db.media(vault.secret)[0]['id']), 'progress'], {'watched': True})


def test_manga_state_and_favorites(vault):
    iid = vault.manga.items(vault.sid)[0]['id']
    route = ['manga-items', str(iid), 'progress']
    apply_state(vault.window, vault.tmp, 'normal', route, {'page': 5, 'total_pages': 10, 'finished': True})
    apply_state(vault.window, vault.tmp, 'normal', route, {'page': 2, 'total_pages': 10, 'finished': False})
    item = vault.manga.items(vault.sid)[0]
    assert item['current_page'] == 2 and item['completed'] == 0
    apply_state(vault.window, vault.tmp, 'normal', route, {'page': 1, 'total_pages': 10, 'automatic': True})
    assert vault.manga.items(vault.sid)[0]['current_page'] == 2
    for kind, identity in [('anime', vault.normal), ('manga', vault.sid)]:
        apply_state(vault.window, vault.tmp, 'normal', [kind, str(identity), 'favorite'], {'favorite': True})
        apply_state(vault.window, vault.tmp, 'normal', [kind, str(identity), 'status'], {'status': 'Planning'})
    assert len(json.loads(request(vault, '/api/v1/favorites')[2])) == 2
    assert len(json.loads(request(vault, '/api/v1/statuses')[2])['Planning']) == 2


def test_bind_stop_restart(vault):
    port = vault.server.http.server_address[1]
    vault.server.stop()
    with pytest.raises(OSError):
        socket.create_connection(('127.0.0.1', port), .3)
    vault.server.start('127.0.0.1', port)
    assert request(vault)[0] == 200
    for address in ['0.0.0.0', '8.8.8.8', '::', '192.0.2.1']:
        with pytest.raises(ValueError):
            vault.server.start(address, 8765)


def test_desktop_bridge_owns_database_thread(vault):
    from PySide6.QtCore import QObject
    class Owner(QObject):
        def __init__(self):
            QObject.__init__(self)
            WindowStub.__init__(self, vault.db, vault.manga)
            self.player_page = self.manga_reader_page = None
            self.current_view = 'test'
        _invalidate_discover_page_cache = WindowStub._invalidate_discover_page_cache
        _maybe_sync_anilist_progress = WindowStub._maybe_sync_anilist_progress
    owner = Owner()
    service = DesktopServer(owner, vault.tmp, vault.logs.append)
    service.server = vault.server
    vault.server.auth = service.auth
    vault.token = service.auth.pair(service.auth.new_code(), 'Bridge client', '127.0.0.1')
    vault.server.mutate = service.submit
    media = vault.db.media(vault.normal)[0]
    result = []
    worker = threading.Thread(target=lambda: result.append(request(vault, f'/api/v1/media/{media["id"]}/progress', 'PUT', {'position_ms': 555})))
    worker.start()
    deadline = time.monotonic() + 4
    while worker.is_alive() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(.01)
    worker.join(1)
    assert result and result[0][0] == 200
    assert vault.db.media_by_id(media['id'])['resume_position_ms'] == 555
    service.shutdown()


@pytest.mark.parametrize('extension', ['mp4', 'mkv'])
def test_generated_video_direct_play_and_seeks(vault, extension):
    import subprocess
    import imageio_ffmpeg
    binary = imageio_ffmpeg.get_ffmpeg_exe()
    row = vault.db.media(vault.normal)[0]
    path = Path(row['path']).with_suffix('.' + extension)
    subprocess.run([binary, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
        'testsrc=size=160x90:rate=10', '-t', '2', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p', str(path)], check=True, timeout=30)
    vault.db.connection.execute('UPDATE media SET path=? WHERE id=?', (str(path), row['id']))
    vault.db.connection.commit()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    status, headers, body = request(vault, f'/api/v1/media/{row["id"]}')
    assert status == 200 and body == path.read_bytes()
    assert headers['Content-Type'] == ('video/mp4' if extension == 'mp4' else 'video/x-matroska')
    received = vault.tmp / ('received.' + extension)
    received.write_bytes(body)
    subprocess.run([binary, '-hide_banner', '-loglevel', 'error', '-i', str(received), '-f', 'null', '-'], check=True, timeout=30)
    for start in [len(body) // 2, 0, len(body) - 32, 100]:
        status, _, result = request(vault, f'/api/v1/media/{row["id"]}', headers={'Range': f'bytes={start}-{start + 31}'})
        assert status == 206 and result == body[start:start + 32]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_large_file_range_does_not_load_whole_file(vault):
    row = vault.db.media(vault.normal)[0]
    path = Path(row['path'])
    # Sparse on supported filesystems; no huge byte buffer is allocated.
    size = 2 * 1024**3 + 17
    with path.open('wb') as output:
        output.write(b'first')
        output.seek(size - 4)
        output.write(b'last')
    status, headers, body = request(vault, f'/api/v1/media/{row["id"]}', headers={'Range': 'bytes=-4'})
    assert status == 206 and body == b'last'
    assert headers['Content-Range'] == f'bytes {size - 4}-{size - 1}/{size}'
    assert request(vault, f'/api/v1/media/{row["id"]}', headers={'Range': 'bytes=0-4'})[2] == b'first'


def test_real_window_settings_and_http_progress(window, tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel
    w, qt, aid, *_ = window
    w.show_settings()
    assert w.stack.currentWidget().findChild(QLabel, 'lanStatus')
    assert w.lan_server.server.http is None
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    w.lan_server.start('127.0.0.1', port)
    for _ in range(100):
        QTest.qWait(20)
        if w.lan_server.server.http and not w.lan_server.busy:
            break
    assert w.lan_server.server.http
    token = w.lan_server.auth.pair(w.lan_server.auth.new_code(), 'Phone', '127.0.0.1')
    probe = SimpleNamespace(server=w.lan_server.server, token=token)
    media = w.db.media(aid)[0]
    responses = []
    thread = threading.Thread(target=lambda: responses.append(request(probe, f'/api/v1/media/{media["id"]}/progress', 'PUT', {'position_ms': 789})))
    thread.start()
    for _ in range(200):
        QTest.qWait(10)
        if not thread.is_alive():
            break
    thread.join(1)
    assert responses[0][0] == 200
    assert w.db.media_by_id(media['id'])['resume_position_ms'] == 789
    w.lan_server.stop()
    for _ in range(100):
        QTest.qWait(20)
        if not w.lan_server.busy:
            break
    assert w.db.setting('lan_enabled') == '0' and w.lan_server.server.http is None


from test_cross_media import window


def test_corrupt_device_store_is_preserved(tmp_path):
    path = tmp_path / 'lan-devices.json'
    path.write_bytes(b'broken-private-store')
    auth = PairingStore(path)
    assert not auth.available
    with pytest.raises(APIError):
        auth.new_code()
    assert path.read_bytes() == b'broken-private-store'


def test_revocation_interrupts_started_stream(vault):
    original = vault.server.check
    calls = []
    def guard(http, identity, scope):
        calls.append(1)
        if len(calls) == 3:
            vault.auth.revoke(identity)
        return original(http, identity, scope)
    vault.server.check = guard
    row = vault.db.media(vault.normal)[0]
    with pytest.raises(http.client.IncompleteRead) as stopped:
        request(vault, f'/api/v1/media/{row["id"]}')
    assert len(stopped.value.partial) < 65536
