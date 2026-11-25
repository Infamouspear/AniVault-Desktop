import json
import time
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel,QPushButton
from anime_hub.database import Database
from anime_hub.airing_updates import AiringUpdates,fetch_airing_updates
from anime_hub.app import Card
from test_cross_media import window,anime,remote

@pytest.fixture
def updates(tmp_path):
    db=Database(tmp_path/'vault.db');store=AiringUpdates(db)
    aid=anime(db,tmp_path/'seed-airing',91);db.set_metadata(aid,91,{**remote(91),'status':'RELEASING'})
    yield db,store
    db.connection.close()

def schedule(identifier=91,episode=8,at=1000,adult=False):
    return dict(mediaId=identifier,episode=episode,airingAt=at,media={**remote(identifier,adult=adult),'status':'RELEASING'})

def test_follow_schedule_boundary_dedup_reschedule_and_restart(updates,tmp_path):
    db,s=updates;item=schedule()['media'];assert s.set_follow(item,True)
    assert s.ingest([schedule(at=1001)],1000)==0
    assert s.ingest([schedule()],1000)==1
    assert s.ingest([schedule()],1000)==0
    s.mark(91,8);s.mark(91,8,True)
    assert s.ingest([schedule(at=999)],1000)==0
    assert not s.history()
    reopened=Database(db.path);again=AiringUpdates(reopened)
    assert again.followed(91) and not again.history()
    row=reopened.connection.execute('SELECT * FROM airing_updates').fetchone()
    assert row['airing_at']==999 and row['is_read'] and row['dismissed']
    reopened.connection.close()

def test_actual_inventory_gaps_and_rescan_refresh(updates,tmp_path):
    db,s=updates;aid=anime(db,tmp_path/'anime',91);s.set_follow(schedule()['media'],True)
    db.connection.execute('UPDATE media SET episode=7,path=? WHERE anime_id=?',(str(tmp_path/'07.mkv'),aid));db.connection.commit()
    assert s.ingest([schedule()],1000)==1 and s.history()[0]['availability']=='missing'
    db.connection.execute('UPDATE media SET episode=8,path=? WHERE anime_id=?',(str(tmp_path/'08.mkv'),aid));db.connection.commit()
    assert s.history()[0]['availability']=='present'
    db.connection.execute('UPDATE media SET present=0 WHERE anime_id=?',(aid,));db.connection.commit()
    assert s.history()[0]['availability']=='missing'
    db.connection.execute('UPDATE media SET present=1,episode=NULL WHERE anime_id=?',(aid,));db.connection.commit()
    assert s.history()[0]['availability']=='uncertain'

@pytest.mark.parametrize('filename',['Show E01-E08.mkv','Show 01-08.mkv','Show E01+E08.mkv'])
def test_packs_are_uncertain(updates,tmp_path,filename):
    db,s=updates;aid=anime(db,tmp_path/'anime',91)
    db.connection.execute('UPDATE media SET episode=1,path=? WHERE anime_id=?',(str(tmp_path/filename),aid));db.connection.commit()
    assert s.availability(91,8)=='uncertain'

def test_default_monitoring_explicit_unfollow_and_scope(updates,tmp_path):
    db,s=updates;aid=anime(db,tmp_path/'normal',91)
    db.set_metadata(aid,91,schedule()['media']);db.set_manual_status('Watching',anime_id=aid)
    assert 91 in s.candidates() and s.followed(91)
    assert s.set_follow(schedule()['media'],False)
    assert 91 in s.candidates() # Legacy unfollow never hides a vault title now.
    assert s.ingest([schedule()],1000)==1
    assert s.set_follow(schedule()['media'],True)
    db.set_manual_status('Paused',anime_id=aid);assert 91 in s.candidates()
    private=anime(db,tmp_path/'private',92,True)
    assert not s.set_follow(schedule(92)['media'],True)
    assert not s.set_follow(schedule(93,adult=True)['media'],True)
    assert not s.set_follow(remote(94,'MANGA'),True)
    assert s.ingest([schedule(92),schedule(93,adult=True)],1000)==0
    assert s.ingest([schedule()],1000)==0
    db.set_metadata(aid,91,remote(91,adult=True))
    assert not s.history() and not s.candidates()

