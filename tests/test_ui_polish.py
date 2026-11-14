import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QPushButton

import anime_hub.app as app_module
from anime_hub.app import AniVaultDialog, Card, CollectionCard, ResponsiveLibraryGrid, WideCard, Window


def qt_app():
    return QApplication.instance() or QApplication([])


def row():
    return {"id":1,"metadata_json":"{}","title":"Test Show","episode_count":12,
            "watched_count":4,"favorite":0,"last_watched_episode":4}


def test_cards_are_streaming_scale():
    qt_app(); poster=Card(row(),show_progress=True); wide=WideCard(row(),next_episode=5)
    art=next(label for label in poster.findChildren(QLabel) if label.text()=="NO ARTWORK")
    assert art.width()*3==art.height()*2
    assert poster.width()-art.width()<=16
    assert poster.findChild(QProgressBar).value()==4
    assert poster.findChild(QProgressBar).height()<=4
    assert wide.width()>=470 and wide.height()>=174


def test_home_cards_use_fixed_alignment_regions():
    qt_app()
    long_row=row() | {
        "title":"This Is an Intentionally Very Long Anime Title That Must Wrap Cleanly",
        "metadata_json":'{"genres":["Fantasy","Adventure"]}',
    }
    continued=WideCard(long_row,next_episode=5)
    recent=WideCard(long_row,compact=True)
    favorite=WideCard(long_row,compact=True,favorite=True)

    for card in (continued,recent,favorite):
        title=card.findChild(QLabel,"cardTitle")
        muted=card.findChild(QLabel,"muted")
        assert title.wordWrap() and title.height()==42
        assert muted.height()==20

    progress=continued.findChild(QProgressBar)
    button=continued.findChild(QPushButton,"primary")
    assert progress.height()==7
    assert button.height()==38
    assert recent.findChild(QProgressBar).height()==7
    assert favorite.findChild(QProgressBar) is None


def test_vee_application_icon_is_available():
    qt_app()
    assert app_module.ICON_PATH.exists()
    assert (app_module.ASSET_DIR/"anivault_icon.png").exists()
    assert (app_module.ASSET_DIR/"anivault.ico").exists()
    window=Window()
    assert not window.windowIcon().isNull()
    window.close()


def test_sidebar_active_state_and_frameless_shell(tmp_path,monkeypatch):
    qt_app(); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    window=Window()
    assert window.windowFlags() & Qt.FramelessWindowHint
    window.show_home()
    assert window.nav_buttons["home"].property("active") is True
    window.show_library(state_filter="Favorites")
    assert window.nav_buttons["favorites"].property("active") is True
    assert window.nav_buttons["home"].property("active") is False
    window.show_library(category_filter="Watching")
    assert window.nav_buttons["watching"].property("active") is True
    window.show_settings()
    assert window.nav_buttons["settings"].property("active") is True
    window.close()


def test_responsive_library_grid_uses_width_without_recreating_cards():
    app=qt_app(); cards=[QLabel(str(i)) for i in range(24)]
    for card in cards: card.setFixedSize(228,120)
    grid=ResponsiveLibraryGrid(); grid.resize(500,800); grid.show()
    for card in cards: grid.add_card(card)
    app.processEvents(); narrow=grid._columns; identities=[id(card) for card in grid.cards]
    grid.resize(2380,800); app.processEvents()
    assert narrow==2
    assert 8 <= grid._columns <= 10
    assert [id(card) for card in grid.cards]==identities
    grid.resize(740,800); app.processEvents()
    assert grid._columns==3
    assert [id(card) for card in grid.cards]==identities
    grid.close()


def test_collection_card_selects_on_single_click_and_opens_on_double_click_or_enter():
    app=qt_app(); row={"id":7,"name":"Racing","item_count":3,"preview_metadata":"{}"}
    card=CollectionCard(row); selected=QSignalSpy(card.selected); opened=QSignalSpy(card.opened); card.show()
    QTest.mouseClick(card,Qt.LeftButton); assert selected.count()==1 and opened.count()==0
    QTest.mouseDClick(card,Qt.LeftButton); assert opened.count()==1
    card.setFocus()
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier))
    assert opened.count()==2
    card.close()


def test_dialog_and_menu_theme_rules_are_present():
    assert "QMessageBox" in app_module.STYLE and "QInputDialog" in app_module.STYLE
    assert "QMenu::right-arrow" in app_module.STYLE and "padding:9px 34px" in app_module.STYLE


def test_anivault_dialog_is_frameless_and_uses_custom_panel():
    qt_app(); dialog=AniVaultDialog(None,"Delete Collection","Only the collection will be removed.")
    assert dialog.windowFlags() & Qt.FramelessWindowHint
    assert dialog.findChild(QFrame,"vaultDialogPanel") is not None
    assert dialog.findChild(QLabel,"vaultDialogTitle").text()=="Delete Collection"
    dialog.close()
