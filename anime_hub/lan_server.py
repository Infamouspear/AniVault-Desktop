"""Bounded LAN HTTP server. No arbitrary path routes, URL tokens, proxies or CORS."""
import json
import mimetypes
import socket
import threading
import time
from email.utils import formatdate
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .lan_auth import APIError, local_address
from .lan_catalog import Catalog, snapshot
from .version import APP_VERSION


def addresses():
    values = {'127.0.0.1'}
    try:
        values.update(r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted((v for v in values if local_address(v)), key=lambda v: (v.startswith('127.'), v))


def session_cookie(token, expires_at):
    remaining=max(0,int(expires_at-time.time()))
    return f'anivault_token={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={remaining}; Expires={formatdate(expires_at,usegmt=True)}'


def byte_range(value, size):
    if value is None:
        return 0, size - 1, False
    try:
        if not value.startswith('bytes=') or ',' in value or size == 0:
            raise ValueError
        first, last = value[6:].split('-', 1)
        if not first:
            if not last.isdecimal() or int(last) <= 0:
                raise ValueError
            start, end = max(0, size - int(last)), size - 1
        else:
            if not first.isdecimal() or (last and not last.isdecimal()):
                raise ValueError
            start, end = int(first), min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            raise ValueError
        return start, end, True
    except (ValueError, OverflowError):
        raise APIError(416, 'invalid_range')


from .lan_probe import HTML as PROBE, JS as PROBE_JS


class BoundedServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits a second listener to steal an occupied port.
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, handler)

    def verify_request(self, request, address):
        return local_address(address[0])

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        self.owner.log('LAN request failed')  # Never print request/auth headers.


