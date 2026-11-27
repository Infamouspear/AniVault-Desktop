"""Durable, deduplicated metadata jobs; local indexing never waits on this queue."""
import hashlib,json,os,sqlite3,time
from pathlib import Path
from . import scan_state as state
from .anilist_transport import Deferred,get_scheduler

SCHEMA='''CREATE TABLE IF NOT EXISTS metadata_jobs(
 scope TEXT NOT NULL,target TEXT NOT NULL,operation TEXT NOT NULL,anime_id INTEGER NOT NULL,
 media_id INTEGER,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
 outcome TEXT NOT NULL DEFAULT '',next_at REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1,failed_requests INTEGER NOT NULL DEFAULT 0,owner INTEGER,lease_until REAL NOT NULL DEFAULT 0,updated REAL NOT NULL,
 PRIMARY KEY(scope,target,operation));
 CREATE INDEX IF NOT EXISTS metadata_due ON metadata_jobs(scope,state,next_at);
 CREATE TABLE IF NOT EXISTS metadata_job_metrics(scope TEXT PRIMARY KEY,duration_ms INTEGER NOT NULL DEFAULT 0,last_batch_ms INTEGER NOT NULL DEFAULT 0,batches INTEGER NOT NULL DEFAULT 0);'''
RETRY={'no_match':86400,'ambiguous':86400,'network':60,'timeout':60,'api_unavailable':60,'invalid_response':300,'http_error':900,'artwork':3600}


def migrate(db):
    new_table=not db.connection.execute("SELECT 1 FROM sqlite_master WHERE name='metadata_jobs'").fetchone()
    if new_table and db.connection.execute('SELECT 1 FROM anime LIMIT 1').fetchone():state.backup(db,'pre-metadata-queue')
    db.connection.executescript(SCHEMA)
    if 'failed_requests' not in {r[1] for r in db.connection.execute('PRAGMA table_info(metadata_jobs)')}:
        db.connection.execute('ALTER TABLE metadata_jobs ADD COLUMN failed_requests INTEGER NOT NULL DEFAULT 0');db.connection.commit()
    if new_table:enqueue_existing(db)


def fingerprint(payload,files):
    value={**payload,'files':sorted((r['id'],r['path'],r['season'],r['episode'],r['size_bytes'],(r['file_identity'] if 'file_identity' in r.keys() and r['file_identity'] else r['modified']),r['present']) for r in files)}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def enqueue(db,anime_id,payload,files,*,media_id=None,operation='identify',now=None):
    now=time.time() if now is None else now
    if db.anime_scope(anime_id)!='normal':return False
    source=state.source_state(db,anime_id)
    if operation=='identify' and media_id is None and source['locked']:return False
    if media_id:
        row=db.connection.execute('SELECT locked FROM scan_file_matches WHERE media_id=?',(media_id,)).fetchone()
        if row and row[0]:return False
    target=('media:'+str(media_id)) if media_id else 'anime:'+str(anime_id);stamp=fingerprint(payload,files)
    previous=db.connection.execute("SELECT * FROM metadata_jobs WHERE scope='normal' AND target=? AND operation=?",(target,operation)).fetchone()
    if previous and previous['fingerprint']==stamp and previous['anime_id']==anime_id and previous['outcome']!='retired':return False
    db.connection.execute("""INSERT INTO metadata_jobs(scope,target,operation,anime_id,media_id,fingerprint,payload,updated)
      VALUES('normal',?,?,?,?,?,?,?) ON CONFLICT(scope,target,operation) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,
      anime_id=excluded.anime_id,media_id=excluded.media_id,state='pending',outcome='source_changed',next_at=0,revision=metadata_jobs.revision+1,owner=NULL,lease_until=0,updated=excluded.updated""",
      (target,operation,anime_id,media_id,stamp,json.dumps(payload),now))
    # Import a recent, completed 1.9.0 lookup into the negative cache on upgrade.
    # A later source-fingerprint change creates a fresh revision immediately.
    if previous is None and operation=='identify':
        report=state.safe_json(source['report'])
        if media_id:
            file=db.connection.execute('SELECT report FROM scan_file_matches WHERE media_id=?',(media_id,)).fetchone()
            report=state.safe_json(file[0]) if file else {}
        if isinstance(report,dict) and report.get('query')==payload.get('title') and isinstance(report.get('candidates'),list) and report.get('network_error') is False:
            from datetime import datetime,timezone
            try:checked=datetime.fromisoformat(source.get('updated','')).replace(tzinfo=timezone.utc).timestamp()
            except (ValueError,TypeError):checked=0
            if checked>0 and checked+86400>now:
                outcome='ambiguous' if report['candidates'] else 'no_match'
                db.connection.execute("UPDATE metadata_jobs SET state='unresolved',outcome=?,next_at=? WHERE scope='normal' AND target=? AND operation=?",(outcome,checked+86400,target,operation))
    return True