def test_missing_metadata_and_no_automatic_discover_follow(updates):
    _,s=updates
    assert 91 in s.candidates()
    for item in [{'id':1},{'id':'bad','isAdult':False},{'id':None,'isAdult':False}]:
        assert not s.set_follow(item,True)
    assert not s.history()

def test_fetch_uses_official_times_paginates_and_propagates_failure(monkeypatch):
    calls=[];monkeypatch.setattr('anime_hub.airing_updates.time.sleep',lambda *_:None)
    def request(query,variables):
        calls.append((query,variables))
        return {'Page':{'pageInfo':{'hasNextPage':variables['page']==1},'airingSchedules':[schedule(episode=variables['page'])]}}
    rows=fetch_airing_updates([91],1000,request);assert len(rows)==2
    assert calls[0][1]=={'ids':[91],'after':1000-30*86400,'before':1000+14*86400+1,'page':1}
    assert 'airingAt_lesser:$before' in calls[0][0]
    with pytest.raises(RuntimeError):fetch_airing_updates([91],1000,lambda *_:{})

def test_simple_vault_list_without_watching_or_following(window,tmp_path,monkeypatch):
    w,qt,aid,*_=window;item={**remote(11),'status':'RELEASING'};w.db.set_metadata(aid,11,item)
    w.airing_updates.set_follow(item,False)
    assert 11 in w.airing_updates.candidates()
    w.show_airing_updates();page=w.stack.currentWidget()
    assert any('Shared 11' in x.text() for x in page.findChildren(QLabel))
    assert not any('Mark all' in b.text() or 'Follow' in b.text() for b in page.findChildren(QPushButton))
    w.airing_updates.ingest([schedule(11,8)],1000);w._refresh_airing_bell();assert w.airing_bell.text()=='1'
    w.show_airing_updates();assert any('Episode 8 has aired' in x.text() for x in w.stack.currentWidget().findChildren(QLabel))
    captured={};monkeypatch.setattr(w,'_submit_discover_job',lambda key,op,ok,fail:captured.update(ok=ok,fail=fail))
    w.check_airing_updates(True);assert w._airing_check_busy
    w.show_home();captured['fail'](RuntimeError('secret'));assert len(w.airing_updates.history())==1
    w._airing_check_after=0;w.check_airing_updates(True)
    captured['ok']({'catalog':[item],'schedules':[schedule(11,9)]})
    assert len(w.airing_updates.vault_titles())==1
    assert w.airing_updates.vault_titles()[0]['episode']==9
    w.show_airing_history();next(b for b in w.stack.currentWidget().findChildren(QPushButton) if b.text()=='Mark all as read').click()
    assert not w.airing_updates.history(unread=True)
    # Read/dismissed history cannot hide a known missing episode from the vault list.
    w._airing_mark(w.airing_updates.history()[0],True)
    assert w.airing_updates.vault_titles()[0]['episode']==9


def test_marker_scope_and_no_follow_controls(window):
    w,qt,aid,*_=window;w.db.set_metadata(aid,11,{**remote(11),'status':'RELEASING'})
    w.show_detail(aid);assert not w.stack.currentWidget().findChild(QPushButton,'airingFollow')
    w.show_library(view_mode='Posters');QTest.qWait(100)
    card=next(c for c in w.stack.currentWidget().findChildren(Card) if c.anime_id==aid)
    assert card.findChild(QLabel,'airingBadge').text()=='Airing'
    w.airing_updates.ingest([schedule(11,8)],1000);w._refresh_airing_card_markers()
    assert card.findChild(QLabel,'airingBadge').text()=='New ep 8'
    QTest.mouseDClick(card,Qt.LeftButton);assert w.current_anime_id==aid and w.current_view=='detail'
    w.db.set_setting('restricted_unlocked','1');w.show_home('restricted');qt.processEvents();assert not w.airing_bell.isVisible()
    previous=w.stack.currentWidget();w.show_airing_updates();assert w.stack.currentWidget() is previous
    w.lock_restricted();assert w.airing_bell.isVisible()

