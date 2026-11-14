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
