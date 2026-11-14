"""Focus View and supplied branding runtime acceptance."""
import hashlib
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt,QEvent,QPoint
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QLabel,QPushButton,QComboBox,QTabWidget
from PySide6.QtTest import QTest
from anime_hub.app import Card,SeasonCard
from anime_hub.hub_ui import HomeTile,ArtworkHero
from anime_hub.branding import EmptyState,startup_splash
from test_cross_media import window,anime,remote,manga

def open_library(w):
    w.resize(1600,1000);w.show_library(view_mode='Individual Titles');QTest.qWait(50)
    page=w.stack.currentWidget()
    for _ in range(100):
        if any(c.isVisible() for c in page.findChildren(Card)):break
        QTest.qWait(10)
    return page

def rendered_card(page,kind=Card):
    # Deferred deletion can leave retired, hidden cards in the QObject tree.
    # Acceptance must target what the user can actually click.
    for _ in range(100):
        card=next((card for card in page.findChildren(kind) if card.isVisible()),None)
        if card is not None:return card
        QTest.qWait(10)
    raise AssertionError('No rendered '+kind.__name__+' in active page')

def test_single_click_pins_double_opens_no_first_navigation(window):
    w,qt,aid,*_=window;page=open_library(w);card=rendered_card(page)
    QTest.mouseClick(card,Qt.LeftButton,pos=QPoint(25,25));qt.processEvents()
    assert w.stack.currentWidget() is page and w._hub_pinned and w.context_rail.entity.local['id']==aid
    assert card.property('focusPinned') and w.context_rail.pin_button.isVisible()
    QTest.mouseDClick(card,Qt.LeftButton,pos=QPoint(25,25));qt.processEvents()
    assert w.current_view=='detail' and w.current_anime_id==aid and not w.context_rail.isVisible()

def test_delay_cancel_pin_unpin_and_intentional_selection(window,tmp_path):
    w,qt,aid,*_=window;second=anime(w.db,tmp_path/'Second',999);page=open_library(w);cards={c.anime_id:c for c in page.findChildren(Card)}
    qt.sendEvent(cards[aid],QEvent(QEvent.Enter));QTest.qWait(80);assert w.context_rail.entity is None
    qt.sendEvent(cards[aid],QEvent(QEvent.Leave));qt.sendEvent(cards[second],QEvent(QEvent.Enter));QTest.qWait(330)
    assert w.context_rail.entity.local['id']==second
    QTest.mouseClick(cards[aid],Qt.LeftButton);assert w._hub_pinned
    qt.sendEvent(cards[second],QEvent(QEvent.Enter));QTest.qWait(350);assert w.context_rail.entity.local['id']==aid
    w.context_rail.pin_button.click();qt.sendEvent(cards[second],QEvent(QEvent.Enter));QTest.qWait(330)
    assert not w._hub_pinned and w.context_rail.entity.local['id']==second
    QTest.mouseClick(cards[second],Qt.LeftButton);assert w._hub_pinned
    w.show_settings();QTest.qWait(350);assert not w._hub_hover_timer.isActive() and not w._hub_pinned and not w.context_rail.isVisible()

@pytest.mark.parametrize('kind',['local_manga','remote','restricted'])
def test_cards_use_same_selection_rules(window,tmp_path,kind):
    w,qt,aid,sid,*_=window;w.resize(1600,1000)
    if kind=='local_manga':w.show_manga_library();QTest.qWait(50);from anime_hub.manga_ui import MangaCard;card=w.stack.currentWidget().findChild(MangaCard);expected='manga_detail'
    else:
        scope='restricted' if kind=='restricted' else 'normal';w.db.set_setting('restricted_unlocked','1');w._set_status('Planning',scope,item=remote(881,'MANGA',scope=='restricted'));w.show_status_list('Planning',scope);QTest.qWait(50);card=w.stack.currentWidget().findChild(SeasonCard);expected='restricted_detail' if scope=='restricted' else 'airing_detail'
    page=w.stack.currentWidget();QTest.mouseClick(card,Qt.LeftButton);qt.processEvents();assert w.stack.currentWidget() is page and w._hub_pinned
    QTest.mouseDClick(card,Qt.LeftButton);qt.processEvents();assert w.current_view==expected

def test_home_child_button_is_immediate_and_does_not_open_details(window,monkeypatch):
    w,qt,aid,*_=window;w.resize(1600,1000);w.db.set_watched(w.db.media(aid)[0]['id'],True);w.show_home();QTest.qWait(50)
    tile=w.stack.currentWidget().findChild(HomeTile);page=w.stack.currentWidget();QTest.mouseClick(tile,Qt.LeftButton);assert w._hub_pinned and w.stack.currentWidget() is page
    calls=[];monkeypatch.setattr(w,'_continue_hub_entity',lambda entity:calls.append(entity.key))
    action=w.context_rail.findChild(QPushButton,'primary');QTest.mouseClick(action,Qt.LeftButton)
    assert len(calls)==1 and w.stack.currentWidget() is page
    assert not any(button.text() in {'Full Details','Open Full Details','All items & relations →'} for button in w.context_rail.findChildren(QPushButton))

def test_episode_preview_is_bounded_current_next_context(window,tmp_path):
    w,qt,aid,*_=window;folder=tmp_path/'Anime'
    for number in range(2,21):
        path=folder/f'{number:02}.mkv';path.write_bytes(b'read-only');w.db.upsert_media(aid,SimpleNamespace(path=path,kind='episode',season=1,episode=number))
    for row in w.db.media(aid)[:8]:w.db.set_watched(row['id'],True)
    page=open_library(w);card=rendered_card(page);QTest.mouseClick(card,Qt.LeftButton);qt.processEvents()
    buttons=w.context_rail.findChild(QLabel,'focusTitle').parent().findChild(__import__('PySide6.QtWidgets',fromlist=['QWidget']).QWidget,'focusItems').findChildren(QPushButton)
    assert len(buttons)==3 and any('Episode 9' in b.text() for b in buttons)
    assert w.context_rail.findChild(QTabWidget) is None and w.context_rail.findChild(QLabel,'focusCover').height()>158

