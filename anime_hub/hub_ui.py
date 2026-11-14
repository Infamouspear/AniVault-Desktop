"""V0.9 presentation shell. Uses existing identities, caches and playback routes."""
import json, weakref
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QObject, QTimer, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QTextDocument, QFontMetrics
from PySide6.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
 QScrollArea,QTabWidget,QProgressBar,QLineEdit,QComboBox,QSizePolicy,QLayout)
from shiboken6 import isValid
from .organization import display_title


def plain(value):
    document=QTextDocument();document.setHtml(value or '');return document.toPlainText()


class ArtworkHero(QFrame):
    """Full-bleed cover crop with explicit focal coordinates; never contains black margins."""
    def __init__(self,path=None,parent=None):
        super().__init__(parent);self.setObjectName('hubHero');self.focal=(.65,.35)
        self._pixmap=QPixmap(str(path)) if path and Path(path).exists() else QPixmap()
        self._scaled_size=None;self.setMinimumWidth(0)
        self.setStyleSheet('#hubHero{border:1px solid #303547;border-radius:12px} #hubHero QWidget{background:transparent} #hubHero QPushButton{background:rgba(25,30,46,210)} #hubHero QPushButton:hover{background:#493649} #hubHero QPushButton#primary{background:#ff477c}')
        owner=weakref.ref(self)
        class Banner(QLabel):
            def setPixmap(label,pix):
                host=owner()
                if host is not None and isValid(host):host._pixmap=pix;host._scaled_size=None;host.update()
        self.banner=Banner(self);self.banner.hide()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.SmoothPixmapTransform)
        branding=getattr(self,'branding_scope',None)
        if branding:
            background=QLinearGradient(0,0,self.width(),0);background.setColorAt(0,QColor('#161c2d' if branding=='normal' else '#1c1221'));background.setColorAt(1,QColor('#333049' if branding=='normal' else '#512139'));painter.fillRect(self.rect(),background)
        else:painter.fillRect(self.rect(),QColor('#192031'))
        if not self._pixmap.isNull():
            if branding:
                if self.width()>=760:
                    size=QSize(150,170) if branding=='normal' else QSize(280,300)
                    size.setHeight(min(size.height(),max(1,self.height()-16)));image=self._pixmap.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                    painter.drawPixmap(self.width()-image.width()-20,(self.height()-image.height())//2,image)
            elif getattr(self,'safe_banner',False):
                if self._scaled_size!=self.size():
                    self._scaled_size=self.size()
                    # Extend only the scenic left half behind text, never duplicate
                    # the mascot. Keep the complete figure in the foreground.
                    scene=self._pixmap.copy(0,0,int(self._pixmap.width()*.48),self._pixmap.height())
                    self._safe_backdrop=scene.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
                    self._safe_image=self._pixmap.scaledToHeight(self.height(),Qt.SmoothTransformation)
                    mask=QPainter(self._safe_image);mask.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                    fade=QLinearGradient(0,0,self._safe_image.width()*.3,0);fade.setColorAt(0,QColor(0,0,0,0));fade.setColorAt(1,QColor(0,0,0,255));mask.fillRect(self._safe_image.rect(),fade);mask.end()
                painter.drawPixmap(0,0,self._safe_backdrop)
                painter.drawPixmap(self.width()-self._safe_image.width(),0,self._safe_image)
            elif self._scaled_size!=self.size():
                self._scaled_size=self.size();self._scaled_banner=self._pixmap.scaled(self.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            image=self._scaled_banner if not branding and not getattr(self,'safe_banner',False) else QPixmap()
            x=round((image.width()-self.width())*self.focal[0]);y=round((image.height()-self.height())*self.focal[1])
            if not branding and not getattr(self,'safe_banner',False):painter.drawPixmap(0,0,image,x,y,self.width(),self.height())
        gradient=QLinearGradient(0,0,self.width(),0)
        gradient.setColorAt(0,QColor(9,12,22,232));gradient.setColorAt(.52,QColor(9,12,22,172));gradient.setColorAt(1,QColor(9,12,22,35));painter.fillRect(self.rect(),gradient)
        bottom=QLinearGradient(0,0,0,self.height());bottom.setColorAt(0,QColor(9,12,22,0));bottom.setColorAt(1,QColor("#090b10") if getattr(self,"library_overview",False) else QColor(9,12,22,100));painter.fillRect(self.rect(),bottom);painter.end()


class SelectionHook(QObject):
    """One card interaction owner; child buttons/menus retain their own events."""
    def __init__(self,window,card,scope,key):
        super().__init__(card);self.window=weakref.ref(window);self.card=weakref.ref(card);self.scope=scope;self.key=key;self.suppress_release=False
        card.installEventFilter(self)
    def live(self,obj):
        window=self.window()
        return window if window is not None and isValid(window) and not window._closing and obj.isVisible() and window._hub_scope==self.scope and window._organization_allowed(self.scope) else None
    def eventFilter(self,obj,event):
        if event.type() not in (QEvent.Enter,QEvent.Leave,QEvent.FocusIn,QEvent.MouseButtonPress,QEvent.MouseButtonRelease,QEvent.MouseButtonDblClick,QEvent.KeyPress):return False
        # External bookmarks retain their existing behavior.
        if self.key.startswith('source:'):return False
        window=self.live(obj)
        if window is None:
            if event.type() in (QEvent.MouseButtonPress,QEvent.MouseButtonRelease,QEvent.MouseButtonDblClick,QEvent.KeyPress):
                event.accept();return True
            return False
        kind=event.type()
        if kind==QEvent.Enter:window._queue_hub_hover(self)
        elif kind==QEvent.Leave:window._cancel_hub_hover(self)
        elif kind==QEvent.FocusIn:
            if not window._hub_pinned:window._queue_hub_hover(self)
        elif kind in (QEvent.MouseButtonPress,QEvent.MouseButtonRelease,QEvent.MouseButtonDblClick) and event.button()==Qt.LeftButton:
            if kind==QEvent.MouseButtonPress:
                self.suppress_release=False;window._focus_hub_card(self,pin=True)
            elif kind==QEvent.MouseButtonDblClick:
                self.suppress_release=True;window._focus_hub_card(self,pin=True);window._activate_hub_card(self)
            elif not self.suppress_release and obj.rect().contains(event.position().toPoint()):window._focus_hub_card(self,pin=True)
            event.accept();return True
        elif kind==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            window._focus_hub_card(self,pin=True)
            if event.key()!=Qt.Key_Space:window._activate_hub_card(self)
            event.accept();return True
        return False


class DetailRail(QFrame):
    """Compact context and direct continuation; complete management stays in details."""
    def __init__(self,window):
        super().__init__();self.window=window;self.entity=None;self.identity=None;self.setObjectName('contextRail');self.setFixedWidth(320)
        self.setStyleSheet('#contextRail{background:#151a28;border-left:1px solid #303547} #contextRail QWidget{background:transparent} #contextRail QPushButton{background:#242a3b;border:1px solid #383e50;padding:6px 9px} #contextRail QPushButton:hover{background:#3a3047} #contextRail QPushButton#primary{background:#ff477c;color:white;font-weight:700} #contextRail[restricted="true"]{background:#211222;border-left-color:#603446} #contextRail[restricted="true"] QPushButton{background:#351c30} #contextRail[restricted="true"] QPushButton#primary{background:#ff477c} #contextRail QLabel{background:transparent}')
        outer=QVBoxLayout(self);outer.setContentsMargins(16,14,16,12);outer.setSpacing(9)
        header=QHBoxLayout();label=QLabel('IN FOCUS');label.setObjectName('eyebrow');label.setToolTip('Click a card to pin this preview. Double-click for full details.');header.addWidget(label);header.addStretch()
        self.pin_button=QPushButton('Pinned');self.pin_button.setObjectName('focusPin');self.pin_button.setToolTip('Unpin selection to resume hover previews');self.pin_button.setStyleSheet('padding:3px 7px;font-size:11px');self.pin_button.clicked.connect(window._unpin_hub_selection);self.pin_button.hide();header.addWidget(self.pin_button)
        close=QPushButton('×');close.setFixedSize(28,28);close.setStyleSheet('padding:0;font-size:18px');close.setToolTip('Hide Focus View');close.clicked.connect(window._hide_hub_rail);header.addWidget(close);outer.addLayout(header)
        self.body=QScrollArea();self.body.setWidgetResizable(True);self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);outer.addWidget(self.body);self.clear()
    def clear(self):
        self.entity=None;self.identity=None;self.pin_button.hide();old=self.body.takeWidget()
        if old:old.deleteLater()
        self.body.setWidget(QLabel('Highlight a title to see a quick preview.'));self.hide()
    def show_entity(self,entity):
        group=getattr(self.window,'_hub_focus_group',None)
        identity=(entity.scope,entity.media_type,entity.key,self.window.db.connection.total_changes,tuple(group['ids']) if group else ())
        self.pin_button.setVisible(self.window._hub_pinned)
        if self.identity==identity:return
        self.identity=identity;self.entity=entity;old=self.body.takeWidget()
        if old:old.deleteLater()
        body=QWidget();body.setObjectName('focusBody');body.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);layout=QVBoxLayout(body);layout.setSizeConstraint(QLayout.SetNoConstraint);layout.setContentsMargins(0,0,0,4);layout.setSpacing(9)
        item=entity.item;local=entity.local;paths=self.window._entity_cover_paths([entity]);path=paths[0] if paths else None
        artwork=ArtworkHero(item.get('banner_path') or path);artwork.setFixedHeight(212);artwork.setObjectName('hubHero');al=QVBoxLayout(artwork);al.setContentsMargins(0,4,0,4)
        cover=QLabel('NO ART');cover.setObjectName('focusCover');cover.setAlignment(Qt.AlignCenter);cover.setFixedSize(144,204);cover.setStyleSheet('background:rgba(20,24,38,100);color:#9095a6;border:0');al.addWidget(cover,0,Qt.AlignHCenter);layout.addWidget(artwork)
        if path:cover.setPixmap(QPixmap(path).scaled(144,204,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        elif (item.get('coverImage') or {}).get('large'):self.window._load_remote_artwork(item['coverImage']['large'],cover,144,204)
        elif local and entity.media_type=='MANGA':self.window._load_manga_cover(local,cover)
        if not path and item.get('bannerImage'):self.window._load_remote_artwork(item['bannerImage'],artwork.banner,600,300)
        title=QLabel(group['name'] if group else entity.title);title.setObjectName('focusTitle');title.setWordWrap(True);title.setStyleSheet('font-size:21px;font-weight:700');layout.addWidget(title)
        if group:
            active=QLabel(f"{len(group['ids'])} local titles · Active: {entity.title}");active.setWordWrap(True);active.setObjectName('muted');active.setStyleSheet('font-size:12px;color:#a8a6b8');layout.addWidget(active)
        from .app import STATUS_COLORS
        status=('Reading' if entity.media_type=='MANGA' and entity.status=='Watching' else entity.status) or ('In Vault' if local else 'AniList-only')
        label=QLabel('● '+status);label.setObjectName('focusStatus');label.setStyleSheet('font-weight:600;color:'+STATUS_COLORS.get(entity.status,'#baabca'));layout.addWidget(label)
        if local:
            if entity.media_type=='MANGA':progress=float(local.get('progress') or 0);summary=local.get('active_label') or local.get('last_read_label') or f"{local.get('completed_count') or 0} / {local.get('item_count') or 0} local items completed"
            else:progress=100*(local.get('watched_count') or 0)/max(1,local.get('episode_count') or 0);summary=f"{local.get('watched_count') or 0} / {local.get('episode_count') or 0} watched"
            progress_label=QLabel(summary);progress_label.setObjectName('focusProgress');progress_label.setWordWrap(True);layout.addWidget(progress_label)
            bar=QProgressBar();bar.setRange(0,100);bar.setValue(round(progress));bar.setFixedHeight(6);bar.setTextVisible(False);bar.setStyleSheet('QProgressBar{background:#30394b;border:0} QProgressBar::chunk{background:#ff477c}');layout.addWidget(bar)
            play=QPushButton('▶  Continue Reading' if entity.media_type=='MANGA' else '▶  Continue Watching');play.setObjectName('primary');play.setProperty('focusContinue',True);play.setMinimumHeight(40);play.setEnabled(bool(local.get('available_count')));play.clicked.connect(lambda:self.window._continue_hub_entity(entity));layout.addWidget(play)
        if not local and entity.scope=='normal' and entity.media_type=='ANIME':
            from .requests_ui import request_button
            request=request_button(self.window,item)
            if request:
                request.setObjectName('focusRequest')
                request.setMinimumHeight(36)
                layout.addWidget(request)
        quick=QHBoxLayout();status_picker=QComboBox();status_picker.setObjectName('hubStatus');status_picker.setMinimumWidth(0);status_picker.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);status_picker.setStyleSheet('padding:5px 7px');status_picker.addItems(['No Status','Reading' if entity.media_type=='MANGA' else 'Watching','Completed','Planning','Paused','Dropped']);status_picker.setCurrentIndex(['','Watching','Completed','Planning','Paused','Dropped'].index(entity.status or '') if entity.status in {None,'Watching','Completed','Planning','Paused','Dropped'} else 0)
        def changed(index):
            if not self.window._organization_allowed(entity.scope) or self.window._hub_scope!=entity.scope:return
            value=[None,'Watching','Completed','Planning','Paused','Dropped'][index]
            if local and entity.media_type=='MANGA':self.window._manga_status(local['id'],value)
            else:self.window._set_status(value,entity.scope,anime_id=local['id'] if local else None,item=entity.item if not local else None)
        status_picker.activated.connect(changed);quick.addWidget(status_picker,1)
        if local:
            favorite=QPushButton('♥' if local.get('favorite') else '♡');favorite.setObjectName('focusFavorite');favorite.setFixedWidth(36);favorite.setToolTip('Toggle Favorite')
            def toggle_favorite():
                if not self.window._organization_allowed(entity.scope) or self.window._hub_scope!=entity.scope:return
                # Do not rebuild the browsing page or lose a pinned selection.
                if entity.media_type=='MANGA':self.window._manga_favorite(local['id'])
                else:
                    value=not bool(self.window.db.anime(local['id'])['favorite']);self.window.db.set_favorite(local['id'],value);self.window._library_cache_dirty=True
                    for ref in self.window._status_card_refs.get((entity.scope,entity.key),[])+self.window._status_card_refs.get((entity.scope,'anilist:'+str(item.get('id'))),[]):
                        card=ref()
                        if card is not None and isValid(card) and hasattr(card,'set_favorite'):card.set_favorite(value)
                self.window._select_hub_entity(entity.scope,entity.key,entity.item)
            favorite.clicked.connect(toggle_favorite);quick.addWidget(favorite)
        quick.addWidget(self.window._detail_collections_button(entity.scope,anime_id=local['id'] if local and entity.media_type=='ANIME' else None,manga_id=local['id'] if local and entity.media_type=='MANGA' else None,item=item if not local else None));layout.addLayout(quick)
        if local:
            from .ratings import rating_control
            layout.addWidget(rating_control(self.window,entity.scope,entity.media_type,local["id"]))
        count=item.get('chapters') if entity.media_type=='MANGA' else item.get('episodes');unit='chapters' if entity.media_type=='MANGA' else 'episodes'
        metadata=' · '.join(str(v) for v in [str(item.get('format') or entity.media_type).replace('_',' ').title(),item.get('seasonYear') or (item.get('startDate') or {}).get('year'),f'{count} {unit}' if count else None] if v)
        meta=QLabel(metadata);meta.setObjectName('muted');meta.setStyleSheet('font-size:12px;color:#9795a7');layout.addWidget(meta)
        genres=QLabel(' • '.join((item.get('genres') or [])[:3]));genres.setWordWrap(True);genres.setStyleSheet('font-size:12px;color:#ac98bb');layout.addWidget(genres)
        description=plain(item.get('description'))
        if description:
            from .app import TwoLineLabel
            synopsis=TwoLineLabel(description);synopsis.setMinimumWidth(0);synopsis.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);synopsis.setFixedHeight(40);synopsis.setObjectName('muted');synopsis.setStyleSheet('font-size:12px;color:#a4a0ad');layout.addWidget(synopsis)
        if local:
            preview=QWidget();preview.setObjectName('focusItems');pl=QVBoxLayout(preview);pl.setContentsMargins(0,2,0,0);pl.setSpacing(5)
            if entity.media_type=='MANGA':
                current=self.window.manga_store.continue_item(local['id']);rows=[row for row in self.window.manga_store.items(local['id']) if row['present']];index=next((i for i,row in enumerate(rows) if current and row['id']==current['id']),0);rows=rows[index:index+2]
                if rows:heading=QLabel('READ NEXT');heading.setObjectName('eyebrow');pl.addWidget(heading)
                from .display_titles import clean_manga_display_title
                for i,row in enumerate(rows):
                    name=('Current · ' if i==0 else 'Next · ')+clean_manga_display_title(row.get('display_name') or Path(row['path']).stem);button=QPushButton(QFontMetrics(self.font()).elidedText(name,Qt.ElideRight,255));button.setToolTip(name);button.clicked.connect(lambda _,identifier=row['id']:self.window.open_manga_item(identifier));pl.addWidget(button)
            else:
                from .integrated_player import clean_episode_label
                rows=[dict(row) for row in self.window.db.media(local['id']) if row['kind']=='episode' and row['present']];current=self.window.db.next_unwatched(local['id']);index=next((i for i,row in enumerate(rows) if current and row['id']==current['id']),max(0,len(rows)-1));rows=rows[max(0,index-1):index+2]
                if rows:heading=QLabel('EPISODE PREVIEW');heading.setObjectName('eyebrow');pl.addWidget(heading)
                for row in rows:
                    name=('✓  ' if row['watched'] else '▶  ')+clean_episode_label(row['path'],row['episode']);button=QPushButton(QFontMetrics(self.font()).elidedText(name,Qt.ElideRight,255));button.setToolTip(name);button.clicked.connect(lambda _,r=row:self.window.play(r['path'],r['id'],local['id']));pl.addWidget(button)
            layout.addWidget(preview)
        cached=getattr(self.window,'_detail_relation_cache',{}).get((entity.scope,entity.media_type,item.get('id')));relations=(cached[1] if cached else item.get('relations') or {}).get('edges') or [];seen=set()
        for edge in relations:
            node=edge.get('node') or {};identifier=node.get('id')
            if not identifier or identifier in seen or node.get('type') not in {'ANIME','MANGA'} or (node.get('isAdult') is True)!=(entity.scope=='restricted'):continue
            if len(seen)>=3:break
            seen.add(identifier);name=display_title(node);button=QPushButton(QFontMetrics(self.font()).elidedText('Related · '+name,Qt.ElideRight,255));button.setToolTip(name+' · '+str(edge.get('relationType') or 'Related').replace('_',' ').title());button.clicked.connect(lambda _,n=dict(node):self.window._open_related(n,entity.scope));layout.addWidget(button)
        layout.addStretch();hint=QLabel('Double-click a card for full details');hint.setStyleSheet('color:#858394;font-size:11px');layout.addWidget(hint);self.body.setWidget(body)


