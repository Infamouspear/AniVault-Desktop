from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def vlc_command(vlc: str, media_path: str, port: int) -> list[str]:
    return [vlc, "--no-one-instance", "--no-playlist-enqueue", "--extraintf=rc",
            f"--rc-host=127.0.0.1:{port}", media_path]


def extract_rc_integer(reply: str) -> int | None:
    values = re.findall(r"(?:^|[\r\n>])\s*(-?\d+)\s*(?=[\r\n]|$)", reply)
    return int(values[-1]) if values else None


def watched_threshold_reached(position: int | None, duration: int | None, threshold: float = .90) -> bool:
    return bool(duration and duration>0 and position is not None and position/duration>=threshold)


class PlaybackMonitor(QThread):
    watched = Signal(int, int)
    playback_status = Signal(str)
    diagnostic = Signal(str)

    def __init__(self, process, port: int, media_path: str, media_id: int, anime_id: int,
                 threshold: float = 0.90, poll_seconds: float = 2.0):
        super().__init__()
        self.process=process; self.port=port; self.media_path=media_path
        self.media_id=media_id; self.anime_id=anime_id; self.threshold=threshold
        self.poll_seconds=poll_seconds

    def run(self):
        self.diagnostic.emit(f"Episode launched\nMedia path: {self.media_path}\nControl port: {self.port}")
        connection=None
        for _ in range(40):
            if self.isInterruptionRequested() or self.process.poll() is not None: break
            try:
                connection=socket.create_connection(("127.0.0.1",self.port),timeout=.5)
                connection.settimeout(.25); break
            except OSError: time.sleep(.25)
        if connection is None:
            self.diagnostic.emit("VLC session not detected before process exit/timeout")
            return
        self.diagnostic.emit("VLC session detected")
        try:
            self._drain(connection)
            while not self.isInterruptionRequested() and self.process.poll() is None:
                duration=self._query(connection,"get_length")
                position=self._query(connection,"get_time")
                if duration and duration>0 and position is not None:
                    percentage=max(0.0,min(position/duration,1.0))
                    self.playback_status.emit(f"VLC playback: {percentage:.0%}")
                    self.diagnostic.emit(f"Duration: {duration}s\nCurrent playback position: {position}s\nPlayback percentage: {percentage:.2%}")
                    if watched_threshold_reached(position,duration,self.threshold):
                        self.diagnostic.emit(f"Watched threshold reached: {percentage:.2%} >= {self.threshold:.0%}\nWatch-state update requested")
                        self.watched.emit(self.anime_id,self.media_id)
                        return
                time.sleep(self.poll_seconds)
            self.diagnostic.emit("VLC session ended before watched threshold" if not self.isInterruptionRequested() else "Playback monitoring stopped during app shutdown")
        except (OSError,ValueError) as exc:
            self.diagnostic.emit(f"VLC monitoring connection ended: {exc}")
        finally:
            try: connection.close()
            except OSError: pass

    def _drain(self,connection):
        try:
            while connection.recv(4096): pass
        except (socket.timeout,OSError): pass

    def _query(self,connection,command):
        connection.sendall((command+"\n").encode("ascii")); time.sleep(.06)
        chunks=[]
        while True:
            try:
                data=connection.recv(4096)
                if not data: break
                chunks.append(data)
            except socket.timeout: break
        return extract_rc_integer(b"".join(chunks).decode("utf-8","replace"))


def launch_vlc_session(vlc: str, media_path: str):
    port=reserve_local_port()
    kwargs={}
    if sys.platform=="win32": kwargs["creationflags"]=subprocess.CREATE_NO_WINDOW
    process=subprocess.Popen(vlc_command(vlc,media_path,port),**kwargs)
    return process,port
