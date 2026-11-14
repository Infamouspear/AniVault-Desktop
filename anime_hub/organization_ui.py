"""Shared organization views built from existing anime/manga/discovery cards."""
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QComboBox
from .organization import Organization


class OrganizationMixin:
    def _recommendation_profile(self,scope,media_type):
        from .recommendations import build_profile
        from .app import _append_playback_log
        import time
        key=(scope,media_type);now=time.time();stamp=self.db.connection.total_changes
        cached=self._recommendation_profile_cache.get(key)
        if cached and cached['stamp']==stamp and now-cached['built']<900:return cached['profile']
        profile=build_profile(self.organization(scope),media_type)
        if cached and cached['profile'].fingerprint==profile.fingerprint and now-cached['built']<900:
            cached['stamp']=stamp;return cached['profile']
        self._recommendation_profile_cache[key]={'profile':profile,'stamp':stamp,'built':now}
        _append_playback_log(f'RecommendationProfile scope={scope} media_type={media_type} seeds={len(profile.seeds)} local_excluded={len(profile.local)}')
        return profile

    def _rank_recommendations(self,profile,items,seen=None):
        from .recommendations import rank_candidates
        from .app import _append_playback_log
        rows,counts=rank_candidates(profile,items,seen)
        _append_playback_log(f'RecommendationBuild scope={profile.scope} media_type={profile.media_type} candidate_count={len(items)} result_count={len(rows)} filtered={counts} explained={sum(bool(row.get("_recommendation_reason")) for row in rows)}')
        return rows

    def _refresh_recommendations(self,restricted,media_type):
        import json
        scope='restricted' if restricted else 'normal'
        query=self._recommendation_profile(scope,media_type).query()
        for page in range(1,4):
            params={'page':page,'is_adult':restricted,'media_type':media_type,**query}
            self._discover_cache.pop(json.dumps(params,sort_keys=True,separators=(',',':')),None)
        self._recommendation_profile_cache.pop((scope,media_type),None)
        self._section_page_cache.pop(('restricted_discover:' if restricted else 'discover:')+media_type,None)
        self.show_discover(restricted,media_type)

    def organization(self,scope='normal'):
        # SQLite's mutation counter invalidates all organization data, including
        # reader progress, matching, status and Favorite changes. Scope is part
        # of the key; a cached private catalog is never reused on the normal side.
        stamp=self.db.change_stamp()
        cache=getattr(self,'_organization_cache',{})
        if cache.get('stamp')!=stamp:cache={'stamp':stamp,'scopes':{}};self._organization_cache=cache
        if scope not in cache['scopes']:cache['scopes'][scope]=Organization(self.db,self.manga_store,scope)
        return cache['scopes'][scope]

    def _organization_allowed(self,scope):
        return scope=='normal' or self.db.setting('restricted_unlocked','0')=='1'

    def _entity_card(self,entity,collection_id=None):
        from .app import Card,SeasonCard
        if entity.local and entity.media_type=='MANGA':
            row=dict(entity.local);row['manual_status']=entity.status
            card=self.make_manga_card(row,collection_id)
        elif entity.local:
            row=entity.local
            card=Card(row,show_progress=(row['watched_count'] or 0)>0,manual_status=entity.status)
            card.clicked.connect(self.show_detail)
            self._attach_collection_menu(card,row['id'],collection_id,scope=entity.scope)
        elif entity.media_type=='EXTERNAL':
            card=self._source_card(entity.item)
            if collection_id:
                card.customContextMenuRequested.disconnect()
                card.customContextMenuRequested.connect(lambda pos,c=card:self._source_menu(c,pos,entity.item,collection_id))
        else:
            card=SeasonCard(entity.item,False,self._load_remote_artwork,False,False,entity.status)
            card.saved_scope=entity.scope
            card.clicked.connect(lambda _:self.show_remote_anilist(entity.item,'Restricted' if entity.scope=='restricted' else 'Saved'))
            card.save_toggled.connect(lambda _,value:self.set_saved(entity.item,value,entity.scope))
            card.setContextMenuPolicy(Qt.CustomContextMenu)
            card.customContextMenuRequested.connect(lambda pos,c=card:self.remote_anime_menu(c,pos,entity.item,entity.scope,collection_id))
        for key in entity.aliases:self._register_status_card(card,entity.scope,key)
        # Labels are explicit without changing the stable dimensions of cards.
        card.setToolTip(entity.label+'\n'+entity.title)
        card.setProperty('organizationKey',entity.key)
        card.setProperty('organizationMedia',entity.media_type)
        if entity.local and entity.media_type!='MANGA' and hasattr(card,'secondary'):
            card.secondary.setText(entity.label);card.secondary.setToolTip(entity.label)
        return card

    def _organization_page(self,title,entities,scope='normal',collection_id=None,sort=False,grouped=False):
        from .app import ResponsiveLibraryGrid
        from .media_cards import POSTER_CARD_WIDTH
        page=QWidget();page.setProperty('transientPage',True);outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);self._top_header(outer)
        if scope=='restricted':self._restricted_nav(outer)
        header=QHBoxLayout();back=QPushButton('← Back');back.clicked.connect(self.navigate_back);header.addWidget(back)
        heading=QLabel(title);heading.setObjectName('title');header.addWidget(heading);header.addStretch()
        if collection_id:
            for text,action in [('Rename Collection',self.rename_collection),('Edit Description',self.edit_collection_description),('Delete Collection',self.delete_collection)]:
                button=QPushButton(text);button.clicked.connect(lambda _,f=action:f(collection_id));header.addWidget(button)
        outer.addLayout(header)
        if collection_id:
            description=self.db.collection(collection_id)['description']
            if description:label=QLabel(description);label.setWordWrap(True);outer.addWidget(label)
        count=QLabel(f'{len(entities)} titles');count.setObjectName('muted');outer.addWidget(count)
        selector=QComboBox();selector.addItems(['Date Added','Title','Year','Recently Watched / Read']);selector.setVisible(sort);outer.addWidget(selector,0,Qt.AlignRight)
        scroll=QScrollArea();scroll.setWidgetResizable(True);grid=ResponsiveLibraryGrid()
        if grouped:
            host=QWidget();groups_layout=QVBoxLayout(host);group_grids={}
            for kind in ('ANIME','MANGA','EXTERNAL'):
                selected=[entity for entity in entities if entity.media_type==kind]
                if not selected:continue
                label=QLabel('External Bookmarks' if kind=='EXTERNAL' else (kind.title()+' Favorites' if title=='Favorites' else kind.title()));label.setObjectName('section');groups_layout.addWidget(label)
                group_grid=ResponsiveLibraryGrid(card_width=POSTER_CARD_WIDTH if all(e.local for e in selected) else 228);group_grids[kind]=group_grid;groups_layout.addWidget(group_grid)
            if not group_grids:groups_layout.addWidget(self._empty_state('results' if 'search' in self.current_view else 'empty','No matching titles.',scope))
            groups_layout.addStretch();scroll.setWidget(host)
        else:scroll.setWidget(grid)
        outer.addWidget(scroll)
        def render():
            grid.clear_cards();rows=list(entities)
            if selector.currentText()=='Title':rows.sort(key=lambda e:e.title.casefold())
            elif selector.currentText()=='Year':rows.sort(key=lambda e:e.item.get('seasonYear') or (e.item.get('startDate') or {}).get('year') or 0,reverse=True)
            elif selector.currentText()=='Recently Watched / Read':rows.sort(key=lambda e:(e.local or {}).get('last_read') or (e.local or {}).get('last_watched_at') or '',reverse=True)
            if grouped:
                for kind,group_grid in group_grids.items():
                    group_grid.clear_cards();group_grid.add_cards(self._entity_card(entity,collection_id) for entity in rows if entity.media_type==kind)
            else:
                cards=[self._entity_card(entity,collection_id) for entity in rows]
                grid.add_cards(cards or [self._empty_state('results' if 'search' in self.current_view else 'empty','No matching titles.',scope)])
        selector.currentTextChanged.connect(render);self.replace(page);render()
        return page

    def show_global_search(self,query='',scope='normal'):
        from .app import _append_playback_log
        if not self._organization_allowed(scope):return
        started=time.perf_counter();store=self.organization(scope);entities=store.search(query)
        self.current_view='restricted_global_search' if scope=='restricted' else 'global_search';self.current_search=(query,scope);self.current_anime_id=None;self._set_active_nav('restricted' if scope=='restricted' else 'all')
        self._organization_page('Search your vault',entities,scope)
        counts={kind:sum(e.media_type==kind for e in entities) for kind in ['ANIME','MANGA','EXTERNAL']}
        _append_playback_log(f'GlobalSearch scope={scope} query_length={len(query)} anime={counts["ANIME"]} manga={counts["MANGA"]} external={counts["EXTERNAL"]} results={len(entities)} elapsed_ms={(time.perf_counter()-started)*1000:.1f}')

    def show_favorites(self,scope='normal'):
        if not self._organization_allowed(scope):return
        self.current_view='restricted_favorites' if scope=='restricted' else 'favorites';self.current_anime_id=None;self._set_active_nav('restricted' if scope=='restricted' else 'favorites')
        self._organization_page('Favorites',self.organization(scope).favorites(),scope,grouped=True)

    def _show_organized_collection(self,cid,scope):
        if not self._organization_allowed(scope):return
        collection=self.db.collection(cid)
        if not collection or collection['scope']!=scope:return self.show_collections(scope)
        self.current_view='restricted_collection_detail' if scope=='restricted' else 'collection_detail';self.current_collection_id=cid;self.current_collection_scope=scope;self.current_anime_id=None;self._set_active_nav('restricted' if scope=='restricted' else 'collections')
        self._organization_page(collection['name'],self.organization(scope).collection(cid),scope,cid,True)

    def _show_organized_status(self,status,scope):
        if not self._organization_allowed(scope):return
        self.current_view='restricted_status_list' if scope=='restricted' else 'status_list';self.current_status_name=status;self.current_collection_scope=scope;self.current_anime_id=None;self._set_active_nav('restricted' if scope=='restricted' else 'collections')
        self._organization_page('Watching / Reading' if status=='Watching' else status,self.organization(scope).statuses(status),scope,grouped=True)
