from datetime import datetime,timezone
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel,QScrollArea
from PySide6.QtTest import QTest
from anime_hub.organization import Organization
from anime_hub.recommendations import build_profile,rank_candidates
from anime_hub.app import SeasonCard,ResponsiveSeasonGrid
from test_cross_media import data,window,remote,anime,manga

NOW=datetime(2026,10,10,tzinfo=timezone.utc)

def item(i,genre='Fantasy',kind='ANIME',adult=False,**extra):
    return {**remote(i,kind,adult),'genres':[genre],'tags':[{'name':genre+' affinity','rank':90}],**extra}

def test_favorites_outweigh_saved_and_dropped(data):
    db,store,aid,sid,_=data
    db.set_metadata(aid,11,item(11));db.set_favorite(aid,True)
    db.save_title(item(30,'Sports'));db.save_title(item(31,'Horror'))
    db.set_manual_status('Dropped',item=item(31,'Horror'))
    profile=build_profile(Organization(db,store),now=NOW)
    assert profile.genres['Fantasy']>profile.genres['Sports']>0
    assert not profile.genres['Horror']
    rows,counts=rank_candidates(profile,[item(101,'Sports',popularity=100000),item(102),item(11),item(31),item(102)])
    assert [row['id'] for row in rows]==[102,101]
    assert rows[0]['_recommendation_reason']=='Similar to a title in Favorites'
    assert counts=={'already_local':1,'completed_or_dropped':1,'duplicate':1}

def test_completed_and_active_signals_do_not_fake_consumption(data):
    db,store,*_=data
    db.save_title(item(40));db.set_manual_status('Completed',item=item(40))
    db.save_title(item(41,'Drama'));db.set_manual_status('Watching',item=item(41,'Drama'))
    profile=build_profile(Organization(db,store),now=NOW)
    rows,_=rank_candidates(profile,[item(100),item(101,'Drama'),item(40)])
    assert len(rows)==2
    assert rows[0]['_recommendation_reason']=='Similar to a completed title'
    assert all('Because you watched' not in (r['_recommendation_reason'] or '') for r in rows)
    assert profile.genres['Drama']>0

def test_scopes_cannot_seed_each_other(data,tmp_path):
    db,store,aid,*_=data
    db.set_metadata(aid,11,item(11,'Sports'));db.set_favorite(aid,True)
    private=anime(db,tmp_path/'Private',55,True)
    db.set_metadata(private,55,item(55,'Horror',adult=True));db.set_favorite(private,True)
    db.save_title(item(56,'Mystery',adult=True),'restricted')
    normal=build_profile(Organization(db,store),now=NOW)
    restricted=build_profile(Organization(db,store,'restricted'),now=NOW)
    assert set(normal.genres)=={'Sports'}
    assert set(restricted.genres)=={'Horror','Mystery'}
    rows,counts=rank_candidates(normal,[item(90),item(91,adult=True)])
    assert [r['id'] for r in rows]==[90] and counts['scope']==1
    rows,_=rank_candidates(restricted,[item(90),item(91,adult=True)])
    assert [r['id'] for r in rows]==[91]

def test_manga_reading_media_and_explicit_relations(data):
    db,store,aid,sid,_=data
    store.match(sid,item(22,'Drama','MANGA'));store.set_favorite(sid,True)
    db.set_metadata(aid,11,item(11,'Fantasy',relations={'edges':[{'relationType':'ADAPTATION','node':{'id':99,'type':'MANGA'}}]}));db.set_favorite(aid,True)
    profile=build_profile(Organization(db,store),'MANGA',now=NOW)
    assert set(profile.genres)=={'Drama'} and 99 in profile.relations
    rows,counts=rank_candidates(profile,[item(99,'Other','MANGA'),item(100,'Fantasy','MANGA'),item(101,'Drama','MANGA'),item(102),item(22,kind='MANGA')])
    assert rows[0]['id']==99 and 'Explicit AniList relation' in rows[0]['_recommendation_reason']
    assert counts['media_type']==1 and counts['already_local']==1
    assert next(r for r in rows if r['id']==100)['_recommendation_reason'] is None

