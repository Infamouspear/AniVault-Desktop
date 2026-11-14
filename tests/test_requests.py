from types import SimpleNamespace
import pytest
from anime_hub.database import Database
from anime_hub.requests_store import Requests


def test_discover_dedup_and_persistence(tmp_path):
    path=tmp_path/'vault.db';db=Database(path);store=Requests(db)
    item={'id':123,'type':'ANIME','isAdult':False,'title':{'english':'A'}}
    key=store.discover(item)
    assert store.discover({**item,'title':{'romaji':'Alias'}})==key
    assert store.discover({**item,'id':124})!=key
    assert not db.manual_status('normal',anilist_id=123)
    store.update(key,'Approved','Keep this')
    store.add('feedback','Missing button','Bug report',details='Steps')
    db.connection.close()
    db=Database(path)
    try:
        rows=Requests(db).all()
        assert [(r['kind'],r['status']) for r in rows]==[('feedback','New'),('anime','Requested'),('anime','Approved')]
        assert rows[-1]['notes']=='Keep this'
    finally:db.connection.close()


def test_availability_requires_exact_normal_match_and_remove_is_independent(tmp_path):
    db=Database(tmp_path/'vault.db');store=Requests(db)
    try:
        key=store.add('anime','Manual',identifier='42')
        with pytest.raises(ValueError,match='exact'):store.update(key,'Available','')
        with pytest.raises(ValueError):store.discover({'id':42,'type':'ANIME','isAdult':True})
        aid=db.upsert_anime('stable','Demo','','Other',str(tmp_path))
        path=tmp_path/'ep.mkv';path.write_bytes(b'x')
        db.upsert_media(aid,SimpleNamespace(path=path,kind='episode',season=1,episode=1))
        db.set_metadata(aid,42,{'isAdult':False})
        store.update(key,'Available','Matched')
        db.finish_scan()
        assert store.all()[0]['status']=='Available'
        store.remove(key)
        assert db.anime(aid) and path.exists()
    finally:db.connection.close()


def test_discover_button_updates_existing_request(monkeypatch,tmp_path):
    from PySide6.QtWidgets import QApplication,QLabel,QPushButton
    from anime_hub import app
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    window=app.Window()
    try:
        window.show_home()
        item={'id':345,'type':'ANIME','isAdult':False,'title':{'english':'Demo'}}
        card=window._make_discover_card(item,{})
        action=next(b for b in card.findChildren(QPushButton) if b.text()=='Request Anime')
        card.show()
        QApplication.processEvents()
        poster = next(label for label in card.findChildren(QLabel) if label.text() == 'LOADING ARTWORK')
        title = card.findChild(QLabel, 'cardTitle')
        assert poster.geometry().bottom() < title.geometry().top()
        assert title.geometry().bottom() < action.geometry().top()
        assert card.contentsRect().contains(action.geometry())
        action.click()
        assert action.text()=='Requested'
        action.click();QApplication.processEvents()
        assert window.current_view=='requests'
        assert len(Requests(window.db).all())==1
        card.deleteLater()
    finally:window.close()


def test_in_focus_request_stays_in_sync(monkeypatch,tmp_path):
    from PySide6.QtWidgets import QPushButton
    from anime_hub import app
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    window=app.Window()
    try:
        window.show_home()
        item={'id':456,'type':'ANIME','isAdult':False,'title':{'english':'Rail demo'}}
        window._select_hub_entity('normal','anilist:456',item)
        button=window.context_rail.findChild(QPushButton,'focusRequest')
        assert button and button.text()=='Request Anime'
        button.click()
        store=Requests(window.db)
        row,=store.all()
        assert row['provider_id']==456 and button.text()=='Requested'
        store.update(row['id'],'Approved','')
        window.requests_changed.emit()
        assert button.text()=='Approved'
        assert not window.db.manual_status('normal',anilist_id=456)
    finally:window.close()
