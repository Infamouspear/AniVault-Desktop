"""Read-only, batched presentation identity resolution. Never merges stored records.

Local IDs remain the authority for playback/reading; an AniList ID is an alias
only within the same media type and privacy scope.
"""
import json
from dataclasses import dataclass, field
from .external_bookmarks import bookmark_record


def metadata(value):
    try:
        result=json.loads(value or '{}') if isinstance(value,str) else value or {}
        return result if isinstance(result,dict) else {}
    except (ValueError,TypeError):return {}


def display_title(item):
    title=item.get('title') or {}
    return (title.get('english') or title.get('userPreferred') or title.get('romaji') or title.get('native') or 'Untitled') if isinstance(title,dict) else str(title)


def media_type(item):
    return item.get('type') or ('MANGA' if item.get('format') in {'MANGA','ONE_SHOT','NOVEL'} else 'ANIME')


@dataclass
class Entity:
    key: str
    media_type: str
    scope: str
    item: dict
    local: dict | None = None
    aliases: set = field(default_factory=set)
    saved: bool = False
    status: str | None = None
    stamp: str = ''

    @property
    def title(self):return self.local.get('display_title',self.local['title']) if self.local else display_title(self.item)
    @property
    def label(self):
        kind='External' if self.media_type=='EXTERNAL' else self.media_type.title()
        location=('Missing / unavailable' if not self.local.get('available_count') else 'In Vault') if self.local else 'External bookmark' if self.media_type=='EXTERNAL' else 'Saved' if self.saved else 'AniList'
        return kind+' · '+location+(' · Saved' if self.saved and self.local else '')