def independent_file(path,root):
    """Aggregate pack labels never turn each numbered episode into an OVA lookup."""
    from .parser import classify_file,SPECIAL_WORDS,SPECIAL_CODE
    path=Path(path);root=Path(root)
    if SPECIAL_WORDS.search(path.stem) or SPECIAL_CODE.search(path.stem) or __import__('re').search(r'\bmovie\b',path.stem,__import__('re').I):return True
    try:parents=path.relative_to(root).parts[:-1]
    except ValueError:parents=()
    if any(__import__('re').fullmatch(r'NC|NCOP|NCED|openings?|endings?',name,__import__('re').I) for name in parents):return False
    if any(__import__('re').fullmatch(r'(?:ovas?|oads?|movies?|specials?|sps?|extras?)',name,__import__('re').I) for name in parents):return True
    try:relative=path.relative_to(root)
    except ValueError:relative=Path(path.name)
    return classify_file(relative).kind!='episode'


def enqueue_existing(db,identifiers=None):
    added=0
    for row in db.anime_list():
        if identifiers is not None and row['id'] not in identifiers:continue
        if db.anime_scope(row,fresh=False)!='normal':continue
        files=[r for r in db.media(row['id']) if r['present']]
        if not files:continue
        saved=state.source_state(db,row['id']);item=state.safe_json(row['metadata_json'])
        if not isinstance(item,dict):item={}
        file_entries=db.connection.execute('SELECT f.media_id FROM scan_file_matches f JOIN media m ON m.id=f.media_id WHERE m.anime_id=? AND m.present=1',(row['id'],)).fetchall()
        mixed=bool(file_entries) and saved['format_hint'] in {'MOVIE','OVA','SPECIAL'}
        primary_movie_ids={r['id'] for r in files if r['kind']=='episode' and Path(r['path']).parent==Path(row['root_path'])} if saved['format_hint']=='MOVIE' else set()
        if len(primary_movie_ids)==1:mixed=False
        if not mixed and not row['anilist_id'] and not saved['locked']:
            added+=enqueue(db,row['id'],{'title':row['parsed_search_title'] or row['title'],'season':row['detected_season'],'year':row['detected_year'],'alternates':[v for v in (row['alt_title'],) if v],'count':row['episode_count'],'format':saved['format_hint'],'part':saved['part']},files)
        elif row['anilist_id']:
            from .reconciliation import artwork_status
            if not any((item.get('title') or {}).values()):added+=enqueue(db,row['id'],{'id':row['anilist_id']},[],operation='media')
            elif ((item.get('coverImage') or {}).get('extraLarge') or (item.get('coverImage') or {}).get('large')) and artwork_status(item) not in {'Available','Manual artwork','Manual artwork needs review'}:added+=enqueue(db,row['id'],{'id':row['anilist_id'],'artwork_revision':artwork_status(item)},[],operation='artwork')
        if file_entries:
            for file in db.connection.execute('SELECT f.* FROM scan_file_matches f JOIN media m ON f.media_id=m.id WHERE m.anime_id=? AND m.present=1 AND f.locked=0 AND f.anilist_id IS NULL',(row['id'],)).fetchall():
                source_file=next((r for r in files if r['id']==file['media_id']),None)
                if source_file is not None and ((not mixed and file['media_id'] in primary_movie_ids) or not independent_file(source_file['path'],row['root_path'])):
                    db.connection.execute("UPDATE scan_file_matches SET state='Part of parent release',report=? WHERE media_id=?",(json.dumps({'query':file['parsed_title'],'reason':'A regular numbered episode is not an independent release; no AniList search is queued.','candidates':[]}),file['media_id']))
                    db.connection.execute("UPDATE metadata_jobs SET state='completed',outcome='part_of_parent',revision=revision+1,owner=NULL,lease_until=0 WHERE scope='normal' AND target=? AND operation='identify' AND outcome<>'part_of_parent'",('media:'+str(file['media_id']),))
                    continue
                added+=enqueue(db,row['id'],{'title':file['parsed_title'],'format':file['format_hint']},[r for r in files if r['id']==file['media_id']],media_id=file['media_id'])
    db.connection.commit();return added


