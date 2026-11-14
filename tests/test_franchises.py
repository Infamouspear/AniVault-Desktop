from pathlib import Path
from types import SimpleNamespace

import pytest

from anime_hub.database import Database
import anime_hub.anilist_integration as anilist


def add_anime(db,index):
    identity=f"initial-d-{index}"; path=db.path.parent/f"{identity}.mkv"; path.touch()
    anime_id=db.upsert_anime(identity,f"Initial D Stage {index}","","Other",str(path.parent))
    db.upsert_media(anime_id,SimpleNamespace(path=path,kind="episode",season=1,episode=1)); db.set_metadata(anime_id,1000+index,{"id":1000+index,"anilist_user_progress":index})
    db.set_favorite(anime_id,index==1); db.set_watched(db.media(anime_id)[0]["id"],True); db.set_resume_position(db.media(anime_id)[0]["id"],index*1000)
    return anime_id


def test_initial_d_franchise_keeps_independent_state_and_manual_order(tmp_path):
    db=Database(tmp_path/"vault.db"); ids=[add_anime(db,i) for i in range(1,12)]; collection=db.create_collection("Racing");db.add_to_collection(collection,ids[0])
    franchise=db.create_franchise("Initial D","Stages and Legend movies")
    for anime_id in ids: assert db.add_to_franchise(franchise,anime_id)
    assert [row["id"] for row in db.franchise_anime(franchise)]==ids
    assert db.move_franchise_item(franchise,ids[-1],-1)
    expected=ids[:-2]+[ids[-1],ids[-2]]; assert [row["id"] for row in db.franchise_anime(franchise)]==expected
    db.connection.close(); db=Database(tmp_path/"vault.db")
    assert [row["id"] for row in db.franchise_anime(franchise)]==expected
    first=db.anime(ids[0]); media=db.media(ids[0])[0]
    assert first["anilist_id"]==1001 and first["favorite"]==1
    assert media["watched"]==1 and db.anime_collection_ids(ids[0])=={collection}


def test_franchise_is_many_to_one_and_delete_is_non_destructive(tmp_path):
    db=Database(tmp_path/"vault.db"); anime_id=add_anime(db,1); first=db.create_franchise("Initial D"); second=db.create_franchise("Wrong Group")
    assert db.add_to_franchise(first,anime_id)
    with pytest.raises(ValueError): db.add_to_franchise(second,anime_id)
    db.delete_franchise(first)
    assert db.anime(anime_id) is not None and db.media(anime_id)


def test_rescan_preserves_franchise_membership_and_order(tmp_path):
    db=Database(tmp_path/"vault.db"); ids=[add_anime(db,i) for i in range(1,4)]; franchise=db.create_franchise("Initial D")
    for anime_id in ids:db.add_to_franchise(franchise,anime_id)
    db.start_scan()
    for i in range(1,4):add_anime(db,i)
    db.finish_scan(); assert [row["id"] for row in db.franchise_anime(franchise)]==ids


def test_anilist_relations_are_one_hop_filtered_and_deduped(monkeypatch):
    calls=[]
    def fake_graphql(query,variables):
        calls.append(variables["id"])
        return {"Media":{"relations":{"edges":[
            {"relationType":"SEQUEL","node":{"id":2,"type":"ANIME","title":{"english":"Second"}}},
            {"relationType":"CHARACTER","node":{"id":3,"type":"ANIME","title":{"english":"Character"}}},
            {"relationType":"PREQUEL","node":{"id":4,"type":"MANGA","title":{"english":"Manga"}}},
        ]}}}
    monkeypatch.setattr(anilist,"graphql",fake_graphql)
    result=anilist.fetch_anime_relations([1,1])
    assert calls==[1] and [(item["id"],item["relationType"]) for item in result]==[(2,"SEQUEL")]
