"""Virtualized anime review queue; records are archived, never removed by review."""
import json
import sqlite3
from collections import OrderedDict
from PySide6.QtCore import Qt,QAbstractListModel,QModelIndex,QSize,QRect,QEvent,QTimer
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QKeySequence,QShortcut
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,
 QListView,QStyledItemDelegate,QAbstractItemView,QMenu,QStyle)
from .requests_store import PROCESSED
from .polish_ui import CompactFilterLayout


def item_data(row):
    try:return json.loads(row['metadata'] or '{}')
    except (TypeError,ValueError):return {}


class QueueModel(QAbstractListModel):
    def __init__(self,store,parent=None):super().__init__(parent);self.store=store;self.rows=[];self.history=False;self.query='';self.status='All statuses';self.sort=0
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.UserRole:return row
        if role in (Qt.DisplayRole,Qt.AccessibleTextRole):return row['title']+' · '+row['status']
    def sync(self):
        rows=[]
        for row in self.store.visible():
            if row['kind']!='anime' or bool(row['archived'])!=self.history:continue
            item=item_data(row);names=[row['title'],row['notes'],*(item.get('title') or {}).values(),*(item.get('synonyms') or [])]
            if self.query and not any(self.query.casefold() in str(n).casefold() for n in names):continue
            if self.status!='All statuses' and self.status!=row['status']:continue
            rows.append(row)
        if self.sort==1:rows.reverse()
        if self.sort==2:rows.sort(key=lambda r:(r['title'].casefold(),r['id']))
        old=[r['id'] for r in self.rows];new=[r['id'] for r in rows];old_set=set(old);new_set=set(new)
        if old==new:
            self.rows=rows
            if rows:self.dataChanged.emit(self.index(0),self.index(len(rows)-1))
        elif len(old)==len(new)+1 and [i for i in old if i in new_set]==new:
            position=next(n for n,i in enumerate(old) if i not in new_set);self.beginRemoveRows(QModelIndex(),position,position);self.rows=rows;self.endRemoveRows()
        elif len(new)==len(old)+1 and [i for i in new if i in old_set]==old:
            position=next(n for n,i in enumerate(new) if i not in old_set);self.beginInsertRows(QModelIndex(),position,position);self.rows=rows;self.endInsertRows()
        else:self.beginResetModel();self.rows=rows;self.endResetModel()


class QueueDelegate(QStyledItemDelegate):
    def __init__(self,owner):super().__init__(owner.view);self.owner=owner;self.covers=OrderedDict()
    def sizeHint(self,option,index):return QSize(600,100)
    def actions(self,row):
        if not row['archived']:return [('Approve','Approved'),('Decline','Declined'),('Downloaded','Available')]
        return [('Downloaded','Available'),('Restore','restore')] if row['status']=='Approved' else [('Restore','restore')]
    def buttons(self,rect,row):
        actions=self.actions(row);width=92;x=rect.right()-8-len(actions)*(width+6)
        return [(QRect(x+n*(width+6),rect.top()+34,width,30),label,action) for n,(label,action) in enumerate(actions)]
    def cover(self,row):
        item=item_data(row);url=(item.get('coverImage') or {}).get('large');key=(row['id'],url)
        if not url:return None
        if key not in self.covers:
            viewport=self.owner.view.viewport()
            class Target(QLabel):
                def setPixmap(target,pix):
                    super().setPixmap(pix);viewport.update()
            target=Target(self.owner.view);target.hide();self.covers[key]=target
            self.owner.window._load_remote_artwork(url,target,46,66,'normal')
            while len(self.covers)>96:self.covers.popitem(last=False)[1].deleteLater()
        else:self.covers.move_to_end(key)
        return self.covers[key].pixmap()
    def paint(self,painter,option,index):
        row=index.data(Qt.UserRole)
        if not row:return
        painter.save();painter.setRenderHint(QPainter.Antialiasing)
        rect=option.rect.adjusted(2,2,-2,-2)
        selected=bool(option.state & QStyle.State_Selected)
        painter.fillRect(rect,QColor('#251b2a' if selected else '#0d121c'))
        painter.setPen(QColor('#303747'));painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        art=QRect(rect.left()+8,rect.top()+12,46,66);pix=self.cover(row)
        if pix and not pix.isNull():painter.drawPixmap(art,pix)
        else:painter.fillRect(art,QColor('#202838'))
        buttons=self.buttons(rect,row);right=buttons[0][0].left()-12
        text=QRect(art.right()+12,rect.top()+10,max(20,right-art.right()-12),22)
        font=QFont(option.font);font.setBold(True);painter.setFont(font);painter.setPen(QColor('#f1edf5'))
        painter.drawText(text,Qt.AlignVCenter,painter.fontMetrics().elidedText(row['title'],Qt.ElideRight,text.width()))
        font.setBold(False);font.setPointSize(9);painter.setFont(font);painter.setPen(QColor('#a6afc1'))
        item=item_data(row);meta=' · '.join(str(v) for v in (item.get('format') or row['category'],item.get('seasonYear'),row['created'][:10],row['status']) if v)
        painter.drawText(text.translated(0,24),Qt.AlignVCenter,painter.fontMetrics().elidedText(meta,Qt.ElideRight,text.width()))
        note=('Processed '+str(row['processed_at'] or '') if row['archived'] else row['notes'])
        if note:painter.drawText(text.translated(0,46),Qt.AlignVCenter,painter.fontMetrics().elidedText(note,Qt.ElideRight,text.width()))
        for area,label,action in buttons:
            painter.setPen(QColor('#89405c' if action in PROCESSED else '#394254'));painter.setBrush(QColor('#302032' if action in PROCESSED else '#19202c'));painter.drawRoundedRect(area,8,8);painter.setPen(QColor('#f7edf4'));painter.drawText(area,Qt.AlignCenter,label)
        painter.restore()
    def editorEvent(self,event,model,option,index):
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton:
            for rect,label,action in self.buttons(option.rect.adjusted(2,2,-2,-2),index.data(Qt.UserRole)):
                if rect.contains(event.position().toPoint()):self.owner.perform(index.data(Qt.UserRole),action);return True
        return False