def test_stable_sparse_candidates_and_readonly(data):
    db,store,*_=data;before=db.connection.total_changes
    profile=build_profile(Organization(db,store),now=NOW)
    candidates=[remote(80),remote(70),{**remote(90),'averageScore':None,'popularity':None}]
    first,_=rank_candidates(profile,candidates);second,_=rank_candidates(profile,list(reversed(candidates)))
    assert first==second and [r['id'] for r in first]==[70,80,90]
    assert not any(r['_recommendation_reason'] for r in first)
    assert db.connection.total_changes==before

def test_collection_aliases_do_not_amplify_signal(data):
    db,store,aid,*_=data;db.set_metadata(aid,11,item(11));db.set_favorite(aid,True)
    cid=db.create_collection('Fantasy');db.add_to_collection(cid,aid)
    baseline=build_profile(Organization(db,store),now=NOW).genres['Fantasy']
    db.connection.execute('INSERT OR IGNORE INTO collection_entries(collection_id,entity_key) VALUES(?,?)',(cid,f'local:{aid}'));db.connection.commit()
    assert build_profile(Organization(db,store),now=NOW).genres['Fantasy']==baseline

def test_runtime_profile_cache_mutations(window):
    w,qt,aid,*_=window
    first=w._recommendation_profile('normal','ANIME')
    assert w._recommendation_profile('normal','ANIME') is first
    w.db.set_setting('unrelated','1')
    assert w._recommendation_profile('normal','ANIME') is first
    w.db.set_favorite(aid,True)
    assert w._recommendation_profile('normal','ANIME').fingerprint!=first.fingerprint

def test_runtime_discover_reason_cache_manga_and_lock(window,monkeypatch):
    w,qt,aid,sid,_=window;requests=[]
    w.db.set_metadata(aid,11,item(11));w.db.set_favorite(aid,True)
    monkeypatch.setattr(w,'_request_discover_filters',lambda *_:None)
    def request(params,success,failure):
        requests.append(dict(params));kind=params.get('media_type','ANIME')
        result={'items':[item(101,kind=kind),item(101,kind=kind),item(11,kind=kind)],'pageInfo':{'hasNextPage':False}}
        QTimer.singleShot(0,lambda:success(result))
    monkeypatch.setattr(w,'_request_discover_page',request)
    w.show_discover();qt.processEvents();qt.processEvents()
    page=w.stack.currentWidget()
    assert page.findChild(QLabel,'recommendationReason') is not None
    assert all(card.item['id']!=11 for card in page.findChildren(SeasonCard) if card.findChild(QLabel,'recommendationReason'))
    count=len(requests);w.show_home();w.show_discover();qt.processEvents()
    assert w.stack.currentWidget() is page and len(requests)==count
    w.show_discover(False,'MANGA');qt.processEvents();qt.processEvents()
    assert w._route_snapshot()==('normal_discover','MANGA')
    assert all(card.item['type']=='MANGA' for card in w.stack.currentWidget().findChildren(SeasonCard))
    page=w.stack.currentWidget();w.show_discover(True);assert w.stack.currentWidget() is page
    w.show_discover_all('Popular',{'restricted':True});assert w.stack.currentWidget() is page
    w.db.set_setting('restricted_unlocked','1')
    w.show_remote_anilist(remote(999),'Restricted');assert w.stack.currentWidget() is page

def test_runtime_saved_reason_is_transient(window):
    w,qt,*_=window;w.set_saved(item(120,_recommendation_reason='Not persistent'),True)
    row=w.db.connection.execute("SELECT * FROM manual_status WHERE entity_key='anilist:120'").fetchone()
    assert row['status']=='Planning' and '_recommendation_reason' not in row['metadata_json']
    assert not w.db.is_saved(120)

