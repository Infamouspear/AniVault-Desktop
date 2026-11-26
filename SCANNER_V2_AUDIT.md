# Scanner V2 audit and rollout

The starting point is AniVault Desktop v1.9.3, commit 20f20c0. The Git tag
and the detached baseline checkout remain available for comparison.

## Pipeline and findings

| Stage | v1.9.3 behavior and finding | Candidate behavior |
| --- | --- | --- |
| Discovery | The scanner takes a strict filesystem inventory, then finds release directories. It splits named or numbered child releases when the parent has no direct video. Folder discovery and media classification previously disagreed about which bonus directories were structural. | Structural detection and media classification share the same extras-folder classifier. The existing strict inventory and reversible container retirement remain in use. |
| Classification | A numbered video under CD, Live-Action, Menus, OP & ED, or PV could pass the episode parser. The primary-video fallback could give several unnumbered, ambiguous videos episode numbers. Season suffix parsing left +SP in the AniList search title. | Directory evidence is release-relative and takes precedence over numbering. Extras retain their media records and are grouped in the desktop Extras panel. One automatic version of a numbered episode enters sequential playback. Existing progress takes precedence, then explicit revision and path determine the selection. |
| Local identity | Path-based identity, backed by directory and file IDs on the same filesystem, already preserved in-place IDs and supported verified renames. AniList links were separate from local IDs. | The candidate reuses these identities, media overrides, and Restricted Archive ownership inheritance. |
| Metadata | Search uses the parsed title and alternatives. Candidate scoring checks season, format, and title evidence. Manual locks and per-file review already existed. Old candidate reports could hide a newly detected contradiction. | Existing contradictions are shown in Scanner Review. Existing links with uncertain provenance are retained for manual correction. Automatic jobs cannot overwrite assigned parent metadata. |
| Artwork and grouping | AniList IDs drive artwork recovery and official franchise relationships. Scanner Review reports missing artwork. Custom artwork survives rematching. | The same artwork cache, relationship worker, and manual controls remain in use. |
| Requests | Scanner, Discover, franchise and other AniList callers share a persistent scheduler. It enforces header-derived budget and Retry-After, coalesces duplicate requests, and persists request results. A conclusive unresolved lookup could be retried indefinitely after its cache expired. | The metadata queue gives unresolved searches one delayed retry. The source can be matched again after source evidence changes or through manual review. Rate-limited and temporary network failures retain their deferred jobs. |
| Reconciliation | v1.9.3 already compared complete inventory snapshots and retired confirmed missing sources using active/present flags. Canceled or unreadable roots preserve records. | The preview tool runs the same offline scan on a consistent SQLite backup and reports the projected changes. Reconciliation keeps the existing history, favorite, rating, status and collection records. |
| Library and playback | Desktop counts, Continue Watching and Next Episode use the episode kind. Similar filters feed organization, statistics and LAN catalog. Manga has its own scanner and storage. | Classification flows into those consumers without an episode-count cap. Extra categories are rendered in the existing desktop Extras panel. |

## Preview and rollback

From a source checkout with the app dependencies installed, run:

    python packaging/preview_scan.py "%LOCALAPPDATA%/AnimeHub/anime_hub.db"

Use PowerShell's environment syntax when running there:

    python packaging/preview_scan.py "$env:LOCALAPPDATA/AnimeHub/anime_hub.db"

Supply --root if the database has no configured anime library. The preview
opens the source database read-only, uses the SQLite backup API to capture a
consistent snapshot, and scans the temporary copy without AniList traffic.
The report uses local IDs and aggregate counts for standard-library sources.

The candidate introduces no new schema migration. During a committed rescan,
AniVault creates a before-scan backup under the app data backups directory and
validates it with SQLite quick_check. Record the backup timestamp before
rolling out. To roll back, close AniVault, retain a separate copy of the
current database and sidecar files, restore the selected pre-scan database
with the app stopped, and reinstall the v1.9.3 build if needed. Keep any
post-scan user changes in the retained database copy.

## Known limits

Pre-existing suspicious links need review because their original automatic or
manual provenance may be unknown. The candidate does not infer cross-volume
moves when filesystem identity changes. Entirely unnumbered multi-file series
with no release-format evidence need manual classification. Distinct local
copies on different paths retain separate records. This work does not convert
absent metadata into a presumed official identity.

## Verification on this machine

| Check | v1.9.3 or snapshot before scan | Candidate |
| --- | ---: | ---: |
| Queen's Blade 2 regular episodes on a copy of the real library | 36 | 12 |
| Queen's Blade Grimoire regular episodes | 8 | 2 |
| Queen's Blade Rebellion regular episodes | 33 | 12 |
| Queen's Blade Beautiful Warriors regular episodes | 18 | 6 |
| Standard-library active sources | 127 | 127 |
| Standard-library regular episodes | 1,510 | 1,415 |
| Standard-library items in the ambiguous review count | 13 | 15 |
| Mocked AniList requests, initial scan | 21 | 16 |
| Mocked requests, immediate unchanged rescan | 0 | 0 |
| Mocked requests, unchanged rescan after process restart | 0 | 0 |

The preview found no additional source retirement in the current library. The
Freezing container was already retired, with both children active and 12 regular
episodes each. Existing distinct AniList links and 13, 12 and 16 episodes were
observed for the three Arifureta seasons. The two Cyberpunk sources retained
their distinct local records and existing links. This preview made no live
catalog requests to verify those links.

The desktop verification used a database copy and actual Queen's Blade media.
The detail page showed 12 episodes and separately grouped Extras. The
integrated VLC player decoded Episode 1, loaded Episode 2 via Next Episode,
and advanced playback in both files.

The v1.9.4 Windows x64 installer passed the packaged TLS startup and bundle
integrity checks. SHA-256:
CB9D6D3802D3D80D4DA484E971BEC7AEC4B6A548BE25DC810F738BD944252124.
GitHub v1.9.3 remains the baseline release. The candidate was built locally.
