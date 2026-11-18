import json,time,hashlib
from types import SimpleNamespace
from PySide6.QtWidgets import QLabel,QPushButton,QListWidget,QFrame,QScrollArea,QLineEdit
from PySide6.QtCore import Qt,QThread
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtTest import QTest
from shiboken6 import isValid
from anime_hub import app
from anime_hub.app import Card,CollectionCard,StatusCountLabel,ResponsiveLibraryGrid
from anime_hub.manga_ui import MangaCard
from anime_hub.polish_ui import SearchSuggestions,CoverListCard,CompactFilterLayout
from test_cross_media import window,data,remote,anime,manga


def wait(qt,condition,timeout=5000):
    started=time.monotonic()
    while not condition():
        assert time.monotonic()-started<timeout/1000
        QTest.qWait(10)


def test_actual_sidebar_favorites_click_and_mixed_detail_routing(window):
    w,qt,aid,sid,_=window;w.db.set_favorite(aid,True);w.manga_store.set_favorite(sid,True)
    QTest.mouseClick(w.nav_buttons['favorites'],Qt.LeftButton);QTest.qWait(30)
    assert w.current_view=='favorites' and w.active_nav_key=='favorites'
    page=w.stack.currentWidget();assert page.findChild(Card) and page.findChild(MangaCard)
    page.findChild(Card).clicked.emit(aid);assert w.current_anime_id==aid
    w.navigate_back();w.stack.currentWidget().findChild(MangaCard).clicked.emit(sid);assert w.current_view=='manga_detail'


def test_favorites_scope_isolation(window,tmp_path):
    w,qt,aid,sid,_=window;private=anime(w.db,tmp_path/'Private',99,True);w.db.set_favorite(private,True);w.db.set_favorite(aid,True)
    w.show_favorites();assert [c.anime_id for c in w.stack.currentWidget().findChildren(Card)]==[aid]
    w.db.set_setting('restricted_unlocked','1');w.show_favorites('restricted')
    assert [c.anime_id for c in w.stack.currentWidget().findChildren(Card)]==[private]
    w.lock_restricted();assert not w.current_view.startswith('restricted')


def test_episode_titles_are_display_only(window,tmp_path):
    w,qt,aid,*_=window;path=tmp_path/'7th.Time.Loop.S01E04.Turning.the.Knave.Into.a.Secret.Spice.1080p.HEVC.mkv';path.write_bytes(b'unchanged')
    w.db.upsert_media(aid,SimpleNamespace(path=path,kind='episode',season=1,episode=4));digest=hashlib.sha256(path.read_bytes()).digest()
    w.show_detail(aid);listings=w.stack.currentWidget().findChildren(QListWidget)
    row=next(listing.item(i) for listing in listings for i in range(listing.count()) if listing.item(i).data(Qt.UserRole)==str(path))
    assert 'Episode 4 — Turning the Knave Into a Secret Spice' in row.text() and '1080p' not in row.text()
    assert row.data(Qt.UserRole)==str(path);assert hashlib.sha256(path.read_bytes()).digest()==digest
    item=remote(11);item['episode_titles']={'4':'Metadata Episode Title'};w.db.set_metadata(aid,11,item);w.show_detail(aid)
    assert any('Episode 4 — Metadata Episode Title' in listing.item(i).text() for listing in w.stack.currentWidget().findChildren(QListWidget) for i in range(listing.count()))


def test_direct_status_controls_update_without_detail_rebuild(window):
    w,qt,aid,sid,_=window
    for kind,identifier in [('ANIME',aid),('MANGA',sid),('REMOTE',77)]:
        w.show_detail(identifier) if kind=='ANIME' else w.show_manga_detail(identifier) if kind=='MANGA' else w.show_remote_anilist(remote(identifier),'Discover')
        page=w.stack.currentWidget();bar=page.findChild(QFrame,'directStatusControls') or page.findChild(app.QWidget,'directStatusControls')
        controls={b.text():b for b in bar.findChildren(QPushButton)};controls['Planning'].click()
        assert w.stack.currentWidget() is page and controls['Planning'].isChecked()
        controls['Reading' if kind=='MANGA' else 'Watching'].click();assert not controls['Planning'].isChecked()
        assert sum(button.isChecked() for button in controls.values())==1
        controls['Clear'].click();assert not any(button.isChecked() for button in controls.values())
        assert any(b.text()=='+ Collection' for b in page.findChildren(QPushButton))
        assert not any(b.text() in {'Open Details','Status / Collections…','Manage…','Save'} for b in page.findChildren(QPushButton))


