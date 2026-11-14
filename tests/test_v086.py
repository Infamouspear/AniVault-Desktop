import json,sqlite3,time,hashlib
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel,QPushButton,QFrame,QListWidget,QWidget
from anime_hub.database import Database
from anime_hub.organization import Organization
from anime_hub.manga_library import MangaStore
from anime_hub.manga_ui import MangaCard
from anime_hub.app import SeasonCard,Card
from test_cross_media import data,window,remote
from test_recommendations import item

def test_upgrade_copy_preserves_state_and_existing_status(data,tmp_path):
    db,store,aid,sid,book=data
    db.save_title(remote(33));db.save_title(remote(44,'MANGA'));db.save_title(remote(55,'MANGA',True),'restricted')
    db.set_manual_status('Completed',item=remote(33));store.set_status(sid,'Paused');db.set_favorite(aid,True)
    media=db.media(aid)[0];db.set_watched(media['id'],True)
    db.connection.execute('UPDATE media SET resume_position_ms=41000 WHERE id=?',(media['id'],))
    collection=db.create_collection('Existing');db.add_to_collection(collection,aid);store.add_collection(sid,collection)
    franchise=db.create_franchise('Legacy Franchise');db.add_to_franchise(franchise,aid)
    db.save_source_gallery({'source':'nhentai','external_id':'99','title':'Preserved bookmark','source_url':'https://nhentai.net/g/99/'})
    db.connection.execute("DELETE FROM settings WHERE key IN ('saved_planning_v086','restricted_saved_planning_v0881')");db.connection.commit()
    tables=['anime','media','overrides','collections','collection_items','collection_entries','franchises','franchise_items','restricted_source_saved','manga_series','manga_items']
    before={table:[tuple(row) for row in db.connection.execute('SELECT * FROM '+table)] for table in tables}
    original_saved=[tuple(row) for row in db.connection.execute("SELECT anilist_id,title,metadata_json,saved_at FROM saved_titles WHERE scope='normal'")]
    copy=tmp_path/'upgrade-copy.db';connection=sqlite3.connect(copy);db.connection.backup(connection);connection.close()
    upgraded=Database(copy)
    try:
        assert before=={table:[tuple(row) for row in upgraded.connection.execute('SELECT * FROM '+table)] for table in tables}
        org=Organization(upgraded,MangaStore(upgraded));assert org.resolve('anilist:11').status=='Planning'
        assert org.resolve('anilist:22').status=='Paused' and org.resolve('anilist:33').status=='Completed'
        assert org.resolve('anilist:44').status=='Planning'
        assert upgraded.manual_status('restricted',anilist_id=55)=='Planning' and not upgraded.saved_titles('normal')
        assert original_saved==[tuple(row) for row in upgraded.connection.execute('SELECT * FROM normal_saved_migration_archive')]
        report=upgraded.saved_planning_report;assert report=={'migrated':2,'preserved_status':2,'skipped':0}
    finally:upgraded.connection.close()
    reopened=Database(copy);assert reopened.saved_planning_report['migrated']==0;reopened.connection.close()
    assert book.read_bytes()==b'scan-only'

def test_normal_planning_ui_grouping_and_no_save(window):
    w,qt,aid,sid,_=window;w._set_status('Planning','normal',anime_id=aid);w._manga_status(sid,'Planning')
    w.show_status_list('Planning','normal');QTest.qWait(100)
    page=w.stack.currentWidget();labels=[label.text() for label in page.findChildren(QLabel)]
    assert 'Anime' in labels and 'Manga' in labels
    assert page.findChild(Card) is not None
    assert not any('Saved'==b.text() or 'Save'==b.text() for b in page.findChildren(QPushButton))
    assert 'saved' not in w.nav_buttons and 'franchises' not in w.nav_buttons
    for kind in ('ANIME','MANGA'):
        card=w._make_discover_card(remote(101,kind),{},'Discover');assert not hasattr(card,'save_button');card.deleteLater()
        w.show_remote_anilist(remote(102,kind),'Discover');qt.processEvents()
        assert not any(b.text() in {'Save','Saved','Remove from Saved'} for b in w.stack.currentWidget().findChildren(QPushButton))
    w.db.set_setting('restricted_unlocked','1')
    card=w._make_discover_card(remote(103,'MANGA',True),{},'Restricted',scope='restricted');assert not hasattr(card,'save_button');card.deleteLater()

def test_related_one_hop_routing_scope_and_cache(window,monkeypatch):
    w,qt,aid,sid,_=window;requests=[]
    nodes=[remote(11),remote(22,'MANGA'),remote(99),remote(66,'MANGA',True)]
    result={'edges':[{'relationType':'SOURCE' if node['type']=='MANGA' else 'SEQUEL','node':node} for node in nodes]+[{'node':nodes[1]},None]}
    def submit(key,operation,success,failure):requests.append(key);success(result)
    monkeypatch.setattr(w,'_submit_discover_job',submit)
    panel=w._related_panel(remote(77));panel.show();qt.processEvents()
    cards={card.findChild(QLabel,'cardTitle').toolTip():card for card in [*panel.findChildren(Card),*panel.findChildren(SeasonCard),*panel.findChildren(MangaCard)]}
    assert set(cards)>={'Shared 11','Shared 22','Shared 99'} and 'Shared 66' not in cards
    labels=[label.text() for label in panel.findChildren(QLabel)];assert any('Manga' in text and 'Source' in text for text in labels)
    monkeypatch.setattr(w,'show_detail',lambda i:requests.append(('anime',i)));monkeypatch.setattr(w,'show_manga_detail',lambda i:requests.append(('manga',i)));monkeypatch.setattr(w,'show_remote_anilist',lambda node,source:requests.append(('remote',node['id'],source)))
    for name in ('Shared 11','Shared 22','Shared 99'):QTest.mouseDClick(cards[name],Qt.LeftButton)
    assert requests[1:]==[('anime',aid),('manga',sid),('remote',99,'Discover')]
    count=len(requests);other=w._related_panel(remote(77));assert len(requests)==count
    panel.deleteLater();other.deleteLater()

