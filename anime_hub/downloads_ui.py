from pathlib import Path
import urllib.parse
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame,QScrollArea,QProgressBar,QFileDialog

def size(value):return f'{(value or 0)/1024**2:.1f} MiB'

class DownloadsMixin:
    def show_downloads(self):
        from .app import AniVaultDialog
        self.current_view='downloads';self.current_anime_id=None;self._set_active_nav('downloads')
        from shiboken6 import isValid
        cached=getattr(self,'_downloads_page',None)
        if cached is not None and isValid(cached):self.replace(cached);return
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(22,18,22,18);header=QHBoxLayout();title=QLabel('Downloads');title.setObjectName('title');header.addWidget(title);header.addStretch()
        add=QPushButton('+ Add Direct File');add.setObjectName('primary');header.addWidget(add);clear=QPushButton('Clear Completed');header.addWidget(clear);outer.addLayout(header)
        note=QLabel('Direct HTTP/HTTPS files only. Existing files are never overwritten. Partial transfers stay in .part files.');note.setWordWrap(True);note.setObjectName('muted');outer.addWidget(note)
        scroll=QScrollArea();scroll.setWidgetResizable(True);host=QWidget();body=QVBoxLayout(host);empty=self._empty_state('empty','No downloads yet.',copy='Add a direct file to start a transfer.');empty.setObjectName('muted');body.addWidget(empty);body.addStretch();scroll.setWidget(host);outer.addWidget(scroll);rows={}
        def guarded(action):
            try:action()
            except Exception as exc:AniVaultDialog.alert(self,'Download',str(exc))
        def update(identifier):
            from shiboken6 import isValid
            if not isValid(page):return
            data=self.downloads.get(identifier)
            if not data:
                old=rows.pop(identifier,None)
                if old:old['frame'].deleteLater()
                empty.setVisible(not rows)
                return
            if identifier not in rows:
                frame=QFrame();frame.setObjectName('panel');layout=QVBoxLayout(frame);name=QLabel();name.setWordWrap(True);layout.addWidget(name);details=QLabel();details.setObjectName('muted');details.setWordWrap(True);layout.addWidget(details);bar=QProgressBar();bar.setRange(0,100);layout.addWidget(bar);actions=QHBoxLayout();buttons={}
                for label,action in [('Pause',lambda:self.downloads.pause(identifier)),('Resume',lambda:self.downloads.resume(identifier)),('Cancel',lambda:self.downloads.cancel(identifier)),('Retry',lambda:self.downloads.retry(identifier)),('Open Folder',lambda:self.open_folder(str(Path(data['target']).parent))),('Remove Entry',lambda:self.downloads.remove(identifier))]:
                    button=QPushButton(label);button.clicked.connect(lambda _,f=action:guarded(f));actions.addWidget(button);buttons[label]=button
                actions.addStretch();layout.addLayout(actions);body.insertWidget(body.count()-1,frame);rows[identifier]={'frame':frame,'name':name,'details':details,'bar':bar,'buttons':buttons}
            row=rows[identifier];total=data['total'];downloaded=data['downloaded'];speed=getattr(self.downloads,'speed',0) if identifier==self.downloads.active else 0;eta=(total-downloaded)/speed if total and speed else None
            row['name'].setText(Path(data['target']).name+' · '+data['label'])
            row['details'].setText(data['state']+(f' · {100 if data["state"]=="Completed" else min(100,downloaded/max(1,total)*100):.0f}%' if total is not None else '')+' · '+size(downloaded)+' / '+(size(total) if total is not None else 'Unknown size')+(f' · {speed/1024:.0f} KiB/s' if speed else '')+(f' · ETA {eta:.0f}s' if eta is not None else '')+'\n'+data['target']+('\n'+data['error'] if data['error'] else ''))
            row['bar'].setRange(0,100 if total or data['state']!='Downloading' else 0);row['bar'].setValue(100 if data['state']=='Completed' else int(downloaded/max(1,total or 1)*100) if total else 0)
            state=data['state'];row['buttons']['Pause'].setEnabled(state=='Queued' or (state=='Downloading' and bool(data['resumable'])));row['buttons']['Resume'].setEnabled(state=='Paused' and (not downloaded or bool(data['resumable'])));row['buttons']['Cancel'].setEnabled(state in {'Queued','Downloading','Paused'});row['buttons']['Retry'].setEnabled(state in {'Failed','Cancelled','Paused'});row['buttons']['Remove Entry'].setEnabled(state in {'Completed','Failed','Cancelled'})
            empty.hide()
        def queue():
            url,ok=AniVaultDialog.prompt(self,'Add Direct File','Direct HTTP/HTTPS URL:')
            if not ok or not url.strip():return
            filename=Path(urllib.parse.urlsplit(url).path).name or 'download.bin';target,_=QFileDialog.getSaveFileName(self,'Download Destination',filename)
            if target:guarded(lambda:self.downloads.add(url.strip(),target))
        add.clicked.connect(queue);clear.clicked.connect(lambda:[self.downloads.remove(row['id']) for row in self.downloads.rows() if row['state']=='Completed'])
        self.downloads.changed.connect(update);page.destroyed.connect(lambda:self.downloads.changed.disconnect(update) if not self.downloads.closed else None)
        self._downloads_page=page;self.replace(page)
        for data in self.downloads.rows():update(data['id'])
