"""Small native presentation helpers; no media writes or new worker threads."""
import time, weakref
from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, Signal, QRect, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient,QIcon
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QMenu, QListWidget, QListWidgetItem, QLayout,QProgressBar)
from shiboken6 import isValid
from .organization import display_title


class CompactFilterLayout(QLayout):
    """One compact row when it fits; wraps without forcing a wider window."""
    def __init__(self):
        super().__init__();self.items=[];self.setContentsMargins(0,0,0,0);self.setSpacing(6)
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,index):return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index):return self.items.pop(index) if 0<=index<len(self.items) else None
    def expandingDirections(self):return Qt.Orientations()
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),False)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):return QSize(160,32)
    def setGeometry(self,rect):super().setGeometry(rect);self.arrange(rect,True)
    def arrange(self,rect,apply):
        x=rect.x();y=rect.y();height=0
        for item in self.items:
            if item.isEmpty():continue
            size=item.sizeHint();width=min(size.width(),item.widget().maximumWidth(),max(1,rect.width()))
            if x>rect.x() and x+width>rect.right()+1:x=rect.x();y+=height+self.spacing();height=0
            if apply:item.setGeometry(QRect(x,y,width,32))
            x+=width+self.spacing();height=max(height,32)
        return y-rect.y()+height


from .hub_ui import ArtworkHero

class DetailBackdrop(ArtworkHero):
    def __init__(self):super().__init__()


class CoverListCard(QFrame):
    clicked = Signal()
    def __init__(self, title, subtitle, covers=(), color='#ae97ce', description='',width=270,height=204,art_height=104):
        super().__init__(); self.setObjectName('card'); self.setFixedSize(width,height)
        self.setCursor(Qt.PointingHandCursor); self.setFocusPolicy(Qt.StrongFocus)
        standard=width==228 and height==460;pad=9 if standard else 12
        layout=QVBoxLayout(self); layout.setContentsMargins(pad,pad,pad,pad); layout.setSpacing(4 if standard else 6);layout.setAlignment(Qt.AlignTop)
        art_width=width-2*pad;art=QLabel();self.art=art;self._mosaic_images={}; art.setObjectName("coverMosaic");art.setFixedSize(art_width,art_height); art.setAttribute(Qt.WA_TransparentForMouseEvents)
        pix=QPixmap(art_width,art_height); pix.fill(QColor('#17202b')); painter=QPainter(pix)
        from .app import _scaled_artwork
        paths=[path for path in covers if path][:4]
        width=art_width//max(1,len(paths))
        for i,path in enumerate(paths):
            image=_scaled_artwork(path,width,art_height)
            if not image.isNull(): painter.drawPixmap(i*width,0,image,0,0,width,art_height)
        if not paths:
            painter.setPen(QColor(color));font=painter.font();font.setPointSize(28);painter.setFont(font);painter.drawText(pix.rect(),Qt.AlignCenter,'+' if 'New Collection' in title else title[:1])
        painter.end(); art.setPixmap(pix); layout.addWidget(art)
        placeholder=QPixmap(art_width,art_height);placeholder.fill(QColor('#17202b'));painter=QPainter(placeholder);painter.setPen(QColor(color));font=painter.font();font.setPointSize(28);painter.setFont(font);painter.drawText(placeholder.rect(),Qt.AlignCenter,'+' if 'New Collection' in title else title[:1]);painter.end();self._mosaic_placeholder=placeholder
        from .app import TwoLineLabel
        name=TwoLineLabel(title) if standard else QLabel(title);name.setObjectName('cardTitle');name.setStyleSheet('color:'+color);name.setWordWrap(True);name.setFixedHeight(42) if standard else name.setMaximumHeight(42)
        layout.addWidget(name); self.count_label=QLabel(subtitle);self.count_label.setObjectName('muted');self.count_label.setWordWrap(True);self.count_label.setFixedHeight(20) if standard else self.count_label.setMaximumHeight(38);layout.addWidget(self.count_label)
        if standard:
            from .media_cards import text_slot,footer_slot
            self.secondary=text_slot(layout,'mediaAvailability',30);self.secondary.setAlignment(Qt.AlignCenter)
            self.note=text_slot(layout,'mediaNote',32,True);self.note.setStyleSheet('color:#a89ab8;font-size:11px')
            layout.addSpacing(28);self.progress=QProgressBar();self.progress.setFixedHeight(6);self.progress.setTextVisible(False);layout.addWidget(self.progress)
        if description:self.setToolTip(description)
        from .media_cards import card_input
        card_input(self)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.rect().contains(event.position().toPoint()):self.clicked.emit()
        super().mouseReleaseEvent(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):self.clicked.emit();event.accept();return
        super().keyPressEvent(event)


