"""Runtime cleanup and read-only upgrade checks for the frozen V0.8 branch."""
import json,sqlite3,hashlib
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QPixmap,QColor,QWheelEvent
from PySide6.QtWidgets import QLabel,QPushButton,QScrollArea,QWidget,QVBoxLayout,QListWidget,QLineEdit
from PySide6.QtTest import QTest
from anime_hub import app
from anime_hub.app import Card,SeasonCard,ResponsiveLibraryGrid
from anime_hub.manga_ui import MangaCard
from anime_hub.manga_state import ReaderStore
from anime_hub.manga_library import MangaStore,scan_manga
from anime_hub.media_cards import CARD_WIDTH,CARD_HEIGHT,COVER_WIDTH,COVER_HEIGHT,ContainedScrollArea,ContainedListWidget
from anime_hub.database import Database
from anime_hub.integrated_player import clean_episode_label
from test_cross_media import data,window,remote
from test_v087 import franchise_fixture


def test_standard_media_card_slots_and_favorites_sections(window):
    w,qt,aid,sid,_=window;w.db.set_favorite(aid,True);w.manga_store.set_favorite(sid,True)
    w.show_favorites();qt.processEvents();page=w.stack.currentWidget()
    assert {'Anime Favorites','Manga Favorites'} <= {label.text() for label in page.findChildren(QLabel)}
    cards=[page.findChild(Card),page.findChild(MangaCard),SeasonCard({**remote(90),'_recommendation_reason':'A reason that is long enough to wrap over two lines for readability'},show_save=True)]
    for card in cards[:2]:
        assert card.property('posterCard')
        assert any(label.width()*3==label.height()*2 and label.height()==258 for label in card.findChildren(QLabel))
    for card in cards[2:]:
        assert (card.width(),card.height())==(CARD_WIDTH,CARD_HEIGHT)
        assert card.findChild(QLabel,'cardTitle').height()==42
        cover=next(label for label in card.findChildren(QLabel) if label.size().width()==COVER_WIDTH and label.size().height()==COVER_HEIGHT)
        assert cover.height()==258
    second,_=franchise_fixture(w,aid,Path(w.db.path).parent)
    group=w._franchise_card(w._library_franchises()[0]);assert group.property("posterCard") and group.property("franchiseLocalIds")
    w.show_library_franchise((aid,second));qt.processEvents()
    franchise_cards=w.stack.currentWidget().findChildren(Card)
    assert len(franchise_cards)==2 and all(card.property('posterCard') for card in franchise_cards)
    cards[-1].deleteLater();group.deleteLater()


def test_finish_unfinish_preserves_resume_bookmark_manual_status_and_source(data,tmp_path):
    db,store,aid,sid,book=data;other=book.parent/'Vol2.cbz';other.write_bytes(b'unchanged second source');store.reconcile(scan_manga(store.roots()))
    items=store.items(sid);first=items[0];second=items[1];reader=ReaderStore(db)
    state=reader.open(first['path'],'normal',first['source_type'],20,first['reader_identity']);reader.save(state['identity'],7,20);reader.toggle_bookmark(state['identity'],5)
    store.set_status(sid,'Paused');before=db.connection.execute('SELECT current_page,total_pages,percent_complete FROM manga_reader_state WHERE identity=?',(first['reader_identity'],)).fetchone()
    digests={p:hashlib.sha256(p.read_bytes()).digest() for p in [book,other]}
    store.set_item_finished(first['id'],True);assert store.series(sid)['completed_count']==1
    store.set_item_finished(first['id'],False);assert store.series(sid)['completed_count']==0
    after=db.connection.execute('SELECT current_page,total_pages,percent_complete FROM manga_reader_state WHERE identity=?',(first['reader_identity'],)).fetchone()
    assert tuple(before)==tuple(after) and reader.bookmarks(first['reader_identity'])==[5]
    assert not store.items(sid)[1]['completed'] and store.series(sid)['manual_status']=='Paused'
    assert all(hashlib.sha256(p.read_bytes()).digest()==value for p,value in digests.items())
    store.set_item_finished(second['id'],True);assert store.series(sid)['completed_count']==1
    copied=tmp_path/'reopen.db';connection=sqlite3.connect(copied);db.connection.backup(connection);connection.close()
    reopened=Database(copied);again=MangaStore(reopened,tmp_path/'owned-again')
    assert again.series(sid)['completed_count']==1 and again.continue_item(sid)['id']==first['id']
    assert reopened.audit_integrity(deep=True)['sqlite_integrity']=='ok';reopened.connection.close()


