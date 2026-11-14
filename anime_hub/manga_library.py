"""Read-only filesystem discovery and additive local manga storage."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from .manga_sources import IMAGE_TYPES, natural_key
from .manga_state import item_identity
from .display_titles import manga_display_title,clean_manga_display_title

SCHEMA = '''
CREATE TABLE IF NOT EXISTS manga_roots (
 id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT UNIQUE NOT NULL,
 scope TEXT NOT NULL DEFAULT 'normal', enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS manga_series (
 id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 root_path TEXT NOT NULL, root_id INTEGER REFERENCES manga_roots(id),
 scope TEXT NOT NULL DEFAULT 'normal', manual_scope TEXT,
 anilist_id INTEGER, metadata_json TEXT NOT NULL DEFAULT '{}',
 cover_path TEXT, manual_cover_path TEXT, favorite INTEGER NOT NULL DEFAULT 0,
 added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS manga_series_scope ON manga_series(scope);
CREATE INDEX IF NOT EXISTS manga_series_anilist ON manga_series(anilist_id);
CREATE TABLE IF NOT EXISTS manga_items (
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES manga_series(id),
 path TEXT NOT NULL, path_key TEXT UNIQUE NOT NULL, source_type TEXT NOT NULL,
 volume REAL, chapter REAL, display_name TEXT NOT NULL,
 reader_identity TEXT NOT NULL, present INTEGER NOT NULL DEFAULT 1,
 modified REAL NOT NULL DEFAULT 0, added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS manga_items_series ON manga_items(series_id);
CREATE INDEX IF NOT EXISTS manga_items_reader ON manga_items(reader_identity);
'''

def path_key(path):return os.path.normcase(str(Path(path).expanduser().resolve()))

def number(value):
    value=float(value)
    return str(int(value)) if value.is_integer() else str(value)

def clean_title(value):
    # Group labels and technical annotations are not chapter/volume identities.
    original=value
    value=re.sub(r'\[[^\]]*\]|\((?:digital|scan|edition|\d{3,4}p)[^)]*\)', '',value,flags=re.I)
    cleaned=re.sub(r'[ _]+',' ',value).strip(' ._-')
    # An entirely bracketed title is still a title, not a release-group prefix.
    return cleaned or original.strip(' ._-[]()')

def parse_numbers(name):
    stem=Path(name).stem if Path(name).suffix.lower() in {'.cbz','.cbr','.pdf'} else name
    # Never interpret numbers inside a release-group/edition annotation.
    def annotation(match):
        value=match.group()[1:-1]
        if re.fullmatch(r'(?i)(?:volume|vol\.?|v|chapter|chap\.?|ch\.?|c)\s*[._ -]*\d+(?:\.\d+)?',value):return ' '+value+' '
        return ' '*len(match.group())
    candidate=re.sub(r'\[[^\]]*\]|\([^)]*\)',annotation,stem)
    volume=re.search(r'(?i)(?:^|[\s_.-])(?:volume|vol\.?|v)\s*[._-]?\s*(\d+(?:\.\d+)?)\b',candidate)
    chapter=re.search(r'(?i)(?:^|[\s_.-])(?:chapter|chap\.?|ch\.?|c)\s*[._-]?\s*(\d+(?:\.\d+)?)\b',candidate)
    def parsed(match):
        if not match:return None
        n=float(match.group(1))
        return None if n in {480,720,1080,2160,4320} or 1900<=n<=2099 else n
    v=parsed(volume);c=parsed(chapter)
    plain=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*',candidate)
    if c is None and v is None and plain:c=parsed(plain)
    positions=[m.start() for m,n in ((volume,v),(chapter,c)) if m and n is not None]
    title=clean_title(stem[:min(positions)] if positions else stem)
    if plain and c is not None:title=''
    return v,c,title

def generic_folder(name):
    return name.casefold() in {'pages','images','chapters','volumes'} or bool(re.fullmatch(r'(?i)(?:volume|vol\.?|v|chapter|chap\.?|ch\.?|c)\s*[._ -]*\d+(?:\.\d+)?',name)) or bool(re.fullmatch(r'\d+(?:\.\d+)?',name))

def readable_label(name,volume,chapter):
    labels=([f'Volume {number(volume)}'] if volume is not None else [])+([f'Chapter {number(chapter)}'] if chapter is not None else [])
    stem=Path(name).stem if Path(name).suffix.lower() in {'.cbz','.cbr','.pdf'} else name
    if not labels:return clean_title(stem) or stem
    cleaned=re.sub(r'\[[^\]]*\]|\([^)]*\)','',stem)
    markers=list(re.finditer(r'(?i)(?:^|[\s_.-])(?:volume|vol\.?|v|chapter|chap\.?|ch\.?|c)\s*[._-]?\s*\d+(?:\.\d+)?\b',cleaned))
    tail=cleaned[markers[-1].end():].strip(' ._-') if markers else ''
    return ' · '.join(labels)+(' — '+tail if tail and not re.fullmatch(r'(?i)\d{3,4}p',tail) else '')

def scan_manga(roots, cancelled=lambda:False):
    """Enumerate files only; never open an archive or decode a cover during scan."""
    result={'series':{},'roots_done':[],'errors':[]};seen=set()
    for root in roots:
        base=Path(root['path']);scope=root['scope'];root_id=root['id']
        if cancelled():break
        if not base.is_dir():result['errors'].append(f'Root unavailable: {base}');continue
        errors=[]
        def error(exc):errors.append(f'{type(exc).__name__}: {exc}')
        for folder,dirs,files in os.walk(base,followlinks=False,onerror=error):
            if cancelled():return result
            directory=Path(folder)
            dirs[:]=sorted([d for d in dirs if not d.startswith('.') and not (directory/d).is_symlink()],key=natural_key)
            files=sorted([f for f in files if not f.startswith('.') and not (directory/f).is_symlink()],key=lambda n:(natural_key(n),n))
            archives=[directory/f for f in files if Path(f).suffix.lower() in {'.cbz','.cbr','.pdf'}]
            images=[f for f in files if Path(f).suffix.lower() in IMAGE_TYPES and Path(f).stem.casefold() not in {'cover','folder','poster','thumb','thumbnail'}]
            candidates=[(p,p.suffix[1:].lower()) for p in archives]
            if images and not archives:
                candidates.append((directory,'folder'));dirs[:]=[]
            for path,kind in candidates:
                key=path_key(path)
                if key in seen:continue
                seen.add(key)
                relative=path.relative_to(base);parts=relative.parts
                if path==base:
                    series_path=base;title=base.name;identity=path_key(base)
                elif len(parts)>=2 or kind=='folder':
                    series_path=path if kind=='folder' else path.parent
                    while series_path!=base and generic_folder(series_path.name):series_path=series_path.parent
                    title=series_path.name;identity=path_key(series_path)
                else:
                    pv,pc,parsed=parse_numbers(path.name)
                    title=parsed or base.name;series_path=base
                    # Exact parsed titles group loose volumes; no fuzzy name merging.
                    if not parsed or parsed.casefold()==base.name.casefold() or ((pv is not None or pc is not None) and re.fullmatch(r'\d+(?:\.\d+)?',parsed)):
                        title=base.name;identity=path_key(base)
                    else:identity=path_key(base)+'\0loose:'+title.casefold()
                sid=hashlib.sha256(identity.encode()).hexdigest()
                series=result['series'].setdefault(sid,{'identity':sid,'title':title,'root_path':str(series_path),'root_id':root_id,'scope':scope,'items':[]})
                v,c,_=parse_numbers(path.name)
                if v is None:
                    for parent in reversed(relative.parts[:-1]):
                        v,_,_=parse_numbers(parent)
                        if v is not None:break
                display=readable_label(path.name,v,c)
                try:modified=path.stat().st_mtime
                except OSError as exc:errors.append(f'{type(exc).__name__}: {path}');continue
                series['items'].append({'path':str(path.resolve()),'path_key':key,'source_type':kind,'volume':v,'chapter':c,'display_name':display,'modified':modified})
        if not errors:result['roots_done'].append(root_id)
        result['errors'].extend(errors)
    return result

class MangaStore:
    def __init__(self,db,owned_data_dir=None):
        self.db=db;self.connection=db.connection;self.owned_data_dir=Path(owned_data_dir).resolve() if owned_data_dir else None
    def roots(self):return [dict(r) for r in self.connection.execute('SELECT * FROM manga_roots WHERE enabled=1 ORDER BY id')]
    def add_root(self,path,scope='normal'):
        path=Path(path).expanduser().resolve()
        if scope not in {'normal','restricted'}:raise ValueError('Unknown root scope.')
        if not path.is_dir():raise ValueError('Choose an accessible manga folder.')
        owned=self.owned_data_dir
        if owned and (path==owned or path in owned.parents or owned in path.parents):raise ValueError('Choose a dedicated manga folder outside AniVault app data and cache directories.')
        key=path_key(path)
        for root in self.roots():
            other=Path(root['path'])
            if root['path_key']==key:
                if root['scope']!=scope:raise ValueError('This root already belongs to the other scope.')
                return root['id']
            if path in other.parents or other in path.parents:raise ValueError('Overlapping manga roots are not supported. Choose one common root.')
        anime_root=self.db.setting('library_root')
        if anime_root:
            anime=Path(anime_root).expanduser().resolve()
            if path==anime or path in anime.parents or anime in path.parents:raise ValueError('Keep manga and anime roots separate.')
        cursor=self.connection.execute('''INSERT INTO manga_roots(path,path_key,scope) VALUES(?,?,?)
          ON CONFLICT(path_key) DO UPDATE SET enabled=1,scope=excluded.scope RETURNING id''',(str(path),key,scope));rid=cursor.fetchone()[0];self.connection.commit();return rid
    def disable_root(self,rid):self.connection.execute('UPDATE manga_roots SET enabled=0 WHERE id=?',(rid,));self.connection.commit()
    def reconcile(self,result):
        new=changed=removed=0
        with self.connection:
            before={r['path_key']:dict(r) for r in self.connection.execute('SELECT * FROM manga_items')}
            before_series_paths={}
            for key,value in before.items():
                if value['present']:before_series_paths.setdefault(value['series_id'],set()).add(key)
            reader_states={r['identity']:dict(r) for r in self.connection.execute('SELECT identity,scope FROM manga_reader_state')}
            existing_series={r['id']:dict(r) for r in self.connection.execute('SELECT * FROM manga_series')}
            imports=[];grouping_conflicts=0
            for series in result['series'].values():
                known={before[i['path_key']]['series_id'] for i in series['items'] if i['path_key'] in before}
                if len(known)>1:
                    # Better normalization must not silently collapse distinct
                    # persisted records and orphan their statuses/memberships.
                    grouping_conflicts+=1
                    for sid in sorted(known):
                        original=existing_series[sid]
                        items=[i for i in series['items'] if i['path_key'] in before and before[i['path_key']]['series_id']==sid]
                        imports.append({**series,'identity':original['identity'],'title':original['title'],'items':items})
                    new_items=[i for i in series['items'] if i['path_key'] not in before]
                    if new_items:imports.append({**series,'items':new_items})
                else:imports.append(series)
            for rid in result['roots_done']:
                self.connection.execute('UPDATE manga_items SET present=0 WHERE series_id IN (SELECT id FROM manga_series WHERE root_id=?)',(rid,))
            touched=set()
            for series in imports:
                known={before[i['path_key']]['series_id'] for i in series['items'] if i['path_key'] in before}
                exists=self.connection.execute('SELECT id FROM manga_series WHERE identity=?',(series['identity'],)).fetchone()
                old_paths=before_series_paths.get(next(iter(known)),set()) if len(known)==1 else set()
                new_paths={i['path_key'] for i in series['items']}
                if not exists and len(known)==1 and old_paths<=new_paths:
                    self.connection.execute('UPDATE manga_series SET identity=? WHERE id=?',(series['identity'],next(iter(known))))
                self.connection.execute('''INSERT INTO manga_series(identity,title,root_path,root_id,scope) VALUES(?,?,?,?,?)
                  ON CONFLICT(identity) DO UPDATE SET root_path=excluded.root_path,root_id=excluded.root_id,
                  scope=COALESCE(manga_series.manual_scope,CASE WHEN json_extract(manga_series.metadata_json,'$.isAdult')=1 THEN 'restricted' ELSE excluded.scope END)''',
                  (series['identity'],series['title'],series['root_path'],series['root_id'],series['scope']))
                row=dict(self.connection.execute('SELECT * FROM manga_series WHERE identity=?',(series['identity'],)).fetchone());sid=row['id']
                for item in series['items']:
                    old=before.get(item['path_key']);identity=old['reader_identity'] if old else item_identity(item['path'],row['scope'])
                    if old is None:
                        private_identity=item_identity(item['path'],'restricted');normal_identity=item_identity(item['path'],'normal')
                        # A prior Restricted reader opening was an explicit privacy
                        # choice. Adopt that state instead of exposing it as normal.
                        if private_identity in reader_states and row['scope']=='normal' and not row['manual_scope']:
                            row['scope']='restricted';row['manual_scope']='restricted'
                            self.connection.execute("UPDATE manga_series SET scope='restricted',manual_scope='restricted' WHERE id=?",(sid,))
                        preferred=item_identity(item['path'],row['scope'])
                        alternate=normal_identity if row['scope']=='restricted' else private_identity
                        identity=preferred if preferred in reader_states else alternate if alternate in reader_states else preferred
                    self.connection.execute('''INSERT INTO manga_items(series_id,path,path_key,source_type,volume,chapter,display_name,reader_identity,modified)
                      VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(path_key) DO UPDATE SET present=1,
                      series_id=excluded.series_id,path=excluded.path,modified=excluded.modified,source_type=excluded.source_type,
                      volume=excluded.volume,chapter=excluded.chapter,display_name=excluded.display_name''',
                      (sid,item['path'],item['path_key'],item['source_type'],item['volume'],item['chapter'],item['display_name'],identity,item['modified']))
                    touched.add(item['path_key'])
                    self.connection.execute('UPDATE manga_reader_state SET scope=? WHERE identity=?',(row['scope'],identity))
                    if old is None:new+=1
                    elif not old['present'] or old['modified']!=item['modified']:
                        changed+=1
                        if old['modified']!=item['modified']:self.connection.execute('UPDATE manga_series SET cover_path=NULL WHERE id=?',(sid,))
                self.connection.execute('UPDATE manga_reader_state SET scope=? WHERE identity IN (SELECT reader_identity FROM manga_items WHERE series_id=?)',(row['scope'],sid))
            removed=sum(1 for key,row in before.items() if row['present'] and key not in touched and self.connection.execute('SELECT present FROM manga_items WHERE path_key=?',(key,)).fetchone()[0]==0)
        return {'series':len(imports),'items':sum(len(s['items']) for s in imports),'new':new,'changed':changed,'removed':removed,'errors':len(result['errors']),'preserved_group_conflicts':grouping_conflicts}
    def series(self,sid,scope=None):
        rows=self.series_list(scope,series_id=sid)
        return rows[0] if rows else None
    def series_list(self,scope='normal',series_id=None):
        conditions=['r.enabled=1'];params=[]
        if scope is not None:conditions.append('s.scope=?');params.append(scope)
        if series_id is not None:conditions.append('s.id=?');params.append(series_id)
        rows=self.connection.execute('''SELECT s.*,COALESCE(ms.status,(SELECT status FROM manual_status WHERE scope=s.scope AND entity_key='anilist:'||s.anilist_id)) manual_status,
          COUNT(i.id) item_count,SUM(CASE WHEN i.present=1 THEN 1 ELSE 0 END) available_count,
          SUM(CASE WHEN p.completed=1 THEN 1 ELSE 0 END) completed_count,
          MAX(p.last_opened_at) last_opened,MAX(p.last_read_at) last_read,AVG(COALESCE(p.percent_complete,0)) progress,
          (SELECT x.display_name||' · Page '||q.current_page||' / '||q.total_pages FROM manga_items x JOIN manga_reader_state q ON q.identity=x.reader_identity WHERE x.series_id=s.id ORDER BY q.last_read_at DESC LIMIT 1) last_read_label,
          (SELECT x.id FROM manga_items x JOIN manga_reader_state q ON q.identity=x.reader_identity WHERE x.series_id=s.id AND x.present=1 AND q.completed=0 AND q.current_page>1 ORDER BY q.last_read_at DESC,x.id DESC LIMIT 1) active_item_id,
          (SELECT x.display_name||' · Page '||q.current_page||' / '||q.total_pages FROM manga_items x JOIN manga_reader_state q ON q.identity=x.reader_identity WHERE x.series_id=s.id AND x.present=1 AND q.completed=0 AND q.current_page>1 ORDER BY q.last_read_at DESC,x.id DESC LIMIT 1) active_label,
          (SELECT COUNT(DISTINCT volume) FROM manga_items WHERE series_id=s.id AND present=1 AND volume IS NOT NULL) volume_count,
          (SELECT COUNT(DISTINCT chapter) FROM manga_items WHERE series_id=s.id AND present=1 AND chapter IS NOT NULL) chapter_count
          FROM manga_series s JOIN manga_roots r ON r.id=s.root_id
          LEFT JOIN manga_items i ON i.series_id=s.id
          LEFT JOIN manga_reader_state p ON p.identity=i.reader_identity
          LEFT JOIN manual_status ms ON ms.scope=s.scope AND ms.entity_key='manga:'||s.id
          WHERE '''+' AND '.join(conditions)+' GROUP BY s.id HAVING COUNT(i.id)>0 ORDER BY s.title COLLATE NOCASE',params).fetchall()
        records=[dict(r) for r in rows]
        for row in records:
            metadata=json.loads(row['metadata_json'] or '{}');titles=metadata.get('title') or {};titles=titles if isinstance(titles,dict) else {}
            row['display_title']=manga_display_title(row,metadata)
            for label_key in ('last_read_label','active_label'):
                if row.get(label_key):
                    parts=row[label_key].split(' · Page ',1);row[label_key]=clean_manga_display_title(parts[0])+(' · Page '+parts[1] if len(parts)>1 else '')
            row['search_titles']=' '.join(str(t) for t in [row['display_title'],row['title'],*titles.values(),*(metadata.get('synonyms') or [])] if t)
        return records
    def items(self,sid):
        rows=[dict(r) for r in self.connection.execute('''SELECT i.*,p.current_page,p.total_pages,p.completed,p.percent_complete,p.last_read_at
          FROM manga_items i LEFT JOIN manga_reader_state p ON p.identity=i.reader_identity WHERE i.series_id=?''',(sid,))]
        return sorted(rows,key=lambda r:(r['volume'] if r['volume'] is not None else -1,r['chapter'] if r['chapter'] is not None else -1,natural_key(r['path']),r['path_key']))
    def item(self,iid):
        row=self.connection.execute('SELECT * FROM manga_items WHERE id=?',(iid,)).fetchone();return dict(row) if row else None
    def item_by_path(self,path):
        row=self.connection.execute('SELECT i.*,s.scope FROM manga_items i JOIN manga_series s ON s.id=i.series_id WHERE i.path_key=?',(path_key(path),)).fetchone()
        return dict(row) if row else None
    def continue_item(self,sid):
        items=self.items(sid);active=[i for i in items if i['present'] and not i['completed'] and (i['current_page'] or 0)>1]
        if active:return max(active,key=lambda i:(i['last_read_at'] or '',i['id']))
        return next((i for i in items if i['present'] and not i['completed']),next((i for i in items if i['present']),None))
    def set_item_finished(self,iid,finished):
        """Only mutate this item's completion bit; pages, bookmarks and manual status stay intact."""
        item=self.item(iid)
        if item is None:raise ValueError('Manga item no longer exists.')
        series=self.series(item['series_id'])
        if series is None:raise ValueError('Manga series is unavailable.')
        self.connection.execute("""INSERT INTO manga_reader_state(identity,path,scope,source_type,total_pages,current_page,completed)
          VALUES(?,?,?,?,0,1,?) ON CONFLICT(identity) DO UPDATE SET completed=excluded.completed""",
          (item['reader_identity'],item['path'],series['scope'],item['source_type'],int(bool(finished))))
        self.connection.commit()

    def metadata(self,sid):
        row=self.series(sid)
        if row is None:return {}
        metadata=json.loads(row['metadata_json'] or '{}');title=metadata.get('title')
        return {**metadata,'local_manga_id':sid,'title':title if isinstance(title,dict) else {'romaji':row['display_title']},'type':'MANGA','isAdult':row['scope']=='restricted','cover_path':row['cover_path']}
    def set_status(self,sid,status):
        row=self.series(sid)
        if not row:raise ValueError('Manga no longer exists.')
        if status not in {None,'Watching','Completed','Planning','Paused','Dropped'}:raise ValueError('Unknown status.')
        key=f'manga:{sid}'
        if status is None:self.connection.execute('DELETE FROM manual_status WHERE entity_key=? AND scope=?',(key,row['scope']))
        else:self.connection.execute('''INSERT INTO manual_status(scope,entity_key,status,metadata_json) VALUES(?,?,?,?)
          ON CONFLICT(scope,entity_key) DO UPDATE SET status=excluded.status,metadata_json=excluded.metadata_json,updated_at=CURRENT_TIMESTAMP''',(row['scope'],key,status,json.dumps(self.metadata(sid))))
        # An explicit change also updates an existing Saved alias. Import/match
        # never overwrites either status; only a user mutation reconciles them.
        if row['anilist_id']:
            alias=f"anilist:{row['anilist_id']}"
            if status is None:self.connection.execute('DELETE FROM manual_status WHERE entity_key=? AND scope=?',(alias,row['scope']))
            else:self.connection.execute('UPDATE manual_status SET status=?,updated_at=CURRENT_TIMESTAMP WHERE entity_key=? AND scope=?',(status,alias,row['scope']))
        self.connection.commit();return key
    def set_favorite(self,sid,value):self.connection.execute('UPDATE manga_series SET favorite=? WHERE id=?',(int(value),sid));self.connection.commit()
    def add_collection(self,sid,cid):
        row=self.series(sid);collection=self.db.collection(cid)
        if not row or not collection or row['scope']!=collection['scope']:raise ValueError('Collection scope must match this manga.')
        if row['anilist_id']:
            exists=self.connection.execute("""SELECT 1 FROM collection_entries ce WHERE ce.collection_id=? AND
              (ce.entity_key=? OR ce.entity_key IN (SELECT 'manga:'||id FROM manga_series WHERE anilist_id=? AND scope=?)) LIMIT 1""",
              (cid,f"anilist:{row['anilist_id']}",row['anilist_id'],row['scope'])).fetchone()
            if exists:return False
        cursor=self.connection.execute('INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)',(cid,f'manga:{sid}',json.dumps(self.metadata(sid))))
        self.connection.execute('UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(cid,));self.connection.commit();return bool(cursor.rowcount)
    def set_scope(self,sid,scope):
        row=self.series(sid)
        if not row or scope not in {'normal','restricted'}:raise ValueError('Invalid scope.')
        if scope=='normal' and json.loads(row['metadata_json'] or '{}').get('isAdult') is True:raise ValueError('Unmatch the explicitly adult AniList record before moving this title to normal Manga.')
        key=f'manga:{sid}'
        with self.connection:
            self.connection.execute('UPDATE manga_series SET scope=?,manual_scope=? WHERE id=?',(scope,scope,sid))
            self.connection.execute('UPDATE manual_status SET scope=? WHERE entity_key=?',(scope,key))
            self.connection.execute('UPDATE manga_reader_state SET scope=? WHERE identity IN (SELECT reader_identity FROM manga_items WHERE series_id=?)',(scope,sid))
            # Move membership to a same-named collection in the new scope, never
            # leave a private entity/count in a normal collection.
            memberships=self.connection.execute('SELECT c.* FROM collection_entries e JOIN collections c ON c.id=e.collection_id WHERE e.entity_key=?',(key,)).fetchall()
            for c in memberships:
                target=self.connection.execute('SELECT id FROM collections WHERE name=? COLLATE NOCASE AND scope=?',(c['name'],scope)).fetchone()
                if not target:
                    name=c['name']+' ('+('Restricted' if scope=='restricted' else 'Manga')+')'
                    self.connection.execute('INSERT OR IGNORE INTO collections(name,description,scope) VALUES(?,?,?)',(name,c['description'],scope))
                    target=self.connection.execute('SELECT id FROM collections WHERE name=? COLLATE NOCASE AND scope=?',(name,scope)).fetchone()
                if target:
                    self.connection.execute('INSERT OR IGNORE INTO collection_entries(collection_id,entity_key,metadata_json) SELECT ?,entity_key,metadata_json FROM collection_entries WHERE collection_id=? AND entity_key=?',(target[0],c['id'],key))
                self.connection.execute('DELETE FROM collection_entries WHERE collection_id=? AND entity_key=?',(c['id'],key))
    def match(self,sid,item):
        if item.get('type')!='MANGA':raise ValueError('Only AniList MANGA records can be matched.')
        self.connection.execute('UPDATE manga_series SET anilist_id=?,metadata_json=?,cover_path=NULL WHERE id=?',(int(item['id']),json.dumps(item),sid));self.connection.commit()
        if item.get('isAdult') is True:self.set_scope(sid,'restricted')
    def unmatch(self,sid):self.connection.execute("UPDATE manga_series SET anilist_id=NULL,metadata_json='{}' WHERE id=?",(sid,));self.connection.commit()
