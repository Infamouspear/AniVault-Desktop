"""Deterministic API accounting, shared budget and restart-safe scanner jobs."""
import io,json,threading,time,urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest
from anime_hub.anilist_transport import Scheduler,Deferred,request_context,configure
from anime_hub.metadata import AniListClient
from anime_hub.database import Database
from anime_hub.scanner import scan
from anime_hub import metadata_jobs as jobs
from anime_hub import scan_state
from test_cross_media import window

class Response(io.BytesIO):
    status=200
    def __init__(self,payload,headers=None):super().__init__(json.dumps(payload).encode());self.headers=headers or {}

def body(items=()):return {'data':{'Page':{'media':list(items)}}}

def anime(identifier=1,title='Example Saga'):
    return {'id':identifier,'type':'ANIME','isAdult':False,'format':'TV','title':{'english':title},'coverImage':{}}

def make_source(tmp_path,title='Example Saga S01'):
    root=tmp_path/'Anime';folder=root/title;folder.mkdir(parents=True);(folder/'S01E01.mkv').write_bytes(b'episode')
    return root,Database(tmp_path/'vault.db')

def zero_scheduler(tmp_path,monkeypatch,clock=None):
    scheduler=Scheduler(tmp_path/'api',clock=clock or time.time,min_interval=0)
    from anime_hub import anilist_transport as transport
    monkeypatch.setattr(transport,'configure',lambda directory,scheduler_override=None:scheduler)
    monkeypatch.setattr(transport,'get_scheduler',lambda:scheduler)
    return scheduler


def test_duplicate_consumers_share_one_inflight_request_and_cache(tmp_path):
    scheduler=Scheduler(tmp_path/'api',min_interval=0);entered=threading.Event();release=threading.Event();calls=[]
    def network(*args,**kwargs):calls.append(1);entered.set();release.wait(3);return Response(body([anime()]))
    with patch('urllib.request.urlopen',side_effect=network),ThreadPoolExecutor(max_workers=2) as workers:
        first=workers.submit(scheduler.request,'query($search:String){Page{media{id}}}',{'search':'same'},origin='scanner')
        assert entered.wait(2)
        second=workers.submit(scheduler.request,'query($search:String){Page{media{id}}}',{'search':'same'},origin='discover')
        deadline=time.monotonic()+2
        while scheduler.snapshot()['counts'].get('coalesced',0)==0 and time.monotonic()<deadline:time.sleep(.01)
        release.set();assert first.result().payload==second.result().payload
    assert len(calls)==1
    restored=Scheduler(tmp_path/'api',min_interval=0)
    with patch('urllib.request.urlopen',side_effect=AssertionError('Cached search repeated')):
        assert restored.request('query($search:String){Page{media{id}}}',{'search':'same'}).cached


def test_budget_headers_and_retry_after_apply_to_every_feature(tmp_path):
    now=[100.0];scheduler=Scheduler(tmp_path/'api',clock=lambda:now[0],min_interval=0)
    error=urllib.error.HTTPError('https://graphql.anilist.co',429,'Rate limit',{'Retry-After':'30','X-RateLimit-Limit':'2','X-RateLimit-Remaining':'0','X-RateLimit-Reset':'135'},None)
    with patch('urllib.request.urlopen',side_effect=[error,Response(body(),{'X-RateLimit-Limit':'60','X-RateLimit-Remaining':'59'})]) as network:
        with pytest.raises(Deferred) as caught:scheduler.request('query{one}',origin='scanner',wait=False)
        assert caught.value.retry_at==135
        now[0]=134
        with pytest.raises(Deferred):scheduler.request('query{two}',origin='airing',wait=False)
        assert network.call_count==1
        now[0]=161
        assert scheduler.request('query{two}',origin='airing',wait=False).status==200
    assert scheduler.limit==60
    restored=Scheduler(tmp_path/'api',clock=lambda:162,min_interval=0);assert restored.limit==60


