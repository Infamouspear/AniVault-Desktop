from unittest.mock import patch

from anime_hub.anilist_integration import fetch_discover_catalog, fetch_discover_page, fetch_anime_relations
from anime_hub.database import Database
from anime_hub.metadata import LookupReport
from anime_hub.scanner import scan


def test_discover_uses_expected_stable_sources(monkeypatch):
    calls=[]
    def fake(season,year,page,status,sort):
        calls.append((season,year,page,status,sort))
        return {"items":[{"id":len(calls)}]}
    monkeypatch.setattr("anime_hub.anilist_integration.fetch_season_page",fake)
    catalog=fetch_discover_catalog("FALL",2026)
    assert list(catalog)==["Trending","Popular","Upcoming","Top Rated"]
    assert calls[0]==(None,None,1,None,"TRENDING_DESC")
    assert calls[1]==(None,None,1,None,"POPULARITY_DESC")
    assert calls[2]==("WINTER",2027,1,"NOT_YET_RELEASED","POPULARITY_DESC")
    assert calls[3]==(None,None,1,None,"SCORE_DESC")


def test_relation_batch_is_one_http_request(monkeypatch):
    calls=[]
    def fake(query,variables):
        calls.append(query)
        return {"m0":{"relations":{"edges":[]}},"m1":{"relations":{"edges":[]}}}
    monkeypatch.setattr("anime_hub.anilist_integration.graphql",fake)
    assert fetch_anime_relations([10,11])==[]
    assert len(calls)==1 and "m0: Media(id:10" in calls[0] and "m1: Media(id:11" in calls[0]


def test_single_file_release_becomes_playable_but_extras_do_not(tmp_path):
    root=tmp_path/"Anime"; ova=root/"Initial D Extra Stage 2"; ova.mkdir(parents=True)
    (ova/"Initial D Extra Stage 2.mkv").touch()
    extras=root/"Example Show"/"Extras"; extras.mkdir(parents=True)
    (extras/"Bonus.mkv").touch()
    db=Database(tmp_path/"vault.db")
    unmatched=LookupReport("",True,200,"",[],None,0.0,"no candidate")
    with patch("anime_hub.scanner.lookup_anilist",return_value=unmatched): scan(root,db)
    rows={row["source_folder_name"]:row for row in db.anime_list()}
    ova_media=db.media(rows["Initial D Extra Stage 2"]["id"])
    assert [(item["kind"],item["episode"]) for item in ova_media]==[("episode",1)]
    if "Example Show" in rows:
        assert all(item["kind"]!="episode" for item in db.media(rows["Example Show"]["id"]))


def test_discover_advanced_query_keeps_filters_and_pagination(monkeypatch):
    captured={}
    def fake(query,variables,include_http_status=False):
        captured.update(query=query,variables=variables)
        return ({"Page":{"pageInfo":{"currentPage":2,"hasNextPage":True},"media":[{"id":42}]}},200)
    monkeypatch.setattr("anime_hub.anilist_integration.graphql",fake)
    result=fetch_discover_page(2,"initial",["Romance","Drama"],["School"],2020,2026,"FALL",["TV"],"FINISHED","SCORE_DESC")
    assert result["items"]==[{"id":42}] and result["pageInfo"]["hasNextPage"] is True
    assert captured["variables"]["page"]==2 and captured["variables"]["genres"]==["Romance","Drama"]
    assert captured["variables"]["tags"]==["School"] and captured["variables"]["formats"]==["TV"]
    assert "genre_in:$genres" in captured["query"] and "tag_in:$tags" in captured["query"]


def test_single_primary_video_wins_over_known_extras_and_more_containers(tmp_path):
    root=tmp_path/"Anime"; release=root/"Initial D Battle Stage"; release.mkdir(parents=True)
    main=release/"Initial D Battle Stage.m2ts"; main.touch()
    (release/"NCOP.mkv").touch(); (release/"Trailer.mp4").touch()
    db=Database(tmp_path/"vault.db"); unmatched=LookupReport("",True,200,"",[],None,0.0,"no candidate")
    with patch("anime_hub.scanner.lookup_anilist",return_value=unmatched): scan(root,db)
    row=db.anime_list()[0]; media={item["path"]:item for item in db.media(row["id"])}
    assert media[str(main)]["kind"]=="episode" and media[str(main)]["episode"]==1
    assert media[str(release/"NCOP.mkv")]["kind"]=="special"
    assert media[str(release/"Trailer.mp4")]["kind"]=="special"
