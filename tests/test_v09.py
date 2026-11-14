"""Runtime acceptance for the V0.9 shell; real local identities and unchanged source files."""
import hashlib
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QLabel,QPushButton,QLineEdit,QTabWidget,QComboBox
from PySide6.QtTest import QTest
from anime_hub.hub_ui import ArtworkHero,HomeTile
from anime_hub.app import Card,ResponsiveLibraryGrid
from test_cross_media import window,anime,remote


def test_home_uses_new_shell_real_items_and_single_search(window):
    w,qt,aid,sid,book=window;w.resize(1600,1000);w.show_home();qt.processEvents()
    page=w.stack.currentWidget();assert page.findChildren(HomeTile)
    assert page.findChildren(ArtworkHero) and not page.findChildren(QLineEdit)
    assert w.context_rail.isVisible() and w.context_rail.entity.local['id']==aid
    assert not any('Restricted' in tile.entity.title for tile in page.findChildren(HomeTile))
    assert w.global_search.parent() is w.title_bar
    QTest.keyClick(w,Qt.Key_K,Qt.ControlModifier);qt.processEvents();assert w.global_search.hasFocus()


def test_hover_selection_and_narrow_rail_without_grid_recreation(window):
    w,qt,aid,*_=window;w.resize(1600,1000);w.show_library();QTest.qWait(40);qt.processEvents();card=w.stack.currentWidget().findChild(Card)
    qt.sendEvent(card,QEvent(QEvent.Enter));QTest.qWait(330);qt.processEvents();assert w.context_rail.isVisible() and w.context_rail.entity.local['id']==aid
    identities=[id(c) for c in w.stack.currentWidget().findChildren(Card)]
    w.resize(1100,800);qt.processEvents();assert not w.context_rail.isVisible()
    assert identities==[id(c) for c in w.stack.currentWidget().findChildren(Card)]
    w.resize(1600,1000);qt.processEvents();assert w.context_rail.isVisible()
    assert identities==[id(c) for c in w.stack.currentWidget().findChildren(Card)]


def test_rail_actions_route_local_episode_and_manga(window,monkeypatch):
    w,qt,aid,sid,book=window;w.resize(1600,1000);w.show_home();qt.processEvents();calls=[]
    monkeypatch.setattr(w,'play',lambda *args:calls.append(args))
    episode=next(b for b in w.context_rail.findChildren(QPushButton) if b.text().startswith('▶  Episode'))
    episode.click();assert calls[0][0]==w.db.media(aid)[0]['path'] and calls[0][2]==aid
    w._select_hub_entity('normal','manga:'+str(sid));qt.processEvents()
    assert w.context_rail.findChild(QTabWidget) is None and any(label.text()=='READ NEXT' for label in w.context_rail.findChildren(QLabel))
    opened=[];monkeypatch.setattr(w,'open_manga_item',opened.append);w._continue_hub_entity(w.context_rail.entity)
    assert opened==[w.manga_store.items(sid)[0]['id']]
    w._open_hub_entity(w.context_rail.entity)
    assert w.current_view=='manga_detail' and w.current_manga_id==sid and not w.context_rail.isVisible()


def test_status_updates_only_rail_and_cards_source_readonly(window):
    w,qt,aid,sid,book=window;digest=hashlib.sha256(book.read_bytes()).digest();w.resize(1600,1000);w.show_home();qt.processEvents();page=w.stack.currentWidget();tiles=page.findChildren(HomeTile)
    picker=w.context_rail.findChild(QComboBox,'hubStatus');picker.activated.emit(3);qt.processEvents()
    assert w.db.manual_status('normal',anime_id=aid)=='Planning' and w.stack.currentWidget() is page
    assert page.findChildren(HomeTile)==tiles and w.context_rail.entity.status=='Planning'
    assert hashlib.sha256(book.read_bytes()).digest()==digest


def test_scope_change_clears_persistent_search_and_rail(window,tmp_path):
    w,qt,aid,*_=window;private=anime(w.db,tmp_path/'Private',300,True);w.db.set_setting('restricted_unlocked','1');w.resize(1600,1000);w.show_home();qt.processEvents()
    w.global_search.setText('Shared');w.show_restricted_home();qt.processEvents()
    assert w._hub_scope=='restricted' and not w.global_search.text() and w.context_rail.entity is None
    w._select_hub_entity('restricted','local:'+str(private));assert w.context_rail.entity.local['id']==private
    w.global_suggestions.results=[(remote(300,adult=True),None)];w.global_search.setText('Private')
    w.lock_restricted();qt.processEvents()
    assert w._hub_scope=='normal' and not w.global_search.text() and not w.global_suggestions.results
    assert w.context_rail.entity is None or w.context_rail.entity.scope=='normal'
    w._select_hub_entity('restricted','local:'+str(private));assert w.context_rail.entity is None or w.context_rail.entity.scope=='normal'


def test_home_never_features_private_local_title(window,tmp_path):
    w,qt,*_=window;private=anime(w.db,tmp_path/'Private',300,True);w.db.set_favorite(private,True);w.show_home();qt.processEvents()
    assert all(tile.entity.scope=='normal' and tile.entity.local['id']!=private for tile in w.stack.currentWidget().findChildren(HomeTile) if tile.entity.media_type=='ANIME')
    assert w.context_rail.entity.scope=='normal'


def test_shared_hero_fills_edges_at_multiple_aspects(window):
    _,qt,*_=window;hero=ArtworkHero();image=QPixmap(160,400);image.fill(QColor('#fff0a0'));hero.banner.setPixmap(image)
    for width,height in [(900,240),(300,420),(1400,280)]:
        hero.resize(width,height);hero.show();qt.processEvents();paint=hero.grab().toImage()
        # Even at the darkest edge, actual art contributes to the pixel.
        assert paint.pixelColor(10,height//2).red()>20
        assert paint.pixelColor(width-10,height//2).red()>100
        assert hero._scaled_banner.width()>=width and hero._scaled_banner.height()>=height
    hero.close();hero.deleteLater()


def test_status_hub_planning_and_utility_routes_keep_history(window):
    w,qt,*_=window;w.show_home();w.show_status_hub();qt.processEvents();assert w.active_nav_key=='status_hub'
    w.show_status_list('Planning');qt.processEvents();assert w.active_nav_key=='planning'
    w.navigate_back();qt.processEvents();assert w.current_view=='status_hub'
    w.show_collections();qt.processEvents();assert any(b.text()=='Franchise Groups' for b in w.stack.currentWidget().findChildren(QPushButton))


def test_discover_hero_uses_existing_response_no_extra_request(window,monkeypatch):
    w,qt,*_=window;requests=[];monkeypatch.setattr(w,'_request_discover_filters',lambda *_:None)
    monkeypatch.setattr(w,'_request_discover_page',lambda params,loaded,failed:requests.append((params,loaded)))
    w.show_discover();qt.processEvents();assert len(requests)==5
    requests[1][1]({'items':[remote(901)],'pageInfo':{'hasNextPage':False}});qt.processEvents()
    assert len(requests)==5 and any(hero.isVisible() for hero in w.stack.currentWidget().findChildren(ArtworkHero))
    assert not w.db.anime_by_anilist(901) if hasattr(w.db,'anime_by_anilist') else all(r['anilist_id']!=901 for r in w.db.anime_list())
