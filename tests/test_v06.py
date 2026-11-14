import json
import os
from datetime import datetime
from types import SimpleNamespace
import pytest

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QWidget

from anime_hub import app as app_module
from anime_hub import anilist_integration as anilist_module
from anime_hub.anilist_integration import AniListHTTPError, current_anime_season, next_anime_season, season_label
from anime_hub.app import ResponsiveSeasonGrid, SeasonCard, Window
from anime_hub.database import Database
from anime_hub.integrated_player import IntegratedPlayer, PlayerInputOverlay, SeekSlider, VideoSurface


def test_anime_seasons_follow_calendar_quarters():
    assert current_anime_season(datetime(2026,1,5)) == ("WINTER",2026)
    assert current_anime_season(datetime(2026,4,5)) == ("SPRING",2026)
    assert current_anime_season(datetime(2026,7,5)) == ("SUMMER",2026)
    assert current_anime_season(datetime(2026,10,5)) == ("FALL",2026)
    assert season_label("FALL",2026) == "Fall 2026"
    assert next_anime_season("FALL",2026)==("WINTER",2027)
    assert next_anime_season("SUMMER",2026)==("FALL",2026)


def test_anilist_list_merge_never_changes_local_progress(tmp_path):
    db=Database(tmp_path/"vault.db")
    anime_id=db.upsert_anime("show","Show","","Other",str(tmp_path/"Show"))
    db.set_metadata(anime_id,42,{"id":42,"title":{"english":"Show"}})
    db.connection.execute("""INSERT INTO media(anime_id,path,kind,episode,detected_kind,watched)
      VALUES(?,?,?,?,?,?)""",(anime_id,str(tmp_path/"e1.mkv"),"episode",1,"episode",1))
    db.connection.commit()
    changed=db.merge_anilist_list([{"status":"CURRENT","progress":9,"media":{"id":42}}])
    metadata=json.loads(db.anime(anime_id)["metadata_json"])
    assert changed==1 and metadata["anilist_user_progress"]==9
    assert db.anime_progress(anime_id)==(1,1)


def test_anilist_list_merge_ignores_unmatched_entries(tmp_path):
    db=Database(tmp_path/"vault.db")
    anime_id=db.upsert_anime("show","Show","","Other",str(tmp_path/"Show"))
    db.set_metadata(anime_id,42,{"id":42})
    assert db.merge_anilist_list([{"status":"CURRENT","progress":3,"media":{"id":99}}])==0
    assert "anilist_user_progress" not in json.loads(db.anime(anime_id)["metadata_json"])


def test_video_single_click_and_double_click_are_disambiguated():
    QApplication.instance() or QApplication([])
    video=VideoSurface(); video.resize(320,180); video.show()
    play_spy=QSignalSpy(video.toggle_playback); full_spy=QSignalSpy(video.toggle_fullscreen)
    QTest.mouseClick(video,Qt.LeftButton); QTest.qWait(QApplication.doubleClickInterval()+30)
    assert play_spy.count()==1 and full_spy.count()==0
    QTest.mouseDClick(video,Qt.LeftButton); QTest.qWait(QApplication.doubleClickInterval()+30)
    assert play_spy.count()==1 and full_spy.count()==1


def test_native_video_input_overlay_disambiguates_clicks_and_stays_transparent():
    QApplication.instance() or QApplication([])
    layer=PlayerInputOverlay(); layer.resize(640,360); layer.show(); QApplication.processEvents()
    play_spy=QSignalSpy(layer.toggle_playback); full_spy=QSignalSpy(layer.toggle_fullscreen)
    QTest.mouseClick(layer,Qt.LeftButton); QTest.qWait(QApplication.doubleClickInterval()+30)
    assert play_spy.count()==1 and full_spy.count()==0
    QTest.mouseDClick(layer,Qt.LeftButton); QTest.qWait(QApplication.doubleClickInterval()+30)
    assert play_spy.count()==1 and full_spy.count()==1
    assert layer.testAttribute(Qt.WA_TranslucentBackground) and not layer.testAttribute(Qt.WA_TransparentForMouseEvents)
    layer.close()


