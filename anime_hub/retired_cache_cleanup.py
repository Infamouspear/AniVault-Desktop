"""Explicit, conservative verification/quarantine of the retired generated index.

Never called on startup/navigation. Never deletes files or touches anime_hub.db.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

_TABLES = {'galleries','terms','search','search_data','search_idx','search_content',
           'search_docsize','search_config','sqlite_stat1','sqlite_stat4'}
_FIELDS = {'source','external_id','title','url','cover_url','page_count','tags',
           'upload_date','metadata_provider','category','source_upload_date'}


def _target(app_dir):
    path = Path(app_dir) / 'doujin_index.db'
    if path.is_symlink():raise ValueError('Refusing a symlinked cache')
    return path


def _signature(path):
    st = path.stat()
    return (st.st_size,st.st_mtime_ns,st.st_ino)


def inspect_retired_cache(app_dir):
    path = _target(app_dir)
    if not path.exists():return {'present':False}
    before = _signature(path)
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Cache has active SQLite sidecar files; close the older app first')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'galleries','terms','search'} <= tables or tables - _TABLES:
            raise ValueError('Unexpected schema; cannot prove this is only a generated cache')
        for table,columns in (('galleries',{'external_id','title','upload_date','metadata'}),
                              ('terms',{'field','value','external_id'}),
                              ('search',{'title','tag','artist','group','parody','character','language'})):
            if {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')} != columns:
                raise ValueError('Unexpected cache columns; leaving the file untouched')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Cache integrity could not be verified')
        records = 0
        for external_id,metadata in db.execute('SELECT external_id,metadata FROM galleries'):
            item = json.loads(metadata)
            if (not isinstance(item,dict) or set(item)-_FIELDS or item.get('source')!='nhentai'
                    or str(item.get('external_id'))!=str(external_id)):
                raise ValueError('Unexpected/user-owned fields detected; leaving the file untouched')
            records += 1
    if _signature(path) != before:raise ValueError('Cache changed during verification')
    return {'present':True,'signature':before,'records':records,'bytes':before[0]}


def quarantine_retired_cache(app_dir,verified):
    path = _target(app_dir)
    if not verified.get('present') or _signature(path) != tuple(verified['signature']):
        raise ValueError('Cache changed after verification; nothing was moved')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Cache is active; nothing was moved')
    parent = Path(app_dir) / 'retired-source-cache'
    if parent.is_symlink():raise ValueError('Refusing a symlinked quarantine directory')
    parent.mkdir(exist_ok=True)
    folder = parent / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir()
    os.rename(path,folder/path.name)
    # Status sidecar is small; preserve it in place rather than assume it is disposable.
    return folder
