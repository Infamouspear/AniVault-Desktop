"""Read-only local page sources. All handles belong to the reader worker."""
from __future__ import annotations
import re
import threading
import zipfile
from pathlib import Path
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QImage, QImageReader

IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
PDF_LOCK = threading.Lock()  # PDFium is not thread safe, including across books.
MAX_PAGE_BYTES = 64 * 1024 * 1024
MAX_EDGE = 3072

class ReaderSourceError(Exception):
    pass

def natural_key(name):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', str(name)))

def readable_name(name):
    path = Path(name)
    return path.suffix.lower() in IMAGE_TYPES and not any(
        part.startswith('.') or part == '__MACOSX' for part in path.parts)

def decode_image(data):
    if len(data) > MAX_PAGE_BYTES:
        raise ReaderSourceError('This page exceeds the safe decoding size (64 MiB).')
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer); reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > MAX_EDGE:
        reader.setScaledSize(size.scaled(QSize(MAX_EDGE, MAX_EDGE), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ReaderSourceError(reader.errorString() or 'Unreadable page image.')
    if max(image.width(),image.height())>MAX_EDGE:
        image=image.scaled(MAX_EDGE,MAX_EDGE,Qt.KeepAspectRatio,Qt.SmoothTransformation)
    return image

from PySide6.QtCore import Qt

class ImageSource:
    def __init__(self, path, kind, handle=None):
        self.path, self.kind, self.handle = Path(path), kind, handle
        if kind == 'folder':
            self.pages = sorted([p for p in self.path.iterdir() if p.is_file() and readable_name(p.name)], key=lambda p: natural_key(p.name))
        else:
            self.pages = sorted([p for p in handle.infolist() if not p.is_dir() and readable_name(p.filename)], key=lambda p: natural_key(p.filename))
        self.count = len(self.pages)
        if not self.count:
            self.close(); raise ReaderSourceError('No readable images were found in this item.')

    def image(self, page):
        member = self.pages[page]
        size = member.stat().st_size if self.kind == 'folder' else member.file_size
        if size > MAX_PAGE_BYTES:
            raise ReaderSourceError('This page exceeds the safe decoding size (64 MiB).')
        stream = member.open('rb') if self.kind == 'folder' else self.handle.open(member, 'r')
        with stream:
            return decode_image(stream.read(MAX_PAGE_BYTES + 1))

    def close(self):
        if self.handle is not None: self.handle.close()

class PdfSource:
    kind = 'pdf'
    def __init__(self, path):
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise ReaderSourceError('PDF support needs pypdfium2. Install the build requirements.') from exc
        with PDF_LOCK:
            self.document = pdfium.PdfDocument(str(path))
            self.count = len(self.document)
        if not self.count:
            self.close(); raise ReaderSourceError('This PDF contains no pages.')

    def image(self, index):
        with PDF_LOCK:
            page = self.document[index]
            try:
                width, height = page.get_size()
                scale = min(2., MAX_EDGE / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    pil = bitmap.to_pil().convert('RGBA')
                    data = pil.tobytes()
                    return QImage(data, pil.width, pil.height, pil.width * 4, QImage.Format_RGBA8888).copy()
                finally: bitmap.close()
            finally: page.close()

    def close(self):
        with PDF_LOCK: self.document.close()

def open_source(path, cache_dir):
    path = Path(path)
    if not path.exists(): raise ReaderSourceError('This source no longer exists.')
    if path.is_dir(): return ImageSource(path, 'folder')
    suffix = path.suffix.lower()
    if suffix == '.cbz': return ImageSource(path, 'cbz', zipfile.ZipFile(path, 'r'))
    if suffix == '.pdf': return PdfSource(path)
    if suffix == '.cbr':
        try:
            import rarfile
            # rarfile may build temporary helper archives, never beside source media.
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            config = getattr(rarfile, 'config', rarfile)
            config.HACK_TMP_DIR = str(Path(cache_dir).parent)
            config.USE_EXTRACT_HACK = False  # stream from source; no helper archive copy
            rarfile.tool_setup()
        except Exception as exc:
            raise ReaderSourceError('CBR needs rarfile and a supported RAR tool on PATH, preferably UnRAR. Install UnRAR, restart AniVault, and try again.') from exc
        return ImageSource(path, 'cbr', rarfile.RarFile(path, 'r'))
    raise ReaderSourceError('Choose a CBZ, CBR, PDF, or folder containing page images.')