class SearchSuggestions(QListWidget):
    """Non-modal child dropdown with scoped cache and stale-response protection."""
    def __init__(self,window,editor,scope):
        super().__init__(window);self.window=window;self.editor=editor;self.scope=scope
        self.setObjectName('searchSuggestions');self.setStyleSheet('QListWidget{background:#202332;border:1px solid #72546a;border-radius:8px} QListWidget::item{padding:4px 8px} QListWidget::item:selected{background:#594051}')
        self.setFocusPolicy(Qt.NoFocus);self.setIconSize(QSize(40,56));self.hide();self.generation=0;self.results=[];self._cover_labels=[]
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(350);self.timer.timeout.connect(self.remote)
        editor.installEventFilter(self);editor.textEdited.connect(self.changed);editor.destroyed.connect(self.deleteLater)
        self.itemClicked.connect(self.open_item)
        self.verticalScrollBar().valueChanged.connect(lambda _:self.load_visible_covers(self.generation))
        window._search_suggestions.append(weakref.ref(self))
    def dismiss(self):self.generation+=1;self.timer.stop();self.hide()
    def changed(self,text):
        self.generation+=1;self.timer.stop();self.results=[]
        query=text.strip().casefold()
        if len(query)<2:self.hide();return
        store=self.window.organization(self.scope)
        entities=[e for e in store.entities.values() if e.media_type in {'ANIME','MANGA'} and all(t in e.title.casefold() for t in query.split())]
        entities.sort(key=lambda e:(not bool(e.local),e.title.casefold(),e.key))
        self.window._load_library_relations();self._grouped_anilist_ids=set();grouped_keys=set();summaries=[]
        for group in self.window._library_franchises(self.scope):
            if all(term in group.name.casefold() for term in query.split()):
                representative=store.resolve('local:'+str(group.rows[0]['id']))
                item={**(representative.item if representative else {}),'type':'ANIME','title':{'english':group.name},'_franchise_ids':group.local_ids,'isAdult':self.scope=='restricted'}
                summaries.append((item,None));grouped_keys.update('local:'+str(row['id']) for row in group.rows);self._grouped_anilist_ids.update(row['anilist_id'] for row in group.rows)
        self.results=[*summaries,*[(dict(e.item),e) for e in entities if not e.aliases.intersection(grouped_keys)]][:8];self.render();self.timer.start()
    def render(self):
        if not isValid(self.editor) or not self.editor.isVisible() or not self.window._organization_allowed(self.scope):self.hide();return
        for label in self._cover_labels:label.deleteLater()
        self._cover_labels=[];self.clear()
        for item,entity in self.results[:10]:
            kind=item.get('type') or 'ANIME';label=(str(len(item['_franchise_ids']))+' local anime titles · In Vault') if item.get('_franchise_ids') else kind.title()+' · '+('In Vault' if entity and entity.local else 'AniList-only')
            if entity and entity.status:label+=' · '+('Reading' if kind=='MANGA' and entity.status=='Watching' else entity.status)
            row=QListWidgetItem((entity.title if entity else display_title(item))+'\n'+label);row.setData(Qt.UserRole,(item,entity));row.setSizeHint(QSize(250,66));placeholder=QPixmap(40,56);placeholder.fill(QColor('#17202b'));row.setIcon(QIcon(placeholder));self.addItem(row)
        if not self.count():self.hide();return
        point=self.editor.mapTo(self.window,QPoint(0,self.editor.height()+3))
        self.setGeometry(point.x(),point.y(),min(660,self.editor.width()),min(370,self.count()*66+8));self.raise_();self.show()
        generation=self.generation
        QTimer.singleShot(0,lambda:self.load_visible_covers(generation) if isValid(self) else None)
    def load_visible_covers(self,generation):
        if generation!=self.generation or not self.isVisible() or not self.window._organization_allowed(self.scope):return
        popup_ref=weakref.ref(self)
        # Each closure must own its row, not the loop's final row.
        def target_for(entry):
            class Target(QLabel):
                def setPixmap(label,pixmap):
                    popup=popup_ref()
                    if popup is not None and isValid(popup) and popup.generation==generation and isValid(entry) and entry.listWidget() is popup:
                        entry.setIcon(QIcon(pixmap));super().setPixmap(pixmap)
            target=Target(self);target.setFixedSize(40,56);target.hide();self._cover_labels.append(target);return target
        from .app import _scaled_artwork
        for index in range(self.count()):
            row=self.item(index)
            if not self.visualItemRect(row).intersects(self.viewport().rect()) or row.data(Qt.UserRole+1):continue
            row.setData(Qt.UserRole+1,True);item,entity=row.data(Qt.UserRole);target=target_for(row)
            paths=self.window._entity_cover_paths([entity]) if entity else []
            if item.get('_franchise_ids'):
                representative=self.window.organization(self.scope).resolve('local:'+str(item['_franchise_ids'][0]));paths=self.window._entity_cover_paths([representative]) if representative else []
            if paths:
                pixmap=_scaled_artwork(paths[0],40,56)
                if not pixmap.isNull():target.setPixmap(pixmap);continue
            url=(item.get('coverImage') or {}).get('large') or (item.get('coverImage') or {}).get('extraLarge')
            if url:self.window._load_remote_artwork(url,target,40,56)
            elif entity and entity.local and entity.media_type=='MANGA':self.window._load_manga_cover(entity.local,target)
    def remote(self):
        query=self.editor.text().strip();generation=self.generation;window=self.window;key=(self.scope,query.casefold())
        cache=getattr(window,'_suggestion_cache',{});window._suggestion_cache=cache
        reference=weakref.ref(self)
        def loaded(items):
            popup=reference()
            if popup is None or not isValid(popup) or generation!=popup.generation or not window._organization_allowed(popup.scope):return
            seen={(item.get('type'),item.get('id')) for item,_ in popup.results}
            for item in items:
                identity=(item.get('type'),item.get('id'))
                if item.get('type') not in {'ANIME','MANGA'} or not item.get('id') or (item.get('isAdult') is True)!=(popup.scope=='restricted') or identity in seen or (item.get('type')=='ANIME' and item.get('id') in getattr(popup,'_grouped_anilist_ids',set())):continue
                seen.add(identity);entity=window.organization(popup.scope).resolve('anilist:'+str(item['id']),item);popup.results.append((item,entity))
            popup.render()
        if key in cache and time.monotonic()-cache[key][0]<300:loaded(cache[key][1]);return
        if time.time()<window._discover_cooldown_until:return
        inflight=getattr(window,'_suggestion_inflight',{});window._suggestion_inflight=inflight
        if key in inflight:inflight[key].append(loaded);return
        inflight[key]=[loaded]
        def success(items):
            if len(cache)>=64:cache.pop(next(iter(cache)))
            cache[key]=(time.monotonic(),items)
            for callback in inflight.pop(key,[]):callback(items)
        def failure(exc):
            from .anilist_integration import AniListHTTPError
            if isinstance(exc,AniListHTTPError) and exc.status_code==429:window._discover_cooldown_until=max(window._discover_cooldown_until,time.time()+int(exc.retry_after or 15))
            inflight.pop(key,None)
        window._submit_discover_job('suggestion:'+str(key),lambda adult=self.scope=='restricted':fetch_suggestions(query,adult),success,failure)
    def open_item(self,row):
        item,entity=row.data(Qt.UserRole);self.dismiss()
        if not self.window._organization_allowed(self.scope):return
        if item.get('_franchise_ids'):self.window.show_library_franchise(item['_franchise_ids'],self.scope)
        elif entity and entity.local:
            self.window.show_manga_detail(entity.local['id']) if entity.media_type=='MANGA' else self.window.show_detail(entity.local['id'])
        else:self.window.show_remote_anilist(item,'Restricted' if self.scope=='restricted' else 'Discover')
    def eventFilter(self,obj,event):
        if obj is not self.editor:return super().eventFilter(obj,event)
        if event.type()==QEvent.KeyPress:
            key=event.key()
            if key==Qt.Key_Escape:self.dismiss();return True
            if key in (Qt.Key_Return,Qt.Key_Enter):self.dismiss();return False
            if self.isVisible() and key in (Qt.Key_Down,Qt.Key_Up):
                self.setCurrentRow((self.currentRow()+(1 if key==Qt.Key_Down else -1))%self.count());return True
            if self.isVisible() and key==Qt.Key_Tab and self.currentItem():self.open_item(self.currentItem());return True
        if event.type() in (QEvent.Hide,QEvent.Move,QEvent.Resize):self.dismiss()
        if event.type()==QEvent.FocusOut:QTimer.singleShot(150,lambda:self.hide() if isValid(self) else None)
        return super().eventFilter(obj,event)


