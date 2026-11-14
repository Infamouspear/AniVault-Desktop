"""Supplied art placement, separate from source media and metadata."""
from pathlib import Path
import time
from PySide6.QtCore import Qt,QTimer,QSize,QObject,Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame,QLabel,QVBoxLayout,QSplashScreen

ASSET_DIR=Path(__file__).resolve().parent.parent/'assets'
ASSETS={'empty':'empty_vee.png','results':'no_results_vee.png','caught_up':'caught_up_vee.png'}
_PIXMAPS={}

def artwork(name):
    if name not in _PIXMAPS:_PIXMAPS[name]=QPixmap(str(ASSET_DIR/name))
    return _PIXMAPS[name]

class EmptyState(QFrame):
    def __init__(self,kind,message,scope='normal',copy=''):
        super().__init__();self.setObjectName('panel');self.setProperty('brandEmptyState',True);self.kind=kind;self.scope=scope;self.setMinimumWidth(200);self.setMaximumWidth(420)
        self.setStyleSheet('QLabel{background:transparent}');layout=QVBoxLayout(self);layout.setContentsMargins(14,12,14,12);layout.setSpacing(8)
        self.art=QLabel();self.art.setObjectName('emptyStateArt');self.art.setAttribute(Qt.WA_TransparentForMouseEvents);self.art.setAlignment(Qt.AlignCenter);layout.addWidget(self.art,0,Qt.AlignHCenter)
        title=QLabel(message);title.setWordWrap(True);title.setAlignment(Qt.AlignCenter);layout.addWidget(title)
        if copy:description=QLabel(copy);description.setWordWrap(True);description.setObjectName('muted');description.setAlignment(Qt.AlignCenter);layout.addWidget(description)
        self._art_allowed=True;self.resize_art()
    def resize_art(self):
        host=self.window();small=host.height()<680;very_small=host.width()<650
        size=QSize(64,80) if very_small else QSize(96,112) if small else QSize(150,170)
        self.art.setFixedSize(size);pix=artwork(ASSETS.get(self.kind,'empty_vee.png'))
        if not pix.isNull():self.art.setPixmap(pix.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.art.setVisible(self._art_allowed and not pix.isNull())
    def allow_art(self,value):
        if self._art_allowed!=value:self._art_allowed=value;self.resize_art()
    def schedule(self):
        host=self.window()
        if hasattr(host,'_schedule_branding_ownership'):host._schedule_branding_ownership()
    def showEvent(self,event):super().showEvent(event);self.schedule()
    def hideEvent(self,event):super().hideEvent(event);self.schedule()

def startup_splash(application):
    """Show supplied branding immediately, without a progress indicator."""
    pix=artwork('splash.png')
    if pix.isNull():return None
    screen=application.primaryScreen();available=screen.availableGeometry().size() if screen else QSize(900,600)
    size=QSize(min(640,int(available.width()*.7)),min(360,int(available.height()*.7)))
    splash=QSplashScreen(pix.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation));splash.setObjectName('startupSplash');splash.show();application.processEvents();return splash


SPLASH_DURATIONS = {'Brief': 1000, 'Standard': 2750, 'Extended': 5000}

class StartupTransition(QObject):
    finished = Signal()
    def __init__(self, application, enabled=True, duration='Standard', parent=None):
        super().__init__(parent or application)
        self.started = time.monotonic()
        self.minimum_ms = SPLASH_DURATIONS.get(duration, 2750)
        self.splash = startup_splash(application) if enabled else None
        self.window = None
        self.timer = QTimer(self); self.timer.setTimerType(Qt.PreciseTimer); self.timer.setSingleShot(True); self.timer.timeout.connect(self._finish)
    def ready(self, window):
        self.window = window
        remaining = max(0, self.minimum_ms - int((time.monotonic()-self.started)*1000)) if self.splash else 0
        self.timer.start(remaining)
    def _finish(self):
        if self.window is None: return
        self.window.show()
        if self.splash: self.splash.finish(self.window); self.splash = None
        self.finished.emit()
    def abort(self):
        self.timer.stop()
        if self.splash: self.splash.close(); self.splash = None
