from __future__ import annotations

import json
import itertools
import queue
import faulthandler
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
import weakref
from datetime import datetime, timezone
from pathlib import Path
from shiboken6 import isValid

from PySide6.QtCore import QEvent, Qt, QThread, Signal, QObject, QSize, QStringListModel, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QDesktopServices, QColor, QFontMetrics, QIcon, QKeySequence, QLinearGradient, QPainter, QPixmap, QImageReader, QShortcut, QTextLayout, QTextOption
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkDiskCache, QNetworkReply
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QToolBar, QVBoxLayout, QWidget, QComboBox, QDialog,
    QMenu, QProgressBar, QCheckBox, QSizePolicy, QLayout, QTextEdit, QCompleter)
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtWidgets import QInputDialog

from .version import APP_VERSION, APP_USER_MODEL_ID
from .icons import NAV_ICONS, outline_icon
from .release_safety import prepare_existing_database, record_release, splash_preferences
from .media_cards import POSTER_WIDTH,POSTER_HEIGHT,POSTER_CARD_WIDTH,poster_layout,CARD_WIDTH,CARD_HEIGHT,COVER_WIDTH,COVER_HEIGHT,media_layout,text_slot,footer_slot,ContainedListWidget
from .database import Database
from .local_manga_reader import LocalMangaReader
from .manga_ui import MangaLibraryMixin
from .organization_ui import OrganizationMixin
from .related_ui import RelatedMixin
from .library_franchises import LibraryFranchiseMixin, build_franchises
from .desktop_ui import decorate_search
from .polish_ui import PolishMixin, SearchSuggestions, CoverListCard, DetailBackdrop, CompactFilterLayout
from .hub_ui import HubMixin, ArtworkHero, DetailRail, SelectionHook
from .downloads import Downloads
from .downloads_ui import DownloadsMixin
from .organization import media_type as organization_media_type
from .metadata import cache_artwork, search_anilist
from .playback import PlaybackMonitor, launch_vlc_session
from .integrated_player import IntegratedPlayer, clean_episode_label, format_time
from .anilist_integration import (AniListHTTPError, SEASON_PAGE_SIZE, current_anime_season, fetch_airing_catalog,
    fetch_discover_catalog, fetch_discover_filters, fetch_discover_page,
    fetch_anime_relations, fetch_season_page, fetch_user_list, next_anime_season, season_label, update_progress, validate_token)
from .scanner import scan
from .external_bookmarks import bookmark_record, bookmark_url, cached_artwork_path, source_label

# Keep the V0.1-V0.3 data directory so the rebrand never strands an existing library.
APP_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "AnimeHub"
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSET_DIR / ("anivault.ico" if sys.platform == "win32" else "anivault_icon.png")
ART_PACKS={
    "normal":{"sidebar":ASSET_DIR/"vee.png"},
    "restricted":{"sidebar":ASSET_DIR/"restricted_vee.png","hero":ASSET_DIR/"restricted_banner.png"},
}
CRASH_LOG = APP_DIR / "crash.log"
_FAULT_LOG_HANDLE = None

DISCOVER_SPECS={
    "Trending":{"sort":"TRENDING_DESC"},
    "Popular":{"sort":"POPULARITY_DESC"},
    "Upcoming":{"sort":"POPULARITY_DESC","status":"NOT_YET_RELEASED"},
    "Top Rated":{"sort":"SCORE_DESC"},
}
MANGA_COUNTRIES={"All countries":None,"Japan":"JP","South Korea":"KR","China":"CN","Taiwan":"TW"}
MANGA_SOURCES={"All sources":None,"Doujin / self-published":"DOUJINSHI"}
STATUS_COLORS={"Watching":"#55c7e8","Completed":"#6ed39a","Planning":"#ad83e6","Paused":"#e4ae55","Dropped":"#c66b79"}


def _status_markup(status,text=""):
    color_key="Watching" if status=="Reading" else status
    prefix=f'<span style="color:{STATUS_COLORS.get(color_key,"#9ba1a6")};font-weight:650">● {status}</span>' if status else ""
    return prefix+(f" <span style='color:#9ba1a6'>• {text}</span>" if prefix and text else text)
STYLE = """
QWidget { background:#090b10; color:#f4eef3; font-family:'Segoe UI'; font-size:14px; }
QLabel { background:transparent; }
QFrame#sidebar { background:#0b111a; border-right:1px solid #20293a; }
QFrame#card,QFrame#wideCard,QFrame#panel { background:#101823; border:1px solid #263246; border-radius:12px; }
QFrame#card:hover,QFrame#card:focus { border-color:#af6b94; }
QFrame#card[focusPinned="true"] { border:2px solid #ff5a8b; }
QFrame#card[posterCard="true"] {background:transparent;border:1px solid transparent;border-radius:8px;}
QFrame#card[posterCard="true"]:hover,QFrame#card[posterCard="true"]:focus {border-color:#815574;background:#171925;}
QFrame#card[posterCard="true"][focusPinned="true"] {border-color:#ff5a8b;background:#1a1825;}
QFrame#card[selected="true"] { border:2px solid #ff5a8b; background:#171825; }
QPushButton { background:#171b24; border:1px solid #303541; border-radius:12px; padding:7px 12px; }
QPushButton:hover { background:#252f42; border-color:#6f577e; }
QPushButton#primary { background:#ff3f78; color:white; border:0; font-weight:600; }
QPushButton#primary:hover { background:#ff5a8b; }
QPushButton#nav { background:transparent; border:0; text-align:left; padding:8px 10px; min-height:22px; font-size:13px; font-weight:550; }
QPushButton#nav:hover { background:#241523; color:#ff5a8b; }
QPushButton#nav[active="true"] { background:#321a2c; border:1px solid #82405f; border-left:4px solid #ff4f84; color:#ff82a7; font-weight:700; padding-left:7px; }
QFrame#titleBar { background:#080c12; border-bottom:1px solid #20293a; }
QPushButton#windowButton { background:transparent; border:0; border-radius:0; padding:0; font-size:16px; }
QPushButton#windowButton:hover { background:#252f42; }
QPushButton#closeButton { background:transparent; border:0; border-radius:0; padding:0; font-size:16px; }
QPushButton#closeButton:hover { background:#c42b4d; color:white; }
QLineEdit,QComboBox { background:#141923; border:1px solid #303a4a; border-radius:16px; padding:7px 12px; selection-background-color:#a83762; }
QComboBox { padding-right:26px; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; width:24px; border:0; background:transparent; }
QComboBox::down-arrow { image:url(__CHEVRON__); width:12px; height:12px; }
QLineEdit:focus,QComboBox:focus,QPushButton:focus {border:1px solid #b46c90;}
QToolTip {background:#171b25;color:#f8eef5;border:1px solid #584354;padding:5px;}
QScrollBar:vertical {background:#0c1017;width:9px;margin:2px;}
QScrollBar:horizontal {background:#0c1017;height:9px;margin:2px;}
QScrollBar::handle {background:#404757;border-radius:3px;min-height:22px;min-width:22px;}
QScrollBar::handle:hover {background:#766179;}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;}
QScrollBar::add-page,QScrollBar::sub-page {background:transparent;}
QTextEdit { background:#111925; border:1px solid #2c394c; border-radius:8px; padding:9px; selection-background-color:#ff3f78; }
QListWidget { border:1px solid #263246; border-radius:10px; background:#0e151f; outline:0; }
QListWidget::item { padding:10px; border-bottom:1px solid #202b3b; }
QListWidget::item:selected { background:#321a2a; color:#fff; border-left:3px solid #ff3f78; }
QScrollArea { border:0; }
QLabel#brand { font-size:25px; font-weight:750; color:#ffffff; }
QLabel#tagline,QLabel#muted { color:#9aa6b6; }
QLabel#eyebrow { color:#ff5a8b; font-size:12px; font-weight:700; }
QLabel#title { font-size:32px; font-weight:750; }
QFrame#overviewStats { background:#121720; border:1px solid #2b303c; border-radius:14px; }
QLabel#statValue { font-size:24px; font-weight:750; }
QFrame#sidebar[compact="true"] QPushButton#nav {text-align:center;padding:6px;}
QPushButton#localProfile {background:transparent;border:0;padding:0;}
QPushButton#filterChip {border-radius:14px;padding:5px 11px;background:transparent;border-color:transparent;}
QPushButton#filterChip:hover {border-color:#535060;}
QPushButton#filterChip:checked {background:#342635;border-color:#85516c;color:#ffbad0;}
QComboBox QAbstractItemView {background:#171b24;border:1px solid #414657;selection-background-color:#593048;outline:0;}
QLabel#heroTitle { font-size:36px; font-weight:750; }
QLabel#section { font-size:21px; font-weight:650; }
QLabel#cardTitle { font-weight:650; font-size:15px; }
QProgressBar { background:#2b3445; border:0; border-radius:3px; min-height:7px; max-height:7px; text-align:center; color:transparent; }
QProgressBar::chunk { background:#ff3f78; border-radius:3px; }
QStatusBar { background:#0b111a; color:#b9c0cb; border-top:1px solid #20293a; }
QDialog,QMessageBox,QInputDialog { background:#0d141e; color:#f4eef3; }
QDialog QLabel,QMessageBox QLabel,QInputDialog QLabel { color:#f4eef3; background:transparent; }
QDialog QPushButton,QMessageBox QPushButton,QInputDialog QPushButton { min-width:82px; padding:8px 15px; }
QMenu { background:#101823; color:#f4eef3; border:1px solid #354158; border-radius:8px; padding:6px; }
QMenu::item { padding:9px 34px 9px 16px; border-radius:5px; }
QMenu::item:selected { background:#321a2c; color:#ff82a7; }
QMenu::item:disabled { color:#6f7785; }
QMenu::separator { height:1px; background:#2a3445; margin:5px 8px; }
QMenu::right-arrow { right:10px; }
QFrame#vaultDialogPanel { background:#101823; border:1px solid #3b4860; border-radius:14px; }
QLabel#vaultDialogTitle { font-size:20px; font-weight:700; color:#ffffff; }
"""
STYLE=STYLE.replace("__CHEVRON__", (ASSET_DIR/"icons"/"chevron-down.svg").as_posix())

RESTRICTED_STYLE=STYLE+"""
QWidget { background:#0d080d; color:#fff2f6; }
QLabel { background:transparent; }
QFrame#sidebar { background:#160912; border-right:1px solid #4a1731; }
QFrame#card,QFrame#wideCard,QFrame#panel { background:#1b0d18; border-color:#5b203d; }
QPushButton { background:#2a1122; border-color:#6b294b; }
QPushButton:hover { background:#46162f; border-color:#d94b86; }
QPushButton#primary { background:#d62f70; }
QPushButton#nav[active="true"] { background:#50152f; border-color:#a43365; border-left-color:#ff4f9a; color:#ff9fc3; }
QLabel#eyebrow { color:#ff5795; }
QProgressBar::chunk { background:#ee3f87; }
"""

_ARTWORK_PIXMAP_CACHE={}
_ARTWORK_CACHE_LIMIT=384