def test_remote_detail_scroll_and_larger_related_grid(window,monkeypatch):
    w,qt,*_=window;item=remote(77);edges=[{'relationType':'SEQUEL','node':remote(i)} for i in range(101,109)]
    monkeypatch.setattr(w,'_submit_discover_job',lambda key,operation,success,failure:success({'edges':edges}))
    w.show_remote_anilist(item,'Discover');w.resize(1800,950);QTest.qWait(60)
    page=w.stack.currentWidget();scroll=page.findChild(QScrollArea);assert scroll.widget().findChild(QFrame,'panel')
    grids=page.findChildren(ResponsiveLibraryGrid);assert len(grids)==1 and len(grids[0].cards)==8
    assert 2<=grids[0]._columns<=8
    assert all(row.width()==228 and row.height()==460 for row in grids[0].cards)


def test_collections_live_counts_visual_cards_and_selection(window,tmp_path):
    w,qt,aid,*_=window;art=tmp_path/'cover.png';pix=QPixmap(200,300);pix.fill(QColor('#d7759d'));pix.save(str(art))
    item=remote(11);item['cover_path']=str(art);w.db.set_metadata(aid,11,item);w._set_status('Planning','normal',anime_id=aid)
    cid=w.db.create_collection('Racing');w.db.add_to_collection(cid,aid);w.show_collections();QTest.qWait(40)
    page=w.stack.currentWidget();assert not any(b.text()=='Open Status List' for b in page.findChildren(QPushButton))
    counts=page.findChildren(StatusCountLabel);assert next(c for c in counts if c.status=='Planning').text()=='1 titles'
    assert len(page.findChildren(CoverListCard))>=7
    card=page.findChild(CollectionCard);QTest.mouseClick(card,Qt.LeftButton);assert w.current_view=='collections'
    QTest.keyClick(card,Qt.Key_Return);assert w.current_view=='collection_detail'
    w.show_collections();w._set_status('Dropped','normal',anime_id=aid)
    counts=w.stack.currentWidget().findChildren(StatusCountLabel);assert next(c for c in counts if c.status=='Planning').text()=='0 titles';assert next(c for c in counts if c.status=='Dropped').text()=='1 titles'


def test_live_search_local_first_dedupe_cache_and_stale_response(window,monkeypatch):
    w,qt,aid,*_=window;w.show_detail(aid);page=w.stack.currentWidget();editor=w.global_search;popup=w.global_suggestions
    requests=[];monkeypatch.setattr(w,'_submit_discover_job',lambda *args:requests.append(args))
    editor.setFocus();editor.setText('Shared');popup.changed('Shared');assert popup.isVisible();assert popup.item(0).data(Qt.UserRole)[1].local
    popup.timer.stop();popup.remote();assert len(requests)==1
    requests[0][2]([remote(11),remote(88),remote(89,'MANGA'),remote(90,adult=True),{'id':91,'type':'CHARACTER'}])
    labels=[popup.item(i).text() for i in range(popup.count())];assert any('Shared 88' in x for x in labels) and not any('Shared 90' in x for x in labels)
    assert sum('Shared 11' in x for x in labels)==1
    popup.changed('Shared');popup.timer.stop();popup.remote();assert len(requests)==1
    editor.setText('Different');popup.changed('Different');popup.timer.stop();popup.remote();assert len(requests)==2
    popup.dismiss();requests[1][2]([remote(99)]);assert not popup.isVisible()
    popup.changed('Shared');popup.timer.stop();QTest.keyClick(editor,Qt.Key_Escape);assert not popup.isVisible()


def test_restricted_overview_scroll_and_lock_disposal(window,monkeypatch,tmp_path):
    w,qt,*_=window
    calls=[]
    w.db.set_setting('restricted_unlocked','1')
    monkeypatch.setattr(w,'_request_discover_page',lambda *args:calls.append(args))
    for index in range(10):anime(w.db,tmp_path/str(index),800+index,True)
    w.resize(1000,600)
    w.show_restricted_home()
    QTest.qWait(60)
    page=w.stack.currentWidget()
    scroll=page.findChild(QScrollArea)
    banner=scroll.widget().findChild(app.ArtworkHero)
    assert banner and banner.library_overview
    wait(qt,lambda:scroll.verticalScrollBar().maximum()>0)
    initial=banner.mapTo(page,banner.rect().topLeft()).y()
    scroll.verticalScrollBar().setValue(200)
    QTest.qWait(30)
    assert banner.mapTo(page,banner.rect().topLeft()).y()<initial
    w.lock_restricted()
    w.db.set_setting('restricted_unlocked','1')
    w.show_restricted_home()
    assert w.stack.currentWidget() is not page and not calls


