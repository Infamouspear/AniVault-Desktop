"""Local dashboard aggregates. No file traversal or viewing-history inference."""
from collections import Counter
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import QFrame,QLabel,QVBoxLayout,QHBoxLayout,QProgressBar,QWidget
from .desktop_ui import overview_stats

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


PINK = "#ff5591"
STATUS_COLORS = ("#58aaf6", "#51dda9", "#c05ff1", "#ffca65", "#fc5873", "#a685ff")
FORMAT_COLORS = (PINK, "#bc51ef", "#58aaf6", "#ffab67", "#9180f4")


class Donut(QWidget):
    def __init__(self, values, colors, number, label, description):
        super().__init__()
        self.values, self.colors = values, colors
        self.number, self.label = number, label
        self.setFixedSize(144, 144)
        self.setAccessibleName(description)
        self.setToolTip(description)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        ring = QRectF(12, 12, 120, 120)
        painter.setPen(QPen(QColor("#343c50"), 16))
        painter.drawEllipse(ring)
        total = sum(self.values)
        angle = 90 * 16
        cumulative = 0
        for value, color in zip(self.values, self.colors):
            if total and value:
                cumulative += value
                end = 90 * 16 - round(cumulative / total * 360 * 16)
                painter.setPen(QPen(QColor(color), 16, Qt.SolidLine, Qt.FlatCap))
                painter.drawArc(ring, angle, end - angle)
                angle = end
        painter.setPen(QColor("#f6f5fc"))
        font = painter.font()
        font.setPixelSize(26)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 42, 144, 37), Qt.AlignCenter, self.number)
        font.setPixelSize(13)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRectF(0, 76, 144, 25), Qt.AlignCenter, self.label)


class Distribution(QWidget):
    def __init__(self, histogram):
        super().__init__()
        self.histogram = histogram
        self.setMinimumHeight(146)
        self.setAccessibleName("Rating distribution, titles by half-point rating")
        self.setToolTip("\n".join(f"{score / 2:.1f}: {histogram[score]} titles" for score in range(2, 21)))

    def paintEvent(self, event):
        from math import ceil
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        left, top, bottom = 32, 10, self.height() - 25
        width = max(1, self.width() - left - 8)
        step = max(1, ceil(max(self.histogram.values(), default=0) / 4))
        for tick in range(5):
            y = bottom - (bottom - top) * tick / 4
            painter.setPen(QPen(QColor("#42495c"), 1, Qt.DashLine if tick else Qt.SolidLine))
            painter.drawLine(left, round(y), left + width, round(y))
            painter.setPen(QColor("#cbd0df"))
            painter.drawText(QRectF(0, y - 8, left - 5, 16), Qt.AlignRight | Qt.AlignVCenter, str(tick * step))
        slot = width / 19
        for index in range(19):
            height = self.histogram[index + 2] * (bottom - top) / (step * 4)
            x = left + index * slot
            if height:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(PINK))
                painter.drawRoundedRect(QRectF(x + slot * .19, bottom - height, slot * .62, height), 3, 3)
            if slot >= 22 or index % 2 == 0:
                painter.setPen(QColor("#cbd0df"))
                painter.drawText(QRectF(x - 5, bottom + 4, slot + 10, 18), Qt.AlignCenter, f"{(index + 2) / 2:.1f}")


def _panel(title=None):
    frame = QFrame()
    frame.setObjectName("statisticsPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 11, 14, 11)
    layout.setSpacing(8)
    if title:
        heading = QLabel(title)
        heading.setObjectName("section")
        layout.addWidget(heading)
    return frame, layout


def _metric(caption, value, icon):
    from .icons import outline_icon
    from PySide6.QtWidgets import QSizePolicy
    frame, layout = _panel()
    row = QHBoxLayout()
    badge = QLabel()
    badge.setObjectName("statisticsIcon")
    badge.setFixedSize(34, 34)
    badge.setAlignment(Qt.AlignCenter)
    if icon.startswith("glyph:"):
        badge.setText(icon.removeprefix("glyph:"))
        badge.setStyleSheet("font-size:22px")
    else:
        badge.setPixmap(outline_icon(icon, active=True).pixmap(22, 22))
    row.addWidget(badge)
    labels = QVBoxLayout()
    labels.setSpacing(1)
    number = QLabel(str(value))
    number.setObjectName("statisticsValue")
    number.setWordWrap(True)
    number.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    name = QLabel(caption)
    name.setWordWrap(True)
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    labels.addWidget(number)
    labels.addWidget(name)
    row.addLayout(labels, 1)
    layout.addLayout(row)
    frame.setMinimumHeight(66)
    return frame


def _legend(layout, rows, colors, total):
    for (name, count), color in zip(rows, colors):
        row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}")
        row.addWidget(dot)
        label = QLabel(name)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        row.addWidget(QLabel(f"{count:,} ({count / max(1, total):.0%})"))
        layout.addLayout(row)


