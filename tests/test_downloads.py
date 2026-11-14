import threading,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.downloads import Downloads,safe_url

DATA=bytes(range(256))*8192

def wait(qt,predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        qt.processEvents()
        if predicate():return
        QTest.qWait(10)
    raise AssertionError('Download did not reach expected state')

@pytest.fixture
def transfer(tmp_path):
    qt=QApplication.instance() or QApplication([]);requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            requests.append((self.path,self.headers.get('Range'),self.headers.get('If-Range')))
            if self.path=='/fail':self.send_error(503);return
            start=int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0])
            ranged=bool(start and self.path!='/ignore');offset=start if ranged else 0
            body=DATA[offset:]
            self.send_response(206 if ranged else 200)
            if self.path!='/unknown':self.send_header('Content-Length',str(len(body)))
            if self.path!='/no-range':self.send_header('Accept-Ranges','bytes');self.send_header('ETag','"fixture-v1"')
            if ranged:self.send_header('Content-Range',f'bytes {offset}-{len(DATA)-1}/{len(DATA)}')
            self.end_headers()
            try:
                for index in range(0,len(body),16384):
                    self.wfile.write(body[index:index+16384]);self.wfile.flush()
                    if self.path in {'/slow','/ignore','/no-range'}:time.sleep(.015)
                    if self.path=='/short' and index>=65536:break
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    db=Database(tmp_path/'queue.db');logs=[];manager=Downloads(db,logs.append)
    yield qt,db,manager,f'http://127.0.0.1:{server.server_port}',requests,logs
    manager.shutdown()
    if manager._thread:manager._thread.join(6)
    server.shutdown();server.server_close();db.connection.close()

def test_complete_queue_atomic_and_remove_records_only(transfer,tmp_path):
    qt,db,m,base,requests,logs=transfer;first=m.add(base+'/file',tmp_path/'first');second=m.add(base+'/file',tmp_path/'second')
    wait(qt,lambda:m.get(second)['state']=='Completed')
    assert (tmp_path/'first').read_bytes()==DATA==(tmp_path/'second').read_bytes()
    assert not (tmp_path/'first.part').exists()
    assert all(m.get(i)['downloaded']==len(DATA) for i in (first,second))
    assert len(requests)==2 and any('event=completed' in line for line in logs)
    m.remove(first);assert not m.get(first) and (tmp_path/'first').read_bytes()==DATA

def test_pause_resume_uses_verified_range(transfer,tmp_path):
    qt,db,m,base,requests,logs=transfer;i=m.add(base+'/slow',tmp_path/'resume')
    wait(qt,lambda:m.get(i)['resumable'] and m.get(i)['downloaded']>0)
    m.pause(i);wait(qt,lambda:m.get(i)['state']=='Paused')
    before=m.get(i)['downloaded'];assert 0<before<len(DATA)
    m.resume(i);wait(qt,lambda:m.get(i)['state']=='Completed')
    assert requests[1][1:]==(f'bytes={before}-','"fixture-v1"')
    assert (tmp_path/'resume').read_bytes()==DATA

def test_ignored_range_fails_without_corrupting_partial(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/ignore',tmp_path/'ignore')
    wait(qt,lambda:m.get(i)['downloaded']>0);m.pause(i);wait(qt,lambda:m.get(i)['state']=='Paused')
    partial=(tmp_path/'ignore.part').read_bytes();m.resume(i);wait(qt,lambda:m.get(i)['state']=='Failed')
    assert not (tmp_path/'ignore').exists() and (tmp_path/'ignore.part').read_bytes()==partial
    assert 'Range' in m.get(i)['error']

def test_no_range_cancel_and_retry(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/no-range',tmp_path/'cancel')
    wait(qt,lambda:m.get(i)['downloaded']>0)
    with pytest.raises(ValueError):m.pause(i)
    m.cancel(i);wait(qt,lambda:m.get(i)['state']=='Cancelled')
    assert not (tmp_path/'cancel').exists()
    m.retry(i);wait(qt,lambda:m.get(i)['state']=='Completed')
    assert (tmp_path/'cancel').read_bytes()==DATA

def test_http_failure_retry_then_success(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/fail',tmp_path/'failed');wait(qt,lambda:m.get(i)['state']=='Failed')
    assert '503' in m.get(i)['error'] and not (tmp_path/'failed').exists()
    db.connection.execute('UPDATE downloads SET url=? WHERE id=?',(base+'/file',i));db.connection.commit()
    m.retry(i);wait(qt,lambda:m.get(i)['state']=='Completed');assert (tmp_path/'failed').read_bytes()==DATA

@pytest.mark.parametrize('endpoint',['/unknown','/short'])
def test_unknown_size_or_truncated_response(transfer,tmp_path,endpoint):
    qt,db,m,base,*_=transfer;i=m.add(base+endpoint,tmp_path/'content')
    wait(qt,lambda:m.get(i)['state'] in {'Completed','Failed'})
    if endpoint=='/unknown':assert m.get(i)['state']=='Completed' and (tmp_path/'content').read_bytes()==DATA
    else:assert m.get(i)['state']=='Failed' and not (tmp_path/'content').exists()

def test_restart_recovery_and_nonblocking_shutdown(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/slow',tmp_path/'recover');wait(qt,lambda:m.get(i)['downloaded']>0)
    start=time.monotonic();m.shutdown();assert time.monotonic()-start<.25
    m._thread.join(6)
    reopened=Database(tmp_path/'queue.db');second=Downloads(reopened)
    try:
        assert second.get(i)['state']=='Paused' and second.get(i)['downloaded']==(tmp_path/'recover.part').stat().st_size
        second.resume(i);wait(qt,lambda:second.get(i)['state']=='Completed')
        assert (tmp_path/'recover').read_bytes()==DATA
    finally:second.shutdown();reopened.connection.close()

def test_missing_partial_and_completed_survive_restart(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/file',tmp_path/'done');wait(qt,lambda:m.get(i)['state']=='Completed')
    m.shutdown()
    db.connection.execute("INSERT INTO downloads(url,target,temp,state,downloaded,label) VALUES(?,?,?,'Downloading',100,'Missing')",(base+'/file',str(tmp_path/'missing'),str(tmp_path/'missing.part')));db.connection.commit()
    recovered=Downloads(db)
    assert recovered.get(i)['state']=='Completed' and recovered.rows()[0]['state']=='Failed';recovered.shutdown()

def test_collisions_and_url_validation(transfer,tmp_path):
    qt,db,m,base,*_=transfer;path=tmp_path/'keep';path.write_bytes(b'user-owned')
    with pytest.raises(ValueError):m.add(base+'/file',path)
    assert path.read_bytes()==b'user-owned'
    (tmp_path/'busy.part').write_bytes(b'not ours')
    with pytest.raises(ValueError):m.add(base+'/file',tmp_path/'busy')
    for url in ('file:///x','https://user:secret@example.com','javascript:alert(1)'):
        with pytest.raises(ValueError):safe_url(url)

def test_final_destination_race_never_overwrites(transfer,tmp_path):
    qt,db,m,base,*_=transfer;i=m.add(base+'/slow',tmp_path/'race');wait(qt,lambda:m.get(i)['downloaded']>0)
    (tmp_path/'race').write_bytes(b'unrelated');wait(qt,lambda:m.get(i)['state']=='Failed')
    assert (tmp_path/'race').read_bytes()==b'unrelated' and (tmp_path/'race.part').exists()
