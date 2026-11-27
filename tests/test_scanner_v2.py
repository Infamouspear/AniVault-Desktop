from anime_hub.database import Database
from anime_hub.scanner import scan


def video(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + '.mkv')).touch()


def test_queens_blade_extras_and_playback(tmp_path):
    root = tmp_path / 'Anime'
    release = root / "Queen's Blade 2 - The Evil Eye (2009)"
    for number in range(1, 13):
        video(release, f'S02E{number:02}')
    for folder in ('CD', 'Live-Action', 'Menus', 'OP & ED', 'PV', 'Specials'):
        for number in range(1, 5):
            video(release / folder, f'S02E{number:02}')
    db = Database(tmp_path / 'vault.db')
    try:
        assert scan(root, db, match_online=False) == 1
        row, = db.anime_list()
        assert row['episode_count'] == 12
        episodes = {r['episode']: r for r in db.media(row['id']) if r['kind'] == 'episode'}
        assert db.adjacent_episode(row['id'], episodes[1]['id'], 1)['id'] == episodes[2]['id']
        assert len(db.media(row['id'])) == 36
    finally:
        db.connection.close()


def test_arifureta_seasons_and_mixed_pack_suffix(tmp_path):
    root = tmp_path / 'Anime'
    for season, count in enumerate((13, 12, 16), 1):
        release = root / (f'Arifureta S{season:02}' + ('+SP' if season == 2 else ''))
        for number in range(1, count + 1):
            video(release, f'S{season:02}E{number:02}')
        if season == 2:
            video(release, 'Arifureta SP01')
    db = Database(tmp_path / 'vault.db')
    try:
        assert scan(root, db, match_online=False) == 3
        rows = sorted(db.anime_list(), key=lambda row: row['detected_season'])
        assert [r['parsed_search_title'] for r in rows] == ['Arifureta'] * 3
        assert [r['episode_count'] for r in rows] == [13, 12, 16]
        assert [r['kind'] for r in db.media(rows[1]['id'])].count('special') == 1
    finally:
        db.connection.close()


def test_freezing_bundle_and_alternate_episode(tmp_path):
    root = tmp_path / 'Anime'
    container = root / 'Freezing Complete Series + +OVAs,Specials'
    for title in ('Freezing', 'Freezing Vibration'):
        release = container / title
        video(release, f'{title} - 01')
        video(release, f'{title} - 01v2')
        video(release, f'{title} - 02')
        video(release / 'Specials', f'{title} - S01E03')
    db = Database(tmp_path / 'vault.db')
    try:
        old = db.upsert_anime('legacy-container', 'Freezing bundle', '', 'Other', str(container))
        db.set_favorite(old, True)
        scan(root, db, match_online=False)
        assert not db.anime(old)['active']
        assert db.anime(old)['favorite']
        assert {r['title'] for r in db.anime_list()} == {'Freezing', 'Freezing Vibration'}
        for row in db.anime_list():
            files = db.media(row['id'])
            assert sorted(r['kind'] for r in files) == ['alternate', 'episode', 'episode', 'special']
            assert next(r for r in files if r['episode'] == 1 and r['kind'] == 'episode')['path'].endswith('01v2.mkv')
    finally:
        db.connection.close()


def test_cyberpunk_second_season_cannot_reuse_first_season_metadata(tmp_path):
    from anime_hub.metadata_jobs import process

    root = tmp_path / 'Anime'
    for season in (1, 2):
        video(root / f'Cyberpunk Edgerunners S{season:02}', f'S{season:02}E01')
    matches = [{'id': 120377, 'title': {'english': 'Cyberpunk: Edgerunners'},
                'type': 'ANIME', 'format': 'ONA', 'isAdult': False}]

    def lookup(title, season, year, client, *args):
        from anime_hub.metadata import search_variants
        client.query_cache = {variant: {'data': {'Page': {'media': matches}}}
                              for variant in search_variants(title)}
        return client.lookup(title, season, year, *args)

    db = Database(tmp_path / 'vault.db')
    try:
        scan(root, db, match_online=False)
        process(db, lookup=lookup, include_artwork=False)
        rows = sorted(db.anime_list(), key=lambda row: row['detected_season'])
        assert [r['anilist_id'] for r in rows] == [120377, None]
        assert rows[0]['id'] != rows[1]['id']
    finally:
        db.connection.close()


def test_alternate_selection_respects_manual_file_classification(tmp_path):
    root = tmp_path / 'Anime'
    release = root / 'Example Show'
    video(release, 'Example Show - 01')
    video(release, 'Example Show - 01v2')
    db = Database(tmp_path / 'vault.db')
    try:
        scan(root, db, match_online=False)
        row, = db.anime_list()
        db.override(str(release / 'Example Show - 01v2.mkv'), 'ignore')
        scan(root, db, match_online=False)
        item, = [file for file in db.media(row['id']) if file['kind'] == 'episode']
        assert item['path'].endswith('01.mkv')
    finally:
        db.connection.close()
