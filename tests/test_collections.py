import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anime_hub.database import Database


def add_anime(db, identity="show", title="Show"):
    anime_id=db.upsert_anime(identity,title,"","Other",f"C:/{title}")
    media_path=db.path.parent/f"{identity}.mkv"; media_path.touch()
    media=SimpleNamespace(path=media_path,kind="episode",season=1,episode=1)
    db.upsert_media(anime_id,media); db.connection.commit()
    return anime_id


def test_collection_crud_and_many_to_many(tmp_path):
    db=Database(tmp_path/"library.db"); first=add_anime(db,"a","Alpha"); second=add_anime(db,"b","Beta")
    romance=db.create_collection("  Romance  "); comfort=db.create_collection("Comfort")
    assert db.add_to_collection(romance,first) is True
    assert db.add_to_collection(romance,first) is False
    assert db.add_to_collection(comfort,first) is True
    assert db.add_to_collection(romance,second) is True
    assert db.anime_collection_ids(first)=={romance,comfort}
    assert [row["id"] for row in db.collection_anime(romance,"Title")]==[first,second]
    db.rename_collection(romance,"Romance Archive")
    assert db.collection(romance)["name"]=="Romance Archive"
    db.set_collection_description(romance,"  Fast cars and faster anime.  ")
    assert db.collection(romance)["description"]=="Fast cars and faster anime."
    db.set_collection_description(romance,"")
    assert db.collection(romance)["description"]==""
    assert db.remove_from_collection(romance,first) is True
    assert db.anime(first) is not None
    db.delete_collection(romance)
    assert db.collection(romance) is None and db.anime(second) is not None


def test_collection_names_are_trimmed_nonempty_and_unique(tmp_path):
    db=Database(tmp_path/"library.db"); db.create_collection("Romance")
    with pytest.raises(ValueError): db.create_collection("   ")
    with pytest.raises(ValueError): db.create_collection(" romance ")


def test_v0613_migration_preserves_existing_state(tmp_path):
    import sqlite3
    path=tmp_path/"old.db"; connection=sqlite3.connect(path)
    connection.executescript("""CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE anime(id INTEGER PRIMARY KEY,identity TEXT UNIQUE NOT NULL,title TEXT NOT NULL,alt_title TEXT DEFAULT '',category TEXT DEFAULT 'Other',root_path TEXT NOT NULL,anilist_id INTEGER,metadata_json TEXT DEFAULT '{}',added_at TEXT DEFAULT CURRENT_TIMESTAMP,favorite INTEGER NOT NULL DEFAULT 0,last_watched_episode INTEGER,last_watched_at TEXT);
    CREATE TABLE media(id INTEGER PRIMARY KEY,anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,path TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,season INTEGER,episode INTEGER,detected_kind TEXT NOT NULL,present INTEGER DEFAULT 1,modified REAL DEFAULT 0,watched INTEGER NOT NULL DEFAULT 0,watched_at TEXT,resume_position_ms INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE overrides(path TEXT PRIMARY KEY,kind TEXT NOT NULL);
    INSERT INTO anime(id,identity,title,root_path,anilist_id,favorite,last_watched_episode) VALUES(1,'stable','Stable Show','C:/Stable',42,1,7);
    INSERT INTO media(id,anime_id,path,kind,season,episode,detected_kind,watched,resume_position_ms) VALUES(1,1,'C:/Stable/01.mkv','episode',1,1,'episode',1,12345);""")
    connection.commit(); connection.close()
    db=Database(path); anime=db.anime(1); media=db.media_by_id(1)
    assert (anime["anilist_id"],anime["favorite"],anime["last_watched_episode"])==(42,1,7)
    assert (media["watched"],media["resume_position_ms"])==(1,12345)
    collection=db.create_collection("Migrated"); assert db.add_to_collection(collection,1)


def test_rescan_retains_membership_for_stable_identity(tmp_path):
    db=Database(tmp_path/"library.db"); anime_id=add_anime(db); collection=db.create_collection("Keep")
    db.add_to_collection(collection,anime_id); db.start_scan(); add_anime(db); db.finish_scan()
    assert db.anime_collection_ids(anime_id)=={collection}
