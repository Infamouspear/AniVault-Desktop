"""Native, bounded local reader. No WebEngine, VLC, network, or source writes."""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
import threading
import tempfile
from PySide6.QtCore import Qt, QObject, Signal, QEvent, QRectF, QSize
from PySide6.QtGui import QPainter, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QComboBox, QCheckBox, QSizePolicy, QApplication, QMenu)
from .manga_sources import open_source
from .manga_state import ReaderStore
from .reading_settings import save_reading_preferences

class PageCache:
    def __init__(self, max_pages=5, max_bytes=96*1024*1024):
        self.images=OrderedDict(); self.max_pages=max_pages; self.max_bytes=max_bytes;self.pinned=set()
    @property
    def bytes(self): return sum(image.sizeInBytes() for image in self.images.values())
    def put(self, index, image):
        self.images.pop(index,None); self.images[index]=image
        while len(self.images)>self.max_pages or self.bytes>self.max_bytes:
            victim=next((i for i in self.images if i not in self.pinned),None)
            if victim is None:break
            del self.images[victim]
    def get(self,index):
        image=self.images.get(index)
        if image is not None:self.images.move_to_end(index)
        return image

class PageWorker(QObject):
    opened=Signal(str,int)
    page_ready=Signal(int,int,object)
    failed=Signal(int,int,str)
    open_failed=Signal(str)
    def __init__(self,path,cache_dir):
        super().__init__();self.path=path;self.cache_dir=cache_dir
        self.condition=threading.Condition();self.pending=[];self.generation=0;self.stopping=False
        self.thread=threading.Thread(target=self.run,name='AniVaultLocalReader',daemon=True)
    def start(self):self.thread.start()
    def request(self,indices,generation):
        with self.condition:
            self.generation=generation;self.pending=list(dict.fromkeys(indices));self.condition.notify()
    def stop(self):
        with self.condition:self.stopping=True;self.pending=[];self.condition.notify()
    def run(self):
        source=None
        try:
            # This session's temporary files are owned by AniVault, not the book.
            Path(self.cache_dir).mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='session-',dir=self.cache_dir) as temp:
                try: source=open_source(self.path,temp)
                except Exception as exc:
                    if not self.stopping:self.open_failed.emit(f'{type(exc).__name__}: {exc}')
                    return
                if self.stopping:return
                self.opened.emit(source.kind,source.count)
                while True:
                    with self.condition:
                        self.condition.wait_for(lambda:self.stopping or self.pending)
                        if self.stopping:break
                        index=self.pending.pop(0); generation=self.generation
                    try:
                        image=source.image(index)
                        with self.condition:
                            if not self.stopping and generation==self.generation:self.page_ready.emit(generation,index,image)
                    except Exception as exc:
                        with self.condition:
                            if not self.stopping and generation==self.generation:self.failed.emit(generation,index,f'{type(exc).__name__}: {exc}')
                source.close();source=None
        except Exception as exc:
            if not self.stopping:self.open_failed.emit(f'{type(exc).__name__}: {exc}')
        finally:
            if source is not None:
                try:source.close()
                except Exception:pass