def alive(pid):
    if not pid:return False
    if pid==os.getpid():return True
    if os.name=='nt':
        import ctypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.restype=ctypes.c_void_p;kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle:return False
        try:
            code=ctypes.c_ulong();return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(int(pid),0);return True
    except OSError:return False


def recover(db,now=None):
    now=time.time() if now is None else now
    for row in db.connection.execute("SELECT * FROM metadata_jobs WHERE state='running'").fetchall():
        if row['lease_until']<=now or not alive(row['owner']):
            db.connection.execute("UPDATE metadata_jobs SET state='pending',owner=NULL,lease_until=0 WHERE scope=? AND target=? AND operation=? AND revision=?",(row['scope'],row['target'],row['operation'],row['revision']))
    db.connection.commit()


def summary(db,now=None):
    rows=db.connection.execute("SELECT state,outcome,next_at,operation,failed_requests FROM metadata_jobs WHERE scope='normal'").fetchall()
    completed=sum(r['state']=='completed' for r in rows);unresolved=sum(r['state']=='unresolved' for r in rows)
    pending=sum(r['state'] in {'pending','running','deferred'} for r in rows)
    failed=sum(r['failed_requests'] for r in rows)
    times=[r['next_at'] for r in rows if r['state'] in {'pending','deferred'} or (r['state']=='unresolved' and r['next_at']>0)]
    timing=db.connection.execute("SELECT duration_ms FROM metadata_job_metrics WHERE scope='normal'").fetchone()
    return {'processing_ms':timing[0] if timing else 0,'pending':pending,'completed':completed,'unresolved':unresolved,'failed':failed,'next_retry':min(times) if times else None,'paused':db.setting('metadata_paused','0')=='1','waiting_reasons':sorted({r['outcome'] for r in rows if r['state']=='deferred'})}


def next_due(db,scheduler=None):
    scheduler=scheduler or get_scheduler();times=[]
    for row in db.connection.execute("SELECT operation,next_at FROM metadata_jobs WHERE scope='normal' AND (state IN ('pending','deferred') OR (state='unresolved' AND next_at>0))"):
        times.append(max(row['next_at'],scheduler.eligible_at() if row['operation']!='artwork' else 0))
    return min(times) if times else None


def progress_text(db):
    info=summary(db);text=f"AniList Metadata Matching: {info['pending']} pending jobs · {info['completed']} completed jobs · {info['unresolved']} unresolved entries · {info['failed']} failed API requests"
    if info['paused']:text+=' · paused by user'
    elif 'rate_limited' in info['waiting_reasons']:text+=' · API matching paused by rate limit; local files remain available'
    elif any(kind in info['waiting_reasons'] for kind in ('network','timeout','api_unavailable')):text+=' · API unavailable; retry scheduled'
    due=next_due(db)
    if not info['paused'] and due and due>time.time():
        from datetime import datetime
        text+=' · next eligible attempt '+datetime.fromtimestamp(due).strftime('%H:%M:%S')+' (local)'
    return text


