"""Normal-library airing history. SQLite writes stay on the UI thread."""
import json
import re
import time
from pathlib import Path
from .parser import classify_file
from .organization import metadata

SCHEMA = """
CREATE TABLE IF NOT EXISTS airing_follows (
 media_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, metadata_json TEXT NOT NULL,
 updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS airing_updates (
 media_id INTEGER NOT NULL, episode INTEGER NOT NULL, airing_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL, metadata_json TEXT NOT NULL,
 availability TEXT NOT NULL DEFAULT 'uncertain', is_read INTEGER NOT NULL DEFAULT 0,
 dismissed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(media_id,episode));
"""


def positive_id(value):
    try:
        return int(value) if not isinstance(value,bool) and str(value).isdigit() and int(value)>0 else None
    except (ValueError, TypeError, OverflowError):
        return None


class AiringUpdates:
    def __init__(self, db):
        self.db = db

    def blocked_ids(self):
        stamp=self.db.change_stamp()
        cached=getattr(self,'_blocked_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        rows = self.db.anime_list()
        blocked = {positive_id(r['anilist_id']) for r in rows if self.db.anime_scope(r, fresh=False) == 'restricted'}
        for table, condition in [('saved_titles', "scope='restricted'"), ('manual_status', "scope='restricted'")]:
            for r in self.db.connection.execute(f'SELECT metadata_json FROM {table} WHERE {condition}'):
                item = metadata(r[0])
                if item.get('type') != 'MANGA':
                    blocked.add(positive_id(item.get('id')))
        for row in self.db.connection.execute('SELECT media_id,metadata_json FROM airing_follows'):
            if metadata(row['metadata_json']).get('isAdult') is True:blocked.add(row['media_id'])
        result=blocked-{None}
        self._blocked_cache=(stamp,result)
        return result

    def allowed(self, item):
        return (positive_id(item.get('id')) is not None and item.get('type', 'ANIME') == 'ANIME'
                and item.get('isAdult') is False and positive_id(item['id']) not in self.blocked_ids())

    def followed(self, identifier):
        row = self.db.connection.execute('SELECT enabled FROM airing_follows WHERE media_id=?', (identifier,)).fetchone()
        return bool(row[0]) if row else identifier in self.candidates()

    def set_follow(self, item, enabled):
        if not self.allowed(item):
            return False
        with self.db.connection:
            self.db.connection.execute('INSERT INTO airing_follows VALUES(?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET enabled=excluded.enabled,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at',
                                       (int(item['id']), int(enabled), json.dumps(item), int(time.time())))
        return True

    def local_titles(self):
        stamp=self.db.change_stamp();cached=getattr(self,'_local_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        result={}
        for row in self.db.anime_list():
            identifier=positive_id(row['anilist_id']);item=metadata(row['metadata_json']);item['id']=identifier
            if identifier and self.db.anime_scope(row,fresh=False)=='normal' and identifier not in self.blocked_ids():
                result.setdefault(identifier,[]).append((dict(row),item))
        self._local_cache=(self.db.change_stamp(),result)
        return result

    def candidates(self):
        # Every eligible airing title in the vault is monitored automatically.
        # Legacy follows/read/dismissal remain stored, but do not gate this list.
        return {identifier:members[0][1] for identifier,members in self.local_titles().items()
                if members[0][1].get('status')=='RELEASING' and self.allowed(members[0][1])}

    def apply_catalog(self, items):
        local=self.local_titles()
        for item in items:
            identifier=positive_id(item.get('id'))
            if identifier not in local or item.get('type')!='ANIME' or type(item.get('isAdult')) is not bool:continue
            if item['isAdult']:
                self.db.observe_classifications([item],allow_normal=False)
                scrubbed=json.dumps({'id':identifier,'type':'ANIME','isAdult':True})
                with self.db.connection:
                    self.db.connection.execute('UPDATE airing_follows SET enabled=0,metadata_json=? WHERE media_id=?',(scrubbed,identifier))
                    self.db.connection.execute('UPDATE airing_updates SET metadata_json=? WHERE media_id=?',(scrubbed,identifier))
                continue
            for row,previous in local[identifier]:
                updated={**previous,'isAdult':False,'status':item.get('status'),'nextAiringEpisode':item.get('nextAiringEpisode')}
                if not previous.get('title'):updated['title']=item.get('title')
                if updated!=previous:self.db.set_metadata(row['id'],identifier,updated)

    def vault_titles(self):
        stamp=self.db.change_stamp();cached=getattr(self,'_vault_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        latest={}
        for row in self.db.connection.execute('SELECT * FROM airing_updates WHERE airing_at<=? ORDER BY episode DESC,airing_at DESC',(int(time.time()),)):
            if self.allowed(metadata(row['metadata_json'])):latest.setdefault(row['media_id'],dict(row))
        inventory=self.inventory();result=[]
        for identifier,item in self.candidates().items():
            members=self.local_titles()[identifier];notice=latest.get(identifier)
            availability=self.availability(identifier,notice['episode'],inventory) if notice else None
            episodes=inventory.get(identifier,[]);numbers={m['episode'] for m in episodes if m['numbering_confident'] and positive_id(m['episode'])}
            result.append({'media_id':identifier,'item':item,'local_ids':tuple(r['id'] for r,_ in members),
                           'episode':notice['episode'] if notice else None,'availability':availability,
                           'local_count':len(episodes),'local_latest':max(numbers) if numbers else None,
                           'badge':('New ep '+str(notice['episode'])) if availability=='missing' else 'Airing'})
        result.sort(key=lambda r:(r['availability']!='missing',str(r['item'].get('title') or {}).casefold()))
        self._vault_cache=(self.db.change_stamp(),result)
        return result

    def inventory(self):
        stamp=self.db.change_stamp()
        cached=getattr(self,'_inventory_cache',None)
        if cached and cached[0]==stamp:return cached[1]
        by_local={r['id']:positive_id(r['anilist_id']) for r in self.db.anime_list()
                  if self.db.anime_scope(r,fresh=False)=='normal' and positive_id(r['anilist_id'])}
        result={identifier:[] for identifier in by_local.values()}
        for row in self.db.connection.execute("SELECT anime_id,season,episode,path,kind FROM media WHERE present=1 AND kind IN ('episode','movie','other','special')"):
            if row['anime_id'] in by_local:
                item=dict(row);parsed=classify_file(Path(row['path']),row['season'] or 1)
                item['numbering_confident']=row['kind']=='episode' and parsed.kind=='episode' and positive_id(parsed.episode)==positive_id(row['episode'])
                result[by_local[row['anime_id']]].append(item)
        for identifier,items in result.items():
            episodes=[m for m in items if m['kind']=='episode']
            if episodes:result[identifier]=episodes
        self._inventory_cache=(stamp,result)
        return result

    def availability(self, identifier, episode, inventory=None):
        inventory=self.inventory() if inventory is None else inventory
        if identifier not in inventory:return 'not_local'
        media=inventory[identifier]
        # Different local seasons, unidentified files and explicit multi-episode packs
        # cannot safely be mapped to AniList's per-season numbering.
        seasons = {m['season'] for m in media if m['season'] is not None}
        ambiguous = len(seasons) > 1 or any(not m['numbering_confident'] or not positive_id(m['episode']) or re.search(r'(?:E\d+\s*[-~+]\s*(?:E)?\d+|\b\d{2,3}\s*[-~]\s*\d{2,3}\b)', m['path'], re.I) for m in media)
        numbers = {m['episode'] for m in media if positive_id(m['episode'])}
        if ambiguous:
            return 'uncertain'
        if numbers and episode<min(numbers) and min(numbers)>1:return 'uncertain'
        return 'present' if episode in numbers else 'missing'

    def ingest(self, schedules, now=None):
        now = int(time.time() if now is None else now)
        # A trusted adult reclassification must also hide older normal history.
        # Retain only an opaque identity tombstone, never new private title/art.
        with self.db.connection:
            for schedule in schedules:
                item=schedule.get('media') or {};identifier=positive_id(schedule.get('mediaId'))
                if identifier and positive_id(item.get('id'))==identifier and item.get('type')=='ANIME' and item.get('isAdult') is True:
                    scrubbed=json.dumps({'id':identifier,'type':'ANIME','isAdult':True})
                    self.db.connection.execute('UPDATE airing_follows SET enabled=0,metadata_json=? WHERE media_id=?',(scrubbed,identifier))
                    self.db.connection.execute('UPDATE airing_updates SET metadata_json=? WHERE media_id=?',(scrubbed,identifier))
        candidates = self.candidates(); inventory=self.inventory(); added = 0
        with self.db.connection:
            for schedule in schedules:
                item = schedule.get('media') or {}; identifier = positive_id(schedule.get('mediaId'))
                episode = positive_id(schedule.get('episode')); at = positive_id(schedule.get('airingAt'))
                if identifier not in candidates or not episode or not at or positive_id(item.get('id')) != identifier or not self.allowed(item):
                    continue
                existing = self.db.connection.execute('SELECT 1 FROM airing_updates WHERE media_id=? AND episode=?', (identifier, episode)).fetchone()
                if at>now:
                    if existing:self.db.connection.execute('UPDATE airing_updates SET airing_at=? WHERE media_id=? AND episode=?',(at,identifier,episode))
                    continue
                self.db.connection.execute('INSERT INTO airing_updates(media_id,episode,airing_at,created_at,metadata_json,availability) VALUES(?,?,?,?,?,?) ON CONFLICT(media_id,episode) DO UPDATE SET airing_at=excluded.airing_at,metadata_json=excluded.metadata_json,availability=excluded.availability',
                                           (identifier, episode, at, now, json.dumps(item), self.availability(identifier, episode, inventory)))
                added += not bool(existing)
        return added

    def history(self, unread=False):
        blocked = self.blocked_ids(); inventory=self.inventory(); result = []
        for row in self.db.connection.execute('SELECT * FROM airing_updates WHERE dismissed=0 AND airing_at<=? ORDER BY airing_at DESC,media_id,episode DESC',(int(time.time()),)):
            record = dict(row); item = metadata(row['metadata_json'])
            if row['media_id'] in blocked or not self.allowed(item):
                continue
            if unread and row['is_read']:
                continue
            availability = self.availability(row['media_id'], row['episode'], inventory)
            if availability != row['availability']:
                self.db.connection.execute('UPDATE airing_updates SET availability=? WHERE media_id=? AND episode=?', (availability, row['media_id'], row['episode']))
            record['availability'] = availability; result.append(record)
        self.db.connection.commit()
        return result

    def mark(self, identifier=None, episode=None, dismiss=False):
        # Never mutate unrelated user data; preserve dismissed rows as dedup tombstones.
        field = 'dismissed' if dismiss else 'is_read'
        with self.db.connection:
            if identifier is None:
                for row in self.history():
                    self.db.connection.execute(f'UPDATE airing_updates SET {field}=1 WHERE media_id=? AND episode=?', (row['media_id'], row['episode']))
            else:
                self.db.connection.execute(f'UPDATE airing_updates SET {field}=1 WHERE media_id=? AND episode=?', (identifier, episode))


def availability_text(value, episode):
    return {'present': 'Already indexed in your library.',
            'missing': f'Your local library may be missing Episode {episode}. Check for a new release.',
            'not_local': 'This title is not in your normal library. Check for a new release.',
            'uncertain': "Episode identification is uncertain. Check your library for the latest release."}[value]


def fetch_airing_updates(identifiers, now, request=None, after=None):
    """Bounded batches, paginated official schedules, no estimated weekly dates.

    A first check covers 30 days. Later checks can extend back to the last
    successful check after a longer offline gap. Future schedules reconcile
    delayed broadcasts without changing the episode dedup identity.
    """
    from .anilist_integration import graphql
    request = request or graphql; results = []
    query = '''query($ids:[Int],$after:Int,$before:Int,$page:Int) {
      Page(page:$page,perPage:50) { pageInfo { hasNextPage }
        airingSchedules(mediaId_in:$ids,airingAt_greater:$after,airingAt_lesser:$before,sort:TIME) {
          mediaId episode airingAt media { id type isAdult title { english romaji } status format
          coverImage { large } season seasonYear } } } }'''
    for start in range(0, len(identifiers), 20):
        for page in range(1, 101):
            data = request(query, {'ids': list(identifiers[start:start+20]), 'after': now-30*86400 if after is None else after, 'before': now+14*86400+1, 'page': page})
            payload = data.get('Page')
            if not isinstance(payload, dict) or not isinstance(payload.get('airingSchedules'), list):
                raise RuntimeError('Incomplete airing schedule response')
            results.extend(payload['airingSchedules'])
            if not (payload.get('pageInfo') or {}).get('hasNextPage'):
                break
            # Keep notification traffic below 30 requests/minute; never sleep UI.
            time.sleep(2.1)
        else:
            raise RuntimeError('Airing schedule page limit reached')
        if start+20 < len(identifiers):
            time.sleep(2.1)
    return results


def fetch_vault_airing(identifiers, now, after=None, request=None):
    """Refresh identification status first, then retrieve actual episode schedules."""
    from .anilist_integration import graphql
    request=request or graphql;catalog=[]
    query="""query($ids:[Int]) { Page(perPage:50) { media(id_in:$ids,type:ANIME) {
      id type isAdult status title { english romaji } nextAiringEpisode { episode airingAt }
    } } }"""
    for start in range(0,len(identifiers),20):
        payload=request(query,{'ids':list(identifiers[start:start+20])}).get('Page')
        if not isinstance(payload,dict) or not isinstance(payload.get('media'),list):raise RuntimeError('Incomplete airing catalog')
        catalog.extend(payload['media'])
        if start+20<len(identifiers):time.sleep(2.1)
    airing=[i['id'] for i in catalog if i.get('type')=='ANIME' and i.get('isAdult') is False and i.get('status')=='RELEASING']
    schedules=fetch_airing_updates(airing,now,request,after) if airing else []
    return {'catalog':catalog,'schedules':schedules}
