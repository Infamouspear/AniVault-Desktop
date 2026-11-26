"""Scanner provenance, reversible matching and source identity reconciliation."""
import hashlib,json,os,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from .parser import parse_title,VIDEO_EXTS


def safe_json(value):
    try:return json.loads(value or '{}')
    except (ValueError,TypeError):return {}


def backup(db,reason='scan'):
    if not db.path.exists():return None
    folder=db.path.parent/'backups';folder.mkdir(exist_ok=True)
    target=folder/f"{reason}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.db"
    source=sqlite3.connect(db.path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        dest=sqlite3.connect(target)
        try:source.backup(dest);assert dest.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        finally:dest.close()
    finally:source.close()
    return target


def migrate(db):
    c=db.connection
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='scan_sources'").fetchone() and c.execute('SELECT 1 FROM anime LIMIT 1').fetchone():backup(db,'pre-scanner')
    with c:
        if not c.in_transaction:c.execute('BEGIN')
        c.execute("""CREATE TABLE IF NOT EXISTS scan_sources (
          anime_id INTEGER PRIMARY KEY REFERENCES anime(id) ON DELETE CASCADE,
          part INTEGER,format_hint TEXT,state TEXT NOT NULL DEFAULT 'Unmatched',method TEXT NOT NULL DEFAULT 'legacy',
          locked INTEGER NOT NULL DEFAULT 0,report TEXT NOT NULL DEFAULT '{}',warnings TEXT NOT NULL DEFAULT '[]',
          artwork_state TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS scan_file_matches (
          media_id INTEGER PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
          parsed_title TEXT NOT NULL,format_hint TEXT,anilist_id INTEGER,metadata_json TEXT NOT NULL DEFAULT '{}',
          state TEXT NOT NULL DEFAULT 'Unmatched',locked INTEGER NOT NULL DEFAULT 0,report TEXT NOT NULL DEFAULT '{}')""")
        c.execute("""CREATE TABLE IF NOT EXISTS scan_match_changes (
          id INTEGER PRIMARY KEY,anime_id INTEGER NOT NULL,media_id INTEGER,previous_id INTEGER,
          previous_metadata TEXT NOT NULL,action TEXT NOT NULL,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        columns={r[1] for r in c.execute('PRAGMA table_info(media)')}
        for name,kind in [('file_identity','TEXT'),('episode_end','INTEGER')]:
            if name not in columns:c.execute(f'ALTER TABLE media ADD COLUMN {name} {kind}')
        c.execute('CREATE INDEX IF NOT EXISTS media_file_identity ON media(file_identity)')


def path_key(path):return os.path.normcase(os.path.abspath(str(path)))

def file_identity(path):
    stat=path.stat();return f'{stat.st_dev}:{stat.st_ino}' if stat.st_ino else None


def source_snapshot(db):
    # Immutable evidence is essential when one old container is split into roots.
    # Relocating the first file must not make the remaining subset look like a rename.
    rows=[dict(r) for r in db.anime_list()];signatures={r['id']:set() for r in rows}
    for media in db.connection.execute('SELECT anime_id,path,file_identity FROM media'):
        if media['file_identity'] and Path(media['path']).suffix.lower() in VIDEO_EXTS:signatures[media['anime_id']].add(media['file_identity'])
    return {'rows':rows,'signatures':signatures,'missing':{r['id'] for r in rows if not Path(r['root_path']).exists()},'claimed':set()}


def source_id(db,path,parsed,files,category,snapshot=None):
    rows=db.anime_list();same=[r for r in rows if path_key(r['root_path'])==path_key(path)]
    found=same[0] if same else None
    if found is None:
        owned={r['anime_id'] for f in files for r in db.connection.execute('SELECT anime_id FROM media WHERE path=?',(str(f),))}
        if len(owned)==1:
            # Older scanners collapsed multiple roots into one local identity.
            # Retain those file associations; separating them requires deliberate review.
            return next(iter(owned))
    if found is None:
        # Only filesystem identities can prove a rename. Similar names/size never merge sources.
        identities={file_identity(f) for f in files if f.suffix.lower() in VIDEO_EXTS}-{None}
        snapshot=snapshot or source_snapshot(db)
        previous={r['id']:r for r in snapshot['rows'] if r['id'] in snapshot['missing'] and r['id'] not in snapshot['claimed']}
        evidence=[identifier for identifier in previous if identities and identities==snapshot['signatures'].get(identifier)]
        if len(evidence)==1:
            found=previous[evidence[0]];snapshot['claimed'].add(found['id'])
    identity=found['identity'] if found else 'source:'+hashlib.sha256(path_key(path).encode()).hexdigest()[:28]
    return db.upsert_anime(identity,parsed.title,parsed.alternate_title,category,str(path),path.name,parsed.title,parsed.season if parsed.season_explicit else None,parsed.year)


def source_state(db,anime_id):
    row=db.connection.execute('SELECT * FROM scan_sources WHERE anime_id=?',(anime_id,)).fetchone()
    return dict(row) if row else {'anime_id':anime_id,'locked':0,'method':'legacy','state':'Unmatched','report':'{}','warnings':'[]','part':None,'format_hint':None}


def record(db,anime_id,*,state,report=None,warnings=(),part=None,format_hint=None,method=None,artwork_state='',commit=True):
    previous=source_state(db,anime_id)
    db.connection.execute("""INSERT INTO scan_sources(anime_id,part,format_hint,state,method,locked,report,warnings,artwork_state)
       VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(anime_id) DO UPDATE SET part=excluded.part,format_hint=excluded.format_hint,
       state=excluded.state,method=excluded.method,report=excluded.report,warnings=excluded.warnings,
       artwork_state=excluded.artwork_state,updated=CURRENT_TIMESTAMP""",
       (anime_id,part,format_hint,state,method or previous['method'],previous['locked'],json.dumps(report or {}),json.dumps(list(warnings)),artwork_state))
    if commit:db.connection.commit()


def report_data(report):
    return {'query':report.search_title,'level':getattr(report,'confidence_level','Unmatched'),
            'reason':report.failure_reason or next((d['reason'] for d in getattr(report,'decisions',[]) if report.selected and d['id']==report.selected['id']),''),'candidates':report.candidates,'decisions':[d for d in getattr(report,'decisions',[]) if d.get('id') in {c.get('id') for c in report.candidates}],
            'selected_id':report.selected.get('id') if report.selected and report.selected.get('id') in {c.get('id') for c in report.candidates} else None,'network_error':bool(report.api_error),'failure_kind':getattr(report,'failure_kind',''),'next_retry':getattr(report,'next_retry',0),'requests':getattr(report,'requests',0),'cache_hits':getattr(report,'cache_hits',0),'rate_limited':report.rate_limited}


def merge_art(old,new):
    value=dict(new)
    for field in ('cover_path','banner_path'):
        path=old.get(field)
        if path and Path(path).is_file() and (old.get('id')==new.get('id') or not __import__('re').match(r'^\d+_(?:cover|banner)_path\.',Path(path).name)):value[field]=path
    return value


def manual_match(db,anime_id,item=None,media_id=None,scope='normal',clear=False):
    row=db.anime(anime_id)
    if not row or db.anime_scope(row)!=scope or (scope=='restricted' and db.setting('restricted_unlocked','0')!='1'):raise ValueError('This source is not authorized in this workspace.')
    if item is not None and (type(item.get('id')) is not int or item['id']<=0 or type(item.get('isAdult')) is not bool or item['isAdult']!=(scope=='restricted') or item.get('type','ANIME')!='ANIME'):raise ValueError('Choose an authorized anime identity.')
    backup(db,'before-match')
    with db.connection:
        if media_id is not None:
            media=db.connection.execute('SELECT * FROM media WHERE id=? AND anime_id=?',(media_id,anime_id)).fetchone()
            if not media:raise ValueError('The source file no longer belongs to this entry.')
            previous=db.connection.execute('SELECT * FROM scan_file_matches WHERE media_id=?',(media_id,)).fetchone()
            if not previous:raise ValueError('Review this file after scanning its source.')
            db.connection.execute('INSERT INTO scan_match_changes(anime_id,media_id,previous_id,previous_metadata,action) VALUES(?,?,?,?,?)',(anime_id,media_id,previous['anilist_id'],previous['metadata_json'],'clear' if clear else 'manual' if item else 'leave_unmatched'))
            db.connection.execute('UPDATE scan_file_matches SET anilist_id=?,metadata_json=?,state=?,locked=? WHERE media_id=?',(item['id'] if item else None,json.dumps(item or {}),'Manual' if item else 'Unmatched',int(not clear),media_id))
        else:
            # Attach existing user choices to the stable local ID before changing a remote alias.
            old_key=db.entity_key_for_anime(anime_id);local_key=f'local:{anime_id}'
            if old_key!=local_key:
                shared=db.connection.execute('SELECT 1 FROM anime WHERE anilist_id=? AND id<>?',(row['anilist_id'],anime_id)).fetchone()
                for link in db.connection.execute('SELECT * FROM collection_entries WHERE entity_key=?',(old_key,)).fetchall():
                    db.connection.execute('INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json,added_at) VALUES(?,?,?,?)',(link['collection_id'],local_key,link['metadata_json'],link['added_at']))
                for status in db.connection.execute('SELECT * FROM manual_status WHERE scope=? AND entity_key=?',(scope,old_key)).fetchall():
                    db.connection.execute('INSERT OR IGNORE INTO manual_status(scope,entity_key,status,metadata_json) VALUES(?,?,?,?)',(scope,local_key,status['status'],status['metadata_json']))
                if not shared:
                    db.connection.execute('DELETE FROM collection_entries WHERE entity_key=?',(old_key,))
                    db.connection.execute('DELETE FROM manual_status WHERE scope=? AND entity_key=?',(scope,old_key))
            old=safe_json(row['metadata_json']);value=merge_art(old,item or {k:v for k,v in old.items() if k in ('isAdult','episode_titles')})
            db.connection.execute('INSERT INTO scan_match_changes(anime_id,previous_id,previous_metadata,action) VALUES(?,?,?,?)',(anime_id,row['anilist_id'],row['metadata_json'],'clear' if clear else 'manual' if item else 'leave_unmatched'))
            db.connection.execute('UPDATE anime SET anilist_id=?,metadata_json=? WHERE id=?',(item['id'] if item else None,json.dumps(value),anime_id))
            db.connection.execute('UPDATE manual_status SET metadata_json=? WHERE scope=? AND entity_key=?',(json.dumps(value),scope,local_key))
            db.connection.execute('UPDATE collection_entries SET metadata_json=? WHERE entity_key=?',(json.dumps(value),local_key))
            db.connection.execute("INSERT INTO scan_sources(anime_id,state,method,locked) VALUES(?,?,?,?) ON CONFLICT(anime_id) DO UPDATE SET state=excluded.state,method=excluded.method,locked=excluded.locked",(anime_id,'Manual' if item else 'Unmatched','automatic' if clear else 'manual',int(not clear)))
        target=('media:'+str(media_id)) if media_id is not None else 'anime:'+str(anime_id)
        db.connection.execute("UPDATE metadata_jobs SET state=?,outcome=?,next_at=0,revision=revision+1,owner=NULL,lease_until=0 WHERE scope=? AND target=? AND operation='identify'",('pending' if clear else 'completed','manual_cleared' if clear else 'manual',scope,target))


def file_title(path,parent_title):
    import re
    text=path.stem
    text=re.sub(r'^\s*\[[^\]]+\]\s*','',text)
    text=re.sub(r'\[[^\]]*\]','',text)
    text=re.sub(r'\s*[,\-]?\s*Part\s*\d+\s*$','',text,flags=re.I)
    text=re.sub(r'^S\d+(?:SP|E)\d+[- ._]*','',text,flags=re.I)
    if not re.search(r'[A-Za-z]{3}',text):return parent_title
    return text.strip(' ._-')


def review_rows(db,scope='normal'):
    if scope not in {'normal','restricted'} or (scope=='restricted' and db.setting('restricted_unlocked','0')!='1'):return []
    result=[]
    missing=dict(db.connection.execute('SELECT anime_id,SUM(present=0) FROM media GROUP BY anime_id'))
    for row in db.anime_list():
        if db.anime_scope(row,fresh=False)!=scope:continue
        state=source_state(db,row['id']);item=safe_json(row['metadata_json'])
        result.append({'anime_id':row['id'],'media_id':None,'title':row['parsed_search_title'] or row['title'],'source':row['root_path'],'season':row['detected_season'],'count':row['media_count'],'state':state['state'] if state['method']!='legacy' or state.get('updated') else 'Existing match' if row['anilist_id'] else 'Unmatched','item':item,'report':safe_json(state['report']),'locked':state['locked'],'anilist_id':row['anilist_id']})
        if missing.get(row['id']):
            result[-1]['state']='Missing source'
            result[-1]['report']={**result[-1]['report'],'reason':str(missing[row['id']])+' unavailable indexed files were retained, including their user data.'}
        for media in db.connection.execute('SELECT f.*,m.path FROM scan_file_matches f JOIN media m ON m.id=f.media_id WHERE m.anime_id=?',(row['id'],)):
            result.append({'anime_id':row['id'],'media_id':media['media_id'],'format_hint':media['format_hint'],'title':media['parsed_title'],'source':media['path'],'season':None,'count':1,'state':media['state'],'item':safe_json(media['metadata_json']),'report':safe_json(media['report']),'locked':media['locked'],'anilist_id':media['anilist_id']})
    return result


def audit(db,scope='normal'):
    if scope not in {'normal','restricted'} or (scope=='restricted' and db.setting('restricted_unlocked','0')!='1'):raise ValueError('Unlock the authorized workspace first.')
    from .metadata import evaluate_candidate
    backup(db,'before-review')
    count=0
    for row in db.anime_list():
        if db.anime_scope(row,fresh=False)!=scope:continue
        path=Path(row['root_path']);parsed=parse_title(path.name,tuple(p.name for p in path.parents));item=safe_json(row['metadata_json']);saved=source_state(db,row['id'])
        if saved['locked']:continue
        warnings=[]
        if not path.exists():warnings.append('Source is unavailable; records and progress were retained.')
        if row['anilist_id']:
            decision=evaluate_candidate(parsed.title,item,parsed.season if parsed.season_explicit else None,parsed.year,alternates=tuple(v for v in (parsed.alternate_title,) if v),format_hint=parsed.format_hint)
            level='Needs Review' if not decision['eligible'] or decision['score']<.86 else 'Existing match'
            reason=decision['reason'] if level=='Needs Review' else 'Existing link retained; original automatic/manual provenance is unknown.'
        else:level='Unmatched';reason='No AniList identity is assigned.'
        record(db,row['id'],state=level,report={'query':parsed.title,'reason':reason,'candidates':[]},warnings=warnings,part=parsed.part,format_hint=parsed.format_hint)
        count+=1
    return count
