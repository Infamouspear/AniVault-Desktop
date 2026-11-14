import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from anime_hub.integrated_player import (IntegratedPlayer, PlayerControlOverlay,
    clean_episode_label, format_time, track_label)


def qt_app():
    return QApplication.instance() or QApplication([])


def test_player_time_and_track_fallback_labels():
    assert format_time(0)=="0:00"
    assert format_time(761000)=="12:41"
    assert format_time(3723000)=="1:02:03"
    assert track_label(b"English Signs/Songs","Subtitle",2)=="English Signs/Songs"
    assert track_label(b"undetermined","Audio",3)=="Audio Track 3"


def test_player_controls_exist_without_initializing_libvlc():
    qt_app(); player=IntegratedPlayer(seek_step=10,volume=72,muted=True)
    assert player.seek_step==10
    assert player.volume.value()==72
    assert player.mute.text()==""
    assert player.mute.toolTip()=="Mute"
    assert player.subtitle.menu() is not None
    assert player.audio.menu() is not None
    player.stop()


def test_play_button_is_immediate_and_state_transitions_use_explicit_pause():
    app=qt_app(); player=IntegratedPlayer(hover_previews=False); calls=[]
    class Native:
        playing=True
        def is_playing(self): return self.playing
        def set_pause(self,value): calls.append(("pause",value)); self.playing=not bool(value)
        def play(self): calls.append(("play",)); self.playing=True
    player._player=Native(); player._expected_playing=True; player.show(); app.processEvents()
    QTest.mouseClick(player.play_pause,Qt.LeftButton)
    assert calls==[("pause",1)] and player._expected_playing is False
    QTest.mouseClick(player.play_pause,Qt.LeftButton)
    assert calls[-1]==("pause",0) and player._expected_playing is True
    player.close()


def test_hidden_player_overlays_release_mouse_input():
    app=qt_app(); player=IntegratedPlayer(hover_previews=False); player.resize(800,500); player.show(); app.processEvents()
    player._enable_windowed_overlay(); app.processEvents(); assert not player.input_overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
    player.hide(); app.processEvents()
    assert player.input_overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert player.control_panel.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert not player.input_overlay.isVisible() and not player.control_panel.isVisible()
    player.close()


def test_clean_episode_label_removes_release_metadata():
    path="7th.Time.Loop.S01E01.The.Fiancée.Who.Killed.Me.1080p.BluRay.REMUX.AVC.FLAC.2.0.mkv"
    assert clean_episode_label(path,1)=="Episode 1 — The Fiancée Who Killed Me"
    assert clean_episode_label("[Judas] Show - S01E01.mkv",1)=="Episode 1"
    assert clean_episode_label(path,1,"The Fiancée Who Killed Me")=="Episode 1 — The Fiancée Who Killed Me"


def test_fullscreen_mode_uses_video_only_canvas_and_overlay():
    qt_app(); player=IntegratedPlayer(); player.resize(1280,720); player.show(); qt_app().processEvents()
    player.set_fullscreen_mode(True); qt_app().processEvents()
    assert not player.header_widget.isVisible()
    assert player.control_panel.isVisible()
    assert player.control_panel.isWindow()
    assert player.control_panel.testAttribute(Qt.WA_TranslucentBackground)
    assert player.control_panel.windowFlags() & Qt.Tool
    assert player.overlay_timer.interval()==2600
    assert player.pointer_timer.isActive()
    assert player.fullscreen.toolTip()=="Exit fullscreen"
    player._hide_overlay(); qt_app().processEvents()
    assert not player.control_panel.isVisible()
    player._show_overlay(); qt_app().processEvents()
    assert player.control_panel.isVisible()
    player.set_fullscreen_mode(False); qt_app().processEvents()
    assert player.header_widget.isVisible()
    assert player.control_panel.isVisible()
    assert player.control_panel.isWindow()
    assert player.control_panel.fullscreen_overlay
    assert player.fullscreen.toolTip()=="Fullscreen"
    # Windows windowed native video still needs pointer polling for its input overlay.
    assert player.pointer_timer.isActive() == (os.name=="nt")
    player.close()
    assert not player.pointer_timer.isActive()


def test_native_video_pointer_poll_reveals_hidden_overlay(monkeypatch):
    qt_app(); player=IntegratedPlayer(); player.resize(1280,720); player.show(); qt_app().processEvents()
    player.set_fullscreen_mode(True); qt_app().processEvents(); player._hide_overlay(); qt_app().processEvents()
    assert not player.control_panel.isVisible()
    start=player.video_container.mapToGlobal(player.video_container.rect().center())
    current={"position":start}
    monkeypatch.setattr(QCursor,"pos",staticmethod(lambda:current["position"]))
    for offset in range(1,4):
        player._hide_overlay(); qt_app().processEvents(); assert not player.control_panel.isVisible()
        player._last_pointer_pos=current["position"]; current["position"]=start+QPoint(offset,0)
        player._poll_pointer_activity(); qt_app().processEvents(); assert player.control_panel.isVisible()
    player.close()


