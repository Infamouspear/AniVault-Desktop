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
