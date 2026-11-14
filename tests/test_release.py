"""Release safety and actual Qt lifecycle checks; no personal dataset needed."""
import importlib.util
import time
import hashlib
import json
import sqlite3
from pathlib import Path
import shutil
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QPushButton,QCheckBox,QComboBox,QLineEdit,QLabel
from PySide6.QtTest import QTest
from anime_hub.database import Database
from anime_hub.branding import StartupTransition,EmptyState
from anime_hub.release_safety import prepare_existing_database,record_release,splash_preferences
from anime_hub.anilist_login import authorization_url
from test_cross_media import window

ROOT=Path(__file__).resolve().parents[1]

def test_preflight_backup_includes_wal_and_keeps_state(tmp_path):
    path=tmp_path/'anime_hub.db';db=Database(path)
    db.connection.execute('PRAGMA journal_mode=WAL')
    db.set_setting('anilist_access_token','TEST-ONLY-PRIVATE-STATE')
    db.set_setting('library_root','synthetic-library');cid=db.create_collection('Kept')
    before=db.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    logs=[];prepare_existing_database(path,logs.append)
    backup=next((tmp_path/'backups').glob('*.db'))
    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT value FROM settings WHERE key='anilist_access_token'").fetchone()[0]=='TEST-ONLY-PRIVATE-STATE'
        assert copy.execute('SELECT name FROM collections WHERE id=?',(cid,)).fetchone()[0]=='Kept'
    record_release(db,logs.append);prepare_existing_database(path,logs.append)
    assert len(list((tmp_path/'backups').glob('*.db')))==1
    assert before==db.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    db.connection.close()

def test_corrupt_database_never_recreated(tmp_path):
    path=tmp_path/'anime_hub.db';path.write_bytes(b'CORRUPT USER DATA');digest=hashlib.sha256(path.read_bytes()).digest()
    with pytest.raises(sqlite3.DatabaseError):prepare_existing_database(path,lambda _:None)
    assert hashlib.sha256(path.read_bytes()).digest()==digest and not (tmp_path/'backups').exists()

@pytest.mark.parametrize('enabled,duration',[(True,'Brief'),(True,'Standard'),(True,'Extended'),(False,'Standard')])
def test_splash_waits_for_ready_and_minimum(gui_application,enabled,duration):
    transition=StartupTransition(gui_application,enabled,duration);window=QWidget()
    QTest.qWait(20);assert not window.isVisible() and not transition.timer.isActive()
    transition.ready(window)
    if enabled:
        assert not window.isVisible()
    QTest.qWait(transition.timer.remainingTime()+100);assert window.isVisible() and transition.splash is None
    if enabled:assert (time.monotonic()-transition.started)*1000>=transition.minimum_ms
    window.close();transition.deleteLater()

def test_splash_preferences_persist_without_revealing_auth(tmp_path):
    path=tmp_path/'anime_hub.db';db=Database(path);db.set_setting('show_splash','0');db.set_setting('splash_duration','Extended');db.connection.close()
    assert splash_preferences(path)==(False,'Extended')

def test_sidebar_icons_and_empty_state_are_independent(window):
    w,qt,*_=window;w.resize(1600,1100);w.show_global_search('no matching item');QTest.qWait(50)
    state=w.stack.currentWidget().findChild(EmptyState)
    assert state.art.isVisible() and w.sidebar.art.isVisible()
    assert all(not button.icon().isNull() for button in w.nav_buttons.values())
    assert w.nav_buttons['all'].text()=='Anime'

@pytest.mark.parametrize('size',[(820,620),(1200,800),(1600,1000)])
def test_empty_art_does_not_overlap_text_or_action(gui_application,size):
    host=QWidget();host.resize(*size)
    from PySide6.QtWidgets import QVBoxLayout
    box=QVBoxLayout(host);state=EmptyState('empty','Nothing here yet',copy='Create a collection to organize your library.');box.addWidget(state)
    button=QPushButton('Create');state.layout().addWidget(button);host.show();state.resize_art();QTest.qWait(20)
    widgets=[state.layout().itemAt(i).widget() for i in range(state.layout().count())]
    assert all(a.geometry().bottom()<b.geometry().top() for a,b in zip(widgets,widgets[1:]))
    assert button.isVisible();host.close()

