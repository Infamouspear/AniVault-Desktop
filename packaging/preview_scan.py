"""Preview scanner changes on a temporary SQLite backup using local files only."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anime_hub.database import Database
from anime_hub.reconciliation import health
from anime_hub.scanner import scan


def snapshot(db):
    result = {}
    kinds = Counter()
    for row in db.anime_list(include_retired=True):
        if db.anime_scope(row, fresh=False) != 'normal':
            continue
        media = Counter(item['kind'] for item in db.media(row['id']) if item['present'])
        if row['active']:
            kinds.update(media)
        result[row['id']] = (row['active'], row['availability'], row['root_path'], media)
    return result, dict(kinds)


def compare(database, root=None):
    with TemporaryDirectory(prefix='anivault-preview-') as work:
        copy = Path(work) / 'vault.db'
        source = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        db = Database(copy)
        try:
            root = root or db.setting('library_root')
            if not root:
                raise ValueError('Pass --root or configure a library root in AniVault.')
            before, before_media = snapshot(db)
            before_health = health(db)
            messages = []
            scan(Path(root).resolve(), db, match_online=False, metadata_status=messages.append)
            after, after_media = snapshot(db)
            return {
                'scan_completed': db.last_scan_completed,
                'before': {'health': before_health, 'media': before_media},
                'after': {'health': health(db), 'media': after_media},
                'changed_source_ids': sorted(key for key in before.keys() | after.keys()
                                             if before.get(key) != after.get(key)),
                'retired_source_ids': sorted(key for key in before.keys() & after.keys()
                                             if before[key][0] and not after[key][0]),
                'messages': messages,
            }
        finally:
            db.connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    result = compare(args.database, args.root)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['scan_completed'] else 1)
