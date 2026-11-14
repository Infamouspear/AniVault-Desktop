"""Source-neutral, one-page-at-a-time Restricted Archive reader."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QScrollArea, QComboBox, QSizePolicy


class ReaderArea(QScrollArea):
    moved = Signal(int)
    def wheelEvent(self,event):
        self.moved.emit(1 if event.angleDelta().y()<0 else -1);event.accept()


class RestrictedReader(QWidget):
    page_changed=Signal(int,int)
    closed=Signal()
    fullscreen_requested=Signal()
    diagnostic=Signal(str)

    def __init__(self,source,gallery,start_page=1,parent=None):
        super().__init__(parent)
        self.source=source;self.gallery=gallery;self.total=int(gallery.get("page_count") or 0)
        self.page=max(1,min(int(start_page),max(1,self.total)));self._cache={};self._requests={};self._generation=0
        self._network=QNetworkAccessManager(self);self._mode="Fit Page";self._rtl=False
        self.setFocusPolicy(Qt.StrongFocus)
        outer=QVBoxLayout(self);outer.setContentsMargins(12,10,12,8);outer.setSpacing(7)
        row=QHBoxLayout();back=QPushButton("← Back");back.clicked.connect(self.closed);row.addWidget(back)
        self.heading=QLabel(gallery.get("title") or "Gallery");self.heading.setMaximumWidth(580);row.addWidget(self.heading);row.addStretch()
        self.counter=QLabel();row.addWidget(self.counter)
        self.fit=QComboBox();self.fit.addItems(["Fit Page","Fit Width"]);self.fit.currentTextChanged.connect(self._set_fit);row.addWidget(self.fit)
        self.direction=QPushButton("RTL: Off");self.direction.clicked.connect(self._toggle_rtl);row.addWidget(self.direction)
        fullscreen=QPushButton("⛶");fullscreen.setToolTip("Fullscreen");fullscreen.clicked.connect(self.fullscreen_requested);row.addWidget(fullscreen);outer.addLayout(row)
        self.area=ReaderArea();self.area.setWidgetResizable(True);self.area.setAlignment(Qt.AlignCenter);self.area.moved.connect(self.turn)
        surface=QWidget();layout=QVBoxLayout(surface);layout.setContentsMargins(0,0,0,0);self.image=QLabel("Loading page…");self.image.setAlignment(Qt.AlignCenter);self.image.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);layout.addWidget(self.image);self.area.setWidget(surface);outer.addWidget(self.area,1)
        bottom=QHBoxLayout();prev=QPushButton("← Previous");nxt=QPushButton("Next →");retry=QPushButton("Retry Page");prev.clicked.connect(lambda:self.go(self.page-1));nxt.clicked.connect(lambda:self.go(self.page+1));retry.clicked.connect(lambda:self._fetch(self.page,True));bottom.addStretch();bottom.addWidget(prev);bottom.addWidget(retry);bottom.addWidget(nxt);bottom.addStretch();outer.addLayout(bottom)
        for key,step in ((Qt.Key_Left,-1),(Qt.Key_Right,1),(Qt.Key_PageUp,-1),(Qt.Key_PageDown,1)):
            shortcut=QShortcut(QKeySequence(key),self);shortcut.setContext(Qt.WidgetWithChildrenShortcut);shortcut.activated.connect(lambda s=step:self.turn(s))
        escape=QShortcut(QKeySequence(Qt.Key_Escape),self);escape.setContext(Qt.WidgetWithChildrenShortcut);escape.activated.connect(self.closed)
        full=QShortcut(QKeySequence(Qt.Key_F),self);full.setContext(Qt.WidgetWithChildrenShortcut);full.activated.connect(self.fullscreen_requested)
        self._render()

    def _set_fit(self,value):self._mode=value;self._render_pixmap()
    def _toggle_rtl(self):self._rtl=not self._rtl;self.direction.setText("RTL: On" if self._rtl else "RTL: Off")
    def turn(self,step):self.go(self.page+(-step if self._rtl else step))
    def go(self,page):
        if page<1 or page>self.total or page==self.page:return
        self.page=int(page);self._generation+=1
        for number,reply in list(self._requests.items()):
            if abs(number-self.page)>2:reply.abort();self._requests.pop(number,None)
        for number in list(self._cache):
            if abs(number-self.page)>3:self._cache.pop(number,None)
        self._render()

    def _render(self):
        self.counter.setText(f"Page {self.page} / {self.total}")
        self.page_changed.emit(self.page,self.total)
        self._render_pixmap()
        if self.page not in self._cache:self._fetch(self.page)
        else:self._preload()

    def _render_pixmap(self):
        pixmap=self._cache.get(self.page)
        if pixmap is None:
            self.image.clear();self.image.setText("Loading page…" if self.page in self._requests or self.total else "No reader pages available.");return
        size=self.area.viewport().size();width=max(1,size.width()-12);height=max(1,size.height()-12)
        scaled=pixmap.scaled(width,height,Qt.KeepAspectRatio,Qt.SmoothTransformation) if self._mode=="Fit Page" else pixmap.scaledToWidth(width,Qt.SmoothTransformation)
        self.image.setPixmap(scaled)

    def resizeEvent(self,event):super().resizeEvent(event);self._render_pixmap()

    def _fetch(self,page,force=False):
        if page<1 or page>self.total or (page in self._requests and not force):return
        if force and page in self._requests:self._requests.pop(page).abort()
        try:url=self.source.page_url(self.gallery,page)
        except Exception as exc:
            if page==self.page:self.image.setText("Page could not be loaded. Select Retry Page.")
            self.diagnostic.emit(f"Page URL resolution failed source={self.source.key} id={self.gallery.get('external_id')} page={page} error={type(exc).__name__}");return
        request=QNetworkRequest(QUrl(url))
        request.setTransferTimeout(15000)
        for header,value in self.source.page_headers().items():request.setRawHeader(header.encode("ascii"),value.encode("utf-8"))
        started=time.perf_counter();stamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        reply=self._network.get(request);self._requests[page]=reply
        self.diagnostic.emit(f"Page fetch source={self.source.key} id={self.gallery.get('external_id')} page={page} request_start={stamp} url={url}")
        def finished():
            active=self._requests.get(page) is reply
            if active:self._requests.pop(page,None)
            data=bytes(reply.readAll());failed=reply.error()!=reply.NetworkError.NoError
            http=reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            content_type=reply.header(QNetworkRequest.ContentTypeHeader)
            health="SUCCESS" if not failed else "HTTP_BLOCKED" if http==403 else "RATE_LIMITED" if http==429 else "NOT_FOUND" if http==404 else "SERVER_ERROR" if isinstance(http,int) and http>=500 else "NETWORK_ERROR"
            self.diagnostic.emit(f"Page response source={self.source.key} id={self.gallery.get('external_id')} page={page} response_at={datetime.now(timezone.utc).isoformat(timespec='seconds')} HTTP={http} final_url={reply.url().toString()} content_type={content_type} bytes={len(data)} elapsed_ms={(time.perf_counter()-started)*1000:.0f} health={health} failure_stage={'image fetch' if failed else 'none'} exception={reply.errorString()[:160] if failed else 'none'}")
            reply.deleteLater()
            if not active:return
            pixmap=QPixmap();ok=not failed and pixmap.loadFromData(data)
            render_health="SUCCESS" if ok else health if failed else "UNEXPECTED_RESPONSE" if str(content_type).lower().startswith("text/html") else "PARSE_ERROR"
            self.diagnostic.emit(f"Page render source={self.source.key} id={self.gallery.get('external_id')} page={page} ok={ok} health={render_health} failure_stage={'image content validation' if not ok and not failed else 'none'} ms={(time.perf_counter()-started)*1000:.0f}")
            if ok:
                self._cache[page]=pixmap
                if page==self.page:self._render_pixmap();self._preload()
            elif page==self.page:self.image.setText("Page could not be loaded. Select Retry Page.")
        reply.finished.connect(finished)

    def _preload(self):
        for page in (self.page+1,self.page-1,self.page+2):
            if 1<=page<=self.total and page not in self._cache and page not in self._requests and len(self._requests)<2:self._fetch(page)

    def closeEvent(self,event):
        for reply in list(self._requests.values()):reply.abort()
        self._requests.clear();super().closeEvent(event)
