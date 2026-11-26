"""Missing history is retained without inflating present release counts."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from anime_hub.database import Database
from anime_hub.parser import classify_file
from anime_hub.scanner import scan
from anime_hub.app import Card


def add(db,aid,path,kind='episode',episode=1):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'video')
    db.upsert_media(aid,SimpleNamespace(path=path,kind=kind,season=1,episode=episode));db.connection.commit()
    return db.connection.execute('SELECT id FROM media WHERE path=?',(str(path),)).fetchone()[0]


def test_missing_movies_do_not_inflate_library_collection_or_franchise(tmp_path):
    db=Database(tmp_path/'vault.db');root=tmp_path/'Movie 01 - Example';aid=db.upsert_anime('movie1','Movie 01 - Example','','Other',str(root),root.name)
    main=add(db,aid,root/'Movie 01.mkv');missing=[]
    for number in (2,3,4):missing.append(add(db,aid,tmp_path/'old pack'/f'Movie {number:02}.mkv',episode=number))
    add(db,aid,root/'ova'/'Bonus 1.mkv','special');add(db,aid,root/'ova'/'Bonus 2.mkv','special')
    db.set_watched(missing[0],True)
    with db.connection:db.connection.executemany('UPDATE media SET present=0 WHERE id=?',[(i,) for i in missing])
    cid=db.create_collection('Films');db.add_to_collection(cid,aid);fid=db.create_franchise('Example');db.add_to_franchise(fid,aid)
    rows=[db.anime_list()[0],db.collection_anime(cid)[0],db.franchise_anime(fid)[0],db.recently_watched()[0]]
    for row in rows:assert row['episode_count']==1 and row['watched_count']==0
    assert rows[0]['media_count']==3 and rows[0]['extras_count']==2
    assert not db.continue_watching()
    assert len(db.media(aid))==6 and db.media_by_id(missing[0])['watched']
    card=Card(rows[0]);assert card.status_label.text()=='1 movie · 2 extras';card.deleteLater()
    db.connection.close()


def test_split_container_does_not_adopt_entire_collection_for_one_movie(tmp_path):
    root=tmp_path/'Anime';pack=root/'Movies Collection';pack.mkdir(parents=True)
    for i in (1,2):(pack/f'Movie {i:02}.mkv').write_bytes(b'video')
    db=Database(tmp_path/'vault.db');scan(root,db,match_online=False)
    old=db.anime_list()[0]['id'];media={Path(r['path']).name:dict(r) for r in db.media(old)}
    first_id=media['Movie 01.mkv']['id'];db.set_watched(first_id,True);db.set_resume_position(first_id,45000)
    db.override(str(pack/'Movie 01.mkv'),'special')
    for i in (1,2):
        dest=root/f'Movie {i:02}';dest.mkdir();(pack/f'Movie {i:02}.mkv').rename(dest/f'Movie {i:02}.mkv')
    pack.rmdir();scan(root,db,match_online=False)
    owners=[]
    for i in (1,2):
        row=db.media_by_id(media[f'Movie {i:02}.mkv']['id']);owners.append(row['anime_id'])
        assert row['present'] and Path(row['path']).parent==root/f'Movie {i:02}'
    assert len(set(owners))==2 and old not in owners
    assert db.media_by_id(first_id)['watched'] and db.media_by_id(first_id)['resume_position_ms']==45000 and db.media_by_id(first_id)['kind']=='special'
    assert db.connection.execute('SELECT count(*) FROM media').fetchone()[0]==2
    db.connection.close()


def test_one_movie_with_ova_subfolder_queues_the_movie_as_parent(tmp_path):
    root=tmp_path/'Anime';folder=root/'Example Movie 01';folder.mkdir(parents=True)
    (folder/'Example Movie 01.mkv').touch();(folder/'ova').mkdir();(folder/'ova'/'Example OVA.mkv').touch()
    db=Database(tmp_path/'vault.db');scan(root,db,match_online=False)
    row=db.anime_list()[0];assert row['episode_count']==1 and row['extras_count']==1
    jobs=db.connection.execute("SELECT target FROM metadata_jobs WHERE operation='identify' AND state<>'completed'").fetchall()
    assert 'anime:'+str(row['id']) in {r[0] for r in jobs}
    assert len(jobs)==2
    db.connection.close()
