"""Explicit, scoped API projections on a fresh read-only SQLite snapshot."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .database import Database
from .manga_library import MangaStore
from .organization import Organization, metadata
from .lan_auth import APIError


@contextmanager
def snapshot(path):
    db = Database.__new__(Database)
    db.path = Path(path)
    db.connection = sqlite3.connect(db.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.connection.row_factory = sqlite3.Row
    db.connection.execute('PRAGMA query_only=ON')
    db.connection.execute('BEGIN')
    try:
        yield db, MangaStore(db)
    finally:
        db.connection.close()


def fields(row, names):
    return {name: row[name] for name in names if name in row.keys()}


class Catalog:
    def __init__(self, db, manga, scope, data_dir):
        self.db, self.manga, self.scope = db, manga, scope
        self.data_dir = Path(data_dir).resolve()

    def anime(self, identity):
        row = self.db.anime(identity)
        if row is None or not row['active'] or self.db.anime_scope(row) != self.scope:
            raise APIError(404, 'title_not_found')
        return dict(row)

    def series(self, identity):
        row = self.manga.series(identity, self.scope)
        if row is None or (self.scope == 'normal' and metadata(row['metadata_json']).get('isAdult') is True):
            raise APIError(404, 'title_not_found')
        return row

    def media(self, identity):
        row = self.db.media_by_id(identity)
        if row is None or row['kind'] == 'ignore':
            raise APIError(404, 'media_not_found')
        self.anime(row['anime_id'])
        return dict(row)

    def manga_item(self, identity):
        row = self.manga.item(identity)
        if row is None:
            raise APIError(404, 'item_not_found')
        self.series(row['series_id'])
        return row

    def title(self, row, kind):
        info = metadata(row['metadata_json'])
        result = fields(row, ('id', 'anilist_id', 'favorite', 'added_at'))
        result.update(type=kind, title=info.get('title') or row.get('display_title') or row['title'],
            genres=info.get('genres', []), format=info.get('format'), scope=self.scope)
        if kind == 'anime':
            watched, total = self.db.anime_progress(row['id'])
            result.update(progress={'watched': watched, 'total': total}, status=self.db.manual_status(self.scope, anime_id=row['id']))
        else:
            result.update(progress=fields(row, ('completed_count', 'item_count', 'progress', 'last_read')), status=row.get('manual_status'))
        base = '/api/v1/' + ('restricted/' if self.scope == 'restricted' else '')
        result['artwork'] = {role: f'{base}{kind}/{row["id"]}/artwork/{role}' for role in ('poster', 'banner', 'thumbnail')}
        return result

    def anime_list(self):
        result = []
        for row in self.db.anime_list():
            try:
                result.append(self.title(self.anime(row['id']), 'anime'))
            except APIError:
                pass
        return result

    def manga_list(self):
        result = []
        for row in self.manga.series_list(self.scope):
            try:
                result.append(self.title(self.series(row['id']), 'manga'))
            except APIError:
                pass
        return result

    def episode(self, row):
        return fields(row, ('id', 'anime_id', 'kind', 'season', 'episode', 'present', 'watched', 'resume_position_ms', 'watched_at'))

    def volume(self, row):
        return fields(row, ('id', 'series_id', 'volume', 'chapter', 'display_name', 'source_type', 'present', 'current_page', 'total_pages', 'completed', 'percent_complete', 'last_read_at'))

    def entities(self, entries):
        result = []
        for entity in entries:
            if entity.media_type == 'EXTERNAL':
                continue  # Retired external bookmarks are not local LAN media.
            if entity.local:
                try:
                    kind = 'manga' if entity.media_type == 'MANGA' else 'anime'
                    row = self.series(entity.local['id']) if kind == 'manga' else self.anime(entity.local['id'])
                    result.append(self.title(row, kind))
                except APIError:
                    pass
            elif (entity.item.get('isAdult') is True) == (self.scope == 'restricted'):
                result.append({'key': entity.key, 'type': entity.media_type.lower(), 'title': entity.title,
                    'anilist_id': entity.item.get('id'), 'status': entity.status, 'scope': self.scope})
        return result

    def read(self, route):
        if len(route)==3 and route[0]=='media' and route[2]=='progress':
            return self.episode(self.media(int(route[1])))
        if route == ['library']:
            return {'anime': len(self.anime_list()), 'manga': len(self.manga_list()), 'scope': self.scope}
        if route == ['anime']:
            return self.anime_list()
        if route == ['manga']:
            return self.manga_list()
        if route == ['recently-added']:
            return sorted(self.anime_list() + self.manga_list(), key=lambda r: r.get('added_at') or '', reverse=True)[:50]
        if route == ['continue-watching']:
            ids = {r['id'] for r in self.db.continue_watching()}
            resumed = {r[0] for r in self.db.connection.execute('SELECT DISTINCT anime_id FROM media WHERE resume_position_ms>0 AND watched=0 AND present=1')}
            return [r for r in self.anime_list() if r['id'] in ids | resumed]
        if route == ['continue-reading']:
            return [r for r in self.manga_list() if r['progress'].get('last_read') and r['progress'].get('completed_count', 0) < r['progress'].get('item_count', 0)]
        if route == ['progress']:
            return self.anime_list() + self.manga_list()
        if route and route[0] in {'favorites', 'collections', 'statuses'}:
            org = Organization(self.db, self.manga, self.scope)
            if route == ['favorites']:
                return self.entities(org.favorites())
            if route == ['collections']:
                return [{**fields(r, ('id', 'name', 'description')), 'titles': self.entities(org.collection(r['id']))} for r in self.db.collections(scope=self.scope)]
            if route == ['statuses']:
                return {status: self.entities(org.statuses(status)) for status in ('Watching', 'Completed', 'Planning', 'Paused', 'Dropped')}
        if route == ['franchises']:
            output = []
            for franchise in self.db.franchises():
                rows = self.db.franchise_anime(franchise['id'])
                permitted = []
                for row in rows:
                    try:
                        permitted.append(self.title(self.anime(row['id']), 'anime'))
                    except APIError:
                        pass
                # A mixed-scope franchise name/description may identify private titles.
                if permitted and len(permitted) == len(rows):
                    output.append({**fields(franchise, ('id', 'name', 'description')), 'titles': permitted,
                        'artwork': permitted[0]['artwork']})
            return output
        if len(route) >= 2 and route[0] in {'anime', 'manga'}:
            try:
                identity = int(route[1])
            except ValueError:
                raise APIError(404, 'route_not_found')
            kind = route[0]
            row = self.anime(identity) if kind == 'anime' else self.series(identity)
            items = [self.episode(r) for r in self.db.media(identity)] if kind == 'anime' else [self.volume(r) for r in self.manga.items(identity)]
            if len(route) == 2:
                return {**self.title(row, kind), 'items': items}
            if len(route) == 3 and route[2] in {'episodes', 'volumes', 'progress'}:
                return items
            if len(route) == 3 and route[2] == 'related':
                # Only locally scoped, known records; do not return nested raw AniList metadata.
                if kind == 'manga':
                    return []
                franchise = self.db.anime_franchise(identity)
                return next((r['titles'] for r in self.read(['franchises']) if franchise and r['id'] == franchise['id']), [])
        raise APIError(404, 'route_not_found')

    def artwork(self, kind, identity, role):
        if role not in {'poster', 'banner', 'thumbnail'}:
            raise APIError(404, 'artwork_not_found')
        row = self.anime(identity) if kind == 'anime' else self.series(identity)
        info = metadata(row['metadata_json'])
        value = info.get('banner_path') if role == 'banner' else info.get('cover_path')
        if kind == 'manga' and role != 'banner':
            value = row.get('manual_cover_path') or row.get('cover_path') or value
            if not value and row.get('anilist_id'):
                cached = self.data_dir / 'cache' / 'manga_covers' / f'anilist-{row["anilist_id"]}.png'
                if cached.is_file():
                    value = str(cached)
            if not value:
                for item in self.manga.items(identity):
                    cached = self.data_dir / 'cache' / 'manga_covers' / (item['reader_identity'] + '-' + str(int(item.get('modified', 0) * 1000000)) + '.png')
                    if cached.is_file():
                        value = str(cached)
                        break
        if not value:
            raise APIError(404, 'artwork_not_cached')
        path = Path(value).resolve()
        roots = [self.data_dir / 'cache' / name for name in ('artwork', 'manga_covers')]
        if kind == 'manga':
            roots.append(Path(row['root_path']).resolve())
        if not any(path.is_relative_to(root.resolve()) for root in roots) or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.gif'} or not path.is_file():
            raise APIError(404, 'artwork_not_found')
        if self.scope == 'normal':
            # A shared path is private if any explicitly Restricted title references it.
            private = []
            for candidate in self.db.anime_list():
                info = metadata(candidate['metadata_json'])
                if self.db.anime_scope(candidate) == 'restricted':
                    private.extend(info.get(k) for k in ('cover_path', 'banner_path'))
            for candidate in self.manga.series_list('restricted'):
                info = metadata(candidate['metadata_json'])
                private.extend([candidate.get('cover_path'), candidate.get('manual_cover_path'), info.get('cover_path'), info.get('banner_path')])
                if candidate.get('anilist_id'):
                    private.append(str(self.data_dir / 'cache' / 'manga_covers' / f'anilist-{candidate["anilist_id"]}.png'))
            if any(Path(p).resolve() == path for p in private if p):
                raise APIError(404, 'artwork_not_found')
        return path

    def media_path(self, identity):
        row = self.media(identity)
        anime = self.anime(row['anime_id'])
        path = Path(row['path']).resolve()
        if not row['present'] or not path.is_file() or not path.is_relative_to(Path(anime['root_path']).resolve()) or path.suffix.lower() not in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.m2ts', '.wmv'}:
            raise APIError(404, 'media_unavailable')
        return path
