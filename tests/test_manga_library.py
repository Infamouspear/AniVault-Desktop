import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QPushButton,QListWidget,QDialog
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.manga_library import MangaStore,scan_manga,parse_numbers
from anime_hub.manga_state import ReaderStore,item_identity

@pytest.fixture(scope='module')
def qt():return QApplication.instance() or QApplication([])

def wait(qt,predicate,seconds=6):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        qt.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Manga runtime operation timed out')

def picture(color='coral'):
    buffer=io.BytesIO();Image.new('RGB',(250,380),color).save(buffer,'PNG');return buffer.getvalue()

def cbz(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'w') as archive:
        for i in [1,2,10]:archive.writestr(f'{i}.png',picture())

@pytest.fixture
def library(tmp_path):
    root=tmp_path/'Manga';root.mkdir()
    for name in ['Berserk/Vol. 02.cbz','Berserk/Vol. 01.cbz','Nested/Volume 01/Chapter 12.5.cbz','Nested/Volume 01/Chapter 7.1.cbz','Loose v01.cbz','Loose v02.cbz']:cbz(root/name)
    for relative in ['Image Series/Chapter 001','Image Series/Chapter 002','Pages Series/pages']:
        folder=root/relative;folder.mkdir(parents=True)
        for i in range(1,4):(folder/f'{i}.png').write_bytes(picture())
    pdf=root/'PDF Series'/'chapter_001.pdf';pdf.parent.mkdir();Image.new('RGB',(200,300),'white').save(pdf,save_all=True,append_images=[Image.new('RGB',(200,300),'coral')])
    cbr=root/'RAR Series'/'Vol1.cbr';cbr.parent.mkdir();cbr.write_bytes(b'index without opening archive')
    return root

@pytest.mark.parametrize('name,expected',[
    ('Vol 1.cbz',(1,None)),('Vol. 01.cbz',(1,None)),('Volume 1',(1,None)),('v01.cbz',(1,None)),
    ('Ch 1.cbz',(None,1)),('Ch. 001',(None,1)),('Chapter 12',(None,12)),('c012',(None,12)),
    ('001',(None,1)),('12.5',(None,12.5)),('Chapter 7.1.pdf',(None,7.1)),
    ('2026',(None,None)),('1080',(None,None)),('Release 2026 1080p',(None,None))])
def test_tolerant_number_parsing(name,expected):assert parse_numbers(name)[:2]==expected

def test_scan_grouping_sort_and_source_safety(library,tmp_path):
    before={str(p):hashlib.sha256(p.read_bytes()).digest() for p in library.rglob('*') if p.is_file()}
    db=Database(tmp_path/'db');store=MangaStore(db);rid=store.add_root(library);assert store.add_root(library)==rid
    result=scan_manga(store.roots());summary=store.reconcile(result)
    assert summary['series']==7;assert summary['items']==11
    titles={r['title']:r for r in store.series_list()}
    assert titles['Berserk']['item_count']==2
    assert [i['volume'] for i in store.items(titles['Berserk']['id'])]==[1,2]
    assert [i['chapter'] for i in store.items(titles['Nested']['id'])]==[7.1,12.5]
    assert titles['Image Series']['item_count']==2
    assert store.items(titles['RAR Series']['id'])[0]['source_type']=='cbr'
    assert store.reconcile(scan_manga(store.roots()))['new']==0
    assert before=={str(p):hashlib.sha256(p.read_bytes()).digest() for p in library.rglob('*') if p.is_file()}
    db.connection.close()