def fetch_suggestions(query,adult):
    from .anilist_integration import graphql
    fields='id type isAdult title{english romaji native} format status seasonYear coverImage{large} description genres'
    data=graphql('query($q:String,$adult:Boolean){anime:Page(page:1,perPage:6){media(search:$q,type:ANIME,isAdult:$adult){'+fields+'}} manga:Page(page:1,perPage:4){media(search:$q,type:MANGA,isAdult:$adult){'+fields+'}}}',{'q':query,'adult':adult})
    return [item for key in ('anime','manga') for item in (data.get(key) or {}).get('media') or []]


class PolishMixin:
    def _direct_status_controls(self,scope,anime_id=None,item=None,manga_id=None):
        from .app import STATUS_COLORS
        host=QWidget();host.setObjectName('directStatusControls');host.setStyleSheet('#directStatusControls{background:transparent}');layout=QHBoxLayout(host);layout.setContentsMargins(0,4,0,4);layout.setSpacing(5)
        if manga_id is not None:entity=self.organization(scope).resolve('manga:'+str(manga_id))
        elif anime_id is not None:entity=self.organization(scope).resolve('local:'+str(anime_id))
        else:entity=self.organization(scope).resolve('anilist:'+str(item['id']),item)
        aliases=entity.aliases if entity else set();kind=entity.media_type if entity else (item or {}).get('type','ANIME')
        def current():
            store=self.organization(scope);value=next((store.resolve(key,item) for key in aliases if store.resolve(key,item)),None)
            return value.status if value else None
        buttons={}
        def refresh():
            value=current()
            for status,button in buttons.items():button.setChecked(status==value)
        def change(value):
            if manga_id is not None:
                row=self.manga_store.series(manga_id);key=self.manga_store.set_status(manga_id,value);self.manual_status_changed.emit(scope,key,value)
                if row['anilist_id']:self.manual_status_changed.emit(scope,'anilist:'+str(row['anilist_id']),value)
            else:self._set_status(value,scope,anime_id,item)
            refresh()
        for status,color in STATUS_COLORS.items():
            button=QPushButton('Reading' if status=='Watching' and kind=='MANGA' else status);button.setCheckable(True);button.setObjectName('statusAction');button.setMinimumHeight(30)
            button.setStyleSheet('QPushButton{padding:5px 8px;border:1px solid '+color+';color:'+color+';border-radius:6px} QPushButton:checked{background:'+color+';color:#151820} QPushButton:hover{background:#353448}')
            button.clicked.connect(lambda _,value=status:change(value));buttons[status]=button;layout.addWidget(button)
        clear=QPushButton('Clear');clear.setToolTip('Clear manual status');clear.clicked.connect(lambda:change(None));layout.addWidget(clear);layout.addStretch();refresh()
        reference=weakref.ref(host)
        def updated(changed_scope,key,value):
            if reference() is not None and isValid(reference()) and changed_scope==scope and key in aliases:refresh()
        self.manual_status_changed.connect(updated)
        host.destroyed.connect(lambda:self.manual_status_changed.disconnect(updated) if isValid(self) else None)
        return host

    def _detail_collections_button(self,scope,anime_id=None,item=None,manga_id=None):
        button=QPushButton('+ Collection');button.setObjectName('detailCollectionAction');button.setToolTip('Add to a collection');button.setStyleSheet('padding:5px 9px')
        def menu():
            if not self._organization_allowed(scope):return
            key='manga:'+str(manga_id) if manga_id is not None else 'local:'+str(anime_id) if anime_id is not None else 'anilist:'+str(item['id'])
            entity=self.organization(scope).resolve(key,item)
            if entity is None:return
            memberships=self.organization(scope).memberships(entity);popup=QMenu(button)
            for collection in self.db.collections('Name',scope):
                action=popup.addAction(('✓  ' if collection['id'] in memberships else '')+collection['name']);action.setEnabled(collection['id'] not in memberships)
                action.triggered.connect(lambda _,cid=collection['id']:self._add_detail_membership(cid,entity))
            popup.addSeparator()
            def create():
                cid=self.create_collection(scope=scope)
                if cid:self._add_detail_membership(cid,entity)
            popup.addAction('+ New Collection').triggered.connect(create);popup.exec(button.mapToGlobal(button.rect().bottomLeft()))
        button.clicked.connect(menu);return button

    def _entity_cover_paths(self,entities):
        from .app import APP_DIR
        from .external_bookmarks import cached_artwork_path
        from .organization import metadata
        from pathlib import Path
        paths=[]
        for entity in entities[:4]:
            local=entity.local or {};item={**metadata(local.get('metadata_json')),**entity.item}
            path=local.get('manual_cover_path') or local.get('cover_path') or item.get('cover_path')
            if not path and entity.media_type=='MANGA' and local.get('anilist_id'):
                candidate=APP_DIR/'cache'/'manga_covers'/('anilist-'+str(local['anilist_id'])+'.png');path=str(candidate) if candidate.exists() else None
            if not path and entity.media_type=='EXTERNAL':path=cached_artwork_path(entity.item)
            if path and Path(path).is_file():paths.append(path)
        return paths

    def _populate_cover_mosaic(self,card,entities):
        """Reuse existing artwork services for up to four covers; never block a page."""
        if card is None:return
        from .app import _scaled_artwork
        from .organization import metadata
        card._mosaic_generation=getattr(card,'_mosaic_generation',0)+1;generation=card._mosaic_generation
        for target in getattr(card,'_mosaic_targets',[]):target.deleteLater()
        card._mosaic_targets=[];card._mosaic_images={};reference=weakref.ref(card)
        candidates=[]
        for entity in entities:
            paths=self._entity_cover_paths([entity]);local=entity.local or {};item={**metadata(local.get('metadata_json')),**entity.item}
            url=(item.get('coverImage') or {}).get('extraLarge') or (item.get('coverImage') or {}).get('large')
            if paths or url or (entity.media_type=='MANGA' and entity.local):candidates.append((entity,paths,url))
            if len(candidates)==4:break
        count=len(candidates)
        if not count:card.art.setPixmap(card._mosaic_placeholder)
        def paint(index,pix):
            current=reference()
            if current is None or not isValid(current) or generation!=current._mosaic_generation or pix.isNull():return
            current._mosaic_images[index]=pix
            width=current.art.width();height=current.art.height();canvas=QPixmap(width,height);canvas.fill(QColor('#17202b'));painter=QPainter(canvas)
            for slot,image in current._mosaic_images.items():
                left=slot*width//max(1,count);right=(slot+1)*width//max(1,count);part=image.scaled(right-left,height,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
                painter.drawPixmap(left,0,part,(part.width()-(right-left))//2,(part.height()-height)//2,right-left,height)
            painter.end();current.art.setPixmap(canvas)
        for index,(entity,paths,url) in enumerate(candidates):
            width=max(1,card.art.width()//count);height=card.art.height()
            if paths:
                image=_scaled_artwork(paths[0],width,height)
                if not image.isNull():paint(index,image);continue
            def target_for(slot):
                class Target(QLabel):
                    def setPixmap(label,pix):paint(slot,pix)
                target=Target(card);target.setFixedSize(width,height);target.hide();card._mosaic_targets.append(target);return target
            target=target_for(index)
            if url:self._load_remote_artwork(url,target,width,height)
            elif entity.media_type=='MANGA' and entity.local:self._load_manga_cover(entity.local,target)

    def _add_detail_membership(self,cid,entity):
        if entity.local and entity.media_type=='MANGA':self.manga_store.add_collection(entity.local['id'],cid)
        elif entity.local:self.db.add_to_collection(cid,entity.local['id'])
        else:self.db.add_remote_to_collection(cid,entity.item)