def _claim(db,now):
    with db.connection:
        db.connection.execute('BEGIN IMMEDIATE')
        row=db.connection.execute("""SELECT * FROM metadata_jobs WHERE scope='normal' AND (state IN ('pending','deferred') OR (state='unresolved' AND next_at>0)) AND next_at<=?
          ORDER BY CASE operation WHEN 'identify' THEN CASE WHEN media_id IS NULL THEN 10 ELSE 15 END WHEN 'media' THEN 20 ELSE 30 END,updated LIMIT 1""",(now,)).fetchone()
        if not row:return None
        db.connection.execute("UPDATE metadata_jobs SET state='running',owner=?,lease_until=? WHERE scope=? AND target=? AND operation=? AND revision=?",(os.getpid(),now+120,row['scope'],row['target'],row['operation'],row['revision']))
        return dict(row)


def _valid(db,job):
    current=db.connection.execute('SELECT * FROM metadata_jobs WHERE scope=? AND target=? AND operation=?',(job['scope'],job['target'],job['operation'])).fetchone()
    if not current or current['revision']!=job['revision'] or not db.anime(job['anime_id']) or not db.anime(job['anime_id'])['active'] or db.anime_scope(job['anime_id'])!='normal':return False
    if job['media_id']:
        source=db.connection.execute('SELECT f.locked,m.anime_id, m.present FROM scan_file_matches f JOIN media m ON m.id=f.media_id WHERE f.media_id=?',(job['media_id'],)).fetchone()
        return bool(source and not source[0] and source['anime_id']==job['anime_id'] and source['present'])
    if job['operation']!='identify':return db.anime(job['anime_id'])['anilist_id']==json.loads(job['payload']).get('id')
    return not db.anime(job['anime_id'])['anilist_id'] and not state.source_state(db,job['anime_id'])['locked']


def _finish(db,job,status,outcome,next_at=0,failed_requests=0):
    db.connection.execute('UPDATE metadata_jobs SET state=?,outcome=?,next_at=?,attempts=attempts+1,failed_requests=failed_requests+?,owner=NULL,lease_until=0,updated=? WHERE scope=? AND target=? AND operation=? AND revision=?',
      (status,outcome,next_at,failed_requests,time.time(),job['scope'],job['target'],job['operation'],job['revision']))


