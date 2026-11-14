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


def requests_page(window):
    page = QWidget(); page.setProperty("transientPage", True)
    layout = QVBoxLayout(page); layout.setContentsMargins(24, 22, 24, 22)
    heading = QLabel("Requests & Feedback"); heading.setObjectName("title")
    layout.addWidget(heading)
    note = QLabel("Local preview · Try the request tracker here. Entries stay on this desktop for this session; LAN submissions are not connected yet.")
    note.setWordWrap(True); note.setObjectName("muted"); layout.addWidget(note)
    rows = getattr(window, "_request_preview", [])
    window._request_preview = rows
    form = QHBoxLayout()
    kind = QComboBox(); kind.addItems(["Show request", "Feature request", "Bug report"])
    title = QLineEdit(); title.setMaxLength(160); title.setPlaceholderText("Title or short summary")
    add = QPushButton("Add request"); add.setObjectName("primary")
    form.addWidget(kind); form.addWidget(title, 1); form.addWidget(add); layout.addLayout(form)
    listing = QListWidget(); layout.addWidget(listing, 1)
    status = QComboBox(); status.addItems(["New", "Planned", "In progress", "Done"])
    layout.addWidget(QLabel("Selected request status")); layout.addWidget(status, 0, Qt.AlignLeft)
    def text(row):
        return "  ·  ".join(row)
    for row in rows:
        listing.addItem(text(row))
    def submit():
        value = title.text().strip()
        if value:
            row = [kind.currentText(), value, "New"]
            rows.append(row); listing.addItem(text(row)); listing.setCurrentRow(len(rows)-1); title.clear()
    def select(index):
        status.setEnabled(index >= 0)
        if index >= 0:
            status.blockSignals(True); status.setCurrentText(rows[index][2]); status.blockSignals(False)
    def change(value):
        index = listing.currentRow()
        if index >= 0:
            rows[index][2] = value; listing.item(index).setText(text(rows[index]))
    add.clicked.connect(submit); title.returnPressed.connect(submit)
    listing.currentRowChanged.connect(select); status.currentTextChanged.connect(change); select(-1)
    return page
