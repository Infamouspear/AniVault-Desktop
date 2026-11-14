"""One long-lived background queue for explicit scans and visible thumbnails."""
from collections import deque
from pathlib import Path
import threading
from PySide6.QtCore import QObject, Signal, Qt
from .manga_library import scan_manga
from .manga_sources import open_source

class MangaJobs(QObject):
    scanned=Signal(object)
    scan_failed=Signal(str)
    cover_ready=Signal(int,str,str)
    def __init__(self,cache_dir):
        super().__init__();self.cache_dir=Path(cache_dir);self.condition=threading.Condition()
        self.pending=deque();self.cover_keys=set();self.stopped=False;self.scan_active=False
        self.thread=threading.Thread(target=self.run,name='AniVaultMangaLibrary',daemon=True);self.thread.start()
    def scan(self,roots):
        with self.condition:
            if self.scan_active or self.stopped:return False
            self.scan_active=True;self.pending.appendleft(('scan',roots));self.condition.notify();return True
    def cover(self,item):
        with self.condition:
            if self.stopped or item['id'] in self.cover_keys or len(self.cover_keys)>=12:return False
            self.cover_keys.add(item['id']);self.pending.append(('cover',dict(item)));self.condition.notify();return True
    def retain_covers(self,ids):
        with self.condition:
            self.pending=deque((kind,data) for kind,data in self.pending if kind!='cover' or data['id'] in ids)
            self.cover_keys={data['id'] for kind,data in self.pending if kind=='cover'}
    def stop(self):
        with self.condition:self.stopped=True;self.pending.clear();self.condition.notify()
    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.stopped or self.pending)
                if self.stopped:return
                kind,data=self.pending.popleft()
            if kind=='scan':
                try:
                    result=scan_manga(data,lambda:self.stopped)
                    if not self.stopped:self.scanned.emit(result)
                except Exception as exc:
                    if not self.stopped:self.scan_failed.emit(f'{type(exc).__name__}: {exc}')
                finally:
                    with self.condition:self.scan_active=False
            else:
                source=None;error='';path=''
                try:
                    self.cache_dir.mkdir(parents=True,exist_ok=True)
                    destination=self.cache_dir/(data['reader_identity']+'-'+str(int(data.get('modified',0)*1000000))+'.png')
                    if not destination.exists():
                        source=open_source(data['path'],self.cache_dir/'temporary')
                        image=source.image(0).scaled(270,330,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                        temporary=destination.with_suffix('.tmp.png')
                        if not image.save(str(temporary),'PNG'):raise OSError('Could not cache thumbnail.')
                        temporary.replace(destination)
                    path=str(destination)
                except Exception as exc:error=f'{type(exc).__name__}: {exc}'
                finally:
                    if source is not None:
                        try:source.close()
                        except Exception:pass
                    with self.condition:self.cover_keys.discard(data['id'])
                if not self.stopped:self.cover_ready.emit(data['id'],path,error)