def test_http_date_retry_after_and_no_header_default_are_bounded(tmp_path):
    scheduler=Scheduler(clock=lambda:100,min_interval=0)
    scheduler._observe({'Retry-After':'Thu, 01 Jan 1970 00:02:00 GMT'},429)
    assert scheduler.blocked_until==120
    scheduler._observe({},429,retry=2);assert scheduler.blocked_until==120


def test_cancelled_budget_wait_is_prompt_and_leaves_no_ticket():
    scheduler=Scheduler(min_interval=0);scheduler.blocked_until=time.time()+60
    with pytest.raises(Deferred) as caught:scheduler.request('query{x}',cancel=lambda:True)
    assert caught.value.kind=='cancelled' and not scheduler.tickets and not scheduler.active


def test_normal_cache_and_diagnostics_never_contain_private_metadata_or_token(tmp_path):
    scheduler=Scheduler(tmp_path/'api',min_interval=0)
    secret={**anime(99,'SECRET PRIVATE TITLE'),'isAdult':True}
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(),secret]))):
        result=scheduler.request('query{Page{media{id title{english} isAdult}}}')
    assert len(result.payload['data']['Page']['media'])==1
    assert b'SECRET PRIVATE TITLE' not in (tmp_path/'api'/'normal'/'requests.sqlite3').read_bytes()
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response({'data':{'Viewer':{'id':4}}})):
        scheduler.request('query{Viewer{id}}',token='SECRET_TOKEN')
    assert 'SECRET_TOKEN' not in json.dumps(scheduler.snapshot())


def test_local_indexing_finishes_with_no_api_and_negative_matches_skip_rescans(tmp_path,monkeypatch):
    now=[1000.0];scheduler=zero_scheduler(tmp_path,monkeypatch,lambda:now[0]);root,db=make_source(tmp_path)
    with patch('urllib.request.urlopen',side_effect=AssertionError('Local scan contacted AniList')):assert scan(root,db,match_online=False)==1
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body())) as network:
        jobs.process(db,scheduler=scheduler,max_jobs=100)
        first=network.call_count;assert first>0
        scan(root,db,match_online=False);jobs.process(db,scheduler=scheduler,max_jobs=100)
        assert network.call_count==first
        db.connection.close();db=Database(tmp_path/'vault.db')
        scan(root,db,match_online=False);jobs.process(db,scheduler=scheduler,max_jobs=100)
        assert network.call_count==first
    assert jobs.summary(db)['unresolved']==1
    now[0]+=86401
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(10)]))) as retry:
        jobs.process(db,scheduler=scheduler);assert retry.call_count>0 and db.anime_list()[0]['anilist_id']==10
    db.connection.close()


def test_success_and_manual_match_survive_restart_without_search(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path)
    scan(root,db,match_online=False)
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(10)]))) as network:
        jobs.process(db,scheduler=scheduler);assert network.call_count==1
    assert db.connection.execute('SELECT batches FROM metadata_job_metrics').fetchone()[0]==1
    aid=db.anime_list()[0]['id'];mid=db.media(aid)[0]['id'];db.set_watched(mid,True);db.set_resume_position(mid,5000);db.set_personal_rating('ANIME',aid,8);db.set_favorite(aid,True)
    scan_state.manual_match(db,aid,anime(20,'Manual identity'))
    db.connection.close();db=Database(tmp_path/'vault.db')
    with patch('urllib.request.urlopen',side_effect=AssertionError('Completed/manual job repeated')):
        scan(root,db,match_online=False);jobs.process(db,scheduler=scheduler)
    assert db.anime(aid)['anilist_id']==20 and db.media(aid)[0]['watched'] and db.media(aid)[0]['resume_position_ms']==5000 and db.personal_rating('ANIME',aid)==16 and db.anime(aid)['favorite']
    scan_state.manual_match(db,aid,clear=True)
    with patch('urllib.request.urlopen',side_effect=AssertionError('A valid cached identity should be reusable')):jobs.process(db,scheduler=scheduler)
    assert db.anime(aid)['anilist_id']==10 and db.media(aid)[0]['watched']
    db.connection.close()


