"""Reversible retirement, based only on complete readable filesystem snapshots."""
import os
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from .parser import VIDEO_EXTS, AUDIO_EXTS, IMAGE_EXTS


class ScanCancelled(Exception):
    pass


class ScanChanged(OSError):
    pass


@lru_cache(maxsize=512)
def _image_valid(path,size,modified):
    from PIL import Image
    try:
        with Image.open(path) as image:image.verify()
        return True
    except (OSError,ValueError):return False


def artwork_status(item):
    import re
    path=item.get('cover_path')
    if path:
        manual=not re.match(r'^\d+_cover_path\.',Path(path).name)
        try:
            info=Path(path).stat()
            valid=_image_valid(str(path),info.st_size,info.st_mtime_ns)
        except OSError:valid=False
        return ('Manual artwork' if valid else 'Manual artwork needs review') if manual else 'Available' if valid else 'Invalid cached artwork'
    if not item.get('id'):return 'No identity'
    return 'Download pending' if (item.get('coverImage') or {}).get('large') or (item.get('coverImage') or {}).get('extraLarge') else 'Missing artwork URL'


def inventory(root, cancelled=lambda: False):
    root=Path(root)
    # stat/iterdir must raise, rather than interpreting inaccessible as empty.
    if not root.is_dir():raise OSError('Library root is unavailable')
    found={}
    def error(exc):raise exc
    for folder,dirs,files in os.walk(root,followlinks=False,onerror=error):
        if cancelled():raise ScanCancelled()
        base=Path(folder)
        # Symlinks/junctions need a separately configured root; never retire their targets.
        if any((base/d).is_symlink() or (hasattr(os.path,'isjunction') and os.path.isjunction(base/d)) for d in dirs):
            raise OSError('Linked library directories require a separate source root')
        info=base.stat();found[str(base)]=(info.st_dev,info.st_ino)
        for name in files:
            p=base/name
            if p.suffix.lower() in VIDEO_EXTS|AUDIO_EXTS|IMAGE_EXTS:
                info=p.stat();found[str(p)]=(info.st_dev,info.st_ino,info.st_size)
    if cancelled():raise ScanCancelled()
    if not root.is_dir():raise OSError('Library root became unavailable')
    return found


def within(path, root):
    try:return os.path.commonpath([os.path.normcase(os.path.abspath(path)),os.path.normcase(os.path.abspath(root))])==os.path.normcase(os.path.abspath(root))
    except ValueError:return False


def complete(db,root,touched,snapshot):
    now=datetime.now(timezone.utc).isoformat();touched=set(touched)
    previous=db.connection.execute('SELECT generation FROM scan_root_health WHERE root=?',(str(root),)).fetchone()
    generation=(previous[0] if previous else 0)+1
    retired=0
    for row in db.connection.execute('SELECT * FROM anime').fetchall():
        if not within(row['root_path'],root):continue
        present=db.connection.execute("SELECT 1 FROM media WHERE anime_id=? AND present=1 AND kind<>'ignore' LIMIT 1",(row['id'],)).fetchone()
        active=int(row['id'] in touched and bool(present))
        files=[tuple(r) for r in db.connection.execute('SELECT path,file_identity,size_bytes,kind,season,episode FROM media WHERE anime_id=? AND present=1 ORDER BY path',(row['id'],))]
        stamp=hashlib.sha256(json.dumps(files).encode()).hexdigest()
        status=('Changed' if row['source_stamp'] and row['source_stamp']!=stamp else 'Present') if active else 'Container' if row['root_path'] in snapshot else 'Missing'
        if active and row['last_successful_scan']:
            old=db.connection.execute('SELECT root_path FROM scan_source_history WHERE anime_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            status='Relocated' if old and old[0]!=row['root_path'] else 'Changed' if row['availability']=='Missing' else status
        if row['active'] and not active:retired+=1
        db.connection.execute('UPDATE anime SET active=?,availability=?,last_successful_scan=?,scan_generation=?,source_identity=COALESCE(?,source_identity),source_stamp=? WHERE id=?',(active,status,now,generation,('%s:%s'%snapshot[row['root_path']][:2]) if isinstance(snapshot.get(row['root_path']),tuple) else None,stamp,row['id']))
        db.connection.execute('INSERT INTO scan_source_history(anime_id,root_path,availability,generation) VALUES(?,?,?,?)',(row['id'],row['root_path'],status,generation))
        if not active:
            db.connection.execute("UPDATE metadata_jobs SET state='completed',outcome='retired',revision=revision+1,owner=NULL,lease_until=0 WHERE anime_id=? AND outcome<>'retired'",(row['id'],))
    db.connection.execute("INSERT INTO scan_root_health(root,generation,status,indexed,retired,updated) VALUES(?,?,'Complete',?,?,?) ON CONFLICT(root) DO UPDATE SET generation=excluded.generation,status=excluded.status,indexed=excluded.indexed,retired=excluded.retired,updated=excluded.updated",(str(root),generation,len(touched),retired,now))
    return retired


def unavailable(db,root,status):
    # Availability is diagnostic only: do not alter active flags or media presence.
    with db.connection:
        for row in db.connection.execute('SELECT id,root_path FROM anime').fetchall():
            if within(row['root_path'],root):db.connection.execute('UPDATE anime SET availability=? WHERE id=?',(status,row['id']))
        db.connection.execute("INSERT INTO scan_root_health(root,status) VALUES(?,?) ON CONFLICT(root) DO UPDATE SET status=excluded.status",(str(root),status))


def health(db,scope='normal'):
    rows=[r for r in db.anime_list(include_retired=True) if db.anime_scope(r,fresh=False)==scope]
    from .scan_state import safe_json,source_state
    active=[r for r in rows if r['active']]
    art=[]
    for r in active:
        item=safe_json(r['metadata_json'])
        art.append(artwork_status(item))
    ids=[r['anilist_id'] for r in active if r['anilist_id']]
    return {'active':len(active),'unmatched':sum(not r['anilist_id'] for r in active),'ambiguous':sum(source_state(db,r['id'])['state']=='Needs Review' for r in active),'missing_artwork':sum(a not in {'Available','Manual artwork'} for a in art),'suspected_duplicates':len(ids)-len(set(ids)),'missing_sources':sum(r['availability']=='Missing' for r in rows),'unavailable_sources':sum(r['availability']=='Source unavailable' for r in rows),'retired':sum(not r['active'] for r in rows)}