def test_native_double_click_final_release_never_rearms_single_click():
    QApplication.instance() or QApplication([])
    layer=PlayerInputOverlay(); layer.resize(640,360); layer.show()
    play_spy=QSignalSpy(layer.toggle_playback); full_spy=QSignalSpy(layer.toggle_fullscreen)
    QTest.mousePress(layer,Qt.LeftButton); QTest.mouseRelease(layer,Qt.LeftButton)
    double=QMouseEvent(QEvent.MouseButtonDblClick,QPointF(10,10),QPointF(10,10),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    release=QMouseEvent(QEvent.MouseButtonRelease,QPointF(10,10),QPointF(10,10),Qt.LeftButton,Qt.NoButton,Qt.NoModifier)
    layer.mouseDoubleClickEvent(double); layer.mouseReleaseEvent(release)
    QTest.qWait(QApplication.doubleClickInterval()+40)
    assert full_spy.count()==1 and play_spy.count()==0
    layer.close()


def test_named_opening_chapter_controls_skip_target():
    QApplication.instance() or QApplication([])
    class Player:
        target=None
        def get_title(self): return 0
        def get_full_chapter_descriptions(self,title):
            return [SimpleNamespace(name=b"Prologue",time_offset=0,duration=10000),
                    SimpleNamespace(name=b"Opening Theme",time_offset=10000,duration=90000),
                    SimpleNamespace(name=b"Episode",time_offset=100000,duration=1200000),
                    SimpleNamespace(name=b"ED",time_offset=1300000,duration=90000)]
        def set_time(self,value): self.target=value
    widget=IntegratedPlayer(hover_previews=False); widget.resize(900,600); widget.show(); widget._player=Player()
    widget._configure_skip_overlay()
    widget.refresh_chapters()
    assert widget._opening_chapter["start"]==10000 and widget._opening_chapter["end"]==100000
    widget._update_skip_opening(20000); assert widget.skip_opening.isVisible()
    assert widget.skip_opening.isWindow() and widget.skip_opening.windowFlags() & Qt.FramelessWindowHint
    widget._skip_opening(); assert widget._player.target==100000 and not widget.skip_opening.isVisible()
    widget.close(); widget.skip_opening.close(); widget.preview.close()


def test_intro_and_credits_chapter_aliases_are_case_insensitive():
    QApplication.instance() or QApplication([])
    class Player:
        def get_title(self): return 0
        def get_full_chapter_descriptions(self,title):
            return [SimpleNamespace(name=b"iNtRo",time_offset=0,duration=60000),
                    SimpleNamespace(name=b"Episode",time_offset=60000,duration=1000000),
                    SimpleNamespace(name=b"CrEdItS",time_offset=1060000,duration=90000)]
    widget=IntegratedPlayer(hover_previews=False); widget._player=Player(); widget.refresh_chapters()
    assert widget._opening_chapter["name"]=="iNtRo"
    assert [chapter["name"] for chapter in widget._ending_chapters]==["CrEdItS"]
    widget.close()


def test_named_ending_chapter_shows_overlay_and_skips_to_next_meaningful_chapter():
    QApplication.instance() or QApplication([])
    class Player:
        target=None
        def get_title(self): return 0
        def get_full_chapter_descriptions(self,title):
            return [SimpleNamespace(name=b"Episode",time_offset=0,duration=1200000),
                    SimpleNamespace(name=b"Ending Theme",time_offset=1200000,duration=90000),
                    SimpleNamespace(name=b"Preview",time_offset=1290000,duration=30000)]
        def set_time(self,value): self.target=value
    widget=IntegratedPlayer(hover_previews=False); widget.resize(900,600); widget.show(); widget._player=Player(); widget._last_duration=1320000
    widget._configure_skip_overlay(); widget.refresh_chapters(); widget._update_skip_chapters(1240000)
    assert widget.skip_ending.isVisible() and widget.skip_ending.isWindow()
    widget._skip_ending()
    assert widget._player.target==1290000 and not widget.skip_ending.isVisible()
    widget.close(); widget.skip_opening.close(); widget.skip_ending.close(); widget.preview.close()


def test_final_outro_skips_to_media_end_without_guessing_duration():
    QApplication.instance() or QApplication([])
    widget=IntegratedPlayer(hover_previews=False)
    class Player:
        target=None
        def set_time(self,value): self.target=value
    widget._player=Player(); widget._last_duration=1500000
    widget._chapters=[{"name":"Episode","start":0,"end":1400000},{"name":"Outro","start":1400000,"end":1490000}]
    widget._ending_chapters=[widget._chapters[-1]]; widget._active_ending_chapter=widget._chapters[-1]
    widget._skip_ending(); assert widget._player.target==1500000
    widget.close(); widget.skip_ending.close(); widget.preview.close()


def test_credits_aliases_are_classified_as_ending_chapters():
    QApplication.instance() or QApplication([])
    labels=[b"Credits Start",b"Credits",b"End Credits",b"Ending Credits",b"Ending",b"ED",b"Ending Theme",b"Outro"]
    class Player:
        def get_title(self): return 0
        def get_full_chapter_descriptions(self,title):
            return [SimpleNamespace(name=name,time_offset=index*10000,duration=10000) for index,name in enumerate(labels)]
    widget=IntegratedPlayer(hover_previews=False); widget._player=Player(); widget.refresh_chapters()
    assert [chapter["name"] for chapter in widget._ending_chapters]==[name.decode() for name in labels]
    widget.close(); widget.skip_ending.close(); widget.preview.close()


def test_windowed_controls_are_overlayed_and_timeline_has_large_hit_target():
    QApplication.instance() or QApplication([])
    widget=IntegratedPlayer(hover_previews=False); widget.resize(900,600); widget.show(); widget._enable_windowed_overlay(); QApplication.processEvents()
    assert widget.control_panel.isWindow() and widget.control_panel.fullscreen_overlay
    assert widget.timeline.minimumHeight()>=28
    assert widget.control_panel.height()==82 and type(widget.episode_label).__name__=="ElidedCenterLabel"
    assert widget.input_overlay.isWindow()
    assert (widget.input_overlay.pos()-widget.video.mapToGlobal(widget.video.rect().topLeft())).manhattanLength()<=4
    assert widget.input_overlay.size()==widget.video.size()
    widget.begin_teardown("test",lambda _message:None); widget.close()


def test_control_overlay_never_reserves_layout_space_and_tracks_video_geometry():
    QApplication.instance() or QApplication([])
    widget=IntegratedPlayer(hover_previews=False); widget.resize(1000,700); widget.show(); QApplication.processEvents()
    assert widget.outer.indexOf(widget.control_panel)==-1
    assert widget.control_panel.width()==widget.video.width()
    assert widget.control_panel.geometry().bottom()==widget.video.mapToGlobal(widget.video.rect().bottomRight()).y()
    widget.resize(1200,760); QApplication.processEvents(); widget._position_overlay()
    assert widget.control_panel.width()==widget.video.width()
    widget.set_fullscreen_mode(True); QApplication.processEvents(); widget._position_overlay()
    assert widget.control_panel.geometry().bottom()==widget.video.mapToGlobal(widget.video.rect().bottomRight()).y()
    widget.set_fullscreen_mode(False); QApplication.processEvents(); widget._position_overlay()
    assert widget.outer.indexOf(widget.control_panel)==-1
    widget.begin_teardown("test",lambda _message:None); widget.close()


def test_timeline_emits_hover_without_mouse_button():
    QApplication.instance() or QApplication([])
    slider=SeekSlider(Qt.Horizontal); slider.resize(500,28); slider.setRange(0,100000); slider.show()
    spy=QSignalSpy(slider.hover_requested)
    move=QMouseEvent(QEvent.MouseMove,QPointF(250,14),QPointF(250,14),Qt.NoButton,Qt.NoButton,Qt.NoModifier)
    slider.mouseMoveEvent(move); QApplication.processEvents()
    assert spy.count()>=1


def test_discovery_grid_uses_more_columns_at_wide_sizes():
    QApplication.instance() or QApplication([])
    grid=ResponsiveSeasonGrid([QWidget() for _ in range(12)]); grid.resize(500,800); grid.show(); QApplication.processEvents(); grid._reflow(); narrow=grid._columns
    grid.resize(1500,800); QApplication.processEvents(); grid._reflow()
    assert narrow<=2 and grid._columns>=6


def test_watching_this_season_card_has_unclipped_footer():
    QApplication.instance() or QApplication([])
    item={"id":7,"title":{"english":"A Current Show"},"format":"TV","episodes":26,
          "nextAiringEpisode":{"episode":14},"coverImage":{}}
    local=SeasonCard(item,True); remote=SeasonCard(item,False)
    local.show(); QApplication.processEvents()
    assert local.height()==remote.height()
    badge=local.findChild(QWidget,"seasonLocalMetadata")
    assert badge is not None and badge.text().endswith("Episode 14") and badge.height()>=30
    assert badge.geometry().bottom()<=local.contentsRect().bottom()-8


def _season_items(count):
    return [{"id":index+1,"title":{"english":f"Season Show {index+1}"},"format":"TV","episodes":26,
             "isAdult":False,"popularity":1000-index,"trending":500-index,"coverImage":{},
             "nextAiringEpisode":{"episode":14}} for index in range(count)]


def test_airing_catalog_preserves_page_one_for_each_view_all_query(monkeypatch):
    calls=[]
    def page_fetch(season,year,page,status,sort):
        calls.append((season,year,page,status,sort))
        item={**_season_items(1)[0],"id":len(calls),"status":status or "FINISHED"}
        return {"items":[item],"pageInfo":{"currentPage":1,"hasNextPage":True},"httpStatus":200,"rawCount":1}
    monkeypatch.setattr(anilist_module,"fetch_season_page",page_fetch)
    catalog=anilist_module.fetch_airing_catalog("FALL",2026)
    assert calls==[("FALL",2026,1,"RELEASING","POPULARITY_DESC"),
                   ("FALL",2026,1,None,"TRENDING_DESC"),
                   ("FALL",2026,1,None,"POPULARITY_DESC"),
                   (None,None,1,"RELEASING","POPULARITY_DESC"),
                   ("WINTER",2027,1,"NOT_YET_RELEASED","POPULARITY_DESC")]
    assert catalog["trending"]==catalog["section_pages"]["Trending Now"]["items"]
    assert catalog["popular"]==catalog["section_pages"]["Popular This Season"]["items"]


def test_optional_anilist_filters_are_omitted_instead_of_sent_as_null(monkeypatch):
    requests=[]
    def fake_graphql(query,variables,include_http_status=False):
        requests.append((query,variables)); return {"Page":{"media":[],"pageInfo":{"hasNextPage":False}}},200
    monkeypatch.setattr(anilist_module,"graphql",fake_graphql)
    anilist_module.fetch_season_page("FALL",2026,1,None,"TRENDING_DESC")
    query,variables=requests[-1]
    assert "status:$status" not in query and "$status:MediaStatus" not in query and "status" not in variables
    assert "season:$season" in query and "seasonYear:$year" in query
    anilist_module.fetch_season_page(None,None,1,"RELEASING","START_DATE")
    query,variables=requests[-1]
    assert "season:$season" not in query and "seasonYear:$year" not in query
    assert variables["status"]=="RELEASING" and "status:$status" in query


def test_empty_trending_result_is_not_replaced_by_releasing_catalog(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    monkeypatch.setattr(app_module,"current_anime_season",lambda:("FALL",2026))
    current=_season_items(15); empty={"items":[],"pageInfo":{"currentPage":1,"hasNextPage":False},"httpStatus":200}
    catalog={"current":current,"trending":[],"popular":[],"currently":current,"upcoming":[],
             "section_pages":{"Trending Now":empty,"Popular This Season":empty}}
    monkeypatch.setattr(app_module,"fetch_airing_catalog",lambda *_:catalog)
    window=Window(); window.show(); window.show_airing()
    for _ in range(60):
        app.processEvents(); QTest.qWait(10)
        if window.anilist_worker is None: break
    sections=window.stack.currentWidget().findChildren(QWidget,"airingSection")
    trending=next(section for section in sections if section.findChild(QWidget,"section").text()=="Trending Now")
    assert trending.findChild(ResponsiveSeasonGrid) is None
    assert any(label.text()=="Nothing here yet." for label in trending.findChildren(QWidget) if hasattr(label,"text"))
    window.close()


def test_live_view_all_loads_beyond_initial_card_batch(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    window=Window(); window.resize(1200,800); window.show(); window.show_airing_all("Popular This Season",_season_items(90))
    app.processEvents(); grid=window.stack.currentWidget().findChild(ResponsiveSeasonGrid)
    assert grid is not None and len(grid.cards)==36
    more=next(button for button in window.stack.currentWidget().findChildren(QPushButton) if button.text().startswith("Load More"))
    original_grid=grid; QTest.mouseClick(more,Qt.LeftButton); app.processEvents()
    grid=window.stack.currentWidget().findChild(ResponsiveSeasonGrid)
    assert grid is original_grid and len(grid.cards)==72
    window.close()


def test_live_view_all_requests_and_merges_later_anilist_pages(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    calls=[]
    def page_fetch(season,year,page,status,sort):
        calls.append(page); start=11 if page==2 else 61
        return {"items":[{**item,"id":item["id"]+start-1,"title":{"english":f"Remote {item['id']+start-1}"}} for item in _season_items(50)],
                "pageInfo":{"currentPage":page,"hasNextPage":page<3},"httpStatus":200}
    monkeypatch.setattr(app_module,"fetch_season_page",page_fetch)
    window=Window(); window.resize(1200,800); window.show()
    initial_items=_season_items(10)
    initial_result={"items":initial_items,"pageInfo":{"currentPage":1,"hasNextPage":True,"perPage":50},"httpStatus":200}
    window.show_airing_all("Popular This Season",initial_items,("FALL",2026,None,"POPULARITY_DESC"),initial_result); app.processEvents()
    page=window.stack.currentWidget(); original_grid=page.findChild(ResponsiveSeasonGrid,"airingResultsGrid")
    more=next(button for button in page.findChildren(QPushButton) if button.text().startswith("Load More"))
    QTest.mouseClick(more,Qt.LeftButton)
    for _ in range(30):
        app.processEvents(); QTest.qWait(10)
        if calls and window.airing_page_worker is None: break
    grid=page.findChild(ResponsiveSeasonGrid,"airingResultsGrid")
    assert calls and calls[0]==2 and len(grid.cards)>10
    # Consume the rest of page two, then request page three.
    for _ in range(3):
        QTest.mouseClick(more,Qt.LeftButton)
        for _ in range(30):
            app.processEvents(); QTest.qWait(10)
            if len(calls)>=2 and window.airing_page_worker is None: break
        if len(calls)>=2: break
    assert calls[:2]==[2,3]
    ids=[int(card.item["id"]) for card in page.findChild(ResponsiveSeasonGrid,"airingResultsGrid").cards]
    assert page.findChild(ResponsiveSeasonGrid,"airingResultsGrid") is original_grid
    assert len(ids)==len(set(ids)) and max(ids)>60
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert "AiringGrid created id=" in diagnostics
    assert "current_page=1" in diagnostics
    assert "LazyLoad trigger section=Popular This Season page=2" in diagnostics
    assert "LazyLoad response page=3" in diagnostics
    assert "append target valid=true" in diagnostics.lower()
    assert "Query definition season=FALL year=2026 status=None sort=POPULARITY_DESC" in diagnostics
    assert "Airing query pipeline category=Popular This Season page=1 perPage=20" in diagnostics
    assert "raw API media count=10 API hasNextPage=True" in diagnostics
    assert "Airing query pipeline category=Popular This Season page=2 perPage=20" in diagnostics
    assert "count after adult filtering=" in diagnostics and "visible cards produced=" in diagnostics
    assert "Internal C++ object" not in diagnostics
    window.close()


def test_airing_view_all_scroll_visibly_appends_page_two_cards(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    monkeypatch.setattr(app_module,"current_anime_season",lambda:("FALL",2026))
    page_one=_season_items(20)
    page_one_result={"items":page_one,"pageInfo":{"currentPage":1,"hasNextPage":True,"perPage":20},"httpStatus":200}
    catalog={"current":page_one,"trending":page_one,"popular":page_one,"currently":page_one,"upcoming":[],
             "section_pages":{"Trending Now":page_one_result,"Popular This Season":page_one_result,
                              "Currently Airing":page_one_result},
             "upcoming_season":"WINTER","upcoming_year":2027}
    monkeypatch.setattr(app_module,"fetch_airing_catalog",lambda *_:catalog)
    calls=[]
    def fetch_page(season,year,page,status,sort):
        calls.append((season,year,page,status,sort))
        offset=(page-1)*20
        rows=[{**item,"id":item["id"]+offset,"title":{"english":f"Page {page} Item {item['id']}"}} for item in _season_items(20)]
        return {"items":rows,"pageInfo":{"currentPage":page,"hasNextPage":page<3,"perPage":20},"httpStatus":200}
    monkeypatch.setattr(app_module,"fetch_season_page",fetch_page)
    window=Window(); window.resize(1000,700); window.show(); window.show_airing()
    for _ in range(80):
        app.processEvents(); QTest.qWait(10)
        if window.anilist_worker is None: break
    airing_page=window.stack.currentWidget()
    view_all=next(button for button in airing_page.findChildren(QPushButton) if button.text().startswith("View All"))
    QTest.mouseClick(view_all,Qt.LeftButton); app.processEvents()
    result_page=window.stack.currentWidget(); grid=result_page.findChild(ResponsiveSeasonGrid,"airingResultsGrid")
    assert len(grid.cards)==20
    original_cards=list(grid.cards); original_ids=[card.item["id"] for card in original_cards]
    original_cells=[grid.grid.getItemPosition(index) for index in range(20)]
    scroll=result_page.findChild(QScrollArea); bar=scroll.verticalScrollBar()
    bar.setValue(bar.maximum()); first_anchor=bar.value()
    for _ in range(100):
        app.processEvents(); QTest.qWait(10)
        if calls and window.airing_page_worker is None and len(grid.cards)>20: break
    assert calls==[("FALL",2026,2,None,"TRENDING_DESC")]
    assert len(grid.cards)==40
    assert grid.cards[:20]==original_cards and [card.item["id"] for card in grid.cards[:20]]==original_ids
    assert [grid.grid.getItemPosition(index) for index in range(20)]==original_cells
    assert bar.value()==first_anchor
    bar.setValue(bar.maximum())
    for _ in range(100):
        app.processEvents(); QTest.qWait(10)
        if len(calls)>=2 and window.airing_page_worker is None and len(grid.cards)>40: break
    assert calls[-1]==("FALL",2026,3,None,"TRENDING_DESC") and len(grid.cards)==60
    assert grid.cards[:20]==original_cards and [card.item["id"] for card in grid.cards]==list(range(1,61))
    assert [grid.grid.getItemPosition(index) for index in range(20)]==original_cells
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert "raw API media count=20 API hasNextPage=False" in diagnostics
    assert "Cards before append=20" in diagnostics and "Cards after append=40" in diagnostics and "Cards after append=60" in diagnostics
    lazy_diagnostics=diagnostics[diagnostics.index("LazyLoad trigger section=Trending Now"):]
    assert "mode=in-place" in lazy_diagnostics and "reason=reuse-replace" not in lazy_diagnostics
    window.close()


@pytest.mark.parametrize("heading,spec",[
    ("Trending Now",("FALL",2026,None,"TRENDING_DESC")),
    ("Popular This Season",("FALL",2026,None,"POPULARITY_DESC")),
    ("Currently Airing",(None,None,"RELEASING","POPULARITY_DESC")),
    ("Upcoming Next Season",("WINTER",2027,"NOT_YET_RELEASED","POPULARITY_DESC")),
])
def test_each_view_all_category_batches_without_hiding_or_resizing_existing_cards(tmp_path,monkeypatch,heading,spec):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    initial=_season_items(20); initial_result={"items":initial,"pageInfo":{"currentPage":1,"hasNextPage":True},"httpStatus":200}
    rows=[{**item,"id":item["id"]+20,"title":{"english":f"Later {item['id']}"}} for item in _season_items(20)]
    monkeypatch.setattr(app_module,"fetch_season_page",lambda *_:{"items":rows,"pageInfo":{"currentPage":2,"hasNextPage":False},"httpStatus":200})
    window=Window(); window.resize(1000,700); window.show(); window.show_airing_all(heading,initial,spec,initial_result); QTest.qWait(450); app.processEvents()
    page=window.stack.currentWidget(); grid=page.findChild(ResponsiveSeasonGrid,"airingResultsGrid"); original=list(grid.cards); geometries=[card.geometry() for card in original]
    class Watcher(QObject):
        def __init__(self): super().__init__(); self.hide=0; self.show=0; self.resize=0
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Hide: self.hide+=1
            elif event.type()==QEvent.Show: self.show+=1
            elif event.type()==QEvent.Resize: self.resize+=1
            return False
    watcher=Watcher()
    for card in original: card.installEventFilter(watcher)
    scroll=page.findChild(QScrollArea); bar=scroll.verticalScrollBar(); bar.setValue(bar.maximum()); anchor=bar.value()
    for _ in range(80):
        app.processEvents(); QTest.qWait(10)
        if window.airing_page_worker is None and len(grid.cards)==40: break
    assert len(grid.cards)==40 and grid.cards[:20]==original
    assert [card.geometry() for card in original]==geometries
    assert watcher.hide==0 and watcher.show==0 and watcher.resize==0 and bar.value()==anchor
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    lazy=diagnostics[diagnostics.index(f"LazyLoad trigger section={heading}"):]
    assert "AiringGrid batch append" in lazy and "layout_passes=1 updates_scope=grid" in lazy
    assert "Append paint begin" in lazy and "Append paint end" in lazy
    assert "full reflow triggered=false" in lazy and "existing widgets recreated=0" in lazy
    assert "AiringGrid reflow" not in lazy and "reason=reuse-replace" not in lazy
    window.close()


def test_adult_filter_removes_only_explicit_boolean_true(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    initial=_season_items(1)
    response=[]
    for offset,adult in enumerate((True,False,None,"true"),start=2):
        response.append({**_season_items(1)[0],"id":offset,"title":{"english":f"Audit {offset}"},"isAdult":adult})
    monkeypatch.setattr(app_module,"fetch_season_page",lambda *_:{"items":response,"pageInfo":{"currentPage":2,"hasNextPage":False},"httpStatus":200})
    window=Window(); window.show(); window.show_airing_all("Trending Now",initial,("FALL",2026,None,"TRENDING_DESC"),
        {"items":initial,"pageInfo":{"currentPage":1,"hasNextPage":True},"httpStatus":200})
    page=window.stack.currentWidget(); more=next(button for button in page.findChildren(QPushButton) if button.text().startswith("Load More"))
    QTest.mouseClick(more,Qt.LeftButton)
    for _ in range(60):
        app.processEvents(); QTest.qWait(10)
        if window.airing_page_worker is None: break
    grid=page.findChild(ResponsiveSeasonGrid,"airingResultsGrid")
    assert {card.item["id"] for card in grid.cards}=={1,3,4,5}
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert "adult removed=1" in diagnostics
    assert "Adult filter audit:" not in diagnostics
    window.close()


def test_live_view_all_suppresses_duplicate_requests_backs_off_429_and_stops_at_last_page(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    calls=[]
    def page_fetch(season,year,page,status,sort):
        calls.append((season,year,page,status,sort))
        if len(calls)==1: raise AniListHTTPError(429,"rate limited",1)
        return {"items":_season_items(4),"pageInfo":{"currentPage":page,"hasNextPage":False},"httpStatus":200}
    monkeypatch.setattr(app_module,"fetch_season_page",page_fetch)
    window=Window(); window.resize(1200,800); window.show()
    spec=("FALL",2026,"RELEASING","POPULARITY_DESC")
    window.show_airing_all("Currently Airing",_season_items(10),spec); app.processEvents()
    page=window.stack.currentWidget()
    more=next(button for button in page.findChildren(QPushButton) if button.text().startswith("Load More"))
    QTest.mouseClick(more,Qt.LeftButton); QTest.mouseClick(more,Qt.LeftButton)
    for _ in range(40): app.processEvents(); QTest.qWait(10)
    assert calls==[("FALL",2026,2,"RELEASING","POPULARITY_DESC")]
    QTest.qWait(1100)
    for _ in range(60):
        app.processEvents(); QTest.qWait(10)
        if len(calls)>=2 and window.airing_page_worker is None: break
    assert calls==[("FALL",2026,2,"RELEASING","POPULARITY_DESC")]*2
    QTest.mouseClick(more,Qt.LeftButton); QTest.qWait(50)
    assert len(calls)==2
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert "HTTP status=429" in diagnostics and "Rate-limit backoff seconds=1" in diagnostics
    assert "HTTP status=200" in diagnostics and "hasNextPage=False" in diagnostics
    assert "Request timestamp=" in diagnostics
    window.close()


def test_live_airing_grid_reflows_on_first_window_state_change(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    monkeypatch.setattr(app_module.AniListWorker,"start",lambda self:None)
    window=Window(); window.db.set_setting("anilist_season_cache_key","discovery-v4:FALL:2026")
    window.db.set_setting("anilist_season_cache",json.dumps({"current":_season_items(16),"upcoming":[]}))
    monkeypatch.setattr(app_module,"current_anime_season",lambda:("FALL",2026))
    window.resize(700,720); window.show(); window.show_airing(); QTest.qWait(360)
    grid=window.stack.currentWidget().findChild(ResponsiveSeasonGrid); narrow=grid._columns
    window.resize(1500,850); QTest.qWait(260)
    assert narrow<=2 and grid._columns>=4 and grid._columns>narrow
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert "Airing resize event received" in diagnostics and "Airing relayout fired" in diagnostics
    assert "Scroll area viewport size:" in diagnostics and "Computed columns:" in diagnostics
    window.close()


def test_live_airing_refresh_has_one_view_all_button_per_section(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    catalog={"current":_season_items(16),"upcoming":_season_items(8)}
    monkeypatch.setattr(app_module,"current_anime_season",lambda:("FALL",2026))
    monkeypatch.setattr(app_module,"fetch_airing_catalog",lambda *_:catalog)
    window=Window(); window.db.set_setting("anilist_season_cache_key","discovery-v4:FALL:2026"); window.db.set_setting("anilist_season_cache",json.dumps(catalog))
    window.resize(1200,800); window.show(); window.show_airing()
    for _ in range(40):
        app.processEvents(); QTest.qWait(10)
        if window.anilist_worker is None: break
    page=window.stack.currentWidget(); buttons=[button for button in page.findChildren(QPushButton) if button.text().startswith("View All")]
    sections=page.findChildren(QWidget,"airingSection")
    assert len(buttons)==4 and len(sections)==5
    scroll=page.findChild(app_module.QScrollArea,"airingScroll")
    assert scroll.widget().width()==scroll.viewport().width()
    window.close()


def test_airing_grid_destroy_diagnostic_and_owned_timer_cleanup(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]); monkeypatch.setattr(app_module,"APP_DIR",tmp_path)
    owner=QWidget(); grid=ResponsiveSeasonGrid([QWidget()],owner,context="Lifecycle Test"); gid=grid.grid_id
    grid._schedule_reflow(100); owner.deleteLater(); QApplication.sendPostedEvents(None,QEvent.DeferredDelete); app.processEvents()
    diagnostics=(tmp_path/"playback_diagnostics.log").read_text(encoding="utf-8")
    assert f"AiringGrid created id={gid}" in diagnostics and f"AiringGrid destroyed id={gid}" in diagnostics