def process(db,*,lookup=None,scheduler=None,should_cancel=lambda:False,status=lambda _:None,max_jobs=8,include_artwork=True,max_seconds=20):
    from .metadata import AniListClient,lookup_anilist,fetch_anilist_id,cache_artwork
    lookup=lookup or lookup_anilist;scheduler=scheduler or get_scheduler();recover(db)
    client=AniListClient(scheduler=scheduler,max_retries=0,wait=False,origin='scanner',should_cancel=should_cancel,status_callback=status)
    applied=processed=0;started=time.monotonic()
    while processed<max_jobs and not should_cancel() and time.monotonic()-started<max_seconds:
        if db.setting('metadata_paused','0')=='1':break
        job=_claim(db,scheduler.clock())
        if not job:break
        if not include_artwork and job['operation']!='identify':
            with db.connection:_finish(db,job,'pending','auxiliary_pending',scheduler.clock()+1)
            break
        payload=json.loads(job['payload']);report=None;item=None;error=None
        try:
            if not _valid(db,job):
                with db.connection:_finish(db,job,'completed','manual_or_superseded')
                continue
            if job['operation']=='identify':
                client.force=job['outcome']=='invalid_response'
                report=lookup(payload['title'],payload.get('season'),payload.get('year'),client,tuple(payload.get('alternates',[])),payload.get('count'),payload.get('format'),payload.get('part'))
                if report.failure_kind and report.failure_kind not in {'no_match','ambiguous'}:raise Deferred(report.failure_kind,report.next_retry,report.http_status,report.requests,report.retry_count)
                if report.rate_limited and not report.selected:raise Deferred('rate_limited',report.next_retry or scheduler.clock()+60,429)
                item=report.selected if not job['media_id'] else None
            elif job['operation']=='media':item=fetch_anilist_id(payload['id'],scheduler=scheduler,force=job['outcome']=='invalid_response')
            elif job['operation']=='artwork':
                row=db.anime(job['anime_id'])
                if row['anilist_id']!=payload['id']:raise Deferred('superseded')
                item=cache_artwork(state.safe_json(row['metadata_json']),db.path.parent/'cache'/'artwork')
            if should_cancel():raise Deferred('cancelled')
        except Deferred as exc:error=exc
        except Exception:error=Deferred('artwork' if job['operation']=='artwork' else 'api_unavailable',scheduler.clock()+(RETRY['artwork'] if job['operation']=='artwork' else 60))
        with db.connection:
            db.connection.execute('BEGIN IMMEDIATE')
            if not _valid(db,job):_finish(db,job,'completed','manual_or_superseded');continue
            if error:
                retry=0 if error.kind=='cancelled' else error.retry_at or scheduler.clock()+RETRY.get(error.kind,60)
                _finish(db,job,'pending' if error.kind=='cancelled' else 'deferred',error.kind,retry,error.attempts if error.kind not in {'waiting','cancelled'} else 0)
            elif item:
                # Never reclassify a normal queue entry into Restricted content.
                if item.get('isAdult') is True:_finish(db,job,'unresolved','scope_conflict')
                else:
                    row=db.anime(job['anime_id']);old=state.safe_json(row['metadata_json'])
                    item=state.merge_art(old,{**old,**item}) if old.get('id')==item.get('id') else state.merge_art(old,item)
                    db.connection.execute('UPDATE anime SET anilist_id=?,metadata_json=? WHERE id=?',(item['id'],json.dumps(item),row['id']))
                    previous=state.source_state(db,row['id'])
                    state.record(db,row['id'],state='High Confidence' if report else previous['state'],report=state.report_data(report) if report else state.safe_json(previous['report']),method='automatic' if report else previous['method'],part=previous['part'],format_hint=previous['format_hint'],artwork_state='Available' if item.get('cover_path') else 'Retry artwork',commit=False)
                    _finish(db,job,'completed','matched' if report else job['operation']);applied+=1
                    remote=(item.get('coverImage') or {}).get('extraLarge') or (item.get('coverImage') or {}).get('large')
                    if job['operation']!='artwork' and remote and (not item.get('cover_path') or not Path(item['cover_path']).is_file()):enqueue(db,row['id'],{'id':item['id']},[],operation='artwork')
                    # The match query has fewer relation fields than the detail query;
                    # only fetch_anime_relations stores that complete per-ID cache.
            else:
                kind='ambiguous' if report.candidates else 'no_match';details=state.report_data(report)
                if job['media_id']:
                    db.connection.execute('UPDATE scan_file_matches SET report=?,state=? WHERE media_id=?',(json.dumps(details),'Needs Review' if report.candidates else 'Unmatched',job['media_id']))
                else:
                    previous=state.source_state(db,job['anime_id']);state.record(db,job['anime_id'],state='Needs Review' if report.candidates else 'Unmatched',report=details,method='automatic',part=previous['part'],format_hint=previous['format_hint'],commit=False)
                # Give new catalog entries one delayed chance to appear.
                # Further attempts require a changed source or manual review.
                retry = scheduler.clock() + RETRY[kind] if job['outcome'] not in {'ambiguous', 'no_match'} else 0
                _finish(db,job,'unresolved',kind,retry)
        processed+=1;status(progress_text(db))
        if error and error.kind in {'rate_limited','waiting','network','timeout','api_unavailable','cancelled'}:break
    elapsed=round((time.monotonic()-started)*1000)
    if processed:
        with db.connection:db.connection.execute("INSERT INTO metadata_job_metrics(scope,duration_ms,last_batch_ms,batches) VALUES('normal',?,?,1) ON CONFLICT(scope) DO UPDATE SET duration_ms=duration_ms+excluded.duration_ms,last_batch_ms=excluded.last_batch_ms,batches=batches+1",(elapsed,elapsed))
    return {**summary(db),'applied':applied,'processed':processed,'duration_ms':elapsed}
