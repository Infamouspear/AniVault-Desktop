import hashlib
import io
import time
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.manga_sources import open_source, ReaderSourceError, natural_key
from anime_hub.manga_state import ReaderStore, item_identity
from anime_hub.local_manga_reader import LocalMangaReader, PageCache, spread_indices

@pytest.fixture(scope='module')
def qt():
    return QApplication.instance() or QApplication([])

def image_bytes(color='coral',format='PNG'):
    stream=io.BytesIO();Image.new('RGB',(300,450),color).save(stream,format=format);return stream.getvalue()

@pytest.fixture
def book(tmp_path):
    path=tmp_path/'book.cbz'
    with zipfile.ZipFile(path,'w') as archive:
        for name,color in [('10.png','blue'),('2.png','green'),('1.png','red')]:archive.writestr(name,image_bytes(color))
        archive.writestr('readme.txt','ignored');archive.writestr('__MACOSX/._1.png',b'ignored')
    return path

def wait(qt,predicate,seconds=5):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        qt.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Reader runtime condition timed out')

def ready(qt,reader):
    wait(qt,lambda:reader.total>0 and len(reader.canvas.images)==len(reader.visible_indices()))

def test_cbz_direct_natural_order_and_source_safety(qt,book,tmp_path):
    before=(book.read_bytes(),book.stat().st_mtime_ns)
    source=open_source(book,tmp_path/'cache')
    assert [p.filename for p in source.pages]==['1.png','2.png','10.png']
    assert source.image(0).pixelColor(0,0).name()=='#ff0000'
    source.close();assert before==(book.read_bytes(),book.stat().st_mtime_ns)
    assert sorted(p.name for p in tmp_path.iterdir())==['book.cbz']

def test_image_folder_nonrecursive_formats(qt,tmp_path):
    folder=tmp_path/'images';folder.mkdir()
    for name,fmt in [('10.webp','WEBP'),('2.jpg','JPEG'),('1.png','PNG')]: (folder/name).write_bytes(image_bytes(format=fmt))
    (folder/'nested').mkdir();(folder/'nested'/'0.png').write_bytes(image_bytes())
    (folder/'note.txt').write_text('unrelated')
    source=open_source(folder,tmp_path/'cache');assert source.count==3
    assert [p.name for p in source.pages]==['1.png','2.jpg','10.webp']
    assert all(not source.image(i).isNull() for i in range(3));source.close()

def test_pdf_on_demand(qt,tmp_path):
    pdf=tmp_path/'sample.pdf';Image.new('RGB',(200,300),'white').save(pdf,save_all=True,append_images=[Image.new('RGB',(200,300),'pink')])
    before=hashlib.sha256(pdf.read_bytes()).digest();source=open_source(pdf,tmp_path/'cache')
    assert source.count==2;assert source.image(1).width()>0;source.close()
    assert hashlib.sha256(pdf.read_bytes()).digest()==before

def test_missing_corrupt_empty_and_cbr_dependency(qt,tmp_path,monkeypatch):
    with pytest.raises(ReaderSourceError):open_source(tmp_path/'missing.cbz',tmp_path/'cache')
    bad=tmp_path/'bad.cbz';bad.write_bytes(b'bad zip')
    with pytest.raises(zipfile.BadZipFile):open_source(bad,tmp_path/'cache')
    with zipfile.ZipFile(bad,'w') as archive:archive.writestr('note.txt','not a page')
    with pytest.raises(ReaderSourceError,match='No readable images'):open_source(bad,tmp_path/'cache')
    import rarfile
    monkeypatch.setattr(rarfile,'tool_setup',lambda:(_ for _ in ()).throw(rarfile.RarCannotExec('missing')))
    cbr=tmp_path/'book.cbr';cbr.write_bytes(b'not overwritten')
    with pytest.raises(ReaderSourceError,match='UnRAR'):open_source(cbr,tmp_path/'cache')
    assert cbr.read_bytes()==b'not overwritten'

