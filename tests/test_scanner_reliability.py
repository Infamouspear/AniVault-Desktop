"""Real release evidence and system-wide scanner regression protection."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from anime_hub.database import Database
from anime_hub.metadata import AniListClient,LookupReport,evaluate_candidate,cache_artwork
from anime_hub.scanner import scan
from anime_hub.parser import parse_title,classify_file
from anime_hub import scan_state as state
from anime_hub.library_franchises import build_franchises,LibraryFranchiseMixin
from anime_hub.scanner_review import ScannerReview,sanitized_report
from test_cross_media import window


def candidate(identifier,title,format='TV',adult=False):
    return {'id':identifier,'title':{'english':title},'type':'ANIME','isAdult':adult,'format':format,'synonyms':[]}


def lookup(items,title,season=None,format=None,part=None):
    client=AniListClient(min_interval=0,max_retries=0);client.query_cache={title:{'data':{'Page':{'media':items}}}}
    with patch('anime_hub.metadata.search_variants',return_value=[title]):return client.lookup(title,season,detected_format=format,detected_part=part)


@pytest.mark.parametrize('season,expected',[(1,100668),(2,112323),(3,154473)])
def test_arifureta_complete_title_and_season_evidence(season,expected):
    items=[candidate(100668,'Arifureta: From Commonplace to World\'s Strongest'),candidate(112323,'Arifureta: From Commonplace to World\'s Strongest Season 2'),candidate(154473,'Arifureta: From Commonplace to World\'s Strongest Season 3'),candidate(140162,'Arifureta Theme','MUSIC'),candidate(145560,'Arifureta Shokugyou de Sekai Saikyou Prologue','ONA'),candidate(213514,'Arifureta Shokugyou de Sekai Saikyou Picture Drama','ONA')]
    report=lookup(items,'Arifureta',season,'SERIES')
    assert report.selected['id']==expected and report.confidence_level=='High Confidence'
    assert any('season' in d['reason'] for d in report.decisions if d['id']!=expected)


def test_cyberpunk_second_season_requires_separate_official_identity():
    first=candidate(120377,'Cyberpunk: Edgerunners','ONA');second=candidate(195539,'Cyberpunk: Edgerunners 2','ONA')
    assert lookup([first],'Cyberpunk Edgerunners',2,'SERIES').selected is None
    assert lookup([first,second],'Cyberpunk Edgerunners',2,'SERIES').selected['id']==195539


def test_weak_and_ambiguous_candidates_are_never_applied():
    assert not lookup([candidate(7059,'Black Rock Shooter','OVA')],'OVA',format='OVA').selected
    report=lookup([candidate(1,'Example Saga'),candidate(2,'Example Saga')],'Example Saga')
    assert report.selected is None and report.confidence_level=='Needs Review'
    assert not evaluate_candidate('My Hero Academia OVAs',candidate(7059,'Black Rock Shooter','OVA'))['eligible']
    assert not lookup([{},None,{'id':-1,'title':{}},candidate(1,'Unrelated')],'My Hero Academia').selected


def test_part_and_multiepisode_evidence_survives_parsing():
    parsed=parse_title('[Group] Example Saga S02 Part 2 1080p x265')
    assert (parsed.season,parsed.part)==(2,2)
    assert not evaluate_candidate(parsed.title,candidate(1,'Example Saga Season 2 Part 1'),2,part=2)['eligible']
    file=classify_file(Path('Example S01-S07+Movies+OVAs')/'Season 2'/'S02E03-E04.mkv')
    assert (file.kind,file.season,file.episode,file.episode_end)==('episode',2,3,4)


def test_release_copy_rename_offline_and_manual_state_are_reversible(tmp_path):
    db=Database(tmp_path/'vault.db');root=tmp_path/'Anime';first=root/'Example Saga S01';first.mkdir(parents=True);file=first/'S01E01.mkv';file.write_bytes(b'episode')
    report=LookupReport('Example Saga',candidates=[],failure_reason='Offline')
    with patch('anime_hub.scanner.lookup_anilist',return_value=report):scan(root,db)
    row=db.anime_list()[0];aid=row['id'];mid=db.media(aid)[0]['id'];db.set_watched(mid,True);db.set_resume_position(mid,45000);db.set_favorite(aid,True);db.set_personal_rating('ANIME',aid,8);collection=db.create_collection('Keep');db.add_to_collection(collection,aid)
    state.manual_match(db,aid,candidate(10,'Example Saga'))
    second=root/'Example Saga S01 Copy';second.mkdir();(second/'S01E01.mkv').write_bytes(b'episode')
    renamed=root/'Renamed Example Saga S01';first.rename(renamed)
    with patch('anime_hub.scanner.lookup_anilist',return_value=report):scan(root,db)
    assert len(db.anime_list())==2 and db.anime(aid)['root_path']==str(renamed)
    assert db.media(aid)[0]['id']==mid and db.media(aid)[0]['resume_position_ms']==45000 and db.media(aid)[0]['watched']
    assert db.anime(aid)['anilist_id']==10 and db.anime(aid)['favorite'] and db.personal_rating('ANIME',aid)==16 and db.anime_collection_ids(aid)=={collection}
    (renamed/'S01E01.mkv').unlink()
    with patch('anime_hub.scanner.lookup_anilist',return_value=report):scan(root,db)
    assert db.media(aid)[0]['id']==mid and db.media(aid)[0]['present']==0 and db.next_unwatched(aid) is None
    before=[tuple(r) for r in db.connection.execute('SELECT * FROM media')]
    assert scan(tmp_path/'OfflineDrive',db)==0 and before==[tuple(r) for r in db.connection.execute('SELECT * FROM media')]
    state.manual_match(db,aid,clear=True);assert not state.source_state(db,aid)['locked']
    assert list((tmp_path/'backups').glob('before-match*.db'))
    db.connection.close()


def test_shared_mha_ovas_keep_files_and_review_individual_identities(tmp_path):
    root=tmp_path/'Anime';folder=root/'My Hero Academia'/'OVA';folder.mkdir(parents=True)
    for name in ('All Might Rising The Animation','Training of the Dead','Make It Do or Die Part 1','Make It Do or Die Part 2'):(folder/f'[Anime Time] My Hero Academia OVA - {name}.mkv').touch()
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('ova','OVA','','Other',str(folder));db.set_metadata(aid,7059,candidate(7059,'Black Rock Shooter','OVA'))
    # A container with just structural OVA children remains a stable local parent.
    rootrow=state.source_id(db,folder,parse_title('OVA',('My Hero Academia',)),list(folder.iterdir()),'Other');assert rootrow==aid
    with patch('anime_hub.scanner.discover_series_roots',return_value=[SimpleNamespace(category='Other',path=folder)]),patch('anime_hub.scanner.lookup_anilist',return_value=LookupReport('My Hero Academia OVAs')):scan(root,db)
    assert len(db.media(aid))==4 and db.anime(aid)['anilist_id']==7059
    assert state.source_state(db,aid)['state']=='Needs Review'
    files=db.connection.execute('SELECT * FROM scan_file_matches').fetchall();assert len(files)==4 and all('My Hero Academia' in f['parsed_title'] for f in files)
    state.manual_match(db,aid,None);state.manual_match(db,aid,candidate(20,'My Hero Academia: Training of the Dead','OVA'),files[0]['media_id'])
    db.connection.close();db=Database(tmp_path/'vault.db')
    assert state.source_state(db,aid)['locked'] and db.anime(aid)['anilist_id'] is None
    assert db.connection.execute('SELECT anilist_id FROM scan_file_matches WHERE media_id=?',(files[0]['media_id'],)).fetchone()[0]==20
    db.connection.close()


def test_grouping_uses_official_links_across_missing_local_middle_season():
    rows=[{'id':1,'title':'Different localized title','anilist_id':10,'metadata_json':json.dumps(candidate(10,'First Saga'))},{'id':2,'title':'Season three','anilist_id':30,'metadata_json':json.dumps(candidate(30,'Third Saga'))}]
    bridge={str(i):[dict(candidate(20,'Absent season'),relationType=kind)] for i,kind in [(10,'SEQUEL'),(30,'PREQUEL')]}
    groups=build_franchises(rows,bridge);assert len(groups)==1 and set(groups[0].local_ids)=={1,2}
    bridge['30'][0]['isAdult']=True
    assert not build_franchises(rows,bridge)


def test_relationship_batch_queue_completes_after_navigation(window,monkeypatch):
    from anime_hub.library_franchises import QTimer
    w,qt,aid,*_=window;pending=[];timers=[];w._load_library_relations()
    monkeypatch.setattr(w,'_request_library_relations',LibraryFranchiseMixin._request_library_relations.__get__(w))
    for i in range(30):
        ident=w.db.upsert_anime('batch'+str(i),'No special title','','Other','/batch/'+str(i));w.db.set_metadata(ident,100+i,candidate(100+i,'Different name '+str(i)))
    monkeypatch.setattr(w,'_submit_discover_job',lambda *args:pending.append(args));monkeypatch.setattr(QTimer,'singleShot',lambda delay,callback:timers.append(callback))
    LibraryFranchiseMixin._request_library_relations(w);assert len(pending)==1
    w.current_view='home';w.active_nav_key='home';pending[0][2]([])
    assert timers
    timers[-1]();assert len(pending)==2
    pending[1][2]([]);timers[-1]();assert len(pending)==2
    assert len(w._library_relation_dates)==31


def test_review_is_scoped_manual_and_sanitized(window):
    w,qt,aid,*_=window
    private=w.db.upsert_anime('secret','Secret','','Other','C:/private/secret');w.db.set_metadata(private,999,candidate(999,'Secret','OVA',True))
    review=ScannerReview(w,anime_id=aid);review.show();qt.processEvents()
    assert all(r['anime_id']!=private for r in review.items)
    raw=LookupReport('Normal query',candidates=[candidate(11,'Correct')],selected=candidate(999,'Secret','OVA',True),decisions=[{'id':11,'reason':'Title agrees'},{'id':999,'reason':'Title conflicts'}])
    filtered=state.report_data(raw);assert filtered['selected_id'] is None and [d['id'] for d in filtered['decisions']]==[11]
    text=json.dumps(sanitized_report(w.db));assert 'Secret' not in text and 'private' not in text and 'root_path' not in text
    with pytest.raises(ValueError):state.manual_match(w.db,aid,candidate(999,'Secret','OVA',True))
    review.show_candidates([candidate(11,'Correct'),candidate(999,'Secret','OVA',True)]);assert review.candidates.count()==1
    review.apply();assert state.source_state(w.db,aid)['locked'] and w.db.anime(aid)['anilist_id']==11
    review.close()


def test_artwork_recovery_validates_cache_and_keeps_custom_art(tmp_path):
    from PIL import Image
    custom=tmp_path/'my-cover.png';Image.new('RGB',(8,12),'pink').save(custom)
    result=cache_artwork({'id':1,'cover_path':str(custom),'coverImage':{'large':'https://invalid/cover.jpg'}},tmp_path/'art')
    assert result['cover_path']==str(custom)
    damaged=tmp_path/'art'/'1_cover_path.jpg';damaged.write_bytes(b'incomplete')
    import io
    data=io.BytesIO();Image.new('RGB',(8,12),'blue').save(data,format='JPEG')
    class Response(io.BytesIO):pass
    with patch('anime_hub.metadata.urllib.request.urlopen',return_value=Response(data.getvalue())):
        fixed=cache_artwork({'id':1,'cover_path':str(damaged),'coverImage':{'large':'https://example.org/cover.jpg'}},tmp_path/'art')
    with Image.open(fixed['cover_path']) as image:image.verify()
    assert not list((tmp_path/'art').glob('*.part'))


def test_old_collapsed_release_splits_ownership_without_losing_media_ids(tmp_path):
    root=tmp_path/'Anime';one=root/'Example Saga S01';two=root/'Example Saga S01 Copy'
    for folder in (one,two):folder.mkdir(parents=True);(folder/'S01E01.mkv').touch()
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('legacy-collapse','Example Saga','','Other',str(two))
    for folder in (one,two):db.upsert_media(aid,classify_file(folder/'S01E01.mkv'))
    db.connection.commit();before={r['id']:r['anime_id'] for r in db.media(aid)}
    with patch('anime_hub.scanner.lookup_anilist',return_value=LookupReport('Example Saga')):scan(root,db)
    assert len(db.anime_list())==2
    after={r['id']:r['anime_id'] for r in db.connection.execute('SELECT id,anime_id FROM media')}
    assert set(before)==set(after) and len(set(after.values()))==2
    db.connection.close()


def test_nested_seasons_are_distinct_and_specials_are_retained(tmp_path):
    from anime_hub.scanner import discover_series_roots
    root=tmp_path/'Anime';parent=root/'Watching'/'Example Saga'
    for season in (1,2):
        folder=parent/f'Season {season}';folder.mkdir(parents=True);(folder/f'S{season:02}E01.mkv').touch()
    extras=parent/'OVA';extras.mkdir();(extras/'Example Saga OVA - New Adventure.mkv').touch()
    roots=list(discover_series_roots(root));assert {r.path.name for r in roots}=={'Season 1','Season 2','OVA'}
    db=Database(tmp_path/'vault.db')
    with patch('anime_hub.scanner.lookup_anilist',return_value=LookupReport('Example Saga')):scan(root,db)
    assert len(db.anime_list())==3 and sum(len(db.media(r['id'])) for r in db.anime_list())==3
    assert {r['detected_season'] for r in db.anime_list()}=={1,2,None}
    db.connection.close()


def test_scan_cancellation_rolls_back_new_files_and_keeps_old_progress(tmp_path):
    root=tmp_path/'Anime';folder=root/'Example Saga';folder.mkdir(parents=True);(folder/'S01E01.mkv').touch()
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('existing','Example Saga','','Other',str(folder));db.upsert_media(aid,classify_file(folder/'S01E01.mkv'));db.connection.commit()
    mid=db.media(aid)[0]['id'];db.set_resume_position(mid,1200)
    assert scan(root,db,should_cancel=lambda:True)==0
    assert db.media(aid)[0]['present'] and db.media(aid)[0]['resume_position_ms']==1200
    db.connection.close()


def test_incomplete_relationship_response_does_not_poison_cache():
    from anime_hub.anilist_integration import fetch_anime_relations
    with patch('anime_hub.anilist_integration.graphql',return_value={'m0':{'relations':{'edges':[]}}}):
        with pytest.raises(RuntimeError):fetch_anime_relations([10,20])


def test_locked_restricted_review_and_audit_deny_access(tmp_path):
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('private','Private','','Other','/private');db.set_metadata(aid,999,candidate(999,'Private','OVA',True))
    assert state.review_rows(db,'restricted')==[]
    with pytest.raises(ValueError):state.audit(db,'restricted')
    db.set_setting('restricted_unlocked','1');assert len(state.review_rows(db,'restricted'))==1
    db.connection.close()


def test_correcting_existing_id_keeps_collection_and_status_on_local_record(tmp_path):
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('wrong','Example Saga','','Other','/local');custom=tmp_path/'custom-cover.png';custom.write_bytes(b'local artwork');db.set_metadata(aid,7059,{**candidate(7059,'Wrong OVA','OVA'),'cover_path':str(custom)});cid=db.create_collection('Keep');db.add_to_collection(cid,aid);db.set_manual_status('Watching',anime_id=aid)
    state.manual_match(db,aid,candidate(20,'Example Saga'))
    assert db.anime_collection_ids(aid)=={cid} and db.manual_status('normal',anime_id=aid)=='Watching'
    state.manual_match(db,aid,None)
    assert json.loads(db.anime(aid)['metadata_json'])['cover_path']==str(custom)
    assert db.anime_collection_ids(aid)=={cid} and db.manual_status('normal',anime_id=aid)=='Watching'
    db.connection.close()


def test_review_selects_supported_identity_before_conflicting_search_results(window):
    w,qt,aid,*_=window;review=ScannerReview(w,anime_id=aid)
    report=lookup([candidate(1,'Arifureta Theme','MUSIC'),candidate(100668,'Arifureta From Commonplace to Worlds Strongest')],'Arifureta',1,'SERIES')
    review.target['report']=state.report_data(report);review.show_candidates(report.candidates)
    from PySide6.QtCore import Qt
    assert review.candidates.currentItem().data(Qt.UserRole)['id']==100668
    review.close()
