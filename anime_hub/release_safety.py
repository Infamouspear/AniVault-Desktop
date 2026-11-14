"""Non-destructive release preflight. Retain the historical user-data path."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .version import APP_VERSION

def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)

def splash_preferences(path):
    if not Path(path).exists(): return True, 'Standard'
    try:
        with readonly(path) as connection:
            values = dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('show_splash','splash_duration')"))
        return str(values.get('show_splash', '1')) != '0', values.get('splash_duration', 'Standard')
    except (sqlite3.Error, OSError):
        return True, 'Standard'  # Preflight reports the actual database failure.

def prepare_existing_database(path, log):
    """Never recreate corrupt data. SQLite backup includes committed WAL state."""
    path = Path(path)
    if not path.exists():
        log('ReleaseData result=new_install existing_database=false'); return
    marker = path.parent / 'release-state.json'
    with readonly(path) as connection:
        result = connection.execute('PRAGMA quick_check').fetchone()[0]
        if result != 'ok': raise sqlite3.DatabaseError('Database integrity check failed; original database retained.')
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'anime', 'settings'}.issubset(tables):
            raise sqlite3.DatabaseError('Unrecognized existing database; original database retained.')
        try: previous = json.loads(marker.read_text()).get('app_version')
        except (OSError, ValueError): previous = None
        if previous != APP_VERSION:
            folder = path.parent / 'backups'; folder.mkdir(exist_ok=True)
            backup = folder / ('pre-' + APP_VERSION + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.db')
            with sqlite3.connect(backup) as target: connection.backup(target)
            log('ReleaseData result=backup_ready migration=existing_idempotent backup=' + str(backup))
        else: log('ReleaseData result=existing_retained migration=current_release')

def record_release(database, log):
    rows = database.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    fingerprint = hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()
    record = {'app_version': APP_VERSION, 'install_version': APP_VERSION,
              'schema_fingerprint': fingerprint, 'migration_strategy': 'existing_idempotent',
              'last_successful_startup': datetime.now(timezone.utc).isoformat()}
    marker = database.path.parent / 'release-state.json'; temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2)); temporary.replace(marker)
    log('ReleaseVersion app=' + APP_VERSION + ' schema_fingerprint=' + fingerprint)
