"""Offline presentation helpers for existing Restricted external records.

No source client, metadata provider, browser engine, or reader is initialized.
"""
from pathlib import Path
from urllib.parse import urlsplit


def bookmark_record(value, source=None, external_id=None):
    item = dict(value) if isinstance(value, dict) else {}
    item['source'] = str(source if source is not None else item.get('source') or '')
    item['external_id'] = str(external_id if external_id is not None else item.get('external_id') or '')
    item['title'] = str(item.get('title') or f"External entry {item['external_id']}")
    if item.get('tags') and not isinstance(item['tags'], dict):
        values = item['tags'] if isinstance(item['tags'], (list, tuple)) else [item['tags']]
        item['tags'] = {'tag': [str(value) for value in values]}
    return item


def source_label(source):
    return 'nHentai' if source == 'nhentai' else str(source or 'External source')


def bookmark_url(item):
    """Only ordinary browser URLs; the known legacy identity can recover its link."""
    url = item.get('source_url') or item.get('url')
    if not url and item.get('source') == 'nhentai' and str(item.get('external_id', '')).isdecimal():
        url = f"https://nhentai.net/g/{item['external_id']}/"
    try:
        parts = urlsplit(str(url or ''))
        if parts.scheme in ('https', 'http') and parts.hostname and not parts.username and not parts.password:
            return str(url)
    except ValueError:
        pass
    return None


def cached_artwork_path(item):
    for field in ('cover_path', 'cached_cover_path', 'cover_cache', 'artwork_path'):
        value = item.get(field)
        if not isinstance(value, str) or '://' in value:
            continue
        try:
            path = Path(value)
            if path.is_file():
                return path
        except OSError:
            pass
    return None
