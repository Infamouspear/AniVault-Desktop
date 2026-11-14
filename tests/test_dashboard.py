from types import SimpleNamespace
from anime_hub.dashboard import summarize


def test_completion_counts_explicit_status_and_genres_overlap():
    anime=[SimpleNamespace(status=None,item={'genres':['Drama','Drama','Action']},local={'category':'Other'}),
           SimpleNamespace(status='Completed',item={'format':'MOVIE','genres':['Drama']},local={})]
    manga=[SimpleNamespace(status='Reading',item={},local={})]
    data=summarize(anime,manga,[(1,2,2,0),(2,1,0,1)])
    assert dict(data['summary'])['Library titles']==3
    assert dict(data['summary'])['Movies']==1
    assert data['statuses']['Completed']==1
    assert data['statuses']['Unassigned']==1
    assert data['statuses']['Watching']==1
    assert data['genres']=={'Drama':2,'Action':1}
    assert (data['indexed'],data['watched'])==(3,2)

def test_storage_sizes_are_indexed_and_unknown_is_not_zero(tmp_path):
    from anime_hub.database import Database
    from anime_hub.manga_library import MangaStore, scan_manga
    from anime_hub.dashboard import storage_text
    db = Database(tmp_path / 'library.db')
    try:
        anime_id = db.upsert_anime('show','Show','','Other',str(tmp_path))
        video = tmp_path / 'episode.mkv'
        video.write_bytes(b'12345')
        db.upsert_media(anime_id, SimpleNamespace(path=video,kind='episode',season=1,episode=1))
        assert db.connection.execute('SELECT size_bytes FROM media').fetchone()[0] == 5
        folder=tmp_path/'manga'
        folder.mkdir()
        (folder/'Book.cbz').write_bytes(b'123')
        store=MangaStore(db)
        store.add_root(folder)
        store.reconcile(scan_manga(store.roots()))
        assert db.connection.execute('SELECT size_bytes FROM manga_items').fetchone()[0] == 3
        assert storage_text([(2,1,5)]) == '5 B (partial)'
        assert storage_text([(1,0,0)]) == 'Rescan needed'
        assert storage_text([(2,2,8)]) == '8 B'
    finally:
        db.connection.close()

def test_personal_ratings_persist_and_remain_independent(tmp_path):
    import pytest
    from anime_hub.database import Database
    from anime_hub.manga_library import MangaStore,scan_manga
    path=tmp_path/'vault.db'
    db=Database(path)
    aid=db.upsert_anime('anime-a','Same title','','Other',str(tmp_path))
    root=tmp_path/'manga';root.mkdir();(root/'Title.cbz').write_bytes(b'fixture')
    store=MangaStore(db);store.add_root(root);store.reconcile(scan_manga(store.roots()))
    mid=store.series_list('normal')[0]['id']
    for invalid in (0,10.5,3.2,float('nan'),True):
        with pytest.raises(ValueError):
            db.set_personal_rating('ANIME',aid,invalid)
    db.set_personal_rating('ANIME',aid,8.5);db.set_personal_rating('MANGA',mid,4.5)
    db.upsert_anime('anime-a','Renamed','','Other',str(tmp_path));store.reconcile(scan_manga(store.roots()))
    db.connection.close()
    db=Database(path)
    try:
        assert db.anime(aid)['title']=='Renamed'
        assert db.personal_rating('ANIME',aid)==17
        assert db.personal_rating('MANGA',mid)==9
        db.set_personal_rating('ANIME',aid,10)
        assert db.personal_rating('ANIME',aid)==20
        db.set_personal_rating('ANIME',aid,None)
        assert db.personal_rating('ANIME',aid) is None
    finally:db.connection.close()


def test_rating_histogram_and_overlapping_genres():
    from anime_hub.dashboard import rating_summary
    entries=[SimpleNamespace(local={'personal_rating_units':score},title=str(i),key=str(i),
                             item={'genres':['Drama','Drama','Action']}) for i,score in enumerate((None,2,19,19))]
    rated,histogram,genres=rating_summary(entries)
    assert len(rated)==3 and histogram=={2:1,19:2}
    assert genres['Drama']==genres['Action']==[2,19,19]
