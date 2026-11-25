"""Desktop request controls and management view."""
import json
from collections import Counter
from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFormLayout,QFrame,
    QHBoxLayout,QLabel,QLineEdit,QPushButton,QScrollArea,QTabWidget,QTextEdit,QVBoxLayout,QWidget)
from .requests_store import Requests, REQUEST, FEEDBACK, CATEGORIES
from .desktop_ui import decorate_search
from .polish_ui import CompactFilterLayout


def listen(window, owner, callback):
    class Listener(QObject):
        @Slot()
        def refresh(self): callback()
    listener=Listener(owner)
    window.requests_changed.connect(listener.refresh)


def state_map(window):
    store=Requests(window.db)
    stamp=window.db.change_stamp()
    cached=getattr(window,'_request_states',None)
    if cached and cached[0]==stamp:return cached[1]
    states={r['provider_id']:r['status'] for r in store.visible() if r['provider_id']}
    window._request_states=(stamp,states)
    return states


def request_button(window,item):
    if item.get('isAdult') is not False or item.get('type','ANIME')!='ANIME' or Requests(window.db).restricted(item.get('id')):return None
    item={**item,'type':'ANIME'}
    button=QPushButton()
    def refresh():
        status=state_map(window).get(item['id'])
        button.setText('Available in Library' if status=='Available' else status or 'Request Anime')
        button.setToolTip('Open existing request' if status else 'Add to your local request list')
    def submit():
        from .app import AniVaultDialog
        if window.current_view.startswith('restricted'):return
        if item['id'] in state_map(window):
            window.show_requests(provider=item['id']);return
        try:Requests(window.db).discover(item)
        except ValueError as exc:AniVaultDialog.alert(window,'Anime request',str(exc));return
        window.requests_changed.emit()
    listen(window,button,refresh);refresh();button.clicked.connect(submit)
    return button


def editor(window,store,kind,row=None):
    from .app import AniVaultDialog
    dialog=QDialog(window);dialog.setWindowTitle('Request details' if row else 'New request' if kind=='anime' else 'New feedback')
    layout=QFormLayout(dialog)
    if row:
        title=QLabel(row['title']);title.setTextFormat(Qt.PlainText);title.setWordWrap(True);layout.addRow(title)
        layout.addRow('Created',QLabel(row['created']+' UTC'));layout.addRow('Updated',QLabel(row['updated']+' UTC'))
        if row['reference']:layout.addRow('Reference',QLabel(row['reference']));layout.itemAt(layout.count()-1).widget().setTextFormat(Qt.PlainText)
        original=row['details'] or json.loads(row['metadata']).get('description') or ''
        if original:
            description=QTextEdit();description.setPlainText(original);description.setReadOnly(True);description.setMaximumHeight(120);layout.addRow('Description',description)
        states=QComboBox();states.addItems(REQUEST if kind=='anime' else FEEDBACK);states.setCurrentText(row['status']);layout.addRow('Status',states)
        notes=QTextEdit();notes.setPlainText(row['notes']);layout.addRow('Notes',notes)
        if kind=='anime':
            events=store.events(row['id'])
            if events:
                timeline=QTextEdit();timeline.setReadOnly(True);timeline.setMaximumHeight(110);timeline.setPlainText('\n'.join(e['created']+' UTC · '+e['action']+' · '+str(e['previous_status'] or '')+' → '+e['status'] for e in events));layout.addRow('Decision history',timeline)
    else:
        title=QLineEdit();title.setMaxLength(200);layout.addRow('Title',title)
        category=QComboBox();category.addItems(('Anime title','Specific release','Other') if kind=='anime' else CATEGORIES);layout.addRow('Type',category)
        details=QTextEdit();layout.addRow('Description',details)
        reference=QLineEdit();reference.setMaxLength(2000);layout.addRow('HTTPS reference',reference)
        identifier=QLineEdit();identifier.setMaxLength(19)
        if kind=='anime': layout.addRow('AniList ID (optional)',identifier)
    buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addRow(buttons)
    def save():
        try:
            if row:store.update(row['id'],states.currentText(),notes.toPlainText())
            else:store.add(kind,title.text(),category.currentText(),details.toPlainText(),reference.text().strip(),identifier.text().strip() or None)
        except ValueError as exc:AniVaultDialog.alert(dialog,'Requests & Feedback',str(exc));return
        dialog.accept();window.requests_changed.emit()
    buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject);dialog.resize(480,300);dialog.exec()


