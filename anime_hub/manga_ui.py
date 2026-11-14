"""Local Manga UI integration; the V0.8.1 reader remains the only reader."""
from __future__ import annotations
import json
import time
import weakref
from pathlib import Path
from shiboken6 import isValid
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QPixmap, QFontMetrics
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
    QScrollArea,QLineEdit,QComboBox,QProgressBar,QMenu,QDialog,QListWidget,QListWidgetItem,QFileDialog)
from .media_cards import POSTER_WIDTH,POSTER_HEIGHT,POSTER_CARD_WIDTH,poster_layout,CARD_WIDTH,CARD_HEIGHT,COVER_WIDTH,COVER_HEIGHT,media_layout,text_slot,footer_slot,ContainedListWidget
from .manga_library import MangaStore
from .display_titles import clean_manga_display_title
from .manga_jobs import MangaJobs
from .anilist_integration import fetch_discover_page,graphql,AniListHTTPError

def ui():
    from . import app
    return app

class MangaCard(QFrame):
    clicked=Signal(int)
    def __init__(self,row):
        super().__init__();self.row=dict(row);self.setObjectName('card');self.setCursor(Qt.PointingHandCursor);layout=poster_layout(self)
        self.cover=QLabel('MANGA');self.cover.setAlignment(Qt.AlignCenter);self.cover.setFixedSize(POSTER_WIDTH,POSTER_HEIGHT);self.cover.setStyleSheet('background:#17202b;border-radius:8px;color:#707d8c;');layout.addWidget(self.cover)
        name=('♥  ' if row['favorite'] else '')+row.get('display_title',row['title']);self.title_label=ui().TwoLineLabel(name);self.title_label.setFixedHeight(36);self.title_label.setObjectName('cardTitle');self.title_label.setToolTip(name);layout.addWidget(self.title_label)
        self.status_label=text_slot(layout,'muted',20);self.set_manual_status(row['manual_status'])
        self.secondary=text_slot(layout,'muted',17);self.secondary.setAlignment(Qt.AlignCenter);value=row.get('active_label') or row['last_read_label'] or 'Not started';self.secondary.setText(QFontMetrics(self.secondary.font()).elidedText(value,Qt.ElideRight,COVER_WIDTH));self.secondary.setToolTip(value)
        progress=QProgressBar();progress.setRange(0,100);progress.setValue(int(row['progress'] or 0));progress.setTextVisible(False);progress.setFixedHeight(3);progress.setVisible(0<int(row['progress'] or 0)<100);layout.addWidget(progress)
        from .media_cards import card_input
        card_input(self,lambda:self.clicked.emit(self.row['id']));self.cover_requested=False
    def set_manual_status(self,status):
        self.row['manual_status']=status;self.status_label.setText(ui()._status_markup('Reading' if status=='Watching' else status,'Missing items' if not self.row['available_count'] else ''))
    def set_favorite(self,value):
        self.row['favorite']=value;self.title_label.setText(('♥  ' if value else '')+self.row.get('display_title',self.row['title']))
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit(self.row['id'])
        super().mouseReleaseEvent(event)