class LANServer:
    def __init__(self, db_path, data_dir, auth, mutate, log=lambda message: None):
        self.db_path, self.data_dir, self.auth = db_path, data_dir, auth
        self.mutate, self.log = mutate, log
        self.http = None
        self.thread = None
        self.lock = threading.RLock()
        self.generation = 0
        self.state = 'Stopped'
        self.last_error = ''

    def status_info(self):
        with self.lock:
            if self.state=='Running' and (not self.http or not self.thread or not self.thread.is_alive()):
                return {'state':'Error','address':'','error':'Server worker stopped unexpectedly'}
            return {'state':self.state,'address':self.url,'error':self.last_error}

    def _serve(self, http):
        try:
            http.serve_forever(poll_interval=.1)
        except Exception:
            self.log('LAN worker stopped unexpectedly')
        finally:
            with self.lock:
                if self.http is http:
                    self.http=None;self.generation+=1;self.state='Error'
                    self.last_error='Server worker stopped unexpectedly; restart the server'
                    self.auth.lock_archive()
            http.server_close()

    @property
    def url(self):
        with self.lock:
            return f'http://{self.http.server_address[0]}:{self.http.server_address[1]}' if self.http else ''

    def start(self, host, port):
        if not self.auth.available:
            raise ValueError('Paired-device store is unreadable; original file retained')
        if not local_address(host) or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Choose a local/private IPv4 address and a valid port')
        with self.lock:
            if self.http:
                raise ValueError('Server is already running')
            self.state='Starting';self.last_error=''
            try:
                http = BoundedServer((host, port), Handler)
            except OSError as exc:
                self.state='Error'
                number=getattr(exc,'winerror',None) or exc.errno
                self.last_error= ('Port already in use; choose another port' if number in {10048,98,48} else
                    'Address is unavailable on this PC; select a current LAN address' if number in {10049,99,49} else
                    'Windows denied the bind; check private-network firewall permissions' if number in {10013,13} else 'Could not bind the selected address and port')
                self.log('LAN bind failed')
                raise
            self.generation += 1
            http.owner, http.generation = self, self.generation
            self.http = http
            self.thread = threading.Thread(target=self._serve, args=(http,), daemon=True, name='AniVault-LAN')
            self.thread.start()
            self.state='Running'
            self.log('LAN server started')

    def stop(self):
        with self.lock:
            self.state='Stopping'
            http, self.http = self.http, None
            self.generation += 1
            self.auth.pairing = None
            self.auth.lock_archive()
        if http:
            http.shutdown()
            http.server_close()
            self.log('LAN server stopped')
        with self.lock:self.state='Stopped';self.last_error=''

    def check(self, http, identity, scope):
        if self.http is not http or self.generation != http.generation:
            raise APIError(503, 'server_stopped')
        self.auth.check(identity, scope)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'AniVault'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_api()

    def do_HEAD(self):
        self.handle_api()

    def do_POST(self):
        self.handle_api()

    def do_PUT(self):
        self.handle_api()

    def send_data(self, status, data, content_type='application/json', headers=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header('Connection', 'close')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        if self.command != 'HEAD':
            self.wfile.write(data)

    def body(self):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise APIError(400, 'content_length_required')
        try:
            length = int(self.headers['Content-Length'])
            if not 0 < length <= 16384:
                raise APIError(413, 'body_too_large')
            if self.headers.get_content_type() != 'application/json':
                raise APIError(415, 'json_required')
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError):
            raise APIError(400, 'invalid_json')

    def token(self):
        header = self.headers.get('Authorization', '')
        if header:
            if not header.startswith('Bearer '):
                raise APIError(401, 'authentication_required')
            token = header[7:]
        else:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                token = cookie['anivault_token'].value
            except (KeyError, ValueError):
                raise APIError(401, 'authentication_required')
        return token

    def authenticate(self):
        return self.server.owner.auth.authenticate(self.token())

    def handle_api(self):
        owner = self.server.owner
        self.close_connection = True
        try:
            host = f'{self.server.server_address[0]}:{self.server.server_address[1]}'
            if self.headers.get('Host') != host or len(self.headers.get_all('Host', [])) != 1:
                raise APIError(403, 'invalid_host')
            if self.headers.get('Origin') not in (None, 'http://' + host) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise APIError(403, 'cross_origin_denied')
            if any(self.headers.get(h) for h in ('Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host')):
                raise APIError(403, 'proxy_denied')
            parsed = urlsplit(self.path)
            if parsed.query or parsed.scheme or parsed.netloc or '%' in parsed.path or '//' in parsed.path:
                raise APIError(400, 'invalid_route')
            if owner.http is not self.server:
                raise APIError(503, 'server_stopped')
            if parsed.path in {'/', '/probe.js'} and self.command in {'GET', 'HEAD'}:
                return self.send_data(200, (PROBE if parsed.path == '/' else PROBE_JS).encode(),
                    'text/html; charset=utf-8' if parsed.path == '/' else 'text/javascript; charset=utf-8')
            if parsed.path == '/pair' and self.command == 'POST':
                body = self.body()
                try:existing=self.token()
                except APIError:existing=None
                result = owner.auth.pair(body.get('code'), body.get('name', ''), self.client_address[0],existing)
                cookie=session_cookie(result['token'],result['expires_at'])
                return self.send_data(200, result, headers={'Set-Cookie':cookie})
            identity = self.authenticate()
            parts = parsed.path.strip('/').split('/')
            if parts[:2] != ['api', 'v1']:
                raise APIError(404, 'route_not_found')
            route = parts[2:]
            scope = 'restricted' if route[:1] == ['restricted'] else 'normal'
            if scope == 'restricted':
                route = route[1:]
            owner.check(self.server, identity, scope)
            if route==['session'] and self.command in {'GET','HEAD'}:
                record=next(row for row in owner.auth.listing() if row['id']==identity)
                # Upgrade legacy session-only cookies without rotating or extending credentials.
                return self.send_data(200,{'device_id':identity,'name':record['name'],'expires_at':record['expires_at']},headers={'Set-Cookie':session_cookie(self.token(),record['expires_at'])})
            if self.command in {'POST', 'PUT'}:
                body = self.body()
                result = owner.mutate(identity, scope, route, body, lambda: owner.check(self.server, identity, scope))
                owner.check(self.server, identity, scope)
                return self.send_data(200, result)
            with snapshot(owner.db_path) as (db, manga):
                catalog = Catalog(db, manga, scope, owner.data_dir)
                if len(route) == 2 and route[0] == 'media':
                    path = catalog.media_path(int(route[1]))
                    media_id = int(route[1])
                elif len(route) == 4 and route[0] in {'anime', 'manga'} and route[2] == 'artwork':
                    path = catalog.artwork(route[0], int(route[1]), route[3])
                    media_id = None
                else:
                    result = {'name': 'AniVault', 'version': APP_VERSION, 'scope': scope, 'streaming': 'direct', 'transcoding': False} if route == ['info'] else catalog.read(route)
                    owner.check(self.server, identity, scope)
                    return self.send_data(200, result)
            # Close DB snapshot before starting a potentially long file response.
            return self.stream(path, identity, scope, media_id)
        except APIError as exc:
            owner.log(f'LAN API error status={exc.status} code={exc.code}')
            self.send_data(exc.status, {'error': exc.code})
        except (ValueError, TypeError):
            self.send_data(400, {'error': 'invalid_request'})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            owner.log('LAN client disconnected or timed out')
        except Exception:
            owner.log('LAN API internal error')
            self.send_data(500, {'error': 'internal_error'})

    def stream(self, path, identity, scope, media_id):
        owner = self.server.owner
        try:
            source = path.open('rb')
        except OSError:
            raise APIError(404, 'file_unavailable')
        with source:
            size = source.seek(0, 2)
            try:
                if len(self.headers.get_all('Range', [])) > 1:
                    raise APIError(416, 'invalid_range')
                start, end, partial = byte_range(self.headers.get('Range'), size)
            except APIError:
                owner.log('LAN range request rejected')
                return self.send_data(416, {'error': 'invalid_range'}, headers={'Content-Range': f'bytes */{size}'})
            owner.check(self.server, identity, scope)
            self.send_response(206 if partial else 200)
            content_type = {'.mkv': 'video/x-matroska', '.mp4': 'video/mp4', '.m4v': 'video/mp4'}.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(max(0, end - start + 1)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            source.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    owner.check(self.server, identity, scope)
                    if media_id is not None:
                        # Reclassification during a stream cannot bypass the scope boundary.
                        with snapshot(owner.db_path) as (db, manga):
                            if Catalog(db, manga, scope, owner.data_dir).media_path(media_id) != path:
                                raise APIError(403, 'media_changed')
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (APIError, OSError, TimeoutError):
                # Headers have been sent; abort without appending JSON to a media file.
                owner.log('LAN stream interrupted')
