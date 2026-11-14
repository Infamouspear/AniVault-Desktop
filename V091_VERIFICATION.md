# V0.9.1 verification

## Scope

V0.9.0 is the baseline. Focus View remains a contextual preview. No new database migration, player/reader engine, scanner or live-source integration was introduced.

## Runtime acceptance

The tests exercise rendered widgets, not hidden/retired cards left in the Qt object tree:

- Hover waits 280 ms; leaving cancels the pending preview.
- Click pins the selected local anime, manga or AniList-only card.
- Hover cannot replace a pin; Pinned unpins; intentional click replaces selection.
- Double-click opens the original Full Details route. Franchise cards open their existing overview, with child title details still accessible.
- Enter opens and Space selects. Live search suggestions keep direct navigation.
- Continue Watching/Reading actions operate immediately through existing media/item IDs.
- Continue Reading cards use a direct button while double-click opens series details.
- Episode preview is bounded to three nearby normal episodes. Manga preview uses current/next available local items.
- Status and Favorite updates retain the current browsing page and pin. Collection and cached-related actions use existing organization routes.
- Pending hover is cancelled on navigation, scope change and close.
- Deleted, hidden or out-of-scope cards cannot receive late input and fall back to their old single-click navigation.
- Narrow/wide resizing hides/restores the rail without recreating library cards.
- Long synopsis content cannot enlarge the rail body beyond its viewport.

## Branding acceptance

ASSET_PLACEMENT.md defines the placement map before integration.

Seven supplied PNG assets were copied byte-for-byte; the originals in the upload directory were not modified. The ICO is a multi-resolution format derivative of the transparent supplied icon. Splash art is only referenced by the startup splash helper.

Normal sidebar art is the little fox. Restricted sidebar/hero art is the provided Restricted cutout. Shared empty states use one main illustration per page; sidebar decoration is suppressed when a main illustration is visible. Small windows reduce art size or use text only. Face/body crop is avoided for branding cutouts; media heroes retain focal/aspect cropping.

The supplied All Caught Up PNG has fully opaque alpha. It is preserved unchanged rather than falsely treating its background as transparent.

Rendered native Qt screenshots inspected: pinned Focus View, Restricted hero, and No Results empty state at 1600 × 1000. Test cover data were synthetic; no user library was available.

## Backend audit

These nine files remain byte-for-byte identical to V0.9.0:

database.py, scanner.py, integrated_player.py, playback.py, local_manga_reader.py, manga_library.py, anilist_integration.py, recommendations.py, downloads.py.

Source safety tests retain file hashes, reader resume/bookmarks, watch state, Favorites, Collections, scoped data and external bookmarks. No media/source folder changes are part of this patch.

## Final results

- Full regression suite: **316 passed in 106.60 seconds**.
- Focus/branding acceptance: **14 passed in 7.13 seconds**.
- Python compilation passed.
- ZIP contents exclude user databases, logs, bytecode and caches.

## Test environment

Python 3.12, PySide6 6.11.2, Qt offscreen platform on Linux. The GUI regression harness keeps one QApplication alive for the test session, as pixmaps/widgets share that platform lifetime. Tests expecting the old card-click navigation were updated to double-click or direct Continue buttons.

## Manual limits

Windows taskbar/Alt+Tab/shortcut icon caching, hardware-specific VLC/fullscreen, real user media and Windows input timing still need manual acceptance. No installer is built here; assets/anivault.ico is the shared icon resource for future shortcut/installer packaging.

Manga AniList chapter progress synchronization remains deferred. No private data are bundled in the ZIP. Original supplied PNGs and source media remain unchanged.
