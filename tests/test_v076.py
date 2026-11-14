from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import patch

from anime_hub.database import Database
from anime_hub.metadata import LookupReport
from anime_hub.scanner import scan


def remote_item(anilist_id=101,title="Saved Show"):
    return {"id":anilist_id,"title":{"english":title},"seasonYear":2026,"format":"TV",
            "genres":["Romance"],"tags":[{"name":"School","rank":80}],"averageScore":82,"popularity":1234}


def test_saved_persists_and_local_match_does_not_duplicate(tmp_path):
    path=tmp_path/"vault.db"; db=Database(path); item=remote_item(); db.save_title(item); db.connection.close(); db=Database(path)
    saved=db.saved_titles(); assert len(saved)==1 and json.loads(saved[0]["metadata_json"])["id"]==101
    media_path=tmp_path/"saved.mkv"; media_path.touch(); anime_id=db.upsert_anime("saved-show","Saved Show","","Other",str(tmp_path)); db.upsert_media(anime_id,SimpleNamespace(path=media_path,kind="episode",season=1,episode=1)); db.set_metadata(anime_id,101,item)
    assert len(db.anime_list())==1 and len(db.saved_titles())==1 and db.is_saved(101)
    assert db.unsave_title(101) and db.anime(anime_id) is not None and db.media(anime_id)


def test_saved_sorting(tmp_path):
    db=Database(tmp_path/"vault.db"); db.save_title(remote_item(1,"Zulu")); db.save_title(remote_item(2,"Alpha"))
    assert [row["title"] for row in db.saved_titles("Title")]==["Alpha","Zulu"]


def test_multiple_unnumbered_primary_videos_become_stable_episodes(tmp_path):
    root=tmp_path/"Anime"; release=root/"Initial D Extra Stage"; release.mkdir(parents=True)
    second=release/"Second OVA.mkv"; first=release/"First OVA.mkv"; second.touch(); first.touch(); (release/"NCED.mkv").touch(); (release/"Trailer.mp4").touch()
    db=Database(tmp_path/"vault.db"); unmatched=LookupReport("",True,200,"",[],None,0.0,"no candidate")
    with patch("anime_hub.scanner.lookup_anilist",return_value=unmatched):scan(root,db)
    row=db.anime_list()[0]; media=db.media(row["id"]); episodes=[item for item in media if item["kind"]=="episode"]
    assert [(item["episode"],Path(item["path"]).name) for item in episodes]==[(1,"First OVA.mkv"),(2,"Second OVA.mkv")]
    assert {Path(item["path"]).name for item in media if item["kind"]=="special"}=={"NCED.mkv","Trailer.mp4"}
    db.set_metadata(row["id"],999,{"id":999,"title":{"english":"Initial D Extra Stage"}})
    with patch("anime_hub.scanner.lookup_anilist") as lookup:scan(root,db)
    assert [(item["episode"],Path(item["path"]).name) for item in db.media(row["id"]) if item["kind"]=="episode"]==[(1,"First OVA.mkv"),(2,"Second OVA.mkv")]
    lookup.assert_not_called()
