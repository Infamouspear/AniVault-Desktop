from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS anime (
 id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 alt_title TEXT DEFAULT '', category TEXT DEFAULT 'Other', root_path TEXT NOT NULL,
 anilist_id INTEGER, metadata_json TEXT DEFAULT '{}', added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS media (
 id INTEGER PRIMARY KEY, anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
 path TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, season INTEGER, episode INTEGER,
 detected_kind TEXT NOT NULL, present INTEGER DEFAULT 1, modified REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS overrides (
 path TEXT PRIMARY KEY, kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS media_anime ON media(anime_id);
CREATE TABLE IF NOT EXISTS collections (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 description TEXT NOT NULL DEFAULT '', sort_order INTEGER,
 scope TEXT NOT NULL DEFAULT 'normal',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_items (
 collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
 anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
 added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(collection_id, anime_id)
);
CREATE INDEX IF NOT EXISTS collection_items_anime ON collection_items(anime_id);
CREATE TABLE IF NOT EXISTS collection_entries (
 collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
 entity_key TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
 added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(collection_id,entity_key)
);
CREATE INDEX IF NOT EXISTS collection_entries_key ON collection_entries(entity_key);
CREATE TABLE IF NOT EXISTS manual_status (
 scope TEXT NOT NULL DEFAULT 'normal', entity_key TEXT NOT NULL,
 status TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(scope,entity_key)
);
CREATE TABLE IF NOT EXISTS franchises (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS franchise_items (
 franchise_id INTEGER NOT NULL REFERENCES franchises(id) ON DELETE CASCADE,
 anime_id INTEGER NOT NULL UNIQUE REFERENCES anime(id) ON DELETE CASCADE,
 sort_order INTEGER NOT NULL DEFAULT 0, relation_type TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(franchise_id,anime_id)
);
CREATE INDEX IF NOT EXISTS franchise_items_franchise ON franchise_items(franchise_id,sort_order);
CREATE TABLE IF NOT EXISTS saved_titles (
 anilist_id INTEGER NOT NULL, scope TEXT NOT NULL DEFAULT 'normal', title TEXT NOT NULL, metadata_json TEXT NOT NULL,
 saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(scope,anilist_id)
);
CREATE TABLE IF NOT EXISTS restricted_source_saved (
 source TEXT NOT NULL, external_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
 saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_visited_at TEXT,
 PRIMARY KEY(source,external_id)
);
CREATE TABLE IF NOT EXISTS restricted_reading_progress (
 source TEXT NOT NULL, external_id TEXT NOT NULL, last_page INTEGER NOT NULL DEFAULT 1,
 total_pages INTEGER NOT NULL DEFAULT 0, last_read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(source,external_id)
);
CREATE TABLE IF NOT EXISTS restricted_source_metadata (
 source TEXT NOT NULL, external_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
 cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(source,external_id)
);
CREATE TABLE IF NOT EXISTS restricted_source_history (
 source TEXT NOT NULL, external_id TEXT NOT NULL, last_visited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 visit_count INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(source,external_id)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        from .manga_state import SCHEMA as READER_SCHEMA
        self.connection.executescript(READER_SCHEMA)
        from .manga_library import SCHEMA as MANGA_SCHEMA
        self.connection.executescript(MANGA_SCHEMA)
        self._migrate()
        self.connection.executescript("CREATE INDEX IF NOT EXISTS manual_status_list ON manual_status(scope,status,updated_at DESC); CREATE INDEX IF NOT EXISTS collection_entries_added ON collection_entries(collection_id,added_at DESC);")

    def _migrate(self):
        source_columns={row[1] for row in self.connection.execute("PRAGMA table_info(restricted_source_saved)")}
        if "last_visited_at" not in source_columns:
            self.connection.execute("ALTER TABLE restricted_source_saved ADD COLUMN last_visited_at TEXT")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(anime)")}
        for name, declaration in (("source_folder_name", "TEXT DEFAULT ''"),
                                  ("parsed_search_title", "TEXT DEFAULT ''"),
                                  ("detected_season", "INTEGER"),
                                  ("detected_year", "INTEGER"),
                                  ("favorite", "INTEGER NOT NULL DEFAULT 0"),
                                  ("last_watched_episode", "INTEGER"),
                                  ("last_watched_at", "TEXT")):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE anime ADD COLUMN {name} {declaration}")
        media_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(media)")}
        for name, declaration in (("watched", "INTEGER NOT NULL DEFAULT 0"),
                                  ("watched_at", "TEXT"),
                                  ("size_bytes", "INTEGER"),
                                  ("resume_position_ms", "INTEGER NOT NULL DEFAULT 0")):
            if name not in media_columns:
                self.connection.execute(f"ALTER TABLE media ADD COLUMN {name} {declaration}")
        if 'size_bytes' not in {row[1] for row in self.connection.execute("PRAGMA table_info(manga_items)")}:
            self.connection.execute("ALTER TABLE manga_items ADD COLUMN size_bytes INTEGER")
        for table in ('anime','manga_series'):
            if 'personal_rating_units' not in {r[1] for r in self.connection.execute(f'PRAGMA table_info({table})')}:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN personal_rating_units INTEGER CHECK(typeof(personal_rating_units)='integer' AND personal_rating_units BETWEEN 2 AND 20 OR personal_rating_units IS NULL)")
        saved_columns={row[1] for row in self.connection.execute("PRAGMA table_info(saved_titles)")}
        if "scope" not in saved_columns:
            self.connection.executescript("""ALTER TABLE saved_titles RENAME TO saved_titles_legacy;
              CREATE TABLE saved_titles (anilist_id INTEGER NOT NULL,scope TEXT NOT NULL DEFAULT 'normal',title TEXT NOT NULL,metadata_json TEXT NOT NULL,saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(scope,anilist_id));
              INSERT INTO saved_titles(anilist_id,scope,title,metadata_json,saved_at) SELECT anilist_id,'normal',title,metadata_json,saved_at FROM saved_titles_legacy;
              DROP TABLE saved_titles_legacy;""")
        collection_columns={row[1] for row in self.connection.execute("PRAGMA table_info(collections)")}
        if "scope" not in collection_columns:
            self.connection.execute("ALTER TABLE collections ADD COLUMN scope TEXT NOT NULL DEFAULT 'normal'")
        # V0.7.8 promotes local-only membership into stable entity keys. Matched
        # anime use their AniList ID so membership survives Saved -> local.
        self.connection.execute("""INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json,added_at)
          SELECT ci.collection_id,
                 CASE WHEN a.anilist_id IS NOT NULL THEN 'anilist:'||a.anilist_id ELSE 'local:'||a.id END,
                 a.metadata_json,ci.added_at
          FROM collection_items ci JOIN anime a ON a.id=ci.anime_id""")
        self.connection.commit()

        self.saved_planning_report={"migrated":0,"preserved_status":0,"skipped":0}
        if self.setting("saved_planning_v086","0")!="1":
            import json
            with self.connection:
                self.connection.execute("CREATE TABLE IF NOT EXISTS normal_saved_migration_archive(anilist_id INTEGER PRIMARY KEY,title TEXT,metadata_json TEXT,saved_at TEXT)")
                for row in self.connection.execute("SELECT * FROM saved_titles WHERE scope='normal'").fetchall():
                    try:
                        item=json.loads(row['metadata_json']);identifier=int(row['anilist_id'])
                        if not isinstance(item,dict) or item.get('isAdult') is True:raise ValueError('unsupported normal bookmark')
                    except (ValueError,TypeError):
                        self.saved_planning_report['skipped']+=1;continue
                    self.connection.execute('INSERT OR IGNORE INTO normal_saved_migration_archive VALUES(?,?,?,?)',(identifier,row['title'],row['metadata_json'],row['saved_at']))
                    keys=[f'anilist:{identifier}']
                    keys.extend(f"local:{r[0]}" for r in self.connection.execute('SELECT id FROM anime WHERE anilist_id=?',(identifier,)))
                    keys.extend(f"manga:{r[0]}" for r in self.connection.execute("SELECT id FROM manga_series WHERE anilist_id=? AND scope='normal'",(identifier,)))
                    existing=self.connection.execute("SELECT 1 FROM manual_status WHERE scope='normal' AND entity_key IN ("+','.join('?' for _ in keys)+') LIMIT 1',keys).fetchone()
                    if existing:self.saved_planning_report['preserved_status']+=1
                    else:
                        self.connection.execute("INSERT INTO manual_status(scope,entity_key,status,metadata_json) VALUES('normal',?,'Planning',?)",(keys[0],row['metadata_json']))
                        self.saved_planning_report['migrated']+=1
                    self.connection.execute("DELETE FROM saved_titles WHERE scope='normal' AND anilist_id=?",(identifier,))
                self.connection.execute("INSERT INTO settings(key,value) VALUES('saved_planning_v086','1') ON CONFLICT(key) DO UPDATE SET value='1'")

        # Restricted AniList bookmarks now use the same Planning organization
        # as normal titles. External source bookmarks remain in their own table.
        self.restricted_saved_planning_report={"migrated":0,"preserved_status":0,"skipped":0}
        if self.setting("restricted_saved_planning_v0881","0")!="1":
            import json
            with self.connection:
                self.connection.execute("CREATE TABLE IF NOT EXISTS restricted_saved_migration_archive(anilist_id INTEGER PRIMARY KEY,title TEXT,metadata_json TEXT,saved_at TEXT)")
                for row in self.connection.execute("SELECT * FROM saved_titles WHERE scope='restricted'").fetchall():
                    self.connection.execute('INSERT OR IGNORE INTO restricted_saved_migration_archive VALUES(?,?,?,?)',(row['anilist_id'],row['title'],row['metadata_json'],row['saved_at']))
                    try:
                        item=json.loads(row['metadata_json']);identifier=int(row['anilist_id'])
                        if not isinstance(item,dict) or item.get('isAdult') is not True:raise ValueError('not an adult AniList record')
                    except (ValueError,TypeError):
                        self.restricted_saved_planning_report['skipped']+=1;continue
                    keys=[f'anilist:{identifier}']
                    keys.extend(f"local:{r[0]}" for r in self.connection.execute('SELECT id FROM anime WHERE anilist_id=?',(identifier,)))
                    keys.extend(f"manga:{r[0]}" for r in self.connection.execute("SELECT id FROM manga_series WHERE anilist_id=? AND scope='restricted'",(identifier,)))
                    existing=self.connection.execute("SELECT 1 FROM manual_status WHERE scope='restricted' AND entity_key IN ("+','.join('?' for _ in keys)+") AND status IN ('Watching','Completed','Planning','Paused','Dropped') LIMIT 1",keys).fetchone()
                    if existing:self.restricted_saved_planning_report['preserved_status']+=1
                    else:
                        self.connection.execute("INSERT INTO manual_status(scope,entity_key,status,metadata_json) VALUES('restricted',?,'Planning',?) ON CONFLICT(scope,entity_key) DO UPDATE SET status='Planning'",(keys[0],row['metadata_json']))
                        self.restricted_saved_planning_report['migrated']+=1
                    self.connection.execute("DELETE FROM saved_titles WHERE scope='restricted' AND anilist_id=?",(identifier,))
                self.connection.execute("INSERT INTO settings(key,value) VALUES('restricted_saved_planning_v0881','1') ON CONFLICT(key) DO UPDATE SET value='1'")

    def audit_integrity(self,deep=False):
        """Read-only support audit. Ambiguous aliases and user records are never removed."""
        connection=self.connection
        checks={
          'orphan_collection_items':"SELECT COUNT(*) FROM collection_items ci LEFT JOIN collections c ON c.id=ci.collection_id LEFT JOIN anime a ON a.id=ci.anime_id WHERE c.id IS NULL OR a.id IS NULL",
          'orphan_collection_entries':"SELECT COUNT(*) FROM collection_entries ce LEFT JOIN collections c ON c.id=ce.collection_id WHERE c.id IS NULL",
          'orphan_franchise_items':"SELECT COUNT(*) FROM franchise_items fi LEFT JOIN franchises f ON f.id=fi.franchise_id LEFT JOIN anime a ON a.id=fi.anime_id WHERE f.id IS NULL OR a.id IS NULL",
          'orphan_manga_items':"SELECT COUNT(*) FROM manga_items i LEFT JOIN manga_series s ON s.id=i.series_id WHERE s.id IS NULL",
          'orphan_bookmarks':"SELECT COUNT(*) FROM manga_bookmarks b LEFT JOIN manga_reader_state s ON s.identity=b.identity WHERE s.identity IS NULL",
          'invalid_status_rows':"SELECT COUNT(*) FROM manual_status WHERE scope NOT IN ('normal','restricted') OR status NOT IN ('Watching','Completed','Planning','Paused','Dropped')",
          'invalid_reader_state':"SELECT COUNT(*) FROM manga_reader_state WHERE current_page<1 OR total_pages<0 OR (total_pages>0 AND current_page>total_pages) OR percent_complete<0 OR percent_complete>100 OR completed NOT IN (0,1) OR scope NOT IN ('normal','restricted')",
        }
        result={key:connection.execute(query).fetchone()[0] for key,query in checks.items()}
        result['duplicate_status_keys']=connection.execute('SELECT COUNT(*) FROM (SELECT scope,entity_key FROM manual_status GROUP BY scope,entity_key HAVING COUNT(*)>1)').fetchone()[0]
        result['duplicate_collection_keys']=connection.execute('SELECT COUNT(*) FROM (SELECT collection_id,entity_key FROM collection_entries GROUP BY collection_id,entity_key HAVING COUNT(*)>1)').fetchone()[0]
        result['foreign_key_errors']=len(connection.execute('PRAGMA foreign_key_check').fetchall())
        if deep:result['sqlite_integrity']=connection.execute('PRAGMA integrity_check').fetchone()[0]
        return result

    def setting(self, key: str, default=""):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value):
        self.connection.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.connection.commit()

    def save_title(self,item,scope="normal"):
        if scope=="restricted" and item.get("isAdult") is not True:raise ValueError("Restricted Saved only accepts titles explicitly marked adult by AniList.")
        if scope=="normal" and item.get("isAdult") is True:raise ValueError("Adult titles belong in Restricted Saved.")
        anilist_id=int(item["id"]); titles=item.get("title") or {}; title=titles.get("english") or titles.get("romaji") or "Untitled"
        self.connection.execute("""INSERT INTO saved_titles(anilist_id,scope,title,metadata_json) VALUES(?,?,?,?)
          ON CONFLICT(scope,anilist_id) DO UPDATE SET title=excluded.title,metadata_json=excluded.metadata_json""",
          (anilist_id,scope,title,json.dumps(item))); self.connection.commit()

    def unsave_title(self,anilist_id,scope="normal"):
        cursor=self.connection.execute("DELETE FROM saved_titles WHERE anilist_id=? AND scope=?",(int(anilist_id),scope)); self.connection.commit(); return bool(cursor.rowcount)

    def is_saved(self,anilist_id,scope="normal"):
        return self.connection.execute("SELECT 1 FROM saved_titles WHERE anilist_id=? AND scope=?",(int(anilist_id),scope)).fetchone() is not None

    def saved_titles(self,sort="Recently Saved",scope="normal"):
        order={"Title":"title COLLATE NOCASE","Year":"json_extract(metadata_json,'$.seasonYear') DESC",
               "Score":"json_extract(metadata_json,'$.averageScore') DESC","Popularity":"json_extract(metadata_json,'$.popularity') DESC",
               "Recently Saved":"saved_at DESC"}.get(sort,"saved_at DESC")
        return self.connection.execute(f"SELECT * FROM saved_titles WHERE scope=? ORDER BY {order}",(scope,)).fetchall()

    @staticmethod
    def source_key(source,external_id):
        source=str(source);external_id=str(external_id)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}",source) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",external_id):
            raise ValueError("Invalid restricted source identity.")
        return f"source:{source}:{external_id}"

    def save_source_gallery(self,item):
        source=item["source"];external_id=item["external_id"];self.source_key(source,external_id)
        item=self._merge_source_metadata(self.cached_source_item(source,external_id),item)
        self.connection.execute("""INSERT INTO restricted_source_saved(source,external_id,metadata_json,last_visited_at) VALUES(?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(source,external_id) DO UPDATE SET metadata_json=excluded.metadata_json,last_visited_at=CURRENT_TIMESTAMP""",
          (source,str(external_id),json.dumps(item)));self.connection.commit()

    def touch_source_gallery(self,item):
        self.source_key(item["source"],item["external_id"])
        item=self._merge_source_metadata(self.cached_source_item(item["source"],item["external_id"]),item)
        self.connection.execute("""UPDATE restricted_source_saved SET last_visited_at=CURRENT_TIMESTAMP,
          metadata_json=? WHERE source=? AND external_id=?""",
          (json.dumps(item),item["source"],str(item["external_id"])));self.connection.commit()

    def unsave_source_gallery(self,source,external_id):
        self.source_key(source,external_id)
        self.connection.execute("DELETE FROM restricted_source_saved WHERE source=? AND external_id=?",(source,str(external_id)));self.connection.commit()

    def is_source_saved(self,source,external_id):
        self.source_key(source,external_id)
        return self.connection.execute("SELECT 1 FROM restricted_source_saved WHERE source=? AND external_id=?",(source,str(external_id))).fetchone() is not None

    def source_saved(self):
        return self.connection.execute("SELECT * FROM restricted_source_saved ORDER BY saved_at DESC").fetchall()

    def cache_source_items(self,items):
        rows=[]
        for item in items:
            try:key=self.source_key(item["source"],item["external_id"])
            except (KeyError,ValueError):continue
            item=self._merge_source_metadata(self.cached_source_item(item["source"],item["external_id"]),item)
            rows.append((item["source"],str(item["external_id"]),json.dumps(item)))
        if rows:
            self.connection.executemany("""INSERT INTO restricted_source_metadata(source,external_id,metadata_json)
              VALUES(?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET
              metadata_json=excluded.metadata_json,cached_at=CURRENT_TIMESTAMP""",rows)
            self.connection.commit()
        return len(rows)

    @staticmethod
    def _merge_source_metadata(previous,item):
        if not previous:return dict(item)
        merged=dict(previous)
        for key,value in item.items():
            if key=="title" and previous.get("metadata_provider") and not item.get("metadata_provider"):
                continue
            if value not in (None,"",0,[],{}):merged[key]=value
        if item.get("tags"):
            tags=dict(previous.get("tags") or {})
            for key,value in item["tags"].items():
                if value:tags[key]=value
            merged["tags"]=tags
        return merged

    def cached_source_item(self,source,external_id):
        self.source_key(source,external_id)
        row=self.connection.execute("SELECT metadata_json FROM restricted_source_metadata WHERE source=? AND external_id=?",(source,str(external_id))).fetchone()
        return json.loads(row[0]) if row else None

    def source_recent(self,source,limit=30):
        rows=self.connection.execute("""SELECT m.metadata_json FROM restricted_source_history h
          JOIN restricted_source_metadata m ON m.source=h.source AND m.external_id=h.external_id
          WHERE h.source=? ORDER BY h.last_visited_at DESC LIMIT ?""",(source,max(1,int(limit)))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def source_cached(self,source,limit=120):
        rows=self.connection.execute("SELECT metadata_json FROM restricted_source_metadata WHERE source=? ORDER BY cached_at DESC LIMIT ?",(source,max(1,int(limit)))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def source_cache_count(self,source):
        return self.connection.execute("SELECT count(*) FROM restricted_source_metadata WHERE source=?",(source,)).fetchone()[0]

    def source_cached_search(self,source,query="",field="title",limit=500):
        """Search only the restricted source cache, without touching normal Saved."""
        allowed={"title","tags","artist","group","parody","character","language"}
        if field not in allowed:raise ValueError("Unsupported cached metadata filter")
        needle=query.strip().casefold();result=[]
        # Bound UI output, but inspect every cached row so recent nonmatches do not hide older matches.
        rows=self.connection.execute("SELECT metadata_json FROM restricted_source_metadata WHERE source=? ORDER BY cached_at DESC,external_id DESC",(source,))
        for row in rows:
            try:item=json.loads(row[0])
            except (ValueError,TypeError):continue
            values=[item.get("title","")] if field=="title" else (item.get("tags") or {}).get("tag" if field=="tags" else field,[])
            if not isinstance(values,list):values=[values]
            if not needle or needle==str(item.get("external_id","")) or any(needle in str(value).casefold() for value in values):
                result.append(item)
                if len(result)>=limit:break
        return result

    def source_activity(self,source,limit=40):
        """Private source signals only; never query the normal recommendation store."""
        rows=self.connection.execute("""SELECT m.metadata_json,stamp FROM (
          SELECT source,external_id,saved_at stamp FROM restricted_source_saved
          UNION ALL SELECT source,external_id,last_visited_at stamp FROM restricted_source_history
          UNION ALL SELECT substr(entity_key,8,instr(substr(entity_key,8),':')-1) source,
            substr(entity_key,8+instr(substr(entity_key,8),':')) external_id,updated_at stamp
            FROM manual_status WHERE scope='restricted' AND status IN ('Watching','Completed','Planning') AND entity_key LIKE 'source:%'
          ) activity JOIN restricted_source_metadata m
          ON m.source=activity.source AND m.external_id=activity.external_id
          WHERE activity.source=? ORDER BY stamp DESC LIMIT ?""",(source,max(1,int(limit))*3)).fetchall()
        seen=set();result=[]
        for row in rows:
            item=json.loads(row[0]);key=(item.get("source"),item.get("external_id"))
            if self.source_status(key[0],key[1])=="Dropped":continue
            if key not in seen:seen.add(key);result.append(item)
            if len(result)>=limit:break
        return result

    def record_source_visit(self,item):
        self.cache_source_items([item]);source=item["source"];external_id=str(item["external_id"])
        self.connection.execute("""INSERT INTO restricted_source_history(source,external_id) VALUES(?,?)
          ON CONFLICT(source,external_id) DO UPDATE SET last_visited_at=CURRENT_TIMESTAMP,
          visit_count=visit_count+1""",(source,external_id))
        self.connection.commit()
        self.touch_source_gallery(item)

    def reading_progress(self,source,external_id):
        self.source_key(source,external_id)
        return self.connection.execute("SELECT * FROM restricted_reading_progress WHERE source=? AND external_id=?",(source,str(external_id))).fetchone()

    def set_reading_progress(self,source,external_id,page,total):
        self.source_key(source,external_id);page=max(1,int(page));total=max(0,int(total))
        self.connection.execute("""INSERT INTO restricted_reading_progress(source,external_id,last_page,total_pages,completed)
          VALUES(?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET
          last_page=excluded.last_page,total_pages=excluded.total_pages,completed=excluded.completed,
          last_read_at=CURRENT_TIMESTAMP""",(source,str(external_id),page,total,int(total>0 and page>=total)))
        self.connection.commit()

    def source_status(self,source,external_id):
        key=self.source_key(source,external_id)
        row=self.connection.execute("SELECT status FROM manual_status WHERE scope='restricted' AND entity_key=?",(key,)).fetchone()
        return row[0] if row else None

    def set_source_status(self,item,status):
        key=self.source_key(item["source"],item["external_id"])
        if status and status not in {"Watching","Completed","Planning","Paused","Dropped"}:raise ValueError("Unknown manual status.")
        if status:
            self.connection.execute("""INSERT INTO manual_status(scope,entity_key,status,metadata_json) VALUES('restricted',?,?,?)
              ON CONFLICT(scope,entity_key) DO UPDATE SET status=excluded.status,metadata_json=excluded.metadata_json,updated_at=CURRENT_TIMESTAMP""",
              (key,status,json.dumps(item)))
        else:self.connection.execute("DELETE FROM manual_status WHERE scope='restricted' AND entity_key=?",(key,))
        self.connection.commit();return key

    def add_source_to_collection(self,collection_id,item):
        collection=self.collection(collection_id)
        if not collection or collection["scope"]!="restricted":raise ValueError("A Restricted Collection is required.")
        key=self.source_key(item["source"],item["external_id"])
        cursor=self.connection.execute("INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)",
                                        (collection_id,key,json.dumps(item)))
        self.connection.commit();return bool(cursor.rowcount)

    def start_scan(self):
        self.connection.execute("UPDATE media SET present=0")

    def upsert_anime(self, identity, title, alt_title, category, root_path,
                     source_folder_name="", parsed_search_title="", detected_season=None,
                     detected_year=None):
        self.connection.execute("""INSERT INTO anime(identity,title,alt_title,category,root_path,
            source_folder_name,parsed_search_title,detected_season,detected_year) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(identity) DO UPDATE SET title=excluded.title,
            alt_title=excluded.alt_title,category=excluded.category,
            root_path=excluded.root_path,
            source_folder_name=excluded.source_folder_name,
            parsed_search_title=excluded.parsed_search_title,
            detected_season=excluded.detected_season,detected_year=excluded.detected_year""",
            (identity, title, alt_title, category, root_path, source_folder_name,
             parsed_search_title, detected_season, detected_year))
        return self.connection.execute("SELECT id FROM anime WHERE identity=?", (identity,)).fetchone()[0]

    def upsert_media(self, anime_id, parsed):
        override = self.connection.execute("SELECT kind FROM overrides WHERE path=?", (str(parsed.path),)).fetchone()
        kind = override[0] if override else parsed.kind
        file_info = parsed.path.stat()
        modified = file_info.st_mtime
        current=self.connection.execute("SELECT id FROM media WHERE path=?",(str(parsed.path),)).fetchone()
        if current is None:
            relocated=self.connection.execute("""SELECT id,path FROM media WHERE anime_id=? AND present=0 AND kind=?
              AND COALESCE(season,-1)=COALESCE(?,-1) AND COALESCE(episode,-1)=COALESCE(?,-1)""",
              (anime_id,kind,parsed.season,parsed.episode)).fetchall()
            if len(relocated)==1:
                old_path=relocated[0]["path"]
                self.connection.execute("""UPDATE media SET path=?,kind=?,season=?,episode=?,detected_kind=?,present=1,modified=?,size_bytes=? WHERE id=?""",
                                        (str(parsed.path),kind,parsed.season,parsed.episode,parsed.kind,modified,file_info.st_size,relocated[0]["id"]))
                self.connection.execute("UPDATE overrides SET path=? WHERE path=?",(str(parsed.path),old_path))
                return
        self.connection.execute("""INSERT INTO media(anime_id,path,kind,season,episode,detected_kind,present,modified,size_bytes)
          VALUES(?,?,?,?,?,?,1,?,?) ON CONFLICT(path) DO UPDATE SET anime_id=excluded.anime_id,
          kind=CASE WHEN EXISTS(SELECT 1 FROM overrides WHERE path=excluded.path)
               THEN (SELECT kind FROM overrides WHERE path=excluded.path) ELSE excluded.kind END,
          season=excluded.season,episode=excluded.episode,detected_kind=excluded.detected_kind,
          present=1,modified=excluded.modified,size_bytes=excluded.size_bytes""",
          (anime_id, str(parsed.path), kind, parsed.season, parsed.episode, parsed.kind, modified, file_info.st_size))

    def finish_scan(self):
        self.connection.execute("DELETE FROM media WHERE present=0")
        self.connection.execute("DELETE FROM anime WHERE NOT EXISTS(SELECT 1 FROM media WHERE media.anime_id=anime.id)")
        self.connection.commit()

    def personal_rating(self, kind, identifier):
        table={'ANIME':'anime','MANGA':'manga_series'}[kind]
        row=self.connection.execute(f'SELECT personal_rating_units FROM {table} WHERE id=?',(identifier,)).fetchone()
        return row[0] if row else None

    def set_personal_rating(self, kind, identifier, value):
        from .ratings import rating_units
        table={'ANIME':'anime','MANGA':'manga_series'}[kind]
        with self.connection:
            self.connection.execute(f'UPDATE {table} SET personal_rating_units=? WHERE id=?',(rating_units(value),identifier))

    def anime_list(self):
        return self.connection.execute("""SELECT a.*, COUNT(m.id) media_count,
          SUM(CASE WHEN m.kind='episode' THEN 1 ELSE 0 END) episode_count,
          SUM(CASE WHEN m.kind='episode' AND m.watched=1 THEN 1 ELSE 0 END) watched_count,
          SUM(CASE WHEN m.kind<>'episode' AND m.kind<>'ignore' THEN 1 ELSE 0 END) extras_count
          FROM anime a LEFT JOIN media m ON m.anime_id=a.id GROUP BY a.id ORDER BY a.title COLLATE NOCASE""").fetchall()

    def anime(self, anime_id):
        return self.connection.execute("SELECT * FROM anime WHERE id=?", (anime_id,)).fetchone()

    def change_stamp(self):
        """Include commits from scanner/other connections when caching UI projections."""
        return self.connection.total_changes, self.connection.execute('PRAGMA data_version').fetchone()[0]

    def anime_scope(self, anime, fresh=True):
        """Explicit AniList adult metadata is the rule, never folder/category or Ecchi.

        Refresh stale row objects by ID. For legacy incomplete metadata, use known
        adult cached matches by the same AniList ID; unmatched unknowns stay normal.
        """
        row = self.anime(anime if isinstance(anime, int) else anime['id']) if fresh else anime
        if row is None:
            return None
        try: item = json.loads(row['metadata_json'] or '{}')
        except (ValueError, TypeError): item = {}
        if type(item.get('isAdult')) is bool:
            return 'restricted' if item['isAdult'] else 'normal'
        if not row['anilist_id']:
            return 'normal'
        stamp = self.change_stamp()
        cached = getattr(self, '_adult_match_cache', None)
        if not cached or cached[0] != stamp:
            identifiers = set()
            values = [r[0] for r in self.connection.execute('SELECT metadata_json FROM saved_titles UNION ALL SELECT metadata_json FROM manual_status')]
            try:
                values.extend(json.dumps(entry.get('media') or {}) for entry in json.loads(self.setting('anilist_user_list_cache', '[]')))
            except (ValueError, TypeError, AttributeError): pass
            for value in values:
                try:
                    known = json.loads(value or '{}')
                    if known.get('isAdult') is True and known.get('type') != 'MANGA' and known.get('id'):
                        identifiers.add(int(known['id']))
                except (ValueError, TypeError, AttributeError): pass
            cached = (stamp, identifiers)
            self._adult_match_cache = cached
        return 'restricted' if row['anilist_id'] in cached[1] else 'normal'

    def anime_scope_map(self, rows):
        """Batch projection for already-fresh catalog rows, without per-card queries."""
        return {row['id']: self.anime_scope(row, fresh=False) for row in rows}

    def observe_classifications(self, items, allow_normal=True):
        """Reconcile trusted AniList responses into matched rows, preserving all state/art."""
        changed = 0
        for item in items:
            if item.get('type') == 'MANGA' or not item.get('id') or type(item.get('isAdult')) is not bool:
                continue
            for row in self.connection.execute('SELECT id,metadata_json FROM anime WHERE anilist_id=?', (item['id'],)).fetchall():
                try: previous = json.loads(row['metadata_json'] or '{}')
                except (ValueError, TypeError): previous = {}
                if not allow_normal and item['isAdult'] is False and type(previous.get('isAdult')) is bool:
                    continue
                if previous.get('isAdult') is not item['isAdult']:
                    previous['isAdult'] = item['isAdult']
                    self.connection.execute('UPDATE anime SET metadata_json=? WHERE id=?', (json.dumps(previous), row['id']))
                    changed += 1
        if changed: self.connection.commit()
        return changed

    @staticmethod
    def _entity_key(anime_id=None,anilist_id=None):
        if anilist_id is not None:return f"anilist:{int(anilist_id)}"
        if anime_id is not None:return f"local:{int(anime_id)}"
        raise ValueError("An anime identity is required.")

    def entity_key_for_anime(self,anime_id):
        row=self.anime(anime_id)
        if not row:raise ValueError("Anime no longer exists.")
        return self._entity_key(anime_id,row["anilist_id"])

    def collections(self, sort="Recently Created",scope="normal"):
        order={"Name":"c.name COLLATE NOCASE", "Recently Updated":"c.updated_at DESC",
               "Recently Created":"c.created_at DESC"}.get(sort,"c.created_at DESC")
        return self.connection.execute(f"""SELECT c.*, COUNT(ce.entity_key) item_count,
          (SELECT x.metadata_json FROM collection_entries x WHERE x.collection_id=c.id ORDER BY x.added_at DESC LIMIT 1) preview_metadata
          FROM collections c LEFT JOIN collection_entries ce ON ce.collection_id=c.id
          WHERE c.scope=? GROUP BY c.id ORDER BY {order}""",(scope,)).fetchall()

    def collection(self, collection_id):
        return self.connection.execute("SELECT * FROM collections WHERE id=?",(collection_id,)).fetchone()

    def create_collection(self, name, description="",scope="normal"):
        name=(name or "").strip(); description=(description or "").strip()
        if not name: raise ValueError("Collection name cannot be empty.")
        try:
            cursor=self.connection.execute("INSERT INTO collections(name,description,scope) VALUES(?,?,?)",(name,description,scope))
            self.connection.commit(); return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A collection named "{name}" already exists.') from exc

    def rename_collection(self, collection_id, name):
        name=(name or "").strip()
        if not name: raise ValueError("Collection name cannot be empty.")
        try:
            cursor=self.connection.execute("UPDATE collections SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(name,collection_id))
            if not cursor.rowcount: raise ValueError("Collection no longer exists.")
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'A collection named "{name}" already exists.') from exc

    def set_collection_description(self, collection_id, description):
        cursor=self.connection.execute("UPDATE collections SET description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                       ((description or "").strip(),collection_id))
        if not cursor.rowcount: raise ValueError("Collection no longer exists.")
        self.connection.commit()

    def delete_collection(self, collection_id):
        self.connection.execute("DELETE FROM collections WHERE id=?",(collection_id,)); self.connection.commit()

    def add_to_collection(self, collection_id, anime_id):
        anime=self.anime(anime_id)
        if not anime:return False
        collection=self.collection(collection_id)
        item=json.loads(anime['metadata_json'] or '{}')
        if not collection or (item.get('isAdult') is True)!=(collection['scope']=='restricted'):
            raise ValueError('Collection scope must match this anime.')
        key=self._entity_key(anime_id,anime["anilist_id"])
        if self.connection.execute('SELECT 1 FROM collection_entries WHERE collection_id=? AND entity_key IN (?,?)',(collection_id,key,f'local:{anime_id}')).fetchone():return False
        if anime['anilist_id'] and self.connection.execute("SELECT 1 FROM collection_entries WHERE collection_id=? AND entity_key IN (SELECT 'local:'||id FROM anime WHERE anilist_id=?) LIMIT 1",(collection_id,anime['anilist_id'])).fetchone():return False
        cursor=self.connection.execute("INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)",(collection_id,key,anime["metadata_json"] or "{}"))
        if cursor.rowcount:
            self.connection.execute("UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(collection_id,))
        self.connection.commit(); return bool(cursor.rowcount)

    def remove_from_collection(self, collection_id, anime_id):
        key=self.entity_key_for_anime(anime_id);cursor=self.connection.execute("DELETE FROM collection_entries WHERE collection_id=? AND entity_key=?",(collection_id,key))
        if cursor.rowcount:
            self.connection.execute("UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(collection_id,))
        self.connection.commit(); return bool(cursor.rowcount)

    def anime_collection_ids(self, anime_id):
        key=self.entity_key_for_anime(anime_id)
        return {row[0] for row in self.connection.execute("SELECT collection_id FROM collection_entries WHERE entity_key=?",(key,))}

    def add_remote_to_collection(self,collection_id,item):
        collection=self.collection(collection_id)
        if not collection:return False
        if collection["scope"]=="restricted" and item.get("isAdult") is not True:raise ValueError("Restricted Collections only accept titles explicitly marked adult by AniList.")
        if collection["scope"]=="normal" and item.get("isAdult") is True:raise ValueError("Adult titles belong in Restricted Collections.")
        key=self._entity_key(anilist_id=item["id"])
        if item.get('type')=='MANGA':
            exists=self.connection.execute("SELECT 1 FROM collection_entries WHERE collection_id=? AND entity_key IN (SELECT 'manga:'||id FROM manga_series WHERE anilist_id=? AND scope=?) LIMIT 1",(collection_id,item['id'],collection['scope'])).fetchone()
            if exists:return False
        cursor=self.connection.execute("INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)",(collection_id,key,json.dumps(item)))
        if cursor.rowcount:self.connection.execute("UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(collection_id,))
        self.connection.commit();return bool(cursor.rowcount)

    def remove_entity_from_collection(self,collection_id,entity_key):
        cursor=self.connection.execute("DELETE FROM collection_entries WHERE collection_id=? AND entity_key=?",(collection_id,entity_key))
        if cursor.rowcount:self.connection.execute("UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(collection_id,))
        self.connection.commit();return bool(cursor.rowcount)

    def entity_collection_ids(self,entity_key):
        return {row[0] for row in self.connection.execute("SELECT collection_id FROM collection_entries WHERE entity_key=?",(entity_key,))}

    def set_manual_status(self,status,scope="normal",anime_id=None,item=None):
        allowed={"Watching","Completed","Planning","Paused","Dropped"}
        if anime_id is not None:
            anime=self.anime(anime_id)
            if not anime:raise ValueError("Anime no longer exists.")
            key=self._entity_key(anime_id,anime["anilist_id"]);metadata=anime["metadata_json"] or "{}"
        elif item is not None:
            if scope=="restricted" and item.get("isAdult") is not True:raise ValueError("Restricted statuses only accept titles explicitly marked adult by AniList.")
            if scope=="normal" and item.get("isAdult") is True:raise ValueError("Adult-title statuses belong in Restricted Archive.")
            key=self._entity_key(anilist_id=item["id"]);metadata=json.dumps(item)
        else:raise ValueError("Anime identity is required.")
        if not status:
            self.connection.execute("DELETE FROM manual_status WHERE scope=? AND entity_key=?",(scope,key))
        elif status not in allowed:raise ValueError("Unknown manual status.")
        else:
            self.connection.execute("""INSERT INTO manual_status(scope,entity_key,status,metadata_json) VALUES(?,?,?,?)
              ON CONFLICT(scope,entity_key) DO UPDATE SET status=excluded.status,metadata_json=excluded.metadata_json,updated_at=CURRENT_TIMESTAMP""",(scope,key,status,metadata))
        self.connection.commit();return key

    def manual_status(self,scope="normal",anime_id=None,anilist_id=None):
        key=self._entity_key(anime_id,anilist_id)
        if anime_id is not None:
            row=self.anime(anime_id)
            if row and row["anilist_id"] is not None:key=self._entity_key(anilist_id=row["anilist_id"])
        row=self.connection.execute("SELECT status FROM manual_status WHERE scope=? AND entity_key=?",(scope,key)).fetchone()
        return row[0] if row else None

    def status_entries(self,status,scope="normal"):
        return self.connection.execute("SELECT * FROM manual_status WHERE scope=? AND status=? ORDER BY updated_at DESC",(scope,status)).fetchall()

    def recommendation_items(self,scope="normal",limit=20):
        """Scoped discovery signals only; never crosses normal/restricted boundaries."""
        rows=self.connection.execute("""SELECT metadata_json,updated_at stamp FROM manual_status WHERE scope=?
          UNION ALL SELECT metadata_json,saved_at stamp FROM saved_titles WHERE scope=?
          ORDER BY stamp DESC LIMIT ?""",(scope,scope,int(limit))).fetchall();seen=set();items=[]
        for row in rows:
            try:item=json.loads(row["metadata_json"] or "{}")
            except (TypeError,ValueError):continue
            media_id=item.get("id")
            if media_id is None or media_id in seen:continue
            seen.add(media_id);items.append(item)
        return items

    def collection_anime(self, collection_id, sort="Date Added"):
        order={"Title":"a.title COLLATE NOCASE", "Year":"COALESCE(a.detected_year,0) DESC",
               "Recently Watched":"a.last_watched_at DESC", "Date Added":"ci.added_at DESC"}.get(sort,"ci.added_at DESC")
        return self.connection.execute(f"""SELECT a.*, ci.added_at collection_added_at,
          COUNT(m.id) media_count,
          SUM(CASE WHEN m.kind='episode' THEN 1 ELSE 0 END) episode_count,
          SUM(CASE WHEN m.kind='episode' AND m.watched=1 THEN 1 ELSE 0 END) watched_count,
          SUM(CASE WHEN m.kind<>'episode' AND m.kind<>'ignore' THEN 1 ELSE 0 END) extras_count
          FROM collection_entries ci JOIN anime a ON
            (ci.entity_key='local:'||a.id OR (a.anilist_id IS NOT NULL AND ci.entity_key='anilist:'||a.anilist_id))
          LEFT JOIN media m ON m.anime_id=a.id WHERE ci.collection_id=?
          GROUP BY a.id ORDER BY {order}""",(collection_id,)).fetchall()

    def collection_entries(self,collection_id):
        rows=self.connection.execute("SELECT * FROM collection_entries WHERE collection_id=? ORDER BY added_at DESC",(collection_id,)).fetchall();result=[]
        for row in rows:
            key=row["entity_key"];local=None
            if key.startswith("anilist:"):local=self.connection.execute("SELECT * FROM anime WHERE anilist_id=?",(int(key.split(':',1)[1]),)).fetchone()
            elif key.startswith("local:"):local=self.anime(int(key.split(':',1)[1]))
            result.append({"entity_key":key,"metadata_json":row["metadata_json"],"added_at":row["added_at"],"local":local})
        return result

    def franchises(self):
        return self.connection.execute("""SELECT f.*,COUNT(fi.anime_id) item_count,
          (SELECT a.metadata_json FROM franchise_items x JOIN anime a ON a.id=x.anime_id
           WHERE x.franchise_id=f.id ORDER BY x.sort_order LIMIT 1) preview_metadata
          FROM franchises f LEFT JOIN franchise_items fi ON fi.franchise_id=f.id
          GROUP BY f.id ORDER BY f.name COLLATE NOCASE""").fetchall()

    def franchise(self, franchise_id):
        return self.connection.execute("SELECT * FROM franchises WHERE id=?",(franchise_id,)).fetchone()

    def create_franchise(self,name,description=""):
        name=(name or "").strip(); description=(description or "").strip()
        if not name: raise ValueError("Franchise name cannot be empty.")
        try:
            cursor=self.connection.execute("INSERT INTO franchises(name,description) VALUES(?,?)",(name,description)); self.connection.commit(); return cursor.lastrowid
        except sqlite3.IntegrityError as exc: raise ValueError(f'A franchise named "{name}" already exists.') from exc

    def update_franchise(self,franchise_id,name=None,description=None):
        current=self.franchise(franchise_id)
        if not current: raise ValueError("Franchise no longer exists.")
        name=current["name"] if name is None else name.strip(); description=current["description"] if description is None else description.strip()
        if not name: raise ValueError("Franchise name cannot be empty.")
        try:
            self.connection.execute("UPDATE franchises SET name=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(name,description,franchise_id)); self.connection.commit()
        except sqlite3.IntegrityError as exc: raise ValueError(f'A franchise named "{name}" already exists.') from exc

    def delete_franchise(self,franchise_id):
        self.connection.execute("DELETE FROM franchises WHERE id=?",(franchise_id,)); self.connection.commit()

    def anime_franchise(self,anime_id):
        return self.connection.execute("""SELECT f.*,fi.sort_order,fi.relation_type FROM franchise_items fi
          JOIN franchises f ON f.id=fi.franchise_id WHERE fi.anime_id=?""",(anime_id,)).fetchone()

    def add_to_franchise(self,franchise_id,anime_id,relation_type=""):
        existing=self.anime_franchise(anime_id)
        if existing:
            if existing["id"]==franchise_id: return False
            raise ValueError(f'This anime already belongs to "{existing["name"]}".')
        order=self.connection.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM franchise_items WHERE franchise_id=?",(franchise_id,)).fetchone()[0]
        self.connection.execute("INSERT INTO franchise_items(franchise_id,anime_id,sort_order,relation_type) VALUES(?,?,?,?)",(franchise_id,anime_id,order,relation_type or ""))
        self.connection.execute("UPDATE franchises SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(franchise_id,)); self.connection.commit(); return True

    def remove_from_franchise(self,franchise_id,anime_id):
        cursor=self.connection.execute("DELETE FROM franchise_items WHERE franchise_id=? AND anime_id=?",(franchise_id,anime_id)); self._normalize_franchise_order(franchise_id); self.connection.commit(); return bool(cursor.rowcount)

    def move_franchise_item(self,franchise_id,anime_id,direction):
        rows=self.connection.execute("SELECT anime_id FROM franchise_items WHERE franchise_id=? ORDER BY sort_order,anime_id",(franchise_id,)).fetchall(); ids=[r[0] for r in rows]
        if anime_id not in ids: return False
        old=ids.index(anime_id); new=old+(-1 if direction<0 else 1)
        if not 0<=new<len(ids): return False
        ids[old],ids[new]=ids[new],ids[old]
        for order,item_id in enumerate(ids): self.connection.execute("UPDATE franchise_items SET sort_order=? WHERE franchise_id=? AND anime_id=?",(order,franchise_id,item_id))
        self.connection.commit(); return True

    def _normalize_franchise_order(self,franchise_id):
        rows=self.connection.execute("SELECT anime_id FROM franchise_items WHERE franchise_id=? ORDER BY sort_order,anime_id",(franchise_id,)).fetchall()
        for order,row in enumerate(rows): self.connection.execute("UPDATE franchise_items SET sort_order=? WHERE franchise_id=? AND anime_id=?",(order,franchise_id,row[0]))

    def franchise_anime(self,franchise_id):
        return self.connection.execute("""SELECT a.*,fi.sort_order,fi.relation_type,
          COUNT(m.id) media_count,SUM(CASE WHEN m.kind='episode' THEN 1 ELSE 0 END) episode_count,
          SUM(CASE WHEN m.kind='episode' AND m.watched=1 THEN 1 ELSE 0 END) watched_count,
          SUM(CASE WHEN m.kind<>'episode' AND m.kind<>'ignore' THEN 1 ELSE 0 END) extras_count
          FROM franchise_items fi JOIN anime a ON a.id=fi.anime_id LEFT JOIN media m ON m.anime_id=a.id
          WHERE fi.franchise_id=? GROUP BY a.id ORDER BY fi.sort_order,a.title COLLATE NOCASE""",(franchise_id,)).fetchall()

    def media(self, anime_id):
        return self.connection.execute("""SELECT * FROM media WHERE anime_id=? AND kind<>'ignore' ORDER BY
          COALESCE(season,999), COALESCE(episode,999), path COLLATE NOCASE""", (anime_id,)).fetchall()

    def set_metadata(self, anime_id, anilist_id, metadata):
        self.connection.execute("UPDATE anime SET anilist_id=?, metadata_json=? WHERE id=?",
                                (anilist_id, json.dumps(metadata), anime_id))
        self.connection.commit()

    def merge_anilist_list(self, entries):
        """Attach remote list hints to matched metadata without changing local watch state."""
        by_id={int(entry["media"]["id"]):entry for entry in entries if entry.get("media") and entry["media"].get("id")}
        changed=0
        for row in self.connection.execute("SELECT id,anilist_id,metadata_json FROM anime WHERE anilist_id IS NOT NULL").fetchall():
            entry=by_id.get(int(row["anilist_id"]))
            if not entry: continue
            metadata=json.loads(row["metadata_json"] or "{}")
            metadata["anilist_user_status"]=entry.get("status")
            metadata["anilist_user_progress"]=entry.get("progress") or 0
            self.connection.execute("UPDATE anime SET metadata_json=? WHERE id=?",(json.dumps(metadata),row["id"]))
            changed+=1
        self.connection.commit()
        return changed

    def set_anilist_user_progress(self, anime_id, progress, status=None):
        row=self.anime(anime_id)
        if not row: return
        metadata=json.loads(row["metadata_json"] or "{}")
        metadata["anilist_user_progress"]=max(0,int(progress or 0))
        if status: metadata["anilist_user_status"]=status
        self.connection.execute("UPDATE anime SET metadata_json=? WHERE id=?",(json.dumps(metadata),anime_id))
        self.connection.commit()

    def anime_progress(self, anime_id):
        row=self.connection.execute("""SELECT COUNT(*) total,
          SUM(CASE WHEN watched=1 THEN 1 ELSE 0 END) watched
          FROM media WHERE anime_id=? AND kind='episode'""",(anime_id,)).fetchone()
        return int(row["watched"] or 0),int(row["total"] or 0)

    def override(self, path, kind):
        self.connection.execute("INSERT INTO overrides VALUES(?,?) ON CONFLICT(path) DO UPDATE SET kind=excluded.kind", (path, kind))
        self.connection.execute("UPDATE media SET kind=? WHERE path=?", (kind, path))
        self.connection.commit()

    def set_watched(self, media_id, watched):
        row = self.connection.execute("SELECT anime_id, episode, kind FROM media WHERE id=?", (media_id,)).fetchone()
        if not row or row["kind"] != "episode":
            return
        now = datetime.now(timezone.utc).isoformat() if watched else None
        self.connection.execute("UPDATE media SET watched=?, watched_at=?, resume_position_ms=CASE WHEN ? THEN 0 ELSE resume_position_ms END WHERE id=?", (int(watched), now, int(watched), media_id))
        self._refresh_last_watched(row["anime_id"])
        self.connection.commit()

    def set_watched_through(self, media_id):
        """Automatic playback rule: fill normal episodes through the completed episode."""
        row = self.connection.execute("SELECT anime_id, season, episode, kind FROM media WHERE id=?", (media_id,)).fetchone()
        if not row or row["kind"] != "episode" or row["episode"] is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute("""UPDATE media SET watched=1, watched_at=?, resume_position_ms=0
          WHERE anime_id=? AND kind='episode' AND (
            COALESCE(season,1) < COALESCE(?,1) OR
            (COALESCE(season,1)=COALESCE(?,1) AND episode<=?)
          )""", (now,row["anime_id"],row["season"],row["season"],row["episode"]))
        self._refresh_last_watched(row["anime_id"])
        self.connection.commit()
        return cursor.rowcount

    def set_all_watched(self, anime_id, watched):
        now = datetime.now(timezone.utc).isoformat() if watched else None
        self.connection.execute("UPDATE media SET watched=?, watched_at=?, resume_position_ms=CASE WHEN ? THEN 0 ELSE resume_position_ms END WHERE anime_id=? AND kind='episode'",
                                (int(watched), now, int(watched), anime_id))
        self._refresh_last_watched(anime_id)
        self.connection.commit()

    def _refresh_last_watched(self, anime_id):
        latest = self.connection.execute("""SELECT episode, watched_at FROM media
          WHERE anime_id=? AND kind='episode' AND watched=1
          ORDER BY watched_at DESC, COALESCE(episode,0) DESC LIMIT 1""", (anime_id,)).fetchone()
        self.connection.execute("UPDATE anime SET last_watched_episode=?, last_watched_at=? WHERE id=?",
                                (latest["episode"] if latest else None, latest["watched_at"] if latest else None, anime_id))

    def set_favorite(self, anime_id, favorite):
        self.connection.execute("UPDATE anime SET favorite=? WHERE id=?", (int(favorite), anime_id))
        self.connection.commit()

    def next_unwatched(self, anime_id):
        return self.connection.execute("""SELECT * FROM media WHERE anime_id=? AND kind='episode' AND watched=0
          ORDER BY COALESCE(season,999), COALESCE(episode,999), path COLLATE NOCASE LIMIT 1""", (anime_id,)).fetchone()

    def media_by_id(self, media_id):
        return self.connection.execute("SELECT * FROM media WHERE id=?",(media_id,)).fetchone()

    def set_resume_position(self, media_id, position_ms):
        self.connection.execute("UPDATE media SET resume_position_ms=? WHERE id=?",
                                (max(0,int(position_ms or 0)),media_id))
        self.connection.commit()

    def adjacent_episode(self, anime_id, media_id, offset):
        rows=self.connection.execute("""SELECT * FROM media WHERE anime_id=? AND kind='episode'
          ORDER BY COALESCE(season,999),COALESCE(episode,999),path COLLATE NOCASE""",(anime_id,)).fetchall()
        ids=[row["id"] for row in rows]
        if media_id not in ids: return None
        target=ids.index(media_id)+offset
        return rows[target] if 0<=target<len(rows) else None

    def continue_watching(self):
        return self.connection.execute("""SELECT a.*,
          COUNT(m.id) episode_count,
          SUM(CASE WHEN m.watched=1 THEN 1 ELSE 0 END) watched_count
          FROM anime a JOIN media m ON m.anime_id=a.id AND m.kind='episode'
          GROUP BY a.id HAVING watched_count>0 AND watched_count<episode_count
          ORDER BY a.last_watched_at DESC""").fetchall()

    def recently_watched(self, limit=12):
        return self.connection.execute("""SELECT a.*,
          SUM(CASE WHEN m.kind='episode' THEN 1 ELSE 0 END) episode_count,
          SUM(CASE WHEN m.kind='episode' AND m.watched=1 THEN 1 ELSE 0 END) watched_count
          FROM anime a LEFT JOIN media m ON m.anime_id=a.id
          WHERE a.last_watched_at IS NOT NULL GROUP BY a.id
          ORDER BY a.last_watched_at DESC LIMIT ?""", (limit,)).fetchall()
