"""Scoped one-hop related media, independent of Extras and manual groups."""
import time,weakref
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QWidget,QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from shiboken6 import isValid
from .media_cards import ContainedScrollArea
from .organization import display_title
from .anilist_integration import graphql,AniListHTTPError

def fetch_related(identifier,kind):
    query='''query($id:Int,$type:MediaType){Media(id:$id,type:$type){relations{edges{relationType node{id type isAdult format status episodes chapters title{romaji english native} coverImage{large} genres tags{name rank}}}}}}'''
    return (graphql(query,{'id':int(identifier),'type':kind}).get('Media') or {}).get('relations') or {}

class RelatedMixin:
    def _related_panel(self,item,scope='normal',presentation='local'):
        from .app import _append_playback_log
        panel=QFrame();panel.setObjectName('panel');panel.setProperty('relatedPanel',True);layout=QVBoxLayout(panel)
        title=QLabel('Franchise / Related');title.setObjectName('section');layout.addWidget(title)
        status=QLabel('Loading explicit AniList relations…');status.setWordWrap(True);layout.addWidget(status)
        from .app import ResponsiveLibraryGrid
        scroll=ContainedScrollArea();scroll.setWidgetResizable(True);scroll.setObjectName('relatedScroll');scroll.setMinimumHeight(480);scroll.hide()
        grid=ResponsiveLibraryGrid();scroll.setWidget(grid);layout.addWidget(scroll)
        load_started=time.perf_counter()
        identifier=item.get('id');kind=item.get('type') or 'ANIME';key=(scope,kind,identifier)
        if not identifier:status.setText('Match this title to AniList to see related media.');scroll.hide();return panel
        ref=weakref.ref(panel);cache=getattr(self,'_detail_relation_cache',{});self._detail_relation_cache=cache
        inflight=getattr(self,'_detail_relation_inflight',{});self._detail_relation_inflight=inflight
        def live():return ref() is not None and isValid(ref()) and self._organization_allowed(scope)
        def render(data):
            if not live():return
            grid.clear_cards();seen=set();entries=[];store=self.organization(scope)
            for edge in data.get('edges') or []:
                if not isinstance(edge,dict) or not isinstance(edge.get('node'),dict):continue
                node=edge['node'];target=node.get('id')
                if node.get('type') not in {'ANIME','MANGA'} or not target or target==identifier or target in seen:continue
                if not isinstance(node.get('isAdult'),bool) or node['isAdult']!=(scope=='restricted'):continue
                seen.add(target);entity=store.resolve(f'anilist:{target}',node)
                entries.append((edge,entity))
            # Stable one-hop API order within local / metadata-only sections.
            entries.sort(key=lambda entry:not bool(entry[1] and entry[1].local))
            for edge,entity in entries:
                node=edge['node'];card=self._entity_card(entity)
                card.clicked.disconnect();card.clicked.connect(lambda _,n=dict(node):self._open_related(n,scope))
                relation=str(edge.get('relationType') or 'Related').replace('_',' ').title()
                card.note.setText(node['type'].title()+' · '+str(node.get('format') or '').replace('_',' ').title()+' · '+relation)
                card.note.setToolTip(card.note.text());card.setProperty('relatedLocal',bool(entity.local));card.setProperty('relationType',edge.get('relationType'))
                grid.add_card(card)
            scroll.setVisible(bool(seen));scroll.setMinimumHeight(480 if seen else 0);scroll.setMaximumHeight(940)
            _append_playback_log(f'RelatedLoad scope={scope} media_type={kind} id={identifier} results={len(seen)} cached={key in cache} elapsed_ms={(time.perf_counter()-load_started)*1000:.0f}')
            status.setText('Explicit AniList relationships' if seen else 'No related titles available in this scope.')
        def loaded(data):
            if not isinstance(data,dict):failed(ValueError('Invalid related-media response'));return
            cache[key]=(time.time(),data)
            for callback,_ in inflight.pop(key,[]):callback(data)
        retry=QPushButton('Retry');retry.hide();layout.addWidget(retry)
        def show_failure(exc):
            if not live():return
            if isinstance(exc,AniListHTTPError) and exc.status_code==429:
                self._discover_cooldown_until=max(self._discover_cooldown_until,time.time()+max(1,int(exc.retry_after or 15)))
                status.setText('AniList is rate-limiting requests. Retry after the cooldown.')
            else:status.setText('Related media is temporarily unavailable.')
            retry.show()
        def failed(exc):
            listeners=inflight.pop(key,[]);_append_playback_log(f'RelatedLoad scope={scope} media_type={kind} id={identifier} exception={type(exc).__name__} message={exc}')
            for _,callback in listeners:callback(exc)
        def request():
            if not live():return
            if time.time()<self._discover_cooldown_until:status.setText('AniList is cooling down. Retry shortly.');retry.show();return
            retry.hide()
            if key in inflight:inflight[key].append((render,show_failure));return
            inflight[key]=[(render,show_failure)];self._submit_discover_job('related:'+str(key),lambda:fetch_related(identifier,kind),loaded,failed)
        retry.clicked.connect(request);cached=cache.get(key)
        if cached and time.time()-cached[0]<86400:render(cached[1])
        else:
            if item.get('relations'):render(item['relations'])
            request()
        return panel

    def _open_related(self,item,scope):
        if not self._organization_allowed(scope):return
        entity=self.organization(scope).resolve(f"anilist:{item['id']}",item)
        if entity and entity.local:
            self.show_manga_detail(entity.local['id']) if entity.media_type=='MANGA' else self.show_detail(entity.local['id'])
        else:self.show_remote_anilist(item,'Restricted' if scope=='restricted' else 'Discover')
