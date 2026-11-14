import io
import hashlib
import zipfile
import pytest
from PIL import Image
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent,QMouseEvent
from PySide6.QtWidgets import QApplication,QPushButton,QComboBox,QLabel
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.local_manga_reader import LocalMangaReader
from anime_hub.manga_library import MangaStore,scan_manga,parse_numbers
from anime_hub.manga_state import ReaderStore
from anime_hub.reading_settings import ReadingSettings
from test_local_manga_reader import ready,wait

@pytest.fixture(scope='module')
def qt():return QApplication.instance() or QApplication([])

def make_book(path,count=5):
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=io.BytesIO();Image.new('RGB',(400,650),'coral').save(stream,'PNG')
    with zipfile.ZipFile(path,'w') as archive:
        for page in range(count):archive.writestr(f'{page+1}.png',stream.getvalue())
    return path

@pytest.fixture
def reader(qt,tmp_path):
    path=make_book(tmp_path/'book.cbz');db=Database(tmp_path/'db');r=LocalMangaReader(db,path,tmp_path/'cache')
    r.resize(1100,800);r.show();r.start();ready(qt,r)
    yield r
    r.shutdown();r.close();db.connection.close();qt.processEvents()

@pytest.mark.parametrize('direction,spread',[('LTR',False),('RTL',False),('LTR',True),('RTL',True)])
def test_actual_page_click_regions(qt,reader,direction,spread):
    reader.direction.setCurrentIndex(reader.direction.findData(direction));reader.spread.setChecked(spread);reader.go(1);ready(qt,reader)
    start=reader.page;viewport=reader.scroll.viewport()
    forward=QPoint(int(viewport.width()*(.2 if direction=='RTL' else .8)),viewport.height()//2)
    QTest.mouseClick(reader.canvas,Qt.LeftButton,pos=reader.canvas.mapFrom(viewport,forward));ready(qt,reader)
    assert reader.page==(3 if spread else 2)
    backward=QPoint(int(viewport.width()*(.8 if direction=='RTL' else .2)),viewport.height()//2)
    QTest.mouseClick(reader.canvas,Qt.LeftButton,pos=reader.canvas.mapFrom(viewport,backward));ready(qt,reader)
    # go() targets a page in the previous spread; visible pair is restored.
    assert reader.visible_indices()==([1,2] if spread else [start])
    before=reader.page;QTest.mouseClick(reader.canvas,Qt.LeftButton,pos=reader.canvas.mapFrom(viewport,viewport.rect().center()));assert reader.page==before

def test_toolbar_reclaims_viewport_and_keyboard_stays_live(qt,reader):
    before=reader.scroll.viewport().height();page_height=reader.canvas.targets[0].height()
    reader.canvas.setFocus();QTest.keyClick(reader.canvas,Qt.Key_T);qt.processEvents()
    assert reader.toolbar.isHidden();assert reader.scroll.viewport().height()>before
    assert reader.canvas.targets[0].height()>page_height
    assert reader.db.setting('reader_toolbar')=='0'
    QTest.keyClick(reader.canvas,Qt.Key_Left);ready(qt,reader);assert reader.page==1
    QTest.keyClick(reader.canvas,Qt.Key_P);assert reader.mode.currentText()=='Fit Page'
    QTest.keyClick(reader.canvas,Qt.Key_B);assert reader.store.bookmarks(reader.identity)==[2]
    QTest.keyClick(reader.canvas,Qt.Key_T);qt.processEvents();assert not reader.toolbar.isHidden()

def test_wheel_zooms_without_turning_and_drag_never_turns(qt,reader):
    before=hashlib.sha256(open(reader.path,'rb').read()).digest();page=reader.page
    reader.reset_zoom();viewport=reader.scroll.viewport()
    wheel=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    QApplication.sendEvent(reader.canvas,wheel);assert reader.zoom>1;assert reader.page==page
    reader.zoom_by(3);qt.processEvents();bar=reader.scroll.verticalScrollBar();bar.setValue(100)
    press=QPoint(150,200);QTest.mousePress(reader.canvas,Qt.LeftButton,pos=press);initial=reader.canvas.drag;value=bar.value()
    move=QMouseEvent(QMouseEvent.MouseMove,QPointF(150,130),initial-QPointF(0,70),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(reader.canvas,move);assert bar.value()>value
    QTest.mouseRelease(reader.canvas,Qt.LeftButton,pos=QPoint(150,130));assert reader.page==page
    assert hashlib.sha256(open(reader.path,'rb').read()).digest()==before

def test_reading_settings_persist_separate_from_book_state(qt,tmp_path):
    path=tmp_path/'db';db=Database(path);settings=ReadingSettings(db)
    settings.direction.setCurrentIndex(1);settings.spread.setCurrentIndex(1);settings.cover.setChecked(False);settings.toolbar.setChecked(False);settings.fit.setCurrentText('Fit Width');settings.save()
    assert db.connection.execute('SELECT COUNT(*) FROM manga_reader_state').fetchone()[0]==0
    db.connection.close();db=Database(path);restored=ReadingSettings(db)
    assert restored.direction.currentData()=='LTR';assert restored.spread.currentIndex()==1;assert not restored.cover.isChecked();assert not restored.toolbar.isChecked();assert restored.fit.currentText()=='Fit Width'
    book=make_book(tmp_path/'book.cbz');r=LocalMangaReader(db,book,tmp_path/'cache');r.show();r.start();ready(qt,r)
    assert r.direction.currentData()=='LTR' and r.spread.isChecked() and not r.cover.isChecked() and r.toolbar.isHidden()
    r.shutdown();r.close();db.connection.close()

def test_settings_live_page_and_reader_fullscreen(qt,tmp_path,monkeypatch):
    from anime_hub import app
    monkeypatch.setattr(app,'APP_DIR',tmp_path/'app');monkeypatch.setattr(app,'_append_playback_log',lambda *args:None)
    monkeypatch.setattr(app.AniVaultDialog,'alert',lambda *args:None)
    w=app.Window();w.resize(900,950);w.show();w.show_settings();page=w.stack.currentWidget();settings=page.findChild(ReadingSettings)
    from PySide6.QtWidgets import QScrollArea
    qt.processEvents();scroll=page.findChild(QScrollArea);assert scroll.horizontalScrollBar().maximum()==0
    assert settings is not None;settings.toolbar.setChecked(False)
    next(b for b in page.findChildren(QPushButton) if b.text()=='Save Settings').click();assert w.db.setting('reader_toolbar')=='0'
    book=make_book(tmp_path/'book.cbz');w.open_local_manga(book);r=w.manga_reader_page;ready(qt,r)
    r.canvas.setFocus();QTest.keyClick(r.canvas,Qt.Key_F);qt.processEvents();assert w.isFullScreen() and r.header_widget.isHidden() and r.toolbar.isHidden()
    QTest.keyClick(r.canvas,Qt.Key_Escape);qt.processEvents();assert not w.isFullScreen() and not r.header_widget.isHidden()
    w.close();qt.processEvents()

def test_completion_logs_once_and_reopen_persists(qt,tmp_path):
    book=make_book(tmp_path/'book.cbz');db=Database(tmp_path/'db');r=LocalMangaReader(db,book,tmp_path/'cache');logs=[];r.diagnostic.connect(logs.append);r.show();r.start();ready(qt,r)
    r.go(4);ready(qt,r)
    for _ in range(10):r.present()
    assert logs.count('ReaderComplete')==1;r.shutdown();r.close();db.connection.close()
    db=Database(tmp_path/'db');r=LocalMangaReader(db,book,tmp_path/'cache');r.diagnostic.connect(logs.append);r.show();r.start();ready(qt,r)
    assert r.completed and r.page==4;assert logs.count('ReaderComplete')==1;r.shutdown();r.close();db.connection.close()

@pytest.mark.parametrize('name,expected',[
    ('[Group c99] A Title v02 [Digital].cbz',(2,None)),
    ('Manga [Collector Edition v2].cbz',(None,None)),
    ('Manga (2026 Edition).pdf',(None,None)),
    ('Manga v1080.cbz',(None,None)),
    ('Manga Chapter 12.5.cbz',(None,12.5)),
    ('Manga [c012].cbz',(None,12)),
])
def test_annotation_numbers_are_not_manga_numbers(name,expected):assert parse_numbers(name)[:2]==expected

def test_loose_volume_grouping_and_existing_identity_preservation(tmp_path):
    root=tmp_path/'Manga';first=make_book(root/'[Group A] Example v01.cbz');second=make_book(root/'[Group B] Example v02.cbz')
    db=Database(tmp_path/'db');store=MangaStore(db);store.add_root(root);result=scan_manga(store.roots());assert len(result['series'])==1
    store.reconcile(result);sid=store.series_list()[0]['id'];store.set_favorite(sid,True);store.set_status(sid,'Planning');cid=db.create_collection('Comics');store.add_collection(sid,cid)
    db.connection.execute('UPDATE manga_series SET identity=? WHERE id=?',('old-parser-identity',sid));db.connection.commit()
    store.reconcile(result);assert store.series_list()[0]['id']==sid;assert store.series(sid)['favorite'];assert store.series(sid)['manual_status']=='Planning';assert db.collection_entries(cid)[0]['entity_key']==f'manga:{sid}'
    assert store.reconcile(scan_manga(store.roots()))['new']==0;db.connection.close()

def test_continue_recent_cards_open_the_active_item(qt,tmp_path,monkeypatch):
    from anime_hub import app
    from anime_hub.manga_ui import MangaCard
    monkeypatch.setattr(app,'APP_DIR',tmp_path/'app');monkeypatch.setattr(app,'_append_playback_log',lambda *args:None)
    root=tmp_path/'Manga';make_book(root/'Series'/'Vol1.cbz');make_book(root/'Series'/'Vol2.cbz');make_book(root/'Untouched'/'Vol1.cbz')
    w=app.Window();w.show();w.manga_store.add_root(root);w.manga_store.reconcile(scan_manga(w.manga_store.roots()));sid=next(r['id'] for r in w.manga_store.series_list() if r['title']=='Series');items=w.manga_store.items(sid)
    rs=ReaderStore(w.db);s=rs.open(items[1]['path'],'normal','cbz',5,items[1]['reader_identity']);rs.save(s['identity'],3,5)
    w.show_manga_library(filter='Continue Reading');qt.processEvents();cards=w.stack.currentWidget().findChildren(MangaCard);assert len(cards)==1;assert 'Page 3 / 5' in cards[0].row['active_label']
    QTest.mouseClick(cards[0],Qt.LeftButton);assert w.manga_reader_page is None
    cards[0].findChild(QPushButton,'mangaContinue').click();r=w.manga_reader_page;ready(qt,r);assert r.path==items[1]['path'] and r.page==2
    w.show_manga_library(filter='Recently Read');qt.processEvents();assert len(w.stack.currentWidget().findChildren(MangaCard))==1
    # Changing Favorite updates the same widget rather than rebuilding the page.
    page=w.stack.currentWidget();card=page.findChild(MangaCard);w._manga_favorite(sid);assert w.stack.currentWidget() is page and card.row['favorite']
    w.close();qt.processEvents()

def test_cover_priority_local_then_anilist_then_generated(qt,tmp_path,monkeypatch):
    from anime_hub import app
    monkeypatch.setattr(app,'APP_DIR',tmp_path/'app');monkeypatch.setattr(app,'_append_playback_log',lambda *args:None)
    root=tmp_path/'Manga';book=make_book(root/'Series'/'Vol1.cbz');w=app.Window();w.manga_store.add_root(root);w.manga_store.reconcile(scan_manga(w.manga_store.roots()));row=w.manga_store.series_list()[0]
    row.update(anilist_id=1,metadata_json='{"coverImage":{"large":"https://example.invalid/cover.jpg"}}')
    cached=app.APP_DIR/'cache'/'manga_covers'/'anilist-1.png';cached.parent.mkdir(parents=True);Image.new('RGB',(100,150),'green').save(cached)
    generated=tmp_path/'generated.png';Image.new('RGB',(100,150),'blue').save(generated);row['cover_path']=str(generated)
    label=QLabel();label.resize(100,150);w._load_manga_cover(row,label);assert label.pixmap().toImage().pixelColor(0,0).name()=='#008000'
    local=book.parent/'cover.png';Image.new('RGB',(100,150),'red').save(local);w._load_manga_cover(row,label);assert label.pixmap().toImage().pixelColor(0,0).name()=='#ff0000'
    manual=tmp_path/'manual.png';Image.new('RGB',(100,150),'yellow').save(manual);row['manual_cover_path']=str(manual);w._load_manga_cover(row,label);assert label.pixmap().toImage().pixelColor(0,0).name()=='#ffff00'
    w.close();qt.processEvents()

def test_normalization_does_not_orphan_distinct_existing_groups(tmp_path):
    root=tmp_path/'Manga';make_book(root/'[A] Title v01.cbz');make_book(root/'[B] Title v02.cbz')
    db=Database(tmp_path/'db');store=MangaStore(db);store.add_root(root);result=scan_manga(store.roots());series=next(iter(result['series'].values()))
    legacy={**result,'series':{}}
    for n,item in enumerate(series['items']):legacy['series'][str(n)]={**series,'identity':str(n),'title':f'Legacy {n}','items':[item]}
    store.reconcile(legacy);original={r['id'] for r in store.series_list()};cid=db.create_collection('Keep')
    for sid in original:store.add_collection(sid,cid);store.set_status(sid,'Paused')
    summary=store.reconcile(result);assert summary['preserved_group_conflicts']==1
    assert {r['id'] for r in store.series_list()}==original;assert len(db.collection_entries(cid))==2
    assert all(r['manual_status']=='Paused' and r['item_count']==1 for r in store.series_list());assert store.reconcile(result)['new']==0
    db.connection.close()
