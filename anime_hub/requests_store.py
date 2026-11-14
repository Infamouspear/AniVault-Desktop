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
    def restricted(self,identifier):
        return any(self.db.anime_scope(r)=='restricted' for r in
                   self.connection.execute('SELECT id FROM anime WHERE anilist_id=?',(identifier,)))

    def local_match(self,identifier):
        if not identifier:return None
        matches=[r['id'] for r in self.connection.execute("""SELECT a.id FROM anime a WHERE a.anilist_id=?
          AND EXISTS(SELECT 1 FROM media m WHERE m.anime_id=a.id AND m.present=1 AND m.kind='episode')""",(identifier,))
                 if self.db.anime_scope(r)=='normal']
        return matches[0] if len(matches)==1 else None
    def update(self,key,status,notes):
        row=self.connection.execute("SELECT kind,provider_id,status FROM desktop_requests WHERE id=?",(key,)).fetchone()
        if not row:raise ValueError("Request no longer exists.")
        if status not in (REQUEST if row['kind']=='anime' else FEEDBACK):raise ValueError("Invalid status.")
        if status=='Available' and row['status']!='Available' and not self.local_match(row['provider_id']):
            raise ValueError("Available requires one exact local AniList match with indexed media.")
        with self.connection:self.connection.execute("UPDATE desktop_requests SET status=?,notes=?,updated=CURRENT_TIMESTAMP WHERE id=?",(status,notes[:8000],key))
    def remove(self,key):
        with self.connection:self.connection.execute("DELETE FROM desktop_requests WHERE id=?",(key,))

