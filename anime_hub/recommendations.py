"""Local, deterministic recommendation signals; no network or database writes."""
from collections import Counter
from dataclasses import dataclass,field
from datetime import datetime,timezone
import hashlib
import json
import math
from .organization import media_type


def tags(item):
    result={}
    for tag in item.get('tags') or []:
        if not isinstance(tag,dict) or not tag.get('name') or tag.get('isMediaSpoiler'):continue
        try:rank=max(0,min(100,float(tag.get('rank') or 50)))/100
        except (ValueError,TypeError):rank=.5
        result[tag['name']]=rank
    return result


def recency(stamp,now):
    try:
        date=datetime.fromisoformat(str(stamp).replace('Z','+00:00'))
        if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
        days=max(0,(now-date).total_seconds()/86400)
        return .35+.65*math.exp(-days/60)
    except (ValueError,TypeError):return .7


@dataclass
class Profile:
    scope:str
    media_type:str
    fingerprint:str
    genres:Counter=field(default_factory=Counter)
    tags:Counter=field(default_factory=Counter)
    seeds:list=field(default_factory=list)
    excluded:set=field(default_factory=set)
    local:set=field(default_factory=set)
    relations:dict=field(default_factory=dict)
    relation_items:dict=field(default_factory=dict)

    def related_candidates(self):
        # Small cached relation shelf; no recursive lookup or extra HTTP jobs.
        identifiers=sorted(self.relation_items,key=lambda key:(-max(row[0] for row in self.relations[key]),key))[:8]
        return [self.relation_items[key] for key in identifiers]

    def query(self):
        # AniList combines genre/tag filters as constraints, not similarity.
        # One broad genre leaves ranking room; do not AND eight profile labels.
        top=sorted(self.genres,key=lambda key:(-self.genres[key],key))[:1]
        return {'genres':top,'sort':'POPULARITY_DESC' if top else 'TRENDING_DESC'}


def build_profile(organization,target_type='ANIME',now=None):
    now=(now or datetime.now(timezone.utc)).replace(hour=0,minute=0,second=0,microsecond=0);scope=organization.scope
    connection=organization.db.connection
    links={}
    for row in connection.execute('SELECT ce.collection_id,ce.entity_key FROM collection_entries ce JOIN collections c ON c.id=ce.collection_id WHERE c.scope=?',(scope,)):
        entity=organization.resolve(row[1])
        if entity:links.setdefault(entity.key,set()).add(row[0])
    memberships={key:len(value) for key,value in links.items()}
    updates={row['entity_key']:row['updated_at'] for row in connection.execute('SELECT entity_key,updated_at FROM manual_status WHERE scope=?',(scope,))}
    signals=[]
    for entity in list(organization.entities.values()):
        if entity.media_type not in {'ANIME','MANGA'}:continue
        item=entity.item;identifier=(entity.local or {}).get('anilist_id') or item.get('id')
        if not identifier:continue
        # Local manually private manga can lack AniList isAdult, but never seeds
        # normal data because the Organization itself is scoped.
        row=entity.local or {};progress=(row.get('watched_count') or 0)/max(1,row.get('episode_count') or 0) if entity.media_type=='ANIME' else (row.get('progress') or 0)/100
        consumed=row.get('last_watched_at') if entity.media_type=='ANIME' else row.get('last_read')
        favorite=bool(row.get('favorite'));status=entity.status
        stamp=consumed or max([entity.stamp or '',*[updates.get(key,'') for key in entity.aliases]])
        weight=(6 if favorite else 0)+{'Completed':4,'Watching':3,'Paused':1,'Planning':.6}.get(status,0)+4*max(0,min(1,progress))+(2 if consumed else 0)+(.35 if entity.saved else 0)
        if weight>0:weight+=min(1,memberships.get(entity.key,0)*.25)
        if status=='Dropped':weight=0
        signals.append((entity,int(identifier),round(weight*recency(stamp,now),6),favorite,progress,bool(consumed)))
    signature=[(e.media_type,i,w,e.status,e.title,sorted(e.item.get('genres') or []),sorted(tags(e.item).items()),e.item.get('relations'),bool(e.local)) for e,i,w,*_ in signals]
    fingerprint=hashlib.sha256(json.dumps(signature,sort_keys=True,default=str).encode()).hexdigest()
    profile=Profile(scope,target_type,fingerprint)
    for entity,identifier,weight,favorite,progress,consumed in signals:
        if entity.media_type==target_type:
            if entity.local:profile.local.add(identifier)
            if entity.status in {'Completed','Dropped'} or progress>=.8:profile.excluded.add(identifier)
        if weight<=0:continue
        # Cross-media affinity is explicit relations only, never title/genre
        # similarity inherited from the other media type.
        relation_data=entity.item.get('relations') or {}
        if not isinstance(relation_data,dict):relation_data={}
        for edge in (relation_data.get('edges') or []) if weight>=2 else []:
            if not isinstance(edge,dict):continue
            node=edge.get('node') or {}
            if not isinstance(node,dict):continue
            if node.get('type')==target_type and node.get('id') and edge.get('relationType') in {'ADAPTATION','SOURCE','PREQUEL','SEQUEL','SIDE_STORY','PARENT','SPIN_OFF','ALTERNATIVE','OTHER'}:
                try:related_id=int(node['id'])
                except (ValueError,TypeError):continue
                profile.relations.setdefault(related_id,[]).append((weight,identifier,entity.media_type))
                # Older relation caches lack the adult flag. They may inform
                # ranking of a validated API candidate, but cannot create a card.
                if isinstance(node.get('isAdult'),bool) and node['isAdult']==(scope=='restricted'):
                    profile.relation_items[related_id]=node
        if entity.media_type!=target_type:continue
        genres=set(entity.item.get('genres') or []);tag_values=tags(entity.item)
        for genre in genres:profile.genres[genre]+=weight
        for name,rank in tag_values.items():profile.tags[name]+=weight*rank
        profile.seeds.append({'id':identifier,'title':entity.title,'weight':weight,'genres':genres,'tags':tag_values,'favorite':favorite,'consumed':consumed,'status':entity.status})
    profile.seeds.sort(key=lambda seed:(-seed['weight'],seed['id']))
    return profile


