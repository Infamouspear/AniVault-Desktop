import json

from PySide6.QtWidgets import QApplication, QLabel

from anime_hub import anilist_integration
from anime_hub import app as app_module
from anime_hub.app import ResponsiveSeasonGrid, SeasonCard, StatusCountLabel, Window
from anime_hub.database import Database


def media(identifier, media_type="ANIME", adult=True, title=None):
    return {
        "id": identifier,
        "type": media_type,
        "isAdult": adult,
        "title": {"english": title or f"Title {identifier}"},
        "format": "MANGA" if media_type == "MANGA" else "TV",
        "status": "RELEASING",
        "chapters": 24 if media_type == "MANGA" else None,
        "volumes": 4 if media_type == "MANGA" else None,
    }


def test_discover_manga_query_uses_media_type_and_manga_fields(monkeypatch):
    calls = []

    def fake(query, variables, include_http_status=False):
        calls.append((query, variables))
        return ({"Page": {"media": [], "pageInfo": {"hasNextPage": False}}}, 200)

    monkeypatch.setattr(anilist_integration, "graphql", fake)
    result = anilist_integration.fetch_discover_page(media_type="MANGA", is_adult=True)
    query, variables = calls[0]
    assert variables["mediaType"] == "MANGA"
    assert variables["adult"] is True
    assert "type:$mediaType" in query
    assert "chapters volumes" in query
    assert result["query"]["mediaType"] == "MANGA"


def test_adult_manga_query_supports_country_doujin_and_sparse_score_fallback(monkeypatch):
    calls=[]
    def fake(query,variables,include_http_status=False):
        calls.append((query,variables));return ({"Page":{"media":[{"id":1,"averageScore":None,"chapters":1}],"pageInfo":{"hasNextPage":False}}},200)
    monkeypatch.setattr(anilist_integration,"graphql",fake)
    result=anilist_integration.fetch_discover_page(media_type="MANGA",is_adult=True,country="JP",source="DOUJINSHI",sort=["SCORE_DESC","POPULARITY_DESC"])
    query,variables=calls[0]
    assert variables["mediaType"]=="MANGA" and variables["adult"] is True
    assert variables["country"]=="JP" and variables["source"]=="DOUJINSHI"
    assert variables["sort"]==["SCORE_DESC","POPULARITY_DESC"]
    assert "$country:CountryCode" in query and "countryOfOrigin:$country" in query
    assert "averageScore_greater" not in query and "popularity_greater" not in query
    assert result["items"][0]["averageScore"] is None


def test_restricted_recommendation_profile_never_reads_normal_scope(tmp_path):
    db = Database(tmp_path / "vault.db")
    db.save_title(media(1, "ANIME", False), "normal")
    db.set_manual_status("Watching", "normal", item=media(2, "ANIME", False))
    db.save_title(media(3, "MANGA", True), "restricted")
    db.set_manual_status("Planning", "restricted", item=media(4, "ANIME", True))
    assert {item["id"] for item in db.recommendation_items("restricted")} == {3, 4}
    assert {item["id"] for item in db.recommendation_items("normal")} == {1, 2}


def test_manga_card_uses_reading_and_chapter_metadata():
    QApplication.instance() or QApplication([])
    card = SeasonCard(media(9, "MANGA", True), False, manual_status="Watching")
    assert "Reading" in card.status_label.text()
    assert "24 Chapters" in card.status_label.text()
    assert "episodes" not in " ".join(label.text() for label in card.findChildren(QLabel)).lower()
    card.set_manual_status("Paused")
    assert "Paused" in card.status_label.text()


def test_status_signal_updates_visible_card_and_counts_without_page_reload(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, "APP_DIR", tmp_path)
    window = Window()
    current_page = window.stack.currentWidget()
    item = media(12, "MANGA", True)
    card = SeasonCard(item, False)
    count = QLabel("0 titles")
    window._register_status_card(card, "restricted", "anilist:12")
    window._register_status_count(count, "restricted", "Watching")
    window._set_status("Watching", "restricted", item=item)
    app.processEvents()
    assert window.stack.currentWidget() is current_page
    assert "Reading" in card.status_label.text()
    assert count.text() == "1 titles"
    window._set_status("Dropped", "restricted", item=item)
    app.processEvents()
    assert count.text() == "0 titles"
    assert "Dropped" in card.status_label.text()
    window.close()


def test_collections_counts_requery_store_on_every_activation(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    window=Window();window.show_collections("normal");app.processEvents()
    window._set_status("Planning","normal",item=media(44,"ANIME",False));app.processEvents()
    assert any(label.text()=="1 titles" for label in window.stack.currentWidget().findChildren(StatusCountLabel))
    window.show_home();window.show_collections("normal");app.processEvents()
    labels=window.stack.currentWidget().findChildren(StatusCountLabel)
    assert any(label.status=="Planning" and label.text()=="1 titles" for label in labels)
    window._set_status("Dropped","normal",item=media(44,"ANIME",False));app.processEvents()
    assert next(label for label in labels if label.status=="Planning").text()=="0 titles"
    assert next(label for label in labels if label.status=="Dropped").text()=="1 titles"
    window.close()


def test_discover_sections_dispatch_independently_and_sparse_manga_renders(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    window=Window();window.db.set_setting("restricted_unlocked","1");requests=[]
    monkeypatch.setattr(window,"_request_discover_filters",lambda *_args,**_kwargs:None)
    monkeypatch.setattr(window,"_request_discover_page",lambda params,success,failure:requests.append((params,success,failure)))
    window.show_discover(True,"MANGA")
    assert len(requests)==5
    trending=next(request for request in requests if request[0]["_context"]=="Discover Trending")
    sparse=media(71,"MANGA",True);sparse.update({"averageScore":None,"popularity":None,"chapters":None,"volumes":None})
    trending[1]({"items":[{"type":"MANGA","isAdult":True},sparse],"pageInfo":{"hasNextPage":False}});app.processEvents()
    grid=next(grid for grid in window.stack.currentWidget().findChildren(ResponsiveSeasonGrid) if grid.context=="Discover Trending")
    assert any(isinstance(card,SeasonCard) and card.item["id"]==71 for card in grid.cards)
    assert all(card.item.get("id")!=71 or card.item.get("averageScore") is None for card in grid.cards if isinstance(card,SeasonCard))
    popular=next(request for request in requests if request[0]["_context"]=="Discover Popular")
    popular[2](RuntimeError("simulated"));app.processEvents()
    pop_grid=next(grid for grid in window.stack.currentWidget().findChildren(ResponsiveSeasonGrid) if grid.context=="Discover Popular")
    assert any("temporarily unavailable" in label.text() for label in pop_grid.findChildren(QLabel))
    window.close()
