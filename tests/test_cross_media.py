import json
import hashlib
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication,QLabel,QPushButton
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.manga_library import MangaStore,scan_manga
from anime_hub.organization import Organization
from anime_hub.app import Window,Card,SeasonCard,CollectionCard,StatusCountLabel
from anime_hub.manga_ui import MangaCard
from anime_hub import app


def remote(i,kind='ANIME',adult=False):
    return {'id':i,'type':kind,'isAdult':adult,'title':{'english':'Shared '+str(i),'romaji':'Alias '+str(i)},'status':'FINISHED','format':'MANGA' if kind=='MANGA' else 'TV'}


def anime(db,path,i=11,adult=False):
    path.mkdir();video=path/'01.mkv';video.write_bytes(b'read-only')
    aid=db.upsert_anime(str(path),'Shared '+str(i),'','Other',str(path))
    db.upsert_media(aid,SimpleNamespace(path=video,kind='episode',season=1,episode=1))
    db.set_metadata(aid,i,remote(i,adult=adult));return aid


def manga(db,store,path,i=22,scope='normal'):
    path.mkdir();(path/'Shared' ).mkdir();book=path/'Shared'/'Vol1.cbz';book.write_bytes(b'scan-only')
    store.add_root(path,scope);store.reconcile(scan_manga(store.roots()));row=next(r for r in store.series_list(scope) if r['root_path']==str(path/'Shared'))
    store.match(row['id'],remote(i,'MANGA',scope=='restricted'));return row['id'],book


@pytest.fixture
def data(tmp_path):
    db=Database(tmp_path/'vault.db');store=MangaStore(db,tmp_path/'owned');aid=anime(db,tmp_path/'Anime');sid,book=manga(db,store,tmp_path/'Manga')
    db.save_title(remote(11));db.save_title(remote(22,'MANGA'))
    yield db,store,aid,sid,book
    db.connection.close()


def test_search_identity_scope_and_storage_readonly(data):
    db,store,aid,sid,book=data
    db.save_title(remote(33,'MANGA',True),'restricted')
    db.save_source_gallery({'source':'nhentai','external_id':'9','title':'Cached bookmark','source_url':'https://nhentai.net/g/9/'})
    before=db.connection.total_changes
    entities=Organization(db,store).search('Shared');assert len(entities)==2
    assert {e.media_type for e in entities}=={'ANIME','MANGA'};assert all(e.saved and e.local for e in entities)
    assert len(Organization(db,store).search('Alias 22'))==1
    assert not Organization(db,store).search('Cached')
    private=Organization(db,store,'restricted');assert len(private.search('Shared'))==1
    assert len(private.search('Cached'))==1;assert db.connection.total_changes==before


def test_saved_local_collection_aliases_no_duplicate(data):
    db,store,aid,sid,book=data;cid=db.create_collection('Mixed')
    assert db.add_to_collection(cid,aid)
    assert db.add_remote_to_collection(cid,remote(22,'MANGA'))
    assert not store.add_collection(sid,cid)
    # Existing duplicated aliases from earlier versions are retained but displayed once.
    db.connection.execute('INSERT INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)',(cid,f'manga:{sid}',json.dumps(remote(22,'MANGA'))));db.connection.commit()
    org=Organization(db,store);entries=org.collection(cid);assert len(entries)==2
    entity=next(e for e in entries if e.media_type=='MANGA');org.remove_membership(cid,entity)
    assert len(Organization(db,store).collection(cid))==1
    assert store.series(sid) and db.is_saved(22)
    assert book.exists()


def test_status_alias_precedence_and_explicit_update(data):
    db,store,aid,sid,book=data;db.set_manual_status('Planning',item=remote(22,'MANGA'))
    assert Organization(db,store).resolve(f'manga:{sid}').status=='Planning'
    store.set_status(sid,'Paused');org=Organization(db,store)
    assert len(org.statuses('Paused'))==1;assert not org.statuses('Planning')
    assert store.series(sid)['progress']==0
    store.set_status(sid,None);assert not Organization(db,store).statuses('Paused')


def test_missing_state_favorites_restart_and_rescan(data):
    db,store,aid,sid,book=data;db.set_favorite(aid,True);store.set_favorite(sid,True);store.set_status(sid,'Dropped');cid=db.create_collection('Preserve');store.add_collection(sid,cid)
    digest=hashlib.sha256(book.read_bytes()).digest();book.unlink();store.reconcile(scan_manga(store.roots()))
    org=Organization(db,store);assert len(org.favorites())==1
    assert org.resolve(f'manga:{sid}') is None and not org.collection(cid)
    path=db.path if hasattr(db,'path') else None
    reopened=Database(book.parents[2]/'vault.db');again=MangaStore(reopened)
    assert len(Organization(reopened,again).favorites())==1
    assert reopened.connection.execute("SELECT status FROM manual_status WHERE entity_key=?",('manga:'+str(sid),)).fetchone()[0]=='Dropped'
    book.write_bytes(b'scan-only');again.reconcile(scan_manga(again.roots()));assert 'In Vault' in Organization(reopened,again).resolve(f'manga:{sid}').label
    assert hashlib.sha256(book.read_bytes()).digest()==digest;reopened.connection.close()