def _bound_pixmap_cache(cache):
    limit=64*1024*1024
    size=sum(p.width()*p.height()*max(1,p.depth()//8) for p in cache.values())
    while len(cache)>_ARTWORK_CACHE_LIMIT or size>limit:
        key=next(iter(cache));pixmap=cache.pop(key);size-=pixmap.width()*pixmap.height()*max(1,pixmap.depth()//8)


def _scaled_artwork(path,width,height):
    if not path or not Path(path).exists(): return QPixmap()
    try: stamp=Path(path).stat().st_mtime_ns
    except OSError: return QPixmap()
    key=(str(path),stamp,int(width),int(height))
    cached=_ARTWORK_PIXMAP_CACHE.get(key)
    if cached is not None: return cached
    reader=QImageReader(str(path));reader.setAutoTransform(True);size=reader.size()
    if size.isValid():reader.setScaledSize(size.scaled(width,height,Qt.KeepAspectRatioByExpanding))
    image=reader.read()
    if image.isNull():return QPixmap()
    scaled=QPixmap.fromImage(image).scaled(width,height,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
    _ARTWORK_PIXMAP_CACHE[key]=scaled;_bound_pixmap_cache(_ARTWORK_PIXMAP_CACHE)
    return scaled


class ScanWorker(QThread):
    progress = Signal(int, int, str)
    status = Signal(str)
    finished_count = Signal(int)
    failed = Signal(str)
    def __init__(self, root, db_path):
        super().__init__(); self.root=Path(root); self.db_path=db_path
    def run(self):
        db = None;started=time.perf_counter()
        try:
            db=Database(self.db_path)
            count=scan(self.root, db, lambda a,b,c:self.progress.emit(a,b,c),
                       self.db_path.parent/"scanner_diagnostics.log", self.status.emit,
                       self.isInterruptionRequested)
            _append_playback_log(f"ScannerComplete elapsed_ms={(time.perf_counter()-started)*1000:.0f} releases={count} cancelled={self.isInterruptionRequested()}")
            self.finished_count.emit(count)
        except Exception:
            details=traceback.format_exc()
            _append_crash_log("Background scan exception\n"+details)
            self.failed.emit(details)
        finally:
            if db is not None:
                db.connection.close()


class AniListWorker(QThread):
    succeeded=Signal(object)
    failed=Signal(object)
    def __init__(self,operation,*args):
        super().__init__(); self.operation=operation; self.args=args
    def run(self):
        try: self.succeeded.emit(self.operation(*self.args))
        except Exception as exc: self.failed.emit(exc)


class DiscoverQueueWorker(QObject):
    """One persistent discovery worker; prevents a burst of short-lived QThreads."""
    succeeded = Signal(str, object)
    failed = Signal(str, object)
    def __init__(self):
        super().__init__(); self._jobs=queue.PriorityQueue(); self._sequence=itertools.count(); self._stopping=False; self._thread=None
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stopping=False; self._thread=threading.Thread(target=self.run,name="AniVaultDiscoverQueue",daemon=True); self._thread.start()
    def isRunning(self): return bool(self._thread and self._thread.is_alive())
    def submit(self,key,operation,priority=False):
        if self._stopping:return
        self._jobs.put((0 if priority else 1,next(self._sequence),key,operation)); self.start()
    def stop(self):
        self._stopping=True
        while True:
            try:self._jobs.get_nowait()
            except queue.Empty:break
    def wait(self,timeout=3000):
        if self._thread: self._thread.join(max(0,timeout)/1000)
    def run(self):
        while not self._stopping:
            try: _,_,key,operation=self._jobs.get(timeout=.2)
            except queue.Empty: continue
            if self._stopping: break
            try:
                result=operation()
                if not self._stopping:self.succeeded.emit(key,result)
            except Exception as exc:
                if not self._stopping:self.failed.emit(key,exc)


class AniVaultDialog(QDialog):
    """Frameless, reusable AniVault-owned prompt without native message-box chrome."""
    def __init__(self,parent,title,message="",value=None,multiline=False,buttons=(("Cancel",None),("Confirm",True))):
        super().__init__(parent,Qt.Dialog|Qt.FramelessWindowHint); self.result_value=None; self.setModal(True); self.setAttribute(Qt.WA_TranslucentBackground,True); self.setMinimumWidth(430)
        shell=QVBoxLayout(self); shell.setContentsMargins(10,10,10,10); panel=QFrame(); panel.setObjectName("vaultDialogPanel"); shell.addWidget(panel)
        layout=QVBoxLayout(panel); layout.setContentsMargins(24,22,24,22); layout.setSpacing(14)
        heading=QLabel(title); heading.setObjectName("vaultDialogTitle"); layout.addWidget(heading)
        if message: copy=QLabel(message); copy.setWordWrap(True); copy.setObjectName("muted"); layout.addWidget(copy)
        self.editor=None
        if value is not None:
            self.editor=QTextEdit() if multiline else QLineEdit(); self.editor.setPlainText(value) if multiline else self.editor.setText(value); self.editor.setMinimumHeight(110 if multiline else 38); layout.addWidget(self.editor)
        actions=QHBoxLayout(); actions.addStretch()
        for label,result in buttons:
            button=QPushButton(label); button.setObjectName("primary" if result is not None and result is not False else "")
            button.clicked.connect(lambda _,r=result:self._finish(r)); actions.addWidget(button)
        layout.addLayout(actions)
    def _finish(self,result): self.result_value=result; self.accept() if result is not None else self.reject()
    def text_value(self): return self.editor.toPlainText() if isinstance(self.editor,QTextEdit) else self.editor.text()
    @classmethod
    def prompt(cls,parent,title,message,value="",multiline=False):
        dialog=cls(parent,title,message,value,multiline); ok=dialog.exec()==QDialog.Accepted; return (dialog.text_value(),ok)
    @classmethod
    def confirm(cls,parent,title,message,confirm="Confirm"):
        dialog=cls(parent,title,message,None,False,(("Cancel",None),(confirm,True))); return dialog.exec()==QDialog.Accepted
    @classmethod
    def choose(cls,parent,title,message,choices):
        dialog=cls(parent,title,message,None,False,tuple(choices)+(("Cancel",None),)); dialog.exec(); return dialog.result_value
    @classmethod
    def alert(cls,parent,title,message): cls(parent,title,message,None,False,(("Close",True),)).exec()


class MatchDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent); self.setWindowTitle("Match anime"); self.resize(600,420); self.selected=None
        layout=QVBoxLayout(self); self.search=QLineEdit(title); layout.addWidget(self.search)
        button=QPushButton("Search AniList"); layout.addWidget(button); self.results=QListWidget(); self.results.setIconSize(QSize(70,100)); layout.addWidget(self.results)
        save=QPushButton("Save Match"); save.setObjectName("primary"); layout.addWidget(save)
        button.clicked.connect(self.do_search); save.clicked.connect(self.save)
        self.matches=[]; self.do_search()
    def do_search(self):
        self.results.clear()
        try:
            self.matches=search_anilist(self.search.text())
            for m in self.matches:
                t=m["title"].get("english") or m["title"].get("romaji")
                details=f"{t}\n{m.get('seasonYear') or '—'}  •  {m.get('format') or '—'}  •  {m.get('episodes') or '—'} episodes"
                item=QListWidgetItem(details)
                cover=(m.get("coverImage") or {}).get("large") or (m.get("coverImage") or {}).get("extraLarge")
                if cover:
                    try:
                        request=urllib.request.Request(cover,headers={"User-Agent":"AniVault/0.6"})
                        with urllib.request.urlopen(request,timeout=10) as response: data=response.read()
                        pixmap=QPixmap(); pixmap.loadFromData(data)
                        if not pixmap.isNull(): item.setIcon(QIcon(pixmap))
                    except Exception: pass
                self.results.addItem(item)
        except Exception as exc: AniVaultDialog.alert(self,"AniList Error",str(exc))
    def save(self):
        row=self.results.currentRow()
        if row>=0: self.selected=self.matches[row]; self.accept()


class TwoLineLabel(QLabel):
    """A fixed-height title that wraps once and elides any remaining text."""
    def paintEvent(self,event):
        painter=QPainter(self); painter.setPen(self.palette().windowText().color()); painter.setFont(self.font())
        width=max(1,self.contentsRect().width()); value=self.text()
        if not value:painter.end();return
        layout=QTextLayout(value,self.font()); option=QTextOption(); option.setWrapMode(QTextOption.WordWrap); layout.setTextOption(option)
        layout.beginLayout(); first=layout.createLine(); first.setLineWidth(width); second=layout.createLine();
        if second.isValid(): second.setLineWidth(width)
        layout.endLayout(); metrics=QFontMetrics(self.font()); line_height=self.height()//2
        first_text=value[first.textStart():first.textStart()+first.textLength()].strip()
        painter.drawText(0,0,width,line_height,Qt.AlignLeft|Qt.AlignVCenter,first_text)
        if second.isValid():
            remaining=value[second.textStart():].strip()
            second_text=metrics.elidedText(remaining,Qt.ElideRight,width)
            painter.drawText(0,line_height,width,self.height()-line_height,Qt.AlignLeft|Qt.AlignVCenter,second_text)
        painter.end()


class MultiSelectPicker(QPushButton):
    """Browseable, searchable multi-select picker; no AniList values need typing."""
    changed=Signal()
    def __init__(self,label,parent=None):
        super().__init__(label,parent); self.label=label; self.options=[]; self._selected=[]; self.clicked.connect(self.open_picker)
    def set_options(self,values): self.options=sorted(dict.fromkeys(str(value) for value in values if value),key=str.casefold)
    def selected(self): return list(self._selected)
    def set_selected(self,values): self._selected=list(dict.fromkeys(values or [])); self._refresh()
    def clear_selection(self): self._selected=[]; self._refresh()
    def _refresh(self): self.setText(f"{self.label} ({len(self._selected)})" if self._selected else self.label); self.setToolTip(", ".join(self._selected))
    def open_picker(self):
        dialog=QDialog(self.window(),Qt.Dialog|Qt.FramelessWindowHint); dialog.setModal(True); dialog.setMinimumSize(420,520); shell=QVBoxLayout(dialog); panel=QFrame(); panel.setObjectName("vaultDialogPanel"); shell.addWidget(panel); layout=QVBoxLayout(panel)
        heading=QLabel(f"Select {self.label}"); heading.setObjectName("vaultDialogTitle"); layout.addWidget(heading); search=QLineEdit(); search.setPlaceholderText(f"Search {self.label.lower()}…"); layout.addWidget(search); listing=QListWidget(); layout.addWidget(listing,1)
        for value in self.options:
            item=QListWidgetItem(value); item.setFlags(item.flags()|Qt.ItemIsUserCheckable); item.setCheckState(Qt.Checked if value in self._selected else Qt.Unchecked); listing.addItem(item)
        search.textChanged.connect(lambda text:[listing.item(i).setHidden(text.casefold() not in listing.item(i).text().casefold()) for i in range(listing.count())])
        actions=QHBoxLayout(); clear=QPushButton("Clear"); cancel=QPushButton("Cancel"); apply=QPushButton("Apply"); apply.setObjectName("primary"); actions.addWidget(clear); actions.addStretch(); actions.addWidget(cancel); actions.addWidget(apply); layout.addLayout(actions)
        clear.clicked.connect(lambda:[listing.item(i).setCheckState(Qt.Unchecked) for i in range(listing.count())]); cancel.clicked.connect(dialog.reject); apply.clicked.connect(dialog.accept)
        if dialog.exec()==QDialog.Accepted:
            self._selected=[listing.item(i).text() for i in range(listing.count()) if listing.item(i).checkState()==Qt.Checked]; self._refresh(); self.changed.emit()


class ViewAllCard(QFrame):
    clicked=Signal()
    def __init__(self,heading):
        super().__init__(); self.setObjectName("card"); self.setFixedSize(CARD_WIDTH,374); layout=QVBoxLayout(self); layout.addStretch(); icon=QLabel("→"); icon.setAlignment(Qt.AlignCenter); icon.setStyleSheet("font-size:42px;color:#ff5a8b"); layout.addWidget(icon); title=QLabel(f"View All {heading}"); title.setObjectName("section"); title.setAlignment(Qt.AlignCenter); title.setWordWrap(True); layout.addWidget(title); hint=QLabel("Keep browsing"); hint.setObjectName("muted"); hint.setAlignment(Qt.AlignCenter); layout.addWidget(hint); layout.addStretch()
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit()


from .media_cards import card_input


class Card(QFrame):
    clicked = Signal(int)
    continue_clicked = Signal(int)
    def __init__(self,row,show_progress=False,next_episode=None,timings=None,manual_status=None):
        super().__init__();self.anime_id=row["id"];self.setObjectName("card");lay=poster_layout(self);card_input(self,lambda:self.clicked.emit(self.anime_id))
        art=QLabel("NO ARTWORK");art.setAlignment(Qt.AlignCenter);art.setFixedSize(POSTER_WIDTH,POSTER_HEIGHT);art.setStyleSheet("background:#171f2b;border-radius:8px;color:#707d8c");lay.addWidget(art)
        metadata=json.loads(row["metadata_json"] or "{}")
        self._poster_art=art;self._poster_path=metadata.get("cover_path")
        titles=metadata.get("title") or {};name=titles.get("english") or titles.get("romaji") or row["title"] or "Unknown Anime"
        label=TwoLineLabel(name);label.setObjectName("cardTitle");label.setFixedHeight(36);label.setToolTip(name);lay.addWidget(label)
        episodes=row["episode_count"] or 0;watched=row["watched_count"] or 0
        self._favorite=bool(row["favorite"]);self._base_title=name;self.title_label=label
        self._episodes=episodes;self._watched=watched
        self.set_favorite(self._favorite)
        self.status_label=text_slot(lay,'muted',20);self.set_manual_status(manual_status)
        if next_episode:
            footer=footer_slot(lay)
            box=QHBoxLayout(footer);box.setContentsMargins(0,0,0,0);button=QPushButton(f"Continue Episode {next_episode}");button.setFixedHeight(28);button.setStyleSheet('padding:3px 7px');button.clicked.connect(lambda:self.continue_clicked.emit(self.anime_id));box.addWidget(button)
        bar=QProgressBar();bar.setRange(0,max(episodes,1));bar.setValue(watched);bar.setTextVisible(False);bar.setFixedHeight(3);bar.setVisible(0<watched<episodes);lay.addWidget(bar);card_input(self)
    def paintEvent(self,event):
        super().paintEvent(event)
        if self._poster_path:
            path,self._poster_path=self._poster_path,None
            pixmap=_scaled_artwork(path,POSTER_WIDTH,POSTER_HEIGHT)
            if not pixmap.isNull():self._poster_art.setPixmap(pixmap)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit(self.anime_id)
    def set_manual_status(self,status):
        state=status or ('Completed' if self._episodes and self._watched>=self._episodes else 'Watching' if self._watched else '')
        count=(f'{self._watched}/{self._episodes}' if 0<self._watched<self._episodes else f'{self._episodes} episodes' if self._episodes else '')
        self.status_label.setText(' · '.join(filter(None,(state,count))))
    def set_favorite(self,value):
        self._favorite=bool(value);self.title_label.setText(('♥  ' if value else '')+self._base_title)


class SeasonCard(QFrame):
    clicked=Signal(int)
    save_toggled=Signal(int,bool)
    def __init__(self,item,in_library=False,artwork_loader=None,show_save=False,saved=False,manual_status=None,compact=False):
        show_save=False # AniList later intent belongs to Planning, never Saved.
        super().__init__();self.item=item;self.saved_scope="normal";self.setObjectName("card");layout=media_layout(self);
        if compact:self.setProperty("posterCard",True);self.setFixedHeight(374)
        card_input(self,lambda:self.clicked.emit(int(self.item["id"])))
        art=QLabel("LOADING ARTWORK");art.setAlignment(Qt.AlignCenter);art.setFixedSize(COVER_WIDTH,COVER_HEIGHT);art.setStyleSheet("background:#171f2b;border-radius:8px;color:#707d8c");layout.addWidget(art)
        cover=(item.get('coverImage') or {}).get('extraLarge') or (item.get('coverImage') or {}).get('large')
        if cover and artwork_loader:artwork_loader(cover,art,COVER_WIDTH,COVER_HEIGHT)
        titles=item.get('title') or {};name=titles.get('english') or titles.get('romaji') or 'Untitled';title=TwoLineLabel(name);title.setObjectName('cardTitle');title.setFixedHeight(42);title.setToolTip(name);layout.addWidget(title)
        is_manga=item.get('type')=='MANGA';count=(str(item['chapters'])+' chapters') if is_manga and item.get('chapters') else (str(item['episodes'])+' eps') if not is_manga and item.get('episodes') else ''
        self._status_summary=' · '.join(str(value).replace('_',' ').title() for value in (item.get('format'),count) if value) or ('Manga' if is_manga else 'Anime')
        self.status_label=text_slot(layout,'muted',20);self.status_label.setTextFormat(Qt.RichText);self.set_manual_status(manual_status)
        state={'RELEASING':'Publishing' if is_manga else 'Currently airing','FINISHED':'Finished','NOT_YET_RELEASED':'Upcoming'}.get(item.get('status'),'Status unavailable');airing=item.get('nextAiringEpisode') or {}
        if not is_manga and airing.get('episode') and item.get('status')!='FINISHED':state=f"Next: Episode {airing['episode']}"
        value=('18+ · ' if item.get('isAdult') else '')+('◈ In Vault' if in_library else 'AniList')+' · '+state
        self.secondary=text_slot(layout,'seasonLocalMetadata' if in_library else 'seasonRemoteMetadata',30);self.secondary.setAlignment(Qt.AlignCenter);self.secondary.setStyleSheet('color:#ff6a96' if in_library else 'color:#a89ab8');self.secondary.setToolTip(value);self.secondary.setWordWrap(True);self.secondary.setFixedHeight(36);self.secondary.setText('\n'.join(value.rsplit(' · ',1)))
        if compact:
            self.secondary.setFixedHeight(20);self.secondary.setAlignment(Qt.AlignLeft)
            self.secondary.setText(('In Vault · ' if in_library else '')+state)
        reason=item.get('_recommendation_reason') or '';self.note=TwoLineLabel(reason);self.note.setObjectName('recommendationReason' if reason else 'mediaNote');self.note.setFixedHeight(26);self.note.setToolTip(reason);self.note.setStyleSheet('color:#c7becd;font-size:11px');layout.addWidget(self.note)
        if compact and not reason:self.note.hide()
        if show_save:
            footer=footer_slot(layout)
            box=QHBoxLayout(footer);box.setContentsMargins(0,0,0,0);self.save_button=QPushButton('Saved' if saved else 'Save');self.save_button.setFixedHeight(28);self.save_button.setStyleSheet('padding:3px 7px');self.save_button.setProperty('saved',saved);self.save_button.clicked.connect(self._toggle_saved);box.addWidget(self.save_button)
        elif not compact:layout.addSpacing(28)
        layout.addSpacing(6);card_input(self)
    def _toggle_saved(self):
        value=not bool(self.save_button.property('saved'));self.save_button.setProperty('saved',value);self.save_button.setText('Saved' if value else 'Save');self.save_toggled.emit(int(self.item['id']),value)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit(int(self.item['id']))
    def set_manual_status(self,status):
        self.status_label.setText(_status_markup('Reading' if status=='Watching' and self.item.get('type')=='MANGA' else status,self._status_summary))


class AiringScrollArea(QScrollArea):
    viewport_resized=Signal(int,str)
    def __init__(self,context="Airing",parent=None):
        super().__init__(parent); self.context=context; self.setObjectName("airingScroll"); self.setWidgetResizable(True); self._last_emitted_width=None; self._applied_viewport_width=None
        self._settle_timers=[]
        for delay in (0,60,180,360):
            timer=QTimer(self); timer.setSingleShot(True); timer.setInterval(delay); timer.timeout.connect(lambda reason=f"deferred-{delay}ms":self._emit_viewport(reason)); self._settle_timers.append(timer)
    def _emit_viewport(self,reason):
        width=self.viewport().contentsRect().width()
        if self._last_emitted_width==width: return
        self._last_emitted_width=width
        _append_playback_log(f"Airing viewport event section={self.context} reason={reason} scroll_size={self.width()}x{self.height()} viewport_size={width}x{self.viewport().height()}")
        self.viewport_resized.emit(width,reason)
    def schedule_settled_layout(self,reason="scheduled"):
        self._emit_viewport(reason)
        for timer in self._settle_timers: timer.start()
    def resizeEvent(self,event):
        super().resizeEvent(event); self.schedule_settled_layout("resize-event")
    def showEvent(self,event):
        super().showEvent(event); self.schedule_settled_layout("show-event")


class ResponsiveSeasonGrid(QWidget):
    _next_grid_id=1
    def __init__(self,cards,parent=None,context="Airing"):
        super().__init__(parent); self.grid_id=ResponsiveSeasonGrid._next_grid_id; ResponsiveSeasonGrid._next_grid_id+=1; self.context=context
        self.cards=list(cards); self.grid=QGridLayout(self); self.grid.setContentsMargins(0,0,0,0); self.grid.setSpacing(12); self.grid.setAlignment(Qt.AlignTop|Qt.AlignLeft); self._columns=0; self._viewport_width=None; self._batch_inserting=False
        self._reflow_timer=QTimer(self); self._reflow_timer.setSingleShot(True); self._reflow_timer.timeout.connect(lambda:self._reflow(True))
        self.destroyed.connect(lambda _=None,gid=self.grid_id,section=self.context:_append_playback_log(f"AiringGrid destroyed id={gid} section={section}"))
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.MinimumExpanding)
        _append_playback_log(f"AiringGrid created id={self.grid_id} section={self.context} object_address={hex(id(self))} cards={len(self.cards)}")
        self._reflow(True,"created")
    def set_viewport_width(self,width,reason="viewport"):
        self._viewport_width=max(228,int(width)); self._reflow(False,reason)
    def _schedule_reflow(self,delay=0):
        self._reflow_timer.start(max(0,int(delay)))
    def _update_minimum_height(self,columns=None):
        columns=max(1,int(columns or self._columns or 1)); rows=(len(self.cards)+columns-1)//columns
        card_height=max((card.height() for card in self.cards),default=0); spacing=self.grid.verticalSpacing()
        self.setMinimumHeight(rows*card_height+max(0,rows-1)*spacing)
    def append_cards(self,cards):
        cards=list(cards)
        if not cards: return
        before=len(self.cards); viewport_before=self._viewport_width or self.width(); columns_before=self._columns
        self.cards.extend(cards)
        available=self._viewport_width or self.width(); columns=self._columns or max(1,max(228,available)//240); self._columns=columns
        _append_playback_log(f"Append paint begin\ngrid id={self.grid_id}\ncards before={before} after={len(self.cards)}\nviewport width before={viewport_before}\ncolumns before={columns_before}")
        self._batch_inserting=True; self.setUpdatesEnabled(False); self.grid.setEnabled(False)
        try:
            self._update_minimum_height(columns)
            for index,card in enumerate(cards,start=before): self.grid.addWidget(card,index//columns,index%columns)
            self.grid.setEnabled(True); self.grid.invalidate(); self.grid.activate(); self.updateGeometry()
        finally:
            self.grid.setEnabled(True); self._batch_inserting=False; self.setUpdatesEnabled(True)
        self.update()
        _append_playback_log(f"AiringGrid batch append id={self.grid_id} section={self.context} before={before} appended={len(cards)} after={len(self.cards)} columns={columns} layout_passes=1 updates_scope=grid\nviewport width after={self._viewport_width or self.width()}\ncolumns after={self._columns}\nfull reflow triggered=false\nexisting widgets recreated=0\nupdate calls=1 batched=true\nAppend paint end")
    def clear_cards(self):
        self.replace_cards([])
    def replace_cards(self,cards):
        old=list(self.cards); self.cards=list(cards)
        while self.grid.count(): self.grid.takeAt(0)
        for card in old:
            if card not in self.cards: card.setParent(None); card.deleteLater()
        self._reflow(True,"reuse-replace")
        _append_playback_log(f"AiringGrid reused id={self.grid_id} section={self.context} cards={len(self.cards)}")
    def _reflow(self,force=False,reason="resize"):
        if self._batch_inserting: return
        available=self._viewport_width or self.width()
        columns=max(1,max(228,available)//240)
        if not force and columns==self._columns and self.grid.count()==len(self.cards): return
        self._columns=columns
        self._update_minimum_height(columns)
        while self.grid.count(): self.grid.takeAt(0)
        for index,card in enumerate(self.cards): self.grid.addWidget(card,index//columns,index%columns)
        _append_playback_log(f"AiringGrid reflow id={self.grid_id} section={self.context} reason={reason} widget_size={self.width()}x{self.height()} available_width={available} computed_columns={columns} cards={len(self.cards)}")
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not self._batch_inserting: self._reflow()
    def _deferred_reflow(self): self._schedule_reflow()
    def showEvent(self,event):
        super().showEvent(event); self._schedule_reflow()


class ResponsiveLibraryGrid(QWidget):
    """Responsive local-card grid which repositions, but never recreates, cards on resize."""
    def __init__(self,card_width=228,spacing=12,parent=None):
        super().__init__(parent); self.card_width=int(card_width); self.spacing=int(spacing); self.cards=[]; self._columns=0
        self.grid=QGridLayout(self); self.grid.setSizeConstraint(QLayout.SetNoConstraint); self.grid.setContentsMargins(0,0,0,0); self.grid.setSpacing(self.spacing); self.grid.setAlignment(Qt.AlignTop|Qt.AlignLeft)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.MinimumExpanding)
    def columns_for_width(self,width):
        return max(1,(max(self.card_width,int(width))+self.spacing)//(self.card_width+self.spacing))
    def _update_height(self):
        rows=(len(self.cards)+max(1,self._columns)-1)//max(1,self._columns)
        heights=[card.height() for card in self.cards]
        self.setMinimumHeight(rows*max(heights,default=0)+max(0,rows-1)*self.spacing)
    def add_card(self,card):
        index=len(self.cards); self.cards.append(card)
        columns=self._columns or self.columns_for_width(self.width()); self._columns=columns
        self.grid.addWidget(card,index//columns,index%columns); self._update_height()
    def add_cards(self,cards):
        cards=list(cards)
        if not cards:return
        start=len(self.cards);columns=self._columns or self.columns_for_width(self.width());self._columns=columns
        self.setUpdatesEnabled(False)
        try:
            self.cards.extend(cards)
            for index,card in enumerate(cards,start):self.grid.addWidget(card,index//columns,index%columns)
            self._update_height();self.updateGeometry()
        finally:self.setUpdatesEnabled(True)
        self.update()
    def clear_cards(self):
        old=list(self.cards); self.cards=[]
        while self.grid.count(): self.grid.takeAt(0)
        for card in old: card.setParent(None); card.deleteLater()
        self._update_height()
    def _reflow(self,force=False):
        columns=self.columns_for_width(self.contentsRect().width())
        if not force and columns==self._columns: return
        self._columns=columns
        while self.grid.count(): self.grid.takeAt(0)
        for index,card in enumerate(self.cards): self.grid.addWidget(card,index//columns,index%columns)
        self._update_height(); self.updateGeometry()
    def resizeEvent(self,event):
        super().resizeEvent(event); self._reflow()
    def showEvent(self,event):
        super().showEvent(event); self._reflow()


class CollectionCard(QFrame):
    selected=Signal(int); opened=Signal(int)
    def __init__(self,row):
        super().__init__(); self.collection_id=int(row["id"]); self.setObjectName("card"); self.setFixedSize(270,170); self.setFocusPolicy(Qt.StrongFocus);self.setCursor(Qt.PointingHandCursor)
        visual=CoverListCard(row['name'],f"{row['item_count']} titles",row.get('cover_paths') or (),description=row.get('description') or '')
        self.setFixedSize(270,204);lay=QVBoxLayout(self);lay.setContentsMargins(0,0,0,0);visual.setAttribute(Qt.WA_TransparentForMouseEvents);visual.setFocusPolicy(Qt.NoFocus);lay.addWidget(visual)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton: self.setFocus(); self.selected.emit(self.collection_id)
        super().mousePressEvent(event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton: self.opened.emit(self.collection_id)
        super().mouseDoubleClickEvent(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter): self.opened.emit(self.collection_id); event.accept(); return
        super().keyPressEvent(event)


class SourceGalleryCard(QFrame):
    clicked=Signal(object)
    def __init__(self,item,artwork_loader,status=None,saved=False):
        super().__init__();self.item=item;self.setObjectName("card");layout=media_layout(self)
        cover=QLabel("NO ART");cover.setFixedSize(COVER_WIDTH,COVER_HEIGHT);cover.setAlignment(Qt.AlignCenter);cover.setStyleSheet("background:#17202b;border-radius:7px;color:#6f7a89")
        artwork_loader(item,cover,COVER_WIDTH,COVER_HEIGHT);layout.addWidget(cover)
        name=item.get("title") or f"Gallery {item.get('external_id')}";title=TwoLineLabel(name);title.setObjectName("cardTitle");title.setFixedHeight(42);title.setToolTip(name);layout.addWidget(title)
        self.status_label=text_slot(layout,'muted',20)
        self.secondary=text_slot(layout,'mediaAvailability',30);self.secondary.setAlignment(Qt.AlignCenter);self.secondary.setText(source_label(item.get('source'))+' · External bookmark')
        self.note=text_slot(layout,'mediaNote',32,True);self.note.setText(str(item['page_count'])+' pages' if item.get('page_count') else '')
        self.set_manual_status(status,saved);layout.addSpacing(28);layout.addSpacing(6);card_input(self,lambda:self.clicked.emit(self.item))
    def set_manual_status(self,status,saved=None):
        if saved is None:saved=getattr(self,"_saved",False)
        self._saved=saved;self.status_label.setText(_status_markup("Reading" if status=="Watching" else status,"Saved bookmark" if saved else "External entry"))
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit(self.item)
        super().mouseReleaseEvent(event)


class BackdropFrame(ArtworkHero):
    pass


class WideCard(QFrame):
    clicked=Signal(int); continue_clicked=Signal(int)
    def __init__(self,row,next_episode=None,compact=False,favorite=False,manual_status=None):
        super().__init__(); self.anime_id=row["id"]; self.setObjectName("wideCard")
        self.setFixedSize(380 if compact else 470,138 if compact else 174)
        metadata=json.loads(row["metadata_json"] or "{}"); art_path=metadata.get("banner_path") or metadata.get("cover_path")
        layout=QHBoxLayout(self); layout.setContentsMargins(10,10,12,10); layout.setSpacing(12)
        art=QLabel("NO ART"); art.setAlignment(Qt.AlignCenter); art.setFixedSize(145 if compact else 180,118 if compact else 154)
        art.setStyleSheet("background:#182130;border-radius:8px;color:#6f7a89")
        pixmap=_scaled_artwork(art_path,art.width(),art.height())
        if not pixmap.isNull(): art.setPixmap(pixmap)
        layout.addWidget(art); text=QVBoxLayout(); text.setContentsMargins(0,2,0,2); text.setSpacing(6)
        title=TwoLineLabel(("♥  " if favorite else "")+(metadata.get("title",{}).get("english") or metadata.get("title",{}).get("romaji") or row["title"] or "Unknown Anime")); title.setObjectName("cardTitle"); title.setWordWrap(True); title.setAlignment(Qt.AlignTop|Qt.AlignLeft); title.setFixedHeight(42); text.addWidget(title)
        total=row["episode_count"] or 0; watched=row["watched_count"] or 0
        if favorite:
            genres=", ".join((metadata.get("genres") or [])[:2]); summary=f"{total} episodes"+(f"  •  {genres}" if genres else "")
        else: summary=f"{watched} / {total} watched"
        self._status_summary=summary;self.status_label=QLabel(_status_markup(manual_status,summary));self.status_label.setTextFormat(Qt.RichText); self.status_label.setObjectName("muted"); self.status_label.setFixedHeight(20); text.addWidget(self.status_label)
        if not favorite:
            bar=QProgressBar(); bar.setRange(0,max(total,1)); bar.setValue(watched); bar.setTextVisible(False); bar.setFixedHeight(7); text.addWidget(bar)
        text.addStretch(1)
        if next_episode:
            footer=QPushButton(f"▶  Continue Episode {next_episode}"); footer.setObjectName("primary"); footer.clicked.connect(lambda:self.continue_clicked.emit(self.anime_id)); footer.setFixedHeight(38)
        elif favorite:
            footer=QLabel("♥  Favorite"); footer.setStyleSheet("color:#ff6a96"); footer.setFixedHeight(22)
        else:
            last=row["last_watched_episode"] if "last_watched_episode" in row.keys() else None
            footer=QLabel(f"Last watched: Episode {last}" if last is not None else "Not watched yet"); footer.setFixedHeight(22)
        text.addWidget(footer); layout.addLayout(text,1)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton: self.clicked.emit(self.anime_id)
    def set_manual_status(self,status):self.status_label.setText(_status_markup(status,self._status_summary))


class ResizeHandle(QWidget):
    def __init__(self,edges,cursor):
        super().__init__(); self.edges=edges; self.setCursor(cursor)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and not self.window().isFullScreen() and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)


class TitleBar(QFrame):
    def __init__(self,window):
        super().__init__(); self.host=window; self.setObjectName("titleBar"); self.setFixedHeight(56)
        layout=QHBoxLayout(self); layout.setContentsMargins(14,0,0,0); layout.setSpacing(0)
        icon=QLabel(); icon.setFixedSize(30,30)
        title_icon=ASSET_DIR/"anivault_icon.png"
        if title_icon.exists(): icon.setPixmap(QPixmap(str(title_icon)).scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        layout.addWidget(icon); layout.addSpacing(7)
        brand=QLabel("Ani<span style='color:#ff3f78'>Vault</span>"); brand.setTextFormat(Qt.RichText); brand.setObjectName("brand"); layout.addWidget(brand)
        layout.addSpacing(20)
        for text,action in (("‹",window.navigate_back),("›",window.navigate_forward)):
            navigation=QPushButton(text);navigation.setFixedSize(30,32);navigation.setStyleSheet('padding:0;font-size:20px');navigation.clicked.connect(action);navigation.setToolTip('Back' if text=='‹' else 'Forward');layout.addWidget(navigation)
        layout.addSpacing(12)
        window.global_search=QLineEdit();window.global_search.setObjectName('globalSearch');window.global_search.setPlaceholderText('Search your vault, anime & manga…   Ctrl+K');window.global_search.setMinimumWidth(180);window.global_search.setMaximumWidth(700);window.global_search.setFixedHeight(36);decorate_search(window.global_search);layout.addWidget(window.global_search,1);layout.addStretch(1)
        window.global_suggestions=SearchSuggestions(window,window.global_search,'normal')
        window.global_search.returnPressed.connect(lambda:window.show_global_search(window.global_search.text(),window._hub_scope))
        window.global_search_shortcut=QShortcut(QKeySequence('Ctrl+K'),window);window.global_search_shortcut.activated.connect(window._focus_global_search)
        for label,slot,name in (("—",window.showMinimized,"windowButton"),("□",window.toggle_maximize,"windowButton"),("×",window.close,"closeButton")):
            button=QPushButton(label); button.setObjectName(name); button.setFixedSize(48,42); button.clicked.connect(lambda _checked=False,action=slot:action()); layout.addWidget(button)
            if label=="□": window.maximize_button=button
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and not self.host.isFullScreen() and self.host.windowHandle(): self.host.windowHandle().startSystemMove()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton: self.host.toggle_maximize()


class SidebarFrame(QFrame):
    """Centralized decorative art layer; never participates in navigation layout/input."""
    def __init__(self):
        super().__init__(); self.setObjectName("sidebar"); self._art_suppressed=False;self._art_cache={};self._restricted_art=None;self.art=QLabel(self); self.art.setAttribute(Qt.WA_TransparentForMouseEvents,True); self.art.setAlignment(Qt.AlignBottom|Qt.AlignHCenter); effect=QGraphicsOpacityEffect(self.art);effect.setOpacity(.28);self.art.setGraphicsEffect(effect);self.art.lower(); self.set_art(False)
    def set_art(self,restricted):
        if self._restricted_art is bool(restricted):return
        self._restricted_art=bool(restricted)
        path=ART_PACKS["restricted" if restricted else "normal"]["sidebar"]
        cache_key=str(path);self._art_pixmap=self._art_cache.get(cache_key)
        if self._art_pixmap is None:
            self._art_pixmap=QPixmap(str(path)) if path.exists() else QPixmap();self._art_cache[cache_key]=self._art_pixmap
        self._layout_art()
    def _layout_art(self):
        if self._art_suppressed or self.property("compact"):self.art.hide();return
        navigation=[child for child in self.findChildren(QWidget) if child is not self.art and isinstance(child,(QPushButton,QLabel)) and child.objectName() in {"nav","eyebrow","brand","tagline"} and child.isVisible()]
        safe_top=max((child.geometry().bottom() for child in navigation),default=0)+8
        rescan=self.findChild(QPushButton,"rescanButton");safe_bottom=(rescan.geometry().top()-8) if rescan and rescan.isVisible() else self.height()-8
        available=max(0,safe_bottom-safe_top)
        if available<54 or self._art_pixmap.isNull():self.art.hide();return
        self.art.show();height=min(240,available);self.art.setGeometry(0,safe_bottom-height,self.width(),height)
        self.art.setPixmap(self._art_pixmap.scaled(min(190,max(1,self.width())),height,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def resizeEvent(self,event):
        super().resizeEvent(event);self._layout_art()


class StatusCountLabel(QLabel):
    """A view over authoritative status storage, refreshed whenever it becomes visible."""
    def __init__(self,database,scope,status,parent=None):
        super().__init__(parent);self.database=database;self.scope=scope;self.status=status;self.refresh()
    def refresh(self):
        count=self.counter() if hasattr(self,"counter") else len(self.database.status_entries(self.status,self.scope));unit="titles";self.setText(f"{count} {unit}")
    def showEvent(self,event):
        self.refresh();super().showEvent(event)


class Window(HubMixin,LibraryFranchiseMixin,PolishMixin,DownloadsMixin,RelatedMixin,OrganizationMixin,MangaLibraryMixin,QMainWindow):
    anilist_progress_updated=Signal(int,int,str)
    requests_changed=Signal()
    personal_rating_changed=Signal()
    manual_status_changed=Signal(str,str,object)
    def __init__(self):
        super().__init__(); startup_started=time.perf_counter(); self._search_suggestions=[]; self._closing=False;self._shutdown_complete=False; APP_DIR.mkdir(parents=True,exist_ok=True); self.db_path=APP_DIR/"anime_hub.db"; self._new_install=not self.db_path.exists(); prepare_existing_database(self.db_path,_append_playback_log); self.db=Database(self.db_path); record_release(self.db,_append_playback_log)
        self._init_manga_library()
        from .lan_desktop import DesktopServer
        self.lan_server = DesktopServer(self, APP_DIR, _append_playback_log)
        _append_playback_log(f"SavedToPlanningMigration {self.db.saved_planning_report} restricted={self.db.restricted_saved_planning_report}")
        _append_playback_log("DatabaseIntegrity "+json.dumps(self.db.audit_integrity(),sort_keys=True))
        self.downloads=Downloads(self.db,_append_playback_log,self)
        self.manga_reader_page=None; self.manga_reader_fullscreen=False; self._reader_was_maximized=False
        self.scan_worker=None; self.anilist_worker=None; self.airing_page_worker=None; self._airing_session_id=None; self.playback_monitors=[]; self.player_page=None; self.player_fullscreen=False; self._player_was_maximized=False; self.current_view="home"; self.current_anime_id=None
        self._library_page_cache={};self._library_rows_cache=None; self._library_cache_dirty=True; self._view_loads={}
        self._network=QNetworkAccessManager(self); self._http_art_cache=QNetworkDiskCache(self._network);self._http_art_cache.setCacheDirectory(str(APP_DIR/'cache'/'http_art'));self._http_art_cache.setMaximumCacheSize(128*1024*1024);self._network.setCache(self._http_art_cache); self._remote_artwork_cache={}; self._remote_artwork_waiters={}
        self._current_route=None; self._back_history=[]; self._forward_history=[]; self._history_navigating=False
        self.current_collection_id=None; self.current_collection_scope="normal";self.current_status_name=None;self.current_franchise_id=None; self.current_remote_item=None; self.current_remote_source="Discover"
        self._relation_cache={}; self._relation_inflight={}; self._relation_cooldown_until=0.0
        self._relation_retry_timer=QTimer(self); self._relation_retry_timer.setSingleShot(True); self._relation_retry_owner=None; self._franchise_session=0
        self._discover_cooldown_until=0.0; self._discover_page_worker=None; self.current_discover_state=None
        self._discover_cache={}; self._discover_inflight={}; self._discover_pending={}; self._discover_filter_cache={}; self._discover_filter_waiters={False:[],True:[]}; self._discover_filter_loading={False:False,True:False}; self._discover_workers=set()
        self._discover_queue_handlers={}; self._discover_queue_worker=DiscoverQueueWorker(); self._discover_queue_worker.succeeded.connect(self._discover_queue_succeeded); self._discover_queue_worker.failed.connect(self._discover_queue_failed); self._discover_queue_worker.start()
        self._status_card_refs={};self._status_count_refs={};self._section_page_cache={};self._recommendation_profile_cache={};self.restricted_media_type="ANIME";self._normal_return_state=None;self.current_source_item=None
        self._discover_cooldown_timer=QTimer(self); self._discover_cooldown_timer.setSingleShot(True); self._discover_cooldown_timer.timeout.connect(self._flush_discover_pending)
        self._airing_reflow_timers=[]
        for delay in (0,40,120,260,420):
            timer=QTimer(self); timer.setSingleShot(True); timer.setInterval(delay); timer.timeout.connect(self._refresh_airing_layout); self._airing_reflow_timers.append(timer)
        self.anilist_progress_updated.connect(self._apply_anilist_progress_update)
        self.manual_status_changed.connect(self._apply_status_change)
        self.nav_buttons={}; self.active_nav_key=None; self.library_context={}; self.setWindowTitle("AniVault — Your anime, your library."); self.resize(1440,900)
        if ICON_PATH.exists(): self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlag(Qt.FramelessWindowHint,True)
        shell=QWidget(); shell_layout=QHBoxLayout(shell); shell_layout.setContentsMargins(0,0,0,0); shell_layout.setSpacing(0)
        self._hub_scope="normal";self._hub_rail_dismissed=False;self._init_hub_selection()
        self.sidebar=self._build_sidebar(); shell_layout.addWidget(self.sidebar); self.stack=QStackedWidget();self.stack.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); shell_layout.addWidget(self.stack,1);self.context_rail=DetailRail(self);shell_layout.addWidget(self.context_rail)
        self.setCentralWidget(self._build_chrome(shell))
        QApplication.instance().installEventFilter(self)
        self.restricted_shortcut=QShortcut(QKeySequence("Ctrl+Shift+R"),self);self.restricted_shortcut.activated.connect(self.unlock_restricted)
        self.show_home()
        if self._new_install: self.show_first_run()
        elif not self.db.setting("library_root"): self.show_settings()
        _append_playback_log(f"Startup elapsed_ms={(time.perf_counter()-startup_started)*1000:.0f}")

    def choose_local_manga(self):
        scope="restricted" if self.current_view.startswith("restricted") else "normal"
        menu=QMenu(self)
        archive=menu.addAction("Open CBZ / CBR / PDF…")
        folder=menu.addAction("Open Image Folder…")
        chosen=menu.exec(self.title_bar.mapToGlobal(self.title_bar.rect().bottomLeft()))
        if chosen is archive:
            path=QFileDialog.getOpenFileName(self,"Open Manga / Comic",self.db.setting("reader_last_directory_"+scope),"Manga / Comics (*.cbz *.cbr *.pdf)")[0]
        elif chosen is folder:
            path=QFileDialog.getExistingDirectory(self,"Open Image Folder",self.db.setting("reader_last_directory_"+scope))
        else:return
        if path:
            self.db.set_setting("reader_last_directory_"+scope,str(Path(path).parent))
            self.open_local_manga(path,"restricted" if self.current_view.startswith("restricted") else "normal")

    def open_local_manga(self,path,scope="normal",reader_identity=None):
        indexed=self.manga_store.item_by_path(path)
        if indexed:
            scope=indexed["scope"];reader_identity=indexed["reader_identity"]
        if scope=="restricted" and self.db.setting("restricted_unlocked","0")!="1":
            self.show_home();return
        self._stop_local_reader()
        page=LocalMangaReader(self.db,path,APP_DIR/"cache"/"local_reader",scope,self,reader_identity=reader_identity)
        page.diagnostic.connect(_append_playback_log)
        page.back_requested.connect(self._leave_local_reader)
        page.fullscreen_requested.connect(self._toggle_reader_fullscreen)
        self.manga_reader_page=page;self.current_manga_item_id=None
        self.current_view="restricted_local_reader" if scope=="restricted" else "local_reader"
        self.replace(page);page.start()

    def _leave_local_reader(self):
        if self._back_history:self.navigate_back()
        else:self.show_home()

    def _toggle_reader_fullscreen(self):
        page=self.manga_reader_page
        if page is None:return
        entering=not self.manga_reader_fullscreen
        if entering:
            self._reader_was_maximized=self.isMaximized();self._reader_restore_geometry=self.saveGeometry()
            self._reader_chrome_visibility=[(widget,widget.isVisible()) for widget in (self.sidebar,self.title_bar,self.statusBar(),*self.resize_handles)]
        self.manga_reader_fullscreen=entering;page.set_fullscreen(entering)
        for widget,visible in self._reader_chrome_visibility:widget.setVisible(False if entering else visible)
        edge=0 if entering else 5
        for column in (0,2):self.chrome_grid.setColumnMinimumWidth(column,edge)
        for row in (0,3):self.chrome_grid.setRowMinimumHeight(row,edge)
        if entering:self.showFullScreen()
        else:
            self.showNormal();self.restoreGeometry(self._reader_restore_geometry)
            if self._reader_was_maximized:self.showMaximized()
        page.canvas.setFocus()

    def _stop_local_reader(self):
        page=self.manga_reader_page
        if page is None:return
        if self.manga_reader_fullscreen:self._toggle_reader_fullscreen()
        self.manga_reader_page=None
        if self._normal_return_state and self._normal_return_state[0] is page:self._normal_return_state=None
        page.shutdown();self.stack.removeWidget(page);page.deleteLater()

    def _discover_queue_succeeded(self,key,result):
        handler=self._discover_queue_handlers.pop(key,None)
        if handler and not self._closing: handler[0](result)
    def _discover_queue_failed(self,key,error):
        handler=self._discover_queue_handlers.pop(key,None)
        if handler and not self._closing: handler[1](error)
    def _submit_discover_job(self,key,operation,on_success,on_failure,priority=False):
        if self._closing:return
        self._discover_queue_handlers[key]=(on_success,on_failure)
        self._discover_queue_worker.submit(key,operation,priority)


    def _build_chrome(self,content):
        chrome=QWidget(); grid=QGridLayout(chrome); grid.setContentsMargins(0,0,0,0); grid.setSpacing(0)
        top_left=ResizeHandle(Qt.TopEdge|Qt.LeftEdge,Qt.SizeFDiagCursor); top=ResizeHandle(Qt.TopEdge,Qt.SizeVerCursor); top_right=ResizeHandle(Qt.TopEdge|Qt.RightEdge,Qt.SizeBDiagCursor)
        left=ResizeHandle(Qt.LeftEdge,Qt.SizeHorCursor); right=ResizeHandle(Qt.RightEdge,Qt.SizeHorCursor)
        bottom_left=ResizeHandle(Qt.BottomEdge|Qt.LeftEdge,Qt.SizeBDiagCursor); bottom=ResizeHandle(Qt.BottomEdge,Qt.SizeVerCursor); bottom_right=ResizeHandle(Qt.BottomEdge|Qt.RightEdge,Qt.SizeFDiagCursor)
        grid.addWidget(top_left,0,0); grid.addWidget(top,0,1); grid.addWidget(top_right,0,2)
        self.title_bar=TitleBar(self); grid.addWidget(self.title_bar,1,0,1,3); grid.addWidget(left,2,0); grid.addWidget(content,2,1); grid.addWidget(right,2,2)
        grid.addWidget(bottom_left,3,0); grid.addWidget(bottom,3,1); grid.addWidget(bottom_right,3,2)
        grid.setColumnMinimumWidth(0,5); grid.setColumnMinimumWidth(2,5); grid.setRowMinimumHeight(0,5); grid.setRowMinimumHeight(3,5); grid.setRowStretch(2,1); grid.setColumnStretch(1,1)
        self.chrome_grid=grid; self.resize_handles=(top_left,top,top_right,left,right,bottom_left,bottom,bottom_right)
        return chrome

    def toggle_maximize(self):
        if self.isFullScreen():return
        if self.current_view in {"airing","airing_all"}: _append_playback_log(f"Airing maximize requested main_window_size={self.width()}x{self.height()} state={'maximized' if self.isMaximized() else 'normal'}")
        if self.isMaximized(): self.showNormal()
        else: self.showMaximized()
        if hasattr(self,"maximize_button"): self.maximize_button.setText("❐" if self.isMaximized() else "□")
        self._schedule_airing_reflow()

    def _schedule_airing_reflow(self):
        if self.current_view not in {"airing","airing_all"}: return
        for timer in self._airing_reflow_timers: timer.start()

    def _refresh_airing_layout(self):
        if self.current_view not in {"airing","airing_all"}: return
        page=self.stack.currentWidget() if hasattr(self,"stack") else None
        if page is None: return
        for scroll in page.findChildren(AiringScrollArea): self._apply_airing_viewport(page,scroll,scroll.viewport().contentsRect().width(),"window-deferred")

    def _apply_airing_viewport(self,page,scroll,width,reason):
        if self.stack.currentWidget() is not page or self.current_view not in {"airing","airing_all"}: return
        viewport_width=max(228,int(width)); body=scroll.widget()
        if body is None: return
        margins=body.layout().contentsMargins() if body.layout() else None
        usable=max(228,viewport_width-(margins.left()+margins.right() if margins else 0))
        grids=scroll.findChildren(ResponsiveSeasonGrid)
        expected_columns=max(1,max(228,usable)//240)
        width_changed=scroll._applied_viewport_width!=viewport_width
        columns_changed=any(grid._columns!=expected_columns for grid in grids)
        if not width_changed and not columns_changed:
            _append_playback_log(f"Airing relayout suppressed reason={reason} viewport_width={viewport_width} columns={expected_columns}")
            return
        scroll._applied_viewport_width=viewport_width
        body.setFixedWidth(viewport_width); body.updateGeometry()
        if body.layout(): body.layout().invalidate(); body.layout().activate()
        for section in body.findChildren(QWidget,"airingSection",Qt.FindDirectChildrenOnly): section.setFixedWidth(usable)
        if body.layout(): body.layout().invalidate(); body.layout().activate()
        for grid in grids: grid.set_viewport_width(usable,reason)
        page.updateGeometry()
        section_widths=",".join(str(section.width()) for section in body.findChildren(QWidget,"airingSection",Qt.FindDirectChildrenOnly)) or "none"
        grid_state=",".join(f"{grid.grid_id}:{grid._columns}" for grid in grids) or "none"
        _append_playback_log(f"Airing relayout fired reason={reason}\nMain window size: {self.width()}x{self.height()}\nAiring page size: {page.width()}x{page.height()}\nScroll area viewport size: {scroll.viewport().width()}x{scroll.viewport().height()}\nGrid available width: {usable}\nComputed columns: {grid_state}\nSection width: {section_widths}")

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._update_hub_rail_visibility();self._schedule_branding_ownership()
        if self.current_view in {"airing","airing_all"}: _append_playback_log(f"Airing resize event received main_window_size={self.width()}x{self.height()}")
        self._schedule_airing_reflow()
        self._update_hub_rail_visibility()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:
            if self.current_view in {"airing","airing_all"}: _append_playback_log(f"Airing WindowStateChange received main_window_size={self.width()}x{self.height()} maximized={self.isMaximized()}")
            self._schedule_airing_reflow()

    def _build_sidebar(self):
        sidebar=SidebarFrame(); sidebar.setFixedWidth(216); layout=QVBoxLayout(sidebar); layout.setContentsMargins(16,14,16,14); layout.setSpacing(2)
        labels=[]
        toggle=QPushButton();toggle.setIcon(outline_icon("chevron-left"));toggle.setToolTip("Expand or collapse navigation");layout.addWidget(toggle)
        def nav(key,text,slot):
            button=QPushButton(text.split("   ")[-1]); button.setIcon(outline_icon(NAV_ICONS.get(key,"bookmark"),ratio=self.devicePixelRatioF())); button.setIconSize(QSize(18,18)); button.setObjectName("nav"); button.setProperty("active",False); button.setMinimumHeight(40); button.clicked.connect(lambda _checked=False,action=slot:action()); layout.addWidget(button); self.nav_buttons[key]=button; return button
        def section(text):
            if layout.count():layout.addSpacing(7)
            label=QLabel(text); label.setObjectName("eyebrow"); layout.addWidget(label);labels.append(label)
        section("PRIMARY"); nav("home","⌂   Home",self.show_home)
        nav("all","▦   Anime",self.show_library);nav("manga","▤   Manga",lambda:self.show_manga_library());nav("favorites","♡   Favorites",self.show_favorites)
        nav("statistics","Statistics",self.show_statistics)
        section("DISCOVER");nav("discover","✦   Discover",self.show_discover);nav("airing","◫   Airing / Upcoming",self.show_airing)
        section("ORGANIZE");nav("planning","◇   Planning",lambda:self.show_status_list("Planning","normal"));nav("collections","▤   Collections",lambda:self.show_collections("normal"))
        section("SYSTEM");nav("requests","Requests && Feedback",self.show_requests);nav("downloads","↓   Downloads",self.show_downloads);nav("settings","⚙   Settings",self.show_settings)
        layout.addSpacing(7); self.restricted_label=QLabel("RESTRICTED"); self.restricted_label.setObjectName("eyebrow"); layout.addWidget(self.restricted_label); self.restricted_button=nav("restricted","◆   Restricted Archive",self.show_restricted_home)
        unlocked=self.db.setting("restricted_unlocked","0")=="1";self.restricted_label.setVisible(unlocked);self.restricted_button.setVisible(unlocked)
        layout.addStretch()
        self.rescan_button=QPushButton("Rescan Library"); self.rescan_button.setIcon(outline_icon("refresh-cw",ratio=self.devicePixelRatioF())); self.rescan_button.setObjectName("rescanButton");self.rescan_button.clicked.connect(self.rescan); layout.addWidget(self.rescan_button);QTimer.singleShot(0,sidebar._layout_art)
        from .desktop_ui import avatar, choose_avatar
        profile=QPushButton();profile.setIconSize(QSize(36,36));profile.setToolTip("Choose local profile image")
        profile.setAccessibleName("Choose local profile image");profile.setObjectName("localProfile")
        profile.clicked.connect(lambda:choose_avatar(self,profile,ASSET_DIR));layout.addWidget(profile)
        avatar(self,profile,ASSET_DIR)
        names={key:button.text() for key,button in self.nav_buttons.items()}
        for key,button in self.nav_buttons.items():
            button.setToolTip(names[key]);button.setAccessibleName(names[key])
        def apply(collapsed):
            sidebar.setFixedWidth(64 if collapsed else 216)
            sidebar.setProperty("compact",collapsed)
            toggle.setIcon(outline_icon("chevron-right" if collapsed else "chevron-left"))
            layout.setContentsMargins(8 if collapsed else 14,10,8 if collapsed else 14,10)
            for key,button in self.nav_buttons.items():button.setText("" if collapsed else names[key])
            for label in labels:label.setVisible(not collapsed)
            self.rescan_button.setText("" if collapsed else "Rescan Library")
            self.rescan_button.setToolTip("Rescan Library")
            sidebar.style().unpolish(sidebar);sidebar.style().polish(sidebar)
            sidebar._layout_art()
        apply(self.db.setting("compact_navigation","0")=="1")
        def flip():
            value=not sidebar.property("compact")
            self.db.set_setting("compact_navigation",int(value));apply(value)
        toggle.clicked.connect(flip)
        return sidebar

    def show_requests(self,provider=None):
        from .requests_ui import requests_page
        self.current_view="requests";self.current_anime_id=None
        self._set_active_nav("requests");self.replace(requests_page(self,provider))

    def _set_active_nav(self,key):
        key=("planning" if self.current_status_name=="Planning" else "status_hub") if key=="collections" and self.current_view=="status_list" else "status_hub" if key in {"unwatched","completed"} else key
        key={"saved":"discover","franchises":"collections"}.get(key,key)
        self.active_nav_key=key
        highlight={"watching":"home","recent":"home","status_hub":"collections"}.get(key,key)
        for name,button in self.nav_buttons.items():
            button.setProperty("active",name==highlight); button.setIcon(outline_icon(NAV_ICONS.get(name,"bookmark"),name==highlight,self.devicePixelRatioF())); button.style().unpolish(button); button.style().polish(button); button.update()

    def replace(self, widget):
        if self.manga_reader_page is not None and widget is not self.manga_reader_page:
            self._stop_local_reader()
        if self.player_page is not None and widget is not self.player_page:
            teardown_started=time.perf_counter(); self._stop_integrated_player(save_resume=True,reason="navigation")
            _append_playback_log(f"Player teardown UI detach: {(time.perf_counter()-teardown_started)*1000:.0f} ms")
        for reference in self._search_suggestions:
            popup=reference()
            if popup is not None and isValid(popup):popup.dismiss()
        self._search_suggestions=[r for r in self._search_suggestions if r() is not None and isValid(r())]
        previous=self.stack.currentWidget()
        if previous is not widget:self._release_manga_page_art(previous)
        returning=self._normal_return_state[0] if self._normal_return_state else None
        if previous is not None and previous is not widget and (previous.property("mangaPage") or previous.property('transientPage')) and previous is not returning:
            self.stack.removeWidget(previous);previous.deleteLater()
        self._apply_theme(self.current_view.startswith("restricted")); self.stack.addWidget(widget); self.stack.setCurrentWidget(widget);self._prepare_hub_page()
        route=self._route_snapshot()
        if route is not None and self.current_view!="player":
            if not self._history_navigating and self._current_route is not None and route!=self._current_route:
                self._back_history.append(self._current_route); self._forward_history.clear()
            self._current_route=route
        if self.current_view!="franchise_detail" and self._relation_retry_timer.isActive():
            self._relation_retry_timer.stop(); self._relation_retry_owner=None

    def _apply_theme(self,restricted):
        # Scope the theme to this window and its owned dialogs/overlays. A
        # QApplication-wide stylesheet also repolishes unrelated closed windows.
        if self.property("restrictedTheme")!=restricted:
            started=time.perf_counter()
            self.setProperty("restrictedTheme",restricted);self.setStyleSheet(RESTRICTED_STYLE if restricted else STYLE)
            _append_playback_log(f"RestrictedTheme scope={'restricted' if restricted else 'normal'} elapsed_ms={(time.perf_counter()-started)*1000:.0f}")
        if hasattr(self,"sidebar"):self.sidebar.set_art(restricted)

    def unlock_restricted(self):
        if self.db.setting("restricted_unlocked","0")=="1":
            self.show_restricted_home();return
        if AniVaultDialog.confirm(self,"Restricted Archive","Unlock the Restricted Archive on this device?\n\nThis private wing contains adult-only AniList discovery.","Unlock"):
            _append_playback_log("RestrictedLock state=unlocked")
            self.db.set_setting("restricted_unlocked","1");self.restricted_label.show();self.restricted_button.show();self.show_restricted_home()

    def lock_restricted(self):
        self.lan_server.auth.lock_archive()
        if self.player_page is not None and self.current_anime_id is not None and self.db.anime_scope(self.current_anime_id)=='restricted':
            self._stop_integrated_player(save_resume=True,reason='Restricted lock')
        if self.manga_reader_page is not None and self.current_view.startswith('restricted'):
            self._stop_local_reader()
        started=time.perf_counter()
        popup=QApplication.activePopupWidget()
        if popup:popup.close()
        self.current_source_item=None
        self.db.set_setting("restricted_unlocked","0");self.restricted_label.hide();self.restricted_button.hide()
        self._back_history.clear();self._forward_history.clear()
        saved=self._normal_return_state;self._normal_return_state=None
        if saved and saved[3] and (saved[1] in {"manga_library","manga_detail"} or self._manga_scope_dirty):
            self._manga_scope_dirty=False;self._dispatch_route(saved[3])
        elif saved and saved[0] is not None and isValid(saved[0]):
            widget,view,nav,route=saved;self.current_view=view;self._set_active_nav(nav);self._current_route=route;self.replace(widget)
        else:self.show_home()
        _append_playback_log(f"RestrictedLock state=locked elapsed_ms={(time.perf_counter()-started)*1000:.0f}")
        self.statusBar().showMessage("Restricted Archive locked. Its data remains safely stored.",5000)

    def _route_snapshot(self):
        if self.current_view=="status_hub":return ("status_hub",)
        if self.current_view in {'library_franchise','restricted_library_franchise'}:return ('library_franchise',*self.current_library_franchise)
        if self.current_view in {"global_search","restricted_global_search"}:return ("global_search",*self.current_search)
        if self.current_view in {"favorites","restricted_favorites"}:return ("favorites","restricted" if self.current_view.startswith("restricted") else "normal")
        if self.current_view in {"manga_library","restricted_manga_library"}:return ("manga_library",dict(self.manga_context))
        if self.current_view in {"manga_detail","restricted_manga_detail"}:return ("manga_detail",self.current_manga_id)
        if self.current_view in {"local_reader","restricted_local_reader"} and self.current_manga_item_id:return ("manga_item",self.current_manga_item_id)

        if self.current_view in {"local_reader","restricted_local_reader"} and self.manga_reader_page:
            return ("local_reader",self.manga_reader_page.path,self.manga_reader_page.scope)
        if self.current_view=="restricted_source_detail" and self.current_source_item:return ("restricted_source_detail",dict(self.current_source_item))
        if self.current_view=="library": return ("library",dict(self.library_context))
        if self.current_view in {"detail","restricted_anime_detail"}: return ("detail",self.current_anime_id)
        if self.current_view in {"collection_detail","restricted_collection_detail"}: return ("collection_detail",self.current_collection_id,self.current_collection_scope)
        if self.current_view in {"status_list","restricted_status_list"}:return ("status_list",self.current_status_name,self.current_collection_scope)
        if self.current_view=="franchise_detail": return ("franchise_detail",self.current_franchise_id)
        if self.current_view in {"airing_detail","restricted_detail"} and self.current_remote_item: return ("remote",self.current_remote_item,self.current_remote_source)
        if self.current_view=="discover_all" and self.current_discover_state: return ("discover_all",dict(self.current_discover_state))
        if self.current_view=="restricted_all" and self.current_discover_state:return ("restricted_all",dict(self.current_discover_state))
        if self.current_view in {"home","settings","airing","collections","franchises","saved","downloads"}: return (self.current_view,)
        if self.current_view=="discover":return ("normal_discover",getattr(self,"discovery_media_type","ANIME"))
        if self.current_view=="restricted_discover":return (self.current_view,self.restricted_media_type)
        if self.current_view in {"restricted_home","restricted_saved","restricted_collections"}:return (self.current_view,)
        return None

    def _dispatch_route(self,route):
        kind=route[0]
        actions={"statistics":self.show_statistics,"requests":self.show_requests,"status_hub":self.show_status_hub,"home":self.show_home,"settings":self.show_settings,"airing":self.show_airing,"downloads":self.show_downloads,
                 "collections":self.show_collections,"franchises":self.show_franchises,"discover":self.show_discover,"saved":self.show_saved}
        if kind=='library_franchise':self.show_library_franchise(route[1],route[2])
        elif kind=="global_search":self.show_global_search(route[1],route[2])
        elif kind=="favorites":self.show_favorites(route[1])
        elif kind=="manga_library":self.show_manga_library(**route[1])
        elif kind=="manga_detail":self.show_manga_detail(route[1])
        elif kind=="manga_item":self.open_manga_item(route[1])
        elif kind=="local_reader":self.open_local_manga(route[1],route[2])
        elif kind in actions: actions[kind]()
        elif kind=="library": self.show_library(**route[1])
        elif kind=="detail": self.show_detail(route[1])
        elif kind=="collection_detail": self.show_collection_detail(route[1],route[2] if len(route)>2 else "normal")
        elif kind=="status_list":self.show_status_list(route[1],route[2] if len(route)>2 else "normal")
        elif kind=="franchise_detail": self.show_franchise_detail(route[1])
        elif kind=="remote": self.show_remote_anilist(route[1],route[2])
        elif kind=="discover_all": self.show_discover_all(**route[1])
        elif kind=="restricted_all": self.show_discover_all(**route[1])
        elif kind=="restricted_home":self.show_restricted_home()
        elif kind=="normal_discover":self.show_discover(False,route[1])
        elif kind=="restricted_discover":self.show_discover(True,route[1] if len(route)>1 else "ANIME")
        elif kind=="restricted_saved":self.show_saved("restricted")
        elif kind=="restricted_collections":self.show_collections("restricted")
        elif kind=="restricted_source_detail":self.show_source_detail(route[1])
        elif kind in {"restricted_doujin","restricted_source_web","restricted_reader"}:
            self.show_saved("restricted") if self.db.setting("restricted_unlocked","0")=="1" else self.show_home()

    def navigate_back(self):
        if not self._back_history:return
        route=self._back_history.pop()
        if self._current_route:self._forward_history.append(self._current_route)
        self._history_navigating=True
        try:self._dispatch_route(route)
        finally:self._history_navigating=False

    def navigate_forward(self):
        if not self._forward_history:return
        route=self._forward_history.pop()
        if self._current_route:self._back_history.append(self._current_route)
        self._history_navigating=True
        try:self._dispatch_route(route)
        finally:self._history_navigating=False

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Wheel and isinstance(obj,QComboBox) and not obj.view().isVisible():
            from PySide6.QtGui import QWheelEvent
            parent=obj.parentWidget()
            while parent is not None and not isinstance(parent,QAbstractScrollArea):
                parent=parent.parentWidget()
            if parent is not None:
                viewport=parent.viewport()
                forwarded=QWheelEvent(viewport.mapFromGlobal(event.globalPosition()),event.globalPosition(),
                    event.pixelDelta(),event.angleDelta(),event.buttons(),event.modifiers(),
                    event.phase(),event.inverted(),event.source(),event.pointingDevice())
                QApplication.sendEvent(viewport,forwarded)
            return True
        if self.current_view!="player" and event.type()==QEvent.MouseButtonPress:
            if event.button()==Qt.BackButton: self.navigate_back(); return True
            if event.button()==Qt.ForwardButton: self.navigate_forward(); return True
        return super().eventFilter(obj,event)

    def _display_title(self, row):
        metadata=json.loads(row["metadata_json"] or "{}")
        return (metadata.get("title",{}).get("english") or metadata.get("title",{}).get("romaji")
                or row["parsed_search_title"] or row["title"] or row["source_folder_name"] or "Unknown Anime")

    def _collection_log(self,event,collection=None,anime=None,result="success"):
        _append_playback_log(f"{event}\ncollection id: {collection['id'] if collection else 'n/a'}\ncollection name: {collection['name'] if collection else 'n/a'}\nanime local id: {anime['id'] if anime else 'n/a'}\nAniList id: {anime['anilist_id'] if anime and anime['anilist_id'] else 'n/a'}\nanime title: {self._display_title(anime) if anime else 'n/a'}\nresult: {result}")

    def _attach_collection_menu(self,card,anime_id,collection_id=None,franchise_id=None,scope="normal"):
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos,c=card,a=anime_id,k=collection_id,f=franchise_id,s=scope:self.anime_collection_menu(c,pos,a,k,f,s))

    def _add_status_menu(self,menu,scope,anime_id=None,item=None):
        status_menu=menu.addMenu("Set Status")
        current=self.db.manual_status(scope,anime_id=anime_id) if anime_id is not None else self.db.manual_status(scope,anilist_id=item["id"])
        for value in STATUS_COLORS:
            label="Reading" if value=="Watching" and item and item.get("type")=="MANGA" else value;action=status_menu.addAction(("✓  " if current==value else "")+label)
            action.triggered.connect(lambda _,v=value:self._set_status(v,scope,anime_id,item))
        status_menu.addSeparator();status_menu.addAction("Clear Status").triggered.connect(lambda:self._set_status(None,scope,anime_id,item))

    def _set_status(self,status,scope,anime_id=None,item=None):
        if anime_id is not None and (self.db.anime_scope(anime_id)!=scope or not self._organization_allowed(scope)):return
        if item and item.get('type')=='MANGA':
            entity=self.organization(scope).resolve(f"anilist:{item['id']}",item)
            if entity and entity.local:
                self._manga_status(entity.local['id'],status);return
        key=self.db.set_manual_status(status,scope,anime_id=anime_id,item=item);self._invalidate_discover_page_cache(scope);self.manual_status_changed.emit(scope,key,status);self.statusBar().showMessage(f"Status {'cleared' if not status else 'set to '+status}.",3000)

    def _register_status_card(self,card,scope,key):
        if hasattr(card,"set_manual_status"):self._status_card_refs.setdefault((scope,key),[]).append(weakref.ref(card))
        if not hasattr(card,'_hub_selection'):
            card._hub_selection=SelectionHook(self,card,scope,key)

    def _register_status_count(self,label,scope,status):
        self._status_count_refs.setdefault((scope,status),[]).append(weakref.ref(label))

    def _apply_status_change(self,scope,key,status):
        refs=self._status_card_refs.get((scope,key),[]);live=[]
        for reference in refs:
            card=reference()
            if card is not None and isValid(card):card.set_manual_status(status);live.append(reference)
        self._status_card_refs[(scope,key)]=live
        if hasattr(self,'context_rail') and self.context_rail.entity:
            selected=self.context_rail.entity
            if scope==selected.scope and key in selected.aliases:
                self._select_hub_entity(scope,selected.key,selected.item)
        for name in STATUS_COLORS:
            kept=[]
            for reference in self._status_count_refs.get((scope,name),[]):
                label=reference()
                if label is not None and isValid(label):
                    if hasattr(label,'refresh'):label.refresh()
                    else:
                        count=self.db.connection.execute('SELECT COUNT(*) FROM manual_status WHERE scope=? AND status=?',(scope,name)).fetchone()[0];label.setText(f'{count} titles')
                    kept.append(reference)
            self._status_count_refs[(scope,name)]=kept

    def _refresh_status_counts(self,scope):
        """Refresh landing-page labels from the authoritative DB on activation."""
        if self._closing:return
        for name in STATUS_COLORS:
            for reference in self._status_count_refs.get((scope,name),[]):
                label=reference()
                if label is not None and isValid(label): label.refresh()

    def _invalidate_discover_page_cache(self,scope):
        prefix="restricted_discover:" if scope=="restricted" else "discover:"
        for key in [key for key in self._section_page_cache if key.startswith(prefix)]:self._section_page_cache.pop(key,None)

    def anime_collection_menu(self,widget,pos,anime_id,current_collection=None,current_franchise=None,scope="normal"):
        anime=self.db.anime(anime_id)
        if not anime: return
        menu=QMenu(self); next_episode=self.db.next_unwatched(anime_id)
        if next_episode:
            episode=next_episode["episode"] if next_episode["episode"] is not None else "Next"
            play=menu.addAction(f"Continue Watching Episode {episode}"); play.triggered.connect(lambda:self.continue_episode(anime_id))
        details=menu.addAction("Open Details"); details.triggered.connect(lambda:self.show_detail(anime_id))
        favorite=menu.addAction("Remove Favorite" if anime["favorite"] else "Add Favorite")
        favorite.triggered.connect(lambda:self.set_favorite_from_context(anime_id,not bool(anime["favorite"]),current_collection))
        if scope=='restricted' and anime['anilist_id'] and self.db.is_saved(anime['anilist_id'],scope):
            menu.addAction('Remove from Saved').triggered.connect(lambda:self.set_saved({**json.loads(anime['metadata_json'] or '{}'),'id':anime['anilist_id']},False,scope))
        self._add_status_menu(menu,scope,anime_id=anime_id)
        menu.addSeparator(); add_menu=menu.addMenu("Add to Collection")
        memberships=self.db.anime_collection_ids(anime_id); collections=self.db.collections("Name",scope)
        for collection in collections:
            action=add_menu.addAction(("✓  " if collection["id"] in memberships else "")+collection["name"])
            action.setEnabled(collection["id"] not in memberships)
            action.triggered.connect(lambda _,cid=collection["id"]:self.add_anime_to_collection(cid,anime_id))
        if collections: add_menu.addSeparator()
        create=add_menu.addAction("+ New Collection"); create.triggered.connect(lambda:self.create_collection(anime_id=anime_id,scope=scope))
        if current_collection is not None:
            menu.addSeparator(); remove=menu.addAction("Remove from Collection")
            remove.triggered.connect(lambda:self.remove_anime_from_collection(current_collection,anime_id))
        if current_franchise is not None:
            menu.addSeparator(); up=menu.addAction("Move Up"); up.triggered.connect(lambda:self.move_franchise_anime(current_franchise,anime_id,-1))
            down=menu.addAction("Move Down"); down.triggered.connect(lambda:self.move_franchise_anime(current_franchise,anime_id,1))
            remove_franchise=menu.addAction("Remove from Franchise"); remove_franchise.triggered.connect(lambda:self.remove_anime_from_franchise(current_franchise,anime_id))
        menu.addSeparator(); folder=menu.addAction("Open Folder"); folder.triggered.connect(lambda:self.open_folder(anime["root_path"]))
        menu.addAction('Match / Change AniList Entry').triggered.connect(lambda:self.match_anime(anime_id,anime['title']))
        menu.exec(widget.mapToGlobal(pos))

    def set_favorite_from_context(self,anime_id,value,current_collection=None):
        self.db.set_favorite(anime_id,value); self._library_cache_dirty=True
        if self.current_view in {"favorites","restricted_favorites"}:self.show_favorites("restricted" if self.current_view.startswith("restricted") else "normal")
        elif current_collection is not None: self.show_collection_detail(current_collection)
        elif self.current_view=="library": self.show_library(**self.library_context)
        elif self.current_view=="home": self.show_home()

    def create_collection(self,anime_id=None,item=None,scope="normal"):
        name,ok=AniVaultDialog.prompt(self,"New Collection","Collection name:")
        if not ok: return None
        try: collection_id=self.db.create_collection(name,scope=scope)
        except ValueError as exc: AniVaultDialog.alert(self,"Collection",str(exc)); return None
        collection=self.db.collection(collection_id); anime=self.db.anime(anime_id) if anime_id else None
        self._collection_log("Collection created",collection,anime)
        if anime_id: self.db.add_to_collection(collection_id,anime_id); self._collection_log("Anime added to collection",collection,anime)
        elif item:self.db.add_remote_to_collection(collection_id,item)
        if self.current_view in {"collections","restricted_collections"}: self.show_collections(scope)
        return collection_id

    def remote_anime_menu(self,widget,pos,item,scope="normal",current_collection=None):
        menu=QMenu(self);menu.addAction("Open Details").triggered.connect(lambda:self.show_remote_anilist(item,"Restricted" if scope=="restricted" else "Saved"))
        self._add_status_menu(menu,scope,item=item);menu.addSeparator();add_menu=menu.addMenu("Add to Collection")
        key=f"anilist:{int(item['id'])}";store=self.organization(scope);entity=store.resolve(key,item);memberships=store.memberships(entity) if entity else set();collections=self.db.collections("Name",scope)
        for collection in collections:
            action=add_menu.addAction(("✓  " if collection["id"] in memberships else "")+collection["name"]);action.setEnabled(collection["id"] not in memberships);action.triggered.connect(lambda _,cid=collection["id"]:self.db.add_remote_to_collection(cid,item))
        if collections:add_menu.addSeparator()
        add_menu.addAction("+ New Collection").triggered.connect(lambda:self.create_collection(item=item,scope=scope))
        if current_collection is not None:
            menu.addSeparator();menu.addAction("Remove from Collection").triggered.connect(lambda:self._remove_remote_from_collection(current_collection,key,scope))
        menu.exec(widget.mapToGlobal(pos))

    def _remove_remote_from_collection(self,collection_id,key,scope):
        store=self.organization(scope);entity=store.resolve(key)
        if entity:store.remove_membership(collection_id,entity)
        else:self.db.remove_entity_from_collection(collection_id,key)
        self.show_collection_detail(collection_id,scope)

    def add_anime_to_collection(self,collection_id,anime_id):
        collection=self.db.collection(collection_id); anime=self.db.anime(anime_id)
        added=self.db.add_to_collection(collection_id,anime_id)
        self._collection_log("Anime added to collection",collection,anime,"success" if added else "already included")

    def remove_anime_from_collection(self,collection_id,anime_id):
        collection=self.db.collection(collection_id); anime=self.db.anime(anime_id)
        store=self.organization(collection["scope"]);entity=store.resolve(f"local:{anime_id}")
        removed=bool(entity)
        if entity:store.remove_membership(collection_id,entity)
        self._collection_log("Anime removed from collection",collection,anime,"success" if removed else "not present")
        self.show_collection_detail(collection_id,collection["scope"])

    def rename_collection(self,collection_id):
        collection=self.db.collection(collection_id)
        if not collection: return
        return_to_overview=self.current_view in {"collections","restricted_collections"};scope=collection["scope"]
        name,ok=AniVaultDialog.prompt(self,"Rename Collection","Collection name:",collection["name"])
        if not ok: return
        try: self.db.rename_collection(collection_id,name)
        except ValueError as exc: AniVaultDialog.alert(self,"Collection",str(exc)); return
        renamed=self.db.collection(collection_id); self._collection_log("Collection renamed",renamed)
        self.show_collections(scope) if return_to_overview else self.show_collection_detail(collection_id,scope)

    def edit_collection_description(self,collection_id):
        collection=self.db.collection(collection_id)
        if not collection: return
        return_to_overview=self.current_view in {"collections","restricted_collections"};scope=collection["scope"]
        description,ok=AniVaultDialog.prompt(self,"Edit Description","Description (optional):",collection["description"] or "",True)
        if not ok: return
        try: self.db.set_collection_description(collection_id,description)
        except ValueError as exc: AniVaultDialog.alert(self,"Collection",str(exc)); return
        updated=self.db.collection(collection_id); self._collection_log("Collection description updated",updated)
        self.show_collections(scope) if return_to_overview else self.show_collection_detail(collection_id,scope)

    def collection_overview_menu(self,widget,pos,collection_id):
        menu=QMenu(self);collection=self.db.collection(collection_id);scope=collection["scope"] if collection else "normal"
        open_action=menu.addAction("Open Collection"); open_action.triggered.connect(lambda:self.show_collection_detail(collection_id,scope))
        menu.addSeparator(); rename=menu.addAction("Rename Collection"); rename.triggered.connect(lambda:self.rename_collection(collection_id))
        description=menu.addAction("Edit Description"); description.triggered.connect(lambda:self.edit_collection_description(collection_id))
        menu.addSeparator(); delete=menu.addAction("Delete Collection"); delete.triggered.connect(lambda:self.delete_collection(collection_id))
        menu.exec(widget.mapToGlobal(pos))

    def delete_collection(self,collection_id):
        collection=self.db.collection(collection_id)
        if not collection: return
        message=f'Delete collection "{collection["name"]}"?\n\nThe titles and their statuses will remain intact.\nOnly the collection will be removed.'
        if not AniVaultDialog.confirm(self,"Delete Collection",message,"Delete Collection"): return
        self.db.delete_collection(collection_id); self._collection_log("Collection deleted",collection); self.show_collections(collection["scope"])

    def show_collections(self,scope="normal"):
        if scope=="restricted" and self.db.setting("restricted_unlocked","0")!="1":return
        restricted=scope=="restricted";self.current_view="restricted_collections" if restricted else "collections"; self.current_collection_scope=scope;self.current_anime_id=None; self._set_active_nav("restricted" if restricted else "collections")
        # This page is rebuilt from authoritative storage.  Do not retain count
        # label ownership from an older page instance in the shared signal map.
        for status_name in STATUS_COLORS:self._status_count_refs[(scope,status_name)]=[]
        page=QWidget();page.setProperty("transientPage",True); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18); self._top_header(outer)
        if restricted:self._restricted_nav(outer)
        header=QHBoxLayout(); title=QLabel("Restricted Collections" if restricted else "Collections"); title.setObjectName("title"); header.addWidget(title); header.addStretch()
        if not restricted:
            franchises=QPushButton('Franchise Groups');franchises.clicked.connect(self.show_franchises);header.addWidget(franchises)
        create=QPushButton("+ New Collection"); create.setObjectName("primary"); create.clicked.connect(lambda:self.create_collection(scope=scope)); header.addWidget(create); outer.addLayout(header)
        controls=QHBoxLayout(); controls.addStretch(); sort=QComboBox(); sort.addItems(["Recently Created","Name","Recently Updated"]); controls.addWidget(QLabel("Sort:")); controls.addWidget(sort); outer.addLayout(controls)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget();body_layout=QVBoxLayout(body);status_heading=QLabel("Status Lists");status_heading.setObjectName("section");body_layout.addWidget(status_heading);status_grid=ResponsiveLibraryGrid(card_width=270);body_layout.addWidget(status_grid);custom_heading=QLabel("Custom Collections");custom_heading.setObjectName("section");body_layout.addWidget(custom_heading);grid=ResponsiveLibraryGrid(card_width=270);body_layout.addWidget(grid);body_layout.addStretch();scroll.setWidget(body); outer.addWidget(scroll); selected={"id":None,"card":None}
        for status_name,color in STATUS_COLORS.items():
            entities=self.organization(scope).statuses(status_name)
            card=CoverListCard("Watching / Reading" if status_name=="Watching" else status_name,"",self._entity_cover_paths(entities),color)
            self._populate_cover_mosaic(card,entities)
            def artwork_changed(changed_scope,key,value,ref=weakref.ref(card),name=status_name):
                target=ref()
                if changed_scope==scope and target is not None and isValid(target):self._populate_cover_mosaic(target,self.organization(scope).statuses(name))
            self.manual_status_changed.connect(artwork_changed)
            card.destroyed.connect(lambda _,callback=artwork_changed:self.manual_status_changed.disconnect(callback) if isValid(self) else None)
            count_label=StatusCountLabel(self.db,scope,status_name);count_label.counter=lambda name=status_name:len(self.organization(scope).statuses(name));count_label.refresh();card.count_label.hide();card.layout().addWidget(count_label);self._register_status_count(count_label,scope,status_name)
            card.clicked.connect(lambda s=status_name:self.show_status_list(s,scope));status_grid.add_card(card)
        def select_collection(collection_id,card):
            if selected["card"] is not None and isValid(selected["card"]):
                selected["card"].setProperty("selected",False); selected["card"].style().unpolish(selected["card"]); selected["card"].style().polish(selected["card"])
            selected.update(id=collection_id,card=card); card.setProperty("selected",True); card.style().unpolish(card); card.style().polish(card); card.update()
        def render():
            selected.update(id=None,card=None); grid.clear_cards()
            rows=self.db.collections(sort.currentText(),scope)
            if not rows:
                empty=self._empty_state('empty','No custom collections yet.',scope,copy='Organize local and AniList anime and manga.');lay=empty.layout(); button=QPushButton("+ New Collection"); button.clicked.connect(lambda:self.create_collection(scope=scope)); lay.addWidget(button,0,Qt.AlignLeft); grid.add_card(empty)
            for row in rows:
                entities=self.organization(scope).collection(row['id']);value=dict(row);value['item_count']=len(entities);value['preview_metadata']='{}'
                if entities:
                    first=entities[0];local=first.local or {};art=local.get('manual_cover_path') or local.get('cover_path') or first.item.get('cover_path')
                    value['preview_metadata']=json.dumps({**first.item,'cover_path':art})
                value['cover_paths']=self._entity_cover_paths(entities);card=CollectionCard(value);self._populate_cover_mosaic(card.findChild(CoverListCard),entities); card.selected.connect(lambda cid,c=card:select_collection(cid,c)); card.opened.connect(lambda cid,s=scope:self.show_collection_detail(cid,s)); card.setContextMenuPolicy(Qt.CustomContextMenu)
                card.customContextMenuRequested.connect(lambda pos,c=card,cid=row["id"]:self.collection_overview_menu(c,pos,cid)); grid.add_card(card)
            add=CoverListCard("＋ New Collection","Organize anime and manga your way.",color="#ff7f9b");add.clicked.connect(lambda:self.create_collection(scope=scope));grid.add_card(add)
        sort.currentTextChanged.connect(render); self.replace(page); render(); QTimer.singleShot(0,lambda:self._refresh_status_counts(scope))

    def show_collection_detail(self,collection_id,scope="normal"):
        return self._show_organized_collection(collection_id,scope)

    def show_status_list(self,status,scope="normal"):
        return self._show_organized_status(status,scope)

    def create_franchise(self,anime_id=None):
        name,ok=AniVaultDialog.prompt(self,"New Franchise","Franchise name:")
        if not ok: return
        description,ok=AniVaultDialog.prompt(self,"New Franchise","Optional description:","",True)
        if not ok: return
        try:
            franchise_id=self.db.create_franchise(name,description)
            if anime_id: self.db.add_to_franchise(franchise_id,anime_id)
        except ValueError as exc: AniVaultDialog.alert(self,"Franchise",str(exc)); return
        _append_playback_log(f"Franchise created id={franchise_id} name={name.strip()} anime_local_id={anime_id or 'n/a'}")
        self.show_franchise_detail(franchise_id)

    def add_anime_to_franchise(self,franchise_id,anime_id,relation_type=""):
        try: added=self.db.add_to_franchise(franchise_id,anime_id,relation_type)
        except ValueError as exc: AniVaultDialog.alert(self,"Franchise",str(exc)); return
        _append_playback_log(f"Anime added to franchise franchise_id={franchise_id} anime_local_id={anime_id} result={'success' if added else 'already included'}")
        if self.current_view=="franchise_detail": self.show_franchise_detail(franchise_id)

    def remove_anime_from_franchise(self,franchise_id,anime_id):
        self.db.remove_from_franchise(franchise_id,anime_id); _append_playback_log(f"Anime removed from franchise franchise_id={franchise_id} anime_local_id={anime_id}"); self.show_franchise_detail(franchise_id)

    def move_franchise_anime(self,franchise_id,anime_id,direction):
        self.db.move_franchise_item(franchise_id,anime_id,direction); self.show_franchise_detail(franchise_id)

    def rename_franchise(self,franchise_id):
        franchise=self.db.franchise(franchise_id)
        if not franchise:return
        name,ok=AniVaultDialog.prompt(self,"Rename Franchise","Franchise name:",franchise["name"])
        if not ok:return
        try:self.db.update_franchise(franchise_id,name=name)
        except ValueError as exc:AniVaultDialog.alert(self,"Franchise",str(exc));return
        self.show_franchise_detail(franchise_id) if self.current_view=="franchise_detail" else self.show_franchises()

    def edit_franchise_description(self,franchise_id):
        franchise=self.db.franchise(franchise_id)
        if not franchise:return
        value,ok=AniVaultDialog.prompt(self,"Edit Franchise Description","Description (optional):",franchise["description"],True)
        if ok:self.db.update_franchise(franchise_id,description=value); self.show_franchise_detail(franchise_id) if self.current_view=="franchise_detail" else self.show_franchises()

    def delete_franchise(self,franchise_id):
        franchise=self.db.franchise(franchise_id)
        if not franchise:return
        if not AniVaultDialog.confirm(self,"Delete Franchise",f'Delete franchise "{franchise["name"]}"?\n\nAll anime will remain in your library. Only the franchise and its membership links will be removed.',"Delete Franchise"):return
        self.db.delete_franchise(franchise_id); _append_playback_log(f"Franchise deleted id={franchise_id} name={franchise['name']}"); self.show_franchises()

    def franchise_menu(self,widget,pos,franchise_id):
        menu=QMenu(self)
        for label,slot in (("Open Franchise",lambda:self.show_franchise_detail(franchise_id)),("Rename Franchise",lambda:self.rename_franchise(franchise_id)),("Edit Description",lambda:self.edit_franchise_description(franchise_id))): menu.addAction(label).triggered.connect(slot)
        menu.addSeparator(); menu.addAction("Delete Franchise").triggered.connect(lambda:self.delete_franchise(franchise_id)); menu.exec(widget.mapToGlobal(pos))

    def show_franchises(self):
        self.current_view="franchises";self.current_anime_id=None;self._set_active_nav("franchises")
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);self._top_header(outer)
        header=QHBoxLayout();title=QLabel("Franchises");title.setObjectName("title");header.addWidget(title);header.addStretch();new=QPushButton("+ New Franchise");new.setObjectName("primary");new.clicked.connect(self.create_franchise);header.addWidget(new);outer.addLayout(header)
        scroll=QScrollArea();scroll.setWidgetResizable(True);grid=ResponsiveLibraryGrid(card_width=270);scroll.setWidget(grid);outer.addWidget(scroll)
        rows=self.db.franchises()
        if not rows: empty=QLabel("No franchises yet.\nGroup related anime without merging their progress or files.");empty.setObjectName("muted");grid.add_card(empty)
        for row in rows:
            if any(self.db.anime_scope(member)!='normal' for member in self.db.franchise_anime(row['id'])):continue
            card=CollectionCard(row);card.opened.connect(self.show_franchise_detail);card.setContextMenuPolicy(Qt.CustomContextMenu);card.customContextMenuRequested.connect(lambda pos,c=card,fid=row["id"]:self.franchise_menu(c,pos,fid));grid.add_card(card)
        self.replace(page)

    def show_franchise_detail(self,franchise_id):
        if any(self.db.anime_scope(member)!='normal' for member in self.db.franchise_anime(franchise_id)):return self.show_home()
        franchise=self.db.franchise(franchise_id)
        if not franchise:self.show_franchises();return
        self.current_view="franchise_detail";self.current_anime_id=None;self.current_franchise_id=franchise_id;self._franchise_session+=1;session=self._franchise_session;self._set_active_nav("franchises")
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);self._top_header(outer)
        header=QHBoxLayout();back=QPushButton("← Back");back.clicked.connect(self.navigate_back);header.addWidget(back);title=QLabel(franchise["name"]);title.setObjectName("title");header.addWidget(title);header.addStretch()
        for label,slot in (("Rename",lambda:self.rename_franchise(franchise_id)),("Edit Description",lambda:self.edit_franchise_description(franchise_id)),("Delete",lambda:self.delete_franchise(franchise_id))):b=QPushButton(label);b.clicked.connect(slot);header.addWidget(b)
        outer.addLayout(header)
        if franchise["description"]:description=QLabel(franchise["description"]);description.setObjectName("muted");description.setWordWrap(True);outer.addWidget(description)
        rows=self.db.franchise_anime(franchise_id);count=QLabel(f"{len(rows)} titles — progress remains independent for every entry");count.setObjectName("muted");outer.addWidget(count)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();body_layout=QVBoxLayout(body);grid=ResponsiveLibraryGrid();body_layout.addWidget(grid)
        for row in rows:
            card=Card(row,show_progress=(row["watched_count"] or 0)>0,manual_status=self.db.manual_status("normal",anime_id=row["id"]));self._register_status_card(card,"normal",self.db.entity_key_for_anime(row["id"]));card.clicked.connect(self.show_detail);self._attach_collection_menu(card,row["id"],franchise_id=franchise_id);grid.add_card(card)
        suggested_title=QLabel("Suggested Related Titles");suggested_title.setObjectName("section");body_layout.addWidget(suggested_title);status=QLabel("Checking direct AniList relations…" if rows else "Add a matched local anime to load relation suggestions.");status.setObjectName("muted");body_layout.addWidget(status);suggestions=ResponsiveLibraryGrid();body_layout.addWidget(suggestions);body_layout.addStretch();scroll.setWidget(body);outer.addWidget(scroll);self.replace(page)
        ids=[row["anilist_id"] for row in rows if row["anilist_id"]]
        if ids:
            def render(items):
                if self.current_view!="franchise_detail" or self._franchise_session!=session or not self.db.franchise(franchise_id):return
                status.setText(f"{len(items)} direct relation suggestion(s)");local={int(row["anilist_id"]):row for row in self.db.anime_list() if row["anilist_id"]}
                member_ids={row["id"] for row in self.db.franchise_anime(franchise_id)}
                for item in sorted(items,key=lambda item:not bool(local.get(int(item['id'])))):
                    if item.get('isAdult') is True:continue
                    local_row=local.get(int(item['id']));panel=self._make_discover_card(item,local,'Discover')
                    panel.note.setText('Anime · '+str(item.get('format') or '')+' · '+item.get('relationType','RELATED').replace('_',' ').title())
                    action=QPushButton("Already Added" if local_row and local_row["id"] in member_ids else "Add to Franchise" if local_row else "AniList-only")
                    action.setFixedHeight(28);action.setStyleSheet('padding:3px 7px');action.setEnabled(bool(local_row and local_row["id"] not in member_ids))
                    action.clicked.connect(lambda _,aid=local_row["id"] if local_row else None,rel=item.get("relationType",""):self.add_anime_to_franchise(franchise_id,aid,rel) if aid else None)
                    panel.layout().takeAt(6);panel.layout().insertWidget(6,action);suggestions.add_card(panel)
            self._request_franchise_relations(ids,session,render,status)

    def _request_franchise_relations(self,ids,session,render,status):
        ids=tuple(dict.fromkeys(int(value) for value in ids))
        missing=tuple(value for value in ids if value not in self._relation_cache)
        def combined():
            seen={};
            for source in ids:
                for item in self._relation_cache.get(source,[]): seen[int(item["id"])]=item
            return list(seen.values())
        if not missing: render(combined()); return
        if time.time()<self._relation_cooldown_until:
            delay=max(1,int(self._relation_cooldown_until-time.time()+0.99)); status.setText(f"AniList is temporarily rate-limiting requests. Retrying in {delay}s…")
            owner=(missing,session)
            if self._relation_retry_owner!=owner:
                self._relation_retry_timer.stop(); self._relation_retry_owner=owner
                try:self._relation_retry_timer.timeout.disconnect()
                except RuntimeError:pass
                self._relation_retry_timer.timeout.connect(lambda:self._request_franchise_relations(ids,session,render,status) if self.current_view=="franchise_detail" and self._franchise_session==session else None)
                self._relation_retry_timer.start(delay*1000)
            return
        key=tuple(sorted(missing))
        if key in self._relation_inflight:
            self._relation_inflight[key].append((session,render,status,ids)); _append_playback_log(f"AniList relation request deduplicated ids={key}"); return
        listeners=[(session,render,status,ids)]; self._relation_inflight[key]=listeners
        worker=AniListWorker(fetch_anime_relations,key); self.anilist_worker=worker
        _append_playback_log(f"AniList relation request started ids={key}")
        def succeeded(items):
            grouped={value:[] for value in key}
            for item in items: grouped.setdefault(int(item.get("sourceAniListId",0)),[]).append(item)
            self._relation_cache.update(grouped); active=self._relation_inflight.pop(key,[])
            for listener_session,callback,_,listener_ids in active:
                if self.current_view=="franchise_detail" and self._franchise_session==listener_session:
                    seen={}
                    for source in listener_ids:
                        for item in self._relation_cache.get(source,[]):seen[int(item["id"])]=item
                    callback(list(seen.values()))
        def failed(exc):
            active=self._relation_inflight.pop(key,[])
            if isinstance(exc,AniListHTTPError) and exc.status_code==429:
                delay=max(1,int(exc.retry_after or 15)); self._relation_cooldown_until=time.time()+delay
                _append_playback_log(f"AniList relation cooldown seconds={delay} ids={key}")
                for listener_session,callback,label,listener_ids in active:
                    if self.current_view=="franchise_detail" and self._franchise_session==listener_session:
                        label.setText("AniList is temporarily rate-limiting requests. Retrying shortly…")
                        self._request_franchise_relations(listener_ids,listener_session,callback,label)
            else:
                for listener_session,_,label,_ in active:
                    if self.current_view=="franchise_detail" and self._franchise_session==listener_session: label.setText("Related titles are temporarily unavailable. Try again later.")
        worker.succeeded.connect(succeeded);worker.failed.connect(failed);worker.finished.connect(worker.deleteLater);worker.start()

    def _request_discover_page(self,params,on_success,on_failure):
        requested=time.perf_counter();raw=dict(params);context=raw.pop("_context","Discover")
        normalized={key:(list(value) if isinstance(value,tuple) else value) for key,value in raw.items()}; key=json.dumps(normalized,sort_keys=True,separators=(",",":"))
        _append_playback_log(f"{context}\npage requested={normalized.get('page',1)} media_type={normalized.get('media_type','ANIME')} adult={normalized.get('is_adult')} sort={normalized.get('sort')} country={normalized.get('country')} formats={normalized.get('formats')}\ncache lookup start")
        if key in self._discover_cache:
            _append_playback_log(f"{context}\nCache: HIT\nCache lookup end={(time.perf_counter()-requested)*1000:.1f} ms")
            QTimer.singleShot(0,lambda:on_success(self._discover_cache[key])); return
        _append_playback_log(f"{context}\nCache: MISS\nCache lookup end={(time.perf_counter()-requested)*1000:.1f} ms")
        if key in self._discover_inflight: self._discover_inflight[key].append((on_success,on_failure)); return
        if self._discover_cooldown_until and time.time()>=self._discover_cooldown_until:self._discover_cooldown_until=0.0
        if time.time()<self._discover_cooldown_until:
            self._discover_pending.setdefault(key,[]).append((normalized,on_success,on_failure,context)); delay=max(1,int(self._discover_cooldown_until-time.time()+.99))
            if not self._discover_cooldown_timer.isActive():self._discover_cooldown_timer.start(delay*1000)
            return
        self._discover_inflight[key]=[(on_success,on_failure)]
        _append_playback_log(f"{context}\nrequest dispatched={(time.perf_counter()-requested)*1000:.1f} ms")
        def succeeded(result):
            if self.db.observe_classifications(result.get('items') or []):self._library_cache_dirty=True
            _append_playback_log(f"{context}\nHTTP response received status={result.get('httpStatus','unknown')} raw_count={result.get('rawCount',len(result.get('items') or []))}\nresponse parse complete={(time.perf_counter()-requested)*1000:.1f} ms")
            self._discover_cache[key]=result; listeners=self._discover_inflight.pop(key,[])
            for callback,_ in listeners:callback(result)
        def failed(exc):
            listeners=self._discover_inflight.pop(key,[])
            if isinstance(exc,AniListHTTPError) and exc.status_code==429:
                delay=max(1,int(exc.retry_after or 15)); self._discover_cooldown_until=max(self._discover_cooldown_until,time.time()+delay)
                pending=self._discover_pending.setdefault(key,[])
                for callback,error in listeners:pending.append((normalized,callback,error,context))
                if not self._discover_cooldown_timer.isActive():self._discover_cooldown_timer.start(delay*1000)
                _append_playback_log(f"Discover global cooldown seconds={delay} key={key}")
            else:
                for _,error in listeners:error(exc)
        self._submit_discover_job("page:"+key,lambda:fetch_discover_page(**normalized),succeeded,failed)

    def _request_discover_filters(self,callback,restricted=False):
        key=bool(restricted); cached=self._discover_filter_cache.get(key)
        if cached is not None:QTimer.singleShot(0,lambda:callback(cached));return
        self._discover_filter_waiters[key].append(callback)
        if self._discover_filter_loading[key]:return
        self._discover_filter_loading[key]=True
        def loaded(options):
            self._discover_filter_cache[key]=options;self._discover_filter_loading[key]=False;waiters=self._discover_filter_waiters[key];self._discover_filter_waiters[key]=[]
            for waiter in waiters:waiter(options)
        def failed(_):self._discover_filter_loading[key]=False;self._discover_filter_waiters[key]=[]
        self._submit_discover_job("filters:"+str(key),lambda:fetch_discover_filters(key),loaded,failed)

    def _flush_discover_pending(self):
        if time.time()<self._discover_cooldown_until:
            self._discover_cooldown_timer.start(max(1,int((self._discover_cooldown_until-time.time()+.99)*1000))); return
        pending=self._discover_pending; self._discover_pending={}
        self._discover_cooldown_until=0.0
        for listeners in pending.values():
            for params,success,failure,context in listeners:self._request_discover_page({**params,"_context":context},success,failure)

    def set_saved(self,item,value,scope="normal"):
        clean_item={key:value for key,value in item.items() if not key.startswith("_recommendation_")}
        # Compatibility entry point: AniList later intent is a status in both
        # scopes. Genuine external bookmarks keep their separate source API.
        self._set_status('Planning' if value else None,scope,item=clean_item)

    def _load_remote_artwork(self,url,label,width,height):
        if self._closing:return
        cached=self._remote_artwork_cache.get((url,width,height))
        if cached is not None: label.setPixmap(cached); return
        self._remote_artwork_waiters.setdefault((url,width,height),[]).append(weakref.ref(label))
        if len(self._remote_artwork_waiters[(url,width,height)])>1: return
        request=QNetworkRequest(QUrl(url));request.setAttribute(QNetworkRequest.CacheLoadControlAttribute,QNetworkRequest.PreferCache);request.setTransferTimeout(15000)
        reply=self._network.get(request)
        def finished():
            data=bytes(reply.readAll()); pixmap=QPixmap(); pixmap.loadFromData(data)
            scaled=pixmap.scaled(width,height,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation) if not pixmap.isNull() else QPixmap()
            key=(url,width,height)
            if not scaled.isNull():
                self._remote_artwork_cache[key]=scaled;_bound_pixmap_cache(self._remote_artwork_cache)
            for reference in self._remote_artwork_waiters.pop(key,[]):
                target=reference()
                if target is not None and not scaled.isNull():
                    try: target.setPixmap(scaled)
                    except RuntimeError: pass
            reply.deleteLater()
        reply.finished.connect(finished)

    def _make_discover_card(self,item,local,source="Discover",on_saved_change=None,scope="normal"):
        item={**item,'type':organization_media_type(item)}
        if self.db.observe_classifications([item],allow_normal=False):self._library_cache_dirty=True
        if scope=='normal' and item['type']=='ANIME' and any(self.db.anime_scope(row)=='restricted' for row in self.db.connection.execute('SELECT id FROM anime WHERE anilist_id=?',(item['id'],))):
            return self._empty_state('results','Title unavailable in this scope.',scope)
        is_manga=item.get("type")=="MANGA"
        local_row=next((entity.local for entity in self.organization(scope).entities.values() if entity.media_type=="MANGA" and entity.local and entity.local["anilist_id"]==item["id"]),None) if is_manga else local.get(int(item["id"]))
        if local_row and not is_manga:
            if self.db.anime_scope(local_row)!=scope:local_row=None
        manual=(local_row["manual_status"] or self.db.manual_status(scope,anilist_id=item["id"])) if is_manga and local_row else self.db.manual_status(scope,anime_id=local_row["id"]) if local_row else self.db.manual_status(scope,anilist_id=item["id"])
        card=SeasonCard(item,bool(local_row),self._load_remote_artwork,False,False,manual,compact=scope=="normal");card.saved_scope=scope
        if scope=='normal' and not is_manga and not local_row and item.get('isAdult') is False:
            from .requests_ui import request_button
            button=request_button(self,item)
            if button:
                button.setFixedHeight(26);button.setStyleSheet('padding:2px 8px')
                card.layout().addWidget(button)
                card.setFixedHeight(max(card.height(),400 if item.get('_recommendation_reason') else 374))
        key=f"manga:{local_row['id']}" if is_manga and local_row else self.db.entity_key_for_anime(local_row["id"]) if local_row else f"anilist:{int(item['id'])}"
        self._register_status_card(card,scope,key);self._register_status_card(card,scope,f"anilist:{int(item['id'])}")
        card.clicked.connect(lambda _:self.show_manga_detail(local_row["id"]) if is_manga and local_row else self.show_detail(local_row["id"]) if local_row else self.show_remote_anilist(item,source))
        def toggled(_,value):
            self.set_saved(item,value,scope)
            if on_saved_change:on_saved_change()
        card.save_toggled.connect(toggled);card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos:self.manga_menu(card,pos,local_row["id"]) if is_manga and local_row else self.anime_collection_menu(card,pos,local_row["id"],scope=scope) if local_row else self.remote_anime_menu(card,pos,item,scope))
        return card

    def _restricted_nav(self,outer):
        row=QHBoxLayout(); home=QPushButton("Restricted Home"); anime=QPushButton("Anime");manga=QPushButton("Manga");collections=QPushButton("Collections");lock=QPushButton("Lock Archive")
        home.clicked.connect(self.show_restricted_home);anime.clicked.connect(lambda:self.show_discover(True,"ANIME"));manga.clicked.connect(lambda:self.show_discover(True,"MANGA"));collections.clicked.connect(lambda:self.show_collections("restricted"));lock.clicked.connect(self.lock_restricted)
        local=QPushButton("Local Manga");local.clicked.connect(lambda:self.show_manga_library("restricted"))
        favorites=QPushButton('Favorites');favorites.clicked.connect(lambda:self.show_favorites('restricted'))
        for button in (home,anime,manga,local,favorites,collections):row.addWidget(button)
        if self.db.source_saved():
            bookmarks=QPushButton("External Bookmarks");bookmarks.clicked.connect(lambda:self.show_saved("restricted"));row.addWidget(bookmarks)
        row.addStretch();row.addWidget(lock);outer.addLayout(row)

    def _source_card(self,item):
        item=bookmark_record(item)
        key=self.db.source_key(item["source"],item["external_id"])
        card=SourceGalleryCard(item,self._load_cached_source_artwork,self.db.source_status(item["source"],item["external_id"]),self.db.is_source_saved(item["source"],item["external_id"]))
        self._register_status_card(card,"restricted",key);card.clicked.connect(self.show_source_detail)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda pos,c=card,value=item:self._source_menu(c,pos,value))
        return card

    def _source_menu(self,widget,pos,item,collection_id=None):
        menu=QMenu(self);menu.addAction("Open Details").triggered.connect(lambda:self.show_source_detail(item))
        action=menu.addAction("Open Source");action.setEnabled(bool(bookmark_url(item)));action.triggered.connect(lambda:self._open_bookmark_source(item))
        saved=self.db.is_source_saved(item["source"],item["external_id"])
        menu.addAction("Remove from Saved" if saved else "Save").triggered.connect(lambda:self._save_source(item,not saved))
        statuses=menu.addMenu("Set Status")
        for value in STATUS_COLORS:
            label="Reading" if value=="Watching" else value
            statuses.addAction(label).triggered.connect(lambda _,v=value:self._source_status(item,v))
        statuses.addAction("Clear Status").triggered.connect(lambda:self._source_status(item,None))
        collections=menu.addMenu("Add to Collection")
        for collection in self.db.collections(scope="restricted"):
            key=self.db.source_key(item["source"],item["external_id"])
            included=collection["id"] in self.db.entity_collection_ids(key)
            collections.addAction(("✓  " if included else "")+collection["name"]).triggered.connect(lambda _,cid=collection["id"]:self._source_collection(cid,item))
        collections.addAction("+ New Collection").triggered.connect(lambda:self._create_source_collection(item))
        if collection_id is not None:
            menu.addAction("Remove from Collection").triggered.connect(lambda:self._remove_source_collection(collection_id,item))
        menu.exec(widget.mapToGlobal(pos))

    def _save_source(self,item,value):
        if self.db.setting("restricted_unlocked","0")!="1":return
        self.db.cache_source_items([item])
        if value:self.db.save_source_gallery(item)
        else:self.db.unsave_source_gallery(item["source"],item["external_id"])
        self._section_page_cache.pop("restricted_saved",None)
        for card in self.stack.findChildren(SourceGalleryCard):
            if card.item.get("source")==item["source"] and card.item.get("external_id")==item["external_id"] and isValid(card):
                card.set_manual_status(self.db.source_status(item["source"],item["external_id"]),value)
        if self.current_view=="restricted_saved" and hasattr(self,"_restricted_saved_render"):
            self._restricted_saved_render()
        self.statusBar().showMessage("Saved" if value else "Removed from Saved",3000)

    def _source_status(self,item,status):
        if self.db.setting("restricted_unlocked","0")!="1":return
        self.db.cache_source_items([item])
        key=self.db.set_source_status(item,status);self.manual_status_changed.emit("restricted",key,status)
        self._section_page_cache.pop("restricted_saved",None)

    def _source_collection(self,collection_id,item):
        if self.db.setting("restricted_unlocked","0")!="1":return
        self.db.cache_source_items([item])
        self.db.add_source_to_collection(collection_id,item);self.statusBar().showMessage("Added to Restricted Collection",3000)

    def _create_source_collection(self,item):
        if self.db.setting("restricted_unlocked","0")!="1":return
        name,ok=AniVaultDialog.prompt(self,"New Collection","Collection name:")
        if not ok:return
        try:self._source_collection(self.db.create_collection(name,scope="restricted"),item)
        except ValueError as exc:AniVaultDialog.alert(self,"Collection",str(exc))

    def _remove_source_collection(self,collection_id,item):
        if self.db.setting("restricted_unlocked","0")!="1":return
        self.db.remove_entity_from_collection(collection_id,self.db.source_key(item["source"],item["external_id"]))
        self.show_collection_detail(collection_id,"restricted")










    def _load_cached_source_artwork(self,item,label,width,height):
        """External bookmarks never resolve/fetch covers from a retired source."""
        path=cached_artwork_path(item)
        url=item.get("cover_url") if isinstance(item.get("cover_url"),str) else None
        pixmap=QPixmap(str(path)) if path else self._remote_artwork_cache.get((url,width,height))
        if pixmap is not None and not pixmap.isNull():
            label.setPixmap(pixmap.scaled(width,height,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation))

    def _open_bookmark_source(self,item):
        if self.db.setting("restricted_unlocked","0")!="1":return
        url=bookmark_url(item)
        if url:webbrowser.open(url)
        else:AniVaultDialog.alert(self,"External Bookmark","This entry has no usable source link.")

    def show_source_detail(self,item):
        """Offline bookmark details: no metadata/index requests or embedded browser."""
        if self.db.setting("restricted_unlocked","0")!="1":return
        item=bookmark_record(item)
        try:self.db.source_key(item["source"],item["external_id"])
        except ValueError:
            AniVaultDialog.alert(self,"External Bookmark","This saved entry has an invalid source identity.");return
        try:cached=self.db.cached_source_item(item["source"],item["external_id"])
        except (TypeError,ValueError):cached=None
        item=bookmark_record(self.db._merge_source_metadata(cached if isinstance(cached,dict) else None,item))
        self.current_view="restricted_source_detail";self.current_source_item=item;self._set_active_nav("restricted")
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);self._restricted_nav(outer)
        back=QPushButton("← Back");back.clicked.connect(self.navigate_back);outer.addWidget(back,0,Qt.AlignLeft)
        row=QHBoxLayout();cover=QLabel("NO ART");cover.setFixedSize(230,310);cover.setAlignment(Qt.AlignCenter)
        self._load_cached_source_artwork(item,cover,230,310);row.addWidget(cover,0,Qt.AlignTop)
        info=QVBoxLayout();heading=QLabel(item["title"]);heading.setObjectName("title");heading.setWordWrap(True);info.addWidget(heading)
        lines=[f"Source: {source_label(item['source'])}",f"External ID: {item['external_id']}","External bookmark · locally stored metadata"]
        if item.get("page_count"):lines.append(f"Pages: {item['page_count']}")
        tags=item.get("tags") if isinstance(item.get("tags"),dict) else {}
        for field,label in (("language","Language"),("artist","Artist"),("group","Group"),("parody","Parody"),("character","Characters"),("tag","Tags")):
            values=tags.get(field)
            if values:lines.append(label+": "+(", ".join(str(value) for value in values) if isinstance(values,(list,tuple)) else str(values)))
        progress=self.db.reading_progress(item["source"],item["external_id"])
        if progress:lines.append(f"Saved reading progress: {progress['last_page']} / {progress['total_pages']}")
        fields=QLabel("\n\n".join(lines));fields.setObjectName("muted");fields.setWordWrap(True);info.addWidget(fields)
        actions=QHBoxLayout();open_source=QPushButton("Open Source");open_source.setObjectName("primary");open_source.setEnabled(bool(bookmark_url(item)));open_source.clicked.connect(lambda:self._open_bookmark_source(item));actions.addWidget(open_source)
        save=QPushButton("Remove from Saved" if self.db.is_source_saved(item["source"],item["external_id"]) else "Save")
        def toggle_saved():
            self._save_source(item,not self.db.is_source_saved(item["source"],item["external_id"]))
            save.setText("Remove from Saved" if self.db.is_source_saved(item["source"],item["external_id"]) else "Save")
        save.clicked.connect(toggle_saved);actions.addWidget(save)
        status_button=QPushButton("Set Status");status_menu=QMenu(status_button)
        for value in STATUS_COLORS:status_menu.addAction("Reading" if value=="Watching" else value).triggered.connect(lambda _,v=value:self._source_status(item,v))
        status_menu.addAction("Clear Status").triggered.connect(lambda:self._source_status(item,None));status_button.setMenu(status_menu);actions.addWidget(status_button)
        collection_button=QPushButton("Add to Collection")
        def collection_menu():
            if self.db.setting("restricted_unlocked","0")!="1":return
            menu=QMenu(collection_button);included=self.db.entity_collection_ids(self.db.source_key(item["source"],item["external_id"]))
            for collection in self.db.collections(scope="restricted"):
                menu.addAction(("✓  " if collection["id"] in included else "")+collection["name"]).triggered.connect(lambda _,cid=collection["id"]:self._source_collection(cid,item))
            menu.addAction("+ New Collection").triggered.connect(lambda:self._create_source_collection(item))
            menu.exec(collection_button.mapToGlobal(collection_button.rect().bottomLeft()))
        collection_button.clicked.connect(collection_menu);actions.addWidget(collection_button)
        info.addLayout(actions);info.addStretch();row.addLayout(info,1);outer.addLayout(row)
        note=QLabel("This external entry is kept in AniVault for organization. Open Source uses your normal browser; no live metadata service is required.");note.setObjectName("muted");note.setWordWrap(True);outer.addWidget(note);outer.addStretch();self.replace(page)

    def show_saved(self,scope="normal"):
        if scope=="normal":return self.show_status_list("Planning","normal")
        if scope=="restricted" and self.db.setting("restricted_unlocked","0")!="1":return
        restricted=scope=="restricted"; self.current_view="restricted_saved" if restricted else "saved"; self.current_anime_id=None; self._set_active_nav("restricted" if restricted else "saved")
        cached=self._section_page_cache.get("restricted_saved") if restricted else None
        if cached is not None and isValid(cached):
            self.replace(cached)
            if cached.property('organizationStamp')!=self.db.connection.total_changes and hasattr(self,'_restricted_saved_render'):self._restricted_saved_render()
            return
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18); self._top_header(outer)
        if restricted:self._restricted_nav(outer)
        header=QHBoxLayout(); title=QLabel("External Bookmarks" if restricted else "Saved"); title.setObjectName("title"); header.addWidget(title); header.addStretch();media_filter=QComboBox();media_filter.addItems(["External Bookmarks"] if restricted else ["All Media","Anime","Manga"]);media_filter.setVisible(True);header.addWidget(media_filter);sort=QComboBox(); sort.addItems(["Recently Saved","Title","Year","Score","Popularity"]); header.addWidget(sort); outer.addLayout(header)
        note=QLabel("External source bookmarks. AniList titles use Planning in Collections." if restricted else "Anime and manga bookmarks. Saved does not mean downloaded; local matches are linked automatically."); note.setObjectName("muted"); outer.addWidget(note)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); grid=ResponsiveSeasonGrid([],context="External Bookmarks" if restricted else "Saved"); scroll.setWidget(grid); outer.addWidget(scroll)
        if restricted:self._section_page_cache["restricted_saved"]=page
        self.replace(page)
        def render():
            grid.clear_cards(); local={int(row["anilist_id"]):row for row in self.db.anime_list() if row["anilist_id"]}; cards=[]
            for row in ([] if restricted else self.db.saved_titles(sort.currentText(),scope)):
                try:item=json.loads(row["metadata_json"])
                except Exception:continue
                if restricted!=(item.get("isAdult") is True):continue
                media_type=organization_media_type(item)
                if media_filter.currentText() not in ("All Media",media_type.title()):continue
                cards.append(self._make_discover_card(item,local,"Restricted" if restricted else "Saved",render,scope))
            if restricted and media_filter.currentText() in ("All Media","External Bookmarks"):
                source_rows=self.db.source_saved();source_items=[]
                for row in source_rows:
                    try:value=json.loads(row["metadata_json"])
                    except (TypeError,ValueError):value={}
                    source_items.append(bookmark_record(value,row["source"],row["external_id"]))
                if sort.currentText()=="Title":source_items.sort(key=lambda item:(item.get("title") or "").casefold())
                cards.extend(self._source_card(item) for item in source_items)
            grid.append_cards(cards)
            page.setProperty('organizationStamp',self.db.connection.total_changes)
            if not cards:
                empty=QFrame(); empty.setObjectName("panel"); lay=QVBoxLayout(empty); heading=QLabel("No external bookmarks yet." if restricted else "Nothing saved yet."); heading.setObjectName("section"); lay.addWidget(heading); lay.addWidget(QLabel("External bookmarks remain available here; use Planning for AniList titles." if restricted else "Use Planning to keep titles for later.")); grid.append_cards([empty])
        sort.currentTextChanged.connect(render);media_filter.currentTextChanged.connect(render); render()
        if restricted:self._restricted_saved_render=render

    def show_restricted_home(self):
        started=time.perf_counter()
        if self.db.setting("restricted_unlocked","0")!="1":self.unlock_restricted();return
        if not self.current_view.startswith("restricted") and hasattr(self,"stack"):
            self._normal_return_state=(self.stack.currentWidget(),self.current_view,self.active_nav_key,self._current_route)
        self.current_view="restricted_home";self.current_anime_id=None;self._set_active_nav("restricted")
        cached=self._section_page_cache.get("restricted_home")
        if cached is not None and isValid(cached):
            self.replace(cached);_append_playback_log(f"RestrictedEnter reused=true elapsed_ms={(time.perf_counter()-started)*1000:.0f}");return
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);self._restricted_nav(outer)
        banner=BackdropFrame(str(ART_PACKS["restricted"]["hero"]));banner.setMinimumHeight(300);banner.setMaximumHeight(320);banner.focal=(.9,.32);banner.safe_banner=True;banner.setProperty('brandIllustration',True);banner.safe_focal=True;hero=QVBoxLayout(banner);hero.setContentsMargins(30,24,30,24);hero.addStretch();eyebrow=QLabel("RESTRICTED ARCHIVE");eyebrow.setObjectName("eyebrow");hero.addWidget(eyebrow);title=QLabel("The private wing of AniVault");title.setObjectName("heroTitle");title.setWordWrap(True);title.setMaximumWidth(540);hero.addWidget(title);copy=QLabel("Adult-only AniList discovery. Every title shown here is explicitly marked adult by AniList.");copy.setWordWrap(True);copy.setMaximumWidth(500);hero.addWidget(copy);actions=QHBoxLayout();browse=QPushButton("Browse Restricted Discover");browse.setObjectName("primary");browse.clicked.connect(lambda:self.show_discover(True));actions.addWidget(browse);collections=QPushButton("Collections");collections.clicked.connect(lambda:self.show_collections("restricted"));actions.addWidget(collections);actions.addStretch();hero.addLayout(actions)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();content=QVBoxLayout(body);content.setContentsMargins(0,8,0,18);content.setSpacing(22);content.addWidget(banner);status=QLabel("Opening the restricted catalogue…");status.setObjectName("muted");content.addWidget(status);content.addStretch();scroll.setWidget(body);outer.addWidget(scroll);self._section_page_cache["restricted_home"]=page;self.replace(page)
        local={int(row["anilist_id"]):row for row in self.db.anime_list() if row["anilist_id"]};specs={"Trending":DISCOVER_SPECS["Trending"],"Popular":DISCOVER_SPECS["Popular"],"Top Rated":DISCOVER_SPECS["Top Rated"]};headings=list(specs)
        def render_section(heading,items):
            if self.current_view!="restricted_home" or self.stack.currentWidget() is not page:return
            label=QLabel(heading);label.setObjectName("section");content.insertWidget(content.count()-1,label);cards=[self._make_discover_card(item,local,"Restricted",scope="restricted") for item in items if item.get("isAdult") is True];view_all=ViewAllCard(heading);view_all.clicked.connect(lambda h=heading,s={**specs[heading],"restricted":True}:self.show_discover_all(h,s));cards.append(view_all);grid=ResponsiveSeasonGrid(cards,context=f"Restricted {heading}");content.insertWidget(content.count()-1,grid);QTimer.singleShot(0,lambda g=grid:g.set_viewport_width(max(228,scroll.viewport().width()-8),"restricted-initial"))
        def load(index=0):
            if self.current_view!="restricted_home" or self.stack.currentWidget() is not page:return
            if index>=len(headings):status.setText("Restricted Archive ready");return
            heading=headings[index];self._request_discover_page({"page":1,"is_adult":True,**specs[heading]},lambda result,h=heading,i=index:(render_section(h,result.get("items") or []),load(i+1)),lambda _exc:status.setText("Restricted discovery is temporarily unavailable. Your local vault is unaffected."))
        load()
        _append_playback_log(f"RestrictedEnter reused=false elapsed_ms={(time.perf_counter()-started)*1000:.0f}")

    def show_discover(self,restricted=False,media_type="ANIME"):
        if restricted and self.db.setting("restricted_unlocked","0")!="1":return
        restricted=bool(restricted);media_type="MANGA" if media_type=="MANGA" else "ANIME";self.restricted_media_type=media_type if restricted else self.restricted_media_type; view_name="restricted_discover" if restricted else "discover"; scope="restricted" if restricted else "normal"; source="Restricted" if restricted else "Discover"
        self.current_view=view_name; self.current_anime_id=None; self._set_active_nav("restricted" if restricted else "discover")
        self.discovery_media_type=media_type
        cache_key=f"{view_name}:{media_type}"
        cached=self._section_page_cache.get(cache_key)
        if cached is not None and isValid(cached) and cached.property("recommendationFingerprint")==self._recommendation_profile(scope,media_type).fingerprint and time.time()-float(cached.property("recommendationBuiltAt") or 0)<900:self.replace(cached);return
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18)
        if restricted:self._restricted_nav(outer)
        media_switch=QHBoxLayout();compact_title=QLabel(("Restricted " if restricted else "")+"Discover "+media_type.title());compact_title.setObjectName("title");media_switch.addWidget(compact_title);media_switch.addStretch()
        for kind in ("ANIME","MANGA"):
            button=QPushButton(kind.title());button.setCheckable(True);button.setChecked(kind==media_type);button.clicked.connect(lambda _,k=kind:self.show_discover(restricted,k));media_switch.addWidget(button)
        if not restricted:
            saved=QPushButton('Saved');saved.clicked.connect(self.show_saved);media_switch.addWidget(saved)
        refresh=QPushButton("↻ Refresh");refresh.setToolTip("Refresh Recommendations");refresh.clicked.connect(lambda:self._refresh_recommendations(restricted,media_type));media_switch.addStretch();media_switch.addWidget(refresh);outer.addLayout(media_switch)
        media_label="Manga" if media_type=="MANGA" else "Anime";title=QLabel(("Restricted " if restricted else "")+"Discover "+media_label); title.setObjectName("title"); title.hide()
        intro=QLabel(f"Adult-only AniList {media_label.lower()} discovery. Every result is explicitly marked adult by AniList." if restricted else "Browse AniList beyond your local vault. Remote titles remain informational until you add your own media."); intro.setObjectName("muted");compact_title.setToolTip(intro.text());intro.hide()
        search_row=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText(f"Search all {media_label.lower()} on AniList…"); decorate_search(search); search_row.addWidget(search,2); genre_picker=MultiSelectPicker("Genres"); tag_picker=MultiSelectPicker("Tags");  search_button=QPushButton("Search"); search_button.setObjectName("primary"); search_row.addWidget(search_button); outer.addLayout(search_row)
        browse_row=CompactFilterLayout(); year_from=QLineEdit(); year_from.setPlaceholderText("Year from"); year_from.setMaximumWidth(95); browse_row.addWidget(year_from); year_to=QLineEdit(); year_to.setPlaceholderText("Year to"); year_to.setMaximumWidth(95); browse_row.addWidget(year_to)
        season_filter=QComboBox(); season_filter.addItems(["Any season","WINTER","SPRING","SUMMER","FALL"]);season_filter.setVisible(media_type=="ANIME"); browse_row.addWidget(season_filter); format_filter=QComboBox(); format_filter.addItems((["Any format","MANGA","ONE_SHOT","NOVEL"] if media_type=="MANGA" else ["Any format","TV","TV_SHORT","MOVIE","SPECIAL","OVA","ONA","MUSIC"])); browse_row.addWidget(format_filter); status_filter=QComboBox(); status_filter.addItems(["Any status","RELEASING","FINISHED","NOT_YET_RELEASED","CANCELLED","HIATUS"]); browse_row.addWidget(status_filter);country_filter=QComboBox();country_filter.addItems(MANGA_COUNTRIES);country_filter.setVisible(media_type=="MANGA");browse_row.addWidget(country_filter);source_filter=QComboBox();source_filter.addItems(MANGA_SOURCES);source_filter.setVisible(media_type=="MANGA");browse_row.addWidget(source_filter); sort_filter=QComboBox(); sort_filter.addItems(["Popularity","Score","Trending","Newest","Oldest","Title"]); browse_row.addWidget(sort_filter); library_filter=QComboBox(); library_filter.addItems(["All","In Library","Not In Library"]);library_filter.setVisible(media_type=="ANIME"); browse_row.addWidget(library_filter); browse_row.addWidget(genre_picker);browse_row.addWidget(tag_picker);clear_filters=QPushButton("Clear");clear_filters.setToolTip("Clear All"); browse_row.addWidget(clear_filters); outer.addLayout(browse_row)
        for control in (search,search_button,genre_picker,tag_picker,year_from,year_to,season_filter,format_filter,status_filter,country_filter,source_filter,sort_filter,library_filter,clear_filters,refresh):control.setFixedHeight(32);control.setStyleSheet("padding:4px 7px")
        outer.setSpacing(8)
        sort_values={"Popularity":"POPULARITY_DESC","Score":"SCORE_DESC","Trending":"TRENDING_DESC","Newest":"START_DATE_DESC","Oldest":"START_DATE","Title":"TITLE_ROMAJI"}
        def search_spec():
            integer=lambda value:int(value) if value.strip().isdigit() else None
            selected_sort=sort_values[sort_filter.currentText()]
            if media_type=="MANGA" and selected_sort=="SCORE_DESC":selected_sort=["SCORE_DESC","POPULARITY_DESC"]
            return {"search":search.text().strip(),"genres":genre_picker.selected(),"tags":tag_picker.selected(),"year_from":integer(year_from.text()),"year_to":integer(year_to.text()),"season":None if season_filter.currentIndex()==0 or media_type=="MANGA" else season_filter.currentText(),"formats":[] if format_filter.currentIndex()==0 else [format_filter.currentText()],"status":None if status_filter.currentIndex()==0 else status_filter.currentText(),"country":MANGA_COUNTRIES[country_filter.currentText()] if media_type=="MANGA" else None,"source":MANGA_SOURCES[source_filter.currentText()] if media_type=="MANGA" else None,"sort":selected_sort,"library":library_filter.currentText(),"restricted":restricted,"media_type":media_type}
        search_action=lambda:self.show_discover_all("Search Results",search_spec())
        search.returnPressed.connect(search_action); search_button.clicked.connect(search_action)
        def clear_landing_filters():
            for editor in (search,year_from,year_to):editor.clear()
            genre_picker.clear_selection();tag_picker.clear_selection()
            for combo in (season_filter,format_filter,status_filter,country_filter,source_filter,sort_filter,library_filter):combo.setCurrentIndex(0)
        clear_filters.clicked.connect(clear_landing_filters)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); content=QVBoxLayout(body); content.setContentsMargins(0,8,0,18); content.setSpacing(22)
        status=QLabel("Loading AniList discovery…"); status.setObjectName("muted"); content.addWidget(status); content.addStretch(); scroll.setWidget(body); outer.addWidget(scroll)
        self._section_page_cache[cache_key]=page
        self.replace(page)
        def landing_filters_loaded(options):
            if self.current_view==view_name and self.stack.currentWidget() is page:
                genre_picker.set_options(options.get("genres") or []); tag_picker.set_options([tag.get("name") for tag in options.get("tags") or [] if tag.get("name")])
        self._request_discover_filters(landing_filters_loaded,restricted)
        local={} if media_type=="MANGA" else {int(row["anilist_id"]):row for row in self.db.anime_list() if row["anilist_id"]}
        recommendation=self._recommendation_profile(scope,media_type)
        page.setProperty("recommendationFingerprint",recommendation.fingerprint);page.setProperty("recommendationBuiltAt",time.time())
        rec_spec=recommendation.query()
        current_season,current_year=current_anime_season(); upcoming_season,upcoming_year=next_anime_season(current_season,current_year)
        upcoming_spec=DISCOVER_SPECS["Upcoming"] if media_type=="MANGA" else {**DISCOVER_SPECS["Upcoming"],"season":upcoming_season,"year_from":upcoming_year,"year_to":upcoming_year}
        top_rated_spec={"sort":["SCORE_DESC","POPULARITY_DESC"]} if media_type=="MANGA" else DISCOVER_SPECS["Top Rated"]
        specs={"Recommended For You":rec_spec,"Trending":DISCOVER_SPECS["Trending"],"Popular":DISCOVER_SPECS["Popular"],"Upcoming":upcoming_spec,"Top Rated":top_rated_spec}
        headings=list(specs)
        discovery_hero=ArtworkHero();discovery_hero.setMinimumHeight(240);discovery_hero.hide();content.insertWidget(0,discovery_hero);hero_ready={"value":False}
        section_grids={};started={heading:time.perf_counter() for heading in headings};pending=set(headings);first_visible={"logged":False}
        def state_card(message):
            card=QFrame();card.setObjectName("panel");card.setFixedSize(228,110);lay=QVBoxLayout(card);label=QLabel(message);label.setObjectName("muted");label.setWordWrap(True);lay.addWidget(label);return card
        for heading in headings:
            label=QLabel(heading);label.setObjectName("section");content.insertWidget(content.count()-1,label)
            grid=ResponsiveSeasonGrid([state_card("Loading…")],context=f"Discover {heading}");section_grids[heading]=grid;content.insertWidget(content.count()-1,grid);QTimer.singleShot(0,lambda g=grid:g.set_viewport_width(max(228,scroll.viewport().width()-8),"discover-initial"))
        def section_done(heading):
            pending.discard(heading)
            if not pending and isValid(status):status.setText("Discover is ready • cached pages will reopen instantly")
        def render_section(heading,items):
            if self.current_view!=view_name or self.stack.currentWidget() is not page:return
            if not hero_ready["value"]:
                candidate=next((item for item in items if (item.get('isAdult') is True)==restricted and (item.get('type') or media_type)==media_type and item.get('id')),None)
                if candidate:
                    entity=self.organization(scope).resolve('anilist:'+str(candidate['id']),candidate)
                    if entity:
                        index=content.indexOf(discovery_hero);content.removeWidget(discovery_hero);discovery_hero.deleteLater();content.insertWidget(index,self._entity_hero(entity));hero_ready['value']=True
            cards=[];filtered=0;bad=0;seen=set()
            if heading=="Recommended For You":items=self._rank_recommendations(recommendation,[*items,*recommendation.related_candidates()])
            for item in items:
                try:
                    if restricted!=(item.get("isAdult") is True):filtered+=1;continue
                    if (item.get("type") or media_type)!=media_type:filtered+=1;continue
                    identifier=int(item["id"])
                    if identifier in seen:filtered+=1;continue
                    seen.add(identifier)
                    cards.append(self._make_discover_card(item,local,source,scope=scope))
                except Exception as exc:
                    bad+=1;_append_playback_log(f"Discover {heading}\nSkipped malformed media id={item.get('id','unknown')} error={exc}")
            view_all=ViewAllCard(heading); view_all.clicked.connect(lambda h=heading,s={**dict(specs[heading]),"restricted":restricted,"media_type":media_type}:self.show_discover_all(h,s)); cards.append(view_all)
            if len(cards)==1:cards.insert(0,self._empty_state('results','No results found.',scope))
            section_grids[heading].replace_cards(cards);section_done(heading)
            elapsed=(time.perf_counter()-started[heading])*1000
            _append_playback_log(f"Discover {heading}\npost-filter count={len(cards)-1} filtered={filtered} malformed={bad}\ncards constructed={len(cards)-1}\ncards rendered={len(cards)-1}\ntotal load time={elapsed:.1f} ms")
            if not first_visible["logged"] and len(cards)>1:first_visible["logged"]=True;_append_playback_log(f"Discover {media_label}\ntime to first visible card={elapsed:.1f} ms")
        def failed_section(heading,exc):
            if self.current_view==view_name and self.stack.currentWidget() is page:section_grids[heading].replace_cards([state_card("This source is temporarily unavailable.")]);section_done(heading)
            _append_playback_log(f"Discover {heading}\nrequest failed={exc}\ntotal load time={(time.perf_counter()-started[heading])*1000:.1f} ms")
        def request_section(heading):
            params={"page":1,"is_adult":restricted,"media_type":media_type,"_context":f"Discover {heading}",**specs[heading]}
            recommendation_pool=[]
            def received(result,h=heading,p=params):
                if self.current_view!=view_name or self.stack.currentWidget() is not page:return
                items=result.get("items") or []
                if h=="Recommended For You" and not items and p["page"]==1 and (p.get("genres") or p.get("tags")):
                    fallback={"page":1,"is_adult":restricted,"media_type":media_type,"sort":"TRENDING_DESC","_context":"Discover Recommended For You fallback"}
                    specs[h]={"sort":"TRENDING_DESC"}
                    self._request_discover_page(fallback,lambda second:render_section(h,second.get("items") or []),lambda exc:failed_section(h,exc));return
                if h=="Recommended For You":
                    recommendation_pool.extend(items)
                    visible=self._rank_recommendations(recommendation,[*recommendation_pool,*recommendation.related_candidates()])
                    # Fill a useful landing shelf after local/completed filtering.
                    # Full View All pagination remains uncapped and unchanged.
                    if len(visible)<6 and p["page"]<3 and (result.get("pageInfo") or {}).get("hasNextPage"):
                        next_params={**p,"page":p["page"]+1}
                        self._request_discover_page(next_params,lambda second,np=next_params:received(second,h,np),lambda exc:failed_section(h,exc));return
                    items=recommendation_pool
                if media_type=="MANGA" and h=="Top Rated" and not items:
                    fallback={**p,"sort":"POPULARITY_DESC","_context":"Discover Top Rated fallback"}
                    self._request_discover_page(fallback,lambda second:render_section(h,second.get("items") or []),lambda exc:failed_section(h,exc));return
                render_section(h,items)
            self._request_discover_page(params,received,lambda exc,h=heading:failed_section(h,exc))
        # Sections are intentionally independent: a slow recommendation or metadata
        # request can no longer serialize every useful shelf behind it.
        for heading in headings:request_section(heading)

    def show_discover_all(self,heading="Search Results",spec=None):
        spec=dict(spec or {}); restricted=bool(spec.pop("restricted",False));media_type="MANGA" if spec.pop("media_type","ANIME")=="MANGA" else "ANIME"; view_name="restricted_all" if restricted else "discover_all"; scope="restricted" if restricted else "normal"; source="Restricted" if restricted else "Discover"
        if restricted and self.db.setting("restricted_unlocked","0")!="1":return
        self.current_view=view_name; self.current_anime_id=None; self.current_discover_state={"heading":heading,"spec":{**spec,"restricted":restricted,"media_type":media_type}}; self._set_active_nav("restricted" if restricted else "discover")
        session=time.monotonic_ns(); page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18)
        if restricted:self._restricted_nav(outer)
        top=QHBoxLayout(); back=QPushButton("← Back"); back.clicked.connect(self.navigate_back); top.addWidget(back); title=QLabel(heading); title.setObjectName("title"); top.addWidget(title); top.addStretch(); outer.addLayout(top)
        filters=QVBoxLayout(); row1=QHBoxLayout(); query=QLineEdit(spec.get("search", "")); query.setPlaceholderText("Search title…"); row1.addWidget(query,2)
        genres=MultiSelectPicker("Genres"); genres.set_selected(spec.get("genres",[])); row1.addWidget(genres); tags=MultiSelectPicker("Tags"); tags.set_selected(spec.get("tags",[])); row1.addWidget(tags); filters.addLayout(row1)
        row2=CompactFilterLayout(); year_from=QLineEdit(str(spec.get("year_from") or "")); year_from.setPlaceholderText("Year from"); year_from.setMaximumWidth(95); row2.addWidget(year_from); year_to=QLineEdit(str(spec.get("year_to") or "")); year_to.setPlaceholderText("Year to"); year_to.setMaximumWidth(95); row2.addWidget(year_to)
        season=QComboBox(); season.addItems(["Any season","WINTER","SPRING","SUMMER","FALL"]); season.setCurrentText(spec.get("season") or "Any season");season.setVisible(media_type=="ANIME"); row2.addWidget(season)
        format_box=QComboBox(); format_box.addItems(["Any format","MANGA","ONE_SHOT","NOVEL"] if media_type=="MANGA" else ["Any format","TV","TV_SHORT","MOVIE","SPECIAL","OVA","ONA","MUSIC"]); format_box.setCurrentText((spec.get("formats") or ["Any format"])[0]); row2.addWidget(format_box)
        status_box=QComboBox(); status_box.addItems(["Any status","RELEASING","FINISHED","NOT_YET_RELEASED","CANCELLED","HIATUS"]); status_box.setCurrentText(spec.get("status") or "Any status"); row2.addWidget(status_box)
        country_box=QComboBox();country_box.addItems(MANGA_COUNTRIES);country_box.setVisible(media_type=="MANGA");country_box.setCurrentText(next((name for name,value in MANGA_COUNTRIES.items() if value==spec.get("country")),"All countries"));row2.addWidget(country_box);source_box=QComboBox();source_box.addItems(MANGA_SOURCES);source_box.setVisible(media_type=="MANGA");source_box.setCurrentText(next((name for name,value in MANGA_SOURCES.items() if value==spec.get("source")),"All sources"));row2.addWidget(source_box)
        sort_box=QComboBox(); sort_map={"Popularity":"POPULARITY_DESC","Score":"SCORE_DESC","Trending":"TRENDING_DESC","Newest":"START_DATE_DESC","Oldest":"START_DATE","Title":"TITLE_ROMAJI"}; sort_box.addItems(sort_map);current_sort=spec.get("sort");sort_box.setCurrentText("Score" if isinstance(current_sort,list) and "SCORE_DESC" in current_sort else next((label for label,value in sort_map.items() if value==current_sort),"Popularity")); row2.addWidget(sort_box)
        library=QComboBox(); library.addItems(["All","In Library","Not In Library"]); library.setCurrentText(spec.get("library") or "All");library.setVisible(media_type=="ANIME"); row2.addWidget(library); clear=QPushButton("Clear All"); row2.addWidget(clear); run=QPushButton("Search / Apply"); run.setObjectName("primary"); row2.addWidget(run); filters.addLayout(row2)
        for control in (query,genres,tags,year_from,year_to,season,format_box,status_box,country_box,source_box,sort_box,library,clear,run):control.setFixedHeight(32);control.setStyleSheet('padding:4px 7px')
        filters.setSpacing(6);outer.setSpacing(8)
        chips=QLabel(); chips.setObjectName("muted"); filters.addWidget(chips); outer.addLayout(filters)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); host=QWidget(); host_layout=QVBoxLayout(host); grid=ResponsiveSeasonGrid([],context=f"Discover: {heading}"); host_layout.addWidget(grid); status=QLabel(); status.setObjectName("muted"); host_layout.addWidget(status,0,Qt.AlignHCenter); host_layout.addStretch(); scroll.setWidget(host); outer.addWidget(scroll); self.replace(page)
        local={} if media_type=="MANGA" else {int(row["anilist_id"]):row for row in self.db.anime_list() if row["anilist_id"]}; state={"page":0,"has_next":True,"loading":False,"ids":set(),"retry":0}
        def values():
            integer=lambda text:int(text) if text.strip().isdigit() else None
            selected_sort=sort_map[sort_box.currentText()]
            if media_type=="MANGA" and selected_sort=="SCORE_DESC":selected_sort=["SCORE_DESC","POPULARITY_DESC"]
            return {"search":query.text().strip(),"genres":genres.selected(),"tags":tags.selected(),"year_from":integer(year_from.text()),"year_to":integer(year_to.text()),"season":None if season.currentIndex()==0 or media_type=="MANGA" else season.currentText(),"formats":[] if format_box.currentIndex()==0 else [format_box.currentText()],"status":None if status_box.currentIndex()==0 else status_box.currentText(),"country":MANGA_COUNTRIES[country_box.currentText()] if media_type=="MANGA" else None,"source":MANGA_SOURCES[source_box.currentText()] if media_type=="MANGA" else None,"sort":selected_sort,"library":library.currentText()}
        recommendation=self._recommendation_profile(scope,media_type) if heading=="Recommended For You" else None
        def make_card(item): return self._make_discover_card(item,local,source,scope=scope)
        def load_more():
            if self.current_view!=view_name or self.stack.currentWidget() is not page or state["loading"] or not state["has_next"]:return
            state["loading"]=True; next_page=state["page"]+1; request_values=values(); status.setText(f"Loading page {next_page}…")
            request_params={key:value for key,value in request_values.items() if key!="library"}; request_params["page"]=next_page; request_params["is_adult"]=restricted;request_params["media_type"]=media_type
            def loaded(result):
                if self.current_view!=view_name or self.stack.currentWidget() is not page:return
                state["loading"]=False; state["page"]=next_page; state["has_next"]=bool((result.get("pageInfo") or {}).get("hasNextPage")); accepted=[]
                incoming=result.get("items") or []
                if recommendation:
                    if next_page==1:incoming=[*incoming,*recommendation.related_candidates()]
                    incoming=self._rank_recommendations(recommendation,incoming,state["ids"])
                for item in incoming:
                    value=int(item["id"])
                    if value in state["ids"] or restricted!=(item.get("isAdult") is True) or (item.get("type") or "ANIME")!=media_type:continue
                    owned=local.get(value); total=(owned["episode_count"] or 0) if owned else 0; watched=(owned["watched_count"] or 0) if owned else 0
                    if library.currentText()=="In Library" and value not in local:continue
                    if library.currentText()=="Not In Library" and value in local:continue
                    state["ids"].add(value); accepted.append(item)
                grid.append_cards(make_card(item) for item in accepted); status.setText(f"{len(grid.cards)} titles loaded"+("" if state["has_next"] else " • End of results")); state["retry"]=0
                _append_playback_log(f"Discover page loaded category={heading} page={next_page} raw={len(result.get('items') or [])} appended={len(accepted)} hasNextPage={state['has_next']}")
                if not state["has_next"] and not state["ids"]:grid.append_cards([self._empty_state("results","No results found.",scope)])
                if state["has_next"] and not accepted: QTimer.singleShot(0,load_more)
            def failed(exc):
                state["loading"]=False; status.setText("Discover results are temporarily unavailable. Your successful results remain available.")
            if time.time()<self._discover_cooldown_until:status.setText("AniList is temporarily rate-limiting requests. Retrying shortly…")
            self._request_discover_page(request_params,loaded,failed)
        def restart():
            state.update(page=0,has_next=True,loading=False,ids=set(),retry=0); grid.clear_cards(); active=[]
            for value in [*values()["genres"],*values()["tags"],format_box.currentText() if format_box.currentIndex() else "",status_box.currentText() if status_box.currentIndex() else ""]:
                if value:active.append(f"[{value} ×]")
            chips.setText("  ".join(active)+("") if active else "No active filters"); self.current_discover_state={"heading":heading,"spec":{**values(),"restricted":restricted,"media_type":media_type}}; load_more()
        run.clicked.connect(restart); query.returnPressed.connect(restart)
        def clear_all():
            for editor in (query,year_from,year_to):editor.clear()
            genres.clear_selection(); tags.clear_selection()
            for combo in (season,format_box,status_box,country_box,source_box,library):combo.setCurrentIndex(0)
            sort_box.setCurrentText("Popularity"); restart()
        clear.clicked.connect(clear_all)
        def filters_loaded(options):
            if self.current_view!=view_name or self.stack.currentWidget() is not page:return
            genres.set_options(options.get("genres") or []); tags.set_options([tag.get("name") for tag in options.get("tags") or [] if tag.get("name")])
        self._request_discover_filters(filters_loaded,restricted)
        scroll.verticalScrollBar().valueChanged.connect(lambda value:load_more() if value>=scroll.verticalScrollBar().maximum()-max(240,scroll.verticalScrollBar().pageStep()//2) else None)
        restart()

    def show_library(self,checked=False,category_filter=None,state_filter=None,sort_mode=None,search_text="",view_mode=None,genre=None):
        stamp=self.db.change_stamp()
        if getattr(self,'_library_data_stamp',None)!=stamp:
            self._library_cache_dirty=True;self._library_data_stamp=stamp
        navigation_started=time.perf_counter(); requested="Favorites" if state_filter=="Favorites" else ("Watching" if state_filter=="In Progress" else category_filter or "All Anime")
        _append_playback_log(f"Navigation requested: {requested}")
        self.current_view="library"; self.current_anime_id=None
        self.library_context={"category_filter":category_filter,"state_filter":state_filter,"sort_mode":sort_mode,"search_text":search_text}
        key=("favorites" if state_filter=="Favorites" else "watching" if state_filter=="In Progress" or category_filter=="Watching" else
             "unwatched" if state_filter=="Unwatched" else
             "completed" if state_filter=="Completed" else "recent" if sort_mode=="Recently Added" else "all")
        self._set_active_nav(key)
        self._load_library_relations()
        view_mode=view_mode or self.db.setting('library_view_mode','Franchises')
        self.library_context['view_mode']=view_mode
        page_key=(category_filter,state_filter,sort_mode,search_text,view_mode,genre,self._library_relation_revision)
        cached=self._library_page_cache.get(page_key)
        if cached and isValid(cached[0]) and cached[1]==self.db.connection.total_changes and not self._library_cache_dirty:
            self.replace(cached[0]);resume=getattr(cached[0],'resume_population',None)
            if resume:QTimer.singleShot(0,resume)
            _append_playback_log(f"LibraryPage reused=true elapsed_ms={(time.perf_counter()-navigation_started)*1000:.0f}");return
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18); self._top_header(outer)
        from .hub_ui import ArtworkHero
        overview=ArtworkHero();overview.library_overview=True;overview.setFixedHeight(174 if key=="all" else 98)
        overview_layout=QVBoxLayout(overview);overview_layout.setContentsMargins(18,10,18,12)
        overview_layout.addStretch()
        eyebrow=QLabel("YOUR LIBRARY");eyebrow.setObjectName("eyebrow");overview_layout.addWidget(eyebrow)
        title=QLabel(requested); title.setObjectName("title");overview_layout.addWidget(title)
        subtitle=QLabel("Browse and manage your anime collection");subtitle.setObjectName("muted");overview_layout.addWidget(subtitle);outer.addWidget(overview)
        controls=CompactFilterLayout(38); search=QLineEdit(search_text); search.setPlaceholderText("Search your library…"); decorate_search(search);search.setMinimumWidth(170);controls.addWidget(search)
        category=QComboBox(); category.addItems(["All categories","Watching","Airing","Unwatched","Finished","Movies","Other"]); controls.addWidget(category); outer.addLayout(controls)
        state=QComboBox(); state.addItems(["All states","Watched","Unwatched","In Progress","Completed","Has Extras","Favorites","Unrated"]); controls.addWidget(state)
        sort=QComboBox(); sort.addItems(["Title A-Z","Recently Added","Recently Watched","Progress","Year"]); controls.addWidget(sort)
        if category_filter and category.findText(category_filter)>=0: category.setCurrentText(category_filter)
        if state_filter and state.findText(state_filter)>=0: state.setCurrentText(state_filter)
        if sort_mode and sort.findText(sort_mode)>=0: sort.setCurrentText(sort_mode)
        view=QComboBox();view.setObjectName('libraryViewMode');view.addItems(['Franchises','Individual Titles']);view.setCurrentText(view_mode);view.setToolTip('Library view mode');controls.addWidget(view);view.setVisible(key=='all')
        refresh_links=QPushButton('Relationships');refresh_links.setIcon(outline_icon('refresh-cw'));refresh_links.setToolTip('Refresh explicit AniList anime relationships');refresh_links.setVisible(key=='all');refresh_links.clicked.connect(lambda:self._request_library_relations(True));controls.addWidget(refresh_links)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); grid=ResponsiveLibraryGrid(card_width=POSTER_CARD_WIDTH)
        db_started=time.perf_counter()
        cache_state="cached/reused"
        if self._library_cache_dirty or self._library_rows_cache is None:
            rows=self.db.anime_list(); self._library_rows_cache=rows; self._library_cache_dirty=False
            cache_state="first load" if requested not in self._view_loads else "rebuilt"
        else: rows=self._library_rows_cache
        status_map={r['entity_key']:r['status'] for r in self.db.connection.execute("SELECT entity_key,status FROM manual_status WHERE scope='normal'")}
        from .library_franchises import metadata as library_metadata
        catalog={row['id']:library_metadata(row) for row in rows if self.db.anime_scope(row)=='normal'}
        if key=="all":
            backdrop=next((item.get('banner_path') or item.get('cover_path') for item in catalog.values()
                           if item.get('banner_path') or item.get('cover_path')),None)
            if backdrop:
                overview.banner.setPixmap(_scaled_artwork(backdrop,1000,150))
        genres={genre for item in catalog.values() for genre in (item.get('genres') or []) if isinstance(genre,str)}
        format_filter=QComboBox();format_filter.addItems(['All formats']+sorted({str(item['format']) for item in catalog.values() if item.get('format')}))
        year_filter=QComboBox();year_filter.addItems(['All years']+sorted({str(item['seasonYear']) for item in catalog.values() if item.get('seasonYear')},reverse=True))
        genre_filter=QComboBox();genre_filter.addItems(['All genres']+sorted(genres))
        for control in (format_filter,year_filter):controls.addWidget(control)
        genre_filter.setParent(page);genre_filter.hide()
        from PySide6.QtWidgets import QButtonGroup
        status_group=QButtonGroup(page);status_chips=QHBoxLayout()
        for value in ('All','Watching','Planning','Paused','Completed','Dropped'):
            chip=QPushButton(value);chip.setObjectName('filterChip');chip.setCheckable(True)
            status_group.addButton(chip);status_chips.addWidget(chip);chip.setChecked(value=='All')
        status_chips.addStretch();outer.addLayout(status_chips)
        genre_strip=QScrollArea();genre_strip.setWidgetResizable(True);genre_strip.setFixedHeight(48)
        genre_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        genre_body=QWidget();genre_layout=QHBoxLayout(genre_body);genre_layout.setContentsMargins(0,0,0,0)
        genre_group=QButtonGroup(page)
        for index in range(genre_filter.count()):
            chip=QPushButton(genre_filter.itemText(index));chip.setObjectName("filterChip");chip.setCheckable(True)
            genre_group.addButton(chip,index);genre_layout.addWidget(chip);chip.setChecked(index==0)
        genre_group.idClicked.connect(genre_filter.setCurrentIndex)
        if genre and genre_filter.findText(genre)>0:
            genre_filter.setCurrentText(genre);genre_group.button(genre_filter.currentIndex()).setChecked(True)
        genre_layout.addStretch();genre_strip.setWidget(genre_body);outer.addWidget(genre_strip)
        def row_key(row):return 'anilist:'+str(row['anilist_id']) if row['anilist_id'] else 'local:'+str(row['id'])
        old=self._library_page_cache.get(page_key)
        if old and old[0] is not self.stack.currentWidget() and isValid(old[0]):self.stack.removeWidget(old[0]);old[0].deleteLater()
        self._library_page_cache[page_key]=(page,self.db.connection.total_changes)
        if len(self._library_page_cache)>8:
            retired_key=next(k for k in self._library_page_cache if k!=page_key);retired=self._library_page_cache.pop(retired_key)[0]
            if retired is not self.stack.currentWidget() and isValid(retired):self.stack.removeWidget(retired);retired.deleteLater()
        self._view_loads[requested]=self._view_loads.get(requested,0)+1
        db_elapsed=time.perf_counter()-db_started
        _append_playback_log(f"Page render mode: {cache_state}")
        generation={"value":0}; metrics={}
        def rebuild():
            generation["value"]+=1; active_generation=generation["value"]
            grid.clear_cards()
            prepared_started=time.perf_counter()
            visible=[r for r in rows if self.db.anime_scope(r)=='normal' and search.text().casefold() in self._display_title(r).casefold() and
                     (category.currentIndex()==0 or r["category"].casefold()==category.currentText().casefold()) and (r["personal_rating_units"] is None if state.currentText()=="Unrated" else self._state_matches(r,state.currentText()))]
            selected=status_group.checkedButton().text()
            visible=[r for r in visible if
                (selected=='All' or status_map.get(row_key(r))==selected
                 or (not status_map.get(row_key(r)) and selected=='Watching' and 0<(r['watched_count'] or 0)<(r['episode_count'] or 0))
                 or (not status_map.get(row_key(r)) and selected=='Completed' and 0<(r['episode_count'] or 0)<=(r['watched_count'] or 0)))
                and (format_filter.currentIndex()==0 or catalog[r['id']].get('format')==format_filter.currentText())
                and (year_filter.currentIndex()==0 or str(catalog[r['id']].get('seasonYear'))==year_filter.currentText())
                and (genre_filter.currentIndex()==0 or genre_filter.currentText() in (catalog[r['id']].get('genres') or []))]
            key=sort.currentText()
            if key=="Recently Added": visible.sort(key=lambda r:r["added_at"] or "",reverse=True)
            elif key=="Recently Watched": visible.sort(key=lambda r:r["last_watched_at"] or "",reverse=True)
            elif key=="Progress": visible.sort(key=lambda r:(r["watched_count"] or 0)/max(r["episode_count"] or 0,1),reverse=True)
            elif key=="Year": visible.sort(key=lambda r:(json.loads(r["metadata_json"] or "{}").get("seasonYear") or r["detected_year"] or 0),reverse=True)
            else: visible.sort(key=lambda r:self._display_title(r).casefold())
            if view.currentText()=='Franchises' and self.active_nav_key=='all':
                groups=build_franchises(visible,self._library_relation_data);membership={row['id']:group for group in groups for row in group.rows};emitted=set();presentations=[]
                for row in visible:
                    group=membership.get(row['id'])
                    if group:
                        identity=group.local_ids
                        if identity in emitted:continue
                        emitted.add(identity);presentations.append({**dict(row),'_franchise':group})
                    else:presentations.append(row)
                visible=presentations
            metrics[active_generation]={"prepare":time.perf_counter()-prepared_started,"widgets":0.0,"artwork":0.0,"first":None}
            def add_batch(start=0):
                if self._closing or not isValid(grid) or self.stack.currentWidget() is not page or generation["value"]!=active_generation or len(grid.cards)!=start: return
                batch_started=time.perf_counter(); batch_end=min(start+10,len(visible)); timing=metrics[active_generation];batch=[]
                for i in range(start,batch_end):
                    row=visible[i]; card_started=time.perf_counter()
                    if isinstance(row,dict) and row.get('_franchise'):card=self._franchise_card(row['_franchise'])
                    else:
                        card=Card(row,show_progress=(row["watched_count"] or 0)>0,timings=timing,manual_status=status_map.get(row_key(row)));self._register_status_card(card,"normal",row_key(row));card.clicked.connect(self.show_detail);self._attach_collection_menu(card,row["id"])
                    batch.append(card)
                    timing["widgets"]+=time.perf_counter()-card_started
                grid.add_cards(batch);page.resume_population=(lambda:add_batch(batch_end)) if batch_end<len(visible) else None
                if timing["first"] is None:
                    timing["first"]=time.perf_counter()-navigation_started
                    _append_playback_log(f"DB query: {db_elapsed*1000:.0f} ms\nCard data preparation: {timing['prepare']*1000:.0f} ms\nPage visible: {timing['first']*1000:.0f} ms")
                if batch_end<len(visible): QTimer.singleShot(0,lambda:add_batch(batch_end))
                else:
                    _append_playback_log(f"Card widget creation: {timing['widgets']*1000:.0f} ms\nArtwork loading/scaling: {timing['artwork']*1000:.0f} ms\nLibrary population complete: {(time.perf_counter()-navigation_started)*1000:.0f} ms ({len(visible)} cards)")
            if not visible:grid.add_card(self._empty_state('results' if search.text() or category.currentIndex() or state.currentIndex() else 'empty','No matching anime.' if rows else 'Nothing here yet.',copy='Change filters or add your local library.'))
            else:add_batch()
        search.textChanged.connect(rebuild); category.currentTextChanged.connect(rebuild); state.currentTextChanged.connect(rebuild); sort.currentTextChanged.connect(rebuild)
        for control in (format_filter,year_filter,genre_filter):control.currentIndexChanged.connect(rebuild)
        status_group.buttonClicked.connect(rebuild)
        page.refresh_franchises=rebuild
        def view_changed():
            self.library_context['view_mode']=view.currentText();self.db.set_setting('library_view_mode',view.currentText());rebuild()
        view.currentTextChanged.connect(view_changed)
        scroll.setWidget(grid); outer.addWidget(scroll); self.replace(page); QTimer.singleShot(0,rebuild)
        if key=='all' and view.currentText()=='Franchises':self._request_library_relations()

    def show_airing(self):
        navigation_started=time.perf_counter(); season,year=current_anime_season(); label=season_label(season,year)
        self._airing_session_id=time.monotonic_ns()
        _append_playback_log(f"Navigation requested: Airing — {label}")
        self.current_view="airing"; self.current_anime_id=None; self._set_active_nav("airing")
        page=QWidget(); page_outer=QVBoxLayout(page); page_outer.setContentsMargins(22,18,22,18); self._top_header(page_outer)
        from .desktop_ui import library_header
        page_outer.addWidget(library_header("THIS SEASON",f"Airing · {label}","Current and upcoming anime from AniList"))
        scroll=AiringScrollArea("Airing")
        body=QWidget(); body.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred); outer=QVBoxLayout(body); outer.setAlignment(Qt.AlignTop); scroll.setWidget(body); page_outer.addWidget(scroll); self.replace(page)
        scroll.viewport_resized.connect(lambda width,reason,p=page,s=scroll:self._apply_airing_viewport(p,s,width,reason))
        _append_playback_log(f"Airing opened main_window_size={self.width()}x{self.height()} page_size={page.width()}x{page.height()} viewport_size={scroll.viewport().width()}x{scroll.viewport().height()}")
        self._schedule_airing_reflow()
        status=QLabel("Vee is checking the current AniList season…"); status.setObjectName("muted"); outer.addWidget(status)
        rows=self.db.anime_list(); by_anilist={int(row["anilist_id"]):row for row in rows if row["anilist_id"] is not None}

        rendered={"value":False}
        def render(catalog,source):
            if self.current_view!="airing": return
            rendered["value"]=True
            while outer.count():
                item=outer.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            current_raw=list(catalog.get("current") or []); upcoming_raw=list(catalog.get("upcoming") or [])
            trending_raw=list(catalog["trending"] if "trending" in catalog else current_raw)
            popular_raw=list(catalog["popular"] if "popular" in catalog else current_raw)
            currently_raw=list(catalog["currently"] if "currently" in catalog else current_raw)
            discovery_filter=lambda values:[item for item in values if item.get("isAdult") is not True]
            current=discovery_filter(current_raw); upcoming=discovery_filter(upcoming_raw)
            try: list_entries=json.loads(self.db.setting("anilist_user_list_cache","[]"))
            except (TypeError,ValueError): list_entries=[]
            remote_watching={int(entry["media"]["id"]) for entry in list_entries if entry.get("media") and entry["media"].get("id") and entry.get("status")=="CURRENT" and (entry.get("progress") or 0)>0}
            def actively_watching(item):
                row=by_anilist.get(int(item["id"])); local=bool(row and 0<(row["watched_count"] or 0)<(row["episode_count"] or 0))
                return local or int(item["id"]) in remote_watching
            watching=[item for item in current if actively_watching(item)]
            trending=discovery_filter(trending_raw)
            popular=discovery_filter(popular_raw)
            currently=discovery_filter(currently_raw)
            item_map={int(item["id"]):item for item in current+trending+popular+currently+upcoming}
            preview_count=max(4,max(self.width()-280,700)//240)
            next_season,next_year=next_anime_season(season,year)
            specs={"Trending Now":(season,year,None,"TRENDING_DESC"),
                   "Popular This Season":(season,year,None,"POPULARITY_DESC"),
                   "Currently Airing":(None,None,"RELEASING","POPULARITY_DESC"),
                   "Upcoming Next Season":(next_season,next_year,"NOT_YET_RELEASED","POPULARITY_DESC")}
            section_pages=catalog.get("section_pages") or {}
            def section(heading,section_items,view_all=False):
                section_widget=QWidget(); section_widget.setObjectName("airingSection"); section_widget.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
                section_layout=QVBoxLayout(section_widget); section_layout.setContentsMargins(0,0,0,0); section_layout.setSpacing(8)
                header=QHBoxLayout(); header.setContentsMargins(0,0,0,0); heading_label=QLabel(heading); heading_label.setObjectName("section"); header.addWidget(heading_label); header.addStretch()
                if view_all and section_items:
                    more=QPushButton("View All  →"); more.clicked.connect(lambda _,name=heading,rows=list(section_items),spec=specs.get(heading),initial=section_pages.get(heading):self.show_airing_all(name,rows,spec,initial)); header.addWidget(more)
                section_layout.addLayout(header)
                if not section_items:
                    empty=QLabel("Nothing here yet."); empty.setObjectName("muted"); section_layout.addWidget(empty); outer.addWidget(section_widget); return
                cards=[]
                for item in (section_items if not view_all else section_items[:preview_count]):
                    anilist_id=int(item["id"]); row=by_anilist.get(anilist_id)
                    card=SeasonCard(item,row is not None,self._load_remote_artwork,compact=True);self._register_status_card(card,'normal',self.db.entity_key_for_anime(row['id']) if row else 'anilist:'+str(item['id']))
                    card.clicked.connect(lambda value,local_rows=by_anilist,items=item_map:self.show_detail(local_rows[value]["id"]) if value in local_rows else self.show_remote_anilist(items[value]))
                    cards.append(card)
                section_layout.addWidget(ResponsiveSeasonGrid(cards,context=heading)); outer.addWidget(section_widget); self._schedule_airing_reflow()
            section("Watching This Season",watching); section("Trending Now",trending,True); section("Popular This Season",popular,True); section("Currently Airing",currently,True); section("Upcoming Next Season",upcoming,True); outer.addStretch()
            local_count=sum(1 for item in current if int(item["id"]) in by_anilist)
            _append_playback_log(f"Airing data: {source}\nPage visible: {(time.perf_counter()-navigation_started)*1000:.0f} ms\nSeason titles: {len(current)}\nUpcoming titles: {len(upcoming)}\nLocal matches: {local_count}")

        # Version the cache because pre-0.6.10 catalogs contained one combined RELEASING
        # list, not page-one results for each discovery query.
        cache_key=f"discovery-v4:{season}:{year}"; cached_key=self.db.setting("anilist_season_cache_key")
        try: cached=json.loads(self.db.setting("anilist_season_cache","[]")) if cached_key==cache_key else []
        except (TypeError,ValueError): cached=[]
        if cached: render(cached if isinstance(cached,dict) else {"current":cached,"upcoming":[]},"cached/reused")
        elif by_anilist:
            fallback=[]
            for anilist_id,row in by_anilist.items():
                metadata=json.loads(row["metadata_json"] or "{}")
                if metadata.get("status")=="RELEASING" and metadata.get("seasonYear")==year and metadata.get("season")==season:
                    fallback.append(metadata | {"id":anilist_id})
            if fallback: render({"current":fallback,"upcoming":[]},"local metadata fallback")

        if self.anilist_worker and self.anilist_worker.isRunning(): return
        worker=AniListWorker(fetch_airing_catalog,season,year); self.anilist_worker=worker
        def loaded(catalog):
            self.db.set_setting("anilist_season_cache_key",cache_key); self.db.set_setting("anilist_season_cache",json.dumps(catalog))
            render(catalog,"AniList refresh"); self.statusBar().showMessage(f"AniList season refreshed: {label}",5000)
        def failed(message):
            if self.current_view=="airing" and not rendered["value"]: status.setText(f"AniList is unavailable. {message}\nYour local library remains fully usable.")
            _append_playback_log(f"AniList season refresh failed: {message}")
        worker.succeeded.connect(loaded); worker.failed.connect(failed); worker.finished.connect(lambda:setattr(self,"anilist_worker",None)); worker.finished.connect(worker.deleteLater); worker.start()

    def show_airing_all(self,heading,items,query_spec=None,initial_page_result=None):
        session_id=time.monotonic_ns(); self._airing_session_id=session_id
        self.current_view="airing_all"; self.current_anime_id=None; self._set_active_nav("airing")
        items=list(items); rows=self.db.anime_list(); by_anilist={int(row["anilist_id"]):row for row in rows if row["anilist_id"] is not None}; item_map={int(item["id"]):item for item in items}
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(22,18,22,18); self._top_header(outer)
        top=QHBoxLayout(); back=QPushButton("←  Airing"); back.clicked.connect(self.show_airing); top.addWidget(back); title=QLabel(heading); title.setObjectName("title"); top.addWidget(title); top.addStretch(); outer.addLayout(top)
        filters=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Filter titles…"); filters.addWidget(search,2)
        sort=QComboBox(); sort.addItems(["Popularity","Score","Title","Start date"]); filters.addWidget(sort); sort_state={"explicit":False}
        formats=QComboBox(); formats.addItem("All formats"); formats.addItems(sorted({item.get("format") for item in items if item.get("format")})); filters.addWidget(formats)
        genres=QComboBox(); genres.addItem("All genres"); genres.addItems(sorted({genre for item in items for genre in (item.get("genres") or [])})); filters.addWidget(genres)
        ownership=QComboBox(); ownership.addItems(["All titles","In Library","Not in Library"]); filters.addWidget(ownership); outer.addLayout(filters)
        scroll=AiringScrollArea(f"View All: {heading}")
        host=QWidget(); host.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred); host_layout=QVBoxLayout(host); host_layout.setContentsMargins(0,8,0,8)
        grid=ResponsiveSeasonGrid([],context=f"View All: {heading}"); grid.setObjectName("airingResultsGrid"); host_layout.addWidget(grid)
        status=QLabel(); status.setObjectName("muted"); status.hide(); host_layout.addWidget(status,0,Qt.AlignHCenter)
        more=QPushButton("Load More"); more.setObjectName("primary"); more.hide(); host_layout.addWidget(more,0,Qt.AlignHCenter); host_layout.addStretch()
        scroll.setWidget(host); outer.addWidget(scroll); self.replace(page)
        scroll.viewport_resized.connect(lambda width,reason,p=page,s=scroll:self._apply_airing_viewport(p,s,width,reason)); self._schedule_airing_reflow()
        initial_page=1 if query_spec is not None and items else 0
        initial_page_info=(initial_page_result or {}).get("pageInfo") or {}
        initial_has_next=(bool(initial_page_info.get("hasNextPage")) if initial_page_result is not None else query_spec is not None)
        current={"grid":grid,"visible":[],"shown":0,"page":initial_page,"has_remote":initial_has_next,"loading":False,
                 "in_flight_page":None,"retry_attempts":{}}; batch_size=36
        _append_playback_log(f"Airing pagination initialized section={heading} session_id={session_id} initial_items={len(items)} current_page={initial_page} query_spec={query_spec}")
        retry_timer=QTimer(page); retry_timer.setSingleShot(True); retry_state={"callback":None}
        retry_timer.timeout.connect(lambda:retry_state["callback"]() if retry_state["callback"] else None)
        continue_timer=QTimer(page); continue_timer.setSingleShot(True); continue_timer.setInterval(0)
        def pipeline_counts(raw_values,existing_ids=None):
            raw_values=list(raw_values or []); after_adult=[item for item in raw_values if item.get("isAdult") is not True]
            # Format and status are server-side query filters.  Keep these explicit in the
            # diagnostics even when no format constraint is currently sent.
            after_format=list(after_adult); after_status=list(after_format)
            seen=set(existing_ids or ()); deduped=[]
            for item in after_status:
                value=int(item["id"])
                if value not in seen: seen.add(value); deduped.append(item)
            return {"raw":len(raw_values),"explicit_adult":sum(item.get("isAdult") is True for item in raw_values),
                    "adult":len(after_adult),"format":len(after_format),"status":len(after_status),
                    "dedupe":len(deduped)},deduped
        if query_spec is not None:
            season_name,season_year,media_status,media_sort=query_spec
            initial_raw=(initial_page_result or {}).get("items") if initial_page_result is not None else items
            initial_counts,_=pipeline_counts(initial_raw)
            initial_http=(initial_page_result or {}).get("httpStatus","cache")
            _append_playback_log(
                f"Airing query pipeline category={heading} page=1 perPage={SEASON_PAGE_SIZE} season={season_name} seasonYear={season_year} "
                f"status={media_status} format_filters=[] adult_filter=hide-explicit-adult sort={media_sort}\n"
                f"HTTP status={initial_http} raw API media count={initial_counts['raw']} API hasNextPage={initial_page_info.get('hasNextPage','unknown')}\n"
                f"adult removed={initial_counts['explicit_adult']} count after adult filtering={initial_counts['adult']} count after format filtering={initial_counts['format']} "
                f"count after status filtering={initial_counts['status']} count after dedupe={initial_counts['dedupe']} visible cards produced={len(items)}")
        def make_card(item):
            value=int(item["id"]); card=SeasonCard(item,value in by_anilist,self._load_remote_artwork,compact=True);self._register_status_card(card,"normal",self.db.entity_key_for_anime(by_anilist[value]["id"]) if value in by_anilist else "anilist:"+str(value))
            card.clicked.connect(lambda anime_id,local=by_anilist,data=item_map:self.show_detail(local[anime_id]["id"]) if anime_id in local else self.show_remote_anilist(data[anime_id])); return card
        def render_batch():
            visible=current["visible"]; start=current["shown"]; end=min(start+batch_size,len(visible))
            if start>=end:
                more.setVisible(current["has_remote"] and not current["loading"]); return
            current["grid"].append_cards(make_card(item) for item in visible[start:end]); current["shown"]=end; self._schedule_airing_reflow()
            more.setText(f"Load More  ({end} loaded)"); more.setVisible(end<len(visible) or current["has_remote"])
        def matches_filters(item):
            title_value=((item.get("title") or {}).get("english") or (item.get("title") or {}).get("romaji") or "")
            if search.text().casefold() not in title_value.casefold(): return False
            if formats.currentIndex()>0 and item.get("format")!=formats.currentText(): return False
            if genres.currentIndex()>0 and genres.currentText() not in (item.get("genres") or []): return False
            value=int(item["id"])
            if ownership.currentText()=="In Library" and value not in by_anilist: return False
            if ownership.currentText()=="Not in Library" and value in by_anilist: return False
            return True
        def rebuild(target_count=None):
            visible=[item for item in items if matches_filters(item)]
            mode=sort.currentText()
            if mode=="Score": visible.sort(key=lambda item:item.get("averageScore") or 0,reverse=True)
            elif mode=="Title": visible.sort(key=lambda item:((item.get("title") or {}).get("english") or (item.get("title") or {}).get("romaji") or "").casefold())
            elif mode=="Start date": visible.sort(key=lambda item:tuple((item.get("startDate") or {}).get(part) or 99 for part in ("year","month","day")))
            elif sort_state["explicit"]: visible.sort(key=lambda item:item.get("popularity") or 0,reverse=True)
            seen=set(); unique=[]
            for item in visible:
                value=int(item["id"])
                if value not in seen: seen.add(value); unique.append(item)
            current["visible"]=unique; current["shown"]=min(len(unique),target_count or batch_size)
            current["grid"].replace_cards(make_card(item) for item in unique[:current["shown"]]); self._schedule_airing_reflow()
            more.setText(f"Load More  ({current['shown']} loaded)"); more.setVisible(current["shown"]<len(unique) or current["has_remote"])
        for control in (search,formats,genres,ownership):
            (control.textChanged if isinstance(control,QLineEdit) else control.currentTextChanged).connect(rebuild)
        def sort_changed(): sort_state["explicit"]=True; rebuild()
        sort.currentTextChanged.connect(sort_changed)
        def load_more():
            if self.current_view!="airing_all" or self.stack.currentWidget() is not page or not isValid(grid):
                _append_playback_log(f"Airing lazy load discarded: inactive/deleted page\nSection/View All category: {heading}\nGrid instance/id: {id(grid)}\nGrid valid before append: {isValid(grid)}")
                return
            if current["shown"]<len(current["visible"]): render_batch(); return
            if not current["has_remote"] or not query_spec:
                more.setVisible(False); return
            if current["loading"] or current["in_flight_page"] is not None:
                _append_playback_log(f"LazyLoad duplicate suppressed section={heading} requested_page={current['page']+1} in_flight_page={current['in_flight_page']}")
                return
            current["loading"]=True; more.setEnabled(False); status.setText("Loading another AniList page…"); status.show()
            season_name,season_year,media_status,media_sort=query_spec; page_number=current["page"]+1
            current["in_flight_page"]=page_number; start_grid_id=grid.grid_id; request_timestamp=datetime.now(timezone.utc).isoformat()
            _append_playback_log(f"LazyLoad trigger section={heading} page={page_number} grid_id={start_grid_id} session_id={session_id}\nRequest timestamp={request_timestamp}\nQuery definition season={season_name} year={season_year} status={media_status} sort={media_sort}\nGrid instance/address: {hex(id(grid))}\nAppend target valid={isValid(grid)}\nCards before append={len(grid.cards)}")
            worker=AniListWorker(fetch_season_page,season_name,season_year,page_number,media_status,media_sort)
            self.airing_page_worker=worker
            def loaded(result):
                returned=len(result.get("items") or []); page_info=result.get("pageInfo") or {}; has_next=bool(page_info.get("hasNextPage")); http_status=int(result.get("httpStatus") or 200)
                valid=(self.current_view=="airing_all" and self.stack.currentWidget() is page and self._airing_session_id==session_id and isValid(grid) and grid.grid_id==start_grid_id)
                before=len(grid.cards) if valid else -1
                try:
                    current["loading"]=False; current["in_flight_page"]=None; current["page"]=page_number; current["has_remote"]=has_next
                    if not valid:
                        _append_playback_log(f"LazyLoad response page={page_number} request_timestamp={request_timestamp} HTTP status={http_status} results={returned} hasNextPage={has_next}\nLazyLoad discarded section={heading} grid_id={start_grid_id} session_id={session_id}\nAppend target valid={valid}"); return
                    old_shown=current["shown"]; existing={int(item["id"]) for item in items}; anchor_value=scroll.verticalScrollBar().value()
                    counts,accepted=pipeline_counts(result.get("items") or [],existing); added=len(accepted)
                    for item in accepted:
                        value=int(item["id"]); items.append(item); item_map[value]=item
                    status.setText(f"AniList page {page_number} loaded • {added} new titles"); more.setEnabled(True)
                    if sort_state["explicit"]:
                        rebuild(min(old_shown+batch_size,len(items)))
                        append_mode="explicit-sort-rebuild"
                    else:
                        visible_additions=[item for item in accepted if matches_filters(item)]
                        current["visible"].extend(visible_additions)
                        current["grid"].append_cards(make_card(item) for item in visible_additions)
                        current["shown"]=len(current["grid"].cards)
                        more.setText(f"Load More  ({current['shown']} loaded)")
                        more.setVisible(current["has_remote"])
                        append_mode="in-place"
                        QTimer.singleShot(0,lambda value=anchor_value,bar=scroll.verticalScrollBar():bar.setValue(min(value,bar.maximum())))
                    after=len(grid.cards)
                    _append_playback_log(
                        f"LazyLoad response page={page_number} request_timestamp={request_timestamp} HTTP status={http_status} results={returned} hasNextPage={has_next}\n"
                        f"Airing query pipeline category={heading} page={page_number} perPage={SEASON_PAGE_SIZE} season={season_name} seasonYear={season_year} "
                        f"status={media_status} format_filters=[] adult_filter=hide-explicit-adult sort={media_sort}\n"
                        f"raw API media count={counts['raw']} API hasNextPage={has_next} adult removed={counts['explicit_adult']} count after adult filtering={counts['adult']} "
                        f"count after format filtering={counts['format']} count after status filtering={counts['status']} "
                        f"count after dedupe={counts['dedupe']} visible cards produced={after}\n"
                        f"LazyLoad append section={heading} grid_id={start_grid_id} session_id={session_id} mode={append_mode}\nAppend target valid={valid}\n"
                        f"Scroll anchor before={anchor_value} after={scroll.verticalScrollBar().value()}\nCards before append={before}\nCards appended={max(0,after-before)}\nCards after append={after}")
                    more.setEnabled(current["shown"]<len(current["visible"]) or current["has_remote"])
                    if current["has_remote"] and added==0: continue_timer.start()
                except Exception as exc:
                    _append_playback_log(f"Airing lazy load exception\nSection/View All category: {heading}\nRequested AniList page: {page_number}\nGrid instance/id: {id(grid)}\nGrid valid before append: {isValid(grid)}\nException: {exc}")
            def failed(message):
                http_status=getattr(message,"status_code",None); retry_after=getattr(message,"retry_after",None)
                if http_status==429:
                    attempt=current["retry_attempts"].get(page_number,0)+1; current["retry_attempts"][page_number]=attempt
                    delay=max(1,int(retry_after or min(60,2**attempt))); status.setText(f"AniList rate limit reached. Retrying page {page_number} in {delay}s…"); status.show()
                    _append_playback_log(f"LazyLoad response page={page_number} request_timestamp={request_timestamp} HTTP status=429 hasNextPage=unknown\nRate-limit backoff seconds={delay} attempt={attempt}\nException: {message}")
                    def retry():
                        if current["in_flight_page"]==page_number:
                            current["loading"]=False; current["in_flight_page"]=None; load_more()
                    retry_state["callback"]=retry; retry_timer.start(delay*1000); return
                current["loading"]=False; current["in_flight_page"]=None; more.setEnabled(True); status.setText(f"Could not load the next AniList page: {message}"); status.show()
                _append_playback_log(f"LazyLoad response page={page_number} request_timestamp={request_timestamp} HTTP status={http_status or 'unknown'} hasNextPage=unknown\nAiring lazy load exception\nSection/View All category: {heading}\nGrid instance/id: {grid.grid_id}\nGrid valid before append: {isValid(grid)}\nException: {message}")
            worker.succeeded.connect(loaded); worker.failed.connect(failed)
            worker.finished.connect(lambda:setattr(self,"airing_page_worker",None) if self.airing_page_worker is worker else None)
            worker.finished.connect(worker.deleteLater); worker.start()
        more.clicked.connect(load_more); continue_timer.timeout.connect(load_more)
        def maybe_load(value):
            bar=scroll.verticalScrollBar()
            if more.isVisible() and value>=bar.maximum()-max(240,bar.pageStep()//2): load_more()
        scroll.verticalScrollBar().valueChanged.connect(maybe_load); rebuild()

    def show_remote_anilist(self,item,source="Airing"):
        if self.db.observe_classifications([item],allow_normal=False):self._library_cache_dirty=True
        started=time.perf_counter();restricted=source=="Restricted";scope="restricted" if restricted else "normal"
        if scope=='normal' and item.get('type','ANIME')!='MANGA' and any(self.db.anime_scope(row)=='restricted' for row in self.db.connection.execute('SELECT id FROM anime WHERE anilist_id=?',(item['id'],))):return
        if not self._organization_allowed(scope) or (item.get("isAdult") is True)!=restricted:return
        media_type=item.get("type") or "ANIME";self.current_view="restricted_detail" if restricted else "airing_detail";self.current_anime_id=None;self.current_remote_item=item;self.current_remote_source=source
        self._set_active_nav("restricted" if restricted else "discover" if source in {"Discover","Saved"} else "airing")
        entity=self.organization(scope).resolve('anilist:'+str(item['id']),item);local_row=entity.local if entity else None
        if local_row and restricted:
            if media_type=='MANGA':return self.show_manga_detail(local_row['id'])
            return self.show_detail(local_row['id'])
        page=QWidget();page.setProperty("transientPage",True);outer=QVBoxLayout(page);outer.setContentsMargins(18,14,18,14);self._top_header(outer)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();flow=QVBoxLayout(body);flow.setSpacing(18);scroll.setWidget(body);outer.addWidget(scroll)
        back=QPushButton("← Back");back.clicked.connect(self.navigate_back);flow.addWidget(back,0,Qt.AlignLeft)
        hero=DetailBackdrop();hero.setMinimumHeight(380);layout=QHBoxLayout(hero);layout.setContentsMargins(22,22,26,22)
        if item.get('bannerImage'):self._load_remote_artwork(item['bannerImage'],hero.banner,1200,450)
        cover=QLabel("NO ARTWORK");cover.setFixedSize(220,310);cover.setAlignment(Qt.AlignCenter);cover.setStyleSheet("background:#171f2b;border-radius:10px;color:#707d8c");layout.addWidget(cover,0,Qt.AlignTop)
        url=(item.get('coverImage') or {}).get('extraLarge') or (item.get('coverImage') or {}).get('large')
        if url:self._load_remote_artwork(url,cover,220,310)
        info=QVBoxLayout();title=QLabel((item.get('title') or {}).get('english') or (item.get('title') or {}).get('romaji') or 'Untitled');title.setObjectName('heroTitle');title.setWordWrap(True);title_row=QHBoxLayout();title_row.addWidget(title,1);title_row.addWidget(self._detail_collections_button(scope,anime_id=local_row['id'] if local_row and media_type=='ANIME' else None,item=item,manga_id=local_row['id'] if local_row and media_type=='MANGA' else None),0,Qt.AlignTop);info.addLayout(title_row)
        year=item.get('seasonYear') or (item.get('startDate') or {}).get('year')
        values=[year,item.get('format'),str(item.get('status') or '').replace('_',' ').title(),', '.join(item.get('genres') or [])]
        if media_type=='MANGA':values.extend([str(item['chapters'])+' chapters' if item.get('chapters') else None,str(item['volumes'])+' volumes' if item.get('volumes') else None])
        elif item.get('episodes'):values.append(str(item['episodes'])+' episodes')
        metadata=QLabel(' • '.join(str(value) for value in values if value));metadata.setWordWrap(True);info.addWidget(metadata)
        synopsis=QLabel(item.get('description') or 'No synopsis is available.');synopsis.setWordWrap(True);synopsis.setTextFormat(Qt.RichText);synopsis.setOpenExternalLinks(True);info.addWidget(synopsis)
        next_airing=item.get('nextAiringEpisode') or {}
        if media_type=='ANIME' and next_airing.get('episode'):info.addWidget(QLabel('Next airing: Episode '+str(next_airing['episode'])))
        info.addWidget(self._direct_status_controls(scope,anime_id=local_row['id'] if local_row and media_type=='ANIME' else None,item=item,manga_id=local_row['id'] if local_row and media_type=='MANGA' else None))
        actions=QHBoxLayout()
        if local_row:
            badge=QPushButton('◈  In Vault');badge.setObjectName('primary');badge.clicked.connect(lambda:self.show_manga_detail(local_row['id']) if media_type=='MANGA' else self.show_detail(local_row['id']));actions.addWidget(badge)
        if scope=='normal' and media_type=='ANIME' and not local_row:
            from .requests_ui import request_button
            request=request_button(self,item)
            if request:actions.addWidget(request)
        actions.addStretch();info.addLayout(actions)
        note=QLabel('AniList • '+media_type.title()+(' • In Vault' if local_row else ' • Metadata only; add local media to '+('read' if media_type=='MANGA' else 'play')));note.setObjectName('muted');note.setWordWrap(True);info.addWidget(note)
        layout.addLayout(info,1);flow.addWidget(hero);flow.addWidget(self._related_panel(item,scope,presentation='discovery'));flow.addStretch();self.replace(page)
        _append_playback_log(f"DetailLoad media_type={media_type} remote_id={item['id']} elapsed_ms={(time.perf_counter()-started)*1000:.0f}")

    def _state_matches(self,row,state):
        total=row["episode_count"] or 0; watched=row["watched_count"] or 0
        return (state=="All states" or (state=="Watched" and watched>0) or
                (state=="Unwatched" and watched==0) or (state=="In Progress" and 0<watched<total) or
                (state=="Completed" and total>0 and watched==total) or
                (state=="Has Extras" and (row["extras_count"] or 0)>0) or (state=="Favorites" and row["favorite"]))

    def show_detail(self, anime_id):
        detail_started=time.perf_counter()
        anime=self.db.anime(anime_id)
        if not anime:return self.show_home()
        media=self.db.media(anime_id);metadata=json.loads(anime["metadata_json"] or "{}")
        scope=self.db.anime_scope(anime)
        if not self._organization_allowed(scope):return
        self.current_view="detail";self.current_anime_id=anime_id
        if scope=="restricted":self.current_view="restricted_anime_detail";self._set_active_nav("restricted")
        page=QWidget();page.setProperty("transientPage",True); page_layout=QVBoxLayout(page); page_layout.setContentsMargins(18,14,18,14); self._top_header(page_layout)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); outer=QVBoxLayout(body); scroll.setWidget(body); page_layout.addWidget(scroll)
        back=QPushButton("←  Back"); back.clicked.connect(self.navigate_back); outer.addWidget(back,0,Qt.AlignLeft)
        display_title=(metadata.get("title",{}).get("english") or metadata.get("title",{}).get("romaji")
                       or anime["parsed_search_title"] or anime["title"] or anime["source_folder_name"] or "Unknown Anime")
        normal=[m for m in media if m["kind"]=="episode"]; watched=sum(1 for m in normal if m["watched"])
        banner_path=metadata.get("banner_path") or metadata.get("cover_path"); hero=BackdropFrame(banner_path);hero.safe_focal=scope=="restricted"; hero.setMinimumHeight(360); hero_layout=QHBoxLayout(hero); hero_layout.setContentsMargins(22,22,30,22)
        poster=QLabel("NO ARTWORK"); poster.setAlignment(Qt.AlignCenter); poster.setFixedSize(220,300); poster.setStyleSheet("background:#141d29;border:1px solid #39465a;border-radius:12px;color:#7c8898")
        cover=metadata.get("cover_path")
        poster_pixmap=_scaled_artwork(cover,poster.width(),poster.height())
        if not poster_pixmap.isNull(): poster.setPixmap(poster_pixmap)
        hero_layout.addWidget(poster); content=QVBoxLayout(); content.addStretch(); title=QLabel(display_title); title.setObjectName("heroTitle"); title.setWordWrap(True); content.addWidget(title)
        info_values=[metadata.get("seasonYear"),metadata.get("format"),anime["category"],", ".join(metadata.get("genres") or [])]
        info=QLabel("  •  ".join(str(x) for x in info_values if x)); content.addWidget(info)
        synopsis=QLabel(metadata.get("description") or "No online metadata matched yet."); synopsis.setWordWrap(True); synopsis.setMaximumWidth(760); content.addWidget(synopsis)
        status=self.db.manual_status(scope,anime_id=anime_id)
        available=any(m["present"] for m in normal);content.addWidget(QLabel("Anime · In Vault" if available else "Anime · Missing / unavailable · history preserved"))
        progress_text=QLabel(f"{watched} / {len(normal)} watched"); progress_text.setObjectName("section"); content.addWidget(progress_text)
        progress=QProgressBar(); progress.setRange(0,max(len(normal),1)); progress.setValue(watched); progress.setTextVisible(False); progress.setMaximumWidth(760); content.addWidget(progress)
        actions=QHBoxLayout(); next_episode=self.db.next_unwatched(anime_id)
        if next_episode:
            continue_button=QPushButton(f"▶  Continue Episode {next_episode['episode']}"); continue_button.setObjectName("primary"); continue_button.clicked.connect(lambda:self.continue_episode(anime_id)); actions.addWidget(continue_button)
        folder=QPushButton("▣  Open Folder"); folder.clicked.connect(lambda:self.open_folder(anime["root_path"])); actions.addWidget(folder)
        favorite=QPushButton("♥  Favorited" if anime["favorite"] else "♡  Favorite"); favorite.clicked.connect(lambda:self.toggle_favorite(anime_id,not anime["favorite"])); actions.addWidget(favorite);actions.addWidget(self._detail_collections_button(scope,anime_id=anime_id)); actions.addStretch(); content.addLayout(actions); from .ratings import rating_control; content.addWidget(rating_control(self,scope,"ANIME",anime_id)); hero_layout.addLayout(content,1); outer.addWidget(hero)

        content.addWidget(self._direct_status_controls(scope,anime_id=anime_id))
        collection_ids=self.db.anime_collection_ids(anime_id);chips=QHBoxLayout()
        for collection in self.db.collections("Name",scope):
            if collection["id"] in collection_ids:
                chip=QPushButton(collection["name"]);chip.clicked.connect(lambda _,cid=collection["id"]:self.show_collection_detail(cid,scope));chips.addWidget(chip)
        if chips.count():outer.addLayout(chips)
        utility=QHBoxLayout(); all_watched=QPushButton("Mark All Watched"); all_watched.clicked.connect(lambda:self.mark_all(anime_id,True)); utility.addWidget(all_watched)
        all_unwatched=QPushButton("Mark All Unwatched"); all_unwatched.clicked.connect(lambda:self.mark_all(anime_id,False)); utility.addWidget(all_unwatched)
        match=QPushButton("Match / Change AniList Entry"); match.clicked.connect(lambda:self.match_anime(anime_id,anime["title"])); utility.addWidget(match); utility.addStretch(); outer.addLayout(utility)

        lists=QHBoxLayout(); episodes=ContainedListWidget(); extras=ContainedListWidget(); next_id=next_episode["id"] if next_episode else None
        for m in media:
            if m["kind"]=="episode":
                number=f"{m['episode']:02d}" if m["episode"] is not None else "—"
                titles=metadata.get("episode_titles") or {}; explicit=titles.get(str(m["episode"])) or titles.get(m["episode"]) or ""
                label=f"{'●' if m['watched'] else '▶' if m['id']==next_id else '○'}   {number}   {clean_episode_label(m['path'],m['episode'],explicit)}"
                item=QListWidgetItem(label); item.setData(Qt.UserRole,m["path"]); item.setData(Qt.UserRole+1,m["id"]); item.setData(Qt.UserRole+2,m["kind"])
                if m["watched"]: item.setForeground(QColor("#9a8296"))
                elif m["id"]==next_id: item.setForeground(QColor("#ff6a96"))
                episodes.addItem(item)
        groups=(("Specials",{"special","movie"}),("Artwork & Scans",{"artwork"}),("Audio",{"audio"}),("Other Files",{"other"}))
        for heading,kinds in groups:
            group=[m for m in media if m["kind"] in kinds]
            if not group: continue
            header=QListWidgetItem(f"  {heading} ({len(group)})"); header.setFlags(Qt.NoItemFlags); header.setForeground(QColor("#ff6a96")); extras.addItem(header)
            for m in group:
                item=QListWidgetItem(f"    {Path(m['path']).name}"); item.setData(Qt.UserRole,m["path"]); item.setData(Qt.UserRole+1,m["id"]); item.setData(Qt.UserRole+2,m["kind"]); extras.addItem(item)
        episodes.setContextMenuPolicy(Qt.CustomContextMenu); extras.setContextMenuPolicy(Qt.CustomContextMenu)
        episodes.customContextMenuRequested.connect(lambda pos:self.episode_menu(episodes,pos,anime_id))
        extras.customContextMenuRequested.connect(lambda pos:self.classify_menu(extras,pos,anime_id))
        episodes.itemDoubleClicked.connect(lambda i:self.play(i.data(Qt.UserRole),i.data(Qt.UserRole+1),anime_id))
        extras.itemDoubleClicked.connect(lambda i:self.open_media(i.data(Qt.UserRole)))
        left=QVBoxLayout(); h=QLabel(f"Episodes ({len(normal)})"); h.setObjectName("section"); left.addWidget(h); left.addWidget(episodes)
        right=QVBoxLayout(); h=QLabel("Extras"); h.setObjectName("section"); right.addWidget(h)
        if extras.count(): right.addWidget(extras)
        panel=QFrame(); panel.setObjectName("panel"); panel_layout=QVBoxLayout(panel); panel_layout.addWidget(QLabel("Information"))
        fields=(("Japanese title",(metadata.get("title") or {}).get("native")),("Year",metadata.get("seasonYear")),("Episodes",metadata.get("episodes") or len(normal)),("Status",metadata.get("status")),("Format",metadata.get("format")),("Genres",", ".join(metadata.get("genres") or [])))
        for field,value in fields:
            if value: panel_layout.addWidget(QLabel(f"{field}:  {value}"))
        right.addWidget(panel);right.addWidget(self._related_panel({**metadata,'id':anime['anilist_id'],'type':'ANIME'},scope));right.addStretch()
        lists.addLayout(left,2); lists.addLayout(right,1); outer.addLayout(lists); self.replace(page)
        _append_playback_log(f"DetailLoad media_type=ANIME local_id={anime_id} episodes={len(normal)} extras={extras.count()} elapsed_ms={(time.perf_counter()-detail_started)*1000:.0f}")

    def toggle_favorite(self,anime_id,value):
        if not self._local_anime_allowed(anime_id):return
        self.db.set_favorite(anime_id,value); self._library_cache_dirty=True; self.show_detail(anime_id)

    def mark_all(self,anime_id,watched):
        if not self._local_anime_allowed(anime_id):return
        if watched and not AniVaultDialog.confirm(self,"Mark All Watched","Mark every normal episode as watched?","Mark All Watched"): return
        if not watched:
            anime=self.db.anime(anime_id); metadata=json.loads(anime["metadata_json"] or "{}") if anime else {}; previous=int(metadata.get("anilist_user_progress") or 0)
            if self.db.setting("anilist_sync_progress","0")=="1" and previous>=5:
                message=f"This will mark the series unwatched locally and lower AniList progress from {previous} to 0. Continue?"
                if not AniVaultDialog.confirm(self,"Confirm Progress Reset",message,"Reset Progress"): return
        self.db.set_all_watched(anime_id,watched); self._library_cache_dirty=True
        self._maybe_sync_anilist_progress(anime_id,"mark all",allow_decrease=not watched); self.show_detail(anime_id)

    def mark_episode(self,anime_id,media_id,watched):
        if not self._local_anime_allowed(anime_id,media_id=media_id):return
        self.db.set_watched(media_id,watched); self._library_cache_dirty=True
        self._maybe_sync_anilist_progress(anime_id,"manual watched" if watched else "manual unwatched",allow_decrease=not watched); self.show_detail(anime_id)

    def continue_episode(self,anime_id):
        episode=self.db.next_unwatched(anime_id)
        if episode: self.play(episode["path"],episode["id"],anime_id)

    def open_folder(self,path):
        folder=Path(path)
        if not folder.exists(): AniVaultDialog.alert(self,"Folder Unavailable",f"This folder no longer exists:\n{path}"); return
        if sys.platform=="win32": os.startfile(str(folder))
        else: subprocess.Popen(["xdg-open",str(folder)])

    def episode_menu(self,widget,pos,anime_id):
        item=widget.itemAt(pos)
        if not item: return
        menu=QMenu(self); play=menu.addAction("Play in AniVault"); play.triggered.connect(lambda:self.play_integrated(item.data(Qt.UserRole),item.data(Qt.UserRole+1),anime_id))
        external=menu.addAction("Open in External VLC"); external.triggered.connect(lambda:self.play_external(item.data(Qt.UserRole),item.data(Qt.UserRole+1),anime_id))
        watched=menu.addAction("Mark Watched"); watched.triggered.connect(lambda:self.mark_episode(anime_id,item.data(Qt.UserRole+1),True))
        unwatched=menu.addAction("Mark Unwatched"); unwatched.triggered.connect(lambda:self.mark_episode(anime_id,item.data(Qt.UserRole+1),False))
        location=menu.addAction("Open File Location"); location.triggered.connect(lambda:self.open_folder(str(Path(item.data(Qt.UserRole)).parent)))
        menu.addSeparator(); submenu=menu.addMenu("Change Type")
        for label,kind in (("Special","special"),("OVA / OAD","special"),("Movie","movie"),("Other","other"),("Ignore","ignore")):
            action=submenu.addAction(label); action.triggered.connect(lambda _,k=kind,p=item.data(Qt.UserRole):(self.db.override(p,k),self.show_detail(anime_id)))
        menu.exec(widget.mapToGlobal(pos))

    def match_anime(self, anime_id, title):
        dialog=MatchDialog(self,title)
        if dialog.exec() and dialog.selected:
            try: selected=cache_artwork(dialog.selected,APP_DIR/"cache"/"artwork")
            except Exception as exc:
                selected=dialog.selected; AniVaultDialog.alert(self,"Artwork Cache",f"The match was saved, but artwork could not be cached.\n\n{exc}")
            self.db.set_metadata(anime_id,selected["id"],selected); self._library_cache_dirty=True; self.show_detail(anime_id)

    def classify_menu(self, widget, pos, anime_id):
        item=widget.itemAt(pos)
        if not item or not item.data(Qt.UserRole): return
        menu=QMenu(self); submenu=menu.addMenu("Change Type")
        kinds=(("Episode","episode"),("Special","special"),("OVA / OAD","special"),("Movie","movie"),
               ("Audio","audio"),("Artwork","artwork"),("Other","other"),("Ignore","ignore"))
        for label,kind in kinds:
            action=submenu.addAction(label); action.triggered.connect(lambda _,k=kind,p=item.data(Qt.UserRole):(self.db.override(p,k),self.show_detail(anime_id)))
        menu.exec(widget.mapToGlobal(pos))

    def open_media(self,path):
        if not self._local_anime_allowed(path=path):return
        if not path: return
        if Path(path).suffix.lower() in {".png",".jpg",".jpeg",".webp"}: self.show_image(path)
        else: self.play(path)

    def show_image(self,path):
        if not self._local_anime_allowed(path=path):return
        dialog=QDialog(self); dialog.setWindowTitle(Path(path).name); dialog.resize(1000,720)
        layout=QVBoxLayout(dialog); scroll=QScrollArea(); label=QLabel(); label.setAlignment(Qt.AlignCenter)
        pix=QPixmap(path); label.setPixmap(pix.scaled(950,650,Qt.KeepAspectRatio,Qt.SmoothTransformation)); scroll.setWidget(label); scroll.setWidgetResizable(True); layout.addWidget(scroll); dialog.exec()

    def show_first_run(self):
        """Short local setup only for a genuinely new database."""
        self.current_view="setup"; self.current_anime_id=None; self._set_active_nav("settings")
        page=QWidget(); page.setObjectName("firstRunSetup");layout=QVBoxLayout(page);layout.setContentsMargins(40,30,40,30);layout.setSpacing(14)
        title=QLabel("Welcome to AniVault");title.setObjectName("title");layout.addWidget(title)
        copy=QLabel("Your anime, your library. AniVault indexes and reads your media; it never renames, moves, converts, or rewrites source files. You can skip setup and add libraries later in Settings.");copy.setWordWrap(True);layout.addWidget(copy)
        anime_root=QLineEdit();anime_root.setObjectName("setupAnimeRoot");anime_root.setPlaceholderText("Anime library folder (optional)")
        manga_root=QLineEdit();manga_root.setObjectName("setupMangaRoot");manga_root.setPlaceholderText("Manga library folder (optional)")
        for label,edit in (("Anime",anime_root),("Manga",manga_root)):
            layout.addWidget(QLabel(label));row=QHBoxLayout();row.addWidget(edit);button=QPushButton("Choose Folder…")
            def choose(_checked=False,target=edit):
                path=QFileDialog.getExistingDirectory(self,"Choose Library Folder")
                if path:target.setText(path)
            button.clicked.connect(choose);row.addWidget(button);layout.addLayout(row)
        layout.addWidget(QLabel("AniList linking is optional. Continue to Settings to link your account with guided browser authorization, or skip it."))
        def finish(settings=False):
            paths=[edit.text().strip() for edit in (anime_root,manga_root)]
            if any(path and not Path(path).is_dir() for path in paths):
                AniVaultDialog.alert(self,"Folder unavailable","Choose an accessible folder or leave it blank to continue.");return
            if paths[0]:self.db.set_setting("library_root",paths[0])
            if paths[1]:self.manga_store.add_root(paths[1],"normal")
            self.db.set_setting("setup_complete","1")
            self.show_settings() if settings else self.show_home()
            if not settings:
                if paths[0]:self.rescan()
                if paths[1]:self.scan_manga_library()
        actions=QHBoxLayout();start=QPushButton("Start AniVault");start.setObjectName("primary");start.clicked.connect(lambda:finish());actions.addWidget(start)
        account=QPushButton("Continue to Settings / AniList");account.clicked.connect(lambda:finish(True));actions.addWidget(account);actions.addStretch();layout.addLayout(actions);layout.addStretch();self.replace(page)

    def refresh_artwork_cache(self):
        # Only disposable decoded/network artwork caches, never metadata/source art.
        _ARTWORK_PIXMAP_CACHE.clear();self._remote_artwork_cache.clear();self._http_art_cache.clear()
        self.statusBar().showMessage("Artwork cache refreshed. Existing artwork remains visible; future loads use fresh cache entries.",6000)
        _append_playback_log("ArtworkCache result=refreshed metadata_retained=true source_media_modified=false")

    def check_vlc_runtime(self,path):
        from .vlc_runtime import discover_vlc,python_architecture
        try:
            installation=discover_vlc(path)
            message=f"AniVault is {python_architecture()}-bit. Compatible VLC found at:\n{installation.directory}\n\nIntegrated playback validates libVLC when a video opens."
            _append_playback_log(f"VLCDependency result=compatible python_bits={python_architecture()} library={installation.library} plugins={installation.plugins}")
        except Exception as exc:
            message=str(exc)+"\n\nInstall matching desktop VLC, then select its executable here. External VLC remains available."
            _append_playback_log(f"VLCDependency result=unavailable exception={type(exc).__name__} message={exc}")
        AniVaultDialog.alert(self,"VLC Runtime",message)

    def show_settings(self):
        self.current_view="settings"; self.current_anime_id=None; self._set_active_nav("settings")
        page=QWidget(); shell=QVBoxLayout(page);shell.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();scroll.setWidget(body);shell.addWidget(scroll)
        layout=QVBoxLayout(body); layout.setContentsMargins(28,22,28,22); self._top_header(layout); t=QLabel("AniVault Settings"); t.setObjectName("title"); layout.addWidget(t)
        intro=QLabel("Your anime, your library. Existing app data is preserved automatically."); intro.setObjectName("muted");intro.setWordWrap(True); layout.addWidget(intro)
        layout.addWidget(self.lan_server.settings())
        root=QLineEdit(self.db.setting("library_root","")); vlc=QLineEdit(self.db.setting("vlc_path",""))
        def picker(edit,folder=False):
            path=QFileDialog.getExistingDirectory(self,"Choose folder") if folder else QFileDialog.getOpenFileName(self,"Choose VLC",filter="Programs (*.exe)")[0]
            if path: edit.setText(path)
        for label,edit,folder in (("Anime library root",root,True),("VLC executable",vlc,False)):
            layout.addWidget(QLabel(label)); row=QHBoxLayout(); row.addWidget(edit); b=QPushButton("Browse"); b.clicked.connect(lambda _,e=edit,f=folder:picker(e,f)); row.addWidget(b); layout.addLayout(row)
        appearance=QLabel("Appearance / Startup"); appearance.setObjectName("section");layout.addWidget(appearance)
        show_splash=QCheckBox("Show splash screen");show_splash.setObjectName("showSplash");show_splash.setChecked(self.db.setting("show_splash","1")=="1");layout.addWidget(show_splash)
        splash_duration=QComboBox();splash_duration.setObjectName("splashDuration");splash_duration.addItems(["Brief","Standard","Extended"]);splash_duration.setCurrentText(self.db.setting("splash_duration","Standard"));layout.addWidget(QLabel("Minimum splash duration (1 / 2.75 / 5 seconds)"));layout.addWidget(splash_duration)
        support=QHBoxLayout();logs=QPushButton("Open Diagnostics Folder");logs.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR))));support.addWidget(logs)
        runtime=QPushButton("Check VLC Runtime");runtime.clicked.connect(lambda:self.check_vlc_runtime(vlc.text()));support.addWidget(runtime);layout.addLayout(support)
        refresh_art=QPushButton("Refresh Artwork Cache");refresh_art.clicked.connect(self.refresh_artwork_cache);layout.addWidget(refresh_art,0,Qt.AlignLeft)
        try: schema=json.loads((APP_DIR/'release-state.json').read_text()).get('schema_fingerprint','unknown')[:12]
        except (OSError,ValueError):schema='unknown'
        release=QLabel("AniVault "+APP_VERSION+" • Build "+APP_VERSION+" • Schema fingerprint "+schema+"\nUser data: "+str(APP_DIR));release.setObjectName("muted");release.setWordWrap(True);layout.addWidget(release)
        from .updates import RELEASE_REPOSITORY, check_release, release_index, download_installer, launch_installer_after_exit
        updates=QLabel("Application updates");updates.setObjectName("section");layout.addWidget(updates)
        status=QLabel("Installed: "+APP_VERSION);status.setTextFormat(Qt.PlainText);status.setWordWrap(True);layout.addWidget(status)
        actions=QHBoxLayout();check=QPushButton("Check for updates");open_release=QPushButton("Open GitHub Releases")
        install=QPushButton("Install update");install.hide()
        actions.addWidget(check);actions.addWidget(install);actions.addWidget(open_release);actions.addStretch();layout.addLayout(actions)
        import concurrent.futures
        from urllib.error import HTTPError
        check.setEnabled(bool(RELEASE_REPOSITORY));open_release.setEnabled(bool(RELEASE_REPOSITORY))
        target=[release_index(RELEASE_REPOSITORY) if RELEASE_REPOSITORY else ""]
        open_release.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(target[0])))
        timer=QTimer(self);timer.setInterval(150)
        pending=[];available=[];installing=[False]
        page.destroyed.connect(lambda:timer.deleteLater() if not installing[0] else None)
        def finished():
            if not pending or not pending[0].done():return
            timer.stop()
            if isValid(check):check.setEnabled(True)
            try:
                result=pending.pop().result()
                if installing[0]:
                    try:
                        launch_installer_after_exit(result,available[0][3])
                    except (OSError,ValueError):
                        from shutil import rmtree
                        rmtree(result.parent,ignore_errors=True)
                        raise
                    self._update_downloading=False
                    self.close()
                    return
                if result:
                    available[:]=[result]
                    install.setVisible(sys.platform=="win32" and getattr(sys,"frozen",False))
                    tag,url,notes,digest=result;target[0]=url
                    status.setText(f"Installed: {APP_VERSION}\nAvailable: {tag}\n{notes}")
                else:status.setText(f"Installed: {APP_VERSION} · Up to date")
            except HTTPError as exc:
                if isValid(status):status.setText("Release information is unavailable. For a private repository, sign in on GitHub and use Open GitHub Releases." if exc.code in (401,403,404) else f"GitHub returned HTTP {exc.code}. Try again later.")
            except (OSError,ValueError) as exc:
                if isValid(status):status.setText(f"Update failed: {exc}")
                elif not self._closing:AniVaultDialog.alert(self,"Update failed",str(exc))
            finally:
                if installing[0]:self._update_downloading=False
                installing[0]=False
                if isValid(install):install.setEnabled(True)
                else:timer.deleteLater()
        def start_install():
            if pending or not available or getattr(self,'_update_downloading',False):return
            installing[0]=True
            self._update_downloading=True
            status.setText("Downloading and verifying update…")
            install.setEnabled(False);check.setEnabled(False)
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            pending.append(pool.submit(download_installer,available[0]))
            pool.shutdown(wait=False);timer.start()
        install.clicked.connect(start_install)
        timer.timeout.connect(finished)
        def start_check():
            if pending or not RELEASE_REPOSITORY:return
            available.clear();install.hide()
            check.setEnabled(False);status.setText(f"Installed: {APP_VERSION} · Checking…")
            with_pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            pending.append(with_pool.submit(check_release,RELEASE_REPOSITORY,APP_VERSION))
            with_pool.shutdown(wait=False);timer.start()
        check.clicked.connect(start_check)
        auto=QCheckBox("Check automatically when opening Settings")
        auto.setEnabled(bool(RELEASE_REPOSITORY));auto.setChecked(self.db.setting("auto_update_check","0")=="1")
        auto.toggled.connect(lambda enabled:self.db.set_setting("auto_update_check",int(enabled)));layout.addWidget(auto)
        if not RELEASE_REPOSITORY:status.setText(f"Installed: {APP_VERSION} · Desktop release repository is not configured.")
        elif auto.isChecked():start_check()
        playback_title=QLabel("Playback"); playback_title.setObjectName("section"); layout.addWidget(playback_title)
        player_choice=QComboBox(); player_choice.addItems(["Integrated AniVault Player","External VLC"]); player_choice.setCurrentText(self.db.setting("default_player","Integrated AniVault Player")); layout.addWidget(QLabel("Default player")); layout.addWidget(player_choice)
        autoplay=QCheckBox("Automatically play next episode"); autoplay.setChecked(self.db.setting("autoplay_next","0")=="1"); layout.addWidget(autoplay)
        seek_step=QComboBox(); seek_step.addItems(["5 sec","10 sec"]); seek_step.setCurrentText(f"{self.db.setting('seek_step','5')} sec"); layout.addWidget(QLabel("Seek step")); layout.addWidget(seek_step)
        remember_volume=QCheckBox("Remember volume"); remember_volume.setChecked(self.db.setting("remember_volume","1")=="1"); layout.addWidget(remember_volume)
        hover_previews=QCheckBox("Timeline hover preview thumbnails"); hover_previews.setChecked(self.db.setting("hover_previews","1")=="1"); layout.addWidget(hover_previews)
        from .reading_settings import ReadingSettings
        reading_title=QLabel("Reading");reading_title.setObjectName("section");layout.addWidget(reading_title)
        reading_settings=ReadingSettings(self.db);layout.addWidget(reading_settings)
        anilist_title=QLabel("AniList Account (optional)"); anilist_title.setObjectName("section"); layout.addWidget(anilist_title)
        account_name=self.db.setting("anilist_user_name")
        account=QLabel(f"Linked as {account_name}" if account_name else "Not linked — AniVault remains fully functional with local state only."); account.setObjectName("muted");account.setWordWrap(True); layout.addWidget(account)
        instructions=QLabel("1. Click Link AniList to open authorization in your browser.\n2. Approve AniVault, then copy the code shown by AniList.\n3. Paste it below and click Validate / Link. It stays only in your local app data.");instructions.setWordWrap(True);layout.addWidget(instructions)
        browser_link=QPushButton("Link AniList — Open Authorization");browser_link.setObjectName("linkAniList");browser_link.setObjectName("primary");layout.addWidget(browser_link,0,Qt.AlignLeft)
        def authorize():
            from .anilist_login import authorization_url
            try:url=authorization_url()
            except ValueError as exc:AniVaultDialog.alert(self,"AniList Link",str(exc));return
            if not QDesktopServices.openUrl(QUrl(url)):AniVaultDialog.alert(self,"AniList Link","Could not open your browser. Check your default browser and try again.")
        browser_link.clicked.connect(authorize)
        layout.addWidget(QLabel("AniList authorization PIN / code"))
        token=QLineEdit();token.setEchoMode(QLineEdit.Password);token.setPlaceholderText("Paste the code from AniList here"); layout.addWidget(token)
        sync_progress=QCheckBox("Update AniList progress when local episodes are marked watched"); sync_progress.setChecked(self.db.setting("anilist_sync_progress","0")=="1"); layout.addWidget(sync_progress)
        account_actions=QGridLayout(); link=QPushButton("Validate / Link"); refresh=QPushButton("Refresh AniList List"); disconnect=QPushButton("Disconnect")
        for index,button in enumerate((link,refresh,disconnect)):account_actions.addWidget(button,index//2,index%2)
        layout.addLayout(account_actions)
        def run_account(operation,args,on_success):
            if self.anilist_worker and self.anilist_worker.isRunning(): self.statusBar().showMessage("An AniList request is already running.",4000); return
            worker=AniListWorker(operation,*args); self.anilist_worker=worker; link.setEnabled(False); refresh.setEnabled(False)
            worker.succeeded.connect(lambda result:on_success(result) if not self._closing else None); worker.failed.connect(lambda message:AniVaultDialog.alert(self,"AniList",str(message)) if not self._closing else None)
            worker.finished.connect(lambda:(setattr(self,"anilist_worker",None),link.setEnabled(True),refresh.setEnabled(True))); worker.finished.connect(worker.deleteLater); worker.start()
        def linked(viewer):
            self.db.set_setting("anilist_access_token",token.text().strip()); self.db.set_setting("anilist_user_id",viewer["id"]); self.db.set_setting("anilist_user_name",viewer["name"])
            token.clear();account.setText(f"Linked as {viewer['name']}"); self.statusBar().showMessage("AniList account linked. Local progress was not changed.",6000)
        def refreshed(entries):
            changed=self.db.merge_anilist_list(entries); self.db.set_setting("anilist_user_list_cache",json.dumps(entries)); self._library_cache_dirty=True
            self.statusBar().showMessage(f"AniList list refreshed for {changed} matched local title(s). Local progress was preserved.",7000)
        link.clicked.connect(lambda:run_account(validate_token,(token.text().strip(),),linked) if token.text().strip() else AniVaultDialog.alert(self,"AniList","Open authorization in your browser, then paste the PIN / code shown by AniList."))
        refresh.clicked.connect(lambda:run_account(fetch_user_list,(self.db.setting("anilist_access_token"),int(self.db.setting("anilist_user_id","0") or 0)),refreshed) if self.db.setting("anilist_access_token") and self.db.setting("anilist_user_id") else AniVaultDialog.alert(self,"AniList","Link the account first."))
        def unlink():
            for key in ("anilist_access_token","anilist_user_id","anilist_user_name"): self.db.set_setting(key,"")
            token.clear(); account.setText("Not linked — AniVault remains fully functional with local state only.")
        disconnect.clicked.connect(unlink)
        cleanup=QPushButton("Move verified retired source cache aside…")
        cleanup.setToolTip("Optional. Verify and move only the old generated index; user records are not deleted.")
        cleanup.clicked.connect(self._cleanup_retired_source_cache);layout.addWidget(cleanup,0,Qt.AlignLeft)
        save=QPushButton("Save Settings"); save.setObjectName("primary")
        def commit():
            self.db.set_setting("show_splash",int(show_splash.isChecked())); self.db.set_setting("splash_duration",splash_duration.currentText()); self.db.set_setting("library_root",root.text()); self.db.set_setting("vlc_path",vlc.text()); self.db.set_setting("default_player",player_choice.currentText())
            self.db.set_setting("autoplay_next",int(autoplay.isChecked())); self.db.set_setting("seek_step",seek_step.currentText().split()[0]); self.db.set_setting("remember_volume",int(remember_volume.isChecked())); self.db.set_setting("hover_previews",int(hover_previews.isChecked()))
            self.db.set_setting("anilist_sync_progress",int(sync_progress.isChecked()));reading_settings.save()
            AniVaultDialog.alert(self,"Settings Saved","Settings saved.")
        save.clicked.connect(commit); layout.addWidget(save,0,Qt.AlignLeft); layout.addStretch(); self.replace(page)

    def _cleanup_retired_source_cache(self):
        if getattr(self,"_retired_cache_busy",False):return
        self._retired_cache_busy=True
        from .retired_cache_cleanup import inspect_retired_cache, quarantine_retired_cache
        self.statusBar().showMessage("Verifying the retired generated cache in the background…")
        def verified(result):
            if not result.get("present"):
                self._retired_cache_busy=False
                AniVaultDialog.alert(self,"Retired Cache","No retired index was found. Nothing was changed.");return
            if not AniVaultDialog.confirm(self,"Retired Cache",f"Verified {result['records']:,} metadata-only cache records ({result['bytes']/1024**2:.1f} MiB).\n\nMove this generated index aside? Saved records, statuses, Collections, history, and media files will remain untouched. Nothing will be deleted.","Move Cache"):
                self._retired_cache_busy=False
                return
            def moved(folder):
                self._retired_cache_busy=False
                _append_playback_log("RetiredCache action=quarantined user_data_deleted=false")
                AniVaultDialog.alert(self,"Retired Cache",f"The verified index was moved to:\n{folder}\n\nIt can be restored. Delete that folder manually if you wish to reclaim disk space. No user-owned data was removed.")
            self._submit_discover_job("retired-cache-move",lambda:quarantine_retired_cache(APP_DIR,result),moved,failed)
        def failed(exc):
            self._retired_cache_busy=False
            _append_crash_log(f"RetiredCache result=REFUSED exception={type(exc).__name__}:{exc}")
            AniVaultDialog.alert(self,"Retired Cache","The cache could not be safely verified or moved. It was left untouched.")
        self._submit_discover_job("retired-cache-inspect",lambda:inspect_retired_cache(APP_DIR),verified,failed)

    def rescan(self):
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.statusBar().showMessage("A library scan is already running.")
            return
        root=self.db.setting("library_root")
        if not root or not Path(root).exists(): AniVaultDialog.alert(self,"Library Unavailable","Choose a valid anime library folder in Settings."); return
        self.statusBar().showMessage("Vee is scanning the vault…"); self.rescan_button.setEnabled(False)
        self.scan_worker=ScanWorker(root,self.db_path)
        self.scan_worker.progress.connect(lambda a,b,c:self.statusBar().showMessage(f"Scanning {a}/{b}: {c}"))
        self.scan_worker.status.connect(self.statusBar().showMessage)
        self.scan_worker.finished_count.connect(self._scan_completed)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self._scan_thread_finished)
        self.scan_worker.start()

    def _scan_completed(self, count):
        if not self._closing and (not self.scan_worker or not self.scan_worker.isInterruptionRequested()):
            self.statusBar().showMessage(f"Scan complete: {count} releases")
            self._library_cache_dirty=True
            self.show_library()

    def _scan_failed(self, details):
        if self._closing:return
        self.statusBar().showMessage("Library scan failed — details saved to crash.log")
        AniVaultDialog.alert(self,"Scan Failed",details[-2000:])

    def _scan_thread_finished(self):
        worker=self.scan_worker
        self.scan_worker=None
        self.rescan_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def closeEvent(self,event):
        if getattr(self,"_update_downloading",False):
            self.statusBar().showMessage("Wait for the update download to finish.",4000);event.ignore();return
        if getattr(self,'_shutdown_complete',False):event.accept();return
        if not self._closing:
            self.lan_server.shutdown()
            self._closing=True;self._shutdown_started=time.perf_counter()
            self._cancel_hub_hover();self._branding_timer.stop();self._unpin_hub_selection()
            self._stop_local_reader();self._stop_integrated_player(save_resume=True,reason='app close');self.downloads.shutdown();self._stop_manga_jobs()
            for timer in [self._discover_cooldown_timer,self._relation_retry_timer,*self._airing_reflow_timers]:timer.stop()
            for reference in self._search_suggestions:
                popup=reference()
                if popup is not None and isValid(popup):popup.dismiss()
            self._discover_queue_worker.stop();self._discover_queue_handlers.clear()
            for reply in self._network.findChildren(QNetworkReply):reply.abort()
            self._shutdown_workers=list({worker for worker in [self.scan_worker,self.anilist_worker,self.airing_page_worker,*self._discover_workers,*self.playback_monitors] if worker is not None and isValid(worker) and worker.isRunning()})
            for worker in self._shutdown_workers:worker.requestInterruption()
            _append_playback_log(f'Shutdown requested qt_workers={len(self._shutdown_workers)}')
        if any(isValid(worker) and worker.isRunning() for worker in self._shutdown_workers):
            event.ignore();self.hide()
            if not hasattr(self,'_shutdown_timer'):
                self._shutdown_timer=QTimer(self);self._shutdown_timer.setInterval(40);self._shutdown_timer.timeout.connect(self._finish_shutdown);self._shutdown_timer.start()
            return
        self._finalize_shutdown();event.accept()

    def _finish_shutdown(self):
        if any(isValid(worker) and worker.isRunning() for worker in self._shutdown_workers):return
        self._shutdown_timer.stop();self._finalize_shutdown();self.close()

    def _finalize_shutdown(self):
        if getattr(self,'_shutdown_complete',False):return
        self._shutdown_complete=True
        if QApplication.instance() is not None:QApplication.instance().removeEventFilter(self)
        self.db.connection.close()
        _append_playback_log(f'Shutdown elapsed_ms={(time.perf_counter()-self._shutdown_started)*1000:.0f} blocking_waits=0')

    def play(self,path,media_id=None,anime_id=None):
        if self.db.setting("default_player","Integrated AniVault Player")=="External VLC": self.play_external(path,media_id,anime_id)
        else: self.play_integrated(path,media_id,anime_id)

    def _local_anime_allowed(self,anime_id=None,media_id=None,path=None):
        row=self.db.media_by_id(media_id) if media_id is not None else self.db.connection.execute('SELECT * FROM media WHERE path=?',(str(path),)).fetchone() if path else None
        if row:
            if anime_id is not None and row['anime_id']!=anime_id:return False
            anime_id=row['anime_id']
        scope=self.db.anime_scope(anime_id) if anime_id is not None else 'normal'
        return scope is not None and self._organization_allowed(scope)

    def play_integrated(self,path,media_id=None,anime_id=None):
        if not self._local_anime_allowed(anime_id,media_id,path):return
        if not Path(path).exists(): AniVaultDialog.alert(self,"Media Unavailable",f"This file no longer exists:\n{path}"); return
        media=self.db.media_by_id(media_id) if media_id is not None else None
        anime=self.db.anime(anime_id) if anime_id is not None else None
        resume_ms=(media["resume_position_ms"] or 0) if media else 0
        if resume_ms>=30000:
            choice=AniVaultDialog.choose(self,"Resume Episode",f"Resume from {format_time(resume_ms)}?",(("Resume","resume"),("Start Over","start")))
            if choice is None:return
            if choice!="resume":resume_ms=0
        title=self._display_title(anime) if anime is not None else "AniVault Player"
        episode_number=media["episode"] if media and media["episode"] is not None else None
        metadata=json.loads(anime["metadata_json"] or "{}") if anime is not None else {}
        episode_titles=metadata.get("episode_titles") or {}
        metadata_title=(episode_titles.get(str(episode_number)) or episode_titles.get(episode_number) or "") if episode_number is not None else ""
        episode_title=clean_episode_label(path,episode_number,metadata_title)
        previous=self.db.adjacent_episode(anime_id,media_id,-1) if media and anime_id is not None else None
        following=self.db.adjacent_episode(anime_id,media_id,1) if media and anime_id is not None else None
        volume=int(self.db.setting("player_volume","80")); muted=self.db.setting("player_muted","0")=="1"
        page=IntegratedPlayer(self.db.setting("vlc_path",""),self.db.setting("seek_step","5"),volume,muted,
                              hover_previews=self.db.setting("hover_previews","1")=="1",parent=self)
        page.back_requested.connect(self._leave_player); page.watched_threshold.connect(self._automatic_watched); page.episode_requested.connect(self._player_adjacent)
        page.fullscreen_requested.connect(self._toggle_player_fullscreen); page.playback_ended.connect(self._integrated_ended); page.playback_error.connect(self._integrated_error)
        page.diagnostic.connect(_append_playback_log); page.external.clicked.connect(self._player_external)
        self.player_page=page; self.current_view="player"; self.current_anime_id=anime_id; self.replace(page)
        page.load(path,media_id,anime_id,title,episode_title,resume_ms,previous is not None,following is not None)

    def play_external(self,path,media_id=None,anime_id=None):
        if not self._local_anime_allowed(anime_id,media_id,path):return
        vlc=self.db.setting("vlc_path","")
        if not vlc:
            from .vlc_runtime import _candidate_directories
            import shutil
            vlc=next((str(directory/'vlc.exe') for directory in _candidate_directories('') if (directory/'vlc.exe').is_file()),shutil.which('vlc') or '')
        if not vlc or not Path(vlc).is_file(): AniVaultDialog.alert(self,"VLC Not Found","Set the VLC executable path in Settings."); return
        if media_id is None or anime_id is None:
            subprocess.Popen([vlc,path]); return
        try: process,port=launch_vlc_session(vlc,path)
        except Exception as exc:
            _append_playback_log(f"Episode launch failed\nMedia path: {path}\n{exc}")
            AniVaultDialog.alert(self,"VLC Launch Failed",str(exc)); return
        monitor=PlaybackMonitor(process,port,path,media_id,anime_id)
        monitor.watched.connect(self._automatic_watched)
        monitor.playback_status.connect(self.statusBar().showMessage)
        monitor.diagnostic.connect(_append_playback_log)
        monitor.finished.connect(lambda m=monitor:self._playback_finished(m))
        self.playback_monitors.append(monitor); monitor.start()

    def _save_player_preferences(self):
        if not self.player_page: return
        if self.db.setting("remember_volume","1")=="1": self.db.set_setting("player_volume",self.player_page.volume.value())
        self.db.set_setting("player_muted",int(self.player_page._desired_muted))

    def _stop_integrated_player(self,save_resume=True,reason="navigation"):
        page=self.player_page
        if not page: return
        if page._teardown_started:
            _append_playback_log(f"Player teardown requested\nreason: {reason}\ncleanup already active: yes")
            return
        if save_resume and page.media_id is not None:
            position=page.position_ms; duration=page.duration_ms
            meaningful=position>=30000 and not (duration>0 and position/duration>=.90)
            self.db.set_resume_position(page.media_id,position if meaningful else 0)
            _append_playback_log(f"resume position saved: {position if meaningful else 0}ms for media {page.media_id}")
        self._save_player_preferences()
        if self.player_fullscreen: self._toggle_player_fullscreen()
        self.player_page=None; page.hide(); page.begin_teardown(reason,_append_playback_log); page.deleteLater()

    def _leave_player(self):
        anime_id=self.current_anime_id; self._stop_integrated_player(save_resume=True,reason="navigation")
        if anime_id is not None: self.show_detail(anime_id)
        else: self.show_home()

    def _player_adjacent(self,offset):
        page=self.player_page
        if not page or page.anime_id is None or page.media_id is None: return
        target=self.db.adjacent_episode(page.anime_id,page.media_id,offset)
        _append_playback_log(f"Next/previous episode resolution: media {page.media_id}, offset {offset}, result {target['id'] if target else 'none'}")
        if target:
            anime_id=page.anime_id; self._stop_integrated_player(save_resume=True,reason="episode change"); self.play_integrated(target["path"],target["id"],anime_id)

    def _player_external(self):
        page=self.player_page
        if not page: return
        path,media_id,anime_id=page.path,page.media_id,page.anime_id
        self._stop_integrated_player(save_resume=True,reason="external VLC fallback"); self.play_external(path,media_id,anime_id)
        if anime_id is not None: self.show_detail(anime_id)

    def _toggle_player_fullscreen(self):
        if not self.player_page: return
        self.player_fullscreen=not self.player_fullscreen
        if self.player_fullscreen:
            self._player_was_maximized=self.isMaximized();self._player_restore_geometry=self.saveGeometry()
            self._player_chrome_visibility=[(widget,widget.isVisible()) for widget in (self.sidebar,self.title_bar,self.statusBar(),*self.resize_handles)]
        for widget,visible in self._player_chrome_visibility:widget.setVisible(False if self.player_fullscreen else visible)
        edge=0 if self.player_fullscreen else 5
        self.chrome_grid.setColumnMinimumWidth(0,edge); self.chrome_grid.setColumnMinimumWidth(2,edge); self.chrome_grid.setRowMinimumHeight(0,edge); self.chrome_grid.setRowMinimumHeight(3,edge)
        if self.player_fullscreen:
            self.showFullScreen(); self.player_page.set_fullscreen_mode(True)
        else:
            self.player_page.set_fullscreen_mode(False);self.showNormal();self.restoreGeometry(self._player_restore_geometry)
            if self._player_was_maximized:self.showMaximized()
        self.player_page.setFocus()

    def _integrated_ended(self,anime_id,media_id):
        page=self.player_page
        if page and not page._threshold_sent: self._automatic_watched(anime_id,media_id)
        if self.db.setting("autoplay_next","0")=="1":
            target=self.db.adjacent_episode(anime_id,media_id,1)
            if target:
                self.statusBar().showMessage(f"Loading Episode {target['episode']}…",3000); self._stop_integrated_player(save_resume=False,reason="episode change"); QTimer.singleShot(500,lambda:self.play_integrated(target["path"],target["id"],anime_id)); return
        self.db.set_resume_position(media_id,0)

    def _integrated_error(self,path,details):
        _append_playback_log(f"Playback error\nMedia path: {path}\n{details}")
        message=details if "architecture is incompatible" in details else f"AniVault couldn't play this file internally.\n\n{details}"
        choice=AniVaultDialog.choose(self,"Playback Error",message,(("Open in VLC","external"),("Close","close")))
        if choice=="external": self._player_external()
        else:
            anime_id=self.current_anime_id; self._stop_integrated_player(save_resume=True,reason="error")
            self.show_detail(anime_id) if anime_id is not None else self.show_home()

    def _automatic_watched(self,anime_id,media_id):
        filled=self.db.set_watched_through(media_id)
        self._library_cache_dirty=True; self._maybe_sync_anilist_progress(anime_id,"playback",allow_decrease=False)
        _append_playback_log(f"Sequential watch-state update: media {media_id} reached threshold; {filled} normal episode row(s) marked watched through this episode")
        self.statusBar().showMessage("Episode marked watched at 90%; earlier normal episodes filled automatically.",8000)
        if self.current_view=="detail" and self.current_anime_id==anime_id: self.show_detail(anime_id)
        elif self.current_view=="library": self.show_library(**self.library_context)
        elif self.current_view=="home": self.show_home()

    def _apply_anilist_progress_update(self,anime_id,progress,status):
        if not self._closing:self.db.set_anilist_user_progress(anime_id,progress,status)

    def _maybe_sync_anilist_progress(self,anime_id,trigger="playback",allow_decrease=False):
        if self.db.setting("anilist_sync_progress","0")!="1": return
        token=self.db.setting("anilist_access_token"); anime=self.db.anime(anime_id)
        if not token or not anime or anime["anilist_id"] is None: return
        watched,total=self.db.anime_progress(anime_id); metadata=json.loads(anime["metadata_json"] or "{}"); previous=int(metadata.get("anilist_user_progress") or 0)
        if watched<previous and not allow_decrease:
            _append_playback_log(f"AniList mutation\nTitle: {self._display_title(anime)}\nAniList ID: {anime['anilist_id']}\nPrevious progress: {previous}\nNew progress: {watched}\nTrigger: {trigger}\nResult: skipped — automatic actions may not lower AniList progress")
            return
        def sync():
            try:
                result=update_progress(token,anime["anilist_id"],watched,total>0 and watched>=total)
                remote=int(result.get("progress",watched) or 0)
                if not self._closing:self.anilist_progress_updated.emit(anime_id,remote,result.get("status") or "")
                _append_playback_log(f"AniList mutation\nTitle: {self._display_title(anime)}\nAniList ID: {anime['anilist_id']}\nPrevious progress: {previous}\nNew progress: {watched}\nTrigger: {trigger}\nResult: succeeded (remote progress {remote})")
            except Exception as exc: _append_playback_log(f"AniList mutation\nTitle: {self._display_title(anime)}\nAniList ID: {anime['anilist_id']}\nPrevious progress: {previous}\nNew progress: {watched}\nTrigger: {trigger}\nResult: failed — local state preserved\n{exc}")
        threading.Thread(target=sync,name="AniVaultAniListProgress",daemon=True).start()

    def _playback_finished(self,monitor):
        if monitor in self.playback_monitors: self.playback_monitors.remove(monitor)
        monitor.deleteLater()