def test_reader_state_adoption_missing_and_restart(library,tmp_path):
    path=tmp_path/'db';db=Database(path);rs=ReaderStore(db);book=library/'Berserk'/'Vol. 01.cbz'
    state=rs.open(book,'normal','cbz',3);rs.save(state['identity'],2,3);rs.toggle_bookmark(state['identity'],2)
    store=MangaStore(db);store.add_root(library);store.reconcile(scan_manga(store.roots()));row=next(r for r in store.series_list() if r['title']=='Berserk');sid=row['id']
    item=next(i for i in store.items(sid) if i['volume']==1);assert item['reader_identity']==state['identity'];assert item['current_page']==2
    store.set_status(sid,'Paused');store.set_favorite(sid,True);cid=db.create_collection('Manga');assert store.add_collection(sid,cid);assert not store.add_collection(sid,cid)
    store.match(sid,{'id':2,'type':'MANGA','isAdult':False,'title':{'romaji':'Berserk'}})
    book.unlink();summary=store.reconcile(scan_manga(store.roots()));assert summary['removed']==1
    item=store.item(item['id']);assert not item['present'];assert rs.bookmarks(item['reader_identity'])==[2]
    db.connection.close();db=Database(path);store=MangaStore(db);row=store.series(sid)
    assert (row['favorite'],row['manual_status'],row['anilist_id'])==(1,'Paused',2)
    assert f'manga:{sid}'==db.collection_entries(cid)[0]['entity_key']
    cbz(book);store.reconcile(scan_manga(store.roots()));assert store.series(sid)['item_count']==2
    assert ReaderStore(db).bookmarks(item['reader_identity'])==[2];db.connection.close()

def test_scopes_roots_collections_and_progress(library,tmp_path):
    db=Database(tmp_path/'db');store=MangaStore(db);store.add_root(library);store.reconcile(scan_manga(store.roots()));row=store.series_list()[0];sid=row['id'];item=store.items(sid)[0]
    rs=ReaderStore(db);state=rs.open(item['path'],'normal',item['source_type'],3);rs.save(state['identity'],2,3);rs.toggle_bookmark(state['identity'],2)
    store.set_status(sid,'Planning');cid=db.create_collection('Private Reads');store.add_collection(sid,cid)
    store.set_scope(sid,'restricted')
    assert store.series(sid,'normal') is None;assert store.series(sid,'restricted')['manual_status']=='Planning'
    assert not db.collection_entries(cid)
    assert any(c['item_count']==1 for c in db.collections(scope='restricted'))
    with pytest.raises(ValueError):store.add_collection(sid,cid)
    state=rs.open(item['path'],'restricted',item['source_type'],3,item['reader_identity']);assert state['current_page']==2;assert rs.bookmarks(state['identity'])==[2]
    store.reconcile(scan_manga(store.roots()));assert store.series(sid)['scope']=='restricted'
    store.set_scope(sid,'normal');assert store.series(sid)['manual_status']=='Planning'
    with pytest.raises(ValueError):store.add_root(library/'Berserk')
    db.set_setting('library_root',str(tmp_path/'Anime'));(tmp_path/'Anime').mkdir()
    with pytest.raises(ValueError):store.add_root(tmp_path/'Anime')
    db.connection.close()

def test_anilist_type_and_explicit_adult_only(library,tmp_path):
    db=Database(tmp_path/'db');store=MangaStore(db);store.add_root(library);store.reconcile(scan_manga(store.roots()));sid=store.series_list()[0]['id']
    with pytest.raises(ValueError):store.match(sid,{'id':3,'type':'ANIME'})
    store.match(sid,{'id':4,'type':'MANGA','isAdult':False,'genres':['Ecchi']});assert store.series(sid)['scope']=='normal'
    store.match(sid,{'id':5,'type':'MANGA','isAdult':True});assert store.series(sid)['scope']=='restricted'
    with pytest.raises(ValueError):store.set_scope(sid,'normal')
    store.unmatch(sid);store.set_scope(sid,'normal');db.connection.close()

def test_nested_containers_do_not_merge_unrelated_titles(tmp_path):
    root=tmp_path/'Comics';cbz(root/'Publisher'/'Different A'/'Vol 1.cbz');cbz(root/'Publisher'/'Different B'/'Vol 1.cbz')
    result=scan_manga([{'id':1,'path':str(root),'scope':'normal'}]);assert {s['title'] for s in result['series'].values()}=={'Different A','Different B'}