class ResumeArtwork(QLabel):
    """Full-width cover above a text-safe fade, using the existing image loaders."""
    def paintEvent(self,event):
        from PySide6.QtGui import QPainterPath
        from PySide6.QtCore import QRectF
        painter=QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        clip=QPainterPath();clip.addRoundedRect(QRectF(self.rect()),12,12)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(),QColor('#1c2432'))
        image=self.pixmap()
        height=min(self.height(),140)
        if image and not image.isNull():
            scale=max(self.width()/image.width(),height/image.height())
            width=self.width()/scale;source_height=height/scale
            source=QRectF((image.width()-width)/2,(image.height()-source_height)*.18,width,source_height)
            painter.drawPixmap(QRectF(0,0,self.width(),height),image,source)
        else:
            painter.setPen(QColor('#abb5c5'))
            painter.drawText(QRectF(0,0,self.width(),90),Qt.AlignCenter,'No artwork')
        fade=QLinearGradient(0,70,0,height)
        fade.setColorAt(0,QColor(15,19,28,0));fade.setColorAt(1,QColor('#0f131c'))
        painter.fillRect(QRectF(0,70,self.width(),height-70),fade)
        painter.fillRect(QRectF(0,height,self.width(),self.height()-height),QColor('#0f131c'))


class HomeTile(QFrame):
    def __init__(self,window,entity,continue_mode=False):
        super().__init__();self.setObjectName('card');self.setProperty('posterCard',True);self.setFixedSize(216 if continue_mode else 132,194 if continue_mode else 140);self.setFocusPolicy(Qt.StrongFocus);self.setCursor(Qt.PointingHandCursor);self.entity=entity;self.item=entity.item
        layout=QVBoxLayout(self);layout.setContentsMargins(8,8,8,8);layout.setSpacing(5)
        self.art=ResumeArtwork(self) if continue_mode else QLabel('NO ART')
        self.art.setAttribute(Qt.WA_TransparentForMouseEvents)
        if continue_mode:
            self.art.setGeometry(self.rect());self.art.lower()
            layout.setContentsMargins(12,8,12,9);layout.setSpacing(3);layout.addStretch()
        else:
            self.art.setFixedSize(116,96);self.art.setAlignment(Qt.AlignCenter)
            self.art.setStyleSheet('background:#202638;border-radius:7px;color:#7e879b')
            layout.addWidget(self.art)
        title=QLabel(entity.title);title.setFixedHeight(20);title.setToolTip(entity.title);title.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(title);self.title=title
        if continue_mode:title.setObjectName("cardTitle")
        local=entity.local
        summary=(local.get('active_label') or local.get('last_read_label') or 'Ready to read') if entity.media_type=='MANGA' and local else f"{local.get('watched_count') or 0} / {local.get('episode_count') or 0} watched" if local else entity.item.get('_recommendation_reason') or entity.label
        self.status_label=QLabel(summary);self.status_label.setObjectName('muted');self.status_label.setFixedHeight(18);self.status_label.setToolTip(summary);self.status_label.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(self.status_label)
        self.status_label.setVisible(continue_mode)
        if continue_mode and local:
            bar=QProgressBar();bar.setTextVisible(False);bar.setFixedHeight(4)
            bar.setRange(0,100 if entity.media_type=='MANGA' else max(1,local.get('episode_count') or 0))
            bar.setValue(int(local.get('progress') or 0) if entity.media_type=='MANGA' else int(local.get('watched_count') or 0))
            bar.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(bar)
        if continue_mode:
            from .icons import outline_icon
            action=QPushButton('Continue Reading' if entity.media_type=='MANGA' else 'Continue');action.setIcon(outline_icon('circle-play'));action.setFixedHeight(28);action.setStyleSheet('padding:2px 7px;font-size:12px');action.clicked.connect(lambda:window._continue_hub_entity(entity));layout.addWidget(action)
        paths=window._entity_cover_paths([entity])
        if paths:
            from .app import _scaled_artwork
            picture=_scaled_artwork(paths[0],self.art.width(),140 if continue_mode else self.art.height())
            if not picture.isNull():self.art.setPixmap(picture)
        elif (entity.item.get('coverImage') or {}).get('large'):window._load_remote_artwork(entity.item['coverImage']['large'],self.art,self.art.width(),140 if continue_mode else self.art.height())
        elif local and entity.media_type=='MANGA':window._load_manga_cover(local,self.art)
        window._register_status_card(self,entity.scope,entity.key)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos:window.manga_menu(self,pos,local['id']) if local and entity.media_type=='MANGA' else window.anime_collection_menu(self,pos,local['id'],scope=entity.scope) if local else window.remote_anime_menu(self,pos,entity.item,entity.scope))
        self.window=window
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if isinstance(self.art,ResumeArtwork):self.art.setGeometry(self.rect())
        self.title.setText(QFontMetrics(self.title.font()).elidedText(self.entity.title,Qt.ElideRight,self.width()-24))
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:self.window._open_hub_entity(self.entity)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter):self.window._open_hub_entity(self.entity)
        else:super().keyPressEvent(event)
    def set_manual_status(self,status):self.entity.status=status;self.status_label.setText(status or self.entity.label)
    def set_favorite(self,value):self.entity.local['favorite']=int(value);self.title.setText(QFontMetrics(self.title.font()).elidedText(('♥  ' if value else '')+self.entity.title,Qt.ElideRight,self.art.width()))


