import sqlite3
from pathlib import Path
from types import SimpleNamespace

from anime_hub.database import Database


def media(path, episode, kind="episode"):
    path.write_bytes(b"test")
    return SimpleNamespace(path=path, kind=kind, season=1, episode=episode)


def make_series(tmp_path, episodes=3):
    db=Database(tmp_path/"hub.db")
    anime_id=db.upsert_anime("show","Show","","Watching",str(tmp_path/"Show"),"Show","Show")
    for number in range(1,episodes+1): db.upsert_media(anime_id,media(tmp_path/f"e{number}.mkv",number))
    db.connection.commit()
    return db,anime_id


def test_old_database_migrates_without_losing_rows(tmp_path):
    path=tmp_path/"old.db"; connection=sqlite3.connect(path)
    connection.executescript("""CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE anime(id INTEGER PRIMARY KEY,identity TEXT UNIQUE NOT NULL,title TEXT NOT NULL,alt_title TEXT DEFAULT '',category TEXT DEFAULT 'Other',root_path TEXT NOT NULL,anilist_id INTEGER,metadata_json TEXT DEFAULT '{}',added_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE media(id INTEGER PRIMARY KEY,anime_id INTEGER NOT NULL,path TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,season INTEGER,episode INTEGER,detected_kind TEXT NOT NULL,present INTEGER DEFAULT 1,modified REAL DEFAULT 0);
      CREATE TABLE overrides(path TEXT PRIMARY KEY,kind TEXT NOT NULL);
      INSERT INTO anime(identity,title,root_path) VALUES('show','Show','C:/Show');
      INSERT INTO media(anime_id,path,kind,episode,detected_kind) VALUES(1,'C:/Show/e1.mkv','episode',1,'episode');""")
    connection.commit(); connection.close()
    db=Database(path)
    assert db.anime(1)["favorite"]==0
    assert db.media(1)[0]["watched"]==0


def test_watch_progress_continue_recent_and_unwatch(tmp_path):
    db,anime_id=make_series(tmp_path)
    first=db.media(anime_id)[0]; db.set_watched(first["id"],True)
    row=db.anime_list()[0]
    assert (row["watched_count"],row["episode_count"])==(1,3)
    assert db.next_unwatched(anime_id)["episode"]==2
    assert db.continue_watching()[0]["id"]==anime_id
    assert db.recently_watched()[0]["last_watched_episode"]==1
    db.set_watched(first["id"],False)
    assert db.anime(anime_id)["last_watched_at"] is None


def test_bulk_only_changes_normal_episodes_and_favorite_persists(tmp_path):
    db,anime_id=make_series(tmp_path,2)
    db.upsert_media(anime_id,media(tmp_path/"extra.mkv",None,"special")); db.connection.commit()
    db.set_all_watched(anime_id,True); db.set_favorite(anime_id,True)
    rows=db.media(anime_id)
    assert all(row["watched"] for row in rows if row["kind"]=="episode")
    assert all(not row["watched"] for row in rows if row["kind"]!="episode")
    assert db.anime_list()[0]["favorite"]==1
    assert db.continue_watching()==[]


def test_upsert_rescan_preserves_watch_state(tmp_path):
    db,anime_id=make_series(tmp_path,1); row=db.media(anime_id)[0]
    db.set_watched(row["id"],True); db.start_scan()
    db.upsert_media(anime_id,media(tmp_path/"e1.mkv",1)); db.finish_scan()
    assert db.media(anime_id)[0]["watched"]==1


def test_flattened_root_move_preserves_match_favorite_watch_and_resume(tmp_path):
    db,anime_id=make_series(tmp_path,1); original=db.media(anime_id)[0]
    db.set_metadata(anime_id,123,{"id":123,"title":{"english":"Show"}}); db.set_favorite(anime_id,True)
    db.set_watched(original["id"],True); db.set_watched(original["id"],False); db.set_resume_position(original["id"],42000)
    moved_root=tmp_path/"Flat Show"; moved_root.mkdir(); moved=moved_root/"e1.mkv"; moved.write_bytes(b"test")
    db.start_scan(); db.upsert_anime("show","Show","","Other",str(moved_root),"Flat Show","Show")
    db.upsert_media(anime_id,SimpleNamespace(path=moved,kind="episode",season=1,episode=1)); db.finish_scan()
    anime=db.anime(anime_id); media_row=db.media(anime_id)[0]
    assert anime["anilist_id"]==123 and anime["favorite"]==1 and anime["root_path"]==str(moved_root)
    assert media_row["id"]==original["id"] and media_row["resume_position_ms"]==42000


def test_automatic_watch_fills_earlier_normal_episodes_only(tmp_path):
    db,anime_id=make_series(tmp_path,12)
    rows=db.media(anime_id); db.set_watched(rows[0]["id"],True)
    db.set_watched(rows[1]["id"],True); db.set_watched(rows[2]["id"],True); db.set_watched(rows[3]["id"],True)
    special=media(tmp_path/"special.mkv",1,"special"); db.upsert_media(anime_id,special); db.connection.commit()
    episode_12=next(row for row in db.media(anime_id) if row["kind"]=="episode" and row["episode"]==12)
    db.set_watched_through(episode_12["id"])
    refreshed=db.media(anime_id)
    assert sum(row["watched"] for row in refreshed if row["kind"]=="episode")==12
    assert not next(row for row in refreshed if row["kind"]=="special")["watched"]
    assert db.continue_watching()==[]
    assert db.recently_watched()[0]["last_watched_episode"]==12


def test_manual_watch_does_not_fill_gaps(tmp_path):
    db,anime_id=make_series(tmp_path,5)
    episode_5=next(row for row in db.media(anime_id) if row["episode"]==5)
    db.set_watched(episode_5["id"],True)
    watched=[row["episode"] for row in db.media(anime_id) if row["watched"]]
    assert watched==[5]
    assert db.next_unwatched(anime_id)["episode"]==1


def test_resume_position_and_adjacent_episode_persist(tmp_path):
    db,anime_id=make_series(tmp_path,episodes=3)
    rows=db.media(anime_id); middle=rows[1]
    db.set_resume_position(middle["id"],761000)
    assert db.media_by_id(middle["id"])["resume_position_ms"]==761000
    assert db.adjacent_episode(anime_id,middle["id"],-1)["episode"]==1
    assert db.adjacent_episode(anime_id,middle["id"],1)["episode"]==3
    db.set_watched(middle["id"],True)
    assert db.media_by_id(middle["id"])["resume_position_ms"]==0
