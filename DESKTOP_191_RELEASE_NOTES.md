# AniVault Desktop 1.9.1 — Scanner rate-limit and metadata queue hotfix

Status: local Windows/source candidate. Not pushed or published. Public rollback point: https://github.com/Infamouspear/AniVault-Desktop/releases/tag/v1.9.0 . The installed user database and media were not modified during development.

## Verified root causes

1. Every 1.9.0 scan constructed a fresh AniListClient and a fresh in-memory query cache. Unmatched roots and unconfirmed mixed-folder files were therefore searched again on each scan and after restart, including their fallback search variants.
2. AniListClient and anilist_integration.graphql used different request paths. Matching had a per-client limiter, while Discover, airing, related-media and account operations could independently consume the same server allowance. Review created another client with another budget.
3. The local indexing transaction committed before online matching, but both ran in ScanWorker. Its final signal and scan-button state waited for online matching, making an API delay appear to be an unfinished local scan.
4. The mixed-folder loop continued separately after the main matching loop paused. There was no durable per-release/per-operation job state or retry deadline shared across scans.
5. An aggregate pack mentioning OVAs/Specials could create one suggested-match record per regular numbered episode. These were unnecessary independent AniList searches, not distinct releases. The hotfix retains local records but excludes those episodes from the online queue.
6. Existing valid AniList IDs were already preserved on ordinary scans; missing artwork alone did not intentionally clear them. The hotfix keeps that safeguard and gives artwork failures their own durable retry operation.

AniList currently documents a temporary reduced allowance of 30 requests/minute and a burst limiter. The documented response controls are X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After and X-RateLimit-Reset: https://docs.anilist.co/guide/rate-limiting . The implementation uses a conservative initial allowance and adapts to actual headers; it does not depend on a permanently fixed allowance or merely add a larger delay.

## Request scheduling and caching

- All GraphQL request paths use one scheduler per running application/profile. Network concurrency is one; waiting requests have priorities. Simultaneous identical reads are coalesced. Mutations are not blindly repeated or cached.
- Explicit Review/rematch requests have highest priority, followed by unidentified releases, known-ID metadata recovery and background work. Ordinary matched sources are not searched again.
- Successful public request results persist in scope-separated SQLite caches keyed by complete query/variables. Scanner searches and full ID requests normally cache for 24 hours; browse/quick-search results normally cache for five minutes. Complete franchise relationship responses also cache by source ID for seven days, across batch compositions.
- Different field selections remain different request-cache entries. Minimal relation fields returned during matching are not substituted for richer detail responses.
- No-match and ambiguous job outcomes normally retry after 24 hours, a changed source identity/fingerprint, or an explicit user rematch. Existing recent, completed negative reports are imported from 1.9.0 on upgrade; transient errors are not imported as permanent no-match results.
- Network outages/timeouts use a shared increasing backoff, starting at one minute and capped at one hour. Invalid responses have a separate five-minute retry policy. HTTP 429 honors server retry/reset headers and persists the shared pause. No local discovery restarts are caused by these conditions.
- Header pacing, recent request accounting and shared pauses survive application restart. Completed work is not resent just because a new scan/client starts.
- Artwork uses validated local/CDN caches and a separate retry job, normally one hour after a download failure. Its failure never falls back to a full title search. Blank metadata on a confirmed identity uses that ID rather than inventing a new match.
- Authenticated responses and mutations are not persisted in the public request cache. Diagnostics contain feature names, hashed keys, counters and statuses, without query text, titles, paths, tokens or raw server error bodies. Restricted caches remain separate; normal matching explicitly requests non-adult results and never enqueues known Restricted sources.

## Durable jobs and UI behaviour

Local Library Scan discovers/parses/indexes files, commits, and reports completion independently of AniList. It emits metadata jobs rather than waiting on the API. The user can browse and play indexed media while online work is deferred.

Metadata jobs have a unique scope/target/operation key, source fingerprint, revision, state, outcome, retry time and processing lease. A changed source updates the existing job instead of creating duplicate pending copies. Lease recovery handles interrupted/dead workers. Completed and unresolved jobs survive restarts. One persistent metadata worker continues eligible unfinished jobs without running file discovery again.

Manual corrections remain authoritative. An in-flight response cannot overwrite a newly confirmed manual choice or a newer source revision. Leaving a release unmatched suppresses automatic identification. Clear manual correction deliberately re-enables its identification job. Auxiliary artwork/ID recovery retains the confirmed identity.

Scanner Review shows separate local and online progress, pending/completed jobs, unresolved entries, actual failed API-request counts, selected-source job status and the next eligible attempt when known. Pause metadata and Resume metadata act on online work, not local indexing. Existing diagnostic export includes queue state, request/cache/coalescing counters, retry reasons and persisted processing duration. Processing duration measures active batch work, excluding idle backoff waits.

