"""Restricted workspace navigation and lock boundary regressions."""
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton
from PySide6.QtCore import QObject, Signal, QByteArray
from shiboken6 import isValid
from test_cross_media import window, anime, manga
from anime_hub import app

REQUEST_PAGE = app.Window._request_discover_page
LOAD_ARTWORK = app.Window._load_remote_artwork


def test_workspace_routes_metrics_lock_and_restart(window, tmp_path):
    w, qt, normal, *_ = window
    private = anime(w.db, tmp_path / "Private", 91, True)
    private_manga, _ = manga(w.db, w.manga_store, tmp_path / "PrivateManga", 92, "restricted")
    w.db.set_personal_rating("ANIME", private, 9.5)
    w.db.set_personal_rating("MANGA", private_manga, 7)
    w.db.set_manual_status("Completed", "restricted", anime_id=private)
    w.db.set_setting("restricted_unlocked", "1")
    w.show_restricted_home()
    qt.processEvents()
    assert w.current_view == "restricted_home"
    assert w._restricted_workspace
    assert all(w.nav_buttons[key].isHidden() for key in w._normal_nav_keys)
    assert all(not w.nav_buttons[key].isHidden() for key in w._restricted_nav_keys)
    assert len(w._dashboard_data("restricted")[0]) == 1
    assert len(w._dashboard_data("restricted")[1]) == 1
    assert private not in w._dashboard_data("normal")[0]
    routes = (
        (lambda: w.show_library(scope="restricted", view_mode="Individual Titles"), "restricted_library"),
        (lambda: w.show_manga_library("restricted"), "restricted_manga_library"),
        (lambda: w.show_discover(True), "restricted_discover"),
        (lambda: w.show_collections("restricted"), "restricted_collections"),
        (lambda: w.show_statistics("restricted"), "restricted_statistics"),
    )
    for action, route in routes:
        action()
        QTest.qWait(25)
        assert w.current_view == route
        assert w.stack.currentWidget().property("restrictedPage")
    w.show_library(scope="restricted", view_mode="Individual Titles")
    QTest.qWait(80)
    assert {card.anime_id for card in w.stack.currentWidget().findChildren(app.Card)} == {private}
    w._select_hub_entity("restricted", "local:" + str(private))
    assert w.context_rail.entity.scope == "restricted"
    stale = w.stack.currentWidget()
    w.lock_restricted()
    qt.processEvents()
    assert not w._restricted_workspace
    assert w._hub_scope == "normal"
    assert w.context_rail.entity is None
    assert not w.global_search.text()
    assert not w._back_history and not w._forward_history
    assert not any(w.stack.widget(i).property("restrictedPage") for i in range(w.stack.count()))
    for action, _ in routes:
        action()
        assert not w.current_view.startswith("restricted")
    w._dispatch_route(("library", {"scope": "restricted"}))
    w.navigate_back()
    assert not w.current_view.startswith("restricted")
    assert w.db.personal_rating("ANIME", private) == 19
    assert w.db.personal_rating("MANGA", private_manga) == 14
    w.db.set_setting("restricted_unlocked", "1")
    w.close()
    qt.processEvents()
    reopened = app.Window()
    try:
        assert not reopened._organization_allowed("restricted")
        assert not reopened.current_view.startswith("restricted")
    finally:
        reopened.close()


def test_late_private_discovery_response_is_discarded(window, monkeypatch):
    w, qt, *_ = window
    # The fixture disables remote calls. Use the real dispatcher with a captured job.
    monkeypatch.setattr(w, "_request_discover_page", REQUEST_PAGE.__get__(w))
    callbacks = []
    monkeypatch.setattr(w, "_submit_discover_job", lambda key, work, success, failure: callbacks.append(success))
    w.db.set_setting("restricted_unlocked", "1")
    w.show_restricted_home()
    w._request_discover_page({"page": 1, "is_adult": True}, lambda result: callbacks.append("delivered"), lambda error: None)
    result = callbacks[0]
    w.lock_restricted()
    result({"items": [{"id": 987, "isAdult": True}]})
    assert "delivered" not in callbacks
    assert not w._discover_cache



def test_unlock_sidebar_and_private_artwork_session(window, monkeypatch):
    from PySide6.QtNetwork import QNetworkRequest

    w, qt, *_ = window
    monkeypatch.setattr(app.AniVaultDialog, "confirm", lambda *args: True)
    w.unlock_restricted()
    assert w.current_view == "restricted_home"
    toggle = next(button for button in w.sidebar.findChildren(QPushButton)
                  if button.toolTip() == "Expand or collapse navigation")
    toggle.click()
    assert w.sidebar.property("compact")
    assert not w.nav_buttons["restricted_lock"].text()
    assert w.nav_buttons["restricted_lock"].accessibleName()
    toggle.click()
    assert w.nav_buttons["restricted_lock"].text()

    class Reply(QObject):
        finished = Signal()

        def readAll(self):
            return QByteArray()

    reply = Reply()
    requests = []
    monkeypatch.setattr(w._network, "get", lambda request: (requests.append(request), reply)[1])
    target = QLabel()
    # A hidden private page may finish rendering after normal navigation.
    w.show_home()
    LOAD_ARTWORK(w, "https://example.invalid/private.png", target, 172, 258, "restricted")
    assert not w._remote_artwork_waiters
    assert len(w._restricted_artwork_waiters) == 1
    assert requests[0].attribute(QNetworkRequest.CacheSaveControlAttribute) is False
    w.lock_restricted()
    reply.finished.emit()
    assert not w._restricted_artwork_cache
    assert not w._restricted_artwork_waiters
    assert target.pixmap().isNull()
    target.deleteLater()



def test_private_player_context_keeps_workspace_authorization(window, tmp_path):
    from PySide6.QtWidgets import QWidget

    w, qt, *_ = window
    private = anime(w.db, tmp_path / "PrivatePlayer", 445, True)
    w.db.set_setting("restricted_unlocked", "1")
    w.show_restricted_home()
    # Verify the shell around the player without opening a native decoder.
    w.current_view = "player"
    w.current_anime_id = private
    page = QWidget()
    w.replace(page)
    assert page.property("restrictedPage")
    assert w._hub_scope == "restricted"
    assert w._restricted_workspace
    assert not w.nav_buttons["restricted_lock"].isHidden()
    w.lock_restricted()
    assert w._hub_scope == "normal"
    assert not w._restricted_workspace