def _append_crash_log(message):
    APP_DIR.mkdir(parents=True,exist_ok=True)
    with CRASH_LOG.open("a",encoding="utf-8") as output:
        output.write(f"\n[{datetime.now(timezone.utc).isoformat()}]\n{message.rstrip()}\n")


def _append_playback_log(message):
    APP_DIR.mkdir(parents=True,exist_ok=True)
    with (APP_DIR/"playback_diagnostics.log").open("a",encoding="utf-8") as output:
        output.write(f"\n[{datetime.now(timezone.utc).isoformat()}]\n{message.rstrip()}\n")




def _install_crash_logging():
    global _FAULT_LOG_HANDLE
    APP_DIR.mkdir(parents=True,exist_ok=True)
    _FAULT_LOG_HANDLE=CRASH_LOG.open("a",encoding="utf-8")
    faulthandler.enable(_FAULT_LOG_HANDLE,all_threads=True)
    def exception_hook(exc_type,exc_value,exc_traceback):
        _append_crash_log("Uncaught exception\n"+"".join(traceback.format_exception(exc_type,exc_value,exc_traceback)))
        sys.__excepthook__(exc_type,exc_value,exc_traceback)
    sys.excepthook=exception_hook
    def thread_hook(args):
        _append_crash_log("Uncaught thread exception\n"+"".join(traceback.format_exception(args.exc_type,args.exc_value,args.exc_traceback)))
    threading.excepthook=thread_hook
    def qt_message(_mode,context,message):
        location=f"{context.file}:{context.line}" if context and context.file else "Qt"
        _append_crash_log(f"Qt message ({location})\n{message}")
    qInstallMessageHandler(qt_message)


def run():
    if sys.platform=="win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
    app=QApplication(sys.argv); app.setApplicationName("AniVault"); app.setApplicationDisplayName("AniVault")
    if ICON_PATH.exists(): app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(STYLE)
    try:_install_crash_logging()
    except OSError:
        AniVaultDialog.alert(None,"User data unavailable",f"AniVault cannot write to its user-data folder:\n{APP_DIR}\n\nCheck access permissions and retry. Existing data was not removed.")
        return 1
    from .branding import StartupTransition
    app.setApplicationVersion(APP_VERSION);app.setStyleSheet(STYLE)
    enabled,duration=splash_preferences(APP_DIR/'anime_hub.db')
    transition=StartupTransition(app,enabled,duration)
    try:
        window=Window();transition.ready(window)
    except Exception as exc:
        transition.abort()
        _append_playback_log(f"StartupFailure exception={type(exc).__name__} message={exc} data_preserved=true")
        AniVaultDialog.alert(None,"AniVault could not start",f"Your existing data has been retained.\n\n{exc}\n\nDiagnostics: {APP_DIR}\nRestore a verified backup or contact support; no database was recreated.")
        return 1
    return app.exec()