def test_duplicate_local_ids_not_merged(data,tmp_path):
    db,store,aid,sid,book=data;other=anime(db,tmp_path/'Second',11);db.set_favorite(other,True)
    org=Organization(db,store);assert len(org.search('Shared 11'))==1
    assert len(org.favorites())==1;assert db.anime(aid) and db.anime(other)
    assert org.resolve(f'local:{other}').aliases=={f'local:{aid}',f'local:{other}','anilist:11'}


def test_scope_mismatch_rejected_and_membership_hidden(data,tmp_path):
    db,store,aid,sid,book=data;private=db.create_collection('Private',scope='restricted')
    with pytest.raises(ValueError):db.add_to_collection(private,aid)
    with pytest.raises(ValueError):store.add_collection(sid,private)
    # Even stale private membership metadata cannot show a local private manga normally.
    rsid,_=manga(db,store,tmp_path/'PrivateManga',33,'restricted');normal=db.create_collection('Normal')
    db.connection.execute('INSERT INTO collection_entries(collection_id,entity_key,metadata_json) VALUES(?,?,?)',(normal,f'manga:{rsid}',json.dumps(remote(33,'MANGA',True))));db.connection.commit()
    assert not Organization(db,store).collection(normal)


@pytest.fixture
def window(tmp_path,monkeypatch):
    qt=QApplication.instance() or QApplication([]);monkeypatch.setattr(app,'APP_DIR',tmp_path/'app');monkeypatch.setattr(app,'_append_playback_log',lambda *_:None)
    monkeypatch.setattr(Window,'_load_remote_artwork',lambda *_:None);monkeypatch.setattr(Window,'_request_library_relations',lambda *args,**kwargs:None)
    monkeypatch.setattr(Window,'_request_discover_page',lambda *_:None)
    monkeypatch.setattr('anime_hub.related_ui.fetch_related',lambda *_:{})
    view=Window();aid=anime(view.db,tmp_path/'Anime');sid,book=manga(view.db,view.manga_store,tmp_path/'Manga');view.db.save_title(remote(11));view.db.save_title(remote(22,'MANGA'))
    view.resize(1280,900);view.show();view._manga_cover_timer.stop()
    yield view,qt,aid,sid,book
    view.close();qt.processEvents();view.db.connection.close()


def test_runtime_mixed_collection_and_local_link(window):
    w,qt,aid,sid,book=window;cid=w.db.create_collection('Mixed');w.db.add_to_collection(cid,aid);w.db.add_remote_to_collection(cid,remote(22,'MANGA'))
    w.show_collection_detail(cid);qt.processEvents();page=w.stack.currentWidget()
    assert len(page.findChildren(Card))==1 and len(page.findChildren(MangaCard))==1
    manga_card=page.findChild(MangaCard);QTest.mouseDClick(manga_card,Qt.LeftButton);qt.processEvents()
    assert w.current_view=='manga_detail' and w.current_manga_id==sid
    w.navigate_back();qt.processEvents();assert w.current_collection_id==cid


def test_runtime_global_search_history_and_favorites(window):
    w,qt,aid,sid,book=window;w.db.set_favorite(aid,True);w.manga_store.set_favorite(sid,True)
    w.show_favorites();qt.processEvents();assert w.stack.currentWidget().findChild(MangaCard) is not None
    w.show_global_search('Shared');qt.processEvents();page=w.stack.currentWidget();assert len(page.findChildren(Card))==1 and len(page.findChildren(MangaCard))==1
    assert 'Manga · In Vault · Saved' in page.findChild(MangaCard).toolTip()
    w.navigate_back();qt.processEvents();assert w.current_view=='favorites'


def test_runtime_saved_manga_card_and_detail_link(window):
    w,qt,aid,sid,book=window;w._manga_status(sid,'Planning');w.show_saved();qt.processEvents();cards=w.stack.currentWidget().findChildren(MangaCard)
    card=cards[0];assert 'In Vault' in card.toolTip()
    QTest.mouseDClick(card,Qt.LeftButton);qt.processEvents();assert w.current_view=='manga_detail'
    w.show_remote_anilist(remote(22,'MANGA'),'Saved');qt.processEvents();page=w.stack.currentWidget()
    next(b for b in page.findChildren(QPushButton) if 'In Vault' in b.text()).click();assert w.current_view=='manga_detail'


