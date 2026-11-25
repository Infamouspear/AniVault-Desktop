"""Keep Qt's single application alive for the complete GUI test session.

Widgets and pixmap caches belong to that application; individual test modules
must not destroy/recreate the platform application underneath other GUI fixtures.
"""
import os
from pathlib import Path
import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope='session',autouse=True)
def gui_application():
    application=QApplication.instance() or QApplication([])
    # Windows offscreen Qt can start without discovering any installed fonts.
    # Use the real Windows UI font so geometry tests measure actual glyphs.
    if os.name == "nt" and application.platformName() == "offscreen" and not QFontDatabase.families():
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        assert font_path.is_file(), "Windows UI font required for offscreen layout tests"
        assert QFontDatabase.addApplicationFont(str(font_path)) >= 0
        application.setFont(QFont("Segoe UI", 9))
    yield application


@pytest.fixture(autouse=True)
def isolated_anilist_transport(tmp_path_factory,monkeypatch):
    from anime_hub import anilist_transport as transport
    cache_root=tmp_path_factory.mktemp('anilist-transport')
    pinned=transport.Scheduler(cache_root/'cache',default_limit=10000,min_interval=0)
    original=transport.configure
    monkeypatch.setattr(transport,'configure',lambda directory,scheduler=None:original(directory,scheduler or pinned))
    import sys
    if 'anime_hub.app' in sys.modules:monkeypatch.setattr(sys.modules['anime_hub.app'],'configure_anilist',transport.configure)
    transport.configure(cache_root/'root')
    yield pinned