def test_pending_rate_limit_job_resumes_without_local_rediscovery(tmp_path,monkeypatch):
    now=[1000.0];scheduler=zero_scheduler(tmp_path,monkeypatch,lambda:now[0]);root,db=make_source(tmp_path);scan(root,db,match_online=False)
    error=urllib.error.HTTPError('https://graphql.anilist.co',429,'Limit',{'Retry-After':'20'},None)
    with patch('urllib.request.urlopen',side_effect=error) as network:jobs.process(db,scheduler=scheduler);assert network.call_count==1
    before=[tuple(r) for r in db.connection.execute('SELECT * FROM media')];db.connection.close();db=Database(tmp_path/'vault.db')
    now[0]=1021;scheduler.sent.clear()
    with patch('anime_hub.scanner.discover_series_roots',side_effect=AssertionError('Metadata rediscovered local folders')),patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(10)]))):jobs.process(db,scheduler=scheduler)
    assert db.anime_list()[0]['anilist_id']==10 and before==[tuple(r) for r in db.connection.execute('SELECT * FROM media')]
    db.connection.close()


def test_offline_queue_uses_shared_transient_backoff_instead_of_all_titles(tmp_path,monkeypatch):
    now=[1000.0];scheduler=zero_scheduler(tmp_path,monkeypatch,lambda:now[0]);root,db=make_source(tmp_path)
    second=root/'Another Saga';second.mkdir();(second/'S01E01.mkv').touch();scan(root,db,match_online=False)
    with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('offline')) as network:
        jobs.process(db,scheduler=scheduler,max_jobs=100);jobs.process(db,scheduler=scheduler,max_jobs=100)
        assert network.call_count==1
    assert jobs.summary(db)['pending']==2 and jobs.next_due(db,scheduler)>=1060
    db.connection.close()


def test_changed_identity_enqueues_one_new_revision_not_duplicates(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path)
    scan(root,db,match_online=False)
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body())):jobs.process(db,scheduler=scheduler)
    aid=db.anime_list()[0]['id'];old=db.connection.execute('SELECT revision FROM metadata_jobs').fetchone()[0]
    (root/'Example Saga S01').rename(root/'Changed Saga S02');scan(root,db,match_online=False)
    row=db.connection.execute('SELECT * FROM metadata_jobs').fetchone()
    assert row['revision']==old+1 and row['state']=='pending' and len(db.anime_list())==1 and db.anime_list()[0]['id']==aid
    scan(root,db,match_online=False);assert db.connection.execute('SELECT count(*) FROM metadata_jobs').fetchone()[0]==1
    db.connection.close()


def test_missing_artwork_never_restarts_title_search(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path)
    scan(root,db,match_online=False)
    item={**anime(10),'coverImage':{'large':'https://example.org/cover.jpg'}}
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([item]))),patch('anime_hub.metadata.cache_artwork',side_effect=OSError('image offline')):jobs.process(db,scheduler=scheduler,max_jobs=10)
    assert db.anime_list()[0]['anilist_id']==10
    with patch('anime_hub.metadata.lookup_anilist',side_effect=AssertionError('Artwork triggered identification')),patch('anime_hub.metadata.cache_artwork',side_effect=OSError('image offline')):
        scan(root,db,match_online=False);jobs.process(db,scheduler=scheduler)
    assert db.connection.execute("SELECT count(*) FROM metadata_jobs WHERE operation='identify'").fetchone()[0]==1
    db.connection.close()


def test_restricted_sources_do_not_enter_normal_metadata_queue(tmp_path):
    root,db=make_source(tmp_path);aid=db.upsert_anime('private','Private','','Other',str(root/'Private'));db.set_metadata(aid,99,{**anime(99,'Private'),'isAdult':True})
    assert not jobs.enqueue(db,aid,{'title':'Private'},[])
    assert jobs.enqueue_existing(db)==0
    assert jobs.summary(db)['pending']==0
    db.connection.close()


def test_graphql_and_match_client_use_same_scheduler(isolated_anilist_transport):
    from anime_hub.anilist_integration import graphql
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(1)]))):
        graphql('query{Page{media{id}}}');AniListClient().lookup('Example Saga')
    snapshot=isolated_anilist_transport.snapshot();assert snapshot['counts']['request']==2