def test_first_run_has_empty_inputs_and_skip_without_network(window,monkeypatch):
    w,qt,*_=window;w.show_first_run();page=w.stack.currentWidget()
    assert page.objectName()=='firstRunSetup'
    assert all(not edit.text() for edit in page.findChildren(QLineEdit))
    scans=[];monkeypatch.setattr(w,'rescan',lambda:scans.append('anime'))
    next(b for b in page.findChildren(QPushButton) if b.text()=='Start AniVault').click()
    assert w.current_view=='home' and w.db.setting('setup_complete')=='1' and not scans

def test_settings_splash_guided_login_does_not_echo_existing_token(window,monkeypatch):
    w,qt,*_=window;w.db.set_setting('anilist_access_token','TEST-ONLY-SECRET');w.show_settings();page=w.stack.currentWidget()
    assert not any(e.text()=='TEST-ONLY-SECRET' for e in page.findChildren(QLineEdit))
    assert any('PIN / code' in l.text() for l in page.findChildren(QLabel))
    assert not any('Developer Settings'==b.text() for b in page.findChildren(QPushButton))
    page.findChild(QCheckBox,'showSplash').setChecked(False);page.findChild(QComboBox,'splashDuration').setCurrentText('Extended')
    from anime_hub.app import AniVaultDialog
    monkeypatch.setattr(AniVaultDialog,'alert',lambda *a:None)
    next(b for b in page.findChildren(QPushButton) if b.text()=='Save Settings').click()
    assert w.db.setting('show_splash')=='0' and w.db.setting('splash_duration')=='Extended'

def test_public_authorization_url_has_no_secrets():
    url=authorization_url('12345')
    assert 'client_id=12345' in url and 'response_type=token' in url
    assert 'client_secret' not in url and 'access_token' not in url
    with pytest.raises(ValueError):authorization_url('NOT-AN-ID')

def load_packaging(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'packaging'/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_clean_staging_excludes_seeded_user_data(tmp_path):
    stage=load_packaging('stage_release');copy=tmp_path/'source';copy.mkdir();shutil.copytree(ROOT/'anime_hub',copy/'anime_hub',ignore=shutil.ignore_patterns('__pycache__'));shutil.copytree(ROOT/'assets',copy/'assets');shutil.copyfile(ROOT/'main.py',copy/'main.py')
    (copy/'assets/release-public.json').write_text('{"anilist_client_id":"12345"}')
    for location in [copy,copy/'anime_hub',copy/'assets']:
        for name in ['anime_hub.db','settings.json','crash.log','token.env','download_queue.sqlite']:(location/name).write_text('TEST-ONLY-PERSONAL-STATE')
    stage.ROOT=copy;target=tmp_path/'clean';manifest=stage.stage(target)
    assert all('TEST-ONLY-PERSONAL-STATE' not in p.read_text(errors='ignore') for p in target.rglob('*') if p.is_file())
    assert all(Path(r['path']).suffix not in {'.db','.sqlite','.env','.log'} for r in manifest)

def test_staging_rejects_secret_config_and_missing_public_id(tmp_path):
    stage=load_packaging('stage_release');copy=tmp_path/'source';(copy/'assets').mkdir(parents=True);stage.ROOT=copy
    for config in [{'anilist_client_id':''},{'anilist_client_id':'12345','access_token':'TEST-ONLY-SECRET'}]:
        (copy/'assets/release-public.json').write_text(json.dumps(config))
        with pytest.raises(ValueError):stage.stage(tmp_path/'never-created')
        assert not (tmp_path/'never-created').exists()

def test_bundle_audit_rejects_userdata(tmp_path):
    audit=load_packaging('audit_bundle');(tmp_path/'AniVault.exe').write_bytes(b'fixture')
    audit.audit(tmp_path);(tmp_path/'anime_hub.db').write_bytes(b'PRIVATE')
    with pytest.raises(RuntimeError):audit.audit(tmp_path)
