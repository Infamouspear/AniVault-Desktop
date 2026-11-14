# V0.8.7 verification

## Implemented

Favorites dispatch now ignores the Qt clicked boolean. Episodes show clean labels. Local and informational details use larger Related cards and separate Extras. Direct status controls update local state without rebuilding the page. Collections show cached cover previews and authoritative counts. Discover filters wrap compactly; the Restricted hero belongs to the scroll body.

Manga titles follow matched AniList, explicit metadata, cleaned parsed title, then raw fallback. This is display-only. All Anime supports Franchises/Individual Titles, defaulting to Franchises. Grouping requires explicit anime-to-anime links between independently matched local records. Similar names and cross-media relations cannot create a group. Manual AniList identity remains authoritative. Overview children retain their normal detail/playback route; relation and release metadata determine useful order. Remote-only related entries remain informational.

Search suggestions are scoped media-only results, local first, with debounce, in-flight dedupe, cache and stale-response guards. Broad franchise matches collapse; specific child queries remain discoverable. AniList relation refresh uses bounded one-hop batches and the existing request queue/cooldown.

## Validation

- Full automated suite: 270 tests passed. The existing 254 tests cover player/watch-state, reader inputs, parsing/extras, matching, sync safety, migration and downloads; 16 new tests cover V0.8.7 behavior.
- Real Qt offscreen interaction checks exercise Favorites navigation, direct statuses, collection actions, search, franchise overview/detail/back, cached pages, resize identity and orderly worker shutdown.
- Synthetic rendered-layout inspection covers informational details, Collections, local details, Discover and Restricted Home.
- 1,051-title fixture: first page population approximately 2,461 ms; cached reopen approximately 92 ms; nine traced database queries. Existing card identities survive reflow.
- 20,000 status-row fixture: indexed count query approximately 0.127 ms versus 1.771 ms before the added covering index. Changes are additive indexes only.
- 1,050-title Normal/Restricted transition fixture: initial Restricted entry 942 ms; cached entries 841–863 ms; lock/normal return 905–972 ms. Successful data/page caches are reused. Theme repolishing remains the main measured transition cost.
- Poster pixmap caches are bounded to 64 MiB each; network artwork disk cache is 128 MiB. Reader page-cache bounds remain unchanged.
- Source-content hashes and persisted raw names remain unchanged in fixtures. Grouping does not merge or rewrite local anime records.

## Limits and manual checks

This environment runs Qt offscreen on Linux. Native Windows VLC rendering, fullscreen transitions on real monitors, mouse input over the native video surface and multi-monitor behavior require manual Windows validation. No actual user library/database was supplied for the Initial D checks; tests use independently matched synthetic entries. The existing player/reader architecture was preserved.

Franchise grouping needs cached or successfully fetched explicit relationships; absent/ambiguous links leave titles individual. No recursive graph crawl is performed. AniList availability and rate limits can delay enrichment. Existing HTTP calls may finish in the background during orderly shutdown; the visible window closes promptly and worker owners remain alive.

No live nHentai/hanime, WebEngine or giant metadata-index initialization was introduced. Existing external Saved records and Restricted privacy remain intact. Source media are read-only: no rename, move, conversion, rewrite or recompression occurs.
