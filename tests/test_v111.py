"""Stability regressions with synthetic libraries only."""
import http.client
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton
from anime_hub import app
from anime_hub.database import Database
from anime_hub.integrated_player import IntegratedPlayer, ThumbnailWorker
from anime_hub.lan_auth import APIError, PairingStore, SESSION_SECONDS
from anime_hub.lan_catalog import Catalog, snapshot
from anime_hub.lan_server import LANServer
from anime_hub.organization import Organization
from test_cross_media import window, anime, remote
from test_lan import vault, request


def cards(w):
    QTest.qWait(50)
    return [c for c in w.stack.currentWidget().findChildren(app.Card) if c.isVisible()]


def test_general_library_other_classification_and_alternate_views(window,tmp_path):
    w,qt,aid,*_=window
    private=anime(w.db,tmp_path/'Unrelated folder',77,True)
    w.db.set_favorite(private,True)
    w.show_library(view_mode='Individual Titles')
    assert {c.anime_id for c in cards(w)}=={aid}
    w.show_library(state_filter='Favorites',view_mode='Individual Titles')
    assert not cards(w)
    w.show_global_search('Shared 77')
    assert not cards(w)
    current=w.stack.currentWidget()
    w.show_detail(private)
    assert w.stack.currentWidget() is current
    episode=w.db.media(private)[0]
    assert not w._local_anime_allowed(private,episode['id'],episode['path'])
    w.mark_episode(private,episode['id'],True)
    assert not w.db.media_by_id(episode['id'])['watched']
    w.db.set_setting('restricted_unlocked','1')
    assert w._local_anime_allowed(private,episode['id'],episode['path'])
    w.show_detail(private)
    assert w.current_view=='restricted_anime_detail'


def test_cached_legacy_metadata_ecchi_unmatched_and_changes(window):
    w,qt,aid,*_=window
    original=dict(w.db.anime(aid))
    w.db.set_metadata(aid,11,{'id':11,'genres':['Ecchi'],'title':{'english':'Kept'}})
    assert w.db.anime_scope(aid)=='normal'
    w.db.save_title(remote(11,adult=True),'restricted')
    assert w.db.anime_scope(aid)=='restricted'
    assert not Organization(w.db,w.manga_store,'normal').resolve('local:'+str(aid))
    assert w.db.observe_classifications([remote(11,adult=False)])==1
    assert w.db.anime_scope(aid)=='normal'
    w.db.set_resume_position(w.db.media(aid)[0]['id'],1234)
    assert w.db.observe_classifications([remote(11,adult=True)])==1
    assert w.db.anime_scope(original)=='restricted'  # Stale row cannot bypass reclassification.
    assert w.db.media(aid)[0]['resume_position_ms']==1234
    w.db.set_metadata(aid,None,{'genres':['Ecchi']})
    assert w.db.anime_scope(aid)=='normal'  # No title-text guessing or broad Ecchi rule.


def test_scan_connection_changes_invalidate_library_and_organization(window):
    w,qt,aid,*_=window
    w.show_library(view_mode='Individual Titles');assert len(cards(w))==1
    assert w.organization('normal').resolve('local:'+str(aid))
    other=Database(w.db_path)
    other.set_metadata(aid,11,remote(11,adult=True));other.connection.close()
    w.show_library(view_mode='Individual Titles');assert not cards(w)
    assert w.organization('normal').resolve('local:'+str(aid)) is None


def test_restricted_discovery_opens_shared_local_episode_view(window,tmp_path):
    w,qt,*_=window
    aid=anime(w.db,tmp_path/'Private',77,True)
    episode=w.db.media(aid)[0]
    w.db.set_setting('restricted_unlocked','1')
    w.show_remote_anilist(remote(77,adult=True),'Restricted')
    assert w.current_view=='restricted_anime_detail' and w.current_anime_id==aid
    assert any(lst.item(i).data(Qt.UserRole+1)==episode['id'] for lst in w.stack.currentWidget().findChildren(QListWidget) for i in range(lst.count()))
    w.lock_restricted();prior=w.stack.currentWidget()
    w.show_remote_anilist(remote(77,adult=True),'Restricted')
    assert w.stack.currentWidget() is prior


def test_normal_discovery_cannot_open_stale_private_match(window,tmp_path):
    w,qt,*_=window
    aid=anime(w.db,tmp_path/'Private',77,True)
    current=w.stack.currentWidget()
    w.show_remote_anilist(remote(77,adult=False),'Discover')
    assert w.stack.currentWidget() is current