class AnimeQueue(QWidget):
    def __init__(self,window,store):
        super().__init__();self.window=window;self.store=store;self.undo_token=None
        outer=QVBoxLayout(self);controls=CompactFilterLayout(38)
        self.mode=QComboBox();self.mode.setObjectName('requestQueueMode');self.mode.addItems(['Active Queue','History']);controls.addWidget(self.mode)
        self.search=QLineEdit();self.search.setPlaceholderText('Search requests…');self.search.setClearButtonEnabled(True);self.search.setMinimumWidth(180);controls.addWidget(self.search)
        self.status=QComboBox();self.status.addItems(['All statuses','Requested','Under Review']);controls.addWidget(self.status)
        self.sort=QComboBox();self.sort.addItems(['Newest first','Oldest first','Title A–Z']);controls.addWidget(self.sort)
        new=QPushButton('New Request');new.clicked.connect(self.new);controls.addWidget(new);outer.addLayout(controls)
        self.notice=QWidget();line=QHBoxLayout(self.notice);line.setContentsMargins(0,0,0,0);self.notice_text=QLabel();self.notice_text.setWordWrap(True);line.addWidget(self.notice_text,1);self.undo_button=QPushButton('Undo');self.undo_button.clicked.connect(self.undo);line.addWidget(self.undo_button);outer.addWidget(self.notice);self.notice.hide()
        self.count=QLabel();self.count.setObjectName('muted');outer.addWidget(self.count)
        self.view=QListView();self.view.setObjectName('animeRequestQueue');self.view.setUniformItemSizes(True);self.view.setSelectionMode(QAbstractItemView.SingleSelection);self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.view.setMinimumWidth(0)
        self.model=QueueModel(store,self.view);self.view.setModel(self.model);self.delegate=QueueDelegate(self);self.view.setItemDelegate(self.delegate);outer.addWidget(self.view,1)
        self.empty=QLabel();self.empty.setWordWrap(True);outer.addWidget(self.empty)
        details=QShortcut(QKeySequence('Return'),self.view);details.setContext(Qt.WidgetWithChildrenShortcut);details.activated.connect(lambda:self.open(self.view.currentIndex().data(Qt.UserRole)))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu);self.view.customContextMenuRequested.connect(self.context)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(90);self.debounce.timeout.connect(self.filter)
        self.search.textChanged.connect(lambda:self.debounce.start())
        self.mode.currentIndexChanged.connect(self.change_mode)
        for signal in (self.status.currentIndexChanged,self.sort.currentIndexChanged):signal.connect(self.filter)
        for key,action in [('A','Approved'),('D','Declined'),('L','Available')]:
            shortcut=QShortcut(QKeySequence(key),self.view);shortcut.setContext(Qt.WidgetWithChildrenShortcut);shortcut.activated.connect(lambda a=action:self.selected(a))
        undo=QShortcut(QKeySequence.Undo,self.view);undo.setContext(Qt.WidgetWithChildrenShortcut);undo.activated.connect(self.undo)
        self.refresh()
    def change_mode(self,*args):
        self.status.blockSignals(True);self.status.clear();self.status.addItems(['All statuses']+(['Approved','Available','Declined'] if self.mode.currentIndex() else ['Requested','Under Review']));self.status.blockSignals(False);self.filter()
    def filter(self,*args):
        self.model.history=self.mode.currentIndex()==1;self.model.query=self.search.text().strip();self.model.status=self.status.currentText();self.model.sort=self.sort.currentIndex();self.refresh()
    def refresh(self):
        scroll=self.view.verticalScrollBar().value();self.model.sync();self.view.doItemsLayout();self.view.verticalScrollBar().setValue(scroll)
        count=len(self.model.rows);self.count.setText(f'{count} '+('archived requests' if self.model.history else 'requests awaiting review')+' · A: approve · D: decline · L: downloaded')
        self.empty.setText('No matching requests. Clear the search or status filter.' if self.search.text() or self.status.currentIndex() else 'History is empty.' if self.model.history else 'Your review queue is clear. Processed requests are in History.');self.empty.setVisible(not count)
    def write(self,operation):
        timeout=self.store.connection.execute('PRAGMA busy_timeout').fetchone()[0]
        self.store.connection.execute('PRAGMA busy_timeout=100')
        try:return operation()
        finally:self.store.connection.execute(f'PRAGMA busy_timeout={int(timeout)}')
    def perform(self,row,action):
        if not row:return
        from .app import AniVaultDialog
        try:
            token=self.write(lambda:self.store.restore(row['id']) if action=='restore' else self.store.process(row['id'],action))
        except (ValueError,sqlite3.OperationalError) as exc:self.notice_text.setText('Library database is busy. Try again when the scan finishes.' if isinstance(exc,sqlite3.OperationalError) else str(exc));self.undo_button.hide();self.notice.show();self.refresh();return
        if token:
            self.undo_token=token;self.notice_text.setText('Request restored to Active Queue.' if action=='restore' else f'Request marked {action} and archived.');self.undo_button.show();self.notice.show();self.window.requests_changed.emit()
    def selected(self,action):self.perform(self.view.currentIndex().data(Qt.UserRole),action)
    def undo(self):
        if not self.undo_token:return
        try:self.write(lambda:self.store.undo(self.undo_token))
        except sqlite3.OperationalError:self.notice_text.setText('Library database is busy. Try Undo again when the scan finishes.');return
        except ValueError as exc:self.notice_text.setText(str(exc));self.undo_button.hide();return
        self.undo_token=None;self.notice.hide();self.window.requests_changed.emit()
    def new(self):
        from .requests_ui import editor
        editor(self.window,self.store,'anime')
    def open(self,row):
        if not row:return
        from .requests_ui import editor
        try:
            fresh=self.store.get(row['id'])
            if self.store.restricted(fresh['provider_id']):raise ValueError('This request is unavailable here.')
        except ValueError as exc:
            self.notice_text.setText(str(exc));self.undo_button.hide();self.notice.show();self.refresh();return
        editor(self.window,self.store,'anime',fresh)
    def context(self,pos):
        index=self.view.indexAt(pos);row=index.data(Qt.UserRole)
        if not row:return
        menu=QMenu(self);menu.addAction('Open details / notes').triggered.connect(lambda:self.open(row))
        item=item_data(row)
        if item.get('id'):menu.addAction('Discover title').triggered.connect(lambda:self.window.show_remote_anilist(item,'Discover'))
        else:menu.addAction('Browse Discover').triggered.connect(self.window.show_discover)
        local=self.store.local_match(row['provider_id'])
        if local:menu.addAction('Open local title').triggered.connect(lambda:self.window.show_detail(local))
        if row['archived']:menu.addAction('Restore to Active Queue').triggered.connect(lambda:self.perform(row,'restore'))
        menu.addSeparator();menu.addAction('Permanently delete…').triggered.connect(lambda:self.delete(row));menu.exec(self.view.viewport().mapToGlobal(pos))
    def delete(self,row):
        from .app import AniVaultDialog
        if AniVaultDialog.confirm(self.window,'Permanently delete request','Delete this request and its decision history? This cannot be undone.','Delete'):
            try:self.write(lambda:self.store.remove(row['id']))
            except sqlite3.OperationalError:self.notice_text.setText('Library database is busy. The request was kept. Try again after the scan.');self.undo_button.hide();self.notice.show();return
            self.window.requests_changed.emit()
