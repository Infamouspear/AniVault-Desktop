"""Read-only franchise presentations built exclusively from explicit anime links."""
import json,re,time,heapq
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea
from shiboken6 import isValid
from .organization import display_title

LINKS={'PREQUEL','SEQUEL','SIDE_STORY','SPIN_OFF','PARENT'}

def metadata(row):
    try:
        value=json.loads(row['metadata_json'] or '{}');return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}

@dataclass
class LibraryFranchise:
    name:str
    rows:list
    edges:list
    scope:str='normal'
    @property
    def local_ids(self):return tuple(row['id'] for row in self.rows)

def build_franchises(rows,relations=None,scope='normal'):
    """No title similarity, manual group or cross-media edge can join records."""
    relations=relations or {};by_id={};parent={};edges=[];raw=[]
    for row in rows:
        item=metadata(row)
        if (item.get('isAdult') is True)!=(scope=='restricted') or not row['anilist_id']:continue
        identifier=int(row['anilist_id']);by_id.setdefault(identifier,[]).append(row);parent[identifier]=identifier
        for edge in (item.get('relations') or {}).get('edges') or []:
            if isinstance(edge,dict) and isinstance(edge.get('node'),dict):raw.append((identifier,edge.get('relationType'),edge['node']))
    for source,items in relations.items():
        try:source=int(source)
        except (ValueError,TypeError):continue
        if source in by_id and isinstance(items,list):
            for item in items:
                if isinstance(item,dict):raw.append((source,item.get('relationType'),item))
    def root(identifier):
        while parent[identifier]!=identifier:parent[identifier]=parent[parent[identifier]];identifier=parent[identifier]
        return identifier
    seen=set()
    for source,relation,node in raw:
        target=node.get('id')
        try:target=int(target)
        except (ValueError,TypeError):continue
        if relation not in LINKS or node.get('type')!='ANIME' or not target or int(target) not in by_id or source==int(target):continue
        if node.get('isAdult') is True and scope=='normal':continue
        key=(source,int(target),relation)
        if key in seen:continue
        seen.add(key);edges.append(key);parent[root(source)]=root(int(target))
    components={}
    for identifier in by_id:components.setdefault(root(identifier),[]).append(identifier)
    groups=[]
    for ids in components.values():
        if len(ids)<2:continue
        links=[edge for edge in edges if edge[0] in ids and edge[1] in ids]
        members=order_titles([row for i in ids for row in by_id[i]],links)
        names=[display_title(metadata(row)) for row in members]
        words=[re.findall(r"[\w’'-]+",name) for name in names];common=[]
        for parts in zip(*words):
            if len({word.casefold() for word in parts})!=1:break
            common.append(parts[0])
        # Only name the already-verified group; this never creates membership.
        name=' '.join(common) if len(common)>=2 or (common and len(common[0])>=4) else names[0]
        if not name or name=='Untitled':name=members[0]['title']
        groups.append(LibraryFranchise(name,members,links,scope))
    return groups

def order_titles(rows,edges):
    # Prefer complete start dates; otherwise follow explicit prequel/sequel order.
    def date(row):
        data=metadata(row);value=data.get('startDate') or {}
        return (value.get('year') or data.get('seasonYear') or 9999,value.get('month') or 1,value.get('day') or 1,row['id'])
    nodes={int(row['anilist_id']) for row in rows};out={i:set() for i in nodes};indegree={i:0 for i in nodes}
    for source,target,relation in edges:
        before,after=(target,source) if relation in {'PREQUEL','PARENT'} else (source,target)
        if after not in out[before]:out[before].add(after);indegree[after]+=1
    keys={i:min(date(row) for row in rows if row['anilist_id']==i) for i in nodes}
    queue=[(keys[i],i) for i in nodes if not indegree[i]];heapq.heapify(queue);ordered=[]
    while queue:
        _,i=heapq.heappop(queue);ordered.append(i)
        for child in sorted(out[i]):
            indegree[child]-=1
            if not indegree[child]:heapq.heappush(queue,(keys[child],child))
    ordered.extend(sorted(nodes-set(ordered),key=lambda i:keys[i]));positions={i:n for n,i in enumerate(ordered)}
    return sorted(rows,key=lambda row:(positions[row['anilist_id']],date(row)))


