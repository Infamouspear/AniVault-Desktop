# V0.9.0 verification

## Baseline and implementation

Baseline: V0.8.8.1. This is the existing native PySide6 application, not a web mockup. No new database migration or source-media operation was added.

New presentation component: `anime_hub/hub_ui.py`. The existing request worker, metadata cache, local identities, card grids, full detail pages, player and reader remain in use.

## Results

- Full regression suite: **302 passed in 89.37 seconds** (293 existing + 9 V0.9 runtime acceptance tests).
- Final targeted suite after small guard/spacing polish: **40 passed in 8.42 seconds**.
- Python compilation passed.
- Native Qt runtime screenshots inspected at 1600 × 1000: new Home/rail, library/rail and Restricted hero. Synthetic test records were used; no user library was available.
- Runtime resize test: 1600 → 1100 → 1600 hides/restores the rail without recreating existing library cards.
- Ctrl+K focuses the persistent header search. Existing live search tests now target the header, preserving local-first results, thumbnail updates, dedupe, franchise grouping, caching and stale-response guards.
- Rail actions resolve actual local anime media IDs and manga item IDs. Full details remain navigable through existing history.
- Manual status changes update the affected Home tiles/rail without recreating the Home page. Existing system status count tests remain passing.
- Restricted entry and lock clear search text/results and selected private rail content. Existing lock/bookmark/persistence tests remain passing.
- Full-bleed artwork pixel tests pass for portrait, landscape and ultrawide viewports. The shared crop preserves image proportions and fills both viewport edges.
- Discover heroes use the existing successful section response without additional requests. Home reuses cached Discover content where available and avoids requests for sparse/no-affinity profiles.
- Fixture source-file hashes remain unchanged by new UI/status actions; existing source safety, scanner, reader and database migration tests remain passing.

## Backend audit

The following files are byte-for-byte identical to V0.8.8.1: database.py, scanner.py, integrated_player.py, playback.py, local_manga_reader.py, manga_library.py, anilist_integration.py, recommendations.py and downloads.py.

Only application/presentation wiring, the version marker, search scope capture, tests and release documentation changed. No live external adult-source integration was added.

## Remaining manual acceptance / limitations

Tests ran on Linux with Qt's offscreen platform. Windows VLC rendering, fullscreen transitions, real user media, hardware-specific window chrome and live AniList connectivity were not verified here. Test request responses use controlled fixtures.

Manga chapter-progress sync remains deferred. Local page reading progress must not be converted into AniList chapter progress by assumption. The rail exposes metadata already available and cached explicit relations, with full details as the path for fresh relation lookup. Staff/character data are not fetched in the rail. Local preview lists are capped at 48 items; the full detail page retains complete lists.

The original many-to-many organization data, Favorites, watch/read state, Restricted Saved external records and source identities are retained. No user database or media is bundled in the release.