def test_direct_series_root_mixes_volume_and_image_chapters(tmp_path):
    root=tmp_path/'A Title';cbz(root/'Vol 1.cbz');pages=root/'Chapter 002';pages.mkdir();(pages/'1.png').write_bytes(picture())
    result=scan_manga([{'id':1,'path':str(root),'scope':'normal'}]);assert len(result['series'])==1;assert len(next(iter(result['series'].values()))['items'])==2

def test_unavailable_root_does_not_mark_everything_missing(library,tmp_path):
    db=Database(tmp_path/'db');store=MangaStore(db);store.add_root(library);store.reconcile(scan_manga(store.roots()))
    roots=store.roots();roots[0]['path']=str(tmp_path/'nonexistent');result=scan_manga(roots);assert result['errors'];assert not result['roots_done']
    summary=store.reconcile(result);assert summary['removed']==0;assert all(r['available_count'] for r in store.series_list());db.connection.close()

def test_adopts_restricted_reader_state_without_privacy_leak(tmp_path):
    root=tmp_path/'Manga';book=root/'Private Title'/'Vol 1.cbz';cbz(book)
    db=Database(tmp_path/'db');rs=ReaderStore(db);state=rs.open(book,'restricted','cbz',3);rs.save(state['identity'],2,3);rs.toggle_bookmark(state['identity'],2)
    store=MangaStore(db);store.add_root(root);store.reconcile(scan_manga(store.roots()))
    assert store.series_list('normal')==[];row=store.series_list('restricted')[0];item=store.items(row['id'])[0]
    assert item['reader_identity']==state['identity'];assert item['current_page']==2;assert rs.bookmarks(item['reader_identity'])==[2]
    db.connection.close()

def test_restricted_root_adopts_normal_reader_progress(tmp_path):
    root=tmp_path/'Private Manga';book=root/'A Title'/'Vol 1.cbz';cbz(book)
    db=Database(tmp_path/'db');rs=ReaderStore(db);state=rs.open(book,'normal','cbz',3);rs.save(state['identity'],2,3)
    store=MangaStore(db);store.add_root(root,'restricted');store.reconcile(scan_manga(store.roots()))
    item=store.items(store.series_list('restricted')[0]['id'])[0];assert item['reader_identity']==state['identity'];assert item['current_page']==2
    db.connection.close()

def test_root_cannot_include_anivault_owned_cache(tmp_path):
    owned=tmp_path/'app';(owned/'cache').mkdir(parents=True);db=Database(owned/'db');store=MangaStore(db,owned)
    for candidate in (owned,owned/'cache',tmp_path):
        with pytest.raises(ValueError,match='app data'):store.add_root(candidate)
    db.connection.close()

