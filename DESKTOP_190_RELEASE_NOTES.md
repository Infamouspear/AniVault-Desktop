# AniVault Desktop 1.9.0 — Scanner reliability and franchise grouping

Release status: Windows candidate prepared locally. Not pushed or published. The public stable release remains 1.8.2 for rollback.

## Changes

- Franchise relationships finish loading across the entire matched normal library even after navigating away from All Anime. Old relationship caches refresh once under the new cache schema. Incomplete responses retain existing groups rather than caching an empty success.
- Grouping uses explicit AniList anime relationships, including verified shared intermediate releases that are absent locally. There are no title-specific exceptions, name-based membership rules, or recursive network crawls. Local seasons, watch progress, ratings and files remain independent.
- Distinct source folders have source identities rather than a shared normalized-title identity. Existing files retain their local IDs and ownership, including legacy records that already aggregated several folders. Proven filesystem renames preserve progress; new physical copies stay separate.
- Season, part/cour, format and franchise conflicts prevent automatic matching. Distinctive abbreviated franchise names can match expanded official titles when the release evidence agrees. Ambiguous candidates stay in Scanner Review. Ranking values are not presented as calibrated probabilities.
- Explicit SxxExx filenames take precedence over aggregate parent names containing Movies/OVAs. Multi-episode ranges retain their ending episode. Nested season releases and shared OVA/movie folders are identified separately where safe.
- Scanner Review is available in All Anime and through Match / Change AniList Entry or View Scan Details. It shows local provenance, candidate identities and artwork, decision reasons, source availability and manual-lock state. Search, retry, confirm, leave unmatched, clear correction and artwork recovery are supported. Network searches and artwork run in the existing background queue.
- Mixed OVA/movie folders retain their stable local parent and expose individual file identities for confirmation. An ambiguous shared folder is never assigned one convenient but unrelated identity.
- Manual choices survive restart and rescan. Correction history and backups retain the previous identity. Collection membership, local status, favorites, ratings, media associations, watched flags and resume positions are preserved.
- Unavailable files and offline roots retain their user data. Missing sources appear in review; automatic next/previous playback excludes unavailable files.
- Artwork is validated and written atomically, cached between attempts, and retried independently of identification. Custom artwork survives identity changes. Private artwork uses a separate cache. Restricted review requires an unlocked archive and closes on lock; normal exports exclude private sources.
- Sanitized diagnostic exports omit titles, source paths, filenames, URLs, raw server responses and credentials. Detailed local provenance remains inside the scoped review UI. LAN response formats and remote/web features were not expanded.

## Verified findings

The installed database was inspected read-only. All scan/repair and UI verification used isolated SQLite copies; the installed database and media were not modified.

- Arifureta's season numbers were already parsed correctly. The earlier scorer could not confidently connect the short folder title to the longer official title. The new decisions distinguish the TV seasons from specials, prologues, picture dramas and music entries. In the copy, seasons 1/2/3 resolved to AniList 100668 / 112323 / 154473. The shared specials folder remains flagged for file-level review.
- Cyberpunk season 1 was linked to 120377; the second source was actually unmatched. The earlier candidate-season parser did not recognize a trailing sequel number. The live API supplied a distinct second identity, 195539, and the copy matched it without borrowing season 1 metadata. Verification covers folder/filename evidence and official metadata, not audiovisual content fingerprinting.
- The My Hero OVA source had the generic parsed identity OVA and retained an existing 7059 Black Rock Shooter link. Generic structural-folder handling lost useful franchise context; existing non-null links were then preserved without reevaluation. Retained logs cannot establish precisely when or how the original wrong selection occurred, so its original selection mechanism is not claimed as proven. The new scan flags the shared source and exposes all eight files. Clearing the wrong link in the UI copy preserved all eight media records.
- Live official relations grouped the six local Demon Slayer releases, seven matched My Hero Academia seasons, and both Shangri-La Frontier seasons using the same shared implementation. Unmatched movie/OVA containers remain reviewable instead of being grouped by a guessed title.
- A scan of the real source tree against an isolated database copy covered 118 roots. All 1,666 previous media IDs, their ownership, watched flags and resume values were retained; 1,799 media records were indexed afterward, including formerly missed files. Filesystem indexing and offline metadata fixture evaluation took about 16 seconds in that run. It was not a network-throughput benchmark. A separate filesystem-only comparison over 119 roots measured approximately 0.80 seconds for 1.8.2 and 1.59 seconds for the update, with network requests stubbed in both cases; the added provenance and preservation work cost about 0.8 seconds in this local run.
- Actual application navigation, grouped library cards, local scan details, eight authorized live manual-search results and candidate artwork were exercised. Screenshots accompany the local delivery.

## Data safety and recovery

The additive scanner migration creates scan_sources, scan_file_matches and scan_match_changes plus media file-identity and episode-range fields. Existing populated databases receive a SQLite backup before this migration. The existing application release-backup mechanism remains in place. Scans and explicit match changes also make recoverable backups in the database directory's backups folder. No media files are renamed, moved, edited or deleted.

Automatic rescans do not replace old non-null identities merely because heuristics changed: contradictory links are flagged. A manual correction is protected until Clear manual correction is chosen. Legacy local records spanning several physical folders are retained rather than automatically split and risking user-data loss.

To recover, close AniVault and restore a verified pre-change SQLite backup to the application's existing database location. Keep the prior installer. A downgrade may not understand new review/provenance tables, so restore its matching pre-upgrade database when rolling back.

## Validation

Acceptance results and checksums are recorded in the delivered SCANNER-UPDATE-NOTES.md and SHA256SUMS.txt. Automated coverage includes the existing desktop suite plus scanner fixtures for season identity, ambiguity, mixed OVAs, nested releases, multiple copies, renames, missing/offline files, cancellation, manual correction persistence, collection/status preservation, artwork recovery, Restricted isolation, incomplete relation responses and relationship batches continuing after navigation.

The source archive and installer are built from the same allowlisted application inputs. Bundle audits exclude personal databases, tokens, logs and local work files. Frozen TLS and AniList connectivity probes are checked separately. Prior stable release: https://github.com/Infamouspear/AniVault-Desktop/releases/tag/v1.8.2

## Limitations

- Ambiguous specials, films and OVAs may require manual selection. File-level metadata inside a shared folder does not automatically split that folder into new library cards or redistribute existing progress.
- Legacy entries already spanning multiple roots are preserved for review; automatic deduplication is intentionally conservative. Moves across filesystems without matching file identity remain separate missing/new sources, with old user data retained.
- Episode ranges are recorded as provenance; watch progress remains attached to the physical media record.
- Relationship refresh requires AniList connectivity. Existing groups survive failures; unverified or missing identities cannot form a verified franchise group.
- Backups are retained locally; this update does not automatically purge older backups.
- The installed user's records still need a normal rescan/review after installation. Copy-based verification is not a claim that the installed library has already been repaired.
