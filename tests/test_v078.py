import json
from types import SimpleNamespace

from anime_hub.database import Database


def item(identifier=77,adult=False):
    return {"id":identifier,"title":{"english":"Remote Movie"},"isAdult":adult,"format":"MOVIE","status":"FINISHED"}


def local_anime(db,tmp_path,anilist_id=77):
    anime_id=db.upsert_anime("movie","Remote Movie","","Movies",str(tmp_path/"movie"))
    path=tmp_path/"movie.mkv";path.touch();db.upsert_media(anime_id,SimpleNamespace(path=path,kind="episode",season=1,episode=1))
    db.connection.execute("UPDATE anime SET anilist_id=?,metadata_json=? WHERE id=?",(anilist_id,json.dumps(item(anilist_id)),anime_id));db.connection.commit();return anime_id


def test_manual_status_local_and_remote_scopes_persist(tmp_path):
    path=tmp_path/"vault.db";db=Database(path);anime_id=local_anime(db,tmp_path)
    db.set_manual_status("Paused","normal",anime_id=anime_id)
    db.set_manual_status("Planning","restricted",item=item(88,True))
    assert db.manual_status("normal",anime_id=anime_id)=="Paused"
    assert db.manual_status("restricted",anilist_id=88)=="Planning"
    assert db.manual_status("normal",anilist_id=88) is None
    db.connection.close();db=Database(path)
    assert db.manual_status("normal",anime_id=anime_id)=="Paused"
    assert len(db.status_entries("Planning","restricted"))==1


def test_saved_to_local_transition_keeps_collection_and_status(tmp_path):
    db=Database(tmp_path/"vault.db");remote=item();db.save_title(remote)
    collection=db.create_collection("Movies",scope="normal")
    assert db.add_remote_to_collection(collection,remote)
    db.set_manual_status("Planning","normal",item=remote)
    anime_id=local_anime(db,tmp_path)
    entries=db.collection_entries(collection)
    assert len(entries)==1 and entries[0]["local"]["id"]==anime_id
    assert db.manual_status("normal",anime_id=anime_id)=="Planning"
    assert db.anime_collection_ids(anime_id)=={collection}


def test_collection_and_status_scopes_never_leak(tmp_path):
    db=Database(tmp_path/"vault.db");normal=db.create_collection("Normal Shelf",scope="normal");restricted=db.create_collection("Private Shelf",scope="restricted")
    db.add_remote_to_collection(normal,item(1,False));db.add_remote_to_collection(restricted,item(2,True))
    db.set_manual_status("Watching","normal",item=item(1,False));db.set_manual_status("Watching","restricted",item=item(2,True))
    assert [row["name"] for row in db.collections(scope="normal")]==["Normal Shelf"]
    assert [row["name"] for row in db.collections(scope="restricted")]==["Private Shelf"]
    assert [row["entity_key"] for row in db.status_entries("Watching","normal")]==["anilist:1"]
    assert [row["entity_key"] for row in db.status_entries("Watching","restricted")]==["anilist:2"]


def test_v077_collection_membership_migrates_to_entity_key(tmp_path):
    db=Database(tmp_path/"vault.db");anime_id=local_anime(db,tmp_path,91);collection=db.create_collection("Racing")
    db.connection.execute("DELETE FROM collection_entries");db.connection.execute("INSERT INTO collection_items(collection_id,anime_id) VALUES(?,?)",(collection,anime_id));db.connection.commit();db.connection.close()
    reopened=Database(tmp_path/"vault.db")
    assert reopened.entity_collection_ids("anilist:91")=={collection}
