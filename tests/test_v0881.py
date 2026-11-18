"""Restricted parity and non-destructive upgrade acceptance checks."""
import json,sqlite3,hashlib
import pytest
from PySide6.QtCore import Qt,QPoint,QEvent
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QLabel,QPushButton,QFrame,QWidget,QScrollArea
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.organization import Organization
from anime_hub.manga_library import MangaStore
from anime_hub.app import Card,SeasonCard,CollectionCard,BackdropFrame,StatusCountLabel,ResponsiveLibraryGrid
from anime_hub.hub_ui import ArtworkHero
from anime_hub.polish_ui import CoverListCard,DetailBackdrop
from anime_hub.media_cards import ContainedScrollArea
from test_cross_media import data,window,remote,anime,manga


def test_restricted_bookmark_upgrade_preserves_all_user_state(data,tmp_path):
    db,store,aid,sid,book=data
    ra=anime(db,tmp_path/'PrivateAnime',101,True);rm,_=manga(db,store,tmp_path/'PrivateManga',102,'restricted')
    for identifier in range(101,109):db.save_title(remote(identifier,'MANGA' if identifier==102 else 'ANIME',True),'restricted')
    statuses=['Watching','Completed','Paused','Dropped','Planning']
    for identifier,status in zip(range(103,108),statuses):db.set_manual_status(status,'restricted',item=remote(identifier,adult=True))
    store.set_status(rm,'Paused');db.set_favorite(ra,True);db.set_watched(db.media(ra)[0]['id'],True)
    cid=db.create_collection('Keep Private',scope='restricted');db.add_to_collection(cid,ra);store.add_collection(rm,cid)
    external={'source':'nhentai','external_id':'990','title':'Kept external bookmark','source_url':'https://nhentai.net/g/990/'}
    db.save_source_gallery(external);db.set_source_status(external,'Dropped');db.add_source_to_collection(cid,external)
    db.connection.execute("DELETE FROM settings WHERE key='restricted_saved_planning_v0881'")
    db.connection.commit();before=hashlib.sha256(book.read_bytes()).digest()
    untouched=['anime','media','manga_series','manga_items','collections','collection_entries','restricted_source_saved','restricted_source_metadata','manga_reader_state','manga_bookmarks']
    records={table:[tuple(row) for row in db.connection.execute('SELECT * FROM '+table)] for table in untouched}
    copied=tmp_path/'upgrade.db';copy=sqlite3.connect(copied);db.connection.backup(copy);copy.close();upgraded=Database(copied)
    assert records=={table:[tuple(row) for row in upgraded.connection.execute('SELECT * FROM '+table)] for table in untouched}
    private=Organization(upgraded,MangaStore(upgraded),'restricted')
    assert private.resolve('anilist:101').status=='Planning' and private.resolve('manga:'+str(rm)).status=='Paused'
    assert all(private.resolve('anilist:'+str(identifier)).status==status for identifier,status in zip(range(103,108),statuses))
    assert private.resolve('anilist:108').status=='Planning'
    assert upgraded.restricted_saved_planning_report=={'migrated':2,'preserved_status':6,'skipped':0}
    assert len(upgraded.connection.execute('SELECT * FROM restricted_saved_migration_archive').fetchall())==8
    assert not upgraded.saved_titles(scope='restricted') and upgraded.is_source_saved('nhentai','990')
    assert len(private.collection(cid))==3 and not Organization(upgraded,MangaStore(upgraded)).statuses('Planning')
    upgraded.connection.close();again=Database(copied);assert again.restricted_saved_planning_report['migrated']==0;again.connection.close()
    assert hashlib.sha256(book.read_bytes()).digest()==before