def test_runtime_live_status_counts_and_no_page_reload(window):
    w,qt,aid,sid,book=window;w.db.set_manual_status('Planning',item=remote(22,'MANGA'));w.show_collections();qt.processEvents()
    page=w.stack.currentWidget();label=next(l for l in page.findChildren(StatusCountLabel) if l.status=='Planning');assert label.text()=='1 titles'
    w._manga_status(sid,'Dropped');qt.processEvents();assert w.stack.currentWidget() is page
    assert label.text()=='0 titles';w.show_home();w.show_collections();qt.processEvents()
    assert next(l for l in w.stack.currentWidget().findChildren(StatusCountLabel) if l.status=='Dropped').text()=='1 titles'


def test_runtime_lock_cannot_restore_private_search(window):
    w,qt,aid,sid,book=window;w.db.set_setting('restricted_unlocked','1');w.db.save_title(remote(44,'MANGA',True),'restricted')
    w.show_global_search('Shared','restricted');qt.processEvents();assert len(w.stack.currentWidget().findChildren(SeasonCard))==1
    w.lock_restricted();qt.processEvents();assert not w.current_view.startswith('restricted')
    page=w.stack.currentWidget();w.show_global_search('Shared','restricted');assert w.stack.currentWidget() is page
    w.show_global_search('Shared');qt.processEvents();assert not w.stack.currentWidget().findChildren(SeasonCard)
    assert w.db.is_saved(44,'restricted')


def test_batched_catalog_queries_do_not_scale_per_card(data):
    db,store,aid,sid,book=data
    for index in range(100,350):db.save_title(remote(index,'MANGA' if index%2 else 'ANIME'))
    queries=[];db.connection.set_trace_callback(queries.append)
    org=Organization(db,store);results=org.search('Shared')
    db.connection.set_trace_callback(None)
    assert len(results)==252
    assert len([q for q in queries if q.lstrip().upper().startswith('SELECT')])<=10


def test_database_reopen_no_destructive_migration(data):
    db,store,aid,sid,book=data;cid=db.create_collection('Original');db.add_to_collection(cid,aid);store.add_collection(sid,cid)
    db.set_favorite(aid,True);store.set_favorite(sid,True);store.set_status(sid,'Paused')
    tables=[row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    before={table:[tuple(row) for row in db.connection.execute('SELECT * FROM "'+table+'"')] for table in tables}
    reopened=Database(book.parents[2]/'vault.db');new_store=MangaStore(reopened)
    Organization(reopened,new_store).search('Shared')
    after={table:[tuple(row) for row in reopened.connection.execute('SELECT * FROM "'+table+'"')] for table in tables}
    assert before==after;reopened.connection.close()


def test_runtime_remote_status_mutation_reaches_local_manga(window):
    w,qt,aid,sid,book=window;w._manga_status(sid,'Paused');w.show_status_list('Paused','normal');qt.processEvents()
    page=w.stack.currentWidget();card=page.findChild(MangaCard)
    w._set_status('Watching','normal',item=remote(22,'MANGA'));qt.processEvents()
    assert w.stack.currentWidget() is page and 'Reading' in card.status_label.text()
    assert w.manga_store.series(sid)['manual_status']=='Watching'


def test_legacy_saved_manga_type_inferred_without_storage_change(data):
    db,store,aid,sid,book=data;item=remote(44,'MANGA');item.pop('type');db.save_title(item)
    stored=db.connection.execute('SELECT metadata_json FROM saved_titles WHERE anilist_id=44').fetchone()[0]
    result=Organization(db,store).search('Shared 44')[0];assert result.media_type=='MANGA'
    assert db.connection.execute('SELECT metadata_json FROM saved_titles WHERE anilist_id=44').fetchone()[0]==stored


def test_runtime_restricted_planning_links_after_local_match(window,tmp_path):
    w,qt,aid,sid,book=window;w.db.set_setting('restricted_unlocked','1');w._set_status('Planning','restricted',item=remote(44,'MANGA',True))
    w.show_status_list('Planning','restricted');qt.processEvents();assert w.stack.currentWidget().findChild(SeasonCard)
    rsid,_=manga(w.db,w.manga_store,tmp_path/'PrivateManga',44,'restricted')
    w.show_home();w.show_status_list('Planning','restricted');qt.processEvents()
    card=w.stack.currentWidget().findChild(MangaCard);assert card is not None and card.row['id']==rsid and 'In Vault' in card.toolTip()
    QTest.mouseDClick(card,Qt.LeftButton);qt.processEvents();assert w.current_manga_id==rsid


def test_removed_legacy_membership_does_not_return_on_restart(data):
    db,store,aid,sid,book=data;cid=db.create_collection('Legacy');db.add_to_collection(cid,aid)
    db.connection.execute('INSERT INTO collection_items(collection_id,anime_id) VALUES(?,?)',(cid,aid));db.connection.commit()
    org=Organization(db,store);org.remove_membership(cid,org.resolve(f'local:{aid}'))
    reopened=Database(book.parents[2]/'vault.db');assert not Organization(reopened,MangaStore(reopened)).collection(cid)
    assert reopened.anime(aid) and reopened.is_saved(11);reopened.connection.close()