def test_live_ui_scan_reader_thumbnail_and_collections(qt,library,tmp_path,monkeypatch):
    from anime_hub import app as app_module
    from anime_hub.manga_ui import MangaCard
    monkeypatch.setattr(app_module,'APP_DIR',tmp_path/'app');logs=[];monkeypatch.setattr(app_module,'_append_playback_log',logs.append)
    window=app_module.Window();window.show();QTest.mouseClick(window.nav_buttons['manga'],Qt.LeftButton);qt.processEvents();assert window.current_view=='manga_library'
    # Exercise the actual root manager dialog and its Add Root action.
    monkeypatch.setattr(app_module.QFileDialog,'getExistingDirectory',lambda *a,**k:str(library))
    def add_root():
        dialog=QApplication.activeModalWidget();assert dialog is not None
        next(b for b in dialog.findChildren(QPushButton) if b.text()=='Add Root…').click()
        next(b for b in dialog.findChildren(QPushButton) if b.text()=='Done').click()
    QTimer.singleShot(30,add_root);window.manage_manga_roots();assert len(window.manga_store.roots())==1
    window.scan_manga_library();wait(qt,lambda:len(window.manga_store.series_list())==7)
    wait(qt,lambda:len(window.stack.currentWidget().findChildren(MangaCard))==7)
    row=next(r for r in window.manga_store.series_list() if r['title']=='Berserk');sid=row['id']
    wait(qt,lambda:window.manga_store.series(sid)['cover_path'] is not None)
    window.resize(2560,1000);qt.processEvents();grid=window.stack.currentWidget().findChild(app_module.ResponsiveLibraryGrid);assert grid._columns>=7
    window.show_manga_detail(sid);item=window.manga_store.continue_item(sid)
    next(b for b in window.stack.currentWidget().findChildren(QPushButton) if b.text()=='Open / Continue Selected').click();reader=window.manga_reader_page
    wait(qt,lambda:reader.total==3 and bool(reader.canvas.images));assert reader.direction.currentText()=='Right-to-Left (Manga)'
    reader.go(1);wait(qt,lambda:bool(reader.canvas.images));reader.toggle_bookmark();reader.go(2);wait(qt,lambda:reader.completed)
    window._leave_local_reader();qt.processEvents();assert window.current_view=='manga_detail'
    assert window.manga_store.series(sid)['completed_count']==1
    assert ReaderStore(window.db).bookmarks(item['reader_identity'])==[2]
    cid=window.db.create_collection('Books');window.manga_store.add_collection(sid,cid);window.show_collection_detail(cid)
    assert len(window.stack.currentWidget().findChildren(MangaCard))==1
    window._manga_status(sid,'Planning');window.show_status_list('Planning');assert len(window.stack.currentWidget().findChildren(MangaCard))==1
    window.db.set_setting('restricted_unlocked','1');window.manga_store.set_scope(sid,'restricted');window.show_manga_library();assert sid not in [c.row['id'] for c in window.stack.currentWidget().findChildren(MangaCard)]
    window.show_manga_library('restricted');assert [c.row['id'] for c in window.stack.currentWidget().findChildren(MangaCard)]==[sid]
    window.open_manga_item(item['id']);reader=window.manga_reader_page;wait(qt,lambda:reader.total==3)
    assert reader.page==2;assert reader.completed
    window.lock_restricted();qt.processEvents();assert window.manga_reader_page is None;assert not window.current_view.startswith('restricted')
    window.open_local_manga(item['path'],'normal');assert window.manga_reader_page is None
    assert any('MangaScanSummary' in log for log in logs)
    window.close();qt.processEvents()

def test_actual_manga_match_dialog_uses_manga_query(qt,library,tmp_path,monkeypatch):
    from anime_hub import app as app_module,manga_ui
    monkeypatch.setattr(app_module,'APP_DIR',tmp_path/'app');monkeypatch.setattr(app_module,'_append_playback_log',lambda *a:None)
    requests=[]
    def fetch(**kwargs):
        requests.append(kwargs);return {'items':[{'id':123,'type':'MANGA','title':{'romaji':'Manga Match'},'isAdult':False,'genres':['Drama']}]}
    monkeypatch.setattr(manga_ui,'fetch_discover_page',fetch)
    window=app_module.Window();window.show();window.manga_store.add_root(library);window.manga_store.reconcile(scan_manga(window.manga_store.roots()));row=window.manga_store.series_list()[0]
    timer=QTimer();timer.setInterval(30)
    def choose():
        dialog=QApplication.activeModalWidget()
        if dialog is None:return
        listing=dialog.findChild(QListWidget)
        if listing is not None and listing.count():
            listing.setCurrentRow(0);timer.stop();next(b for b in dialog.findChildren(QPushButton) if b.text()=='Use Selected Match').click()
    timer.timeout.connect(choose);timer.start();QTimer.singleShot(5000,lambda:QApplication.activeModalWidget().reject() if QApplication.activeModalWidget() else None)
    window.match_manga(row['id']);timer.stop();assert requests and requests[0]['media_type']=='MANGA';assert window.manga_store.series(row['id'])['anilist_id']==123
    window.close();qt.processEvents()