def rank_candidates(profile,items,seen=None):
    seen=set(seen or ());counts=Counter();ranked=[]
    max_genre=max(profile.genres.values(),default=1);max_tag=max(profile.tags.values(),default=1)
    for item in items:
        if not isinstance(item,dict) or not item.get('id'):counts['malformed']+=1;continue
        try:identifier=int(item['id'])
        except (ValueError,TypeError):counts['malformed']+=1;continue
        if (item.get('isAdult') is True)!=(profile.scope=='restricted'):counts['scope']+=1;continue
        if media_type(item)!=profile.media_type:counts['media_type']+=1;continue
        if identifier in seen:counts['duplicate']+=1;continue
        seen.add(identifier)
        if identifier in profile.local:counts['already_local']+=1;continue
        if identifier in profile.excluded:counts['completed_or_dropped']+=1;continue
        genres=set(item.get('genres') or []);tag_values=tags(item)
        score=sum(profile.genres[g]/max_genre for g in genres)*2+sum(profile.tags[t]/max_tag*rank for t,rank in tag_values.items())*3
        reason=None;best=0;reason_seed=None
        for seed in profile.seeds:
            overlap=len(genres&seed['genres'])+2*sum(min(rank,seed['tags'].get(name,0)) for name,rank in tag_values.items())
            relevance=overlap*seed['weight']
            if relevance>best and seed['weight']>=2:best=relevance;reason_seed=seed
        if reason_seed and best>=3:
            seed=reason_seed
            if seed['consumed']:reason='Because you '+('read ' if profile.media_type=='MANGA' else 'watched ')+seed['title']
            elif seed['favorite']:reason='Similar to a title in Favorites'
            elif seed['status']=='Completed':reason='Similar to a completed title'
            elif seed['status']=='Watching':reason='Similar to a title you are '+('reading' if profile.media_type=='MANGA' else 'watching')
        if identifier in profile.relations:
            relation=max(profile.relations[identifier]);score+=min(6,relation[0]);reason='Explicit AniList relation to a title you like'
        # Sparse scores remain valid. Popularity only breaks equal affinity;
        # it cannot dominate the user's interest signals.
        try:popularity=float(item.get('popularity') or 0)
        except (ValueError,TypeError):popularity=0
        ranked.append((score,popularity,identifier,{**item,'_recommendation_reason':reason}))
    ranked.sort(key=lambda row:(-row[0],-row[1],row[2]))
    return [row[3] for row in ranked],dict(counts)
