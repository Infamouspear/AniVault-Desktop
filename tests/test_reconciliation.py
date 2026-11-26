"""Complete scan evidence retires sources; uncertain storage never does."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from anime_hub.database import Database
from anime_hub.scanner import scan
from anime_hub import scan_state
from anime_hub.reconciliation import health
from anime_hub.manga_library import MangaStore,scan_manga
from anime_hub.organization import Organization


def fixture(tmp_path):
    root=tmp_path/'Anime';folder=root/'Example S01';folder.mkdir(parents=True)
    for n in (1,2):(folder/f'S01E{n:02}.mkv').write_bytes(b'video'+bytes([n]))
    db=Database(tmp_path/'vault.db');scan(root,db,match_online=False)
    return db,root,folder,db.anime_list()[0]['id']


def test_retirement_is_reversible_and_preserves_all_user_state(tmp_path):
    db,root,folder,aid=fixture(tmp_path);file=folder/'S01E01.mkv';mid=db.media(aid)[0]['id']
    db.set_watched(mid,True);db.set_resume_position(mid,12345);db.set_favorite(aid,True);db.set_personal_rating('ANIME',aid,8)
    cid=db.create_collection('Keep');db.add_to_collection(cid,aid)
    scan_state.manual_match(db,aid,{'id':10,'title':{'english':'Example'},'isAdult':False,'type':'ANIME','format':'TV'})
    with db.connection:db.connection.execute("UPDATE media SET present=0 WHERE anime_id=?",(aid,))
    # Exact files return later; renaming outside the scanned root simulates deletion safely.
    stored=tmp_path/'Stored';folder.rename(stored)
    scan(root,db,match_online=False)
    assert not db.anime_list() and not db.collection_anime(cid) and not db.continue_watching() and not db.recently_watched()
    assert not Organization(db,MangaStore(db)).resolve('local:'+str(aid))
    row=db.anime(aid);assert not row['active'] and row['availability']=='Missing'
    assert row['favorite'] and row['personal_rating_units']==16 and row['anilist_id']==10
    assert scan_state.source_state(db,aid)['locked'] and db.anime_collection_ids(aid)=={cid}
    assert db.media_by_id(mid)['resume_position_ms']==12345 and db.media_by_id(mid)['watched']
    assert health(db)['retired']==1 and list((tmp_path/'backups').glob('before-scan*.db'))
    stored.rename(folder);scan(root,db,match_online=False)
    assert db.anime_list()[0]['id']==aid and db.media_by_id(mid)['watched']
    assert len(db.collection_anime(cid))==1
    db.connection.close()


def test_retired_remote_collection_alias_does_not_create_ghost_card(tmp_path):
    db,root,folder,aid=fixture(tmp_path)
    item={'id':10,'isAdult':False,'title':{'english':'Example'},'type':'ANIME'}
    db.set_metadata(aid,10,item);cid=db.create_collection('Keep');db.add_to_collection(cid,aid)
    folder.rename(tmp_path/'Stored');scan(root,db,match_online=False)
    assert not Organization(db,MangaStore(db)).collection(cid)
    assert db.anime_collection_ids(aid)=={cid}
    db.save_title(item)
    entity=Organization(db,MangaStore(db)).resolve('anilist:10')
    assert entity and entity.saved and entity.local is None
    db.connection.close()


@pytest.mark.parametrize('failure',['offline','permission','cancel','exception','changed'])
def test_incomplete_scan_never_retires_or_loses_media(tmp_path,failure):
    db,root,folder,aid=fixture(tmp_path)
    before=[tuple(r) for r in db.connection.execute('SELECT * FROM media')]
    if failure=='offline':
        root.rename(tmp_path/'Offline');assert scan(root,db,match_online=False)==0
    elif failure=='permission':
        with patch('anime_hub.reconciliation.os.walk',side_effect=PermissionError('blocked')):assert scan(root,db,match_online=False)==0
    elif failure=='cancel':assert scan(root,db,should_cancel=lambda:True,match_online=False)==0
    elif failure=='exception':
        with patch.object(db,'upsert_media',side_effect=RuntimeError('failure')),pytest.raises(RuntimeError):scan(root,db,match_online=False)
    else:
        from anime_hub.reconciliation import inventory
        snap=inventory(root)
        with patch('anime_hub.reconciliation.inventory',side_effect=[snap,{}]):assert scan(root,db,match_online=False)==0
    assert db.anime(aid)['active'] and before==[tuple(r) for r in db.connection.execute('SELECT * FROM media')]
    db.connection.close()


def test_episode_deletion_keeps_release_and_history(tmp_path):
    db,root,folder,aid=fixture(tmp_path);mid=db.media(aid)[0]['id'];db.set_watched(mid,True)
    Path(db.media_by_id(mid)['path']).unlink();scan(root,db,match_online=False)
    assert db.anime_list()[0]['episode_count']==1 and db.media_by_id(mid)['watched'] and not db.media_by_id(mid)['present']
    assert db.anime(aid)['active'];db.connection.close()


def test_directory_identity_survives_rename_and_added_episode(tmp_path):
    db,root,folder,aid=fixture(tmp_path);renamed=root/'Renamed Example S01';folder.rename(renamed)
    (renamed/'S01E03.mkv').touch();scan(root,db,match_online=False)
    assert len(db.anime_list())==1 and db.anime_list()[0]['id']==aid and db.anime(aid)['availability']=='Relocated'
    assert db.anime_list()[0]['episode_count']==3
    scan(root,db,match_online=False);assert len(db.anime_list())==1
    db.connection.close()


@pytest.mark.parametrize('layout',['single','seasons','named','nested','mixed'])
def test_hierarchical_containers_and_extras(tmp_path,layout):
    root=tmp_path/'Anime';container=root/'Example Complete Series'
    folders={'single':[root/'Example'],'seasons':[container/'Season 1',container/'Season 2'],'named':[container/'Example',container/'Example Vibration'],'nested':[container/'Nested Collection'/'Example',container/'Nested Collection'/'Example Vibration'],'mixed':[root/'Example Movies']}[layout]
    for folder in folders:
        folder.mkdir(parents=True);(folder/'S01E01.mkv').touch();(folder/'NC').mkdir();(folder/'NC'/'ED Episode 12.mkv').touch();(folder/'OVAs').mkdir();(folder/'OVAs'/'Bonus OVA.mkv').touch()
    if layout=='mixed':(folders[0]/'Different Movie.mkv').touch()
    db=Database(tmp_path/'vault.db');scan(root,db,match_online=False)
    assert len(db.anime_list())==len(folders)
    for row in db.anime_list():
        assert row['episode_count']==1 and row['extras_count']>=2
        assert Path(row['root_path']) in folders
    db.connection.close()


def test_existing_empty_container_and_private_state_are_retired_not_deleted(tmp_path):
    db,root,folder,aid=fixture(tmp_path)
    ghost=db.upsert_anime('ghost','Old complete container','','Other',str(root/'Gone'))
    with db.connection:db.connection.execute('UPDATE anime SET anilist_id=999,metadata_json=? WHERE id=?',(json.dumps({'isAdult':True,'id':999}),ghost))
    scan(root,db,match_online=False)
    assert len(db.anime_list())==1 and db.anime(ghost) and not db.anime(ghost)['active']
    assert health(db,'normal')['retired']==0
    assert Organization(db,MangaStore(db)).resolve('anilist:999',{'id':999,'isAdult':False}) is None
    db.connection.close()


def test_manga_deleted_hidden_offline_retained_and_cancelled_atomic(tmp_path):
    db=Database(tmp_path/'vault.db');root=tmp_path/'Manga';folder=root/'Example';folder.mkdir(parents=True);file=folder/'Vol 1.cbz';file.write_bytes(b'fixture')
    store=MangaStore(db);store.add_root(root);store.reconcile(scan_manga(store.roots()));sid=store.series_list()[0]['id']
    file.unlink();store.reconcile(scan_manga(store.roots()));assert not store.series_list()
    assert db.connection.execute('SELECT id FROM manga_series WHERE id=?',(sid,)).fetchone()
    file.write_bytes(b'fixture');store.reconcile(scan_manga(store.roots()));assert store.series_list()[0]['id']==sid
    root.rename(tmp_path/'Offline');store.reconcile(scan_manga(store.roots()));assert store.series_list()[0]['id']==sid
    result={'cancelled':True,'series':{},'roots_done':[store.roots()[0]['id']],'errors':[]};store.reconcile(result);assert store.series_list()
    db.connection.close()


def test_timestamp_touch_does_not_repeat_metadata_jobs(tmp_path):
    import os
    db,root,folder,aid=fixture(tmp_path)
    before=[tuple(r) for r in db.connection.execute('SELECT target,revision,fingerprint FROM metadata_jobs ORDER BY target')]
    for path in folder.glob('*.mkv'):os.utime(path,(1234567890,1234567890))
    scan(root,db,match_online=False)
    assert before==[tuple(r) for r in db.connection.execute('SELECT target,revision,fingerprint FROM metadata_jobs ORDER BY target')]
    db.connection.close()


def test_broken_cached_artwork_queues_only_artwork_and_preserves_custom(tmp_path):
    from anime_hub import metadata_jobs as jobs
    db,root,folder,aid=fixture(tmp_path);path=tmp_path/'10_cover_path.jpg';path.write_bytes(b'broken')
    item={'id':10,'isAdult':False,'title':{'english':'Example'},'cover_path':str(path),'coverImage':{'large':'https://example.com/10.jpg'}}
    db.set_metadata(aid,10,item)
    with db.connection:db.connection.execute('DELETE FROM metadata_jobs')
    jobs.enqueue_existing(db)
    assert [r[0] for r in db.connection.execute('SELECT operation FROM metadata_jobs')]==['artwork']
    before=db.connection.execute('SELECT revision FROM metadata_jobs').fetchone()[0]
    jobs.enqueue_existing(db);assert db.connection.execute('SELECT revision FROM metadata_jobs').fetchone()[0]==before
    item['cover_path']=str(tmp_path/'custom.jpg');Path(item['cover_path']).write_bytes(b'broken custom')
    db.set_metadata(aid,10,item)
    with db.connection:db.connection.execute('DELETE FROM metadata_jobs')
    jobs.enqueue_existing(db);assert not db.connection.execute('SELECT 1 FROM metadata_jobs').fetchone()
    db.connection.close()


def test_split_private_container_never_exposes_children_normally(tmp_path):
    root=tmp_path/'Anime';container=root/'Complete Collection'
    for name in ('One','Two'):
        folder=container/name;folder.mkdir(parents=True);(folder/'S01E01.mkv').touch()
    db=Database(tmp_path/'vault.db');aid=db.upsert_anime('old','Private collection','','Other',str(container))
    from anime_hub.parser import classify_file
    for path in container.rglob('*.mkv'):db.upsert_media(aid,classify_file(path))
    db.set_metadata(aid,999,{'id':999,'isAdult':True,'title':{'english':'Private collection'}})
    scan(root,db,match_online=False)
    assert not db.anime(aid)['active'] and len(db.anime_list())==2
    assert all(db.anime_scope(r,fresh=False)=='restricted' for r in db.anime_list())
    assert not Organization(db,MangaStore(db)).search('')
    db.connection.close()
