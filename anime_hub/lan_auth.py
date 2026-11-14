"""Revocable local pairing. Persist digests, never bearer tokens or pairing codes."""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time
from pathlib import Path

SESSION_SECONDS = 90 * 24 * 60 * 60


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def local_address(value):
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and any(address in ipaddress.ip_network(n) for n in
            ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16'))
    except ValueError:
        return False


class PairingStore:
    def __init__(self, path, log=lambda message: None):
        self.path = Path(path)
        self.log = log
        self.lock = threading.RLock()
        self.devices = {}
        self.pairing = None
        self.attempts = {}
        self.restricted_open = False
        self.available = True
        self.epoch = secrets.token_hex(16)  # Restricted grants never survive restart.
        if self.path.exists():
            try:
                devices = json.loads(self.path.read_text(encoding='utf-8'))['devices']
                if not isinstance(devices, dict) or len(devices) > 64:
                    raise ValueError
                for identity, record in devices.items():
                    if not isinstance(record, dict) or record.get('id') != identity or not isinstance(record.get('digest'), str) or len(record['digest']) != 64:
                        raise ValueError
                    # Additive V1.1 upgrade: no token rotation, fixed expiry from original pairing.
                    record.setdefault('expires_at', int(record['paired_at']) + SESSION_SECONDS)
                self.devices = devices
            except (OSError, ValueError, KeyError, TypeError):
                self.available = False
                self.log('LAN device store unreadable; server disabled, original file preserved')

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def _save(self):
        if not self.available:
            raise APIError(503, 'device_store_unavailable')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump({'devices': self.devices}, output)
        os.replace(temp, self.path)

    def new_code(self):
        with self.lock:
            if not self.available:
                raise APIError(503, 'device_store_unavailable')
            code = f'{secrets.randbelow(100000000):08d}'
            self.pairing = (self.digest(code), time.monotonic() + 120)
            self.log('LAN pairing window opened; expires in 120 seconds')
            return code

    def pair(self, code, name, peer, existing_token=None):
        with self.lock:
            now = time.monotonic()
            # One global budget prevents bypassing a code limit with multiple LAN IPs.
            attempts = self.attempts.setdefault('global', [])
            attempts[:] = [t for t in attempts if now - t < 60]
            if len(attempts) >= 5:
                raise APIError(429, 'pairing_rate_limited')
            attempts.append(now)
            if not isinstance(code, str) or not self.pairing or now > self.pairing[1] or not hmac.compare_digest(self.digest(code), self.pairing[0]):
                raise APIError(401, 'invalid_or_expired_pairing_code')
            existing=None
            if existing_token:
                try:existing=self.authenticate(existing_token)
                except APIError:pass
            if len(self.devices) >= 64 and not existing:
                raise APIError(409, 'revoke_unused_device')
            token = existing_token if existing else secrets.token_urlsafe(32)
            identity = existing or secrets.token_hex(12)
            if existing:
                record=self.devices[identity]
                record['name']=str(name).strip()[:64] or record['name']
                self._save();self.pairing=None
                return {'device_id':identity,'token':token,'expires_at':record['expires_at']}
            self.devices[identity] = {'id': identity, 'name': str(name).strip()[:64] or 'LAN device',
                'digest': self.digest(token), 'paired_at': int(time.time()), 'expires_at':int(time.time())+SESSION_SECONDS, 'restricted_epoch': None}
            self._save()
            self.pairing = None
            self.log('LAN device paired: ' + identity)
            return {'device_id': identity, 'token': token,'expires_at':self.devices[identity]['expires_at']}

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) > 256:
            raise APIError(401, 'authentication_required')
        digest = self.digest(token)
        with self.lock:
            for identity, record in self.devices.items():
                if hmac.compare_digest(digest, record['digest']):
                    if time.time()>=record['expires_at']:raise APIError(401,'session_expired')
                    record['last_seen_at']=int(time.time())
                    return identity
        raise APIError(401, 'authentication_required')

    def check(self, identity, scope):
        with self.lock:
            record = self.devices.get(identity)
            if record is None:
                raise APIError(401, 'device_revoked')
            if time.time()>=record['expires_at']:raise APIError(401,'session_expired')
            if scope == 'restricted' and (not self.restricted_open or record.get('restricted_epoch') != self.epoch):
                raise APIError(403, 'restricted_authorization_required')

    def set_open(self, opened):
        with self.lock:
            self.restricted_open = bool(opened)

    def lock_archive(self):
        with self.lock:
            self.restricted_open = False
            self.epoch = secrets.token_hex(16)
            self.log('LAN Restricted grants invalidated')

    def grant(self, identity):
        with self.lock:
            if not self.restricted_open:
                raise APIError(403, 'restricted_locked')
            if identity not in self.devices:
                raise APIError(404, 'device_not_found')
            self.devices[identity]['restricted_epoch'] = self.epoch
            self._save()
            self.log('LAN Restricted grant: ' + identity)

    def revoke(self, identity):
        with self.lock:
            self.devices.pop(identity, None)
            self._save()
            self.log('LAN device revoked: ' + identity)

    def listing(self):
        with self.lock:
            return [{k: v for k, v in row.items() if k not in {'digest', 'restricted_epoch'}} for row in self.devices.values()]
