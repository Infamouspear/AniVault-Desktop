import json,sqlite3,time
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QModelIndex
from PySide6.QtWidgets import QLabel,QPushButton,QComboBox,QListView,QTabWidget
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.requests_store import Requests,SCHEMA
from anime_hub.request_queue_ui import AnimeQueue
from anime_hub.library_filters import matches_category
from anime_hub.app import Card,ResponsiveLibraryGrid
from test_cross_media import window,anime,remote


def test_legacy_migration_preserves_183_requests_and_feedback(tmp_path):
    path=tmp_path/'legacy.db';c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.executescript(SCHEMA)
    for i in range(183):c.execute("INSERT INTO desktop_requests(kind,provider_id,title,category,metadata,status,notes) VALUES('anime',?,?,'TV',?,?,?)",(1000+i,'Requested '+str(i),json.dumps(remote(1000+i)),['Requested','Approved','Declined','Available'][i%4],'keep '+str(i)))
    c.execute("INSERT INTO desktop_requests(kind,title,category,status) VALUES('feedback','Feedback','Bug report','Planned')");c.commit()
    before=[dict(r) for r in c.execute('SELECT * FROM desktop_requests ORDER BY id')];c.close()
    db=Database(path);rows=[dict(r) for r in db.connection.execute('SELECT * FROM desktop_requests ORDER BY id')]
    assert len(rows)==184
    for old,new in zip(before,rows):
        assert {k:new[k] for k in old}==old
        assert new['archived']==int(old['kind']=='anime' and old['status'] in {'Approved','Declined','Available'})
    db.connection.close();again=Database(path);assert len(Requests(again).all())==184
    assert again.connection.execute('SELECT COUNT(*) FROM desktop_request_events').fetchone()[0]==sum(r['archived'] for r in rows)
    assert again.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok';again.connection.close()


@pytest.mark.parametrize('status',['Approved','Declined','Available'])
def test_quick_archive_undo_restore_and_revision(tmp_path,status):
    db=Database(tmp_path/'db');s=Requests(db);key=s.add('anime','Manual without an ID',details='keep description')
    initial=s.get(key);token=s.process(key,status);r=s.get(key)
    assert r['archived'] and r['processed_at'] and r['status']==status and r['created']==initial['created']
    assert s.process(key,status) is None and len(s.events(key))==1
    s.undo(token);assert s.get(key)['status']=='Requested' and not s.get(key)['archived'] and s.get(key)['created']==initial['created']
    token=s.process(key,status);s.restore(key)
    with pytest.raises(ValueError,match='newer'):s.undo(token)
    assert s.get(key)['details']=='keep description' and not db.manual_status('normal',anilist_id=1)
    db.connection.close()


def test_exact_scan_detection_approval_history_and_no_cross_release(tmp_path):
    db=Database(tmp_path/'db');s=Requests(db)
    exact=s.discover(remote(91));season3=s.discover(remote(93));declined=s.discover(remote(94));manual=s.add('anime','Lookalike without ID')
    s.process(exact,'Approved');s.process(declined,'Declined')
    anime(db,tmp_path/'season1',91);anime(db,tmp_path/'another-season',92);anime(db,tmp_path/'rejected',94)
    db.finish_scan();assert s.get(exact)['status']=='Available' and s.get(exact)['archived']
    assert [e['status'] for e in s.events(exact)]==['Approved','Available']
    assert s.get(season3)['status']=='Requested' and s.get(manual)['status']=='Requested' and s.get(declined)['status']=='Declined'
    assert not db.manual_status('normal',anilist_id=91)
    count=len(s.events(exact));db.finish_scan();assert len(s.events(exact))==count
    db.connection.close()


def test_duplicate_matches_private_and_manga_do_not_auto_fulfil(window,tmp_path):
    w,qt,aid,sid,*_=window;s=Requests(w.db);exact=s.discover(remote(11));book=s.discover(remote(22));unknown=s.discover(remote(99))
    anime(w.db,tmp_path/'duplicate',11);s.reconcile_available()
    assert all(s.get(i)['status']=='Requested' for i in (exact,book,unknown))
    private=anime(w.db,tmp_path/'private',33,True)
    with pytest.raises(ValueError):s.add('anime','Hidden',identifier=33)
    with pytest.raises(ValueError):s.discover(remote(33,adult=True))
    with pytest.raises(ValueError):s.discover(remote(35,'MANGA'))


def test_scan_revision_conflict_preserves_newer_decision(tmp_path,monkeypatch):
    db=Database(tmp_path/'db');s=Requests(db);key=s.discover(remote(91));anime(db,tmp_path/'exact',91)
    original=s.visible
    def racing():
        rows=original();s.process(key,'Declined');return rows
    monkeypatch.setattr(s,'visible',racing);assert s.reconcile_available()==0 and s.get(key)['status']=='Declined'
    db.connection.close()


