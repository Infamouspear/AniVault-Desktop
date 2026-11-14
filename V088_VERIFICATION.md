# V0.8.8 verification

## Scope and implementation

The V0.8.7 baseline is preserved. Changes are presentation cleanup, a reversible per-item manga completion action using the existing reader state, async search thumbnails, contained wheel behavior and a read-only integrity report. No new source integration, scanner, playback or recommendation architecture was added.

Standard media cards use one shared 228 × 460 outer size, 210 × 258 cover region, 42 px title slot, 20 px primary metadata and 30 px secondary metadata. Notes/actions/progress have reserved positions. Grid column counts remain viewport-driven. Empty action space uses layout spacers rather than extra painted panels. Compact horizontal Home/Related cards and organizational overview covers are intentional separate variants.

Favorites is split by media type. Collection/status/search/detail children now reuse standard cards without the previous taller organization wrappers. Manga completion toggles only the selected item's completion bit. Existing page/percent data, bookmarks, source media and manual series statuses are retained. Counts update without replacing the detail page.

Live suggestion thumbnails are fixed 40 × 56 images in 66 px rows. Visible rows load after the text appears through existing cache/network/local-cover infrastructure; old callbacks cannot update replacement rows or a locked scope. The dropdown event filter now distinguishes editor events from its own viewport events, preventing thumbnail/scrollbar changes from dismissing suggestions.

Nested wheel events are consumed at child boundaries; keyboard focus/navigation remain inherited. Franchise overview spacing is tightened and remote relation labels remain visible. No empty episode-title separator is emitted.

## Checks performed

- Full automated regression suite: **285 passed**, 87.52 seconds.
- Final focused checks after presentation/spacer refinements: **32 passed**, covering V0.8.8, V0.8.7 and the earlier Airing footer clipping safeguard.
- Actual Qt offscreen interactions verify Favorite routing/sections, direct statuses, collection actions, reversible manga completion without page replacement, immediate text suggestions, visible async covers, stale callbacks, contained wheel boundaries and franchise navigation.
- Rendered synthetic-art inspection verifies Favorites, anime/manga details, search thumbnails and franchise overview spacing. These are fixtures, not screenshots of the user's library.
- 1,051-title stress fixture verifies batched reads, incremental population, cached reopening and preserved widget identity on resize. Final measured full population: 3,003 ms; cached reopening: 290 ms on this runtime. The destination remains interactive during incremental population. Nine traced SQL queries; no per-card status queries.
- Read-only integrity checks include SQLite integrity, foreign keys, orphaned relationships/bookmarks, invalid reader/status state and duplicate status/collection keys. Valid caches/remote aliases are not treated as missing local titles. The audit never repairs/deletes ambiguous data.
- Copied fixtures simulate pre-manga, pre-status/pre-scope, pre-Saved removal, pre-Franchise redesign, pre-V0.8.6 and V0.8.7 shapes, plus the oldest unscoped Saved schema. They verify watch/resume, Favorites, manual matches, collections, legacy franchise membership, Restricted Saved and external bookmarks as applicable. Saved-to-Planning retains the archive and existing statuses. Reopening is idempotent.
- Source hashes remain unchanged through item toggles and reader/scanner regression checks. Existing tests cover rescan overrides, extras, reader modes, bookmarks/resume, PDF/CBZ/image folders, download restart/Range/finalization and sync safety.
- Existing non-blocking shutdown checks retain active Qt workers until completion, suppress late callbacks and stop reader/art/download queues. No running-QThread destruction warning was observed in the test run.
- Scanner, integrated-player implementation, reader implementation, AniList sync/recommendation/query definitions and transfer engine remain unchanged from V0.8.7.

## Platform limits / manual acceptance

This environment is Linux with Qt offscreen. Native Windows libVLC rendering/audio/subtitles, fullscreen/multi-monitor geometry and real long-idle input require Windows validation. CBR backend behavior depends on installed UnRAR/7-Zip; dependency absence is handled and tested, but no user's real CBR was available. Live AniList outages/rate limits are exercised with controlled responses, not an account's live state.

Migration checks use representative copies/fixtures; no current user database or actual media library was supplied. Do not interpret this as verification of every historical user database. Ambiguous user data is left intact and logged.

An already-running underlying network call may finish after the visible window closes; owners/callback guards remain in place and configured network timeouts bound normal calls. Restricted theme transitions retain the V0.8.7 implementation and its remaining repolishing cost; no new transition rewrite was attempted.

V0.8's feature scope is frozen. Final native Windows acceptance remains manual before declaring the release universally verified.

## Source safety

Source archives, PDFs, video files, folders and images remain read-only. No rename, move, conversion, recompression or source rewrite is performed. State changes and thumbnails belong only to AniVault's database/cache. Existing external Saved records remain intact. No live nHentai/hanime, WebEngine or metadata-index system was activated.
