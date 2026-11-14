"""Local dashboard aggregates. No file traversal or viewing-history inference."""
from collections import Counter
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import QFrame,QLabel,QVBoxLayout,QHBoxLayout,QProgressBar,QWidget
from .desktop_ui import overview_stats,stats_strip

STATUSES = ("Watching","Completed","Planning","Paused","Dropped","Unassigned")


def storage_text(rows):
    total=sum(r[0] for r in rows)
    known=sum(r[1] for r in rows)
    if total and not known:return 'Rescan needed'
    size=sum(r[2] for r in rows)
    units=('B','KiB','MiB','GiB','TiB','PiB')
    for unit in units:
        if size<1024 or unit==units[-1]:break
        size/=1024
    return (f'{size:.1f} {unit}' if unit!='B' else f'{size} B') + (' (partial)' if known<total else '')


def summarize(anime, manga, episodes):
    statuses=Counter({key:0 for key in STATUSES})
    genres=Counter()
    for entity in [*anime,*manga]:
        state="Watching" if entity.status=="Reading" else entity.status
        statuses[state if state in STATUSES else "Unassigned"]+=1
        genres.update({g for g in (entity.item.get("genres") or []) if isinstance(g,str) and g})
    return dict(summary=overview_stats(anime,manga),statuses=statuses,genres=genres,
                indexed=sum(row[1] for row in episodes),watched=sum(row[2] for row in episodes))


class CompletionRing(QWidget):
    def __init__(self, complete, tracked):
        super().__init__()
        self.fraction=complete/tracked if tracked else None
        self.setFixedSize(78,78)
        self.setAccessibleName(f"{complete} of {tracked} tracked titles completed")

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        ring=QRectF(8,8,62,62)
        painter.setPen(QPen(QColor("#353847"),6));painter.drawEllipse(ring)
        if self.fraction:
            painter.setPen(QPen(QColor("#ff6095"),6,Qt.SolidLine,Qt.RoundCap))
            painter.drawArc(ring,90*16,-round(self.fraction*360*16))
        painter.setPen(QColor("#f7f0f5"))
        painter.drawText(self.rect(),Qt.AlignCenter,f"{self.fraction:.0%}" if self.fraction is not None else "—")


def measures(data, compact=False):
    outer=QFrame();outer.setObjectName("overviewStats");layout=QVBoxLayout(outer)
    heading=QLabel("Library Insights" if compact else "Completion & progress");heading.setObjectName("section");layout.addWidget(heading)
    totals=data["statuses"];count=sum(totals.values());tracked=count-totals["Unassigned"]
    label=QLabel(f"{totals['Completed']} of {tracked} tracked titles completed · {data['watched']} of {data['indexed']} indexed episodes watched")
    label.setWordWrap(True)
    if compact:
        summary=QHBoxLayout();summary.addWidget(CompletionRing(totals["Completed"],tracked));summary.addWidget(label,1);layout.addLayout(summary)
    else:layout.addWidget(label)
    if not compact:layout.addWidget(QLabel(f"{totals['Watching']} in progress · {data['indexed']-data['watched']} indexed episodes unwatched"))
    progress=QProgressBar();progress.setTextVisible(False);progress.setRange(0,max(1,data["indexed"]));progress.setValue(data["watched"]);layout.addWidget(progress)
    if compact:
        line=QLabel(" · ".join(f"{totals[s]} {s.lower()}" for s in ("Watching","Planning"))+
                    ("  |  Top genre: "+data["genres"].most_common(1)[0][0] if data["genres"] else ""))
        line.setWordWrap(True);layout.addWidget(line)
    else:
        for title,values,denominator in (
            ("Watch & reading status",totals.items(),count),
            ("Genres (titles can appear in multiple genres)",data["genres"].most_common(),count)):
            heading=QLabel(title);heading.setObjectName("section");heading.setWordWrap(True);layout.addWidget(heading)
            if not values:layout.addWidget(QLabel("No genre metadata yet."))
            for key,value in values:
                row=QHBoxLayout();name=QLabel(key);name.setMinimumWidth(105);row.addWidget(name)
                bar=QProgressBar();bar.setTextVisible(False);bar.setRange(0,max(1,denominator));bar.setValue(value);row.addWidget(bar,1)
                label=QLabel(f"{value} · {value/max(1,denominator):.0%}");label.setMinimumWidth(82);row.addWidget(label)
                layout.addLayout(row)
        if data.get("storage_split"):
            anime,manga=data["storage_split"];layout.addWidget(QLabel(f"Anime storage: {anime} · Manga storage: {manga}"))
        notes=QLabel("Counts include local public library entries once each, without franchise totals. Completion uses assigned status. Episode counts include indexed, present episode files. Storage reflects present indexed files. Rescan Anime and Manga to fill missing sizes. Weekly and monthly activity require a local timestamped event history; current progress cannot reconstruct it.")
        notes.setWordWrap(True);notes.setObjectName("muted");layout.addWidget(notes)
    return outer