class Organization:
    def __init__(self,db,manga_store,scope='normal'):
        self.db=db;self.manga=manga_store;self.scope=scope;self.entities={};self.by_key={}
        availability=dict(db.connection.execute("SELECT anime_id,SUM(CASE WHEN present=1 AND kind='episode' THEN 1 ELSE 0 END) FROM media GROUP BY anime_id"))
        anime_rows=db.anime_list();scopes=db.anime_scope_map(anime_rows)
        self.private_anilist_ids={row['anilist_id'] for row in db.anime_list(include_retired=True) if db.anime_scope(row,fresh=False)=='restricted' and row['anilist_id']}
        all_rows=db.anime_list(include_retired=True)
        active_ids={r['anilist_id'] for r in anime_rows if r['anilist_id']}
        self.retired_aliases={'anilist:'+str(r['anilist_id']) for r in all_rows if not r['active'] and r['anilist_id'] and r['anilist_id'] not in active_ids}
        manga_active={r['id'] for r in manga_store.series_list(scope)}
        self.retired_aliases.update('anilist:'+str(r['anilist_id']) for r in db.connection.execute('SELECT id,anilist_id FROM manga_series WHERE scope=?',(scope,)) if r['id'] not in manga_active and r['anilist_id'])
        self.explicit_saved={'anilist:'+str(r['anilist_id']) for r in db.saved_titles(scope=scope)}
        for row in anime_rows:
            row=dict(row);item=metadata(row['metadata_json'])
            row['metadata_json']=json.dumps(item)
            row['display_title']=display_title(item) if item.get('title') else row.get('parsed_search_title') or row['title']
            row['available_count']=availability.get(row['id'],0)
            if scopes[row['id']] != scope:continue
            item['isAdult'] = scope == 'restricted'
            item={**item,'type':'ANIME'}
            key=f"local:{row['id']}";aliases={key}
            if row['anilist_id']:aliases.add(f"anilist:{row['anilist_id']}")
            self._local(Entity(key,'ANIME',scope,item,row,aliases))
        for row in manga_store.series_list(scope):
            item=metadata(row['metadata_json']);item={**item,'type':'MANGA','isAdult':scope=='restricted'}
            key=f"manga:{row['id']}";aliases={key}
            if row['anilist_id']:aliases.add(f"anilist:{row['anilist_id']}")
            self._local(Entity(key,'MANGA',scope,item,row,aliases))
        for row in db.saved_titles(scope=scope):
            entity=self.resolve(f"anilist:{row['anilist_id']}",metadata(row['metadata_json']))
            if entity:entity.saved=True;entity.stamp=row['saved_at'] or ''
        if scope=='restricted':
            for row in db.source_saved():
                item=bookmark_record(metadata(row['metadata_json']),row['source'],row['external_id'])
                entity=self.resolve(db.source_key(row['source'],row['external_id']),item)
                if entity:entity.saved=True;entity.stamp=row['saved_at'] or ''
        # Local explicit status wins when legacy local and remote keys coexist.
        statuses=list(db.connection.execute('SELECT * FROM manual_status WHERE scope=? ORDER BY updated_at DESC',(scope,)))
        for row in statuses:
            entity=self.resolve(row['entity_key'],metadata(row['metadata_json']))
            if entity and (entity.status is None or row['entity_key']==entity.key):entity.status=row['status']

    def _logical(self,entity):
        identifier=entity.local.get('anilist_id') if entity.local else entity.item.get('id')
        return (entity.media_type,int(identifier)) if identifier and entity.media_type!='EXTERNAL' else (entity.media_type,entity.key)

    def _local(self,entity):
        logical=self._logical(entity)
        prior=self.entities.get(logical)
        if prior:
            prior.aliases.update(entity.aliases)
            if prior.local and entity.local:
                prior.local['favorite']=int(bool(prior.local['favorite'] or entity.local['favorite']))
            # Keep one presentation; retain ALL local records and their state.
            for alias in entity.aliases:self.by_key[(entity.media_type,alias)]=prior
            return
        self.entities[logical]=entity
        for alias in entity.aliases:self.by_key[(entity.media_type,alias)]=entity

    def resolve(self,key,item=None):
        if key in self.retired_aliases and key not in self.explicit_saved:return None
        item=metadata(item)
        if not item:
            matches=[entity for (kind,alias),entity in self.by_key.items() if alias==key]
            if len(matches)==1:return matches[0]
        media='EXTERNAL' if key.startswith('source:') else 'MANGA' if key.startswith('manga:') else media_type(item)
        if media=='ANIME' and self.scope=='normal' and key.startswith('anilist:'):
            try: identifier=int(key.split(':',1)[1])
            except ValueError:return None
            if identifier in self.private_anilist_ids:return None
        existing=self.by_key.get((media,key))
        if existing:return existing
        # A local key in the other scope must never fall back to cached metadata.
        if key.startswith(('local:','manga:')):return None
        if media=='EXTERNAL':
            if self.scope!='restricted':return None
        elif (item.get('isAdult') is True)!=(self.scope=='restricted'):return None
        if not key.startswith(('anilist:','source:')):return None
        item={**item,'type':media} if media!='EXTERNAL' else item
        entity=Entity(key,media,self.scope,item,aliases={key})
        self._local(entity);return entity

    def entries(self,rows):
        result=[];seen=set()
        for row in rows:
            entity=self.resolve(row['entity_key'],metadata(row['metadata_json']))
            if entity and entity.key not in seen:
                seen.add(entity.key);result.append(entity)
        return result

    def collection(self,cid):
        collection=self.db.collection(cid)
        if not collection or collection['scope']!=self.scope:return []
        rows=self.db.connection.execute('SELECT * FROM collection_entries WHERE collection_id=? ORDER BY added_at DESC',(cid,))
        return self.entries(rows)

    def statuses(self,status):return [entity for entity in self.entities.values() if entity.status==status]
    def favorites(self):return [entity for entity in self.entities.values() if entity.local and entity.local['favorite']]
    def search(self,query):
        terms=query.casefold().split();results=[]
        for entity in self.entities.values():
            # Search local and Saved metadata, not unsaved status placeholders.
            if not entity.local and not entity.saved:continue
            item=entity.item;title=item.get('title') or {}
            aliases=list(title.values()) if isinstance(title,dict) else [title]
            haystack=' '.join(str(value) for value in [entity.title,*aliases,*(item.get('synonyms') or []),*(item.get('genres') or []),*entity.aliases] if value).casefold()
            if all(term in haystack for term in terms):results.append(entity)
        return sorted(results,key=lambda entity:entity.title.casefold())

    def memberships(self,entity):
        keys=tuple(entity.aliases)
        marks=','.join('?' for _ in keys)
        return {row[0] for row in self.db.connection.execute(f'SELECT ce.collection_id FROM collection_entries ce JOIN collections c ON c.id=ce.collection_id WHERE c.scope=? AND ce.entity_key IN ({marks})',(self.scope,*keys))}

    def remove_membership(self,cid,entity):
        # Explicit removal acts on all certain aliases, not the anime/manga data.
        if cid not in self.memberships(entity):return
        with self.db.connection:
            self.db.connection.executemany('DELETE FROM collection_entries WHERE collection_id=? AND entity_key=?',[(cid,key) for key in entity.aliases])
            # The old migration imports collection_items on every startup.
            # Remove the corresponding legacy relationships on an explicit
            # user removal, otherwise the deleted membership would return.
            local_ids=[int(key.split(':',1)[1]) for key in entity.aliases if key.startswith('local:')]
            self.db.connection.executemany('DELETE FROM collection_items WHERE collection_id=? AND anime_id=?',[(cid,identifier) for identifier in local_ids])
            self.db.connection.execute('UPDATE collections SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(cid,))