def test_worker_is_singleton_and_review_shows_separate_progress(window,monkeypatch):
    w,qt,aid,*_=window
    from anime_hub.scanner_review import ScannerReview
    review=ScannerReview(w,anime_id=aid);assert 'Local Library Scan:' in review.queue_status.text() and 'AniList Metadata Matching:' in review.queue_status.text()
    jobs.enqueue(w.db,aid,{'title':'Example Saga'},[]);w.db.connection.commit()
    monkeypatch.setattr(jobs,'process',lambda db,**kwargs:{'processed':0,'applied':0})
    w.pause_metadata_jobs();assert jobs.summary(w.db)['paused'];w.resume_metadata_jobs(manual=True);assert not jobs.summary(w.db)['paused']
    worker=w.metadata_worker;assert worker is not None and worker.isRunning()
    w.resume_metadata_jobs();assert w.metadata_worker is worker
    review.close()


def test_manual_request_has_priority_over_waiting_background_refresh(tmp_path):
    scheduler=Scheduler(min_interval=0);scheduler.active=True;order=[]
    def network(request,**kwargs):order.append(json.loads(request.data)['query']);return Response(body())
    with patch('urllib.request.urlopen',side_effect=network),ThreadPoolExecutor(max_workers=2) as workers:
        low=workers.submit(scheduler.request,'query{background}',priority=50)
        deadline=time.monotonic()+2
        while len(scheduler.tickets)<1 and time.monotonic()<deadline:time.sleep(.01)
        high=workers.submit(scheduler.request,'query{manual}',priority=0)
        while len(scheduler.tickets)<2 and time.monotonic()<deadline:time.sleep(.01)
        with scheduler.condition:scheduler.active=False;scheduler.condition.notify_all()
        high.result(timeout=3);low.result(timeout=3)
    assert order==['query{manual}','query{background}']


def test_real_graphql_cooldown_blocks_match_client_from_another_feature(isolated_anilist_transport):
    from anime_hub.anilist_integration import graphql
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime()]),{'X-RateLimit-Limit':'1','X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(time.time()+60)})) as network:
        graphql('query{one}')
        report=AniListClient(wait=False).lookup('Example Saga')
        assert report.rate_limited and network.call_count==1


def test_transient_backoff_grows_and_success_clears_it(tmp_path):
    now=[1000.0];scheduler=Scheduler(tmp_path/'api',clock=lambda:now[0],min_interval=0)
    with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('offline')):
        with pytest.raises(Deferred) as first:scheduler.request('query{first}',wait=False)
        assert first.value.retry_at==1060
        now[0]=1061
        with pytest.raises(Deferred) as second:scheduler.request('query{second}',wait=False)
        assert second.value.retry_at==1181
    now[0]=1182
    with patch('urllib.request.urlopen',return_value=Response(body())):scheduler.request('query{good}',wait=False)
    assert scheduler.error_streak==0


def test_timeouts_and_invalid_responses_are_distinct_and_deferred(tmp_path):
    now=[1000.0];scheduler=Scheduler(tmp_path/'api',clock=lambda:now[0],min_interval=0)
    with patch('urllib.request.urlopen',side_effect=TimeoutError()):
        with pytest.raises(Deferred) as caught:scheduler.request('query{timeout}',wait=False)
        assert caught.value.kind=='timeout'
    now[0]=1061
    with patch('urllib.request.urlopen',return_value=Response({'data':None})):
        with pytest.raises(Deferred) as caught:scheduler.request('query{invalid}',wait=False)
        assert caught.value.kind=='invalid_response' and caught.value.retry_at==1361


def test_dead_worker_job_is_recovered_without_duplicate_rows(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path);scan(root,db,match_online=False)
    with db.connection:db.connection.execute("UPDATE metadata_jobs SET state='running',owner=99999999,lease_until=?",(time.time()+3600,))
    jobs.recover(db)
    assert db.connection.execute('SELECT state FROM metadata_jobs').fetchone()[0]=='pending'
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response(body([anime(10)]))):jobs.process(db,scheduler=scheduler)
    assert db.connection.execute('SELECT count(*) FROM metadata_jobs').fetchone()[0]==1 and db.anime_list()[0]['anilist_id']==10
    db.connection.close()