class MangaLibraryMixin:
    def _init_manga_library(self):
        self.manga_store=MangaStore(self.db,ui().APP_DIR);self.manga_context={'scope':'normal','search':'','filter':'All','sort':'Title'};self.current_manga_id=None;self.current_manga_item_id=None
        self._manga_jobs=None;self._manga_cover_refs={};self._manga_cover_attempts=set();self._manga_remote_cover_failures=set();self._manga_scope_dirty=False
        self._manga_cover_timer=QTimer(self);self._manga_cover_timer.setInterval(140);self._manga_cover_timer.timeout.connect(self._request_visible_manga_covers)
        self._manga_cover_timer.start()
        self._manga_closing=False
    def _ensure_manga_jobs(self):
        if self._manga_jobs is None:
            self._manga_jobs=MangaJobs(ui().APP_DIR/'cache'/'manga_covers');self._manga_jobs.scanned.connect(self._manga_scanned);self._manga_jobs.scan_failed.connect(self._manga_scan_failed);self._manga_jobs.cover_ready.connect(self._manga_cover_ready)
        return self._manga_jobs
    def _manga_allowed(self,scope):return scope=='normal' or self.db.setting('restricted_unlocked','0')=='1'
    def _stop_manga_jobs(self):
        self._manga_closing=True
        self._manga_cover_timer.stop()
        if self._manga_jobs:
            self._manga_jobs.stop()
            for signal,slot in [(self._manga_jobs.scanned,self._manga_scanned),(self._manga_jobs.scan_failed,self._manga_scan_failed),(self._manga_jobs.cover_ready,self._manga_cover_ready)]:signal.disconnect(slot)
    def _manga_scan_failed(self,message):
        if self._manga_closing:return
        self._manga_scan_busy=False;ui()._append_playback_log('MangaScanError '+message);self.statusBar().showMessage('Manga scan failed; previous library state is preserved.',7000)
    def scan_manga_library(self):
        scope=self.manga_context['scope']
        if not self._manga_allowed(scope):return
        roots=[root for root in self.manga_store.roots() if root['scope']==scope]
        if not roots:self.manage_manga_roots(self.manga_context['scope']);return
        if self._ensure_manga_jobs().scan(roots):
            self._manga_scan_busy=True;ui()._append_playback_log('MangaScanStart roots='+json.dumps([r['path'] for r in roots]));self.statusBar().showMessage('Scanning manga read-only…')
    def _manga_scanned(self,result):
        if self._manga_closing:return
        self._manga_scan_busy=False
        try:summary=self.manga_store.reconcile(result)
        except Exception as exc:self._manga_scan_failed(f'{type(exc).__name__}: {exc}');return
        # Cap detail logging, while preserving summary totals for large libraries.
        logged=0
        for series in result['series'].values():
            if logged<100:ui()._append_playback_log(f"MangaSeriesDetected title={series['title']} path={series['root_path']} item_count={len(series['items'])}")
            for item in series['items']:
                if logged<100:ui()._append_playback_log(f"MangaItemDetected path={item['path']} source_type={item['source_type']} volume={item['volume']} chapter={item['chapter']}")
                logged+=1
        ui()._append_playback_log('MangaScanSummary '+' '.join(f'{k}={v}' for k,v in summary.items())+f' detail_logs_capped={logged>100}')
        for error in result['errors'][:10]:ui()._append_playback_log('MangaScanError '+error)
        self._manga_cover_attempts.clear();self.statusBar().showMessage(f"Manga scan: {summary['series']} series, {summary['items']} items; {summary['errors']} errors",8000)
        if self.current_view in {'manga_library','restricted_manga_library'}:self.show_manga_library(**self.manga_context)
        elif self.current_view in {'manga_detail','restricted_manga_detail'}:self.show_manga_detail(self.current_manga_id)
    def manage_manga_roots(self,scope='normal'):
        if not self._manga_allowed(scope):return
        dialog=ui().AniVaultDialog(self,'Manga Library Roots','Only indexed; source files are never modified.',None,False,(('Done',True),));dialog.resize(660,340)
        panel=dialog.findChild(QFrame,'vaultDialogPanel').layout()
        roots=QListWidget();panel.insertWidget(2,roots)
        def refresh():
            roots.clear()
            for root in self.manga_store.roots():
                if root['scope']==scope:
                    item=QListWidgetItem(root['path']);item.setData(Qt.UserRole,root['id']);roots.addItem(item)
        actions=QHBoxLayout();add=QPushButton('Add Root…');remove=QPushButton('Remove Root');actions.addWidget(add);actions.addWidget(remove);panel.insertLayout(3,actions)
        def choose():
            path=QFileDialog.getExistingDirectory(dialog,'Choose '+('Restricted ' if scope=='restricted' else '')+'Manga Root')
            if not path:return
            try:self.manga_store.add_root(path,scope)
            except ValueError as exc:ui().AniVaultDialog.alert(dialog,'Manga Root',str(exc));return
            refresh()
        def disable():
            selected=roots.currentItem()
            if selected and ui().AniVaultDialog.confirm(dialog,'Remove Manga Root','Stop showing this root? Reading history and source files will be preserved.','Remove Root'):
                self.manga_store.disable_root(selected.data(Qt.UserRole));refresh()
        add.clicked.connect(choose);remove.clicked.connect(disable);refresh();dialog.exec()
        if self.current_view in {'manga_library','restricted_manga_library'}:self.show_manga_library(**self.manga_context)
    def show_manga_library(self,scope='normal',search='',filter='All',sort='Title'):
        if not self._manga_allowed(scope):self.show_home();return
        started=time.perf_counter();self.manga_context={'scope':scope,'search':search,'filter':filter,'sort':sort};self.current_view='restricted_manga_library' if scope=='restricted' else 'manga_library';self._set_active_nav('restricted' if scope=='restricted' else 'manga')
        page=QWidget();page.setProperty('mangaPage',True);outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18)
        if scope=='restricted':self._restricted_nav(outer)
        header=QHBoxLayout();title=QLabel('Restricted Local Manga' if scope=='restricted' else 'Manga');title.setObjectName('title');header.addWidget(title);header.addStretch()
        for label,action in [('Roots…',lambda:self.manage_manga_roots(scope)),('Rescan Manga',self.scan_manga_library),('Open Manga / Comic…',self.choose_local_manga)]:
            button=QPushButton(label);button.clicked.connect(action);header.addWidget(button)
        outer.addLayout(header)
        controls=QHBoxLayout();text=QLineEdit(search);text.setPlaceholderText('Search local manga…');controls.addWidget(text,1)
        filters=QComboBox();filters.addItems(['All','Continue Reading','Recently Read','In Progress','No Status','Reading','Planning','Completed','Paused','Dropped','Unread / Not Started','Progress Complete','Favorites','Recently Added']);filters.setCurrentText(filter);controls.addWidget(filters)
        sorts=QComboBox();sorts.addItems(['Title','Recently Added','Recently Read','Progress']);sorts.setCurrentText(sort);controls.addWidget(sorts);outer.addLayout(controls)
        status=QLabel();status.setObjectName('muted');outer.addWidget(status)
        scroll=QScrollArea();scroll.setWidgetResizable(True);grid=ui().ResponsiveLibraryGrid(card_width=POSTER_CARD_WIDTH);scroll.setWidget(grid);outer.addWidget(scroll)
        rows=self.manga_store.series_list(scope);generation={'value':0}
        def render(*args):
            rows=self.manga_store.series_list(scope)
            generation['value']+=1;token=generation['value'];grid.clear_cards()
            chosen=filters.currentText();needle=text.text().casefold();items=[row for row in rows if needle in row.get('search_titles',row['title']).casefold()]
            if chosen in {'Reading','Planning','Completed','Paused','Dropped'}:
                enum='Watching' if chosen=='Reading' else chosen
                items=[r for r in items if r['manual_status']==enum or (chosen=='Reading' and not r['manual_status'] and 0<(r['progress'] or 0)<100)]
            elif chosen=='Continue Reading':items=[r for r in items if r['active_item_id'] or (r['last_read'] and 0<(r['completed_count'] or 0)<r['available_count'])]
            elif chosen=='Recently Read':items=[r for r in items if r['last_opened']]
            elif chosen=='In Progress':items=[r for r in items if 0<(r['progress'] or 0)<100]
            elif chosen=='No Status':items=[r for r in items if not r['manual_status']]
            elif chosen=='Unread / Not Started':items=[r for r in items if not (r['progress'] or 0)]
            elif chosen=='Progress Complete':items=[r for r in items if r['item_count'] and r['completed_count']==r['item_count']]
            elif chosen=='Favorites':items=[r for r in items if r['favorite']]
            order='Recently Added' if chosen=='Recently Added' else 'Recently Read' if chosen in {'Recently Read','Continue Reading'} else sorts.currentText()
            if order=='Recently Added':items.sort(key=lambda r:(r['added_at'],r['id']),reverse=True)
            elif order=='Recently Read':items.sort(key=lambda r:(r['last_opened'] or r['last_read'] or '',r['id']),reverse=True)
            elif order=='Progress':items.sort(key=lambda r:r['progress'] or 0,reverse=True)
            else:items.sort(key=lambda r:r.get('display_title',r['title']).casefold())
            self.manga_context.update(search=text.text(),filter=chosen,sort=sorts.currentText())
            status.setText(f'{len(items)} series · '+('Choose a root, then Rescan Manga.' if not rows else 'Filesystem availability and reading progress are local.'))
            if not items:grid.add_card(self._empty_state('caught_up' if chosen=='Continue Reading' else 'results' if text.text() or chosen!='All' else 'empty','All caught up.' if chosen=='Continue Reading' else 'No manga here yet.',scope,copy='Add a root and scan, or change filters.'));return
            def append(offset=0):
                if not isValid(page) or token!=generation['value'] or self.stack.currentWidget() is not page:return
                grid.add_cards([self.make_manga_card(row,continue_mode=chosen=='Continue Reading') for row in items[offset:offset+24]])
                if offset+24<len(items):QTimer.singleShot(0,lambda:append(offset+24))
            append()
        text.returnPressed.connect(render);filters.currentTextChanged.connect(render);sorts.currentTextChanged.connect(render)
        self.replace(page);render();ui()._append_playback_log(f'MangaPageVisible scope={scope} series={len(rows)} elapsed_ms={(time.perf_counter()-started)*1000:.1f}')
    def make_manga_card(self,row,collection_id=None,continue_mode=False):
        card=MangaCard(row);card.clicked.connect(self.show_manga_detail);self._register_status_card(card,row['scope'],f"manga:{row['id']}")
        if continue_mode:
            card.layout().takeAt(5);footer=QWidget(card);footer.setFixedHeight(28);footer.setStyleSheet('background:transparent');box=QHBoxLayout(footer);box.setContentsMargins(0,0,0,0)
            button=QPushButton('Continue Reading');button.setObjectName('mangaContinue');button.setFixedHeight(28);button.setStyleSheet('padding:3px 7px');button.clicked.connect(lambda:self._continue_manga(row['id']));box.addWidget(button);card.layout().insertWidget(5,footer)
        card.setContextMenuPolicy(Qt.CustomContextMenu);card.customContextMenuRequested.connect(lambda pos,c=card,sid=row['id']:self.manga_menu(c,pos,sid,collection_id))
        self._manga_cover_refs[row['id']]=[ref for ref in self._manga_cover_refs.get(row['id'],[]) if ref() is not None and isValid(ref())]+[weakref.ref(card)]
        return card
    def _continue_manga(self,sid):
        item=self.manga_store.continue_item(sid)
        if item:self.open_manga_item(item['id'])
    def _request_visible_manga_covers(self):
        if not hasattr(self,'stack'):return
        page=self.stack.currentWidget()
        if page is None:return
        visible_ids=set();requested=0
        for card in page.findChildren(MangaCard):
            if not card.isVisible():continue
            scroll=card.parentWidget()
            while scroll and not isinstance(scroll,QScrollArea):scroll=scroll.parentWidget()
            if scroll:
                viewport=scroll.viewport();position=card.rect().translated(card.mapTo(viewport,card.rect().topLeft()))
                if not viewport.rect().intersects(position):
                    if not viewport.rect().adjusted(0,-viewport.height(),0,viewport.height()).intersects(position):self._release_manga_card_art(card)
                    continue
            visible_ids.add(card.row['id'])
            if not card.cover_requested and requested<8:
                card.cover_requested=True;self._load_manga_cover(card.row,card.cover);requested+=1
    def _release_manga_card_art(self,card):
        if card.cover_requested:
            card.cover.clear();card.cover.setText('MANGA');card.cover_requested=False
    def _release_manga_page_art(self,page):
        if page is not None:
            for card in page.findChildren(MangaCard):self._release_manga_card_art(card)
    def _load_manga_cover(self,row,label):
        metadata=json.loads(row['metadata_json'] or '{}')
        # Local/manual art wins; generated thumbnails are the final art fallback.
        candidates=[row.get('manual_cover_path')]
        root=Path(row['root_path'])
        if root.name.casefold()==row['title'].casefold():
            candidates.extend(str(root/(name+ext)) for name in ('cover','folder','poster') for ext in ('.jpg','.jpeg','.png','.webp'))
        for path in candidates:
            if path and Path(path).is_file():
                pixmap=ui()._scaled_artwork(path,label.width(),label.height())
                if not pixmap.isNull():label.setPixmap(pixmap);return
        url=(metadata.get('coverImage') or {}).get('large') or (metadata.get('coverImage') or {}).get('extraLarge')
        if url and url not in self._manga_remote_cover_failures:
            cache=ui().APP_DIR/'cache'/'manga_covers'/f"anilist-{row['anilist_id']}.png"
            if cache.is_file():
                pixmap=ui()._scaled_artwork(str(cache),label.width(),label.height())
                if not pixmap.isNull():label.setPixmap(pixmap);return
            key=('remote',url);refs=self._manga_cover_refs.setdefault(key,[]);refs.append(weakref.ref(label))
            if len(refs)>1:return
            request=QNetworkRequest(QUrl(url));request.setTransferTimeout(15000);reply=self._network.get(request)
            def finish():
                if self._manga_closing:reply.deleteLater();return
                pix=QPixmap();pix.loadFromData(bytes(reply.readAll()));targets=self._manga_cover_refs.pop(key,[])
                if not pix.isNull():
                    pix=pix.scaled(270,330,Qt.KeepAspectRatio,Qt.SmoothTransformation);cache.parent.mkdir(parents=True,exist_ok=True);pix.save(str(cache),'PNG')
                    for ref in targets:
                        target=ref()
                        if target is not None and isValid(target):target.setPixmap(pix.scaled(target.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
                else:
                    self._manga_remote_cover_failures.add(url)
                    for ref in targets:
                        target=ref()
                        if target is not None and isValid(target):self._load_manga_cover(row,target)
                reply.deleteLater()
            reply.finished.connect(finish);return
        path=row.get('cover_path')
        if path and Path(path).is_file():
            pixmap=ui()._scaled_artwork(path,label.width(),label.height())
            if not pixmap.isNull():label.setPixmap(pixmap);return
        key=('local-target',row['id']);refs=self._manga_cover_refs.setdefault(key,[])
        refs[:]=[reference for reference in refs if reference() is not None and isValid(reference())]
        if not any(reference() is label for reference in refs):refs.append(weakref.ref(label))
        self._queue_local_cover(row)
    def _queue_local_cover(self,row):
        item=next((i for i in self.manga_store.items(row['id']) if i['present']),None)
        if item and item['id'] not in self._manga_cover_attempts:
            if self._ensure_manga_jobs().cover(item):self._manga_cover_attempts.add(item['id'])
    def _manga_cover_ready(self,iid,path,error):
        if self._manga_closing:return
        item=self.manga_store.item(iid)
        if not item:return
        if error:ui()._append_playback_log(f'MangaCoverError item={iid} exception={error}');return
        self.db.connection.execute('UPDATE manga_series SET cover_path=? WHERE id=?',(path,item['series_id']));self.db.connection.commit()
        for ref in self._manga_cover_refs.get(item['series_id'],[]):
            card=ref()
            if card is not None and isValid(card):
                card.row['cover_path']=path
                if card.isVisible() and card.cover_requested:self._load_manga_cover(card.row,card.cover)
        for ref in self._manga_cover_refs.pop(('local-target',item['series_id']),[]):
            target=ref()
            if target is not None and isValid(target):self._load_manga_cover(self.manga_store.series(item['series_id']),target)
        detail=getattr(self,'_manga_detail_cover',None)
        if detail and self.current_manga_id==item['series_id'] and isValid(detail):self._load_manga_cover(self.manga_store.series(item['series_id']),detail)
    def show_manga_detail(self,sid):
        row=self.manga_store.series(sid)
        if not row or not self._manga_allowed(row['scope']):self.show_home();return
        scope=row['scope'];self.current_manga_id=sid;self.current_view='restricted_manga_detail' if scope=='restricted' else 'manga_detail';self._set_active_nav('restricted' if scope=='restricted' else 'manga')
        page=QWidget();page.setProperty('mangaPage',True);outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18)
        if scope=='restricted':self._restricted_nav(outer)
        back=QPushButton('← Back');back.clicked.connect(self.navigate_back);outer.addWidget(back,0,Qt.AlignLeft)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
        from .polish_ui import DetailBackdrop
        hero=DetailBackdrop();hero.setMinimumHeight(340);top=QHBoxLayout(hero);top.setContentsMargins(20,20,20,20);cover=QLabel('MANGA');cover.setFixedSize(210,290);cover.setAlignment(Qt.AlignCenter);top.addWidget(cover,0,Qt.AlignTop);self._manga_detail_cover=cover
        info=QVBoxLayout();title=QLabel(row.get('display_title',row['title']));title.setWordWrap(True);title.setObjectName('title');info.addWidget(title)
        summary=QLabel(f"{row['completed_count'] or 0} / {row['item_count']} local items finished · {round(row['progress'] or 0)}%");info.addWidget(summary)
        metadata=json.loads(row['metadata_json'] or '{}');description=metadata.get('description')
        if metadata.get('bannerImage'):self._load_remote_artwork(metadata['bannerImage'],hero.banner,1200,450)
        if row.get('display_title',row['title'])!=row['title']:title.setToolTip('Source title: '+row['title'])
        if row['last_read_label']:info.addWidget(QLabel('Last read: '+row['last_read_label']+' · '+(row['last_read'] or '')))
        memberships=[c for c in self.db.collections('Name',scope) if c['id'] in self.organization(scope).memberships(self.organization(scope).resolve(f'manga:{sid}'))]
        if memberships:
            chips=QHBoxLayout()
            for collection in memberships[:3]:
                chip=QPushButton(collection['name']);chip.clicked.connect(lambda checked=False,cid=collection['id']:self.show_collection_detail(cid,scope));chips.addWidget(chip)
            if len(memberships)>3:
                more=QComboBox();more.addItem('More Collections…',None)
                for collection in memberships[3:]:more.addItem(collection['name'],collection['id'])
                more.activated.connect(lambda index:self.show_collection_detail(more.itemData(index),scope) if more.itemData(index) else None);chips.addWidget(more)
            chips.addStretch();info.addLayout(chips)
        if description:label=QLabel(description);label.setWordWrap(True);info.addWidget(label)
        fields=[]
        for key,label in [('format','Format'),('status','AniList status'),('chapters','Published chapters'),('volumes','Published volumes')]:
            if metadata.get(key) is not None:fields.append(f'{label}: {metadata[key]}')
        if (metadata.get('title') if isinstance(metadata.get('title'),dict) else {}).get('native'):fields.append('Japanese title: '+metadata['title']['native'])
        if metadata.get('genres'):fields.append('Genres: '+', '.join(metadata['genres']))
        if metadata.get('tags'):fields.append('Tags: '+', '.join(t['name'] for t in metadata['tags'] if isinstance(t,dict) and t.get('name')))
        if fields:label=QLabel('\n'.join(fields));label.setWordWrap(True);label.setObjectName('muted');info.addWidget(label)
        actions=QHBoxLayout();item=self.manga_store.continue_item(sid)
        if item:
            play=QPushButton('Continue Reading' if item['current_page'] else 'Read');play.setObjectName('primary');play.clicked.connect(lambda:self.open_manga_item(item['id']));actions.addWidget(play)
        for label,action in [('♥ Favorite' if row['favorite'] else '♡ Favorite',lambda:self._manga_favorite(sid)),('Open Folder',lambda:self.open_folder(row['root_path']))]:
            button=QPushButton(label);button.clicked.connect(action);actions.addWidget(button)
        actions.addWidget(self._detail_collections_button(scope,manga_id=sid));info.addLayout(actions);info.addWidget(self._direct_status_controls(scope,manga_id=sid));match=QPushButton('Change AniList Match' if row['anilist_id'] else 'Find AniList Manga Match');match.clicked.connect(lambda:self.match_manga(sid));info.addWidget(match,0,Qt.AlignLeft)
        if row['anilist_id']:info.addWidget(QLabel(f"AniList Manga ID: {row['anilist_id']} · metadata only; progress sync deferred"))
        top.addLayout(info,1);layout.addWidget(hero)
        heading=QLabel('Local Volumes / Chapters');heading.setObjectName('section');layout.addWidget(heading)
        listing=ContainedListWidget();listing.setMinimumHeight(190);listing.setObjectName("mangaItems")
        for item in self.manga_store.items(sid):
            progress='Finished' if item['completed'] else f"Page {item['current_page']} / {item['total_pages']} · {round(item['percent_complete'] or 0)}%" if item['current_page'] else 'Not started'
            entry=QListWidgetItem(('✓  ' if item['completed'] else '')+clean_manga_display_title(item['display_name'])+' · '+item['source_type'].upper()+' · '+progress+(' · Missing' if not item['present'] else ''))
            entry.setData(Qt.UserRole,item['id']);entry.setToolTip(item['path']);listing.addItem(entry)
        listing.itemActivated.connect(lambda selected:self.open_manga_item(selected.data(Qt.UserRole)))
        listing.setContextMenuPolicy(Qt.CustomContextMenu)
        def completion_menu(pos):
            selected=listing.itemAt(pos)
            if selected is None:return
            iid=selected.data(Qt.UserRole);state=next((i for i in self.manga_store.items(sid) if i['id']==iid),None)
            if state is None:return
            menu=QMenu(listing);menu.addAction('Mark Unfinished' if state['completed'] else 'Mark Finished').triggered.connect(lambda:self._set_manga_item_finished(sid,iid,not bool(state['completed']),listing,summary))
            menu.exec(listing.viewport().mapToGlobal(pos))
        listing.customContextMenuRequested.connect(completion_menu)
        layout.addWidget(listing)
        item_actions=QHBoxLayout();open_selected=QPushButton('Open / Continue Selected');open_selected.setObjectName('primary')
        open_selected.clicked.connect(lambda:self.open_manga_item(listing.currentItem().data(Qt.UserRole)) if listing.currentItem() else None);item_actions.addWidget(open_selected)
        finish_selected=QPushButton('Toggle Finished');finish_selected.setToolTip('Mark the selected item Finished / Unfinished; resume and bookmarks are preserved')
        def toggle_selected():
            selected=listing.currentItem();state=next((i for i in self.manga_store.items(sid) if selected and i['id']==selected.data(Qt.UserRole)),None)
            if state:self._set_manga_item_finished(sid,state['id'],not bool(state['completed']),listing,summary)
        finish_selected.clicked.connect(toggle_selected);item_actions.addWidget(finish_selected)
        folder_selected=QPushButton('Open Item Folder')
        def selected_folder():
            selected=listing.currentItem();item=self.manga_store.item(selected.data(Qt.UserRole)) if selected else None
            if item:self.open_folder(item['path'] if Path(item['path']).is_dir() else str(Path(item['path']).parent))
        folder_selected.clicked.connect(selected_folder);item_actions.addWidget(folder_selected);item_actions.addStretch();layout.addLayout(item_actions)
        if listing.count():listing.setCurrentRow(0)
        layout.addWidget(self._related_panel({**metadata,'id':row['anilist_id'],'type':'MANGA'},scope));layout.addStretch();self.replace(page);self._load_manga_cover(row,cover)
    def _set_manga_item_finished(self,sid,iid,finished,listing,summary):
        self.manga_store.set_item_finished(iid,finished)
        state=next(item for item in self.manga_store.items(sid) if item['id']==iid)
        for index in range(listing.count()):
            entry=listing.item(index)
            if entry.data(Qt.UserRole)==iid:
                progress='Finished' if state['completed'] else f"Page {state['current_page']} / {state['total_pages']}" if state['current_page'] else 'Not started'
                entry.setText(('✓  ' if state['completed'] else '')+clean_manga_display_title(state['display_name'])+' · '+state['source_type'].upper()+' · '+progress+(' · Missing' if not state['present'] else ''))
        row=self.manga_store.series(sid);summary.setText(f"{row['completed_count'] or 0} / {row['item_count']} local items finished · {round(row['progress'] or 0)}%")
        ui()._append_playback_log(f'MangaItemCompletion item_id={iid} completed={finished} resume_preserved=true')

    def open_manga_item(self,iid):
        item=self.manga_store.item(iid);row=self.manga_store.series(item['series_id']) if item else None
        if not item or not row or not self._manga_allowed(row['scope']):return
        if not item['present'] or not Path(item['path']).exists():ui().AniVaultDialog.alert(self,'Manga Unavailable','This item is missing. Its reading history and bookmarks remain preserved.');return
        self.open_local_manga(item['path'],row['scope'],item['reader_identity']);self.current_manga_item_id=iid;self._current_route=('manga_item',iid)
    def _manga_status(self,sid,value):
        row=self.manga_store.series(sid);key=self.manga_store.set_status(sid,value);self.manual_status_changed.emit(row['scope'],key,value)
        if row['anilist_id']:self.manual_status_changed.emit(row['scope'],f"anilist:{row['anilist_id']}",value)
        if self.current_view in {'manga_detail','restricted_manga_detail'}:self.show_manga_detail(sid)
    def _manga_favorite(self,sid):
        row=self.manga_store.series(sid);self.manga_store.set_favorite(sid,not row['favorite'])
        if self.current_view in {'manga_detail','restricted_manga_detail'}:self.show_manga_detail(sid)
        elif self.current_view in {'favorites','restricted_favorites'}:self.show_favorites(row['scope'])
        else:
            for ref in self._manga_cover_refs.get(sid,[]):
                card=ref()
                if card is not None and isValid(card) and hasattr(card,'set_favorite'):card.set_favorite(not row['favorite'])
    def _manga_new_collection(self,sid):
        row=self.manga_store.series(sid);name,ok=ui().AniVaultDialog.prompt(self,'New Collection','Collection name:')
        if not ok:return
        try:cid=self.db.create_collection(name,scope=row['scope']);self.manga_store.add_collection(sid,cid)
        except ValueError as exc:ui().AniVaultDialog.alert(self,'Collection',str(exc))
    def manga_menu(self,widget,pos,sid,collection_id=None):
        row=self.manga_store.series(sid)
        if not row or not self._manga_allowed(row['scope']):return
        menu=QMenu(self);item=self.manga_store.continue_item(sid)
        if item:menu.addAction('Continue Reading').triggered.connect(lambda:self.open_manga_item(item['id']))
        menu.addAction('Open Details').triggered.connect(lambda:self.show_manga_detail(sid))
        menu.addAction('Remove Favorite' if row['favorite'] else 'Add Favorite').triggered.connect(lambda:self._manga_favorite(sid))
        if row['scope']=='restricted' and row['anilist_id'] and self.db.is_saved(row['anilist_id'],row['scope']):
            menu.addAction('Remove from Saved').triggered.connect(lambda:self.set_saved({**json.loads(row['metadata_json'] or '{}'),'id':row['anilist_id']},False,row['scope']))
        statuses=menu.addMenu('Set Status')
        for label,value in [('Reading','Watching'),('Completed','Completed'),('Planning','Planning'),('Paused','Paused'),('Dropped','Dropped'),('No Status',None)]:
            action=statuses.addAction(('✓  ' if row['manual_status']==value else '')+label);action.triggered.connect(lambda _,v=value:self._manga_status(sid,v))
        collections=menu.addMenu('Add to Collection');store=self.organization(row['scope']);entity=store.resolve(f'manga:{sid}');members=store.memberships(entity) if entity else set()
        for collection in self.db.collections('Name',row['scope']):
            action=collections.addAction(('✓  ' if collection['id'] in members else '')+collection['name']);action.setEnabled(collection['id'] not in members);action.triggered.connect(lambda _,cid=collection['id']:self.manga_store.add_collection(sid,cid))
        collections.addAction('+ New Collection').triggered.connect(lambda:self._manga_new_collection(sid))
        if collection_id:menu.addAction('Remove from Collection').triggered.connect(lambda:self._remove_remote_from_collection(collection_id,f'manga:{sid}',row['scope']))
        menu.addAction('Select Local Cover…').triggered.connect(lambda:self.choose_manga_cover(sid));menu.addAction('Find / Change AniList Match').triggered.connect(lambda:self.match_manga(sid))
        if row['anilist_id']:menu.addAction('Clear AniList Match').triggered.connect(lambda:(self.manga_store.unmatch(sid),self.show_manga_detail(sid)))
        if row['scope']=='restricted':menu.addAction('Move to Normal Manga').triggered.connect(lambda:self.change_manga_scope(sid,'normal'))
        elif self.db.setting('restricted_unlocked','0')=='1':menu.addAction('Move to Restricted Manga').triggered.connect(lambda:self.change_manga_scope(sid,'restricted'))
        menu.addAction('Open Folder').triggered.connect(lambda:self.open_folder(row['root_path']));menu.exec(widget.mapToGlobal(pos))
    def change_manga_scope(self,sid,scope):
        if not self._manga_allowed('restricted'):return
        if not ui().AniVaultDialog.confirm(self,'Manga Privacy','Move this manga to '+('Restricted' if scope=='restricted' else 'normal')+' Manga? Progress and bookmarks remain intact. Collection memberships move to matching scoped collections.','Move'):return
        try:self.manga_store.set_scope(sid,scope)
        except ValueError as exc:ui().AniVaultDialog.alert(self,'Manga Privacy',str(exc));return
        self._manga_scope_dirty=True;self.show_manga_library(scope)
    def choose_manga_cover(self,sid):
        path=QFileDialog.getOpenFileName(self,'Choose Local Manga Cover',filter='Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)')[0]
        if path:
            self.db.connection.execute('UPDATE manga_series SET manual_cover_path=? WHERE id=?',(path,sid));self.db.connection.commit();self.show_manga_detail(sid)
    def match_manga(self,sid):
        row=self.manga_store.series(sid)
        if not row or not self._manga_allowed(row['scope']):return
        dialog=ui().AniVaultDialog(self,'Match AniList Manga','Search suggestions, or enter an exact AniList manga ID.',None,False,(('Cancel',None),));dialog.resize(680,480)
        search=QLineEdit(row['title']);results=QListWidget();status=QLabel();search_button=QPushButton('Search AniList');save=QPushButton('Use Selected Match');save.setObjectName('primary')
        panel=dialog.findChild(QFrame,'vaultDialogPanel').layout()
        for index,widget in enumerate([search,search_button,status,results,save],2):panel.insertWidget(index,widget)
        state={'generation':0,'matches':[],'closed':False}
        def submit():
            if not search_button.isEnabled():return
            if time.time()<getattr(self,'_discover_cooldown_until',0):status.setText('AniList is cooling down after rate limiting. Please retry shortly.');return
            if not search.text().strip():status.setText('Enter a manga title or AniList ID.');return
            state['generation']+=1;generation=state['generation'];query=search.text().strip();results.clear();state['matches']=[];status.setText('Loading manga suggestions…');search_button.setEnabled(False)
            def operation():
                if state['closed']:return []
                if query.isdigit():
                    value=graphql('''query($id:Int){Media(id:$id,type:MANGA){id type title{romaji english native} description(asHtml:false) format status chapters volumes isAdult genres tags{name rank} coverImage{large extraLarge} relations{edges{relationType node{id type title{romaji english}}}}}}''',{'id':int(query)}).get('Media')
                    return [value] if value else []
                return fetch_discover_page(search=query,media_type='MANGA',is_adult=row['scope']=='restricted',sort='SEARCH_MATCH')['items']
            def done(items):
                if state['closed'] or not isValid(dialog) or generation!=state['generation']:return
                state['matches']=[i for i in items if i and i.get('type')=='MANGA'];search_button.setEnabled(True);status.setText(f"{len(state['matches'])} manga suggestions")
                for item in state['matches']:
                    title=(item.get('title') or {}).get('english') or (item.get('title') or {}).get('romaji') or str(item['id'])
                    results.addItem(f"{title} · {item.get('format') or 'Manga'} · ID {item['id']}"+(' · Restricted' if item.get('isAdult') is True else ''))
            def failed(exc):
                if isinstance(exc,AniListHTTPError) and exc.status_code==429:
                    self._discover_cooldown_until=max(self._discover_cooldown_until,time.time()+max(1,int(exc.retry_after or 15)))
                if not state['closed'] and isValid(dialog):status.setText('AniList is temporarily unavailable. Local metadata and progress are unchanged.');search_button.setEnabled(True)
                ui()._append_playback_log(f'MangaMatchError series={sid} exception={type(exc).__name__}: {exc}')
            self._submit_discover_job(f'manga_match:{sid}:{id(dialog)}:{generation}',operation,done,failed)
        def choose():
            index=results.currentRow()
            if index<0:return
            item=state['matches'][index]
            if item.get('isAdult') is True and self.db.setting('restricted_unlocked','0')!='1':status.setText('Unlock Restricted Archive before matching this explicitly adult title.');return
            if item.get('isAdult') is True and row['scope']=='normal' and not ui().AniVaultDialog.confirm(dialog,'Restricted Manga','AniList explicitly marks this manga adult. Move it to Restricted Manga?','Match and Move'):return
            self.manga_store.match(sid,item);self._manga_scope_dirty=True;ui()._append_playback_log(f"MangaMatch series={sid} anilist_id={item['id']}");dialog.accept();self.show_manga_detail(sid)
        search_button.clicked.connect(submit);search.returnPressed.connect(submit);save.clicked.connect(choose);submit();dialog.exec();state['closed']=True