def test_visible_overlay_activity_only_resets_one_timer(monkeypatch):
    qt_app(); player=IntegratedPlayer(); player.resize(1280,720); player.show(); qt_app().processEvents()
    player.set_fullscreen_mode(True); qt_app().processEvents(); assert player.control_panel.isVisible()
    calls=[]; original_show=player.control_panel.show
    monkeypatch.setattr(player.control_panel,"show",lambda:(calls.append("show"),original_show()))
    for _ in range(12): player._show_overlay()
    assert calls==[]
    assert player.overlay_timer.isActive()
    player._menu_opened(); player._hide_overlay(); qt_app().processEvents()
    assert player.control_panel.isVisible()
    assert not player.overlay_timer.isActive()
    player._menu_closed(); assert player.overlay_timer.isActive()
    player.close()


def test_actual_fullscreen_overlay_keeps_transparent_pixels():
    app=qt_app(); previous_style=app.styleSheet(); app.setStyleSheet("QWidget { background:#080c12; color:white; }")
    player=IntegratedPlayer(); player.resize(1280,720); player.show(); app.processEvents()
    player.set_fullscreen_mode(True); app.processEvents(); player._show_overlay(); app.processEvents()
    image=player.control_panel.grab().toImage()
    samples=[image.pixelColor(x,y).alpha() for y in range(0,image.height(),max(1,image.height()//8)) for x in range(0,image.width(),max(1,image.width()//20))]
    assert min(samples)<40
    assert any(40<=alpha<220 for alpha in samples)
    player.set_fullscreen_mode(False); player.close(); app.setStyleSheet(previous_style)


def test_overlay_uses_smooth_alpha_gradient_without_checkerboard():
    app=qt_app(); overlay=PlayerControlOverlay(); overlay.resize(500,100); overlay.setAttribute(Qt.WA_TranslucentBackground,True); overlay.set_fullscreen_overlay(True); overlay.show(); app.processEvents()
    image=overlay.grab().toImage()
    top=image.pixelColor(250,5).alpha(); middle=image.pixelColor(250,55).alpha(); bottom=image.pixelColor(250,95).alpha()
    assert top<middle<bottom
    overlay.close()


def test_teardown_is_guarded_and_native_release_is_nonblocking():
    qt_app(); player=IntegratedPlayer(); released=threading.Event(); logs=[]
    def record(message):
        logs.append(message)
        if "teardown complete" in message: released.set()
    class SlowPlayer:
        def set_xwindow(self,value): logs.append(f"detached:{value}")
        set_hwnd=set_xwindow
        set_nsobject=set_xwindow
        def stop(self): time.sleep(.25); logs.append("stopped")
        def set_media(self,value): logs.append("media detached")
        def release(self): logs.append("player released fake")
    class Resource:
        def __init__(self,name): self.name=name
        def release(self): logs.append(f"{self.name} released fake")
    player._player=SlowPlayer(); player._media=Resource("media"); player._instance=Resource("instance")
    started=time.monotonic()
    assert player.begin_teardown("navigation",record)
    assert time.monotonic()-started<.1
    assert not player.begin_teardown("app close",record)
    assert released.wait(1.0)
    combined="\n".join(logs)
    assert "cleanup already active: yes" in combined
    assert "video surface detached" in combined
    assert "Player teardown exception" not in combined
    assert "playback stopped" in combined
    assert "media released" in combined
    assert "player released" in combined
    assert "VLC instance released" in combined
    assert "teardown complete" in combined


def test_integrated_poll_emits_watch_threshold(monkeypatch,tmp_path):
    qt_app(); path=tmp_path/"episode.mkv"; path.write_bytes(b"media")
    fake_vlc=SimpleNamespace(State=SimpleNamespace(Ended="ended",Error="error"))
    class FakeInstance:
        def media_new_path(self,path): return path
    class FakePlayer:
        def set_media(self,media): pass
        def set_xwindow(self,handle): pass
        def audio_set_volume(self,value): pass
        def audio_set_mute(self,value): pass
        def play(self): return 0
        def stop(self): pass
        def get_time(self): return 95000
        def get_length(self): return 100000
        def is_playing(self): return True
        def get_state(self): return "playing"
        def set_time(self,value): pass
        def video_get_spu_description(self): return []
        def audio_get_track_description(self): return []
        def video_get_spu(self): return -1
        def audio_get_track(self): return 1
    player=IntegratedPlayer(); fake=FakePlayer()
    def load_fake(): player._vlc=fake_vlc; player._instance=FakeInstance(); player._player=fake
    monkeypatch.setattr(player,"_load_vlc",load_fake)
    watched=[]; player.watched_threshold.connect(lambda anime_id,media_id:watched.append((anime_id,media_id)))
    player.load(path,7,3,"Show","Episode 1")
    player.poll(); player.poll()
    assert watched==[(3,7)]
    player.stop()