def test_upgrade_reuses_recent_negative_report_without_reindexing(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path);scan(root,db,match_online=False)
    aid=db.anime_list()[0]['id'];mid=db.media(aid)[0]['id'];db.set_resume_position(mid,4500)
    scan_state.record(db,aid,state='Unmatched',method='automatic',report={'query':'Example Saga','candidates':[],'network_error':False,'reason':'No candidates'})
    with db.connection:db.connection.execute('DROP TABLE metadata_jobs')
    db.connection.close();db=Database(tmp_path/'vault.db')
    assert jobs.summary(db)['unresolved']==1 and jobs.summary(db)['pending']==0
    with patch('urllib.request.urlopen',side_effect=AssertionError('Upgrade repeated a recent failed search')):jobs.process(db,scheduler=scheduler)
    assert db.media(aid)[0]['id']==mid and db.media(aid)[0]['resume_position_ms']==4500
    db.connection.close()


def test_blank_metadata_uses_confirmed_id_instead_of_title_search(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root,db=make_source(tmp_path);scan(root,db,match_online=False)
    aid=db.anime_list()[0]['id'];scan_state.manual_match(db,aid,{'id':10,'isAdult':False,'type':'ANIME','title':{}})
    jobs.enqueue_existing(db)
    with patch('anime_hub.metadata.lookup_anilist',side_effect=AssertionError('A known ID triggered title search')),patch('urllib.request.urlopen',return_value=Response({'data':{'Media':anime(10)}})) as network:
        jobs.process(db,scheduler=scheduler);assert network.call_count==1
    assert db.anime(aid)['anilist_id']==10 and scan_state.source_state(db,aid)['locked']
    assert json.loads(db.anime(aid)['metadata_json'])['title']['english']=='Example Saga'
    db.connection.close()


def test_aggregate_ova_pack_does_not_search_every_numbered_episode(tmp_path,monkeypatch):
    scheduler=zero_scheduler(tmp_path,monkeypatch);root=tmp_path/'Anime';pack=root/'Example Saga Complete Series + OVAs, Specials'
    for i in range(1,5):
        folder=pack/'Season 1';folder.mkdir(parents=True,exist_ok=True);(folder/f'Example Saga - {i:02}.mkv').touch()
    (pack/'Example Saga OVA - New Adventure.mkv').touch();db=Database(tmp_path/'vault.db')
    scan(root,db,match_online=False)
    assert sum(len(db.media(r['id'])) for r in db.anime_list())==5
    queued=db.connection.execute("SELECT payload FROM metadata_jobs WHERE operation='identify' AND state<>'completed'").fetchall()
    assert len(queued)==1 and 'New Adventure' in json.loads(queued[0][0])['title']
    assert db.connection.execute("SELECT count(*) FROM scan_file_matches WHERE state='Part of parent release'").fetchone()[0]==4
    db.connection.close()


def test_structural_labels_do_not_consume_api_requests():
    with patch('urllib.request.urlopen',side_effect=AssertionError('Generic labels must not hit AniList')):
        for title in ('OVA','Movies','Specials','Unknown Anime','Season 2'):
            report=AniListClient(wait=False).lookup(title);assert not report.selected and not report.requests


def test_franchise_detail_relations_use_the_existing_bounded_queue(window,monkeypatch):
    from PySide6.QtWidgets import QLabel
    from anime_hub import app
    w,qt,*_=window;pending=[];results=[];session='test';w.current_view='franchise_detail';w._franchise_session=session
    monkeypatch.setattr(w,'_submit_discover_job',lambda *args:pending.append(args))
    monkeypatch.setattr(app,'AniListWorker',lambda *args:(_ for _ in ()).throw(AssertionError('A separate relation worker was created')))
    label=QLabel();w._request_franchise_relations([11,12],session,results.append,label);w._request_franchise_relations([11,12],session,results.append,label)
    assert len(pending)==1
    pending[0][2]([{**anime(12),'sourceAniListId':11,'relationType':'SEQUEL'}]);assert results