def test_reader_runtime_resume_bookmarks_and_modes(qt,book,tmp_path):
    db=Database(tmp_path/'state.db');logs=[]
    reader=LocalMangaReader(db,book,tmp_path/'cache');reader.diagnostic.connect(logs.append);reader.resize(1000,700);reader.show();reader.start();ready(qt,reader)
    assert not reader.completed
    reader.go(1);ready(qt,reader);reader.toggle_bookmark();assert reader.store.bookmarks(reader.identity)==[2]
    reader.mode.setCurrentText('Fit Width');qt.processEvents();assert reader.canvas.width()>=reader.scroll.viewport().width()
    reader.reset_zoom();qt.processEvents();assert reader.canvas.targets[0].width()==300
    reader.zoom_by(2);qt.processEvents();assert reader.canvas.targets[0].width()==600
    reader.shutdown();reader.close();db.connection.close()
    db=Database(tmp_path/'state.db');reader=LocalMangaReader(db,book,tmp_path/'cache');reader.show();reader.start();ready(qt,reader)
    assert reader.page==1;assert reader.store.bookmarks(reader.identity)==[2]
    assert reader.mode.currentText()=='Manual';assert reader.zoom==2
    reader.spread.setChecked(True);reader.direction.setCurrentText('Right-to-Left (Manga)');ready(qt,reader)
    assert reader.visible_indices()==[1,2]
    assert reader.canvas.images[0].pixelColor(0,0).name()=='#0000ff'
    reader.direction.setCurrentText('Left-to-Right');ready(qt,reader)
    assert reader.canvas.images[0].pixelColor(0,0).name()=='#008000'
    reader.spread.setChecked(False);reader.go(0);ready(qt,reader)
    reader.canvas.setFocus();QTest.keyClick(reader.canvas,Qt.Key_Right);ready(qt,reader);assert reader.page==1
    reader.direction.setCurrentText('Right-to-Left (Manga)');QTest.keyClick(reader.canvas,Qt.Key_Left);ready(qt,reader);assert reader.page==2
    assert reader.completed
    reader.toggle_bookmark();assert 3 in reader.store.bookmarks(reader.identity)
    reader.shutdown();reader.close();db.connection.close()
    assert any('ReaderOpen' in entry for entry in logs)

def test_corrupt_individual_page_can_be_skipped(qt,tmp_path):
    path=tmp_path/'mixed.cbz'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('1.png',image_bytes());archive.writestr('2.png',b'corrupt');archive.writestr('3.png',image_bytes('blue'))
    db=Database(tmp_path/'db');reader=LocalMangaReader(db,path,tmp_path/'cache');reader.show();reader.start();ready(qt,reader)
    reader.go(1);wait(qt,lambda:1 in reader.errors);assert reader.retry.isVisible()
    reader.go(2);ready(qt,reader);assert reader.completed
    reader.shutdown();reader.close();db.connection.close()

def test_spread_pairing_and_bounded_cache(qt):
    assert spread_indices(0,5,True,True)==[0]
    assert spread_indices(2,5,True,True)==[1,2]
    assert spread_indices(4,5,True,False)==[4]
    cache=PageCache(max_pages=5,max_bytes=1000)
    for i in range(200):
        image=QImage(10,10,QImage.Format_RGB32);image.fill(Qt.white);cache.put(i,image)
        assert len(cache.images)<=5 and cache.bytes<=1000

def test_reader_migration_does_not_change_existing_data(tmp_path):
    path=tmp_path/'db';db=Database(path)
    db.connection.execute("INSERT INTO anime(identity,title,root_path,favorite,anilist_id) VALUES('existing','Existing','/original',1,42)")
    db.set_setting('existing','preserved');before=[tuple(row) for row in db.connection.execute('SELECT * FROM anime')];db.connection.close()
    db=Database(path);store=ReaderStore(db);state=store.open(tmp_path/'book.cbz','normal','cbz',10);store.save(state['identity'],5,10);store.toggle_bookmark(state['identity'],5)
    assert [tuple(row) for row in db.connection.execute('SELECT * FROM anime')]==before
    assert db.setting('existing')=='preserved';assert item_identity(tmp_path/'book.cbz','normal')!=item_identity(tmp_path/'book.cbz','restricted')
    db.connection.close()