def spread_indices(page,total,spread,cover):
    if not spread:return [page]
    if cover and page==0:return [0]
    start=(1+((page-1)//2)*2) if cover else (page//2)*2
    return list(range(start,min(total,start+2)))

class PageCanvas(QWidget):
    def __init__(self,reader):
        super().__init__();self.reader=reader;self.images=[];self.message='Opening…';self.targets=[];self.drag=None;self.press_position=None;self.dragging=False;self.press_button=None
        self.setMouseTracking(True);self.setStyleSheet('background:#080c12;');self.setFocusPolicy(Qt.StrongFocus)
    def arrange(self,viewport,mode,zoom):
        if not self.images:
            self.resize(viewport);self.targets=[];self.update();return
        gap=4 if len(self.images)>1 else 0
        width=sum(image.width() for image in self.images);height=max(image.height() for image in self.images)
        factor=zoom
        if mode=='Fit Page':factor=min(max(1,viewport.width()-4-gap)/width,max(1,viewport.height()-4)/height)
        elif mode=='Fit Width':factor=max(1,viewport.width()-4-gap)/width
        # Scaling both pages equally preserves each page's aspect ratio.
        canvas_width=max(viewport.width(),int(width*factor+gap+4));canvas_height=max(viewport.height(),int(height*factor+4))
        self.resize(canvas_width,canvas_height);x=(canvas_width-width*factor-gap)/2;self.targets=[]
        for image in self.images:
            w,h=image.width()*factor,image.height()*factor
            self.targets.append(QRectF(x,(canvas_height-h)/2,w,h));x+=w+gap
        self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),Qt.black);painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for image,target in zip(self.images,self.targets):painter.drawImage(target,image)
        if self.message:
            painter.setPen(Qt.white);painter.drawText(self.rect().adjusted(30,30,-30,-30),Qt.AlignCenter|Qt.TextWordWrap,self.message)
    def mousePressEvent(self,event):
        if event.button() in (Qt.LeftButton,Qt.MiddleButton):
            self.drag=event.globalPosition();self.press_position=event.globalPosition();self.press_button=event.button();self.dragging=False
            self.setFocus();event.accept()
        else:super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.drag is None:return
        distance=event.globalPosition()-self.press_position
        if not self.dragging and distance.manhattanLength()>=QApplication.startDragDistance():
            self.dragging=True;self.setCursor(Qt.ClosedHandCursor)
        if self.dragging:
            delta=event.globalPosition()-self.drag
            for bar,step in ((self.reader.scroll.horizontalScrollBar(),delta.x()),(self.reader.scroll.verticalScrollBar(),delta.y())):bar.setValue(bar.value()-int(step))
            self.drag=event.globalPosition()
        event.accept()
    def mouseReleaseEvent(self,event):
        clicked=self.drag is not None and not self.dragging and self.press_button==Qt.LeftButton
        self.drag=None;self.press_position=None;self.press_button=None;self.dragging=False;self.unsetCursor()
        if clicked:
            viewport=self.reader.scroll.viewport();x=self.mapTo(viewport,event.position().toPoint()).x()
            self.reader.click_turn(x,viewport.width())
        event.accept()
    def contextMenuEvent(self,event):self.reader.reader_menu(event.globalPos())

