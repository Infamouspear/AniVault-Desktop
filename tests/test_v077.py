import json
import sqlite3

from anime_hub import anilist_integration
from anime_hub.database import Database


def adult_item(identifier=10, adult=True):
    return {"id":identifier,"title":{"english":f"Title {identifier}"},"isAdult":adult,"genres":["Drama"]}


def test_saved_scopes_are_independent_and_persistent(tmp_path):
    path=tmp_path/"vault.db"; db=Database(path)
    db.save_title(adult_item(10,True),"restricted")
    db.save_title(adult_item(11,False),"normal")
    assert db.is_saved(10,"restricted") and not db.is_saved(10,"normal")
    assert db.is_saved(11,"normal") and not db.is_saved(11,"restricted")
    db.connection.close(); reopened=Database(path)
    assert [row["anilist_id"] for row in reopened.saved_titles(scope="restricted")]==[10]
    assert [row["anilist_id"] for row in reopened.saved_titles(scope="normal")]==[11]


def test_legacy_saved_migration_assigns_normal_scope(tmp_path):
    path=tmp_path/"legacy.db"; connection=sqlite3.connect(path)
    connection.execute("CREATE TABLE saved_titles(anilist_id INTEGER PRIMARY KEY,title TEXT,metadata_json TEXT,saved_at TEXT)")
    connection.execute("INSERT INTO saved_titles VALUES(?,?,?,CURRENT_TIMESTAMP)",(7,"Legacy",json.dumps(adult_item(7,False))))
    connection.commit();connection.close()
    db=Database(path)
    assert not db.is_saved(7,"normal")
    assert db.connection.execute("SELECT status FROM manual_status WHERE scope='normal' AND entity_key='anilist:7'").fetchone()[0]=='Planning'
    assert db.connection.execute('SELECT title FROM normal_saved_migration_archive WHERE anilist_id=7').fetchone()[0]=='Legacy'
    assert not db.is_saved(7,"restricted")


def test_discover_query_sends_explicit_adult_scope(monkeypatch):
    calls=[]
    def fake(query,variables,include_http_status=False):
        calls.append((query,variables));return ({"Page":{"media":[],"pageInfo":{"hasNextPage":False}}},200)
    monkeypatch.setattr(anilist_integration,"graphql",fake)
    result=anilist_integration.fetch_discover_page(is_adult=True)
    assert result["query"]["isAdult"] is True
    assert calls[0][1]["adult"] is True
    assert "isAdult:$adult" in calls[0][0]


def test_normal_filter_options_hide_explicit_adult_metadata(monkeypatch):
    monkeypatch.setattr(anilist_integration,"graphql",lambda *_args,**_kwargs:{
        "GenreCollection":["Drama","Hentai"],
        "MediaTagCollection":[{"name":"School","isAdult":False},{"name":"Adult Tag","isAdult":True},{"name":"Hentai","isAdult":False}],
    })
    normal=anilist_integration.fetch_discover_filters(False)
    restricted=anilist_integration.fetch_discover_filters(True)
    assert normal["genres"]==["Drama"]
    assert [tag["name"] for tag in normal["tags"]]==["School"]
    assert "Hentai" in restricted["genres"]
    assert len(restricted["tags"])==3