## Measured request counts

The reproducible mocked library contains nine roots and 16 videos: Arifureta seasons 1/2/3; Cyberpunk seasons 1/2; four shared My Hero OVA files; two unresolved releases; and an aggregate season/OVA/special pack containing three numbered episodes and two extras. Both versions use the same fixture files and mocked API data.

| Cycle | 1.9.0 | 1.9.1 |
| --- | ---: | ---: |
| Initial scan / cold identification | 28 | 21 |
| Unchanged rescan | 26 | 0 |
| Restart, then unchanged rescan | 26 | 0 |
| Total | 80 | 21 |

This is 59 fewer requests (73.75%) over these three cycles; it is not a claim that every library will achieve that percentage. Unique uncached searches still require API budget and can legitimately wait. Cold-scan reduction comes from excluding ordinary episode jobs; subsequent reductions come from durable results/jobs and caching.

An earlier eight-root/11-video fixture, before adding the aggregate-pack case, measured 15/13/13 versus 15/0/0 (41 versus 15). Both measurements used mocked HTTP and consumed no live AniList allowance.

Reproduce using an extracted 1.9.0 source archive and the current source, with a fresh output directory:

    python packaging/measure_metadata_requests.py before --baseline-source PATH_TO_190_SOURCE --workdir NEW_WORK_DIRECTORY
    python packaging/measure_metadata_requests.py after --workdir NEW_WORK_DIRECTORY

The helper refuses to reuse an existing benchmark library and records each cycle's request count. Delays are disabled in this deterministic measurement; its timings are not production network-performance claims.

## Real-source and safety verification

A read-only snapshot of the actual installed database was scanned against the available real media tree using a separate development database. That copy covered 119 roots, retained all 1,851 old media IDs and their ownership/watched/resume fields, and indexed 1,852 records afterward. Ratings, favorites, collection entries and manual statuses were unchanged.

The observed local scans took about 0.72 seconds in one check and 1.09 seconds in the final check; each made zero API requests. A simulated offline metadata pass made one attempted request, scheduled a shared retry, and made no immediate duplicate attempts. The final copied queue had 14 pending jobs and 15 previously unresolved entries; known Restricted sources were absent from the normal queue. These are copy-based observations, not claims that the installed library has already been repaired.

The actual Qt Review screen was exercised and captured from this isolated copy. It showed local completion while metadata was deferred. Worker shutdown completed without an extra scan. No real API calls were used for the request-count or offline simulations.

The existing release backup remains in place. A populated pre-hotfix database receives an additional SQLite backup before first creating the metadata queue. New metadata_jobs and metadata_job_metrics tables are additive; media/progress/ratings/collection records are not rebuilt or deleted. Request caches are disposable and are not part of the installer's inputs. Preserve the 1.9.0 installer and its pre-upgrade database backup for rollback.

## Regression coverage and limits

Tests cover repeated scans, coalescing, shared headers/cooldowns, Retry-After seconds and dates, adaptive limits, exponential transient backoff, timeout/invalid-response distinction, negative-cache expiry, restart/dead-worker recovery, manual authority/clear correction, changed identities, known-ID recovery, independent artwork retries, ordinary episodes in aggregate packs, structural labels, priority, bounded workers, Restricted isolation and existing Arifureta/Cyberpunk/My Hero matching cases. Final validation: 517 full-suite tests passed in 624.50 seconds; 65 final focused scanner/queue/franchise checks passed in 24.76 seconds, including the bounded detail-queue case added after full-suite collection. Frozen TLS and AniList probes exited 0; the clean bundle audit passed and all 89 staged application files matched the source. The delivery's HOTFIX-NOTES.md includes artifact and checksum details.

- Unique new lookups can still take time under a shared server budget. Background metadata legitimately remains pending while local indexing is complete.
- Shared accounting/coalescing is per running application instance; other devices/app instances on the same IP can consume server allowance. Server 429/reset headers are still honored.
- Explicit interactive Review/Discover requests do not automatically re-open their UI after restart. Cached responses persist; durable normal-library identification, known-ID and artwork work resumes independently. Authenticated mutations are not blindly replayed.
- The durable normal-library worker excludes Restricted sources. Explicit authorized private requests share the limiter but use the private cache and existing authorization controls.
- A changed source is reevaluated immediately; a still-fresh cached search response may be reused. Explicit Review/rematch bypasses that response cache while still respecting the shared budget.
- Existing ambiguous multi-season containers remain reviewable; the hotfix does not split/merge their local records or accept weaker identities to reduce requests.
- API request/cache counters are per session; job state, failed-request counts, retry times and accumulated active-processing duration persist. Backups are retained rather than automatically purged.
- This update contains no Remote/Web development.
