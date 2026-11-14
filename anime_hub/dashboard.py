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

def rating_summary(entities):
    rated=sorted(((e.local.get('personal_rating_units'),e) for e in entities
                  if e.local.get('personal_rating_units') is not None),
                 key=lambda pair:(pair[0],pair[1].title.casefold(),pair[1].key))
    by_genre={}
    for score,e in rated:
        for genre in {g for g in (e.item.get('genres') or []) if isinstance(g,str)}:
            by_genre.setdefault(genre,[]).append(score)
    return rated,Counter(score for score,_ in rated),by_genre


def analytics(window,data,anime,manga):
    from PySide6.QtWidgets import QPushButton
    from .polish_ui import CompactFilterLayout
    from .hub_ui import HomeTile
    host=QWidget();layout=QVBoxLayout(host);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
    counts=data['statuses'];total=sum(counts.values())
    summary=data['summary']+(('Indexed episodes',data['indexed']),('Watched episodes',data['watched']),('Storage',data['storage']))
    for chunk in (summary[:4],summary[4:]):
        layout.addWidget(stats_strip(chunk))
    def panel(title):
        frame=QFrame();frame.setObjectName('overviewStats');body=QVBoxLayout(frame);body.setContentsMargins(14,12,14,12)
        heading=QLabel(title);heading.setObjectName('section');body.addWidget(heading)
        return frame,body
    def line(body,text):
        label=QLabel(text);label.setWordWrap(True);body.addWidget(label)
    def chart(body, rows, denominator, clickable=False):
        for label,count in rows:
            row=QHBoxLayout()
            if clickable:
                name=QPushButton(label);name.clicked.connect(lambda _,g=label:window.show_library(genre=g))
            else:name=QLabel(label)
            row.addWidget(name,2)
            bar=QProgressBar();bar.setFixedWidth(84);bar.setTextVisible(False)
            bar.setRange(0,max(1,denominator));bar.setValue(count);row.addWidget(bar)
            value=f'{count} · {count/max(1,denominator):.0%}'
            bar.setToolTip(f'{label}: {value}');bar.setAccessibleName(f'{label}: {value}')
            row.addWidget(QLabel(value));body.addLayout(row)
    pair=QHBoxLayout();layout.addLayout(pair)
    frame,body=panel('Library completion');pair.addWidget(frame,1)
    body.addWidget(CompletionRing(data['watched'],data['indexed']),0,Qt.AlignHCenter)
    line(body,f"{counts['Completed']} completed titles · {counts['Watching']} watching or reading")
    line(body,f"{data['watched']} watched · {data['indexed']-data['watched']} unwatched indexed episodes")
    frame,body=panel('Watch & reading status');pair.addWidget(frame,1);chart(body,counts.items(),total)
    pair=QHBoxLayout();layout.addLayout(pair)
    frame,body=panel('Library genres');pair.addWidget(frame,1)
    anime_genres=Counter(g for e in anime for g in {v for v in (e.item.get('genres') or []) if isinstance(v,str)})
    line(body,'Anime titles can count toward multiple genres.')
    genres=anime_genres.most_common()
    chart(body,genres[:6],len(anime),True)
    if not genres:line(body,'No anime genre metadata yet.')
    if len(genres)>6:
        extra=QWidget();inner=QVBoxLayout(extra);chart(inner,genres[6:],len(anime),True);body.addWidget(extra);extra.hide()
        more=QPushButton('Show all genres');more.setCheckable(True);more.toggled.connect(extra.setVisible);body.addWidget(more)
    frame,body=panel('Library composition');pair.addWidget(frame,1)
    formats=Counter()
    for e in anime:
        fmt=str(e.item.get('format') or '').upper()
        formats['TV anime' if fmt in {'TV','TV_SHORT'} else 'Movie' if fmt=='MOVIE' or e.local.get('category')=='Movies' else 'OVA / Special' if fmt in {'OVA','SPECIAL'} else 'Other anime']+=1
    formats['Manga']=len(manga);chart(body,formats.items(),total)
    anime_size,manga_size=data['storage_split'];line(body,f'Indexed storage · Anime: {anime_size} · Manga: {manga_size}')
    frame,body=panel('Personal ratings');layout.addWidget(frame)
    rated,histogram,genre_ratings=rating_summary([*anime,*manga])
    line(body,f'{len(rated)} rated · {total-len(rated)} unrated · {len(rated)/max(1,total):.0%} coverage')
    unrated=QPushButton('Browse unrated anime');unrated.clicked.connect(lambda:window.show_library(state_filter='Unrated'));body.addWidget(unrated,0,Qt.AlignLeft)
    if not rated:line(body,'Rate a title from In Focus or its detail page to see your ratings here.')
    else:
        line(body,f'Average {sum(n for n,_ in rated)/len(rated)/2:.2f} · Highest {rated[-1][0]/2:.1f} · Lowest {rated[0][0]/2:.1f}')
        buckets=QHBoxLayout();peak=max(histogram.values())
        for score in range(2,21):
            stack=QVBoxLayout();bar=QProgressBar();bar.setOrientation(Qt.Vertical);bar.setFixedHeight(56)
            bar.setTextVisible(False);bar.setRange(0,peak);bar.setValue(histogram[score])
            label=f'{score/2:g}';bar.setToolTip(f'{label}: {histogram[score]} titles');bar.setAccessibleName(bar.toolTip())
            stack.addWidget(bar,0,Qt.AlignHCenter);stack.addWidget(QLabel(label),0,Qt.AlignHCenter);buckets.addLayout(stack)
        body.addLayout(buckets)
        for heading,entries in [('Highest rated',sorted(rated,key=lambda p:(-p[0],p[1].title.casefold(),p[1].key))[:3]),('Lowest rated',rated[:3])]:
            line(body,heading);strip=CompactFilterLayout(168)
            for score,e in entries:
                item=QWidget();column=QVBoxLayout(item);column.setContentsMargins(0,0,0,0)
                card=HomeTile(window,e);column.addWidget(card);column.addWidget(QLabel(f'{score/2:.1f} / 10'))
                strip.addWidget(item)
            body.addLayout(strip)
        line(body,'Ratings by genre · average and sample size')
        for genre,values in sorted(genre_ratings.items(),key=lambda p:(-len(p[1]),p[0])):
            line(body,f'{genre} · {sum(values)/len(values)/2:.2f} · {len(values)} rated')
    line(layout,'Historical activity is unavailable. AniVault does not record a separate viewing event history.')
    return host