@pytest.mark.parametrize('suffix', ['', '/episodes', '/progress', '/artwork/poster'])
def test_exact_private_title_id_is_intentionally_filtered(vault,suffix):
    assert request(vault,f'/api/v1/anime/{vault.secret}'+suffix)[0]==404
    assert request(vault,f'/api/v1/restricted/anime/{vault.secret}'+suffix)[0]==403
    vault.auth.set_open(True);vault.auth.grant(vault.token['device_id'])
    assert request(vault,f'/api/v1/restricted/anime/{vault.secret}'+suffix)[0]==200


def test_private_progress_media_and_art_reclassified_from_cache(vault):
    row=vault.db.media(vault.normal)[0]
    info=json.loads(vault.db.anime(vault.normal)['metadata_json']);info.pop('isAdult')
    vault.db.set_metadata(vault.normal,10,info)
    vault.db.save_title(remote(10,adult=True),'restricted')
    assert request(vault,f'/api/v1/media/{row["id"]}')[0]==404
    assert request(vault,f'/api/v1/media/{row["id"]}/progress')[0]==404
    assert request(vault,f'/api/v1/anime/{vault.normal}/artwork/poster')[0]==404
    assert b'Show' not in request(vault,'/api/v1/anime')[2]
    catalog=Catalog(vault.db,vault.manga,'normal',vault.tmp)
    with pytest.raises(APIError):catalog.media(row['id'])


def test_cookie_expiry_session_restart_dedup_and_revocation(vault):
    code=vault.auth.new_code()
    status,headers,body=request(vault,'/pair','POST',{'code':code,'name':'Phone'},authenticated=False)
    assert status==200 and 'Max-Age=' in headers['Set-Cookie'] and 'Expires=' in headers['Set-Cookie']
    cookie=headers['Set-Cookie'].split(';',1)[0]
    token=json.loads(body)
    second=request(vault,'/api/v1/session',headers={'Cookie':cookie},authenticated=False)
    assert second[0]==200 and json.loads(second[2])['name']=='Phone'
    assert 'Max-Age=' in second[1]['Set-Cookie']
    assert json.loads(second[2])['expires_at']==token['expires_at']
    reloaded=PairingStore(vault.auth.path)
    vault.server.auth=reloaded
    assert request(vault,'/api/v1/session',headers={'Cookie':cookie},authenticated=False)[0]==200
    count=len(reloaded.devices)
    code=reloaded.new_code()
    response=request(vault,'/pair','POST',{'code':code,'name':'Same Phone'},headers={'Cookie':cookie},authenticated=False)
    assert json.loads(response[2])['device_id']==token['device_id'] and len(reloaded.devices)==count
    assert json.loads(response[2])['expires_at']==token['expires_at']  # Never sliding expiry.
    reloaded.revoke(token['device_id'])
    assert request(vault,'/api/v1/session',headers={'Cookie':cookie},authenticated=False)[0]==401
    media=vault.db.media(vault.normal)[0]
    assert request(vault,f'/api/v1/media/{media["id"]}',headers={'Cookie':cookie},authenticated=False)[0]==401


def test_legacy_tokens_upgrade_without_rotation_and_expire(vault):
    record=vault.auth.devices[vault.token['device_id']]
    record.pop('expires_at')
    vault.auth._save()
    reloaded=PairingStore(vault.auth.path)
    identity=reloaded.authenticate(vault.token['token'])
    assert reloaded.devices[identity]['expires_at']==record['paired_at']+SESSION_SECONDS
    reloaded.devices[identity]['expires_at']=time.time()-1
    with pytest.raises(APIError,match='session_expired'):reloaded.authenticate(vault.token['token'])
    with pytest.raises(APIError,match='session_expired'):reloaded.check(identity,'normal')


def test_lifecycle_occupied_port_status_and_restart(vault):
    assert vault.server.status_info()['state']=='Running'
    occupied=LANServer(vault.db.path,vault.tmp,vault.auth,lambda *args:None)
    with pytest.raises(OSError):occupied.start('127.0.0.1',vault.server.http.server_address[1])
    assert occupied.status_info()['state']=='Error' and occupied.status_info()['error']
    port=vault.server.http.server_address[1]
    vault.server.stop();assert vault.server.status_info()['state']=='Stopped'
    vault.server.start('127.0.0.1',port)
    assert vault.server.status_info()['state']=='Running' and request(vault)[0]==200