class LocalMangaReader(QWidget):
    back_requested=Signal(); fullscreen_requested=Signal(); diagnostic=Signal(str)
    def __init__(self,db,path,cache_dir,scope='normal',parent=None,reader_identity=None):
        super().__init__(parent);self.db=db;self.path=str(path);self.scope=scope;self.store=ReaderStore(db);self.reader_identity=reader_identity
        self.setObjectName('localReader');self.setStyleSheet('QWidget#localReader QPushButton { padding:5px 9px; }')
        self.cache=PageCache();self.total=0;self.page=0;self.identity=None;self.generation=0;self.closed=False;self.completed=False;self.user_navigated=False;self.errors={};self.fullscreen=False;self._saved_position=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        self.header_widget=QWidget();header=QHBoxLayout(self.header_widget);header.setContentsMargins(10,6,10,6)
        def button(text,slot,box=header):
            b=QPushButton(text);b.clicked.connect(slot);box.addWidget(b);return b
        button('← Back',self.back_requested.emit)
        name=QLabel(Path(path).name);name.setToolTip(str(path));name.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);header.addWidget(name,1)
        button('Fullscreen',self.fullscreen_requested.emit).setToolTip('Fullscreen (F)')
        layout.addWidget(self.header_widget)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(False);self.scroll.setAlignment(Qt.AlignCenter);self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.canvas=PageCanvas(self);self.scroll.setWidget(self.canvas);layout.addWidget(self.scroll,1)
        self.toolbar=QWidget();toolbar_layout=QVBoxLayout(self.toolbar);toolbar_layout.setContentsMargins(0,0,0,0);toolbar_layout.setSpacing(0)
        footer=QHBoxLayout();footer.setContentsMargins(10,6,10,6);footer.setSpacing(7)
        button('⇤',lambda:self.go(0),footer).setToolTip('First page (Home)')
        button('Previous',lambda:self.step(-1),footer);button('Next',lambda:self.step(1),footer)
        button('⇥',lambda:self.go(self.total-1),footer).setToolTip('Last page (End)')
        self.counter=QLabel('Opening…');footer.addWidget(self.counter)
        footer.addStretch(1);toolbar_layout.addLayout(footer)
        footer=QHBoxLayout();footer.setContentsMargins(10,0,10,6);footer.setSpacing(7)
        self.mode=QComboBox();self.mode.addItems(['Fit Page','Fit Width','100%','Manual']);self.mode.setCurrentText(db.setting('reader_fit','Fit Page'));footer.addWidget(self.mode)
        button('−',lambda:self.zoom_by(1/1.2),footer);button('+',lambda:self.zoom_by(1.2),footer)
        button('1:1',self.reset_zoom,footer)
        self.spread=QCheckBox('Spread');self.spread.setChecked(db.setting('reader_spread','0')=='1');footer.addWidget(self.spread)
        self.cover=QCheckBox('Single cover');self.cover.setChecked(db.setting('reader_cover','1')=='1');footer.addWidget(self.cover)
        self.direction=QComboBox();self.direction.addItem('Right-to-Left (Manga)','RTL');self.direction.addItem('Left-to-Right','LTR');self.direction.setCurrentIndex(max(0,self.direction.findData(db.setting('reader_direction','RTL'))));footer.addWidget(self.direction)
        footer.addStretch(1);self.bookmark=button('☆',self.toggle_bookmark,footer);self.bookmark.setToolTip('Bookmark current page (B)')
        self.bookmarks=QComboBox();self.bookmarks.setMinimumWidth(118);self.bookmarks.addItem('Bookmarks',None);footer.addWidget(self.bookmarks)
        self.retry=button('Retry page',self.retry_page,footer);self.retry.hide();toolbar_layout.addLayout(footer);layout.addWidget(self.toolbar)
        self.toolbar.setVisible(db.setting("reader_toolbar","1")=="1")
        self.zoom=max(.1,min(4.,float(db.setting('reader_zoom','1'))))
        self._layout_preferences=(self.spread.isChecked(),self.cover.isChecked(),self.direction.currentData())
        for widget in (self.mode,self.direction):widget.currentTextChanged.connect(self.preferences_changed)
        for widget in (self.spread,self.cover):widget.toggled.connect(self.preferences_changed)
        self.bookmarks.activated.connect(self.jump_bookmark)
        self.scroll.viewport().installEventFilter(self);self.canvas.installEventFilter(self)
        self.shortcuts=[]
        actions={'Left':lambda:self.step(1 if self.direction.currentData()=='RTL' else -1),
                 'Right':lambda:self.step(-1 if self.direction.currentData()=='RTL' else 1),
                 'PgDown':lambda:self.step(1),'PgUp':lambda:self.step(-1),'Space':lambda:self.step(1),
                 'Home':lambda:self.go(0),'End':lambda:self.go(self.total-1),'F':self.fullscreen_requested.emit,
                 'Escape':self.exit_fullscreen,'B':self.toggle_bookmark,'T':self.toggle_toolbar,'0':self.reset_zoom,
                 'P':lambda:self.mode.setCurrentText('Fit Page'),'W':lambda:self.mode.setCurrentText('Fit Width'),'+':lambda:self.zoom_by(1.2),'-':lambda:self.zoom_by(1/1.2)}
        self._key_actions=actions
        for key,action in actions.items():
            shortcut=QShortcut(QKeySequence(key),self);shortcut.setContext(Qt.WidgetWithChildrenShortcut);shortcut.activated.connect(action);self.shortcuts.append(shortcut)
        self.worker=PageWorker(path,cache_dir);self.worker.opened.connect(self.opened);self.worker.page_ready.connect(self.received);self.worker.failed.connect(self.page_error);self.worker.open_failed.connect(self.open_error)
        # App connects diagnostics before starting the worker.
    def start(self):self.worker.start()
    def opened(self,kind,total):
        if self.closed:return
        self.total=total;state=self.store.open(self.path,self.scope,kind,total,self.reader_identity);self.identity=state['identity'];self.page=state['current_page']-1;self.completed=bool(state['completed'])
        self.diagnostic.emit(f'ReaderOpen source_type={kind} path={self.path} page_count={total}')
        self.diagnostic.emit(f'ReaderResume page={self.page+1}');self.refresh_bookmarks();self.load()
    def open_error(self,message):
        if self.closed:return
        self.canvas.images=[];self.canvas.message='AniVault could not open this item.\n'+message;self.counter.setText('Unable to open');self.arrange()
        self.diagnostic.emit(f'ReaderOpenError exception={message}')
    def visible_indices(self):return spread_indices(self.page,self.total,self.spread.isChecked(),self.cover.isChecked()) if self.total else []
    def go(self,page):
        if not self.total or self.closed:return
        self.user_navigated=True;self.page=max(0,min(self.total-1,page));self.load()
    def step(self,delta):
        if not self.total:return
        indices=self.visible_indices()
        if delta>0:target=indices[-1]+1
        else:target=indices[0]-1
        self.go(target)
    def load(self):
        self.generation+=1;visible=self.visible_indices();self.cache.pinned=set(visible)
        # The first priority is every visible page, then nearby prefetch only.
        nearby=visible+[visible[-1]+1,visible[0]-1,visible[-1]+2]
        self.worker.request([i for i in nearby if 0<=i<self.total and self.cache.get(i) is None and i not in self.errors],self.generation)
        self.counter.setText(f'Pages {visible[0]+1}–{visible[-1]+1} / {self.total}' if len(visible)>1 else f'Page {self.page+1} / {self.total}');self.present()
    def received(self,generation,index,image):
        if self.closed or generation!=self.generation:return
        self.cache.put(index,image);self.present()
    def page_error(self,generation,index,message):
        if self.closed or generation!=self.generation:return
        self.errors[index]=message;self.diagnostic.emit(f'ReaderPageError page={index+1} exception={message}');self.present()
    def present(self):
        indices=self.visible_indices();images=[self.cache.get(i) for i in indices]
        bad=[i for i in indices if i in self.errors];self.retry.setVisible(bool(bad))
        if bad:
            self.canvas.images=[];self.canvas.message=f'Page {bad[0]+1} could not be loaded.\n{self.errors[bad[0]]}\nRetry or navigate to another page.'
        elif all(image is not None for image in images):
            self.canvas.images=list(reversed(images)) if self.direction.currentData()=='RTL' else images;self.canvas.message=''
            complete=self.user_navigated and self.total-1 in indices
            if complete and not self.completed:self.completed=True;self.diagnostic.emit('ReaderComplete')
            position=(self.page+1,self.total,self.completed)
            if position!=self._saved_position:
                self.store.save(self.identity,*position);self._saved_position=position
        else:self.canvas.images=[];self.canvas.message='Loading page…'
        self.bookmark.setText('★' if self.identity and self.page+1 in self.store.bookmarks(self.identity) else '☆');self.arrange()
    def retry_page(self):
        for index in self.visible_indices():self.errors.pop(index,None)
        self.load()
    def arrange(self):self.canvas.arrange(self.scroll.viewport().size(),self.mode.currentText(),self.zoom)
    def preferences_changed(self,*args):
        if self.closed:return
        if self.mode.currentText()=='100%':self.zoom=1.
        save_reading_preferences(self.db,[('fit',self.mode.currentText()),('spread',int(self.spread.isChecked())),('cover',int(self.cover.isChecked())),('direction',self.direction.currentData()),('zoom',self.zoom)])
        preferences=(self.spread.isChecked(),self.cover.isChecked(),self.direction.currentData())
        changed=preferences!=self._layout_preferences;self._layout_preferences=preferences
        if changed and self.total:self.load()
        else:self.arrange()
    def click_turn(self,x,width):
        if not self.total or width<=0:return
        # The small center dead zone avoids accidental turns while grabbing a page.
        if .46*width<=x<=.54*width:return
        forward=(x<width/2) if self.direction.currentData()=='RTL' else (x>width/2)
        self.step(1 if forward else -1)
    def set_fullscreen(self,fullscreen):
        self.fullscreen=fullscreen;self.header_widget.setVisible(not fullscreen);self.arrange()
    def toggle_toolbar(self):
        shown=self.toolbar.isHidden();self.toolbar.setVisible(shown);self.db.set_setting('reader_toolbar',int(shown));self.arrange()
    def reader_menu(self,position):
        menu=QMenu(self)
        for title,action in [('Previous page',lambda:self.step(-1)),('Next page',lambda:self.step(1)),('Fit Page',lambda:self.mode.setCurrentText('Fit Page')),('Fit Width',lambda:self.mode.setCurrentText('Fit Width')),('Reset zoom',self.reset_zoom),('Show / hide toolbar (T)',self.toggle_toolbar),('Bookmark page (B)',self.toggle_bookmark),('Retry page',self.retry_page),('Fullscreen (F)',self.fullscreen_requested.emit),('Back',self.back_requested.emit)]:
            menu.addAction(title).triggered.connect(action)
        bookmarks=menu.addMenu('Bookmarks')
        for page in self.store.bookmarks(self.identity) if self.identity else []:
            bookmarks.addAction(f'Page {page}').triggered.connect(lambda checked=False,p=page:self.go(p-1))
        menu.exec(position)
    def zoom_by(self,factor,anchor=None):
        if self.mode.currentText() in ('Fit Page','Fit Width') and self.canvas.images:
            self.zoom=self.canvas.targets[0].width()/self.canvas.images[0].width()
        viewport=self.scroll.viewport()
        anchor=anchor or viewport.rect().center()
        old_size=self.canvas.size();old_x=self.scroll.horizontalScrollBar().value()+anchor.x();old_y=self.scroll.verticalScrollBar().value()+anchor.y()
        old_target=self.canvas.targets[0] if self.canvas.targets else None
        image_x=(old_x-old_target.x())/old_target.width() if old_target and old_target.width() else None
        image_y=(old_y-old_target.y())/old_target.height() if old_target and old_target.height() else None
        self.zoom=max(.1,min(4.,self.zoom*factor));self.mode.blockSignals(True);self.mode.setCurrentText('Manual');self.mode.blockSignals(False);self.preferences_changed()
        if old_size.width() and old_size.height():
            target=self.canvas.targets[0] if self.canvas.targets else None
            x=target.x()+image_x*target.width() if target and image_x is not None else old_x*self.canvas.width()/old_size.width()
            y=target.y()+image_y*target.height() if target and image_y is not None else old_y*self.canvas.height()/old_size.height()
            self.scroll.horizontalScrollBar().setValue(round(x-anchor.x()))
            self.scroll.verticalScrollBar().setValue(round(y-anchor.y()))
    def reset_zoom(self):
        self.zoom=1.;self.mode.blockSignals(True);self.mode.setCurrentText('100%');self.mode.blockSignals(False);self.preferences_changed()
    def toggle_bookmark(self):
        if not self.identity:return
        self.store.toggle_bookmark(self.identity,self.page+1);self.refresh_bookmarks();self.bookmark.setText('★' if self.page+1 in self.store.bookmarks(self.identity) else '☆')
    def refresh_bookmarks(self):
        self.bookmarks.clear();self.bookmarks.addItem('Bookmarks',None)
        for page in self.store.bookmarks(self.identity):
            if page<=self.total:self.bookmarks.addItem(f'Page {page}',page)
    def jump_bookmark(self,index):
        page=self.bookmarks.itemData(index)
        if page is not None:self.go(page-1)
        self.bookmarks.setCurrentIndex(0)
    def exit_fullscreen(self):
        if self.fullscreen:self.fullscreen_requested.emit()
    def eventFilter(self,obj,event):
        # Canvas keys must not be swallowed by QScrollArea or depend on tool-window activation.
        if not self.closed and event.type() in (QEvent.ShortcutOverride,QEvent.KeyPress) and not (event.modifiers() & (Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier)):
            action=self._key_actions.get(QKeySequence(event.key()).toString())
            if action is not None:
                event.accept()
                if event.type()==QEvent.KeyPress:action()
                return True
        if event.type()==QEvent.Resize and obj is self.scroll.viewport():self.arrange()
        if event.type()==QEvent.Wheel:
            delta=event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                anchor=obj.mapTo(self.scroll.viewport(),event.position().toPoint())
                self.zoom_by(1.12**max(-3,min(3,delta/120)),anchor)
            return True
        return super().eventFilter(obj,event)
    def shutdown(self):
        if self.closed:return
        self.closed=True;self.worker.stop()
        for signal,slot in [(self.worker.opened,self.opened),(self.worker.page_ready,self.received),(self.worker.failed,self.page_error),(self.worker.open_failed,self.open_error)]:signal.disconnect(slot)
        for shortcut in self.shortcuts:shortcut.setEnabled(False)
        self.canvas.images=[];self.cache.images.clear()
        # Worker owns source cleanup; navigation never waits for archive/PDF IO.
        self.diagnostic.emit('ReaderClosed')