def test_initial_d_related_other_local_group_and_stage_navigation(window,tmp_path):
    from anime_hub.library_franchises import build_franchises
    w,qt,aid,*_=window
    second=anime(w.db,tmp_path/'Stage2',12);film=anime(w.db,tmp_path/'Legend',13)
    a=remote(11);a['title']={'english':'Initial D First Stage'};a['relations']={'edges':[{'relationType':'SEQUEL','node':remote(12)},{'relationType':'ALTERNATIVE','node':remote(13)}]}
    b=remote(12);b['title']={'english':'Initial D Second Stage'}
    w.db.set_metadata(aid,11,a);w.db.set_metadata(second,12,b);w.db.set_metadata(film,13,remote(13))
    # Cached relation outside grouping is still a valid link to another local release.
    w._library_relation_data={str(11):[{**remote(13),'relationType':'SEQUEL'}]};w._library_relation_revision=0
    group=build_franchises(w.db.anime_list())[0]
    w.show_library_franchise(group.local_ids,displayed_group=group);qt.processEvents()
    assert w.current_view=='library_franchise'
    card=next(c for c in w.stack.currentWidget().findChildren(Card) if c.anime_id==film)
    QTest.mouseDClick(card,Qt.LeftButton);assert w.current_anime_id==film
    for identifier in (aid,second,film):
        w.show_detail(identifier);assert w.current_view=='detail' and w.current_anime_id==identifier

@pytest.mark.parametrize('identifier',[None,0])
def test_individual_unidentified_nested_release_stable_ids(window,identifier):
    w,qt,aid,*_=window;w.db.set_metadata(aid,identifier,{'title':{'english':'Nested stage'},'isAdult':False})
    w.show_library_franchise([aid]);assert w.current_anime_id==aid and w.current_view=='detail'


def test_delayed_broadcast_hides_old_alert_without_losing_dismissal(updates):
    db,s=updates;item=schedule()['media'];s.set_follow(item,True)
    now=int(time.time());assert s.ingest([schedule(at=now-100)],now)==1
    s.mark(91,8);assert s.ingest([schedule(at=now+100)],now)==0
    assert not s.history()
    assert s.ingest([schedule(at=now-1)],now)==0
    assert s.history()[0]['is_read']


def test_timezone_independent_unix_boundary(updates,monkeypatch):
    db,s=updates;s.set_follow(schedule()['media'],True)
    # UTC epoch across the US DST fall-back; only absolute airing time matters.
    now=1793512800;monkeypatch.setattr('anime_hub.airing_updates.time.time',lambda:now)
    assert s.ingest([schedule(at=now+1)])==0
    assert s.ingest([schedule(at=now)])==1
    assert len(s.history())==1


def test_safe_idempotent_migration_preserves_existing_data(updates,tmp_path):
    db,s=updates;aid=anime(db,tmp_path/'existing');db.set_favorite(aid,True)
    db.set_personal_rating('ANIME',aid,8);db.set_manual_status('Watching',anime_id=aid)
    before=tuple(db.anime(aid));s.set_follow(schedule()['media'],True);s.ingest([schedule()],1000)
    reopened=Database(db.path);assert tuple(reopened.anime(aid))==before
    assert len(AiringUpdates(reopened).history())==1
    assert reopened.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    reopened.connection.close()


def test_franchise_invalid_metadata_ids_do_not_block_valid_group(window,tmp_path):
    from anime_hub.library_franchises import build_franchises
    w,qt,aid,*_=window
    stage=anime(w.db,tmp_path/'nested-stage',12)
    a=remote(11);a['relations']={'edges':[{'relationType':'SEQUEL','node':remote(12)}]}
    w.db.set_metadata(aid,11,a)
    rows=[dict(row) for row in w.db.anime_list()]
    rows.append({**rows[0],'id':999,'anilist_id':'unidentified'})
    groups=build_franchises(rows);assert len(groups)==1 and set(groups[0].local_ids)=={aid,stage}


def test_unnumbered_scan_fallback_never_assumes_file_count(updates,tmp_path):
    db,s=updates;aid=anime(db,tmp_path/'anime',91)
    db.connection.execute('UPDATE media SET episode=1,path=? WHERE anime_id=?',(str(tmp_path/'feature film.mkv'),aid));db.connection.commit()
    assert s.availability(91,1)=='uncertain' and s.availability(91,8)=='uncertain'