def test_runtime_recommendation_pages_append_without_reordering(window,monkeypatch):
    w,qt,aid,*_=window;requests=[]
    w.db.set_metadata(aid,11,item(11));w.db.set_favorite(aid,True)
    monkeypatch.setattr(w,'_request_discover_filters',lambda *_:None)
    def request(params,success,failure):
        page=params['page'];requests.append(page)
        values=[item(i) for i in range(100,125)] if page==1 else [item(100),*[item(i) for i in range(200,225)],item(11)]
        QTimer.singleShot(0,lambda:success({'items':values,'pageInfo':{'hasNextPage':page==1}}))
    monkeypatch.setattr(w,'_request_discover_page',request)
    w.show_discover_all('Recommended For You',{'genres':['Fantasy']});QTest.qWait(300)
    page=w.stack.currentWidget();grid=page.findChild(ResponsiveSeasonGrid);before=list(grid.cards)
    assert len(before)==25
    scroll=next(scroll for scroll in page.findChildren(QScrollArea) if scroll.isAncestorOf(grid));bar=scroll.verticalScrollBar()
    assert bar.maximum()>0,(w.size(),scroll.size(),scroll.widget().size(),grid.size(),grid._columns)
    bar.setValue(bar.maximum());QTest.qWait(50)
    assert requests==[1,2] and len(grid.cards)==50
    assert grid.cards[:25]==before
    assert len({card.item['id'] for card in grid.cards})==50

def test_consumption_reason_and_manga_completion(data):
    db,store,aid,sid,_=data;db.set_metadata(aid,11,item(11))
    media_id=db.connection.execute('SELECT id FROM media WHERE anime_id=?',(aid,)).fetchone()[0]
    db.set_watched(media_id,True)
    profile=build_profile(Organization(db,store),now=NOW)
    rows,_=rank_candidates(profile,[item(100)])
    assert rows[0]['_recommendation_reason']=='Because you watched Shared 11'
    store.match(sid,item(22,'Drama','MANGA'));store.set_status(sid,'Watching')
    profile=build_profile(Organization(db,store),'MANGA',now=NOW)
    rows,_=rank_candidates(profile,[item(110,'Drama','MANGA')])
    assert rows[0]['_recommendation_reason']=='Similar to a title you are reading'

def test_relation_cards_require_verified_scope(data):
    db,store,aid,*_=data
    edges=[{'relationType':'ADAPTATION','node':item(90,kind='MANGA')},
           {'relationType':'ADAPTATION','node':{'id':91,'type':'MANGA'}},
           {'relationType':'ADAPTATION','node':item(92,kind='MANGA',adult=True)}]
    db.set_metadata(aid,11,item(11,relations={'edges':edges}));db.set_favorite(aid,True)
    profile=build_profile(Organization(db,store),'MANGA',now=NOW)
    assert [row['id'] for row in profile.related_candidates()]==[90]
    assert 91 in profile.relations

def test_runtime_landing_fills_filtered_recommendation_shelf(window,monkeypatch):
    w,qt,aid,*_=window;requested=[]
    w.db.set_metadata(aid,11,item(11));w.db.set_favorite(aid,True)
    monkeypatch.setattr(w,'_request_discover_filters',lambda *_:None)
    def request(params,success,failure):
        recommended=params['_context']=='Discover Recommended For You'
        number=params['page']
        if recommended:requested.append(number)
        values=[item(11)] if recommended and number==1 else [item(i) for i in range(100,107)]
        QTimer.singleShot(0,lambda:success({'items':values,'pageInfo':{'hasNextPage':recommended and number==1}}))
    monkeypatch.setattr(w,'_request_discover_page',request)
    w.show_discover();QTest.qWait(300)
    assert requested==[1,2]
    assert len(w.stack.currentWidget().findChildren(QLabel,'recommendationReason'))==7

def test_runtime_refresh_evicts_only_matching_recommendation_pages(window,monkeypatch):
    import json
    w,qt,aid,*_=window;w.db.set_metadata(aid,11,item(11));w.db.set_favorite(aid,True)
    params={'page':1,'is_adult':False,'media_type':'ANIME',**w._recommendation_profile('normal','ANIME').query()}
    key=json.dumps(params,sort_keys=True,separators=(',',':'));w._discover_cache[key]={'items':[]}
    other='unrelated-cache-sentinel';w._discover_cache[other]={'items':['retained']}
    monkeypatch.setattr(w,'show_discover',lambda *_:None)
    w._refresh_recommendations(False,'ANIME')
    assert key not in w._discover_cache and w._discover_cache[other]['items']==['retained']