def test_concurrent_ranges_and_interrupted_client(vault):
    row=vault.db.media(vault.normal)[0]
    def retrieve(i):return request(vault,f'/api/v1/media/{row["id"]}',headers={'Range':f'bytes={i*64}-{i*64+63}'})
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(retrieve,range(12)))
    assert all(status==206 and len(body)==64 for status,headers,body in results)
    connection=http.client.HTTPConnection('127.0.0.1',vault.server.http.server_address[1])
    connection.request('GET',f'/api/v1/media/{row["id"]}',headers={'Authorization':'Bearer '+vault.token['token']})
    response=connection.getresponse();response.read(1);connection.close()
    assert request(vault)[0]==200


def test_get_progress_roundtrip_and_restart(window):
    w,qt,aid,*_=window
    with socket.socket() as available:available.bind(('127.0.0.1',0));port=available.getsockname()[1]
    w.lan_server.start('127.0.0.1',port)
    for _ in range(100):
        QTest.qWait(15)
        if not w.lan_server.busy:break
    token=w.lan_server.auth.pair(w.lan_server.auth.new_code(),'State client','127.0.0.1')
    client=SimpleNamespace(server=w.lan_server.server,token=token)
    media=w.db.media(aid)[0];route=f'/api/v1/media/{media["id"]}/progress'
    for body in [{'position_ms':555},{'watched':True},{'watched':False,'position_ms':1234}]:
        result=[]
        thread=threading.Thread(target=lambda:result.append(request(client,route,'PUT',body)))
        thread.start()
        for _ in range(400):
            QTest.qWait(10)
            if not thread.is_alive():break
        thread.join(1);assert result[0][0]==200
        assert request(client,route)[0]==200
    assert json.loads(request(client,route)[2])['resume_position_ms']==1234
    assert request(client,route,authenticated=False)[0]==401
    assert request(client,'/api/v1/media/999999/progress')[0]==404
    reopened=Database(w.db_path)
    assert reopened.media_by_id(media['id'])['resume_position_ms']==1234
    reopened.connection.close()
    w.lan_server.stop()
    for _ in range(100):
        QTest.qWait(15)
        if not w.lan_server.busy:break
    w.lan_server.start('127.0.0.1',port)
    for _ in range(100):
        QTest.qWait(15)
        if not w.lan_server.busy:break
    assert json.loads(request(client,route)[2])['resume_position_ms']==1234


def test_thumbnail_subprocess_hides_console_on_windows(monkeypatch):
    from anime_hub import integrated_player as player_module
    calls=[]
    monkeypatch.setattr(player_module.subprocess,'run',lambda *args,**kwargs:(calls.append(kwargs) or SimpleNamespace(returncode=1,stdout=b'')))
    worker=ThumbnailWorker('ffmpeg','synthetic.mp4',1000);worker.run()
    if player_module.sys.platform=='win32':assert calls[0]['creationflags'] & player_module.subprocess.CREATE_NO_WINDOW


def test_failed_thumbnail_has_backoff_and_hover_does_not_spawn_excessively(monkeypatch):
    from anime_hub import integrated_player as module
    player=IntegratedPlayer(hover_previews=False);player._ffmpeg='synthetic-ffmpeg';player.path='missing.mp4';player.timeline.setMaximum(100000)
    calls=[]
    monkeypatch.setattr(module.subprocess,'run',lambda *args,**kwargs:(calls.append(args) or SimpleNamespace(returncode=1,stdout=b'')))
    player.show()
    for i in range(50):player._preview_hover(1000+i,30)
    QTest.qWait(500)
    for _ in range(5):player._request_preview();QTest.qWait(20)
    assert len(calls)==1
    player.stop();player.close()


def test_diagnostic_routes_have_selectors_progress_and_no_credential_display(vault):
    status,headers,html=request(vault,'/',authenticated=False)
    assert status==200 and b'Progress Testing' in html and b'id="title"' in html and b'id="episode"' in html
    script=request(vault,'/probe.js',authenticated=False)[2]
    assert b'/api/v1/media/' in script and b'/progress' in script and b'/api/v1/session' in script
    assert b'localStorage' not in script and b'JSON.stringify(data,null,2)' in script
