"""Behavior regressions for the focused Windows V1.1.2 fixes."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from anime_hub.integrated_player import IntegratedPlayer, VideoSurface, PlayerInputOverlay

@pytest.mark.parametrize("surface_type", [VideoSurface, PlayerInputOverlay])
def test_slow_double_click_does_not_toggle_playback(surface_type):
    app = QApplication.instance()
    surface = surface_type()
    surface.resize(300, 200)
    surface.show()
    playback, fullscreen = [], []
    surface.toggle_playback.connect(lambda: playback.append(True))
    surface.toggle_fullscreen.connect(lambda: fullscreen.append(True))
    old_interval = app.doubleClickInterval()
    app.setDoubleClickInterval(420)
    try:
        QTest.mouseClick(surface, Qt.LeftButton)
        QTest.qWait(230)  # Previously the 180ms timer fired too early.
        assert playback == []
        QTest.mouseDClick(surface, Qt.LeftButton)
        QTest.mouseRelease(surface, Qt.LeftButton)
        QTest.qWait(460)
        assert fullscreen == [True]
        assert playback == []
        QTest.mouseClick(surface, Qt.LeftButton)
        QTest.qWait(460)
        assert playback == [True]
    finally:
        app.setDoubleClickInterval(old_interval)
        surface.close()


def test_player_hide_cancels_pending_click_and_show_restores_overlay():
    app = QApplication.instance()
    player = IntegratedPlayer()
    player.resize(900, 600)
    player.show()
    app.processEvents()
    playback = []
    player.video.toggle_playback.connect(lambda: playback.append(True))
    QTest.mouseClick(player.video, Qt.LeftButton)
    player.hide()
    QTest.qWait(app.doubleClickInterval() + 40)
    assert playback == []
    assert not player.pointer_timer.isActive()
    assert not player.input_overlay.isVisible()
    player.show()
    app.processEvents()
    player.set_fullscreen_mode(True)
    assert player.pointer_timer.isActive()
    QTest.mouseClick(player.video, Qt.LeftButton)
    player.close()
    QTest.qWait(app.doubleClickInterval() + 40)
    assert playback == []
    assert not player.pointer_timer.isActive()
    assert not player.input_overlay.isVisible()


@pytest.mark.parametrize("adult", [False, True])
def test_airing_episode_text_fits_two_lines_and_footer(adult):
    from PySide6.QtCore import QRect, Qt
    from anime_hub.app import SeasonCard
    item = {"id": 7, "title": {"english": "A Current Show"}, "format": "TV",
            "episodes": 1000, "isAdult": adult, "status": "RELEASING",
            "nextAiringEpisode": {"episode": 999}, "coverImage": {}}
    card = SeasonCard(item, True)
    card.show()
    QApplication.processEvents()
    badge = card.secondary
    assert badge.text().endswith("Next: Episode 999")
    assert len(badge.text().splitlines()) == 2
    bounds = badge.fontMetrics().boundingRect(QRect(0, 0, badge.width(), 1000),
        Qt.AlignCenter | Qt.TextWordWrap, badge.text())
    assert bounds.height() <= badge.height()
    assert badge.geometry().bottom() < card.height() - 8
    assert all(child.geometry().bottom() < card.height()
               for child in (card.secondary, card.note))
    card.close()



def test_reader_canvas_keys_dispatch_once_in_both_directions(tmp_path):
    import io
    import time
    import zipfile
    from PIL import Image
    from anime_hub.database import Database
    from anime_hub.local_manga_reader import LocalMangaReader
    book = tmp_path / "book.cbz"
    with zipfile.ZipFile(book, "w") as archive:
        for index in range(5):
            data = io.BytesIO()
            Image.new("RGB", (100, 150), "white").save(data, format="PNG")
            archive.writestr(f"{index}.png", data.getvalue())
    db = Database(tmp_path / "state.db")
    reader = LocalMangaReader(db, book, tmp_path / "cache")
    reader.show()
    reader.start()
    app = QApplication.instance()
    try:
        deadline = time.monotonic() + 5
        while reader.total != 5 and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert reader.total == 5
        reader.direction.setCurrentText("Left-to-Right")
        reader.go(1)
        reader.canvas.setFocus()
        QTest.keyClick(reader.canvas, Qt.Key_Right)
        assert reader.page == 2  # No shortcut + event-filter double dispatch.
        reader.direction.setCurrentText("Right-to-Left (Manga)")
        QTest.keyClick(reader.canvas, Qt.Key_Left)
        assert reader.page == 3
        fullscreen = []
        reader.fullscreen_requested.connect(lambda: fullscreen.append(True))
        QTest.keyClick(reader.canvas, Qt.Key_F)
        assert fullscreen == [True]
        reader.shutdown()
        QTest.keyClick(reader.canvas, Qt.Key_F)
        assert fullscreen == [True]
    finally:
        reader.shutdown()
        reader.worker.thread.join(5)
        assert not reader.worker.thread.is_alive()
        reader.close()
        db.connection.close()
