from pathlib import Path
from unittest.mock import patch
import pytest
from anime_hub.database import Database
from anime_hub.scanner import scan
from anime_hub.parser import classify_file,parse_title
from anime_hub.metadata import evaluate_candidate,AniListClient,search_variants
from anime_hub.organization import Organization
from anime_hub.manga_library import MangaStore
from anime_hub.episode_identity import display_episode
from test_cross_media import window


@pytest.mark.parametrize('label',['0.25','22.25','23.95','0.923','25.01','0'])
def test_exact_stage_turn_labels(label):
    for marker in ('Stage','Turn','Episode'):
        item=classify_file(Path(f'Example/{marker} {label}.mkv'))
        assert item.kind=='episode'
        assert item.episode_label==label if '.' in label or marker in ('Stage','Turn') else item.episode==0


def test_fractional_collection_rescan_restores_nine_playable_files_and_history(tmp_path):
    root=tmp_path/'Anime';folder=root/'Example R2 Picture Drama (2008)';folder.mkdir(parents=True)
    labels=['0.56','0.923','3.33','7.19','9.33','12.31','19.02','23.95','25.01']
    for label in labels:(folder/f'Example - Turn {label}.mkv').touch()
    db=Database(tmp_path/'vault.db');scan(root,db,match_online=False);row=db.anime_list()[0];aid=row['id'];files=db.media(aid)
    assert row['episode_count']==9 and [r['episode_label'] for r in files]==labels
    assert [r['episode'] for r in files]==list(range(1,10))
    db.set_watched(files[0]['id'],True);db.set_resume_position(files[1]['id'],12000)
    with db.connection:db.connection.execute("UPDATE media SET kind='alternate',detected_kind='alternate' WHERE id=?",(files[2]['id'],))
    scan(root,db,match_online=False)
    assert db.anime_list()[0]['episode_count']==9
    assert [r['id'] for r in db.media(aid)]==[r['id'] for r in files]
    assert db.media_by_id(files[0]['id'])['watched'] and db.media_by_id(files[1]['id'])['resume_position_ms']==12000
    assert display_episode(db.next_unwatched(aid))=='0.923'
    assert display_episode(db.adjacent_episode(aid,files[1]['id'],1))=='3.33'
    db.set_watched_through(files[2]['id']);assert sum(r['watched'] for r in db.media(aid))==3
    db.connection.close()


def test_special_constraint_rejects_regular_season_and_retrieves_special(tmp_path):
    title='Example - Rebellion R2 Picture Drama'
    regular={'id':1,'title':{'english':'Example - Rebellion R2'},'format':'TV','type':'ANIME','isAdult':False}
    special={**regular,'id':2,'format':'SPECIAL','title':{'english':title}}
    assert parse_title(title).format_hint=='PICTURE_DRAMA'
    assert not evaluate_candidate(title,regular,format_hint='SERIES')['eligible']
    assert evaluate_candidate(title,special,format_hint='PICTURE_DRAMA')['eligible']
    variants=search_variants(title);assert 'Example R2 Picture Drama' in variants
    client=AniListClient(min_interval=0,max_retries=0)
    client.query_cache={v:{'data':{'Page':{'media':[regular,special]}}} for v in variants}
    assert client.lookup(title,detected_format='PICTURE_DRAMA').selected['id']==2


def test_duplicate_remote_ids_keep_exact_local_sources_and_state(tmp_path):
    db=Database(tmp_path/'vault.db');ids=[]
    for name in ('Regular R2','R2 Picture Drama'):
        folder=tmp_path/name;folder.mkdir();path=folder/'01.mkv';path.touch()
        aid=db.upsert_anime(name,name,'','Other',str(folder));db.upsert_media(aid,classify_file(path));db.set_metadata(aid,2904,{'id':2904,'isAdult':False,'title':{'english':'Regular R2'}});ids.append(aid)
    org=Organization(db,MangaStore(db))
    for aid in ids:
        entity=org.resolve('local:'+str(aid));assert entity.local['id']==aid and entity.local['root_path']==db.anime(aid)['root_path']
    assert org.resolve('anilist:2904').local is None
    db.set_manual_status('Watching',anime_id=ids[1])
    assert db.manual_status(anime_id=ids[0]) is None and db.manual_status(anime_id=ids[1])=='Watching'
    cid=db.create_collection('Independent');assert db.add_to_collection(cid,ids[0]) and db.add_to_collection(cid,ids[1])
    assert len(db.collection_anime(cid))==2
    from anime_hub.scan_state import manual_match
    manual_match(db,ids[1],{'id':5163,'isAdult':False,'type':'ANIME','title':{'english':'R2 Picture Drama'}})
    assert db.anime(ids[0])['anilist_id']==2904 and db.anime(ids[1])['anilist_id']==5163
    db.connection.close()


def test_card_navigation_open_folder_and_manual_id_are_local(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from anime_hub.scanner_review import ScannerReview
    w,qt,first,*_=window
    folder=tmp_path/'Picture Drama';folder.mkdir();file=folder/'Turn 0.923.mkv';file.touch()
    second=w.db.upsert_anime('picture','Picture Drama','','Other',str(folder));parsed=classify_file(file);parsed.episode=1;w.db.upsert_media(second,parsed)
    regular={'id':2904,'isAdult':False,'type':'ANIME','title':{'english':'Regular R2'},'format':'TV'}
    for aid in (first,second):w.db.set_metadata(aid,2904,regular)
    entity=w.organization('normal').resolve('local:'+str(second));card=w._entity_card(entity)
    card.clicked.emit(card.anime_id);qt.processEvents();assert w.current_anime_id==second
    opened=[];monkeypatch.setattr(w,'open_folder',opened.append)
    button=next(b for b in w.stack.currentWidget().findChildren(QPushButton) if 'Open Folder' in b.text());button.click()
    assert opened==[str(folder)]
    candidate={'id':5163,'isAdult':False,'type':'ANIME','title':{'english':'Picture Drama'},'format':'SPECIAL'}
    monkeypatch.setattr('anime_hub.metadata.fetch_anilist_id',lambda identifier,**kwargs:candidate if identifier==5163 else None)
    monkeypatch.setattr('anime_hub.scanner_review.cache_artwork',lambda item,*_:item)
    monkeypatch.setattr(w,'_submit_discover_job',lambda key,work,done,*_,**kw:done(work()))
    review=ScannerReview(w,anime_id=second);review.query.setText('https://anilist.co/anime/5163');review.search()
    assert review.candidates.count()==1
    review.apply();assert w.db.anime(first)['anilist_id']==2904 and w.db.anime(second)['anilist_id']==5163
    review.close();card.deleteLater()