@pytest.mark.parametrize('kind',['special','movie','other'])
def test_only_unmapped_video_is_uncertain(updates,tmp_path,kind):
    db,s=updates;aid=anime(db,tmp_path/'anime',91)
    db.connection.execute('UPDATE media SET kind=? WHERE anime_id IN (SELECT id FROM anime WHERE anilist_id=91)',(kind,));db.connection.commit()
    assert s.availability(91,8)=='uncertain'


def test_real_background_worker_keeps_ui_responsive(window,monkeypatch):
    from PySide6.QtCore import QTimer
    import threading
    w,qt,aid,*_=window;w.db.set_metadata(aid,11,{**remote(11),'status':'RELEASING'})
    entered=threading.Event()
    def slow(*args,**kwargs):
        entered.set();time.sleep(.25);return {'catalog':[{**remote(11),'status':'RELEASING'}],'schedules':[schedule(11)]}
    monkeypatch.setattr('anime_hub.airing_updates_ui.fetch_vault_airing',slow)
    ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    started=time.perf_counter();w.check_airing_updates(True);assert time.perf_counter()-started<.15
    for _ in range(80):
        QTest.qWait(10)
        if entered.is_set() and not w._airing_check_busy:break
    timer.stop();assert entered.is_set() and len(ticks)>=5 and not w._airing_check_busy
    assert len(w.airing_updates.history())==1


def test_api_reclassification_scrubs_old_normal_history(updates):
    db,s=updates;s.set_follow(schedule()['media'],True);assert s.ingest([schedule()],1000)==1
    assert s.ingest([schedule(adult=True)],1000)==0
    assert not s.history() and not s.candidates()
    assert not s.set_follow(schedule()['media'],True)
    record=db.connection.execute('SELECT metadata_json FROM airing_updates').fetchone()[0]
    assert json.loads(record)=={'id':91,'type':'ANIME','isAdult':True}


def test_catalog_transition_and_finished_exclusion(updates):
    db,s=updates;local=next(iter(s.local_titles()[91]))[0]
    s.apply_catalog([{**remote(91),'status':'NOT_YET_RELEASED'}]);assert not s.vault_titles()
    s.apply_catalog([{**remote(91),'status':'RELEASING'}]);assert len(s.vault_titles())==1
    s.apply_catalog([{**remote(91),'status':'FINISHED'}]);assert not s.vault_titles()
    assert db.anime(local['id'])


def test_no_discover_only_follow_in_vault_list(updates):
    db,s=updates;s.set_follow({**remote(500),'status':'RELEASING'},True)
    assert 500 not in s.candidates()
    assert {r['media_id'] for r in s.vault_titles()}=={91}


def test_status_refresh_queries_all_vault_ids_and_only_schedules_airing():
    from anime_hub.airing_updates import fetch_vault_airing
    calls=[]
    def request(query,variables):
        calls.append(variables)
        if 'after' not in variables:return {'Page':{'media':[{**remote(91),'status':'RELEASING'},remote(92)]}}
        return {'Page':{'pageInfo':{'hasNextPage':False},'airingSchedules':[schedule()]}}
    result=fetch_vault_airing([91,92],1000,request=request)
    assert calls[0]=={'ids':[91,92]} and calls[1]['ids']==[91]
    assert len(result['catalog'])==2 and len(result['schedules'])==1


def test_unknown_status_and_new_adult_classification(updates):
    db,s=updates
    s.apply_catalog([{**remote(91),'status':'RELEASING','isAdult':True}])
    assert not s.vault_titles() and not s.local_titles()
    assert all(db.anime_scope(r)=='restricted' for r in db.anime_list())


def test_new_private_status_clears_normal_focus_and_list(window,monkeypatch):
    w,qt,aid,*_=window;w.db.set_metadata(aid,11,{**remote(11),'status':'RELEASING'})
    w.show_library();QTest.qWait(100)
    w._select_hub_entity('normal','local:'+str(aid));assert w.context_rail.entity
    captured={};monkeypatch.setattr(w,'_submit_discover_job',lambda key,op,ok,fail:captured.update(ok=ok))
    w.check_airing_updates(True);captured['ok']({'catalog':[{**remote(11,adult=True),'status':'RELEASING'}],'schedules':[]})
    assert w.current_view=='home'
    selected=w.context_rail.entity
    assert selected is None or selected.media_type!='ANIME' or not selected.local or selected.local['id']!=aid
    assert not w.airing_updates.vault_titles()