def test_manga_detail_toggle_updates_only_item_and_secondary_collection(window):
    w,qt,aid,sid,book=window;w.show_manga_detail(sid);qt.processEvents();page=w.stack.currentWidget();listing=page.findChild(QListWidget,'mangaItems')
    toggle=next(b for b in page.findChildren(QPushButton) if b.text()=='Toggle Finished');toggle.click();assert 'Finished' in listing.item(0).text()
    toggle.click();assert 'Finished' not in listing.item(0).text();assert w.stack.currentWidget() is page
    for show in [lambda:w.show_detail(aid),lambda:w.show_manga_detail(sid),lambda:w.show_remote_anilist(remote(99),'Discover')]:
        show();qt.processEvents();page=w.stack.currentWidget();collection=page.findChild(QPushButton,'detailCollectionAction');assert collection and collection.text()=='+ Collection'
        bar=page.findChild(QWidget,'directStatusControls');assert collection not in bar.findChildren(QPushButton)
        assert not any(b.text()=='Collections…' for b in page.findChildren(QPushButton))


def test_search_covers_async_visible_and_stale_guard(window,monkeypatch):
    w,qt,aid,*_=window;w.show_detail(aid);editor=w.global_search;popup=w.global_suggestions
    QTest.qWait(40);editor.setFocus();qt.processEvents()
    loads=[];monkeypatch.setattr(w,'_load_remote_artwork',lambda url,label,width,height:loads.append((url,label,width,height)))
    monkeypatch.setattr(w,'_submit_discover_job',lambda *_:None)
    editor.setText('Shared');popup.changed('Shared');popup.timer.stop();popup.results=[({**remote(i),'coverImage':{'large':f'https://example.invalid/{i}.jpg'}},None) for i in range(100,110)];popup.render();qt.processEvents()
    assert popup.isVisible() and popup.count()==10 and all(popup.item(i).sizeHint().height()==66 for i in range(10))
    assert 1<=len(loads)<=6 and all((width,height)==(40,56) for _,_,width,height in loads)
    row=popup.item(0);old=row.icon().cacheKey();pix=QPixmap(40,56);pix.fill(QColor('coral'));loads[0][1].setPixmap(pix);assert row.icon().cacheKey()!=old
    target=loads[0][1];editor.setText('Different');popup.changed('Different');target.setPixmap(pix);assert not popup.isVisible()
    assert not any(item.get('type') in {'STAFF','CHARACTER'} for item,_ in popup.results)