def test_status_favorite_keep_pin_and_page_and_source_readonly(window):
    w,qt,aid,sid,book=window;digest=hashlib.sha256(book.read_bytes()).digest();page=open_library(w);card=rendered_card(page);QTest.mouseClick(card,Qt.LeftButton)
    w.context_rail.findChild(QComboBox,'hubStatus').activated.emit(3);qt.processEvents()
    assert w._hub_pinned and w.stack.currentWidget() is page and w.context_rail.entity.status=='Planning'
    w.context_rail.findChild(QPushButton,'focusFavorite').click();qt.processEvents()
    assert w.db.anime(aid)['favorite'] and w._hub_pinned and w.stack.currentWidget() is page
    assert '♥' in card.title_label.text() and hashlib.sha256(book.read_bytes()).digest()==digest

def test_stale_hover_cannot_cross_scope_or_deleted_card(window,tmp_path):
    w,qt,aid,*_=window;page=open_library(w);card=rendered_card(page);qt.sendEvent(card,QEvent(QEvent.Enter))
    w.db.set_setting('restricted_unlocked','1');w.show_restricted_home();QTest.qWait(350)
    assert w.context_rail.entity is None and not w._hub_hover_timer.isActive()
    w.lock_restricted();open_library(w);card=w.stack.currentWidget().findChild(Card);qt.sendEvent(card,QEvent(QEvent.Enter));card.deleteLater();qt.sendPostedEvents(None,QEvent.DeferredDelete);QTest.qWait(350)
    assert not w._hub_hover_timer.isActive()

def test_supplied_art_scope_one_main_illustration_and_small_fallback(window):
    w,qt,*_=window;w.resize(1600,1000);w.show_global_search('never-matches-a-title');QTest.qWait(30)
    state=w.stack.currentWidget().findChild(EmptyState);assert state.kind=='results' and state.art.isVisible() and w.sidebar.art.isVisible()
    assert state.art.pixmap().hasAlphaChannel()
    w.show_collections();QTest.qWait(30);assert any(s.kind=='empty' for s in w.stack.currentWidget().findChildren(EmptyState))
    w.db.set_setting('restricted_unlocked','1');w.show_restricted_home();QTest.qWait(30)
    hero=next(h for h in w.stack.currentWidget().findChildren(ArtworkHero) if h.property('brandIllustration'))
    assert getattr(hero,'branding_scope',None) is None and hero.safe_banner and w.sidebar.art.isVisible()
    w.lock_restricted();QTest.qWait(30)
    assert all(getattr(h,'branding_scope',None)!='restricted' for h in w.stack.currentWidget().findChildren(ArtworkHero))
    splash=startup_splash(qt);assert splash and splash.width()<=640 and splash.height()<=360;splash.close()

def test_franchise_selection_double_open_and_child_details(window,tmp_path):
    from test_v087 import franchise_fixture
    from anime_hub.polish_ui import CoverListCard
    w,qt,aid,*_=window;franchise_fixture(w,aid,tmp_path);w._library_cache_dirty=True;w.resize(1600,1000);w.show_library(view_mode='Franchises');QTest.qWait(60)
    page=w.stack.currentWidget();card=rendered_card(page,CoverListCard);assert card.property('franchiseLocalIds')
    QTest.mouseClick(card,Qt.LeftButton);assert w.stack.currentWidget() is page and w._hub_pinned
    assert w.context_rail.findChild(QLabel,'focusTitle').text()=='Initial D' and len(w._hub_focus_group['ids'])==2
    QTest.mouseDClick(card,Qt.LeftButton);qt.processEvents();assert w.current_view=='library_franchise'
    overview=w.stack.currentWidget();child=rendered_card(overview);QTest.mouseClick(child,Qt.LeftButton);assert w.stack.currentWidget() is overview
    QTest.mouseDClick(child,Qt.LeftButton);assert w.current_view=='detail'

def test_live_search_suggestion_keeps_direct_navigation(window,monkeypatch):
    w,qt,aid,*_=window;w.show_home();QTest.qWait(30);popup=w.global_suggestions
    w.global_search.setText('Shared');popup.changed('Shared');popup.timer.stop();qt.processEvents()
    entry=next(popup.item(i) for i in range(popup.count()) if popup.item(i).data(Qt.UserRole)[1].media_type=='ANIME')
    popup.open_item(entry);qt.processEvents();assert w.current_view=='detail' and w.current_anime_id==aid and not popup.isVisible()

def test_rail_layout_never_exceeds_viewport_for_long_copy(window):
    w,qt,aid,*_=window
    item={**remote(11),'description':'A very long synopsis with several words. '*30}
    w.db.set_metadata(aid,11,item);page=open_library(w);QTest.mouseClick(rendered_card(page),Qt.LeftButton);QTest.qWait(40)
    assert w.context_rail.body.widget().width()==w.context_rail.body.viewport().width()
    assert w.context_rail.findChild(QPushButton,'primary').width()<=w.context_rail.body.viewport().width()

def test_hidden_retired_card_cannot_navigate_from_late_input(window):
    w,qt,aid,*_=window;page=open_library(w);card=rendered_card(page);card.hide()
    QTest.mouseClick(card,Qt.LeftButton);QTest.mouseDClick(card,Qt.LeftButton)
    assert w.stack.currentWidget() is page and not w._hub_pinned