def test_restricted_live_ui_has_planning_and_only_external_bookmarks(window,monkeypatch):
    w,qt,*_=window;w.db.set_setting('restricted_unlocked','1');item=remote(123,'MANGA',True)
    w.set_saved(item,True,'restricted');assert w.db.manual_status('restricted',anilist_id=123)=='Planning' and not w.db.is_saved(123,'restricted')
    w.show_remote_anilist(item,'Restricted');qt.processEvents()
    assert not any(button.text() in {'Save','Saved','Remove from Saved'} for button in w.stack.currentWidget().findChildren(QPushButton))
    card=w._make_discover_card(item,{},'Restricted',scope='restricted');assert not hasattr(card,'save_button');card.deleteLater()
    w.show_collections('restricted');qt.processEvents()
    assert not any(button.text() in {'Saved','Restricted Saved','External Bookmarks'} for button in w.stack.currentWidget().findChildren(QPushButton))
    assert next(label for label in w.stack.currentWidget().findChildren(StatusCountLabel) if label.status=='Planning').text()=='1 titles'
    external={'source':'nhentai','external_id':'7','title':'Preserved source bookmark','source_url':'https://nhentai.net/g/7/'}
    w.db.save_source_gallery(external);w.show_collections('restricted');assert any(b.text()=='External Bookmarks' for b in w.stack.currentWidget().findChildren(QPushButton))
    w.show_saved('restricted');qt.processEvents();assert not w.stack.currentWidget().findChild(SeasonCard)
    assert w.db.is_source_saved('nhentai','7')
    monkeypatch.setattr(w,'_request_discover_page',lambda *_:None);w.show_restricted_home();qt.processEvents()
    assert not any(button.text() in {'Saved','Restricted Saved'} for button in w.stack.currentWidget().findChildren(QPushButton))
    banner=next(frame for frame in w.stack.currentWidget().findChildren(ArtworkHero));assert banner.library_overview
    outer=w.stack.currentWidget().findChild(QScrollArea);assert banner.isAncestorOf(banner.findChild(QLabel)) and outer.widget().isAncestorOf(banner)
    w.lock_restricted();assert not w.current_view.startswith('restricted') and w.db.is_source_saved('nhentai','7')


def test_restricted_status_collection_mosaics_async_and_live(window,monkeypatch,tmp_path):
    w,qt,*_=window;w.db.set_setting('restricted_unlocked','1');item={**remote(501,'MANGA',True),'coverImage':{'large':'https://example.invalid/cover.png'}}
    w._set_status('Planning','restricted',item=item);cid=w.db.create_collection('Private covers',scope='restricted');w.db.add_remote_to_collection(cid,item)
    pending=[];monkeypatch.setattr(w,'_load_remote_artwork',lambda url,label,width,height:pending.append((url,label,width,height)))
    w.show_collections('restricted');qt.processEvents();page=w.stack.currentWidget()
    assert len(pending)==2
    pix=QPixmap(210,258);pix.fill(QColor('#ec607f'))
    for _,label,*_ in pending:label.setPixmap(pix)
    covers=[card for card in page.findChildren(CoverListCard) if card._mosaic_images]
    assert len(covers)==2 and all(card.art.pixmap().toImage().pixelColor(20,20)==QColor('#ec607f') for card in covers)
    w._set_status('Dropped','restricted',item=item);qt.processEvents()
    assert w.stack.currentWidget() is page
    assert next(label for label in page.findChildren(StatusCountLabel) if label.status=='Planning').text()=='0 titles'
    assert next(label for label in page.findChildren(StatusCountLabel) if label.status=='Dropped').text()=='1 titles'
    pending[-1][1].setPixmap(pix)
    # Local anime cached metadata path was previously overlooked by mosaics.
    path=tmp_path/'local.png';pix.save(str(path));ra=anime(w.db,tmp_path/'PrivateAnime',502,True);w.db.set_metadata(ra,502,{**remote(502,adult=True),'cover_path':str(path)})
    assert w._entity_cover_paths([w.organization('restricted').resolve('local:'+str(ra))])==[str(path)]
    target=pending[-1][1];page.deleteLater();qt.sendPostedEvents(None,QEvent.DeferredDelete);target.setPixmap(pix)


