from contextlib import closing
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton

from anime_hub import app as app_module
from anime_hub.app import SourceGalleryCard, Window
from anime_hub.database import Database
from anime_hub.external_bookmarks import bookmark_record, bookmark_url
from anime_hub.retired_cache_cleanup import inspect_retired_cache, quarantine_retired_cache


def entry(source='nhentai',identifier='123456'):
    return {'source':source,'external_id':identifier,'title':'Stored external title',
            'source_url':'https://nhentai.net/g/123456/','page_count':42,
            'cover_url':'https://t.nhentai.net/galleries/111/cover.jpg',
            'tags':{'artist':['Stored artist'],'tag':['Stored tag']}}


@pytest.fixture
def window(tmp_path,monkeypatch):
    qt=QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module,'APP_DIR',tmp_path)
    monkeypatch.setattr(Window,'_request_discover_page',lambda *a,**k:None)
    monkeypatch.setattr(Window,'_request_discover_filters',lambda *a,**k:None)
    view=Window();view.db.set_setting('restricted_unlocked','1')
    yield view,qt
    view.close();qt.processEvents();view.db.connection.close()


def cards(window):
    return window.stack.currentWidget().findChildren(SourceGalleryCard)


def test_offline_bookmarks_no_index_no_webengine(window,tmp_path,monkeypatch):
    view,qt=window
    index=tmp_path/'doujin_index.db';index.write_bytes(b'not a sqlite database')
    item=entry();view.db.save_source_gallery(item)
    monkeypatch.setattr(view,'_load_remote_artwork',lambda *a:pytest.fail('Live artwork'))
    view.show_restricted_home();qt.processEvents()
    buttons={b.text() for b in view.stack.currentWidget().findChildren(QPushButton)}
    assert 'Doujin' not in buttons and 'Download Snapshot' not in buttons
    view.show_saved('restricted');qt.processEvents()
    assert len(cards(view))==1 and cards(view)[0].item['title']==item['title']
    cards(view)[0].clicked.emit(item);qt.processEvents()
    assert view.current_view=='restricted_source_detail'
    buttons={b.text() for b in view.stack.currentWidget().findChildren(QPushButton)}
    assert {'Open Source','Set Status','Add to Collection'}<=buttons
    assert not any('Read in' in b or 'Snapshot' in b or 'Import SQLite' in b for b in buttons)
    opened=[];monkeypatch.setattr(app_module.webbrowser,'open',lambda url:opened.append(url))
    view._open_bookmark_source(item);assert opened==[item['source_url']]
    assert index.read_bytes()==b'not a sqlite database'
    assert not any('QtWebEngine' in module for module in sys.modules)
    for name in ('anime_hub.restricted_sources','anime_hub.restricted_native','anime_hub.restricted_web_view','anime_hub.doujin_index'):
        assert name not in sys.modules
    assert not hasattr(view,'_doujin_update_worker') and not hasattr(view,'_doujin_registry')
    assert not hasattr(view,'show_doujin') and not hasattr(view,'open_source_reader')


def test_status_collection_reading_history_restart_and_unsave(window,tmp_path):
    view,qt=window;item=entry();cid=view.db.create_collection('Private Shelf',scope='restricted')
    view.db.save_source_gallery(item);view.db.set_reading_progress('nhentai','123456',18,42)
    view.db.record_source_visit(item);view._source_status(item,'Watching');view._source_collection(cid,item)
    view.show_collection_detail(cid,'restricted');qt.processEvents();assert len(cards(view))==1
    view.show_status_list('Watching','restricted');qt.processEvents()
    assert len(cards(view))==1 and 'Reading' in cards(view)[0].status_label.text()
    view.show_saved('normal');qt.processEvents();assert not cards(view)
    reopened=Database(tmp_path/'anime_hub.db')
    assert reopened.is_source_saved('nhentai','123456')
    assert reopened.source_status('nhentai','123456')=='Watching'
    assert reopened.entity_collection_ids('source:nhentai:123456')=={cid}
    assert reopened.reading_progress('nhentai','123456')['last_page']==18
    assert reopened.source_recent('nhentai')[0]['title']==item['title']
    reopened.connection.close();view._save_source(item,False)
    assert not view.db.is_source_saved('nhentai','123456')
    assert view.db.source_status('nhentai','123456')=='Watching'
    assert view.db.entity_collection_ids('source:nhentai:123456')=={cid}
    view.show_collection_detail(cid,'restricted');assert len(cards(view))==1


def test_lock_blocks_stale_external_controls_and_unlock_restores(window,monkeypatch):
    view,qt=window;item=entry();view.db.save_source_gallery(item)
    cid=view.db.create_collection('Private',scope='restricted');view._source_collection(cid,item)
    view.show_saved('restricted');view.show_source_detail(item);qt.processEvents()
    opened=[];monkeypatch.setattr(app_module.webbrowser,'open',lambda url:opened.append(url))
    view.lock_restricted();qt.processEvents();normal=view.stack.currentWidget()
    view._open_bookmark_source(item);view._source_status(item,'Dropped');view._save_source(item,False)
    view.show_saved('restricted');view.show_collection_detail(cid,'restricted');view.show_source_detail(item)
    assert view.stack.currentWidget() is normal and not opened
    assert not view.current_view.startswith('restricted') and not view.restricted_button.isVisible()
    assert view.db.is_source_saved('nhentai','123456') and view.db.source_status('nhentai','123456') is None
    view.db.set_setting('restricted_unlocked','1');view.show_saved('restricted');assert len(cards(view))==1