@pytest.mark.parametrize('child_type',[ContainedScrollArea,ContainedListWidget])
def test_nested_wheel_stays_in_child_at_both_boundaries(window,child_type):
    w,qt,*_=window;outer=QScrollArea(w);outer.resize(360,240);outer.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body)
    child=child_type();child.setFixedHeight(120)
    if isinstance(child,QListWidget):child.addItems([str(i) for i in range(50)])
    else:
        content=QWidget();content.setMinimumHeight(800);child.setWidget(content)
    layout.addWidget(child);spacer=QWidget();spacer.setMinimumHeight(800);layout.addWidget(spacer);outer.setWidget(body);outer.show();qt.processEvents();outer.verticalScrollBar().setValue(100)
    for value,delta in [(0,120),(child.verticalScrollBar().maximum(),-120)]:
        child.verticalScrollBar().setValue(value);before=outer.verticalScrollBar().value();event=QWheelEvent(QPointF(20,20),QPointF(child.viewport().mapToGlobal(QPoint(20,20))),QPoint(),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        app.QApplication.sendEvent(child.viewport(),event);qt.processEvents();assert event.isAccepted() and outer.verticalScrollBar().value()==before
    outer.deleteLater()


def test_empty_episode_title_no_separator():
    for name,title in [('Show - 07 - [Group].mkv',''),('Show.S01E07.1080p.HEVC.mkv',''),('Show - 07.mkv',' — '),('Show - 07.mkv','')]:
        assert clean_episode_label(name,7,title)=='Episode 7'


def test_read_only_integrity_audit_reports_without_repair(data):
    db,store,aid,sid,book=data;before=db.connection.total_changes;report=db.audit_integrity(deep=True)
    assert report['sqlite_integrity']=='ok' and all(value==0 for key,value in report.items() if key!='sqlite_integrity')
    assert db.connection.total_changes==before
    db.connection.commit();db.connection.execute('PRAGMA foreign_keys=OFF');db.connection.execute("INSERT INTO collection_entries(collection_id,entity_key) VALUES(999,'anilist:999')");db.connection.commit()
    before=db.connection.total_changes;report=db.audit_integrity();assert report['orphan_collection_entries']==1 and report['foreign_key_errors']==1
    assert db.connection.total_changes==before and db.connection.execute('SELECT COUNT(*) FROM collection_entries WHERE collection_id=999').fetchone()[0]==1


@pytest.mark.parametrize('stage',['pre_manga','pre_status','pre_saved_removal','pre_franchise_redesign','pre_v086','v087'])
def test_representative_upgrade_copies_preserve_app_owned_state(data,tmp_path,stage):
    db,store,aid,sid,book=data;db.set_favorite(aid,True);store.set_favorite(sid,True);store.set_status(sid,'Paused');db.set_watched(db.media(aid)[0]['id'],True)
    db.connection.execute('UPDATE media SET resume_position_ms=47000');cid=db.create_collection('Existing');db.add_to_collection(cid,aid);store.add_collection(sid,cid)
    fid=db.create_franchise('Existing franchise');db.add_to_franchise(fid,aid)
    db.save_title(remote(88,'MANGA',True),'restricted');db.save_source_gallery({'source':'nhentai','external_id':'9','title':'Existing external','source_url':'https://nhentai.net/g/9/'})
    db.connection.commit();copy=tmp_path/(stage+'.db');connection=sqlite3.connect(copy);db.connection.backup(connection);connection.execute('PRAGMA foreign_keys=OFF')
    if stage=='pre_manga':
        connection.execute("DELETE FROM collection_entries WHERE entity_key LIKE 'manga:%'")
        connection.execute("DELETE FROM manual_status WHERE entity_key LIKE 'manga:%'")
        for table in ['manga_bookmarks','manga_reader_state','manga_items','manga_series','manga_roots']:connection.execute('DROP TABLE '+table)
    if stage=='pre_status':connection.execute('DROP TABLE manual_status')
    if stage in {'pre_saved_removal','pre_v086'}:connection.execute("DELETE FROM settings WHERE key='saved_planning_v086'")
    if stage=='pre_franchise_redesign':
        connection.execute('INSERT OR IGNORE INTO collection_items(collection_id,anime_id) VALUES(?,?)',(cid,aid));connection.execute('DROP TABLE collection_entries')
    # Deliberately emulate pre-scope collections while preserving membership.
    if stage=='pre_status':connection.execute('ALTER TABLE collections DROP COLUMN scope')
    connection.commit();anime_before=[tuple(r) for r in connection.execute('SELECT * FROM anime')];media_before=[tuple(r) for r in connection.execute('SELECT * FROM media')];external_before=[tuple(r) for r in connection.execute('SELECT * FROM restricted_source_saved')];connection.close()
    upgraded=Database(copy)
    try:
        assert anime_before==[tuple(r) for r in upgraded.connection.execute('SELECT * FROM anime')]
        assert media_before==[tuple(r) for r in upgraded.connection.execute('SELECT * FROM media')]
        assert external_before==[tuple(r) for r in upgraded.connection.execute('SELECT * FROM restricted_source_saved')]
        assert upgraded.collection(cid) and upgraded.anime(aid)['favorite'] and upgraded.media(aid)[0]['watched'] and upgraded.media(aid)[0]['resume_position_ms']==47000
        assert upgraded.connection.execute('SELECT anime_id FROM franchise_items WHERE franchise_id=?',(fid,)).fetchone()[0]==aid
        assert upgraded.is_saved(88,'restricted')
        if stage not in {'pre_manga','pre_status'}:assert MangaStore(upgraded,tmp_path/'owned2').series(sid)['manual_status']=='Paused'
        assert upgraded.audit_integrity(deep=True)['sqlite_integrity']=='ok' and not upgraded.audit_integrity()['foreign_key_errors']
        if stage=='pre_franchise_redesign':assert upgraded.entity_collection_ids('anilist:11')=={cid}
    finally:upgraded.connection.close()
    reopened=Database(copy);assert reopened.anime(aid)['anilist_id']==11;assert not reopened.audit_integrity()['foreign_key_errors'];reopened.connection.close();assert book.read_bytes()==b'scan-only'


def test_ancient_saved_schema_migrates_to_planning_with_archive(tmp_path):
    path=tmp_path/'legacy.db';connection=sqlite3.connect(path)
    connection.executescript('CREATE TABLE saved_titles(anilist_id INTEGER PRIMARY KEY,title TEXT NOT NULL,metadata_json TEXT NOT NULL,saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);')
    connection.execute('INSERT INTO saved_titles(anilist_id,title,metadata_json) VALUES(?,?,?)',(77,'Old Saved',json.dumps(remote(77))));connection.commit();connection.close()
    db=Database(path)
    assert db.manual_status('normal',anilist_id=77)=='Planning'
    assert db.connection.execute('SELECT title FROM normal_saved_migration_archive WHERE anilist_id=77').fetchone()[0]=='Old Saved'
    assert not db.saved_titles('normal') and not db.audit_integrity()['foreign_key_errors'];db.connection.close()
