"""Additive reader-only state; never touches anime or external Saved state."""
import hashlib
import os
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS manga_reader_state (
 identity TEXT PRIMARY KEY, path TEXT NOT NULL, scope TEXT NOT NULL,
 source_type TEXT NOT NULL, current_page INTEGER NOT NULL DEFAULT 1,
 total_pages INTEGER NOT NULL, percent_complete REAL NOT NULL DEFAULT 0,
 completed INTEGER NOT NULL DEFAULT 0, last_opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS manga_bookmarks (
 identity TEXT NOT NULL REFERENCES manga_reader_state(identity) ON DELETE CASCADE,
 page INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(identity,page)
);
'''

def item_identity(path, scope='normal'):
    canonical = os.path.normcase(str(Path(path).expanduser().resolve()))
    return hashlib.sha256((scope + '\0' + canonical).encode('utf-8')).hexdigest()

class ReaderStore:
    def __init__(self, db):
        self.db = db
        db.connection.executescript(SCHEMA)

    def open(self, path, scope, kind, total, reader_identity=None):
        identity = reader_identity or item_identity(path, scope)
        self.db.connection.execute('''INSERT INTO manga_reader_state(identity,path,scope,source_type,total_pages)
          VALUES(?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET
          total_pages=excluded.total_pages, source_type=excluded.source_type,
          current_page=MIN(current_page,excluded.total_pages),
          percent_complete=CASE WHEN completed=1 THEN 100 ELSE MIN(99.9,100.0*MIN(current_page,excluded.total_pages)/excluded.total_pages) END,
          last_opened_at=CURRENT_TIMESTAMP''', (identity,str(Path(path).resolve()),scope,kind,total))
        self.db.connection.commit()
        return dict(self.db.connection.execute('SELECT * FROM manga_reader_state WHERE identity=?',(identity,)).fetchone())

    def save(self, identity, page, total, complete=False):
        self.db.connection.execute('''UPDATE manga_reader_state SET current_page=?,total_pages=?,
          percent_complete=?,completed=MAX(completed,?),last_read_at=CURRENT_TIMESTAMP WHERE identity=?''',
          (page,total,100 if complete else min(99.9,100*page/total),int(complete),identity))
        self.db.connection.commit()

    def bookmarks(self, identity):
        return [row[0] for row in self.db.connection.execute('SELECT page FROM manga_bookmarks WHERE identity=? ORDER BY page',(identity,))]

    def toggle_bookmark(self, identity, page):
        if page in self.bookmarks(identity):
            self.db.connection.execute('DELETE FROM manga_bookmarks WHERE identity=? AND page=?',(identity,page))
        else:
            self.db.connection.execute('INSERT INTO manga_bookmarks(identity,page) VALUES(?,?)',(identity,page))
        self.db.connection.commit()
