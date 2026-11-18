"""Pinned Lucide 0.468.0 outline icons, rendered at device pixel ratio."""
from pathlib import Path
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
NAV_ICONS = {'home':'house','all':'tv','manga':'book-open','watching':'circle-play',
 'recent':'plus','favorites':'heart','discover':'compass','airing':'calendar',
 'planning':'bookmark','collections':'layers','status_hub':'tags','downloads':'download',
 'restricted_overview':'house','restricted_anime':'tv','restricted_manga':'book-open','restricted_discover':'compass','restricted_collections':'layers','restricted_statistics':'chart-column','restricted_lock':'lock','statistics':'chart-column','settings':'settings','restricted':'lock'}
_CACHE = {}

def outline_icon(name, active=False, ratio=1.0):
    key = (name, bool(active), ratio)
    if key not in _CACHE:
        data = (ICON_DIR / (name + '.svg')).read_text().replace('currentColor', '#ff82a7' if active else '#b0bacb')
        pixmap = QPixmap(round(18*ratio), round(18*ratio)); pixmap.setDevicePixelRatio(ratio); pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap); QSvgRenderer(QByteArray(data.encode())).render(painter); painter.end()
        _CACHE[key] = QIcon(pixmap)
    return _CACHE[key]
