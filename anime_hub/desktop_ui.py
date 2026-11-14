from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget)


def avatar(window, button, asset_dir):
    pix = QPixmap(36, 36)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, 36, 36)
    painter.setClipPath(clip)
    painter.fillRect(pix.rect(), QColor("#262234"))
    path = window.db.setting("local_avatar", "")
    image = QImageReader(path or str(asset_dir / "anivault_icon.png"))
    image.setAutoTransform(True)
    size = image.size()
    if size.isValid():
        image.setScaledSize(size.scaled(36, 36, Qt.KeepAspectRatioByExpanding))
        picture = image.read()
        painter.drawImage((36-picture.width())//2, (36-picture.height())//2, picture)
    painter.end()
    from PySide6.QtGui import QIcon
    button.setIcon(QIcon(pix))


def choose_avatar(window, button, asset_dir):
    path, _ = QFileDialog.getOpenFileName(window, "Choose local avatar", filter="Images (*.png *.jpg *.jpeg *.webp)")
    if path and QImageReader(path).canRead():
        window.db.set_setting("local_avatar", path)
        avatar(window, button, asset_dir)


def overview_stats(anime, manga):
    def category(entity):
        return (entity.item.get("format") or entity.local.get("category") or "").upper()
    return (("Library titles", len(anime)+len(manga)), ("Anime", len(anime)),
            ("Manga", len(manga)), ("Movies", sum(category(e) in {"MOVIE","MOVIES"} for e in anime)),
            ("Specials", sum(category(e)=="SPECIAL" for e in anime)))


def stats_strip(stats):
    frame = QFrame()
    frame.setObjectName("overviewStats")
    layout = QHBoxLayout(frame)
    for label, value in stats:
        cell = QVBoxLayout()
        number = QLabel(str(value)); number.setObjectName("statValue"); number.setAlignment(Qt.AlignCenter)
        caption = QLabel(label); caption.setObjectName("muted"); caption.setAlignment(Qt.AlignCenter)
        cell.addWidget(number); cell.addWidget(caption); layout.addLayout(cell, 1)
    return frame


def decorate_search(field):
    from .icons import outline_icon
    field.addAction(outline_icon("search"), QLineEdit.LeadingPosition)
    field.setProperty("toolbarStretch", True)


def library_header(eyebrow,title,subtitle,path=None):
    from .hub_ui import ArtworkHero
    hero=ArtworkHero(path);hero.library_overview=True;hero.setFixedHeight(150)
    layout=QVBoxLayout(hero);layout.setContentsMargins(18,10,18,12);layout.addStretch()
    for text,object_name in ((eyebrow,'eyebrow'),(title,'title'),(subtitle,'muted')):
        label=QLabel(text);label.setObjectName(object_name);layout.addWidget(label)
    return hero
