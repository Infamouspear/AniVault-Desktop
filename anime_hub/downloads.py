"""Persistent direct-file queue. One daemon worker; no Qt-thread shutdown waits."""
import os,re,sqlite3,threading,time,urllib.request,urllib.parse
from contextlib import closing
from pathlib import Path
from PySide6.QtCore import QObject,Signal,Qt

SCHEMA='''CREATE TABLE IF NOT EXISTS downloads(
 id INTEGER PRIMARY KEY,url TEXT NOT NULL,target TEXT NOT NULL UNIQUE,temp TEXT NOT NULL,
 label TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'Queued',downloaded INTEGER NOT NULL DEFAULT 0,
 total INTEGER,resumable INTEGER NOT NULL DEFAULT 0,validator TEXT,error TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);'''

def safe_url(value):
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Use a direct HTTP/HTTPS URL without embedded credentials.')
    return value

class Downloads(QObject):
    changed=Signal(int)
    _received=Signal(dict)
    def __init__(self,db,log=lambda *_:None,parent=None):
        super().__init__(parent);self.db=db;self.log=log;self.closed=False;self.active=None;self._thread=None;self._cancel=None;self._reason='Cancelled';self._generation=0
        db.connection.executescript(SCHEMA)
        self._db_path=db.connection.execute('PRAGMA database_list').fetchone()[2]
        with db.connection:
            db.connection.execute("UPDATE downloads SET state='Paused',error='Recovered after restart; resume or retry.' WHERE state IN ('Queued','Downloading')")
            for row in self.rows():
                partial=Path(row['temp'])
                if row['state']=='Paused' and partial.is_file() and not partial.is_symlink():db.connection.execute('UPDATE downloads SET downloaded=? WHERE id=?',(partial.stat().st_size,row['id']))
                if row['state']=='Paused' and (partial.is_symlink() or (row['downloaded'] and not partial.is_file())):db.connection.execute("UPDATE downloads SET state='Failed',error='Partial file is missing or unsafe; Retry starts over.' WHERE id=?",(row['id'],))
        states=dict(db.connection.execute('SELECT state,COUNT(*) FROM downloads GROUP BY state'))
        self.log(f'DownloadRecovery states={states}')
        self._received.connect(self._on_received,Qt.QueuedConnection)
    def rows(self):return [dict(row) for row in self.db.connection.execute('SELECT * FROM downloads ORDER BY id DESC')]
    def get(self,i):
        row=self.db.connection.execute('SELECT * FROM downloads WHERE id=?',(i,)).fetchone();return dict(row) if row else None
    def add(self,url,target,label=''):
        safe_url(url);target=Path(target).expanduser().absolute();temp=Path(str(target)+'.part')
        if target.exists() or target.is_symlink() or temp.exists() or temp.is_symlink():raise ValueError('Destination or its .part file already exists. Choose another filename.')
        if not target.parent.is_dir():raise ValueError('Choose an existing destination folder.')
        if self.db.connection.execute('SELECT 1 FROM downloads WHERE target=?',(str(target),)).fetchone():raise ValueError('This destination is already in the queue.')
        with self.db.connection:
            cur=self.db.connection.execute('INSERT INTO downloads(url,target,temp,label) VALUES(?,?,?,?)',(url,str(target),str(temp),label or urllib.parse.urlsplit(url).hostname))
        identifier=cur.lastrowid;self.log(f'DownloadQueued id={identifier} host={urllib.parse.urlsplit(url).hostname}');self.changed.emit(identifier);self._pump();return identifier
    def _update(self,i,**values):
        with self.db.connection:self.db.connection.execute('UPDATE downloads SET '+','.join(key+'=?' for key in values)+",updated_at=CURRENT_TIMESTAMP WHERE id=?",(*values.values(),i))
        self.changed.emit(i)
    def pause(self,i):
        row=self.get(i)
        if not row:return
        if i==self.active:
            if not row['resumable']:raise ValueError('This server has not confirmed safe resumable transfers. Use Cancel instead.')
            self._reason='Paused';self._cancel.set();self.log(f'DownloadPause id={i}')
        elif row['state']=='Queued':self._update(i,state='Paused')
    def cancel(self,i):
        row=self.get(i)
        if not row or row['state'] not in {'Queued','Downloading','Paused'}:return
        if i==self.active:self._reason='Cancelled';self._cancel.set()
        else:self._update(i,state='Cancelled')
        self.log(f'DownloadCancel id={i}')
    def resume(self,i):
        row=self.get(i)
        if not row or row['state']!='Paused' or i==self.active:return
        if row['downloaded'] and not row['resumable']:raise ValueError('This transfer cannot safely resume. Retry starts over.')
        self._update(i,state='Queued',error='');self.log(f'DownloadResume id={i} bytes={row["downloaded"]}');self._pump()
    def retry(self,i):
        row=self.get(i)
        if not row or i==self.active or row['state'] not in {'Paused','Failed','Cancelled'}:return
        temp=Path(row['temp'])
        if temp.is_symlink():raise ValueError('The partial path is a symlink; choose another destination.')
        if temp.exists():temp.unlink()
        self._update(i,state='Queued',downloaded=0,total=None,resumable=0,validator=None,error='');self.log(f'DownloadRetry id={i}');self._pump()
    def remove(self,i):
        row=self.get(i)
        if not row or row['state'] not in {'Completed','Failed','Cancelled'} or i==self.active:return
        with self.db.connection:self.db.connection.execute('DELETE FROM downloads WHERE id=?',(i,))
        self.changed.emit(i)
    def _pump(self):
        if self.closed or self.active is not None:return
        row=self.db.connection.execute("SELECT * FROM downloads WHERE state='Queued' ORDER BY id LIMIT 1").fetchone()
        if not row:return
        job=dict(row);self.active=job['id'];self.speed=0;self._generation+=1;job['generation']=self._generation;self._cancel=threading.Event();self._reason='Cancelled';self._update(self.active,state='Downloading',error='')
        self._thread=threading.Thread(target=self._run,args=(job,self._cancel),name='AniVaultDownload',daemon=True);self._thread.start()
    def _emit(self,job,**payload):
        if self.closed:return
        try:self._received.emit({'id':job['id'],'generation':job['generation'],**payload})
        except RuntimeError:pass
    def _run(self,job,cancel):
        target=Path(job['target']);temp=Path(job['temp']);downloaded=int(job['downloaded']);total=job['total'];validator=job['validator'];resumable=bool(job['resumable']);start=time.monotonic();last=start;initial=downloaded
        try:
            if target.exists() or target.is_symlink() or temp.is_symlink():raise ValueError('Destination collision or unsafe partial-file path.')
            if downloaded and (not temp.is_file() or temp.stat().st_size!=downloaded):raise ValueError('Partial file changed or is missing. Retry starts over.')
            headers={'User-Agent':'AniVault/0.8.7','Accept-Encoding':'identity'}
            if downloaded:
                if not resumable or not validator:raise ValueError('Safe resumption is unavailable. Retry starts over.')
                headers.update({'Range':f'bytes={downloaded}-','If-Range':validator})
            self._emit(job,event='started')
            with urllib.request.urlopen(urllib.request.Request(safe_url(job['url']),headers=headers),timeout=5) as response:
                safe_url(response.geturl());code=response.status
                current_validator=response.headers.get('ETag') or response.headers.get('Last-Modified')
                if current_validator and current_validator.startswith('W/'):current_validator=response.headers.get('Last-Modified')
                if downloaded:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if code!=206 or not match or int(match[1])!=downloaded:raise ValueError('Server ignored or returned an invalid Range. Retry starts over.')
                    if current_validator!=validator:raise ValueError('Remote file changed. Retry starts over.')
                    total=int(match[3])
                else:
                    if code!=200:raise ValueError('Unexpected HTTP status '+str(code))
                    length=response.headers.get('Content-Length');total=int(length) if length else None
                resumable=bool(current_validator and (response.headers.get('Accept-Ranges','').lower()=='bytes' or code==206));validator=current_validator
                self._emit(job,event='response',http=code,total=total,resumable=int(resumable),validator=validator)
                if cancel.is_set():self._emit(job,event='stopped',downloaded=downloaded,total=total);return
                # Exclusive creation prevents taking over an unrelated partial.
                with temp.open('ab' if downloaded else 'xb') as output:
                    while not cancel.is_set():
                        chunk=response.read(65536)
                        if not chunk:break
                        output.write(chunk);downloaded+=len(chunk)
                        now=time.monotonic()
                        if now-last>=.3:
                            self._emit(job,event='progress',downloaded=downloaded,total=total,speed=(downloaded-initial)/max(.01,now-start));last=now
                    output.flush();os.fsync(output.fileno())
            if cancel.is_set():self._emit(job,event='stopped',downloaded=downloaded,total=total);return
            if total is not None and downloaded!=total:raise ValueError('Incomplete response: size does not match Content-Length.')
            if total is None:total=downloaded
            if cancel.is_set():self._emit(job,event='stopped',downloaded=downloaded,total=total);return
            # Never overwrite a colliding final file, including a race with another app.
            if os.name=='nt':os.rename(temp,target)
            else:os.link(temp,target);temp.unlink()
            # A separate, short-lived SQLite connection records finalization even
            # if the UI has closed before its queued completion signal arrives.
            # It only touches this queue row, never anime/manga state.
            with closing(sqlite3.connect(self._db_path,timeout=3)) as connection:
                with connection:connection.execute("UPDATE downloads SET state='Completed',downloaded=?,total=?,error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(downloaded,total,job['id']))
            self._emit(job,event='completed',downloaded=downloaded,total=total)
        except Exception as exc:
            if cancel.is_set():self._emit(job,event='stopped',downloaded=downloaded,total=total)
            else:self._emit(job,event='failed',downloaded=downloaded,total=total,error=f'{type(exc).__name__}: {str(exc).split("?")[0]}')
    def _on_received(self,payload):
        if self.closed or payload['id']!=self.active or payload['generation']!=self._generation:return
        i=payload['id'];event=payload['event'];values={key:payload[key] for key in ('downloaded','total','resumable','validator','error') if key in payload}
        if event=='stopped':values['state']=self._reason
        elif event=='completed':values['state']='Completed'
        elif event=='failed':values['state']='Failed'
        self.speed=float(payload.get('speed') or 0)
        if values:self._update(i,**values)
        if event!='progress':self.log(f'Download id={i} event={event} http={payload.get("http")} bytes={payload.get("downloaded")} total={payload.get("total")} range={payload.get("resumable")} error={payload.get("error","")}')
        if event in {'stopped','completed','failed'}:self.active=None;self._pump()
    def shutdown(self):
        if self.closed:return
        self.closed=True
        if self._cancel:self._cancel.set()
        if self.active:
            # Disk length is reconciled again on restart. No waiting for network I/O.
            row=self.get(self.active);size=row['downloaded']
            with self.db.connection:self.db.connection.execute("UPDATE downloads SET state='Paused',downloaded=?,error='Paused on application shutdown.' WHERE id=? AND state!='Completed'",(size,self.active))
            self.changed.emit(self.active)