def test_category_semantics_match_metadata_not_other_folder():
    row={'category':'Other','watched_count':0,'episode_count':12}
    assert matches_category(row,{'format':'MOVIE'},'Movies')
    assert matches_category(row,{'format':'TV'},'TV Anime')
    assert matches_category(row,{'format':'OVA'},'Specials')
    assert matches_category(row,{'format':'ONA'},'Web Anime')
    assert matches_category(row,{'status':'RELEASING'},'Airing')
    assert matches_category(row,{'status':'FINISHED'},'Finished')
    assert matches_category(row,{},'Watching','Watching')
    assert not matches_category(row,{'format':'MOVIE'},'Other')
    assert matches_category(row,{},None)


def test_library_categories_combined_and_clear(window,tmp_path):
    w,qt,aid,*_=window;movie=anime(w.db,tmp_path/'movie',12);special=anime(w.db,tmp_path/'special',13)
    w.db.set_metadata(aid,11,{**remote(11),'genres':['Action']});w.db.set_metadata(movie,12,{**remote(12),'format':'MOVIE','genres':['Drama']});w.db.set_metadata(special,13,{**remote(13),'format':'OVA'})
    w.show_library();QTest.qWait(100);page=w.stack.currentWidget();category=page.findChild(QComboBox,'libraryCategory')
    category.setCurrentText('Movies');QTest.qWait(50)
    assert [c.anime_id for c in page.findChildren(Card) if c.isVisible()]==[movie]
    action=next(b for b in page.findChildren(QPushButton) if b.text()=='Action');action.click();QTest.qWait(40)
    assert not [c for c in page.findChildren(Card) if c.isVisible()]
    reset=page.findChild(QPushButton,'clearLibraryFilters');assert reset and reset.isVisible();reset.click();QTest.qWait(50)
    assert {c.anime_id for c in page.findChildren(Card) if c.isVisible()}=={aid,movie,special}
    assert not page.findChildren(__import__('anime_hub.manga_ui',fromlist=['MangaCard']).MangaCard)


def test_sidebar_collections_primary_planning_route(window):
    w,qt,*_=window
    assert 'planning' not in w.nav_buttons
    assert not any(l.text()=='ORGANIZE' for l in w.sidebar.findChildren(QLabel))
    order=[w.sidebar.layout().itemAt(i).widget() for i in range(w.sidebar.layout().count()) if w.sidebar.layout().itemAt(i).widget()]
    assert order.index(w.nav_buttons['favorites'])<order.index(w.nav_buttons['collections'])<order.index(w.nav_buttons['statistics'])
    w.show_status_list('Planning','normal');assert w.current_view=='status_list' and w.current_status_name=='Planning' and w.nav_buttons['collections'].property('active')
    w._apply_sidebar_collapse(True);assert w.nav_buttons['collections'].text()==''
    w._apply_sidebar_collapse(False);assert w.nav_buttons['collections'].text()=='Collections'


def test_relationship_refresh_has_visible_feedback_and_grouping(window,monkeypatch):
    w,qt,*_=window;w.show_library(view_mode='Individual Titles');QTest.qWait(80);page=w.stack.currentWidget()
    # Restore the real method, since the shared fixture disables background network.
    from anime_hub.library_franchises import LibraryFranchiseMixin
    monkeypatch.setattr(w,'_request_library_relations',lambda force=False:LibraryFranchiseMixin._request_library_relations(w,force))
    captured={};monkeypatch.setattr(w,'_submit_discover_job',lambda key,op,ok,failed:captured.update(ok=ok,failed=failed))
    next(b for b in page.findChildren(QPushButton) if b.text()=='Refresh relationships').click()
    assert page.findChild(QComboBox,'libraryViewMode').currentText()=='Franchises'
    assert 'Checking' in page.findChild(QLabel,'relationshipStatus').text()
    captured['failed'](RuntimeError('private error must not be printed'));assert 'Could not refresh' in page.findChild(QLabel,'relationshipStatus').text()


def test_virtual_queue_actions_preserve_position_history_and_feedback(window):
    w,qt,*_=window;s=Requests(w.db)
    for i in range(183):s.discover({**remote(1000+i),'title':{'english':f'Queue {i:03}'}})
    feedback=s.add('feedback','Keep feedback','Bug report');w.show_requests();qt.processEvents();queue=w.stack.currentWidget().findChild(AnimeQueue)
    assert queue.model.rowCount()==183 and len(queue.view.findChildren(QPushButton))==0
    queue.view.verticalScrollBar().setValue(2000);qt.processEvents();before=queue.view.verticalScrollBar().value()
    row=queue.model.rows[25];index=queue.model.index(25);queue.view.scrollTo(index);qt.processEvents();before=queue.view.verticalScrollBar().value()
    rect=queue.delegate.buttons(queue.view.visualRect(index).adjusted(2,2,-2,-2),row)[0][0]
    QTest.mouseClick(queue.view.viewport(),Qt.LeftButton,pos=rect.center());qt.processEvents()
    assert s.get(row['id'])['status']=='Approved' and queue.model.rowCount()==182
    assert queue.view.verticalScrollBar().value()==before
    queue.undo_button.click();qt.processEvents();assert queue.model.rowCount()==183 and queue.model.rows[25]['id']==row['id']
    queue.perform(row,'Declined');queue.mode.setCurrentText('History');assert queue.model.rowCount()==1
    queue.perform(queue.model.rows[0],'restore');assert queue.model.rowCount()==0
    queue.mode.setCurrentText('Active Queue');assert queue.model.rowCount()==183
    assert s.get(feedback)['status']=='New' and s.get(feedback)['kind']=='feedback'