class LibraryFranchiseMixin:
    def _library_franchises(self,scope='normal'):
        self._load_library_relations()
        stamp=(self.db.change_stamp(),getattr(self,'_library_relation_revision',0),scope)
        cached=getattr(self,'_library_franchise_cache',{})
        if cached.get('stamp')!=stamp:
            rows=[]
            for row in self.db.anime_list():
                if self.db.anime_scope(row)==scope:
                    row=dict(row);row['metadata_json']=json.dumps({**metadata(row),'isAdult':scope=='restricted'});rows.append(row)
            cached={'stamp':stamp,'groups':build_franchises(rows,getattr(self,'_library_relation_data',{}),scope)};self._library_franchise_cache=cached
        return cached['groups']

    def _load_library_relations(self):
        if hasattr(self,'_library_relation_data'):return
        from .app import APP_DIR
        self._library_relation_path=APP_DIR/'cache'/'library_relations.json';self._library_relation_data={};self._library_relation_dates={};self._library_relation_revision=0;self._library_relations_loading=False
        try:
            data=json.loads(self._library_relation_path.read_text())
            relations=data.get('relations');timestamps=data.get('timestamps')
            self._library_relation_data=relations if isinstance(relations,dict) else {};self._library_relation_dates={key:float(value) for key,value in (timestamps or {}).items() if isinstance(value,(int,float))}
        except (OSError,ValueError,TypeError,AttributeError):pass

    def _request_library_relations(self,force=False):
        from .anilist_integration import fetch_anime_relations,AniListHTTPError
        from .app import _append_playback_log
        self._load_library_relations()
        if self._closing or self._library_relations_loading or time.time()<self._discover_cooldown_until:return
        ids=sorted({int(row['anilist_id']) for row in self.db.anime_list() if row['anilist_id'] and metadata(row).get('isAdult') is not True and (force or time.time()-self._library_relation_dates.get(str(row['anilist_id']),0)>7*86400)})
        if not ids:return
        batch=ids[:20];self._library_relations_loading=True
        def loaded(items):
            self._library_relations_loading=False
            if self._closing:return
            for identifier in batch:
                self._library_relation_data[str(identifier)]=[item for item in items if item.get('sourceAniListId')==identifier and item.get('type')=='ANIME'];self._library_relation_dates[str(identifier)]=time.time()
            self._library_relation_revision+=1;self._library_franchise_cache={}
            self._library_relation_path.parent.mkdir(parents=True,exist_ok=True);temporary=self._library_relation_path.with_suffix('.tmp')
            try:temporary.write_text(json.dumps({'relations':self._library_relation_data,'timestamps':self._library_relation_dates}));temporary.replace(self._library_relation_path)
            except OSError as exc:_append_playback_log(f'LibraryRelations cache_error={type(exc).__name__}')
            _append_playback_log(f'LibraryRelations sources={len(batch)} edges={len(items)} groups={len(self._library_franchises())}')
            active=self.stack.currentWidget();normal_return=self._normal_return_state[0] if self._normal_return_state else None
            retired_pages={entry[0] for entry in self._library_page_cache.values()};self._library_page_cache.clear()
            for retired in retired_pages:
                if retired is not active and retired is not normal_return and isValid(retired):self.stack.removeWidget(retired);retired.deleteLater()
            if self.current_view=='library' and self.active_nav_key=='all':
                page=self.stack.currentWidget();scroll=page.findChild(QScrollArea)
                # Group on the first screen, never move a user's scrolled viewport.
                from PySide6.QtWidgets import QComboBox
                view=page.findChild(QComboBox,'libraryViewMode')
                if scroll is not None and scroll.verticalScrollBar().value()==0 and view is not None and view.currentText()=='Franchises':
                    rebuild=getattr(page,'refresh_franchises',None)
                    if rebuild:rebuild()
                else:self.statusBar().showMessage('Franchise relationships updated. Reopen All Anime to see groups.',5000)
                QTimer.singleShot(500,lambda:self._request_library_relations() if not self._closing and self.current_view=='library' and self.active_nav_key=='all' else None)
        def failed(exc):
            self._library_relations_loading=False
            if isinstance(exc,AniListHTTPError) and exc.status_code==429:self._discover_cooldown_until=max(self._discover_cooldown_until,time.time()+int(exc.retry_after or 15))
            _append_playback_log(f'LibraryRelations failure={type(exc).__name__} fallback=individual_titles')
        self._submit_discover_job('library-relations:'+str(batch),lambda:fetch_anime_relations(batch),loaded,failed)

    def _franchise_card(self,group):
        from .polish_ui import CoverListCard
        store=self.organization(group.scope);entities=[store.resolve('local:'+str(row['id'])) for row in group.rows]
        covers=self._entity_cover_paths([e for e in entities if e]);watched=sum(row['watched_count'] or 0 for row in group.rows);total=sum(row['episode_count'] or 0 for row in group.rows)
        card=CoverListCard(group.name,f'{len(group.rows)} local anime titles',covers,width=184,height=350,art_height=235)
        card.setProperty('posterCard',True);card.count_label.setToolTip(f'{watched}/{total} watched')
        self._register_status_card(card,group.scope,'local:'+str(group.rows[0]['id']))
        card.setProperty('franchiseName',group.name);card.setProperty('franchiseLocalIds',group.local_ids);card.clicked.connect(lambda:self.show_library_franchise(group.local_ids,group.scope));return card

    def show_library_franchise(self,local_ids,scope='normal'):
        if not self._organization_allowed(scope):return
        rows=[row for row in self.db.anime_list() if row['id'] in local_ids and self.db.anime_scope(row)==scope]
        group=next((g for g in self._library_franchises(scope) if set(local_ids)<=set(g.local_ids)),None)
        if group is None:
            if len(rows)==1:self.show_detail(rows[0]['id'])
            else:self.show_library()
            return
        self.current_view='restricted_library_franchise' if scope=='restricted' else 'library_franchise';self.current_anime_id=None;self.current_library_franchise=(tuple(local_ids),scope);self._set_active_nav('restricted' if scope=='restricted' else 'all')
        page=QWidget();page.setProperty('transientPage',True);outer=QVBoxLayout(page);self._top_header(outer);header=QHBoxLayout();back=QPushButton('← Back');back.clicked.connect(self.navigate_back);header.addWidget(back);title=QLabel(group.name);title.setObjectName('title');header.addWidget(title);header.addStretch();outer.addLayout(header)
        outer.addWidget(QLabel(f'{len(group.rows)} local anime titles · Individual watch state and playback remain separate'))
        from .app import ResponsiveLibraryGrid
        scroll=QScrollArea();scroll.setWidgetResizable(True);host=QWidget();flow=QVBoxLayout(host);flow.setSpacing(10);flow.setContentsMargins(0,0,0,8);grid=ResponsiveLibraryGrid();flow.addWidget(grid)
        store=self.organization(scope)
        for row in group.rows:
            entity=store.resolve('local:'+str(row['id']));card=self._entity_card(entity)
            relation=' / '.join(sorted({relation.replace('_',' ').title() for source,target,relation in group.edges if source==row['anilist_id']})) or 'Related'
            label=QLabel(f"{metadata(row).get('format') or 'Anime'} · In Vault · {row['watched_count'] or 0} / {row['episode_count'] or 0} watched\n{entity.status or 'No manual status'} · {relation}");label.setWordWrap(True);label.setObjectName('muted');label.setAlignment(Qt.AlignCenter);card.status_label.setText(relation);card.status_label.setToolTip(label.text());label.deleteLater();grid.add_card(card)
        remote_nodes={}
        local_anilist={row['anilist_id'] for row in group.rows}
        for row in group.rows:
            nodes=[dict(edge.get('node') or {},relationType=edge.get('relationType')) for edge in (metadata(row).get('relations') or {}).get('edges') or [] if edge.get('relationType') in LINKS]
            nodes.extend(getattr(self,'_library_relation_data',{}).get(str(row['anilist_id']),[]))
            for node in nodes:
                if node.get('type')=='ANIME' and node.get('id') not in local_anilist and (node.get('isAdult') is True)==(scope=='restricted'):remote_nodes[node['id']]=node
        if remote_nodes:
            title=QLabel('AniList-only related anime');title.setObjectName('section');flow.addWidget(title);remote_grid=ResponsiveLibraryGrid();flow.addWidget(remote_grid)
            for node in sorted(remote_nodes.values(),key=lambda value:(value.get('seasonYear') or 9999,display_title(value))):
                entity=store.resolve('anilist:'+str(node['id']),node);card=self._entity_card(entity)
                relation=str(node.get('relationType') or 'Related').replace('_',' ').title()
                label=QLabel(f"{node.get('format') or 'Anime'} · AniList-only\n{entity.status or 'No manual status'} · {relation}");label.setWordWrap(True);label.setObjectName('muted');label.setAlignment(Qt.AlignCenter)
                card.note.setText(label.text());label.deleteLater();card.setToolTip('AniList-only · '+relation);remote_grid.add_card(card)
        flow.addStretch();scroll.setWidget(host);outer.addWidget(scroll);self.replace(page)