@pytest.mark.parametrize('scope',['normal','restricted'])
def test_related_whole_card_hit_targets_keyboard_scope_order(window,monkeypatch,scope):
    w,qt,aid,*_=window;w.db.set_setting('restricted_unlocked','1')
    if scope=='restricted':aid=anime(w.db,w.db.path.parent/'PrivateAnime',111,True)
    else:aid=aid
    local_id=w.db.anime(aid)['anilist_id'];adult=scope=='restricted'
    nodes=[remote(999,adult=adult),remote(local_id,adult=adult),remote(998,adult=not adult)]
    monkeypatch.setattr(w,'_submit_discover_job',lambda key,operation,success,failure:success({'edges':[{'relationType':'SEQUEL','node':n} for n in nodes]}))
    opened=[];monkeypatch.setattr(w,'_open_related',lambda item,scope:opened.append((item['id'],scope)))
    w.show_collections(scope);panel=w._related_panel(remote(777,adult=adult),scope);panel.resize(900,650);panel.show();qt.processEvents()
    grid=panel.findChild(ResponsiveLibraryGrid);assert len(grid.cards)==2
    assert [card.property('relatedLocal') for card in grid.cards]==[True,False]
    assert isinstance(panel.findChild(QScrollArea),ContainedScrollArea)
    for card in grid.cards:
        assert card.cursor().shape()==Qt.PointingHandCursor
        if isinstance(card,Card):
            assert card.property('posterCard')
        else:
            assert (card.width(),card.height())==(228,460)
        assert not any('Shared' in button.text() for button in card.findChildren(QPushButton))
        for point in [QPoint(25,25),QPoint(25,285),QPoint(25,347),QPoint(220,440)]:QTest.mouseDClick(card,Qt.LeftButton,pos=point)
        card.setFocus();QTest.keyClick(card,Qt.Key_Return)
    assert len(opened)==10 and all(s==scope for _,s in opened)
    assert all(label.testAttribute(Qt.WA_TransparentForMouseEvents) for card in grid.cards for label in card.findChildren(QLabel))
    panel.close();panel.deleteLater()


def test_detail_hero_art_stays_visible_and_aspect_safe(window):
    w,qt,*_=window;frame=DetailBackdrop();pix=QPixmap(300,500);pix.fill(QColor('#ffe080'));frame.banner.setPixmap(pix)
    frame.resize(700,500);frame.show();qt.processEvents();image=frame.grab().toImage()
    assert image.pixelColor(350,250).red()>70 and image.pixelColor(350,250).green()>60
    assert frame.banner.isHidden() and 'QWidget{background:transparent}' in frame.styleSheet()
    frame.resize(360,600);qt.processEvents();image=frame.grab().toImage();assert image.pixelColor(180,300).red()>70
    frame.close();frame.deleteLater()


def test_generated_local_manga_cover_updates_mosaic_without_rebuild(window,monkeypatch,tmp_path):
    w,qt,aid,sid,*_=window;card=CoverListCard('Manga','1 title');entity=w.organization().resolve('manga:'+str(sid))
    queued=[];monkeypatch.setattr(w,'_queue_local_cover',lambda row:queued.append(row['id']))
    w._populate_cover_mosaic(card,[entity]);assert queued==[sid] and not card._mosaic_images
    art=tmp_path/'generated.png';pix=QPixmap(210,258);pix.fill(QColor('coral'));pix.save(str(art))
    w._manga_cover_ready(w.manga_store.items(sid)[0]['id'],str(art),None)
    assert card._mosaic_images and card.art.pixmap().toImage().pixelColor(20,20)==QColor('coral')
    card.deleteLater()


def test_restricted_label_does_not_paint_an_opaque_text_bar(window):
    w,qt,*_=window;frame=QFrame();frame.setObjectName('card');frame.setStyleSheet(__import__('anime_hub.app',fromlist=['RESTRICTED_STYLE']).RESTRICTED_STYLE)
    frame.resize(120,100);label=QLabel('',frame);label.setGeometry(10,10,100,80);frame.show();qt.processEvents()
    image=frame.grab().toImage();assert image.pixelColor(40,40)==QColor('#1b0d18')
    frame.close();frame.deleteLater()