def test_large_queue_model_no_widget_per_row(window):
    w,qt,*_=window;s=Requests(w.db)
    with w.db.connection:
        w.db.connection.executemany("INSERT INTO desktop_requests(kind,provider_id,title,category,status) VALUES('anime',?,?,'TV','Requested')",[(2000+i,'Title '+str(i)) for i in range(1500)])
    started=time.perf_counter();w.show_requests();qt.processEvents();queue=w.stack.currentWidget().findChild(AnimeQueue)
    assert queue.model.rowCount()==1500 and len(queue.view.findChildren(QPushButton))==0
    assert time.perf_counter()-started<5


def test_interrupted_schema_migration_rolls_back_then_retries(tmp_path):
    from anime_hub.database import SCHEMA as BASE
    from anime_hub.requests_store import migrate_requests
    conn=sqlite3.connect(tmp_path/'legacy');conn.row_factory=sqlite3.Row;conn.executescript(BASE);conn.executescript(SCHEMA)
    attempts=[]
    def deny_second_column(action,arg1,arg2,*args):
        if action==sqlite3.SQLITE_ALTER_TABLE:
            attempts.append(1)
            if len(attempts)==2:return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    conn.set_authorizer(deny_second_column)
    with pytest.raises(sqlite3.DatabaseError):migrate_requests(conn)
    conn.set_authorizer(None)
    assert 'archived' not in {r[1] for r in conn.execute('PRAGMA table_info(desktop_requests)')}
    assert not conn.execute("SELECT 1 FROM settings WHERE key='request_queue_migrated'").fetchone()
    migrate_requests(conn);assert 'revision' in {r[1] for r in conn.execute('PRAGMA table_info(desktop_requests)')}
    conn.close()


def test_queue_permanent_delete_requires_confirmation_and_cascades(window,monkeypatch):
    from anime_hub.app import AniVaultDialog
    w,qt,aid,*_=window;s=Requests(w.db);key=s.discover(remote(77));s.process(key,'Approved')
    w.show_requests();queue=w.stack.currentWidget().findChild(AnimeQueue);row=s.get(key)
    monkeypatch.setattr(AniVaultDialog,'confirm',lambda *args:False);queue.delete(row);assert s.get(key)
    monkeypatch.setattr(AniVaultDialog,'confirm',lambda *args:True);queue.delete(row)
    with pytest.raises(ValueError):s.get(key)
    assert not s.events(key) and w.db.anime(aid)


def test_history_mode_resets_status_choices_and_searches_notes(window):
    w,qt,*_=window;s=Requests(w.db);key=s.discover(remote(700));s.update(key,'Approved','remember special note')
    w.show_requests();queue=w.stack.currentWidget().findChild(AnimeQueue)
    queue.status.setCurrentText('Requested');queue.mode.setCurrentText('History')
    assert queue.status.currentText()=='All statuses' and queue.status.findText('Requested')<0
    queue.search.setText('special note');queue.filter();assert queue.model.rowCount()==1
    queue.mode.setCurrentText('Active Queue');assert queue.model.rowCount()==0


def test_relationship_success_and_private_ids_excluded(window,tmp_path,monkeypatch):
    from anime_hub.library_franchises import LibraryFranchiseMixin
    w,qt,aid,*_=window;private=anime(w.db,tmp_path/'private',99,True)
    w.show_library();QTest.qWait(50);captured={};queried=[]
    monkeypatch.setattr('anime_hub.anilist_integration.fetch_anime_relations',lambda ids:queried.extend(ids) or [])
    monkeypatch.setattr(w,'_submit_discover_job',lambda key,op,ok,failed:captured.update(op=op,ok=ok))
    LibraryFranchiseMixin._request_library_relations(w,True);captured['ok'](captured['op']())
    assert queried==[11] and 'franchise groups' in w.stack.currentWidget().findChild(QLabel,'relationshipStatus').text()


def test_review_queue_handles_scan_write_lock_without_freezing(window):
    w,qt,*_=window;s=Requests(w.db);key=s.discover(remote(800));w.show_requests();queue=w.stack.currentWidget().findChild(AnimeQueue)
    blocker=sqlite3.connect(w.db.path);blocker.execute('BEGIN IMMEDIATE')
    try:
        started=time.perf_counter();queue.perform(s.get(key),'Approved')
        assert time.perf_counter()-started<.75
        assert s.get(key)['status']=='Requested' and not s.events(key)
        assert 'busy' in queue.notice_text.text().lower()
    finally:blocker.rollback();blocker.close()
    queue.perform(s.get(key),'Approved');assert s.get(key)['archived']
