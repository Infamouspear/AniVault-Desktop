"""Scoped scanner review. Network work uses the application's bounded worker queue."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QListWidget,QListWidgetItem,QTextEdit,QFileDialog,QComboBox
from shiboken6 import isValid
from . import scan_state as state
from .metadata import AniListClient,cache_artwork


def sanitized_report(db,scope='normal'):
    if scope!='normal':raise ValueError('Restricted diagnostics are local only.')
    result=[]
    for row in state.review_rows(db,scope):
        # Deliberate allowlist: no title, filename, description, URL, path, token or raw server error.
        report=row['report'];source=state.source_state(db,row['anime_id'])
        result.append({'record':row['anime_id'],'file_record':row['media_id'],'season':row['season'],'indexed_count':row['count'],'anilist_id':row['anilist_id'],'state':row['state'],'method':source['method'],'locked':bool(row['locked']),'candidate_ids':[c.get('id') for c in report.get('candidates',[]) if c.get('isAdult') is False],'network_error':bool(report.get('network_error'))})
    return {'scanner_report_version':1,'sources':result}


class ScannerReview(QDialog):
    def __init__(self,window,scope='normal',anime_id=None):
        super().__init__(window);self.window=window;self.scope=scope;self.target=None;self.busy=False;self.items=[]
        self.setWindowTitle('Scanner Review');self.resize(1060,740);self.setAttribute(Qt.WA_DeleteOnClose)
        layout=QVBoxLayout(self);title=QLabel('Scanner Review');title.setObjectName('title');layout.addWidget(title)
        note=QLabel('Review uncertain identities without changing your local files or watch progress. Existing links stay in place until you choose a correction.');note.setWordWrap(True);layout.addWidget(note)
        top=QHBoxLayout();self.filter=QComboBox();self.filter.addItems(['Needs attention','All sources']);top.addWidget(self.filter)
        audit=QPushButton('Reevaluate existing links');audit.clicked.connect(self.audit);top.addWidget(audit)
        export=QPushButton('Export sanitized report');export.setVisible(scope=='normal');export.clicked.connect(self.export);top.addWidget(export);top.addStretch();layout.addLayout(top)
        columns=QHBoxLayout();self.sources=QListWidget();self.sources.setMinimumWidth(310);columns.addWidget(self.sources,2)
        right=QVBoxLayout();self.details=QTextEdit();self.details.setReadOnly(True);right.addWidget(self.details,2)
        search=QHBoxLayout();self.query=QLineEdit();self.query.setPlaceholderText('Search AniList manually…');search.addWidget(self.query);self.search_button=QPushButton('Search / Retry');self.search_button.clicked.connect(self.search);self.query.returnPressed.connect(self.search);search.addWidget(self.search_button);right.addLayout(search)
        self.candidates=QListWidget();self.candidates.setIconSize(QSize(64,92));right.addWidget(self.candidates,3)
        actions=QHBoxLayout();self.confirm=QPushButton('Confirm selected match');self.confirm.setObjectName('primary');self.confirm.clicked.connect(self.apply);actions.addWidget(self.confirm)
        leave=QPushButton('Leave unmatched');leave.clicked.connect(lambda:self.apply(unmatched=True));actions.addWidget(leave)
        clear=QPushButton('Clear manual correction');clear.clicked.connect(lambda:self.apply(clear=True));actions.addWidget(clear);right.addLayout(actions)
        artwork=QPushButton('Retry artwork for assigned identity');artwork.clicked.connect(self.retry_art);right.addWidget(artwork)
        self.message=QLabel('');self.message.setWordWrap(True);right.addWidget(self.message);columns.addLayout(right,4);layout.addLayout(columns)
        self.sources.currentRowChanged.connect(self.select);self.filter.currentIndexChanged.connect(self.reload)
        self.reload(anime_id=anime_id)

    def authorized(self):
        if not isValid(self) or not self.window._organization_allowed(self.scope):return False
        return self.target is None or self.window.db.anime_scope(self.target['anime_id'])==self.scope

    def reload(self,*_,anime_id=None):
        if not self.authorized():self.close();return
        key=(self.target['anime_id'],self.target['media_id']) if self.target else None
        rows=state.review_rows(self.window.db,self.scope)
        self.items=[r for r in rows if self.filter.currentIndex() or r['state'] not in ('High Confidence','Existing match','Manual') or r['anime_id']==anime_id]
        self.sources.blockSignals(True);self.sources.clear()
        for row in self.items:self.sources.addItem(f"{row['title']}\n{row['state']} · Season {row['season'] or '—'} · {row['count']} files")
        self.sources.blockSignals(False)
        index=next((i for i,r in enumerate(self.items) if (r['anime_id'],r['media_id'])==key or r['anime_id']==anime_id),0)
        self.sources.setCurrentRow(index if self.items else -1)
        if not self.items:self.details.setPlainText('No sources need attention. Choose All sources to review another match.');self.target=None

    def select(self,index):
        self.target=self.items[index] if 0<=index<len(self.items) else None
        if not self.target:return
        row=self.target;db=self.window.db;source=state.source_state(db,row['anime_id']);report=row['report'];files=db.media(row['anime_id'])
        artwork='Available' if row['item'].get('cover_path') and Path(row['item']['cover_path']).is_file() else 'Retry artwork for assigned identity' if row['anilist_id'] else 'Awaiting identification'
        lines=[f"Local source: {row['source']}",f"Parsed title: {row['title']}",f"Season: {row['season'] or 'Not explicit'} · Format: {source['format_hint'] or 'Unspecified'}",f"Assigned AniList ID: {row['anilist_id'] or 'None'}",f"Decision: {row['state']} · Method: {source['method']} · Manual lock: {'Yes' if row['locked'] else 'No'}",report.get('reason',''),f"Artwork: {artwork}",'Local file provenance:']
        base=Path(db.anime(row['anime_id'])['root_path'])
        for media in files:
            path=Path(media['path'])
            try:name=str(path.relative_to(base))
            except ValueError:name=path.name
            lines.append(f"• {name} · S{media['season']} E{media['episode']}"+(f"–{media['episode_end']}" if media['episode_end'] else '')+(' · Unavailable' if not media['present'] else ''))
        lines.extend(state.safe_json(source['warnings']) or [])
        for decision in report.get('decisions',[]):lines.append(f"Candidate {decision.get('id')}: {decision.get('reason')}")
        self.details.setPlainText('\n'.join(str(v) for v in lines));self.query.setText(row['title']);self.show_candidates(report.get('candidates',[]))

    def show_candidates(self,items):
        self.candidates.clear()
        evidence={d.get('id'):d for d in (self.target or {}).get('report',{}).get('decisions',[])}
        items=sorted(items,key=lambda item:(evidence.get(item.get('id'),{}).get('eligible',False),evidence.get(item.get('id'),{}).get('score',0)),reverse=True)
        for item in items:
            if type(item.get('isAdult')) is not bool or item['isAdult']!=(self.scope=='restricted'):continue
            title=(item.get('title') or {}).get('english') or (item.get('title') or {}).get('romaji') or 'Untitled'
            row=QListWidgetItem(f"{title}\nAniList {item.get('id')} · {item.get('format') or 'Unknown format'} · {item.get('seasonYear') or 'Year unknown'}");row.setData(Qt.UserRole,item)
            decision=evidence.get(item.get('id'))
            if decision:row.setToolTip(decision.get('reason',''))
            if item.get('cover_path'):row.setIcon(QIcon(item['cover_path']))
            self.candidates.addItem(row)
        if self.candidates.count():self.candidates.setCurrentRow(0)

    def run(self,key,operation,done):
        if self.busy or not self.authorized():return
        self.busy=True;self.message.setText('Working…');target=dict(self.target) if self.target else None
        def success(value):
            if not isValid(self):return
            self.busy=False
            if not self.authorized():self.close();return
            if target and self.target and (target['anime_id'],target['media_id'])!=(self.target['anime_id'],self.target['media_id']):self.message.setText('Finished. Select the source again to see its results.');return
            done(value)
        def failure(error):
            if isValid(self):self.busy=False;self.message.setText('The request failed. Local files and existing metadata were retained. Retry when the connection is available.')
        self.window._submit_discover_job('scanner:'+str(id(self))+':'+key,operation,success,failure,priority=True)

    def search(self):
        if not self.target:return
        target=dict(self.target);query=self.query.text().strip();parsed=state.source_state(self.window.db,target['anime_id'])
        if not query:return
        def work():
            client=AniListClient(max_retries=1,should_cancel=lambda:self.window._closing)
            report=client.lookup(query,target['season'] if query==target['title'] else None,detected_format=(target.get('format_hint') or parsed['format_hint']) if query==target['title'] else None,detected_part=parsed['part'] if query==target['title'] else None)
            cache=self.window.db.path.parent/'cache'/('restricted_artwork' if self.scope=='restricted' else 'artwork')
            candidates=[]
            for item in report.candidates:
                if item.get('isAdult') is not (self.scope=='restricted'):continue
                try:item=cache_artwork(item,cache)
                except Exception:pass
                candidates.append(item)
            report.candidates=candidates
            return report,candidates
        def done(value):
            report,candidates=value;db=self.window.db;data=state.report_data(report);data['candidates']=candidates
            if target['media_id']:
                with db.connection:db.connection.execute('UPDATE scan_file_matches SET report=? WHERE media_id=?',(json.dumps(data),target['media_id']))
            else:
                old=state.source_state(db,target['anime_id']);state.record(db,target['anime_id'],state=old['state'],report=data,part=old['part'],format_hint=old['format_hint'])
            self.target['report']=data;self.show_candidates(candidates);self.message.setText(report.failure_reason or 'Choose a candidate and confirm its identity. Nothing has been changed yet.')
        self.run('search',work,done)

    def apply(self,unmatched=False,clear=False):
        if self.busy or not self.target or not self.authorized():return
        selected=self.candidates.currentItem();item=None if unmatched or clear else selected.data(Qt.UserRole) if selected else None
        if not unmatched and not clear and item is None:return
        try:state.manual_match(self.window.db,self.target['anime_id'],item,self.target['media_id'],self.scope,clear)
        except Exception as error:self.message.setText(f'Could not save the correction: {error}');return
        self.window._library_cache_dirty=True;self.window._library_page_cache.clear();self.window._library_franchise_cache={}
        self.reload();self.message.setText('Saved. Watch progress, ratings, favorites and collections were retained.'+(' Automatic matching is enabled again.' if clear else ' This choice is protected during rescans.'))

    def audit(self):
        if self.busy or not self.authorized():return
        path=self.window.db.path;scope=self.scope
        def work():
            from .database import Database
            db=Database(path)
            try:return state.audit(db,scope)
            finally:db.connection.close()
        def done(count):
            self.reload();self.message.setText(f'{count} sources evaluated. Suspicious links were flagged; no identities were replaced.')
        self.run('audit',work,done)

    def retry_art(self):
        if not self.target or not self.target['anilist_id']:return
        target=dict(self.target)
        def work():
            item=dict(target['item'])
            if not (item.get('coverImage') or {}).get('large') and not (item.get('coverImage') or {}).get('extraLarge'):
                from .anilist_integration import graphql
                data=graphql('query($id:Int){Media(id:$id,type:ANIME){id type isAdult coverImage{extraLarge large} bannerImage}}',{'id':target['anilist_id']}).get('Media') or {}
                if data.get('id')!=target['anilist_id'] or data.get('type')!='ANIME' or data.get('isAdult') is not (self.scope=='restricted'):raise ValueError('The artwork identity is not authorized.')
                item.update({k:data[k] for k in ('coverImage','bannerImage') if k in data})
            return cache_artwork(item,self.window.db.path.parent/'cache'/('restricted_artwork' if self.scope=='restricted' else 'artwork'))
        def done(item):
            db=self.window.db
            if target['media_id']:
                with db.connection:db.connection.execute('UPDATE scan_file_matches SET metadata_json=? WHERE media_id=? AND anilist_id=?',(json.dumps(item),target['media_id'],target['anilist_id']))
            elif db.anime(target['anime_id'])['anilist_id']==target['anilist_id']:db.set_metadata(target['anime_id'],target['anilist_id'],item)
            self.window._library_cache_dirty=True;self.reload();self.message.setText('Artwork checked. The assigned identity was preserved.')
        self.run('artwork',work,done)

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export sanitized scanner report','scanner-report.json','JSON (*.json)')
        if path:Path(path).write_text(json.dumps(sanitized_report(self.window.db,self.scope),indent=2),encoding='utf-8');self.message.setText('Exported a report without titles, filenames, private paths or credentials.')


class ScannerReviewMixin:
    def show_scanner_review(self,anime_id=None,scope='normal'):
        if not self._organization_allowed(scope):return
        previous=getattr(self,'_scanner_review_dialog',None)
        if previous is not None and isValid(previous):previous.close()
        dialog=ScannerReview(self,scope,anime_id);dialog.show();self._scanner_review_dialog=dialog
