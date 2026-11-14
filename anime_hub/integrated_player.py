from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QKeyEvent, QKeySequence, QLinearGradient, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QApplication, QPushButton, QSlider, QStyle, QToolButton, QVBoxLayout, QWidget)

from .playback import watched_threshold_reached
from .vlc_runtime import initialize_libvlc

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg=None


def format_time(milliseconds: int) -> str:
    seconds=max(0,int(milliseconds or 0)//1000)
    hours,seconds=divmod(seconds,3600); minutes,seconds=divmod(seconds,60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def track_label(description, kind: str, ordinal: int) -> str:
    if isinstance(description,bytes): description=description.decode("utf-8","replace")
    value=(description or "").strip()
    if not value or value.casefold() in {"track","unknown","undetermined"}:
        return f"{kind} Track {ordinal}"
    return value


TECHNICAL_SUFFIX=re.compile(r"\b(?:2160p|1080p|720p|480p|blu[- .]?ray|b[dr]rip|remux|web[- .]?(?:dl|rip)|hevc|avc|x26[45]|h\.?26[45]|10[- ]?bit|8[- ]?bit|flac|aac|opus|dual[- ]?audio|multi[- ]?subs?)\b",re.I)


def clean_episode_label(path: str, episode: int | None = None, metadata_title: str = "") -> str:
    """Create a viewer-facing title without exposing a release filename."""
    candidate=(metadata_title or "").strip()
    if not candidate:
        stem=Path(path).stem
        marker=re.search(r"\bS\d{1,2}E\d{1,4}(?:v\d+)?\b",stem,re.I)
        if not marker and episode is not None:
            marker=re.search(rf"(?:^|[ ._-])(?:Episode|Ep|E)?\s*0*{episode}(?=[ ._-]|$)",stem,re.I)
        candidate=stem[marker.end():] if marker else ""
    candidate=re.split(r"\[[^\]]*\]|\([0-9a-f]{8}\)",candidate,1,flags=re.I)[0]
    technical=TECHNICAL_SUFFIX.search(candidate)
    if technical: candidate=candidate[:technical.start()]
    candidate=re.sub(r"[._]+"," ",candidate); candidate=re.sub(r"\s+"," ",candidate).strip(" -–—[]()")
    prefix=f"Episode {episode}" if episode is not None else "Now Playing"
    return f"{prefix} — {candidate}" if len(candidate)>2 and not candidate.isdigit() else prefix


class SeekSlider(QSlider):
    seek_requested=Signal(int)
    hover_requested=Signal(int,int)
    hover_left=Signal()
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.setMouseTracking(True)
    def mouseMoveEvent(self,event):
        value=round(self.minimum()+(self.maximum()-self.minimum())*event.position().x()/max(1,self.width()))
        self.hover_requested.emit(value,round(event.position().x())); super().mouseMoveEvent(event)
    def leaveEvent(self,event):
        self.hover_left.emit(); super().leaveEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            value=round(self.minimum()+(self.maximum()-self.minimum())*event.position().x()/max(1,self.width()))
            self.setValue(value); self.seek_requested.emit(value)
        super().mousePressEvent(event)


class ThumbnailWorker(QThread):
    ready=Signal(str,int,bytes)
    def __init__(self,ffmpeg,path,timestamp_ms):
        super().__init__(); self.ffmpeg=ffmpeg; self.path=path; self.timestamp_ms=timestamp_ms
    def run(self):
        try:
            result=subprocess.run([self.ffmpeg,"-loglevel","error","-ss",f"{self.timestamp_ms/1000:.3f}","-i",self.path,
                "-frames:v","1","-vf","scale=240:-2","-f","image2pipe","-vcodec","png","pipe:1"],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=False,
                **({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}))
            if result.returncode==0 and result.stdout: self.ready.emit(self.path,self.timestamp_ms,result.stdout)
        except Exception: pass


class VideoSurface(QFrame):
    toggle_fullscreen=Signal()
    toggle_playback=Signal()
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self._consume_release=False; self._single_click=QTimer(self); self._single_click.setSingleShot(True); self._single_click.timeout.connect(self.toggle_playback)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            if self._consume_release:self._consume_release=False
            else:self._single_click.start(QApplication.doubleClickInterval())
        super().mouseReleaseEvent(event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton: self._single_click.stop(); self._consume_release=True; self.toggle_fullscreen.emit()
        super().mouseDoubleClickEvent(event)


class PlayerInputOverlay(QWidget):
    """Mouse-capture sibling for the native libVLC video HWND."""
    activity=Signal()
    toggle_playback=Signal()
    toggle_fullscreen=Signal()
    def __init__(self,parent=None):
        super().__init__(parent); self.setMouseTracking(True)
        self._consume_release=False
        self._single_click=QTimer(self); self._single_click.setSingleShot(True)
        self._single_click.timeout.connect(self.toggle_playback)
        self.setAttribute(Qt.WA_TranslucentBackground,True); self.setAttribute(Qt.WA_NoSystemBackground,True)
        self.setAttribute(Qt.WA_ShowWithoutActivating,True); self.setAutoFillBackground(False)
    def paintEvent(self,event):
        # Alpha 1 remains visually transparent while keeping a layered Win32
        # tool window hit-testable above libVLC's native child window.
        painter=QPainter(self); painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(),QColor(0,0,0,1)); painter.end()
    def mouseMoveEvent(self,event):
        self.activity.emit(); super().mouseMoveEvent(event)
    def mousePressEvent(self,event):
        self.activity.emit(); super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.activity.emit()
            if self._consume_release:
                self._consume_release=False
            else:
                self._single_click.start(QApplication.doubleClickInterval())
        super().mouseReleaseEvent(event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            # Qt sends a release after MouseButtonDblClick. Consume it so that
            # release cannot re-arm the deferred single-click action.
            self._single_click.stop(); self._consume_release=True
            self.activity.emit(); self.toggle_fullscreen.emit(); event.accept(); return
        super().mouseDoubleClickEvent(event)


class ElidedCenterLabel(QLabel):
    def paintEvent(self,event):
        painter=QPainter(self); painter.setPen(self.palette().windowText().color()); painter.setFont(self.font())
        text=painter.fontMetrics().elidedText(self.text(),Qt.ElideRight,max(1,self.width()-12))
        painter.drawText(self.rect(),Qt.AlignCenter|Qt.AlignVCenter,text); painter.end()


class PlayerControlOverlay(QFrame):
    def __init__(self,parent=None):
        super().__init__(parent); self.fullscreen_overlay=False
    def set_fullscreen_overlay(self,enabled):
        self.fullscreen_overlay=bool(enabled); self.update()
    def paintEvent(self,event):
        super().paintEvent(event)
        if not self.fullscreen_overlay: return
        # Explicitly erase any inherited application/palette backing. Source composition
        # writes zero-alpha pixels instead of blending over a QWidget background.
        painter=QPainter(self); painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(),Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        gradient=QLinearGradient(0,0,0,self.height())
        gradient.setColorAt(0,QColor(3,5,8,0)); gradient.setColorAt(.35,QColor(3,5,8,30)); gradient.setColorAt(.72,QColor(3,5,8,105)); gradient.setColorAt(1,QColor(3,5,8,190))
        painter.fillRect(self.rect(),gradient); painter.end()


class IntegratedPlayer(QWidget):
    back_requested=Signal()
    watched_threshold=Signal(int,int)
    episode_requested=Signal(int)
    fullscreen_requested=Signal()
    playback_ended=Signal(int,int)
    playback_error=Signal(str,str)
    diagnostic=Signal(str)

    def __init__(self, vlc_executable="", seek_step=5, volume=80, muted=False, hover_previews=True, parent=None):
        super().__init__(parent); self.vlc_executable=vlc_executable; self.seek_step=max(1,int(seek_step))
        self._vlc=None; self._instance=None; self._player=None; self._media=None; self._dll_handle=None; self._dll_directory=None; self._vlc_installation=None
        self.anime_id=None; self.media_id=None; self.path=""; self._threshold_sent=False; self._ended_sent=False; self._duration_logged=False
        self._last_position=0; self._last_duration=0; self._desired_volume=max(0,min(100,int(volume))); self._desired_muted=bool(muted); self._fullscreen_mode=False
        self._teardown_started=False
        self._expected_playing=None; self._transition_serial=0
        self._windowed_overlay=False
        self._hover_previews=bool(hover_previews); self._ffmpeg=shutil.which("ffmpeg") if self._hover_previews else None
        if self._hover_previews and not self._ffmpeg and imageio_ffmpeg is not None:
            try: self._ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            except Exception: self._ffmpeg=None
        self._thumbnail_cache={}; self._thumbnail_failures={}; self._thumbnail_worker=None; self._hover_value=0; self._hover_x=0
        self._chapters=[]; self._opening_chapter=None; self._ending_chapters=[]; self._active_ending_chapter=None; self._chapters_loaded=False
        self.setFocusPolicy(Qt.StrongFocus)
        self.outer=QVBoxLayout(self); self.outer.setContentsMargins(22,16,22,18); self.outer.setSpacing(0)
        self.header_widget=QWidget(); header=QHBoxLayout(self.header_widget); header.setContentsMargins(0,0,0,0)
        self.back=QPushButton(); self._icon_button(self.back,"SP_ArrowBack","Back to series"); self.back.clicked.connect(self.back_requested); header.addWidget(self.back)
        self.series_label=QLabel(); self.series_label.setObjectName("section"); header.addWidget(self.series_label); header.addStretch()
        self.external=QPushButton("Open in External VLC"); header.addWidget(self.external); self.outer.addWidget(self.header_widget)
        self.video_container=QFrame(); self.video_container.setObjectName("videoContainer"); stage=QVBoxLayout(self.video_container); stage.setContentsMargins(0,0,0,0)
        self.video=VideoSurface(); self.video.setObjectName("videoSurface"); self.video.setMinimumHeight(440); self.video.setStyleSheet("background:#000;border:1px solid #253047;border-radius:10px")
        self.video.toggle_fullscreen.connect(self.fullscreen_requested); self.video.toggle_playback.connect(self.toggle_play); stage.addWidget(self.video); self.outer.addWidget(self.video_container,1)
        self.input_overlay=PlayerInputOverlay(); self.input_overlay.hide()
        self.input_overlay.activity.connect(self._show_overlay); self.input_overlay.toggle_playback.connect(self.toggle_play); self.input_overlay.toggle_fullscreen.connect(self.fullscreen_requested)
        self.skip_opening=QPushButton("Skip Opening",self); self.skip_opening.setObjectName("skipOpening"); self.skip_opening.hide(); self.skip_opening.clicked.connect(self._skip_opening)
        self.skip_opening.setStyleSheet("QPushButton#skipOpening{background:#d92f68;color:white;border:1px solid #ff7ba5;border-radius:9px;padding:9px 15px;font-weight:700} QPushButton#skipOpening:hover{background:#ff4f84}")
        self.skip_ending=QPushButton("Skip Ending",self); self.skip_ending.setObjectName("skipEnding"); self.skip_ending.hide(); self.skip_ending.clicked.connect(self._skip_ending)
        self.skip_ending.setStyleSheet("QPushButton#skipEnding{background:#d92f68;color:white;border:1px solid #ff7ba5;border-radius:9px;padding:9px 15px;font-weight:700} QPushButton#skipEnding:hover{background:#ff4f84}")
        self.control_panel=PlayerControlOverlay(); self.control_panel.setObjectName("playerControls"); panel=QVBoxLayout(self.control_panel); panel.setContentsMargins(0,0,0,2); panel.setSpacing(0)
        self.timeline=SeekSlider(Qt.Horizontal); self.timeline.setObjectName("playerTimeline"); self.timeline.setRange(0,0); self.timeline.seek_requested.connect(self.seek_to); self.timeline.sliderReleased.connect(lambda:self.seek_to(self.timeline.value())); panel.addWidget(self.timeline)
        self.timeline.hover_requested.connect(self._preview_hover); self.timeline.hover_left.connect(self._hide_preview)
        controls=QGridLayout(); controls.setContentsMargins(8,0,8,0); controls.setHorizontalSpacing(8); self.previous=QPushButton(); self.play_pause=QPushButton(); self.next=QPushButton()
        left=QHBoxLayout(); left.setContentsMargins(0,0,0,0); left.setSpacing(4); right=QHBoxLayout(); right.setContentsMargins(0,0,0,0); right.setSpacing(4)
        self._icon_button(self.previous,"SP_MediaSkipBackward","Previous episode"); self._icon_button(self.play_pause,"SP_MediaPlay","Play / pause"); self._icon_button(self.next,"SP_MediaSkipForward","Next episode")
        self.previous.clicked.connect(lambda:self.episode_requested.emit(-1)); self.next.clicked.connect(lambda:self.episode_requested.emit(1)); self.play_pause.clicked.connect(self.toggle_play)
        left.addWidget(self.previous); left.addWidget(self.play_pause); left.addWidget(self.next)
        self.volume=QSlider(Qt.Horizontal); self.volume.setObjectName("playerVolume"); self.volume.setRange(0,100); self.volume.setValue(self._desired_volume); self.volume.setFixedWidth(88); self.volume.valueChanged.connect(self.set_volume)
        self.mute=QPushButton(); self._icon_button(self.mute,"SP_MediaVolumeMuted" if self._desired_muted else "SP_MediaVolume","Mute"); self.mute.clicked.connect(self.toggle_mute); left.addWidget(self.mute); left.addWidget(self.volume)
        self.clock=QLabel("0:00 / 0:00"); self.clock.setObjectName("playerClock"); self.clock.setMinimumWidth(94); left.addWidget(self.clock)
        self.subtitle=QToolButton(); self.subtitle.setText("CC"); self.subtitle.setToolTip("Subtitles"); self.subtitle.setAccessibleName("Subtitles"); self.subtitle.setPopupMode(QToolButton.InstantPopup); self.subtitle.setMenu(QMenu(self)); right.addWidget(self.subtitle)
        self.audio=QToolButton(); self.audio.setText("Audio"); self.audio.setPopupMode(QToolButton.InstantPopup); self.audio.setMenu(QMenu(self)); right.addWidget(self.audio)
        self.speed=QComboBox(); self.speed.addItems(["0.5x","0.75x","1.0x","1.25x","1.5x","2.0x"]); self.speed.setCurrentText("1.0x"); self.speed.currentTextChanged.connect(self.set_speed); right.addWidget(self.speed)
        self.fullscreen=QPushButton(); self._icon_button(self.fullscreen,"SP_TitleBarMaxButton","Fullscreen"); self.fullscreen.clicked.connect(self.fullscreen_requested); right.addWidget(self.fullscreen)
        self.episode_label=ElidedCenterLabel(); self.episode_label.setObjectName("playerEpisodeTitle"); self.episode_label.setMinimumWidth(120)
        controls.addLayout(left,0,0); controls.addWidget(self.episode_label,0,1); controls.addLayout(right,0,2); controls.setColumnStretch(1,1); panel.addLayout(controls)
        self.control_panel.setFixedHeight(82); self.control_panel.hide()
        self.preview=QLabel(None,Qt.ToolTip|Qt.FramelessWindowHint); self.preview.setAlignment(Qt.AlignCenter); self.preview.setFixedSize(244,164); self.preview.hide()
        self.preview.setStyleSheet("background:#0b1019;border:2px solid #374156;border-radius:8px;color:white;font-size:12px;padding:2px")
        self.preview_delay=QTimer(self); self.preview_delay.setSingleShot(True); self.preview_delay.setInterval(180); self.preview_delay.timeout.connect(self._request_preview)
        self.timer=QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.poll)
        self.overlay_timer=QTimer(self); self.overlay_timer.setSingleShot(True); self.overlay_timer.setInterval(2600); self.overlay_timer.timeout.connect(self._hide_overlay)
        self.pointer_timer=QTimer(self); self.pointer_timer.setInterval(80); self.pointer_timer.timeout.connect(self._poll_pointer_activity)
        self._last_pointer_pos=QCursor.pos(); self._last_mouse_buttons=Qt.NoButton; self._menu_open=False
        for widget in (self,self.video_container,self.video,self.control_panel,self.previous,self.play_pause,self.next,self.timeline,self.volume,self.mute,self.subtitle,self.audio,self.speed,self.fullscreen,self.episode_label):
            widget.setMouseTracking(True)
        for menu in (self.subtitle.menu(),self.audio.menu()):
            menu.aboutToShow.connect(self._menu_opened); menu.aboutToHide.connect(self._menu_closed)
        self._apply_control_style(False)
        self._shortcuts=[]
        for key,slot in ((Qt.Key_Space,self.toggle_play),(Qt.Key_Left,lambda:self.seek_relative(-self.seek_step)),
                         (Qt.Key_Right,lambda:self.seek_relative(self.seek_step)),(Qt.Key_Up,lambda:self.volume.setValue(min(100,self.volume.value()+5))),
                         (Qt.Key_Down,lambda:self.volume.setValue(max(0,self.volume.value()-5))),(Qt.Key_M,self.toggle_mute),
                         (Qt.Key_F,self.fullscreen_requested.emit),(Qt.Key_Escape,self._escape_fullscreen)):
            shortcut=QShortcut(QKeySequence(key),self); shortcut.setContext(Qt.ApplicationShortcut); shortcut.activated.connect(lambda action=slot,name=QKeySequence(key).toString():self._run_shortcut(name,action)); self._shortcuts.append(shortcut)
        if self._hover_previews and not self._ffmpeg: self.diagnostic.emit("Timeline hover previews unavailable: ffmpeg was not found; playback is unaffected")

    def _escape_fullscreen(self):
        if self.window().isFullScreen(): self.fullscreen_requested.emit()

    def _run_shortcut(self,name,action):
        if self._teardown_started or not self.isVisible(): return
        focused=QApplication.focusWidget(); owner=type(focused).__name__ if focused is not None else "none"
        self.diagnostic.emit(f"Player input: shortcut={name or 'unknown'} focus_owner={owner} fullscreen={self._fullscreen_mode}")
        if self._fullscreen_mode: self._show_overlay()
        action()

    def _preview_hover(self,value,x):
        if not self._ffmpeg or not self.path or self.timeline.maximum()<=0: return
        self._hover_value=max(0,int(value)); self._hover_x=int(x); self.preview_delay.start()

    def _hide_preview(self):
        self.preview_delay.stop(); self.preview.hide()

    def _position_preview(self):
        point=self.timeline.mapToGlobal(QPoint(self._hover_x,0)); screen=self.timeline.screen().availableGeometry()
        x=max(screen.left()+4,min(point.x()-self.preview.width()//2,screen.right()-self.preview.width()-4))
        y=max(screen.top()+4,point.y()-self.preview.height()-5); self.preview.move(x,y); self.preview.raise_()

    def _request_preview(self):
        bucket=(self._hover_value//10000)*10000; key=(self.path,bucket)
        self.preview.setText(format_time(self._hover_value)); self._position_preview(); self.preview.show()
        cached=self._thumbnail_cache.get(key)
        if cached:
            self._render_preview(cached); return
        if time.monotonic()<self._thumbnail_failures.get(key,0):return
        if self._thumbnail_worker and self._thumbnail_worker.isRunning(): return
        worker=ThumbnailWorker(self._ffmpeg,self.path,bucket); self._thumbnail_worker=worker
        def ready(path,timestamp,data):
            pixmap=QPixmap(); pixmap.loadFromData(data)
            if pixmap.isNull(): return
            image=pixmap.scaled(240,135,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            self._thumbnail_cache[(path,timestamp)]=image
            while len(self._thumbnail_cache)>96:self._thumbnail_cache.pop(next(iter(self._thumbnail_cache)))
            if path==self.path and self.preview.isVisible(): self._render_preview(image)
        def finished():
            self._thumbnail_worker=None
            if key not in self._thumbnail_cache:
                self._thumbnail_failures[key]=time.monotonic()+30
                while len(self._thumbnail_failures)>96:self._thumbnail_failures.pop(next(iter(self._thumbnail_failures)))
            current=(self.path,(self._hover_value//10000)*10000)
            if self.preview.isVisible() and current!=key and current not in self._thumbnail_cache:self.preview_delay.start(180)
        worker.ready.connect(ready); worker.finished.connect(finished); worker.finished.connect(worker.deleteLater); worker.start()

    def _render_preview(self,image):
        canvas=QPixmap(240,160); canvas.fill(QColor("#0b1019")); painter=QPainter(canvas)
        painter.drawPixmap((240-image.width())//2,0,image); painter.setPen(Qt.white); painter.drawText(0,137,240,21,Qt.AlignCenter,format_time(self._hover_value)); painter.end()
        self.preview.setPixmap(canvas); self.preview.setToolTip(format_time(self._hover_value)); self._position_preview()

    def _standard_icon(self,name,fallback="SP_MediaPlay"):
        standard=getattr(QStyle.StandardPixmap,name,getattr(QStyle.StandardPixmap,fallback))
        source=self.style().standardIcon(standard).pixmap(22,22)
        tinted=QPixmap(source.size()); tinted.fill(Qt.transparent)
        mask=QPixmap(source.size()); mask.fill(Qt.transparent); painter=QPainter(mask); painter.drawPixmap(0,0,source); painter.setCompositionMode(QPainter.CompositionMode_SourceIn); painter.fillRect(mask.rect(),QColor("#f4eef3")); painter.end()
        painter=QPainter(tinted); painter.setOpacity(.85); painter.drawPixmap(1,1,mask); painter.setCompositionMode(QPainter.CompositionMode_SourceIn); painter.fillRect(tinted.rect(),QColor("#05070a")); painter.setCompositionMode(QPainter.CompositionMode_SourceOver); painter.setOpacity(1); painter.drawPixmap(0,0,mask); painter.end()
        return QIcon(tinted)

    def _icon_button(self,button,name,tooltip):
        button.setIcon(self._standard_icon(name)); button.setToolTip(tooltip); button.setAccessibleName(tooltip); button.setFixedSize(40,36); button.setText("")

    def _set_play_icon(self,playing):
        name="SP_MediaPause" if playing else "SP_MediaPlay"; self.play_pause.setIcon(self._standard_icon(name))

    def _apply_control_style(self,fullscreen):
        background="transparent" if fullscreen else "#0d141e"
        self.control_panel.setStyleSheet(f"""
            QFrame#playerControls {{ background:{background}; border:0; }}
            QLabel#playerEpisodeTitle {{ color:#f2f3f6; background:rgba(5,7,10,72); border-radius:4px; font-size:12px; padding:2px 8px; }}
            QLabel#playerClock {{ color:#ffffff; background:rgba(5,7,10,115); border-radius:4px; padding:2px 5px; font-size:12px; }}
            QPushButton {{ background:rgba(5,7,10,90); border:0; border-radius:18px; padding:4px; }}
            QPushButton:hover {{ background:rgba(25,29,38,180); }}
            QToolButton {{ background:rgba(5,7,10,90); color:#f4eef3; border:0; border-radius:6px; padding:6px 8px; font-size:12px; font-weight:600; }}
            QToolButton:hover {{ background:rgba(25,29,38,180); }}
            QComboBox {{ background:rgba(5,7,10,90); color:#f4eef3; border:0; border-radius:6px; padding:5px 22px 5px 7px; font-size:12px; }}
            QComboBox:hover {{ background:rgba(25,29,38,180); }}
            QSlider#playerTimeline {{ background:transparent; min-height:28px; max-height:28px; margin:0 8px; }}
            QSlider#playerTimeline::groove:horizontal {{ height:3px; background:#363c47; border:1px solid rgba(0,0,0,170); border-radius:2px; }}
            QSlider#playerTimeline::sub-page:horizontal {{ background:#ff3f78; border-radius:1px; }}
            QSlider#playerTimeline::handle:horizontal {{ background:#ff5a8b; width:10px; height:10px; margin:-4px 0; border-radius:5px; }}
            QSlider#playerTimeline:hover::groove:horizontal {{ height:5px; }}
            QSlider#playerVolume {{ background:transparent; }}
            QSlider#playerVolume::groove:horizontal {{ height:3px; background:#56606d; border-radius:1px; }}
            QSlider#playerVolume::sub-page:horizontal {{ background:#f4eef3; border-radius:1px; }}
            QSlider#playerVolume::handle:horizontal {{ background:#f4eef3; width:9px; margin:-3px 0; border-radius:4px; }}
        """)

    @property
    def position_ms(self): return self._last_position
    @property
    def duration_ms(self): return self._last_duration

    def _load_vlc(self):
        if self._vlc is not None: return
        (self._vlc,self._instance,self._dll_handle,self._dll_directory,
         self._vlc_installation)=initialize_libvlc(self.vlc_executable,self.diagnostic.emit)
        self._player=self._instance.media_player_new()
        self.diagnostic.emit("Integrated player initialized")

    def load(self,path,media_id=None,anime_id=None,series_title="",episode_title="",resume_ms=0,has_previous=False,has_next=False):
        self.stop(save=False); self.path=str(path); self.media_id=media_id; self.anime_id=anime_id; self._threshold_sent=False; self._ended_sent=False; self._duration_logged=False
        self._last_position=0; self._last_duration=0; self._chapters=[]; self._opening_chapter=None; self._ending_chapters=[]; self._active_ending_chapter=None; self._chapters_loaded=False; self.skip_opening.hide(); self.skip_ending.hide(); self.series_label.setText(series_title); self.episode_label.setText(episode_title or "Now Playing")
        self.previous.setEnabled(has_previous); self.next.setEnabled(has_next); self.timeline.setRange(0,0); self.clock.setText("0:00 / 0:00")
        try:
            self._load_vlc(); self._media=self._instance.media_new_path(str(Path(path)))
            self._player.set_media(self._media); self._bind_video(); self._player.audio_set_volume(self._desired_volume); self._player.audio_set_mute(self._desired_muted)
            result=self._player.play()
            if result==-1: raise RuntimeError("libVLC rejected the media file")
            self.timer.start(); self._expected_playing=True; self._set_play_icon(True)
            if hasattr(self._player,"video_set_scale"): self._player.video_set_scale(0.0)
            self.diagnostic.emit(f"Episode launched in integrated player\nMedia path: {path}\nResume position loaded: {resume_ms}ms")
            if resume_ms>0: QTimer.singleShot(600,lambda:self.seek_to(resume_ms))
            QTimer.singleShot(0,self._enable_windowed_overlay); QTimer.singleShot(0,self._configure_skip_overlay); QTimer.singleShot(900,self.refresh_tracks); QTimer.singleShot(1200,self.refresh_chapters)
            if sys.platform.startswith("win"): self.pointer_timer.start()
            self.setFocus()
        except Exception as exc:
            self.diagnostic.emit(f"Integrated playback error\nMedia path: {path}\n{exc}"); self.playback_error.emit(str(path),str(exc))

    def _bind_video(self):
        handle=int(self.video.winId())
        self._video_native_handle=handle
        if sys.platform.startswith("win"): self._player.set_hwnd(handle)
        elif sys.platform=="darwin": self._player.set_nsobject(handle)
        else: self._player.set_xwindow(handle)

    def poll(self):
        if not self._player: return
        position=max(0,self._player.get_time()); duration=max(0,self._player.get_length())
        self._last_position=position; self._last_duration=duration
        if duration>0 and not self._duration_logged:
            self._duration_logged=True; self.diagnostic.emit(f"Duration: {duration}ms\nCurrent playback position: {position}ms\nPlayback percentage: {position/duration:.2%}")
        if not self.timeline.isSliderDown(): self.timeline.setRange(0,max(0,duration)); self.timeline.setValue(min(position,max(0,duration)))
        self.clock.setText(f"{format_time(position)} / {format_time(duration)}")
        self._update_skip_chapters(position)
        playing=bool(self._player.is_playing()); self._set_play_icon(playing)
        if not self._threshold_sent and watched_threshold_reached(position,duration):
            self._threshold_sent=True; self.diagnostic.emit(f"Watched threshold reached: {position}/{duration}ms ({position/duration:.2%})\nWatch-state update requested")
            if self.anime_id is not None and self.media_id is not None: self.watched_threshold.emit(self.anime_id,self.media_id)
        state=self._player.get_state()
        if not self._ended_sent and state==self._vlc.State.Ended:
            self._ended_sent=True; self.timer.stop(); self.diagnostic.emit("Integrated playback ended")
            if self.anime_id is not None and self.media_id is not None: self.playback_ended.emit(self.anime_id,self.media_id)
        elif state==self._vlc.State.Error:
            self.timer.stop(); self.playback_error.emit(self.path,"libVLC reported a playback error")

    def refresh_tracks(self):
        if not self._player: return
        self._fill_track_menu(self.subtitle.menu(),self._player.video_get_spu_description() or [],"Subtitle",self._player.video_get_spu,self._player.video_set_spu,include_off=True)
        self._fill_track_menu(self.audio.menu(),self._player.audio_get_track_description() or [],"Audio",self._player.audio_get_track,self._player.audio_set_track)

    def refresh_chapters(self):
        if not self._player or self._chapters_loaded: return
        try:
            title=self._player.get_title(); descriptions=self._player.get_full_chapter_descriptions(title if title is not None and title>=0 else -1) or []
            chapters=[]
            for index,chapter in enumerate(descriptions):
                name=chapter.name.decode("utf-8","replace") if isinstance(chapter.name,bytes) else str(chapter.name or f"Chapter {index+1}")
                start=max(0,int(chapter.time_offset)); duration=max(0,int(chapter.duration)); end=start+duration
                chapters.append({"index":index,"name":name,"start":start,"end":end})
                self.diagnostic.emit(f"Chapter detected: {name}\nStart: {start}ms\nEnd: {end}ms")
            self._chapters=chapters; self._chapters_loaded=True
            opening=re.compile(r"(?:^|\b)(?:op|opening|intro)(?:\s+theme)?(?:\b|$)",re.I)
            ending=re.compile(r"(?:^|\b)(?:ed|ending(?:\s+(?:theme|credits))?|outro|credits(?:\s+start)?|end\s+credits)(?:\b|$)",re.I)
            self._opening_chapter=next((chapter for chapter in chapters if opening.search(chapter["name"])),None)
            self._ending_chapters=[chapter for chapter in chapters if ending.search(chapter["name"])]
            self.diagnostic.emit(f"Chapter classification: opening={self._opening_chapter['name'] if self._opening_chapter else 'none'}, endings={', '.join(c['name'] for c in self._ending_chapters) or 'none'}")
        except Exception as exc:
            self._chapters_loaded=True; self.diagnostic.emit(f"Chapter metadata unavailable: {exc}")

    def _position_skip_button(self,button):
        button.adjustSize(); point=self.video.mapToGlobal(QPoint(self.video.width()-button.width()-28,self.video.height()-button.height()-110))
        button.move(point); button.show(); button.raise_()

    def _update_skip_chapters(self,position):
        chapter=self._opening_chapter; visible=bool(chapter and chapter["start"]<=position<chapter["end"])
        if visible: self._position_skip_button(self.skip_opening)
        else: self.skip_opening.hide()
        self._active_ending_chapter=next((value for value in self._ending_chapters if value["start"]<=position<value["end"]),None)
        if self._active_ending_chapter: self._position_skip_button(self.skip_ending)
        else: self.skip_ending.hide()

    def _update_skip_opening(self,position):
        """Compatibility wrapper retained for existing integrations/tests."""
        self._update_skip_chapters(position)

    def _configure_skip_overlay(self):
        owner=self.window() if self.window() is not self else None
        for button in (self.skip_opening,self.skip_ending):
            button.hide(); button.setParent(owner,Qt.Tool|Qt.FramelessWindowHint|Qt.NoDropShadowWindowHint)
            button.setAttribute(Qt.WA_ShowWithoutActivating,True); button.setWindowTitle("")
        if sys.platform.startswith("win"):
            try:
                import ctypes; user32=ctypes.windll.user32
                GWL_EXSTYLE=-20; WS_EX_TOOLWINDOW=0x80
                for button in (self.skip_opening,self.skip_ending):
                    hwnd=int(button.winId()); user32.SetWindowLongW(hwnd,GWL_EXSTYLE,user32.GetWindowLongW(hwnd,GWL_EXSTYLE)|WS_EX_TOOLWINDOW)
            except Exception as exc: self.diagnostic.emit(f"Skip Opening overlay configuration warning: {exc}")

    def _skip_opening(self):
        if self._opening_chapter:
            self.seek_to(self._opening_chapter["end"]); self.diagnostic.emit(f"Skip Opening: {self._opening_chapter['name']} -> {self._opening_chapter['end']}ms"); self.skip_opening.hide()

    def _skip_ending(self):
        chapter=self._active_ending_chapter
        if not chapter: return
        following=next((value for value in self._chapters if value["start"]>=chapter["end"] and value not in self._ending_chapters),None)
        target=following["start"] if following else (self._last_duration or chapter["end"])
        self.seek_to(target); self.diagnostic.emit(f"Skip Ending: {chapter['name']} -> {target}ms"); self._active_ending_chapter=None; self.skip_ending.hide()

    def _fill_track_menu(self,menu,tracks,kind,getter,setter,include_off=False):
        menu.clear(); current=getter(); discovered=[]
        if include_off:
            off=menu.addAction("Off"); off.setCheckable(True); off.setChecked(current==-1); off.triggered.connect(lambda _=False:setter(-1))
        for ordinal,entry in enumerate(tracks,1):
            track_id,description=entry; label=track_label(description,kind,ordinal); discovered.append(f"{track_id}:{label}")
            if include_off and track_id==-1: continue
            action=menu.addAction(label); action.setCheckable(True); action.setChecked(track_id==current)
            action.triggered.connect(lambda _,tid=track_id,name=label:(setter(tid),self.diagnostic.emit(f"{kind} track changed: {name} ({tid})")))
        self.diagnostic.emit(f"{kind} tracks discovered: "+(", ".join(discovered) if discovered else "none"))

    def toggle_play(self):
        if not self._player: return
        observed=bool(self._player.is_playing()); target=not (self._expected_playing if self._expected_playing is not None else observed)
        self._expected_playing=target; self._transition_serial+=1; serial=self._transition_serial
        try:
            if target:
                if hasattr(self._player,"set_pause"): self._player.set_pause(0)
                if not self._player.is_playing(): self._player.play()
            else:
                if hasattr(self._player,"set_pause"): self._player.set_pause(1)
                else: self._player.pause()
            self._set_play_icon(target)
        except Exception as exc: self.diagnostic.emit(f"Unexpected playback state transition: target={'playing' if target else 'paused'} error={exc}")
        QTimer.singleShot(220,lambda s=serial,t=target:self._verify_playback_transition(s,t))

    def _verify_playback_transition(self,serial,target):
        if serial!=self._transition_serial or not self._player or self._teardown_started: return
        observed=bool(self._player.is_playing())
        if observed!=target:
            self.diagnostic.emit(f"Unexpected playback state transition: expected={'playing' if target else 'paused'} observed={'playing' if observed else 'paused'}; recovery requested")
            try:
                if target:
                    self._bind_video(); self._player.play()
                    if hasattr(self._player,"video_set_scale"): self._player.video_set_scale(0.0)
                elif hasattr(self._player,"set_pause"): self._player.set_pause(1)
                else: self._player.pause()
            except Exception as exc: self.diagnostic.emit(f"Playback transition recovery failed: {exc}")

    def seek_to(self,milliseconds):
        if self._player and milliseconds>=0: self._player.set_time(int(milliseconds)); self._last_position=int(milliseconds)

    def seek_relative(self,seconds):
        if not self._player: return
        try: live=max(0,int(self._player.get_time()))
        except Exception: live=self._last_position
        base=live if abs(live-self._last_position)<3000 else self._last_position
        target=max(0,min(self._last_duration or 10**12,base+seconds*1000)); self.seek_to(target)
    def set_volume(self,value):
        self._desired_volume=int(value)
        if self._player: self._player.audio_set_volume(self._desired_volume)
    def toggle_mute(self):
        self._desired_muted=not self._desired_muted
        if self._player: self._player.audio_set_mute(self._desired_muted)
        name="SP_MediaVolumeMuted" if self._desired_muted else "SP_MediaVolume"
        self.mute.setIcon(self._standard_icon(name,"SP_MediaVolume")); self.mute.setToolTip("Unmute" if self._desired_muted else "Mute")
    def set_speed(self,text):
        if self._player:
            try: self._player.set_rate(float(text.rstrip("x")))
            except ValueError: pass

    def stop(self,save=True):
        self.timer.stop()
        if self._player:
            try: self._player.stop()
            except Exception: pass

    def set_fullscreen_mode(self,enabled):
        if self._fullscreen_mode==enabled: return
        self._fullscreen_mode=enabled; self.header_widget.setVisible(not enabled)
        if enabled:
            self.outer.setContentsMargins(0,0,0,0); self.outer.setSpacing(0); self.video.setStyleSheet("background:#000;border:0")
            self._prepare_overlay_window()
            self.fullscreen.setIcon(self._standard_icon("SP_TitleBarNormalButton","SP_TitleBarMaxButton")); self.fullscreen.setToolTip("Exit fullscreen")
            self._last_pointer_pos=QCursor.pos(); self._last_mouse_buttons=QApplication.mouseButtons(); self.pointer_timer.start()
            QApplication.instance().installEventFilter(self)
            self.control_panel.show(); self._schedule_overlay_position("fullscreen entry"); self._show_overlay()
        else:
            self.overlay_timer.stop(); self.pointer_timer.stop(); QApplication.instance().removeEventFilter(self); self.unsetCursor(); self.control_panel.hide()
            self.outer.setContentsMargins(22,16,22,18); self.outer.setSpacing(0)
            self.video.setStyleSheet("background:#000;border:1px solid #253047;border-radius:10px")
            self.fullscreen.setIcon(self._standard_icon("SP_TitleBarMaxButton")); self.fullscreen.setToolTip("Fullscreen")
            self._enable_windowed_overlay(); self._schedule_overlay_position("fullscreen exit")
        self.updateGeometry()

    def _deactivate_owned_overlays(self,close=False,reason="hidden"):
        overlays=(self.preview,self.skip_opening,self.skip_ending,self.input_overlay,self.control_panel)
        visible=[type(widget).__name__ for widget in overlays if widget.isVisible()]
        for widget in overlays:
            widget.setAttribute(Qt.WA_TransparentForMouseEvents,True); widget.hide()
            if close: widget.close()
        self.diagnostic.emit(f"Player overlays deactivated: reason={reason}, previously_visible={','.join(visible) or 'none'}, close={close}")

    def _activate_input_overlay(self):
        self.input_overlay.setAttribute(Qt.WA_TransparentForMouseEvents,False)
        self.control_panel.setAttribute(Qt.WA_TransparentForMouseEvents,False)

    def _enable_windowed_overlay(self):
        if self._fullscreen_mode or self._teardown_started or not self.isVisible(): return
        self._windowed_overlay=True; self._prepare_overlay_window(); self._activate_input_overlay(); self.control_panel.show()
        if sys.platform.startswith("win"): self.pointer_timer.start()
        QApplication.instance().installEventFilter(self); self._schedule_overlay_position("windowed overlay")

    def _prepare_overlay_window(self):
        self.control_panel.hide()
        owner=self.window() if self.window() is not self else None
        self.control_panel.setParent(owner,Qt.Tool|Qt.FramelessWindowHint|Qt.NoDropShadowWindowHint)
        windows=sys.platform.startswith("win")
        self.control_panel.setAttribute(Qt.WA_TranslucentBackground,True); self.control_panel.setAttribute(Qt.WA_NoSystemBackground,True); self.control_panel.setAutoFillBackground(False); self.control_panel.setAttribute(Qt.WA_ShowWithoutActivating,True)
        palette=self.control_panel.palette(); palette.setColor(QPalette.Window,QColor(0,0,0,0)); self.control_panel.setPalette(palette)
        self.control_panel.set_fullscreen_overlay(True); self._apply_control_style(True)
        self._prepare_input_overlay(); self._activate_input_overlay()
        if windows: self._enable_windows_alpha()

    def _prepare_input_overlay(self):
        owner=self.window() if self.window() is not self else None
        if self.input_overlay.parent() is not owner or not self.input_overlay.isWindow():
            self.input_overlay.hide(); self.input_overlay.setParent(owner,Qt.Tool|Qt.FramelessWindowHint|Qt.NoDropShadowWindowHint)
        self.input_overlay.setAttribute(Qt.WA_TranslucentBackground,True); self.input_overlay.setAttribute(Qt.WA_NoSystemBackground,True)
        self.input_overlay.setAttribute(Qt.WA_ShowWithoutActivating,True); self.input_overlay.setAutoFillBackground(False)

    def _position_overlay(self):
        if self._teardown_started or not self.isVisible():
            self.input_overlay.setAttribute(Qt.WA_TransparentForMouseEvents,True); self.input_overlay.hide(); self.control_panel.setAttribute(Qt.WA_TransparentForMouseEvents,True); self.control_panel.hide(); return
        if not (self._fullscreen_mode or self._windowed_overlay): return
        viewport=self.video; width=max(280,viewport.width()); height=82; origin=viewport.mapToGlobal(QPoint(0,0))
        self.input_overlay.setGeometry(origin.x(),origin.y(),viewport.width(),viewport.height())
        if not self.input_overlay.isVisible(): self.input_overlay.show()
        self.input_overlay.raise_()
        if self.control_panel.isVisible():
            self.control_panel.setGeometry(origin.x(),origin.y()+max(0,viewport.height()-height),width,height); self.control_panel.raise_()
        if self.skip_opening.isVisible(): self.skip_opening.raise_()
        if self.skip_ending.isVisible(): self.skip_ending.raise_()

    def _schedule_overlay_position(self,reason="geometry change"):
        for delay in (0,30,120): QTimer.singleShot(delay,self._position_overlay)
        QTimer.singleShot(125,lambda:self._log_overlay_geometry(reason))

    def _log_overlay_geometry(self,reason):
        if self._teardown_started: return
        origin=self.video.mapToGlobal(QPoint(0,0)); screen=self.video.screen().geometry()
        self.diagnostic.emit(f"Player overlay geometry\nReason: {reason}\nFullscreen state: {self._fullscreen_mode}\nPlayer viewport geometry: {self.video_container.geometry().getRect()}\nVideo surface geometry: {self.video.geometry().getRect()}\nVideo global origin: ({origin.x()}, {origin.y()})\nOverlay geometry: {self.control_panel.geometry().getRect()}\nOverlay parent: {type(self.control_panel.parent()).__name__ if self.control_panel.parent() else 'None'}\nOverlay is top-level: {self.control_panel.isWindow()}\nScreen geometry: {screen.getRect()}\nLayout reserves overlay height: no")

    def _show_overlay(self):
        if self._teardown_started or not self.isVisible() or not (self._fullscreen_mode or self._windowed_overlay): return
        if not self.control_panel.isVisible():
            self.control_panel.show();
            if sys.platform.startswith("win"): self._enable_windows_alpha()
            self._position_overlay(); self.control_panel.raise_()
        self.unsetCursor(); self.input_overlay.raise_(); self.control_panel.raise_()
        if self.skip_opening.isVisible(): self.skip_opening.raise_()
        if self.skip_ending.isVisible(): self.skip_ending.raise_()
        if self._fullscreen_mode and not self._menu_open: self.overlay_timer.start()

    def _hide_overlay(self):
        if not self._fullscreen_mode: return
        if self._menu_open or self.timeline.isSliderDown(): self.overlay_timer.stop(); return
        self.control_panel.hide(); self.setCursor(Qt.BlankCursor)

    def _menu_opened(self):
        self._menu_open=True; self.overlay_timer.stop()
        if self._fullscreen_mode and not self.control_panel.isVisible():
            self.control_panel.show(); self._position_overlay()

    def _menu_closed(self):
        self._menu_open=False; self._show_overlay()

    def _enable_windows_alpha(self):
        """Keep Qt's per-pixel alpha path and mark the owned overlay as a tool window."""
        if not sys.platform.startswith("win"): return "not required"
        try:
            import ctypes
            hwnd=int(self.control_panel.winId()); user32=ctypes.windll.user32
            GWL_EXSTYLE=-20; WS_EX_LAYERED=0x00080000; WS_EX_TOOLWINDOW=0x00000080
            style=user32.GetWindowLongW(hwnd,GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd,GWL_EXSTYLE,style|WS_EX_TOOLWINDOW)
            self.control_panel.update()
            updated=user32.GetWindowLongW(hwnd,GWL_EXSTYLE)
            return f"Win32 top-level per-pixel alpha (HWND {hwnd}, layered={bool(updated&WS_EX_LAYERED)}, toolwindow={bool(updated&WS_EX_TOOLWINDOW)})"
        except Exception as exc:
            self.diagnostic.emit(f"Fullscreen overlay alpha configuration warning: {exc}")
            return f"Win32 per-pixel alpha setup warning: {exc}"

    def _poll_pointer_activity(self):
        """Native libVLC video HWNDs can bypass Qt mouse events; poll the cursor as a fallback."""
        if not (self._fullscreen_mode or self._windowed_overlay): return
        position=QCursor.pos(); buttons=QApplication.mouseButtons()
        local=self.video_container.mapFromGlobal(position); over_video=self.video_container.rect().contains(local)
        moved=position!=self._last_pointer_pos; clicked=buttons!=Qt.NoButton and self._last_mouse_buttons==Qt.NoButton
        self._last_pointer_pos=position; self._last_mouse_buttons=buttons
        if over_video and (moved or clicked): self._show_overlay()

    def eventFilter(self,watched,event):
        if (self._windowed_overlay or self._fullscreen_mode) and event.type() in (QEvent.Move,QEvent.Resize,QEvent.Show,QEvent.WindowStateChange) and (watched is self.window() or watched is self.video or watched is self.video_container):
            QTimer.singleShot(0,self._position_overlay)
        if self._fullscreen_mode and event.type() in (QEvent.MouseMove,QEvent.MouseButtonPress,QEvent.MouseButtonDblClick,QEvent.Wheel):
            is_player_widget=isinstance(watched,QWidget) and (watched is self or self.isAncestorOf(watched) or watched is self.control_panel or self.control_panel.isAncestorOf(watched))
            is_player_menu=watched in (self.subtitle.menu(),self.audio.menu())
            if is_player_widget or is_player_menu: self._show_overlay()
        return super().eventFilter(watched,event)

    def resizeEvent(self,event):
        super().resizeEvent(event); self._schedule_overlay_position("player resize")

    def showEvent(self,event):
        super().showEvent(event)
        if not self._fullscreen_mode: self._enable_windowed_overlay()
        elif not self._teardown_started:
            self.pointer_timer.start();QApplication.instance().installEventFilter(self);self._show_overlay()

    def hideEvent(self,event):
        self.pointer_timer.stop();self.overlay_timer.stop();self.preview_delay.stop()
        self.video._single_click.stop();self.input_overlay._single_click.stop()
        QApplication.instance().removeEventFilter(self)
        self._deactivate_owned_overlays(False,"player hidden"); super().hideEvent(event)

    def closeEvent(self,event):
        self.begin_teardown("player close",self.diagnostic.emit)
        event.accept()

    def keyPressEvent(self,event: QKeyEvent):
        key=event.key()
        if self._fullscreen_mode: self._show_overlay()
        if key==Qt.Key_Space: self.toggle_play()
        elif key==Qt.Key_Left: self.seek_relative(-self.seek_step)
        elif key==Qt.Key_Right: self.seek_relative(self.seek_step)
        elif key==Qt.Key_Up: self.volume.setValue(min(100,self.volume.value()+5))
        elif key==Qt.Key_Down: self.volume.setValue(max(0,self.volume.value()-5))
        elif key==Qt.Key_M: self.toggle_mute()
        elif key==Qt.Key_F: self.fullscreen_requested.emit()
        elif key==Qt.Key_Escape and self.window().isFullScreen(): self.fullscreen_requested.emit()
        else: super().keyPressEvent(event); return
        event.accept()

    def begin_teardown(self,reason,logger):
        """Detach Qt immediately, then release potentially slow libVLC resources off-thread."""
        if self._teardown_started:
            logger(f"Player teardown requested\nreason: {reason}\ncleanup already active: yes")
            return False
        self._teardown_started=True; started=time.monotonic()
        logger(f"Player teardown requested\nreason: {reason}\ncleanup already active: no")
        self.timer.stop(); self.overlay_timer.stop(); self.pointer_timer.stop(); self.preview_delay.stop(); self._deactivate_owned_overlays(True,"teardown")
        self.video._single_click.stop();self.input_overlay._single_click.stop()
        for shortcut in self._shortcuts: shortcut.setEnabled(False)
        try: QApplication.instance().removeEventFilter(self)
        except Exception: pass
        self.unsetCursor(); logger("timers stopped; owned overlays closed and mouse-transparent")
        player,media,instance=self._player,self._media,self._instance
        runtime_refs=(self._vlc,self._dll_handle,self._dll_directory,self._vlc_installation)
        self._player=None; self._media=None; self._instance=None
        try:
            if player:
                if sys.platform.startswith("win"): player.set_hwnd(0)
                elif sys.platform=="darwin": player.set_nsobject(0)
                else: player.set_xwindow(0)
            logger("video surface detached")
        except Exception as exc: logger(f"Player teardown exception\nfailure stage: video surface detach\n{exc}")
        finished=threading.Event()
        def watchdog():
            if not finished.wait(2.0): logger("Player teardown timeout\ntimeout/fallback used: background cleanup continues without blocking the UI")
        threading.Thread(target=watchdog,name="AniVaultVlcTeardownWatchdog",daemon=True).start()
        def release_native():
            stage="playback stop"
            try:
                logger("playback stop requested")
                if player: player.stop()
                logger("playback stopped")
                stage="media detach"
                if player:
                    try: player.set_media(None)
                    except Exception: pass
                stage="media release"
                if media and hasattr(media,"release"): media.release()
                logger("media released")
                stage="player release"
                if player and hasattr(player,"release"): player.release()
                logger("player released")
                stage="VLC instance release"
                if instance and hasattr(instance,"release"): instance.release()
                logger("VLC instance released")
            except Exception as exc: logger(f"Player teardown exception\nfailure stage: {stage}\n{exc}")
            finally:
                _=runtime_refs  # Keep the loaded libVLC runtime alive through the final release.
                finished.set(); elapsed=(time.monotonic()-started)*1000
                logger(f"widget destruction complete\nteardown complete\nelapsed teardown time: {elapsed:.0f}ms\ntimeout/fallback used: {'yes' if elapsed>=2000 else 'no'}")
        threading.Thread(target=release_native,name="AniVaultVlcTeardown",daemon=True).start()
        return True