def _feedback_page(window,provider=None):
    from .app import AniVaultDialog
    store=Requests(window.db)
    page=QWidget();page.setProperty('transientPage',True)
    outer=QVBoxLayout(page);outer.setContentsMargins(0,0,0,0)
    tabs=QTabWidget();outer.addWidget(tabs,1)
    renderers=[]
    tabs.tabBar().hide()
    for kind,caption in [('feedback','Feedback')]:
        tab=QWidget();tabs.addTab(tab,caption);layout=QVBoxLayout(tab)
        controls=CompactFilterLayout(38);layout.addLayout(controls)
        search=QLineEdit();search.setMinimumWidth(180);search.setPlaceholderText('Search titles…');decorate_search(search);controls.addWidget(search)
        status=QComboBox();status.addItems(('All statuses',)+(REQUEST if kind=='anime' else FEEDBACK));controls.addWidget(status)
        sort=QComboBox();sort.addItems(['Newest first','Oldest first','Title A–Z']);controls.addWidget(sort)
        add=QPushButton('New Request' if kind=='anime' else 'New Feedback');add.setObjectName('primary')
        add.clicked.connect(lambda _,k=kind:editor(window,store,k));controls.addWidget(add)
        scroll=QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
        listing=QWidget();flow=QVBoxLayout(listing);flow.setAlignment(Qt.AlignTop);scroll.setWidget(listing)
        def render(kind=kind,search=search,status=status,sort=sort,flow=flow,scroll=scroll):
            while flow.count():
                node=flow.takeAt(0).widget()
                if node:node.hide();node.deleteLater()
            rows=[r for r in store.all() if r['kind']==kind and not (r['provider_id'] and store.restricted(r['provider_id']))]
            matches=[]
            for r in rows:
                item=json.loads(r['metadata']);names=[r['title'],*(item.get('title') or {}).values(),*(item.get('synonyms') or [])]
                if not any(search.text().casefold().strip() in str(n).casefold() for n in names):continue
                if status.currentIndex() and status.currentText()!=r['status']:continue
                matches.append((r,item))
            if sort.currentIndex()==1:matches.reverse()
            if sort.currentIndex()==2:matches.sort(key=lambda x:(x[0]['title'].casefold(),x[0]['id']))
            if not matches:
                empty=QLabel('No matching entries.' if rows else 'No anime requests yet.' if kind=='anime' else 'No feedback yet.')
                empty.setObjectName('muted');flow.addWidget(empty)
                if kind=='anime' and not rows:
                    discover=QPushButton('Browse Discover');discover.clicked.connect(window.show_discover);flow.addWidget(discover,0,Qt.AlignLeft)
            for r,item in matches:
                card=QFrame();card.setObjectName('overviewStats');line=QHBoxLayout(card)
                cover=(item.get('coverImage') or {}).get('large')
                if kind=='anime':
                    art=QLabel('No art');art.setFixedSize(46,66);art.setAlignment(Qt.AlignCenter)
                    if cover:window._load_remote_artwork(cover,art,46,66)
                    line.addWidget(art)
                column=QVBoxLayout()
                name=QLabel(r['title']);name.setTextFormat(Qt.PlainText);name.setWordWrap(True);name.setObjectName('cardTitle');column.addWidget(name)
                meta=QLabel(' · '.join(str(v) for v in (r['category'],item.get('seasonYear'),r['created'][:10],r['status']) if v));meta.setTextFormat(Qt.PlainText);meta.setWordWrap(True);meta.setObjectName('muted');column.addWidget(meta)
                if r['notes']:
                    note=QLabel(r['notes'][:140]);note.setTextFormat(Qt.PlainText);note.setWordWrap(True);column.addWidget(note)
                actions=CompactFilterLayout()
                def remove(_,row=r):
                    if AniVaultDialog.confirm(window,'Remove entry','Remove this entry from Requests & Feedback?','Remove'):
                        store.remove(row['id']);window.requests_changed.emit()
                for label,fn in [('Open',lambda _,row=r:editor(window,store,row['kind'],row)),('Remove',remove)]:
                    button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
                if item.get('id'):
                    button=QPushButton('Discover');button.clicked.connect(lambda _,i=item:window.show_remote_anilist(i,'Discover'));actions.addWidget(button)
                local=store.local_match(r['provider_id'])
                if local:
                    button=QPushButton('Open local title');button.clicked.connect(lambda _,i=local:window.show_detail(i));actions.addWidget(button)
                column.addLayout(actions);line.addLayout(column,1);flow.addWidget(card)
                if provider and r['provider_id']==provider:
                    card.setStyleSheet('QFrame#overviewStats{border-color:#ff6899;}')
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0,card,lambda c=card,s=scroll:s.ensureWidgetVisible(c))
        for signal in (search.textChanged,status.currentIndexChanged,sort.currentIndexChanged):
            signal.connect(lambda *_,fn=render:fn())
        renderers.append(render)
    def refresh():
        for render in renderers:render()
    listen(window,page,refresh);refresh()
    return page


def requests_page(window,provider=None):
    from .request_queue_ui import AnimeQueue
    store=Requests(window.db);page=QWidget();page.setProperty('transientPage',True)
    outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18)
    title=QLabel('Requests & Feedback');title.setObjectName('title');outer.addWidget(title)
    hint=QLabel('Review anime requests. Approved, declined and downloaded requests move to History automatically.');hint.setObjectName('muted');hint.setWordWrap(True);outer.addWidget(hint)
    tabs=QTabWidget();queue=AnimeQueue(window,store);tabs.addTab(queue,'Anime Requests');tabs.addTab(_feedback_page(window),'Feedback');outer.addWidget(tabs,1)
    listen(window,page,queue.refresh)
    if provider:
        row=next((r for r in store.visible() if r['kind']=='anime' and r['provider_id']==provider),None)
        if row:
            queue.mode.setCurrentIndex(int(bool(row['archived'])))
            position=next((n for n,r in enumerate(queue.model.rows) if r['id']==row['id']),None)
            if position is not None:
                index=queue.model.index(position);queue.view.setCurrentIndex(index)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0,queue,lambda:queue.view.scrollTo(index))
    return page
