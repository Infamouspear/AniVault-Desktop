"""Local requests; intentionally independent of library and watch-state records."""
import json
from urllib.parse import urlsplit

REQUEST=('Requested','Under Review','Approved','Available','Declined')
FEEDBACK=('New','Under Review','Planned','Resolved','Closed')
CATEGORIES=('Bug report','Feature suggestion','General feedback')

SCHEMA="""CREATE TABLE IF NOT EXISTS desktop_requests (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('anime','feedback')),
 provider_id INTEGER UNIQUE CHECK(provider_id IS NULL OR (kind='anime' AND provider_id>0)),
 title TEXT NOT NULL, category TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
 metadata TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);"""


PROCESSED={'Approved','Available','Declined'}

def migrate_requests(connection):
    columns={r[1] for r in connection.execute('PRAGMA table_info(desktop_requests)')}
    first=not connection.execute("SELECT 1 FROM settings WHERE key='request_queue_migrated' AND value='1'").fetchone()
    with connection:
        if not connection.in_transaction:connection.execute('BEGIN')
        for name,declaration in [('archived','INTEGER NOT NULL DEFAULT 0'),('processed_at','TEXT'),('revision','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:connection.execute(f'ALTER TABLE desktop_requests ADD COLUMN {name} {declaration}')
        connection.execute("""CREATE TABLE IF NOT EXISTS desktop_request_events (
          id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES desktop_requests(id) ON DELETE CASCADE,
          action TEXT NOT NULL, previous_status TEXT, status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        connection.execute('CREATE INDEX IF NOT EXISTS requests_queue ON desktop_requests(kind,archived,status,id)')
        connection.execute('CREATE INDEX IF NOT EXISTS request_anime_match ON anime(anilist_id)')
        if first:
            connection.execute("UPDATE desktop_requests SET archived=1,processed_at=updated WHERE kind='anime' AND status IN ('Approved','Available','Declined')")
            connection.execute("INSERT INTO desktop_request_events(request_id,action,status,notes,created) SELECT id,'legacy_archive',status,notes,updated FROM desktop_requests WHERE kind='anime' AND archived=1 AND NOT EXISTS(SELECT 1 FROM desktop_request_events e WHERE e.request_id=desktop_requests.id AND e.action='legacy_archive')")
            connection.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('request_queue_migrated','1')")


def provider_id(value):
    if isinstance(value,bool) or not str(value).isascii() or not str(value).isdecimal():
        raise ValueError("Enter a positive AniList ID.")
    number=int(value)
    if not 0<number<2**63:
        raise ValueError("Enter a positive AniList ID.")
    return number


def https_url(value):
    try:
        url=urlsplit(value)
        return value if url.scheme=='https' and url.hostname and not url.username and not url.password else ''
    except ValueError:return ''


class Requests:
    def __init__(self,db):self.db=db;self.connection=db.connection
    def all(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM desktop_requests ORDER BY id DESC")]
    def add(self,kind,title,category='',details='',reference='',identifier=None,item=None):
        states={'anime':REQUEST,'feedback':FEEDBACK}[kind]
        if kind=='anime' and item and (item.get('isAdult') is True or item.get('type','ANIME')!='ANIME'):raise ValueError('Only normal anime requests are supported here.')
        title=title.strip()
        if not title or len(title)>200:raise ValueError("Enter a title of 1–200 characters.")
        if kind=='feedback' and category not in CATEGORIES:raise ValueError("Choose a feedback category.")
        if reference and not https_url(reference):raise ValueError("Use an HTTPS reference.")
        if identifier is not None:
            if kind!='anime':raise ValueError("AniList IDs apply only to anime requests.")
            identifier=provider_id(identifier)
            if self.restricted(identifier):
                raise ValueError("Restricted titles cannot be requested here.")
        with self.connection:
            cursor=self.connection.execute("""INSERT INTO desktop_requests(kind,provider_id,title,category,details,reference,metadata,status)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO NOTHING""",
                (kind,identifier,title,category,details[:8000],reference[:2000],json.dumps(item or {}),states[0]))
            if not cursor.rowcount:
                return self.connection.execute("SELECT id FROM desktop_requests WHERE provider_id=?",(identifier,)).fetchone()[0]
            return cursor.lastrowid
    def discover(self,item):
        if item.get('type')!='ANIME' or item.get('isAdult') is not False:
            raise ValueError("Only normal anime can be requested from Discover.")
        identifier=provider_id(item.get('id'));titles=item.get('title') or {}
        title=next((titles[k] for k in ('english','romaji','native') if titles.get(k)),f"AniList #{identifier}")
        cover=(item.get('coverImage') or {}).get('large') or (item.get('coverImage') or {}).get('extraLarge')
        metadata={k:item[k] for k in ('format','seasonYear','startDate','description','synonyms','episodes') if k in item}
        metadata.update(id=identifier,type='ANIME',isAdult=False,title=titles,coverImage={'large':https_url(cover or '')})
        return self.add('anime',title,item.get('format') or '',identifier=identifier,item=metadata)
    def blocked_ids(self):
        stamp=self.db.change_stamp();cached=getattr(self.db,'_request_privacy_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        blocked={r['anilist_id'] for r in self.db.anime_list() if r['anilist_id'] and self.db.anime_scope(r,fresh=False)=='restricted'}
        for row in self.connection.execute("SELECT metadata_json FROM saved_titles WHERE scope='restricted' UNION ALL SELECT metadata_json FROM manual_status WHERE scope='restricted'"):
            try:item=json.loads(row[0] or '{}')
            except (ValueError,TypeError):continue
            if item.get('type')!='MANGA' and item.get('id'):blocked.add(item['id'])
        self.db._request_privacy_cache=(stamp,blocked);return blocked

    def restricted(self,identifier):return bool(identifier and identifier in self.blocked_ids())

    def visible(self):
        blocked=self.blocked_ids();result=[]
        for row in self.all():
            try:item=json.loads(row['metadata'] or '{}')
            except (ValueError,TypeError):item={}
            if row['kind']=='anime' and (row['provider_id'] in blocked or item.get('isAdult') is True or item.get('type','ANIME')!='ANIME'):continue
            result.append(row)
        return result

    def local_matches(self):
        stamp=self.db.change_stamp();cached=getattr(self.db,'_request_local_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        blocked=self.blocked_ids();matches={}
        rows=self.connection.execute("""SELECT a.* FROM anime a WHERE a.anilist_id>0 AND EXISTS
            (SELECT 1 FROM media m WHERE m.anime_id=a.id AND m.present=1 AND m.kind IN ('episode','movie'))""").fetchall()
        for row in rows:
            if row['anilist_id'] not in blocked and self.db.anime_scope(row,fresh=False)=='normal':matches.setdefault(row['anilist_id'],[]).append(row['id'])
        result={i:ids[0] for i,ids in matches.items() if len(ids)==1}
        self.db._request_local_cache=(stamp,result);return result

    def local_match(self,identifier):return self.local_matches().get(identifier)

    def get(self,key):
        row=self.connection.execute('SELECT * FROM desktop_requests WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('Request no longer exists.')
        return dict(row)

    def update(self,key,status,notes,*,action='edit',manual_available=False,verified=False,expected_revision=None):
        row=self.get(key)
        if expected_revision is not None and row['revision']!=expected_revision:raise ValueError('A newer review decision must be preserved.')
        if verified and any(self.db.anime_scope(r,fresh=False)!='normal' for r in self.connection.execute('SELECT * FROM anime WHERE anilist_id=?',(row['provider_id'],))):raise ValueError('Local match is no longer normal.')
        if status not in (REQUEST if row['kind']=='anime' else FEEDBACK):raise ValueError('Invalid status.')
        if row['kind']=='anime' and not verified and self.restricted(row['provider_id']):raise ValueError('Restricted requests are unavailable here.')
        if row['kind']=='anime' and status=='Available' and row['status']!='Available' and not (manual_available or verified or self.local_match(row['provider_id'])):
            raise ValueError('Available requires one exact local AniList match with indexed media.')
        archived=int(row['kind']=='anime' and status in PROCESSED)
        notes=notes[:8000]
        if row['status']==status and row['notes']==notes and row['archived']==archived:return None
        fields={k:row[k] for k in ('status','notes','archived','processed_at','updated')}
        with self.connection:
            cursor=self.connection.execute("""UPDATE desktop_requests SET status=?,notes=?,archived=?,
              processed_at=CASE WHEN ?=0 THEN NULL WHEN archived=1 AND status=? THEN processed_at ELSE CURRENT_TIMESTAMP END,
              updated=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=? AND revision=?""",
              (status,notes,archived,archived,status,key,row['revision']))
            if cursor.rowcount!=1:raise ValueError('This request changed. Refresh and try again.')
            if row['kind']=='anime':self.connection.execute('INSERT INTO desktop_request_events(request_id,action,previous_status,status,notes) VALUES(?,?,?,?,?)',(key,action,row['status'],status,notes))
        return {'id':key,'before':fields,'revision':row['revision']+1}

    def process(self,key,status):
        row=self.get(key)
        if row['kind']!='anime' or status not in PROCESSED:raise ValueError('Choose an anime request action.')
        return self.update(key,status,row['notes'],action='manual_downloaded' if status=='Available' else 'review',manual_available=status=='Available')

    def undo(self,token):
        row=self.get(token['id']);before=token['before']
        if row['kind']!='anime' or self.restricted(row['provider_id']):raise ValueError('Request is unavailable.')
        with self.connection:
            cursor=self.connection.execute('UPDATE desktop_requests SET status=?,notes=?,archived=?,processed_at=?,updated=?,revision=revision+1 WHERE id=? AND revision=?',
                (before['status'],before['notes'],before['archived'],before['processed_at'],before['updated'],token['id'],token['revision']))
            if cursor.rowcount!=1:raise ValueError('A newer change prevents Undo. Review the request in History.')
            self.connection.execute("INSERT INTO desktop_request_events(request_id,action,previous_status,status,notes) VALUES(?,'undo',?,?,?)",(token['id'],row['status'],before['status'],before['notes']))

    def restore(self,key):
        row=self.get(key)
        if row['kind']!='anime':raise ValueError('Only anime requests use the review queue.')
        return self.update(key,'Requested',row['notes'],action='restore')

    def events(self,key):return [dict(r) for r in self.connection.execute('SELECT * FROM desktop_request_events WHERE request_id=? ORDER BY id',(key,))]

    def reconcile_available(self):
        matches=self.local_matches();changed=0
        for row in self.visible():
            if row['kind']=='anime' and row['provider_id'] in matches and row['status'] in {'Requested','Under Review','Approved'}:
                try:self.update(row['id'],'Available',row['notes'],action='scan_match',verified=True,expected_revision=row['revision']);changed+=1
                except ValueError:continue
        return changed

    def remove(self,key):
        with self.connection:self.connection.execute("DELETE FROM desktop_requests WHERE id=?",(key,))

