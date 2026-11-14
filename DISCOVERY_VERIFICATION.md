# V0.8.5 verification and implementation notes

## Recommendation behavior

Profiles are read-only projections of the existing organization catalog, keyed
by privacy scope and target media type. There is no migration, status rewrite,
watch-progress update, reader-progress update or AniList mutation from ranking.

| Signal | Base contribution |
|---|---:|
| Local Favorite | 6 |
| Completed manual status | 4 |
| Watching / Reading manual status | 3 |
| Actual watch/read completion fraction | 0–4 |
| Recorded watch/read activity | 2 |
| Paused status | 1 |
| Planning status | 0.6 |
| Saved | 0.35 |
| Collection membership with an existing positive signal | 0.25 each, capped at 1 |
| Dropped | No positive seed contribution |

Recency scales these weights with a 60-day decay and a floor for longstanding
interests. Repeated genres/tags reinforce affinity. Spoiler tags are ignored.
Popularity is a tie-breaker. Profiles and ranking are deterministic; View All
ranks each incoming batch, retaining the positions of already-loaded cards.

The broadest strong genre is used for candidate retrieval rather than an AND
query containing every interest. A landing recommendation shelf may inspect up
to three API pages to compensate for local/completed filtering. This bounded
landing fetch does not cap View All pagination. API `hasNextPage` remains the
pagination authority. The existing request queue, deduplication, cache and global
rate-limit cooldown are reused; no new QThreads or relation request storms.

Recommendations remove duplicate IDs, local titles, completed/dropped or at least
80%-consumed targets, wrong media types and wrong adult scope. Local/Saved aliases
share one input identity. Other discovery sections retain their ordinary In Vault
presentation. Overlap between independent Trending/Popular shelves is intentional;
duplicate identities within a shelf are suppressed.

Reasons appear only for meaningful affinity or explicit relations. Actual activity
can produce "Because you watched/read …"; Favorite/status-only signals use more
careful wording. Reasons are transient presentation metadata. No title histories
are added to diagnostics; new logs use scope, media type, counts and filter totals.

Cached explicit AniList relation nodes can supply a small related-title shelf.
Cross-media affinity never uses similar names or the other medium's genres.
Older relation caches without `isAdult` can boost validated API results but cannot
create a card. No recursive relation crawling is introduced.

Profiles and landing pages expire after 15 minutes. SQLite's mutation counter
checks for signal changes; an unchanged fingerprint reuses the profile. Explicit
Refresh Recommendations evicts matching recommendation query pages and uses the
existing request protections to refresh them, retaining unrelated caches.

## Restricted finalization

Normal and Restricted organization catalogs, profiles, local progress, Saved,
statuses and Collections remain isolated even while the archive is unlocked.
Discover/View All refuse locked Restricted routes. Remote detail views require
an explicitly adult record on the Restricted side. Lock stops private player/
reader navigation through the existing replacement lifecycle and retains data.

External Saved entries remain cached bookmark records keyed by source + ID.
Status and Collection actions remain available; Open Source uses the external
browser. They do not require an index/provider and do not seed AniList tag
preferences because their taxonomy is not interchangeable with AniList's.

Code/import audit found no active WebEngine, live NH metadata API, snapshot/index
worker, nHentai discovery/parser or hanime integration. Those integrations were
already removed by the baseline rollback. Harmless source identity storage,
bookmark URL handling, legacy route redirects and an explicitly invoked safe
retired-cache cleanup utility remain. No user-owned or old cache data is deleted.

## Verification performed

- Full regression run: 230 passed, including all 220 pre-existing tests. One new
  pagination test initially failed because it checked Qt scroll geometry before
  the layout settled. Its corrected runtime test passes in the final runs below.
- Final recommendation/organization/V0.7.9 focused suite: 38 passed; exit 0.
  Final standalone recommendation suite: 14 passed; exit 0. Together the runs
  cover all 234 current tests; this is not a claim of one 234-test full-suite run.
- 14 new engine/Qt runtime tests pass: weighting, actual consumption, honest
  reasons, both scope directions, manga types, explicit relations, relation adult
  validation, local/Saved dedupe, Dropped exclusion, stable sparse-data ranking,
  unchanged-profile reuse, cache reuse/refresh and filtered landing-page fill.
- Actual Qt View All test scrolls to page 2: 25 cards become 50, initial widget
  objects/order are retained, repeated IDs/local titles are rejected.
- Organization/rollback/recommendation focused run: 39 passed. Includes external
  bookmark persistence, status/Collections, normal-browser source links, private
  lock/unlock and no WebEngine/provider/index initialization.
- A populated V0.8.4-created database reopened under V0.8.5: all 20 tables and
  stored rows remain identical after catalog/profile reads. External Saved status,
  memberships and history remain intact. Sample source-file SHA-256 hashes match.
- Offscreen normal Discover screenshot inspected: media switch, centered status,
  compact elided reason and Save controls fit existing fixed card dimensions.
- Python compile checks pass. Scanner/parser, player/playback, manga library,
  reader and database implementations are byte-identical to V0.8.4.

## Practical limits

- Tests run on Linux with offscreen Qt 6.11.2 and controlled asynchronous AniList
  responses. Native Windows VLC video/audio/fullscreen and the user's actual
  library require manual testing on the target machine; no claim of testing those
  hardware paths is made. No user database/media was modified during verification.
- Recommendations depend on available AniList metadata. Unmatched local titles
  cannot contribute known genres/tags; missing cached relations are not invented.
  This is a lightweight deterministic affinity engine, not collaborative filtering.
- Favorites retain the existing local anime/manga model. No new nonlocal/external
  Favorite storage, ignored-state schema or destructive migration is introduced.
- View All appends ranked batches rather than globally reranking the session.
  Sparse history falls back to broad popularity/trending without invented reasons.
- Explicit refresh is an intentional request and still observes AniList cooldown;
  ordinary revisits reuse cached pages. Baseline reader/CBR optional dependencies
  and Windows playback requirements remain unchanged.