class HubMixin:
    def _empty_state(self,kind,message,scope=None,copy=''):
        from .branding import EmptyState
        return EmptyState(kind,message,scope or self._hub_scope,copy)
    def _schedule_branding_ownership(self):
        if self._closing or not hasattr(self,'_branding_timer'):return
        self._branding_timer.start()
    def _refresh_branding_ownership(self):
        if self._closing or not hasattr(self,'stack') or self.stack.currentWidget() is None:return
        from .branding import EmptyState
        page=self.stack.currentWidget();illustration=any(frame.property('brandIllustration') for frame in page.findChildren(QFrame) if frame.isVisible())
        states=[state for state in page.findChildren(EmptyState) if state.isVisible()];chosen=False
        for state in states:
            state.allow_art(not illustration and not chosen);state.resize_art();chosen=True
        self.sidebar._art_suppressed=False;self.sidebar._layout_art()
    def _init_hub_selection(self):
        self._branding_timer=QTimer(self);self._branding_timer.setSingleShot(True);self._branding_timer.setInterval(0);self._branding_timer.timeout.connect(self._refresh_branding_ownership)
        self._hub_pinned=False;self._hub_pinned_card=None;self._hub_focus_group=None;self._hub_hover=None;self._hub_selection_page=None
        self._hub_hover_timer=QTimer(self);self._hub_hover_timer.setSingleShot(True);self._hub_hover_timer.setInterval(280);self._hub_hover_timer.timeout.connect(self._apply_hub_hover)
    def _cancel_hub_hover(self,hook=None):
        pending=self._hub_hover[0]() if self._hub_hover else None
        if hook is None or pending is hook:self._hub_hover_timer.stop();self._hub_hover=None
    def _queue_hub_hover(self,hook):
        if self._hub_pinned or self._hub_rail_dismissed:return
        self._hub_hover=(weakref.ref(hook),weakref.ref(self.stack.currentWidget()));self._hub_hover_timer.start()
    def _apply_hub_hover(self):
        pending=self._hub_hover;self._hub_hover=None
        if self._closing or not pending or self._hub_pinned or self._hub_rail_dismissed:return
        hook,page=pending[0](),pending[1]()
        if hook is None or not isValid(hook) or page is None or not isValid(page) or page is not self.stack.currentWidget():return
        card=hook.card()
        if card is not None and isValid(card) and hook.live(card):self._focus_hub_card(hook)
    def _unpin_hub_selection(self):
        self._hub_pinned=False
        card=self._hub_pinned_card() if self._hub_pinned_card else None
        if card is not None and isValid(card):card.setProperty('focusPinned',False);card.style().unpolish(card);card.style().polish(card);card.update()
        self._hub_pinned_card=None
        if hasattr(self,'context_rail'):self.context_rail.pin_button.hide()
    def _focus_hub_card(self,hook,pin=False):
        card=hook.card()
        if card is None or not isValid(card) or hook.live(card) is None:return
        if self._hub_pinned and not pin:return
        self._cancel_hub_hover();item=getattr(card,'item',None);group_ids=card.property('franchiseLocalIds')
        key=hook.key;self._hub_focus_group=None
        if group_ids:
            store=self.organization(hook.scope);group_entities=[store.resolve('local:'+str(i)) for i in group_ids];group_entities=[e for e in group_entities if e is not None]
            active=next((e for e in group_entities if 0<(e.local.get('watched_count') or 0)<(e.local.get('episode_count') or 0)),next((e for e in group_entities if (e.local.get('watched_count') or 0)<(e.local.get('episode_count') or 0)),None))
            if active:key=active.key
            self._hub_focus_group={'ids':list(group_ids),'name':card.property('franchiseName') or (group_entities[0].title if group_entities else 'Franchise')}
        if pin:
            self._unpin_hub_selection();self._hub_pinned=True;self._hub_pinned_card=weakref.ref(card);card.setProperty('focusPinned',True);card.style().unpolish(card);card.style().polish(card);card.update()
        self._select_hub_entity(hook.scope,key,item if isinstance(item,dict) else None)
    def _activate_hub_card(self,hook):
        card=hook.card()
        if card is None or not isValid(card) or hook.live(card) is None:return
        if card.property('franchiseLocalIds'):card.clicked.emit()
        elif hasattr(card,'anime_id'):card.clicked.emit(card.anime_id)
        elif hasattr(card,'row'):card.clicked.emit(card.row['id'])
        elif hasattr(card,'clicked') and getattr(card,'item',{}).get('id'):card.clicked.emit(int(card.item['id']))
        elif hasattr(card,'entity'):self._open_hub_entity(card.entity)
    def _hide_hub_rail(self):
        self._cancel_hub_hover();self._unpin_hub_selection();self._hub_rail_dismissed=True;self.context_rail.hide()
    def _select_hub_entity(self,scope,key,item=None):
        if self._closing or scope!=self._hub_scope or not self._organization_allowed(scope):return
        entity=self.organization(scope).resolve(key,item)
        if entity is None or entity.media_type not in {'ANIME','MANGA'}:return
        self._hub_rail_dismissed=False;self.context_rail.show_entity(entity);self._update_hub_rail_visibility()
    def _update_hub_rail_visibility(self):
        if not hasattr(self,'context_rail'):return
        supported={'home','library','manga_library','restricted_manga_library','discover','restricted_discover','airing','discover_all','restricted_all','favorites','restricted_favorites','global_search','restricted_global_search','collection_detail','restricted_collection_detail','status_list','restricted_status_list','restricted_home','airing_all','saved','restricted_saved','franchise_detail','library_franchise','restricted_library_franchise'}
        self.context_rail.setVisible(self.width()>=1260 and self.current_view in supported and self.context_rail.entity is not None and not self._hub_rail_dismissed)
    def _prepare_hub_page(self):
        previous=self._hub_selection_page() if self._hub_selection_page else None
        if previous is not self.stack.currentWidget():
            self._cancel_hub_hover();self._unpin_hub_selection();self._hub_focus_group=None;self._hub_rail_dismissed=False;self._hub_selection_page=weakref.ref(self.stack.currentWidget())
        scope='restricted' if self.current_view.startswith('restricted') else 'normal'
        if scope!=self._hub_scope:
            self._hub_scope=scope;self.context_rail.clear();self.global_suggestions.dismiss();self.global_suggestions.results=[];self.global_suggestions.clear();self.global_suggestions.scope=scope;self.global_search.clear()
        if self.context_rail.property('restricted')!=(scope=='restricted'):
            self.context_rail.setProperty('restricted',scope=='restricted');self.context_rail.style().unpolish(self.context_rail);self.context_rail.style().polish(self.context_rail)
        self.global_search.setPlaceholderText('Search Restricted anime & manga…   Ctrl+K' if scope=='restricted' else 'Search your vault, anime & manga…   Ctrl+K')
        self._update_hub_rail_visibility();self._schedule_branding_ownership()
    def _top_header(self,outer,placeholder=None):pass # One persistent header search replaces duplicate page search bars.
    def _open_hub_entity(self,entity):
        if not self._organization_allowed(entity.scope):return
        if entity.local:self.show_manga_detail(entity.local['id']) if entity.media_type=='MANGA' else self.show_detail(entity.local['id'])
        else:self.show_remote_anilist(entity.item,'Restricted' if entity.scope=='restricted' else 'Discover')
    def _continue_hub_entity(self,entity):
        if not self._organization_allowed(entity.scope):return
        if entity.local and entity.media_type=='MANGA':
            item=self.manga_store.continue_item(entity.local['id'])
            if item:self.open_manga_item(item['id'])
        elif entity.local:self.continue_episode(entity.local['id'])
    def _focus_global_search(self):
        if self.current_view in {'player','local_reader','restricted_local_reader'} and self.isFullScreen():return
        self.global_search.setFocus();self.global_search.selectAll()
    def _hero(self,row):
        entity=self.organization('normal').resolve('local:'+str(row['id']))
        return self._entity_hero(entity) if entity else ArtworkHero()
    def _entity_hero(self,entity):
        paths=self._entity_cover_paths([entity]);metadata=entity.item
        path=metadata.get('banner_path') or (paths[0] if paths else None);frame=ArtworkHero(path);frame.setMinimumHeight(280)
        layout=QVBoxLayout(frame);layout.setContentsMargins(28,24,28,24);layout.setSpacing(10);layout.addStretch()
        caption=QLabel('YOUR NEXT CHAPTER' if entity.media_type=='MANGA' else 'FROM YOUR VAULT' if entity.local else 'DISCOVER YOUR NEXT STORY');caption.setObjectName('eyebrow');layout.addWidget(caption)
        title=QLabel(entity.title);title.setWordWrap(True);title.setObjectName('heroTitle');title.setMaximumWidth(600);layout.addWidget(title)
        copy=QLabel(plain(metadata.get('description'))[:145] or entity.label);copy.setWordWrap(True);copy.setMaximumWidth(530);layout.addWidget(copy)
        row=QHBoxLayout();action=QPushButton('Continue Reading' if entity.local and entity.media_type=='MANGA' else '▶ Continue Watching' if entity.local else 'Explore Title');action.setObjectName('primary');action.clicked.connect(lambda:self._continue_hub_entity(entity) if entity.local else self._open_hub_entity(entity));row.addWidget(action);row.addWidget(self._detail_collections_button(entity.scope,anime_id=entity.local['id'] if entity.local and entity.media_type=='ANIME' else None,manga_id=entity.local['id'] if entity.local and entity.media_type=='MANGA' else None,item=entity.item if not entity.local else None));row.addStretch();layout.addLayout(row)
        url=metadata.get('bannerImage') or (metadata.get('coverImage') or {}).get('large')
        if not path and url:self._load_remote_artwork(url,frame.banner,1000,400)
        return frame
    def _home_shelf(self,outer,title,entities,continue_mode=False,shortcut=None):
        if not entities:
            if title not in {'Continue Watching','Continue Reading'}:return None
            label=QLabel(title);label.setObjectName('section');outer.addWidget(label)
            button=QPushButton('All caught up · Browse your library');button.clicked.connect(self.show_library);outer.addWidget(button,0,Qt.AlignLeft);return None
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('section');header.addWidget(label);header.addStretch()
        if shortcut:
            button=QPushButton('View all');button.clicked.connect(shortcut);header.addWidget(button)
        outer.addLayout(header)
        strip=QScrollArea();strip.setWidgetResizable(True);strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);strip.setFixedHeight(205 if continue_mode else 158);strip.setFrameShape(QFrame.NoFrame)
        body=QWidget();layout=QHBoxLayout(body);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12);layout.setAlignment(Qt.AlignLeft)
        for entity in entities[:12]:layout.addWidget(HomeTile(self,entity,continue_mode))
        strip.setWidget(body);outer.addWidget(strip);return strip
    def _dashboard_data(self):
        from .dashboard import summarize
        stamp=self.db.change_stamp()
        cached=getattr(self,'_dashboard_cache',None)
        if cached and cached[0]==stamp:return cached[1:]
        store=self.organization('normal')
        local=[e for e in store.entities.values() if e.local]
        anime={e.local['id']:e for e in local if e.media_type=='ANIME'}
        manga=[e for e in local if e.media_type=='MANGA']
        rows=self.db.connection.execute("""
            SELECT anime_id,count(*),sum(CASE WHEN watched=1 THEN 1 ELSE 0 END),
                   max(CASE WHEN watched=0 AND resume_position_ms>0 THEN 1 ELSE 0 END)
            FROM media WHERE present=1 AND kind='episode' GROUP BY anime_id
        """).fetchall()
        episodes={r[0]:r for r in rows if r[0] in anime}
        data=summarize(list(anime.values()),manga,episodes.values())
        from .dashboard import storage_text
        anime_sizes=[r[1:] for r in self.db.connection.execute("SELECT anime_id,count(*),count(size_bytes),coalesce(sum(size_bytes),0) FROM media WHERE present=1 AND kind IN ('episode','extra','movie','special','ova','trailer') GROUP BY anime_id") if r[0] in anime]
        manga_ids={e.local['id'] for e in manga}
        manga_sizes=[r[1:] for r in self.db.connection.execute("SELECT series_id,count(*),count(size_bytes),coalesce(sum(size_bytes),0) FROM manga_items WHERE present=1 GROUP BY series_id") if r[0] in manga_ids]
        data['storage']=storage_text(anime_sizes+manga_sizes)
        data['storage_split']=(storage_text(anime_sizes),storage_text(manga_sizes))
        self._dashboard_cache=(stamp,anime,manga,episodes,data)
        return anime,manga,episodes,data

    def show_statistics(self):
        from .dashboard import analytics
        self.current_view='statistics';self.current_anime_id=None;self._set_active_nav('statistics')
        page=QWidget();page.setProperty('transientPage',True);shell=QVBoxLayout(page)
        scroll=QScrollArea();scroll.setWidgetResizable(True);shell.addWidget(scroll)
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(22,18,22,18)
        title=QLabel('Statistics');title.setObjectName('title');layout.addWidget(title)
        anime,manga,_,data=self._dashboard_data()
        layout.addWidget(analytics(self,data,list(anime.values()),manga))
        layout.addStretch();scroll.setWidget(body);self.replace(page)

    def show_home(self):
        from .desktop_ui import stats_strip
        from .dashboard import measures
        from .polish_ui import CompactFilterLayout
        from .icons import outline_icon
        self.current_view='home';self.current_anime_id=None;self._set_active_nav('home')
        page=QWidget();page.setProperty('transientPage',True);outer=QVBoxLayout(page);outer.setContentsMargins(16,12,16,12)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();content=QVBoxLayout(body);content.setContentsMargins(0,0,0,8);content.setSpacing(12)
        anime,manga,episodes,data=self._dashboard_data()
        continuing=[anime[i] for i,(_,count,watched,resume) in episodes.items() if resume or 0<watched<count]
        continuing.sort(key=lambda e:e.local.get('last_watched_at') or '',reverse=True)
        added=sorted(anime.values(),key=lambda e:(e.local.get('added_at') or '',e.local['id']),reverse=True)
        featured=next(iter(continuing or added or manga),None)
        paths=self._entity_cover_paths([featured]) if featured else []
        hero=ArtworkHero((featured.item.get('banner_path') or (paths[0] if paths else None)) if featured else None)
        hero.library_overview=True;hero.setMinimumHeight(190)
        head=QVBoxLayout(hero);head.setContentsMargins(20,16,20,12)
        eyebrow=QLabel('OVERVIEW');eyebrow.setObjectName('eyebrow');head.addWidget(eyebrow)
        title=QLabel('Home');title.setObjectName('heroTitle');head.addWidget(title)
        head.addWidget(QLabel('Your anime & manga library at a glance.'));head.addStretch()
        head.addWidget(stats_strip(data['summary']+(('Storage',data['storage']),)));content.addWidget(hero)
        actions=CompactFilterLayout(36)
        for label,icon,callback in (
            ('Continue Watching','circle-play',lambda:self.show_library(state_filter='In Progress')),
            ('Rescan Library','refresh-cw',self.rescan),('Open Anime','tv',self.show_library),
            ('Open Manga','book-open',self.show_manga_library),('View Statistics','chart-column',self.show_statistics)):
            button=QPushButton(label);button.setIcon(outline_icon(icon));button.clicked.connect(lambda _,fn=callback:fn())
            if label=='Continue Watching':button.setObjectName('primary')
            actions.addWidget(button)
        content.addLayout(actions)
        self._home_shelf(content,'Continue Watching',continuing,True)
        self._home_shelf(content,'Recently Added',added,shortcut=lambda:self.show_library(sort_mode='Recently Added'))
        reading=sorted((e for e in manga if e.local.get('active_item_id')),key=lambda e:e.local.get('last_read') or '',reverse=True)
        if reading:self._home_shelf(content,'Continue Reading',reading,True)
        insights=measures(data,True)
        scores=[e.local.get('personal_rating_units') for e in [*anime.values(),*manga]]
        scores=[n for n in scores if n is not None]
        if scores:insights.layout().addWidget(QLabel(f"Personal ratings · {sum(scores)/len(scores)/2:.2f} average · {len(scores)} rated"))
        content.addWidget(insights);content.addStretch();scroll.setWidget(body);outer.addWidget(scroll);self.replace(page)
        if featured:self._select_hub_entity('normal',featured.key)

    def show_status_hub(self):
        self.show_collections('normal');self.current_view='status_hub';self._set_active_nav('status_hub')
        page=self.stack.currentWidget();page.setProperty('transientPage',True)
        # Collections already owns live system-list counts. Keep the shared hub,
        # including custom collections below, rather than a second count cache.
        for label in page.findChildren(QLabel):
            if label.text()=='Collections' and label.objectName()=='title':label.setText('Status Hub')
        self._current_route=('status_hub',);self._prepare_hub_page()