def test_discover_compact_filter_layout(window,monkeypatch):
    w,qt,*_=window;monkeypatch.setattr(w,'_request_discover_filters',lambda *_:None);w.show_discover();w.resize(1100,850);QTest.qWait(30)
    page=w.stack.currentWidget();assert page.findChild(CompactFilterLayout)
    for button in page.findChildren(QPushButton):
        if button.text() in {'Search','Clear','↻ Refresh'}:assert button.height()==32
    assert not any(label.isVisible() and label.text()=='Discover Anime' for label in page.findChildren(QLabel) if label is not page.findChild(QLabel,'title'))


def test_async_close_keeps_worker_alive_without_blocking(window):
    w,qt,*_=window
    class SlowWorker(QThread):
        def run(self):self.msleep(180)
    worker=SlowWorker();w.anilist_worker=worker;worker.start();started=time.perf_counter();w.close()
    assert time.perf_counter()-started<.15 and not w._shutdown_complete
    wait(qt,lambda:w._shutdown_complete);assert not worker.isRunning();assert w._closing


def test_query_indexes_and_bounded_artwork_cache(data,tmp_path):
    db,*_=data
    status_plan=str([tuple(r) for r in db.connection.execute("EXPLAIN QUERY PLAN SELECT * FROM manual_status WHERE scope='normal' AND status='Planning' ORDER BY updated_at DESC")]);assert 'manual_status_list' in status_plan
    collection_plan=str([tuple(r) for r in db.connection.execute('EXPLAIN QUERY PLAN SELECT * FROM collection_entries WHERE collection_id=1 ORDER BY added_at DESC')]);assert 'collection_entries_added' in collection_plan
    cache={}
    for index in range(12):
        pix=QPixmap(2000,1000);pix.fill(QColor('coral'));cache[index]=pix;app._bound_pixmap_cache(cache)
    assert sum(p.width()*p.height()*p.depth()//8 for p in cache.values())<=64*1024*1024


def test_large_library_batch_queries_cached_page_and_population_resume(window,tmp_path):
    w,qt,*_=window
    rows=[('stress:'+str(i),'Stress '+str(i),'',str(tmp_path/str(i))) for i in range(1050)]
    with w.db.connection:
        w.db.connection.executemany('INSERT INTO anime(identity,title,category,root_path) VALUES(?,?,?,?)',rows)
    queries=[];w.db.connection.set_trace_callback(queries.append);w._library_cache_dirty=True;started=time.perf_counter();w.show_library()
    page=w.stack.currentWidget();grid=page.findChild(ResponsiveLibraryGrid)
    wait(qt,lambda:len(grid.cards)>=1051,timeout=15000);first_ms=(time.perf_counter()-started)*1000
    assert sum('SELECT status FROM manual_status' in q for q in queries)==0
    count=len(grid.cards);w.show_favorites();started=time.perf_counter();w.show_library();QTest.qWait(20);reuse_ms=(time.perf_counter()-started)*1000
    assert w.stack.currentWidget() is page and len(grid.cards)==count and reuse_ms<first_ms
    w.resize(1800,950);QTest.qWait(20);ids=[id(card) for card in grid.cards];w.resize(1200,850);QTest.qWait(20);assert ids==[id(card) for card in grid.cards]
    w.db.connection.set_trace_callback(None)
    print(f'\nStressLibrary rows={count} first_ms={first_ms:.0f} reuse_ms={reuse_ms:.0f} queries={len(queries)} columns={grid._columns}')


def franchise_fixture(w,aid,tmp_path):
    second=anime(w.db,tmp_path/'Second Stage',12);third=anime(w.db,tmp_path/'Similar Name',13)
    first_item=remote(11);first_item['title']={'english':'Initial D First Stage'};first_item['relations']={'edges':[{'relationType':'SEQUEL','node':{**remote(12),'title':{'english':'Initial D Second Stage'}}},{'relationType':'SOURCE','node':remote(13,'MANGA')}]}
    first_item['startDate']={'year':1998,'month':4,'day':19}
    first_item['relations']['edges'].append({'relationType':'SIDE_STORY','node':remote(21)})
    second_item=remote(12);second_item['title']={'english':'Initial D Second Stage'};second_item['startDate']={'year':1999,'month':10,'day':15}
    third_item=remote(13);third_item['title']={'english':'Initial D Unrelated Name'}
    w.db.set_metadata(aid,11,first_item);w.db.set_metadata(second,12,second_item);w.db.set_metadata(third,13,third_item)
    return second,third


def test_franchise_graph_excludes_cross_media_similar_names_and_preserves_records(window,tmp_path):
    from anime_hub.library_franchises import build_franchises
    w,qt,aid,*_=window;second,third=franchise_fixture(w,aid,tmp_path);before=[tuple(row) for row in w.db.connection.execute('SELECT * FROM anime')]
    groups=build_franchises(w.db.anime_list());assert len(groups)==1 and groups[0].name=='Initial D';assert groups[0].local_ids==(aid,second) and third not in groups[0].local_ids
    w._library_cache_dirty=True;w.show_library();grid=w.stack.currentWidget().findChild(ResponsiveLibraryGrid);wait(qt,lambda:len(grid.cards)==2)
    group_card=next(card for card in grid.cards if card.property('franchiseLocalIds'));assert group_card.property('posterCard') and group_card.width()<=grid.card_width
    group_card.clicked.emit();assert w.current_view=='library_franchise'
    page=w.stack.currentWidget();cards=page.findChildren(Card);assert [card.anime_id for card in cards]==[aid,second]
    assert any('AniList-only' in label.text() and 'Side Story' in label.text() for label in page.findChildren(QLabel))
    cards[1].clicked.emit(second);assert w.current_anime_id==second;w.navigate_back();assert w.current_view=='library_franchise'
    w.show_library(view_mode='Individual Titles');grid=w.stack.currentWidget().findChild(ResponsiveLibraryGrid);wait(qt,lambda:len(grid.cards)==3);assert len(grid.findChildren(Card))==3
    assert before==[tuple(row) for row in w.db.connection.execute('SELECT * FROM anime')]


def test_franchise_suggestions_collapse_broad_query_and_expand_specific_query(window,tmp_path):
    w,qt,aid,*_=window;second,third=franchise_fixture(w,aid,tmp_path);w.show_detail(aid);editor=w.global_search;popup=w.global_suggestions
    editor.setText('Initial D');popup.changed('Initial D');popup.timer.stop()
    groups=[popup.item(i) for i in range(popup.count()) if popup.item(i).data(Qt.UserRole)[0].get('_franchise_ids')];assert len(groups)==1 and '2 local anime titles · In Vault' in groups[0].text()
    assert not any('First Stage\n' in popup.item(i).text() for i in range(popup.count()))
    editor.setText('Initial D Second');popup.changed('Initial D Second');popup.timer.stop();assert popup.count()==1 and 'Second Stage' in popup.item(0).text()


def test_relation_query_batches_and_cache_reuse_without_recursive_crawl(window,monkeypatch):
    from anime_hub.library_franchises import LibraryFranchiseMixin
    w,qt,*_=window;pending=[];w._load_library_relations();monkeypatch.setattr(w,'_submit_discover_job',lambda *args:pending.append(args))
    LibraryFranchiseMixin._request_library_relations(w);LibraryFranchiseMixin._request_library_relations(w);assert len(pending)==1
    pending[0][2]([{**remote(99),'sourceAniListId':11,'relationType':'SEQUEL'}]);assert w._library_relation_path.is_file()
    LibraryFranchiseMixin._request_library_relations(w);assert len(pending)==1
    # A remote-only relation never creates a local record or fetches its relations.
    assert len(w.db.anime_list())==1 and not w._library_franchises()


def test_manga_display_normalization_priority_and_all_views(window):
    from anime_hub.display_titles import clean_manga_display_title,manga_display_title
    w,qt,aid,sid,book=window;raw='All You Need Is Kill (2014) (Digital) (LuCaZ)';digest=hashlib.sha256(book.read_bytes()).digest()
    assert clean_manga_display_title(raw)=='All You Need Is Kill'
    assert clean_manga_display_title('[LuCaZ] All.You.Need.Is.Kill (Digital) [1080p].cbz')=='All You Need Is Kill'
    assert manga_display_title({'title':raw},{'title':{'english':'Matched Title'}})=='Matched Title'
    assert manga_display_title({'title':raw},{'local_title':'Explicit Title'})=='Explicit Title'
    with w.db.connection:w.db.connection.execute("UPDATE manga_series SET title=?,metadata_json='{}',anilist_id=NULL WHERE id=?",(raw,sid))
    row=w.manga_store.series(sid);assert row['title']==raw and row['display_title']=='All You Need Is Kill'
    entity=w.organization().resolve('manga:'+str(sid));assert entity.title=='All You Need Is Kill';assert w.organization().search('All You Need')
    w.show_manga_detail(sid);assert any(label.text()=='All You Need Is Kill' for label in w.stack.currentWidget().findChildren(QLabel));assert not any(label.text()=='Local title: '+raw for label in w.stack.currentWidget().findChildren(QLabel))
    w.manga_store.set_favorite(sid,True);w.show_favorites();assert w.stack.currentWidget().findChild(MangaCard).title_label.text().endswith('All You Need Is Kill')
    assert hashlib.sha256(book.read_bytes()).digest()==digest and w.db.connection.execute('SELECT title FROM manga_series WHERE id=?',(sid,)).fetchone()[0]==raw