def _donut_panel(title, rows, colors, total):
    panel, body = _panel(title)
    row = QHBoxLayout()
    row.addWidget(Donut([value for _, value in rows], colors, f"{total:,}", "Titles", title))
    legend = QVBoxLayout()
    _legend(legend, rows, colors, total)
    row.addLayout(legend, 1)
    body.addLayout(row, 1)
    return panel


def _rating_entry(window, entity, score):
    from PySide6.QtGui import QIcon, QImageReader, QPixmap
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QPushButton
    title = entity.title if len(entity.title) <= 30 else entity.title[:27].rstrip() + "..."
    button = QPushButton(f"{title}\n★ {score / 2:.1f} / 10")
    button.setToolTip(entity.title)
    button.setMinimumHeight(56)
    button.setStyleSheet("text-align:left")
    covers = window._entity_cover_paths([entity])
    if covers:
        reader = QImageReader(str(covers[0]))
        if reader.size().isValid():
            reader.setScaledSize(reader.size().scaled(70, 88, Qt.KeepAspectRatio))
        poster = QPixmap.fromImage(reader.read())
        button.setIcon(QIcon(poster))
        button.setIconSize(QSize(35, 44))
    button.clicked.connect(lambda: window._open_hub_entity(entity))
    return button


def analytics(window, data, anime, manga, viewport):
    from PySide6.QtWidgets import QGridLayout, QPushButton, QSizePolicy
    from .icons import outline_icon

    host = QWidget()
    host.setObjectName("statisticsDashboard")
    host.setStyleSheet("""
        QFrame#statisticsPanel {background: #131927; border: 1px solid #30374d; border-radius: 13px}
        QLabel#statisticsValue {font-size: 19px; font-weight: bold; color: #fff7fc}
        QLabel#statisticsIcon {background: #362237; color: #ff5591; border-radius: 9px}
        QProgressBar {background: #30384a; border: 0; border-radius: 4px}
        QProgressBar::chunk {background: #ff5591; border-radius: 4px}
        QPushButton[genreLink="true"] {background: transparent; border: 0; padding: 3px; text-align: left}
        QPushButton[genreLink="true"]:hover, QPushButton[genreLink="true"]:focus {color: #ff79a7}
    """)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    header = QHBoxLayout()
    icon = QLabel()
    icon.setPixmap(outline_icon("chart-column", active=True).pixmap(32, 32))
    header.addWidget(icon)
    heading = QVBoxLayout()
    title = QLabel("Statistics")
    title.setObjectName("title")
    heading.addWidget(title)
    subtitle = QLabel("An overview of your library, progress, and personal ratings.")
    subtitle.setWordWrap(True)
    subtitle.setObjectName("muted")
    heading.addWidget(subtitle)
    header.setContentsMargins(0, 0, 0, 4)
    header.addLayout(heading, 1)
    layout.addLayout(header)

    metrics = QGridLayout()
    overview = data["summary"] + (
        ("Indexed episodes", data["indexed"]), ("Watched episodes", data["watched"]),
        ("Library storage", data["storage"]))
    icons = ("layers", "tv", "book-open", "glyph:\u25a6", "glyph:\u2606", "layers", "circle-play", "glyph:\u25b1")
    tiles = [_metric(label, f"{value:,}" if isinstance(value, int) else value, icon)
             for (label, value), icon in zip(overview, icons)]
    layout.addLayout(metrics)

    counts = data["statuses"]
    total = sum(counts.values())
    completion, completion_layout = _panel("Library Completion")
    completed = counts["Completed"]
    completed_fraction = completed / max(1, total)
    row = QHBoxLayout()
    row.addWidget(Donut([completed, total - completed], [PINK, "#343c50"],
                        f"{completed_fraction:.0%}", "Completed",
                        f"{completed:,} of {total:,} library titles completed"))
    details = QVBoxLayout()
    for text in (f"{completed:,} completed titles", f"{counts['Watching']:,} watching / reading",
                 f"{total:,} total titles",
                 f"{data['watched']:,} / {data['indexed']:,} episodes watched "
                 f"({data['watched'] / max(1, data['indexed']):.2%})",
                 f"{data['indexed'] - data['watched']:,} indexed episodes remaining"):
        line = QLabel(text)
        line.setWordWrap(True)
        details.addWidget(line)
    row.addLayout(details, 1)
    completion_layout.addLayout(row, 1)
    status = _donut_panel("Watch & Reading Status", list(counts.items()), STATUS_COLORS, total)

    formats = Counter(dict.fromkeys(("TV Anime", "Movies", "OVA / Special", "Other Anime", "Manga"), 0))
    for entity in anime:
        fmt = str(entity.item.get("format") or "").upper()
        category = entity.local.get("category")
        key = ("TV Anime" if fmt in {"TV", "TV_SHORT"} else
               "Movies" if fmt == "MOVIE" or category == "Movies" else
               "OVA / Special" if fmt in {"OVA", "SPECIAL"} else "Other Anime")
        formats[key] += 1
    formats["Manga"] = len(manga)
    composition = _donut_panel("Library Composition", list(formats.items()), FORMAT_COLORS, total)
    donuts = QGridLayout()
    layout.addLayout(donuts)

    genres, genre_layout = _panel("Top Genres")
    genre_layout.itemAt(0).widget().setToolTip("Anime titles can count toward multiple genres.")
    ranked_genres = Counter(g for entity in anime for g in {
        value for value in (entity.item.get("genres") or []) if isinstance(value, str)
    }).most_common()
    extra = QWidget()
    extra_layout = QVBoxLayout(extra)
    extra_layout.setContentsMargins(0, 0, 0, 0)
    for index, (genre, count) in enumerate(ranked_genres):
        line = QHBoxLayout()
        link = QPushButton(genre)
        link.setProperty("genreLink", True)
        link.clicked.connect(lambda _, name=genre: window.show_library(genre=name))
        link.setFixedWidth(112)
        link.setText(link.fontMetrics().elidedText(genre, Qt.ElideRight, 106))
        link.setToolTip(genre)
        line.addWidget(link)
        bar = QProgressBar()
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setRange(0, max(1, len(anime)))
        bar.setValue(count)
        value = f"{count:,} ({count / max(1, len(anime)):.0%})"
        bar.setAccessibleName(f"{genre}, {value}")
        line.addWidget(bar, 1)
        label = QLabel(value)
        label.setFixedWidth(82)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line.addWidget(label)
        (genre_layout if index < 6 else extra_layout).addLayout(line)
    if len(ranked_genres) > 6:
        genre_layout.addWidget(extra)
        extra.hide()
        more = QPushButton("Show All Genres")
        more.setCheckable(True)
        def toggle_genres(expanded):
            extra.setVisible(expanded)
            more.setText("Show Fewer Genres" if expanded else "Show All Genres")
        more.toggled.connect(toggle_genres)
        genre_layout.addWidget(more)
    if not ranked_genres:
        genre_layout.addWidget(QLabel("No anime genre metadata yet."))
    genre_layout.addStretch()

    ratings, rating_layout = _panel("Personal Ratings")
    rated, histogram, genre_ratings = rating_summary([*anime, *manga])
    average = f"{sum(n for n, _ in rated) / len(rated) / 2:.2f} / 10" if rated else "—"
    rating_tiles = [_metric(label, value, icon) for label, value, icon in (
        ("Average rating", average, "glyph:\u2606"), ("Rated titles", len(rated), "bookmark"),
        ("Unrated titles", total - len(rated), "glyph:\u25cb"),
        ("Library rated", f"{len(rated) / max(1, total):.0%}", "chart-column"))]
    rating_metrics = QGridLayout()
    rating_layout.addLayout(rating_metrics)
    rating_body = QGridLayout()
    rating_layout.addLayout(rating_body)
    chart = QWidget()
    chart_layout = QVBoxLayout(chart)
    chart_layout.setContentsMargins(0, 0, 0, 0)
    chart.setStyleSheet("QWidget {background: transparent}")
    chart_layout.addWidget(QLabel("Rating Distribution"))
    chart_layout.addWidget(Distribution(histogram))
    extremes = QWidget()
    extremes_layout = QVBoxLayout(extremes)
    extremes_layout.setContentsMargins(0, 0, 0, 0)
    extremes.setStyleSheet("QWidget {background: transparent}")
    actions = QHBoxLayout()
    if rated:
        highest = sorted(rated, key=lambda pair: (-pair[0], pair[1].title.casefold(), pair[1].key))
        for label, entries in (("Highest Rated", highest), ("Lowest Rated", rated)):
            extremes_layout.addWidget(QLabel(label))
            score, entity = entries[0]
            entry = _rating_entry(window, entity, score)
            entry.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            extremes_layout.addWidget(entry)
            if len(entries) > 1:
                tip = "\n".join(f"{e.title} · {n / 2:.1f}" for n, e in entries if n == score)
                entry.setToolTip(tip)
        genre_stats = QPushButton("Ratings by Genre")
        from PySide6.QtWidgets import QMenu
        menu = QMenu(genre_stats)
        for genre, values in sorted(genre_ratings.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            menu.addAction(f"{genre} · {sum(values) / len(values) / 2:.2f} · {len(values)} rated").setEnabled(False)
        if genre_ratings:
            genre_stats.setMenu(menu)
            actions.addWidget(genre_stats)
    else:
        empty = QLabel("Rate a title from In Focus or its detail page to see your ratings here.")
        empty.setWordWrap(True)
        extremes_layout.addWidget(empty)
    extremes_layout.addStretch()
    unrated = QPushButton("Browse Unrated Anime")
    unrated.clicked.connect(lambda: window.show_library(state_filter="Unrated"))
    actions.addWidget(unrated)
    actions.addStretch()
    rating_layout.addLayout(actions)
    lower = QGridLayout()
    layout.addLayout(lower)

    storage, storage_layout = _panel("Storage Usage")
    anime_bytes, manga_bytes = data["storage_bytes"]
    size = anime_bytes + manga_bytes
    storage_layout.addWidget(QLabel(f"{data['storage']} indexed"))
    if size:
        bar = QFrame()
        bar.setFixedHeight(16)
        bar.setStyleSheet("background:#30384a;border-radius:5px")
        segments = QHBoxLayout(bar)
        segments.setContentsMargins(0, 0, 0, 0)
        segments.setSpacing(0)
        for amount, color in zip((anime_bytes, manga_bytes), (PINK, "#a685ff")):
            if amount:
                segment = QFrame()
                segment.setStyleSheet(f"background:{color};border-radius:5px")
                segments.addWidget(segment, max(1, round(amount / size * 10000)))
        storage_layout.addWidget(bar)
    legend = QLabel("   ·   ".join(
        f"{label}  {value}" + (f" ({amount / size:.1%} of known size)" if size else "")
        for label, value, amount in zip(("Anime", "Manga"), data["storage_split"], (anime_bytes, manga_bytes))))
    legend.setWordWrap(True)
    storage_layout.addWidget(legend)
    layout.addWidget(storage)

    def place(grid, widgets, columns):
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
        for index in range(grid.columnCount()):
            grid.setColumnStretch(index, int(index < columns))

    previous = None
    def reflow(width):
        nonlocal previous
        mode = (8 if width >= 1290 else 4 if width >= 650 else 2,
                3 if width >= 1090 else 1, width >= 1090, width >= 590)
        if mode == previous:
            return
        previous = mode
        columns, chart_columns, split, wide_ratings = mode
        place(metrics, tiles, columns)
        place(donuts, (completion, status, composition), chart_columns)
        place(rating_metrics, rating_tiles, 4 if split or width >= 650 else 2)
        place(rating_body, (chart, extremes), 2 if wide_ratings else 1)
        rating_body.setColumnStretch(0, 2)
        place(lower, (genres, ratings), 2 if split else 1)
        if split:
            lower.setColumnStretch(1, 2)

    from PySide6.QtCore import QObject, QEvent
    class Reflow(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Resize:
                reflow(event.size().width())
            return False
    guard = Reflow(host)
    viewport.installEventFilter(guard)
    reflow(viewport.width())
    return host
