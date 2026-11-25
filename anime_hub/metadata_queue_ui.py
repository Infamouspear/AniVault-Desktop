"""One persistent metadata worker, independent of the local indexing worker."""
import sqlite3,threading,time
from PySide6.QtCore import QThread,Signal,QTimer
from . import metadata_jobs as jobs
from .anilist_transport import get_scheduler

class MetadataWorker(QThread):
    status=Signal(str)
    changed=Signal(object)
    def __init__(self,path):
        super().__init__();self.path=path;self.event=threading.Event()
    def wake(self):self.event.set()
    def stop(self):self.requestInterruption();self.event.set()
    def run(self):
        from .database import Database
        db=None
        try:
            while db is None and not self.isInterruptionRequested():
                try:db=Database(self.path)
                except sqlite3.OperationalError:
                    self.status.emit('Metadata queue is waiting for the library database; local indexing is not restarted.');self.event.wait(2);self.event.clear()
            if db is None:return
            while not self.isInterruptionRequested():
                try:
                    if db.setting('metadata_paused','0')!='1':
                        result=jobs.process(db,should_cancel=self.isInterruptionRequested,status=self.status.emit)
                        if result['processed']:self.changed.emit(result)
                    else:self.status.emit(jobs.progress_text(db))
                    due=jobs.next_due(db)
                    delay=30 if due is None or db.setting('metadata_paused','0')=='1' else max(.25,min(30,due-time.time()))
                except sqlite3.OperationalError:
                    db.connection.rollback();delay=2;self.status.emit('Metadata queue is waiting for local indexing to commit; no file discovery is restarted.')
                except Exception:
                    db.connection.rollback();delay=60;self.status.emit('Metadata processing paused after an unexpected failure. Queued work is retained for retry.')
                self.event.wait(delay);self.event.clear()
        finally:
            if db is not None:db.connection.close()

class MetadataQueueMixin:
    def _init_metadata_queue(self):
        self.metadata_worker=None;self.local_scan_status='Not running'
        if self.db.setting('metadata_queue_seeded_v191','0')!='1':
            jobs.enqueue_existing(self.db);self.db.set_setting('metadata_queue_seeded_v191','1')
        self._metadata_start_timer=QTimer(self);self._metadata_start_timer.setSingleShot(True)
        self._metadata_start_timer.timeout.connect(self.resume_metadata_jobs);self._metadata_start_timer.start(750)

    def resume_metadata_jobs(self,manual=False):
        if self._closing:return
        if manual:self.db.set_setting('metadata_paused','0')
        if self.db.setting('metadata_paused','0')=='1':return
        if not self.db.connection.execute("SELECT 1 FROM metadata_jobs WHERE scope='normal' AND state<>'completed' LIMIT 1").fetchone():return
        if self.metadata_worker is None or not self.metadata_worker.isRunning():
            if self.metadata_worker is not None:self.metadata_worker.deleteLater()
            self.metadata_worker=MetadataWorker(self.db_path)
            self.metadata_worker.status.connect(self._metadata_status)
            self.metadata_worker.changed.connect(self._metadata_changed)
            self.metadata_worker.start()
        else:self.metadata_worker.wake()

    def pause_metadata_jobs(self):
        self.db.set_setting('metadata_paused','1')
        # A running request may finish; no subsequent job will start while paused.
        if self.metadata_worker:self.metadata_worker.wake()
        self._metadata_status(jobs.progress_text(self.db))

    def _metadata_status(self,message):
        self._metadata_message=message
        if not self._closing and (self.scan_worker is None or not self.scan_worker.isRunning()):self.statusBar().showMessage(message)

    def _metadata_changed(self,result):
        if self._closing:return
        if result.get('applied'):
            self._library_cache_dirty=True;self._library_page_cache.clear();self._library_franchise_cache={}
            self.requests_changed.emit()
        self._metadata_status(jobs.progress_text(self.db))