def test_main_window_reader_fullscreen_navigation_privacy(qt,book,tmp_path,monkeypatch):
    import anime_hub.app as app_module
    monkeypatch.setattr(app_module,'APP_DIR',tmp_path/'app')
    monkeypatch.setattr(app_module,'_append_playback_log',lambda *args:None)
    window=app_module.Window();window.show();window.open_local_manga(book);reader=window.manga_reader_page;ready(qt,reader)
    reader.canvas.setFocus();QTest.keyClick(reader.canvas,Qt.Key_F);qt.processEvents();assert window.isFullScreen();assert not window.sidebar.isVisible()
    QTest.keyClick(reader.canvas,Qt.Key_Escape);qt.processEvents();assert not window.isFullScreen();assert window.sidebar.isVisible()
    window.show_library();qt.processEvents();assert window.manga_reader_page is None;assert reader.closed
    window.db.set_setting('restricted_unlocked','1');window.open_local_manga(book,'restricted');reader=window.manga_reader_page;ready(qt,reader)
    reader.go(1);ready(qt,reader);identity=reader.identity;window.lock_restricted();qt.processEvents()
    assert window.manga_reader_page is None;assert not window.current_view.startswith('restricted')
    assert window.db.connection.execute('SELECT current_page FROM manga_reader_state WHERE identity=?',(identity,)).fetchone()[0]==2
    window.close();qt.processEvents()

@pytest.mark.parametrize('kind',['folder','pdf'])
def test_other_sources_in_live_reader(qt,tmp_path,kind):
    if kind=='folder':
        path=tmp_path/'folder';path.mkdir()
        for i in range(1,4):(path/f'{i}.png').write_bytes(image_bytes())
    else:
        path=tmp_path/'book.pdf';Image.new('RGB',(240,350),'white').save(path,save_all=True,append_images=[Image.new('RGB',(240,350),'pink'),Image.new('RGB',(240,350),'blue')])
    db=Database(tmp_path/'state.db');reader=LocalMangaReader(db,path,tmp_path/'cache');reader.resize(900,650);reader.show();reader.start();ready(qt,reader)
    reader.mode.setCurrentText('Fit Page');qt.processEvents()
    assert reader.canvas.targets[0].height()<=reader.scroll.viewport().height()
    reader.go(1);ready(qt,reader);reader.spread.setChecked(True);ready(qt,reader);assert len(reader.canvas.images)==2
    reader.shutdown();reader.close();db.connection.close()

def test_large_book_loading_is_bounded_and_pan_works(qt,tmp_path):
    path=tmp_path/'large.cbz';data=image_bytes()
    with zipfile.ZipFile(path,'w') as archive:
        for i in range(300):archive.writestr(f'{i+1}.png',data)
    db=Database(tmp_path/'db');reader=LocalMangaReader(db,path,tmp_path/'cache');reader.resize(850,650);reader.show();reader.start();ready(qt,reader)
    QTest.qWait(80);qt.processEvents();assert len(reader.cache.images)<=5
    reader.go(180);ready(qt,reader);QTest.qWait(80);qt.processEvents();assert len(reader.cache.images)<=5
    reader.zoom_by(4);qt.processEvents();reader.scroll.verticalScrollBar().setValue(100)
    QTest.mousePress(reader.canvas,Qt.MiddleButton,pos=reader.canvas.rect().center());start=reader.drag if hasattr(reader,'drag') else reader.canvas.drag
    assert start is not None
    before=reader.scroll.verticalScrollBar().value()
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent,QWheelEvent
    move=QMouseEvent(QMouseEvent.MouseMove,QPointF(100,100),reader.canvas.drag-QPointF(0,30),Qt.NoButton,Qt.MiddleButton,Qt.NoModifier)
    QApplication.sendEvent(reader.canvas,move);assert reader.scroll.verticalScrollBar().value()>before
    QTest.mouseRelease(reader.canvas,Qt.MiddleButton,pos=reader.canvas.rect().center());assert reader.canvas.drag is None
    assert reader.scroll.verticalScrollBar().maximum()>0
    from PySide6.QtCore import QPoint
    wheel=QWheelEvent(QPointF(20,20),QPointF(20,20),QPoint(),QPoint(0,-120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    zoom=reader.zoom;QApplication.sendEvent(reader.canvas,wheel);ready(qt,reader);assert reader.page==180;assert reader.zoom<zoom
    reader.shutdown();reader.close();db.connection.close()

def test_one_page_open_does_not_complete_and_explicit_next_does(qt,tmp_path):
    folder=tmp_path/'one';folder.mkdir();(folder/'1.png').write_bytes(image_bytes())
    db=Database(tmp_path/'db');reader=LocalMangaReader(db,folder,tmp_path/'cache');reader.show();reader.start();ready(qt,reader)
    assert not reader.completed;reader.step(1);ready(qt,reader);assert reader.completed
    reader.shutdown();reader.close();db.connection.close()