def test_related_inflight_failure_fans_out_and_deleted_panel_safe(window,monkeypatch):
    w,qt,*_=window;pending=[]
    monkeypatch.setattr(w,'_submit_discover_job',lambda *args:pending.append(args))
    first=w._related_panel(remote(77));second=w._related_panel(remote(77));assert len(pending)==1
    first.deleteLater();QTest.qWait(10);pending[0][3](TimeoutError('fixture'))
    assert any('temporarily unavailable' in label.text() for label in second.findChildren(QLabel))
    assert not w._detail_relation_inflight;second.deleteLater()

def test_large_extras_stays_separate_from_related(window,monkeypatch,tmp_path):
    w,qt,aid,*_=window;files=[]
    for index in range(35):
        path=tmp_path/f'Artwork {index}.png';path.write_bytes(b'unchanged');files.append(path)
        w.db.upsert_media(aid,SimpleNamespace(path=path,kind='artwork',season=None,episode=None))
    monkeypatch.setattr(w,'_submit_discover_job',lambda key,operation,success,failure:success({'edges':[]}))
    w.show_detail(aid);QTest.qWait(100)
    page=w.stack.currentWidget();trees=page.findChildren(QListWidget)
    assert len(trees)==2 and any('Extras'==label.text() for label in page.findChildren(QLabel))
    assert any(frame.property('relatedPanel') for frame in page.findChildren(QFrame))
    def leaves(tree):return sum(bool(tree.item(j).data(Qt.UserRole)) for j in range(tree.count()))
    assert max(leaves(tree) for tree in trees)>=35
    assert all(path.read_bytes()==b'unchanged' for path in files)

def test_manga_and_anime_reasons_are_visible_and_keep_metadata(window):
    w,qt,aid,sid,_=window
    w.manga_store.match(sid,item(22,'Drama','MANGA'));w.manga_store.set_status(sid,'Watching')
    ranked=w._rank_recommendations(w._recommendation_profile('normal','MANGA'),[item(103,'Drama','MANGA')])
    card=w._make_discover_card(ranked[0],{},'Discover');card.show();QTest.qWait(50)
    reason=card.findChild(QLabel,'recommendationReason');assert reason and reason.isVisible() and 'reading' in reason.text()
    assert any('AniList' in label.text() for label in card.findChildren(QLabel))
    other=w._make_discover_card({**remote(104),'_recommendation_reason':'Similar to a title in Favorites'}, {},'Discover');assert other.findChild(QLabel,'recommendationReason')
    card.deleteLater();other.deleteLater()

def test_fullscreen_reader_player_chrome_and_geometry(window):
    w,qt,*_=window;w.resize(720,640);w.move(20,25);QTest.qWait(50);original=w.geometry()
    class Viewer(QWidget):
        def __init__(self):super().__init__(w);self.canvas=self;self.values=[]
        def set_fullscreen(self,value):self.values.append(value)
        def set_fullscreen_mode(self,value):self.values.append(value)
        def shutdown(self):pass
    for kind in ('reader','player'):
        viewer=Viewer();setattr(w,'manga_reader_page' if kind=='reader' else 'player_page',viewer)
        toggle=w._toggle_reader_fullscreen if kind=='reader' else w._toggle_player_fullscreen
        try:
            toggle();QTest.qWait(100)
            assert w.isFullScreen() and all(not handle.isVisible() for handle in w.resize_handles) and not w.title_bar.isVisible()
            w.toggle_maximize();assert w.isFullScreen()
            toggle();QTest.qWait(100)
            assert not w.isFullScreen() and w.geometry()==original and all(handle.isVisible() for handle in w.resize_handles)
        finally:
            if w.isFullScreen():toggle()
            setattr(w,'manga_reader_page' if kind=='reader' else 'player_page',None);viewer.deleteLater()

def test_restricted_home_reuse_and_lock(window,monkeypatch):
    w,qt,*_=window;requests=[];w.db.set_setting('restricted_unlocked','1');application_style=qt.styleSheet()
    monkeypatch.setattr(w,'_request_discover_page',lambda params,success,failure:(requests.append(params),success({'items':[]})))
    w.show_restricted_home();qt.processEvents();page=w.stack.currentWidget();count=len(requests)
    w.show_home();w.show_restricted_home();qt.processEvents()
    assert w.stack.currentWidget() is page and len(requests)==count
    w.lock_restricted();assert not w.current_view.startswith('restricted') and not w.restricted_button.isVisible()
    assert all(params.get('is_adult') is True for params in requests)
    assert qt.styleSheet()==application_style and w.property('restrictedTheme') is False

def test_downloads_page_persistent_widgets_and_pause_controls(window,tmp_path):
    w,qt,*_=window;w.show_downloads();qt.processEvents();page=w.stack.currentWidget()
    assert any('No downloads' in label.text() for label in page.findChildren(QLabel))
    w.downloads.closed=True
    i=w.downloads.add('https://example.invalid/file',tmp_path/'direct')
    w.downloads._update(i,state='Downloading',downloaded=50,total=100,resumable=0)
    qt.processEvents();pause=next(b for b in page.findChildren(QPushButton) if b.text()=='Pause');assert not pause.isEnabled()
    assert any('50%' in label.text() for label in page.findChildren(QLabel))
    w.show_home();w.show_downloads();assert w.stack.currentWidget() is page