def test_unknown_source_and_sparse_legacy_json_render(window):
    view,qt=window;view.db.save_source_gallery(entry('external_site','work-1'))
    view.db.connection.execute("INSERT INTO restricted_source_saved(source,external_id,metadata_json) VALUES('nhentai','88','{}')")
    view.db.connection.commit();view.show_saved('restricted');qt.processEvents();assert len(cards(view))==2
    sparse=next(card.item for card in cards(view) if card.item['external_id']=='88')
    assert bookmark_url(sparse)=='https://nhentai.net/g/88/'
    view.show_source_detail(sparse);assert view.current_view=='restricted_source_detail'


def test_cached_artwork_and_fresh_overview_without_source_requests(window,tmp_path,monkeypatch):
    view,qt=window;image=tmp_path/'stored.png';pix=QPixmap(30,40);pix.fill(QColor('coral'));pix.save(str(image))
    item=entry();item['cover_path']=str(image);view.db.save_source_gallery(item)
    fetched=[];monkeypatch.setattr(view._network,'get',lambda *a:fetched.append(a))
    view.show_saved('restricted');qt.processEvents()
    assert cards(view)[0].findChildren(app_module.QLabel)[0].pixmap() is not None
    view.show_restricted_home();first=view.stack.currentWidget();view.show_home();view.show_restricted_home()
    assert view.stack.currentWidget() is not first and view.current_view=="restricted_home" and not fetched


def test_url_validation_and_identity():
    assert bookmark_url(entry())=='https://nhentai.net/g/123456/'
    assert bookmark_record({},'external_site','77')['external_id']=='77'
    for url in ('file:///secret','javascript:alert(1)','https://user:password@example.com/'):
        assert bookmark_url({'source_url':url}) is None


def generated_index(folder,extra_metadata=None):
    path=folder/'doujin_index.db'
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('CREATE TABLE galleries(external_id TEXT UNIQUE,title TEXT,upload_date INTEGER,metadata TEXT); CREATE TABLE terms(field TEXT,value TEXT,external_id TEXT); CREATE VIRTUAL TABLE search USING fts5(title,tag,artist,"group",parody,character,language);')
        value={'source':'nhentai','external_id':'1','title':'Cache row','metadata_provider':'local-doujin-index'}
        value.update(extra_metadata or {});db.execute('INSERT INTO galleries VALUES(?,?,?,?)',('1','Cache row',None,json.dumps(value)))
    return path


def test_cleanup_explicit_recoverable_and_main_database_untouched(tmp_path):
    main=tmp_path/'anime_hub.db';main.write_bytes(b'user-owned sentinel')
    status=tmp_path/'doujin_index.status.json';status.write_text('cached provenance')
    path=generated_index(tmp_path);before=path.read_bytes();result=inspect_retired_cache(tmp_path)
    assert result['records']==1 and path.exists()
    folder=quarantine_retired_cache(tmp_path,result)
    assert not path.exists() and (folder/'doujin_index.db').read_bytes()==before
    assert main.read_bytes()==b'user-owned sentinel' and status.read_text()=='cached provenance'


def test_cleanup_refuses_user_state_or_unknown_schema(tmp_path):
    path=generated_index(tmp_path,{'manual_status':'Planning'})
    with pytest.raises(ValueError):inspect_retired_cache(tmp_path)
    assert path.exists()
    with sqlite3.connect(path) as db:db.execute('DELETE FROM galleries');db.execute('CREATE TABLE user_notes(note TEXT)')
    with pytest.raises(ValueError):inspect_retired_cache(tmp_path)
    assert path.exists()


def test_cleanup_refuses_changed_file_and_sidecars(tmp_path):
    path=generated_index(tmp_path);result=inspect_retired_cache(tmp_path)
    with path.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError):quarantine_retired_cache(tmp_path,result)
    assert path.exists()
    Path(str(path)+'-wal').touch()
    with pytest.raises(ValueError):inspect_retired_cache(tmp_path)


def test_generic_reader_local_pages_only(tmp_path):
    from anime_hub.restricted_reader import RestrictedReader
    qt=QApplication.instance() or QApplication([])
    image=tmp_path/'page.png';pix=QPixmap(20,30);pix.fill(QColor('coral'));pix.save(str(image))
    class LocalPages:
        key='local_pages'
        def page_headers(self):return {}
        def page_url(self,item,page):return QUrl.fromLocalFile(str(image)).toString()
    reader=RestrictedReader(LocalPages(),{'title':'Local pages','page_count':12},start_page=1);reader.show()
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and not reader._cache:qt.processEvents();time.sleep(.01)
    assert reader._cache
    reader.go(10);reader.turn(-1);assert reader.page==9
    reader.turn(1);assert reader.page==10
    reader.close();reader.deleteLater();qt.processEvents()
