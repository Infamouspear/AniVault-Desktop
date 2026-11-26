# AniVault Desktop 1.9.3 — Scanner reconciliation

Status: local Windows candidate; not pushed or published. Version 1.9.2 remains the stable rollback release.

## Root causes

Missing media was marked unavailable but its parent anime record remained in every library query. Empty historical container records therefore remained visible indefinitely. Complete-series detection also treated overlapping title words as sufficient evidence for one aggregate release, while an old ownership fallback kept child files attached to collapsed parents.

Numbered credit sequences such as `NC/ED Episode 12.mkv` reached episode parsing before being recognized as extras. Historical per-file metadata rows could additionally block identification of a legitimate TV parent. These behaviors are corrected without title-specific rules or weaker match thresholds.

The installed Freezing hierarchy was inspected: two independent release folders, each with 12 main episodes, plus NC clips and six OVAs. The old complete-series folder is absent and its database record has no media. Its historical folder layout cannot be verified after deletion. Both current releases matched with high confidence using the existing AniList policy; covers downloaded successfully.

## Reconciliation

- Retire confidently stale releases from active anime/manga browsing, Home, search, collections' active views, statistics and LAN catalogs. Keep their records, media history, ratings, favorites, memberships, statuses and manual corrections recoverable.
- Require a complete, readable filesystem snapshot before reconciliation, verify membership again before committing, and roll back incomplete, canceled, permission-denied or changing scans. An unavailable root does not change media presence or active flags. The UI reports an incomplete scan rather than success.
- Keep root generations, source availability, last successful scan, directory identities, file provenance and retirement history. Path identity and verified filesystem identities reconcile reliable moves; similar names never merge releases.
- Discover individual releases recursively under containers. Keep structural extras beneath a single release. Existing collapsed parents can retire after their file records move to the correct child releases; media IDs and user progress are retained.
- Prevent historical remote aliases from recreating retired local collection cards. Explicitly saved online titles remain saved online titles.
- Queue parent TV identification independently of extras. Keep shared rate limiting, persistent negative results and bounded retries. Timestamp-only touches of the same filesystem file and size do not restart title matching.
- Recover invalid generated artwork separately from title identification. Preserve custom artwork and show unreadable custom art as needing review.
- Show active, unmatched, ambiguous, missing-artwork, suspected-duplicate, missing, unavailable and retired counts in Scanner Review. Details include classification, source availability, generation and last successful scan. Exported normal diagnostics omit titles and paths; Restricted diagnostics remain local and scoped.

## Backup and recovery

Migration adds columns and diagnostic tables; it does not delete existing records. Existing populated databases receive a `pre-reconciliation` backup before the new schema fields. Successful scans receive verified SQLite backups under the application data `backups` directory before bulk reconciliation. Manga reconciliation is backed up as well. No source media files are written or removed.

Reimporting a reliably identified source reuses retained IDs and associated state. Ambiguous moves, cross-volume copies without stable identity, and old parent-level choices that cannot safely be assigned to one of several child releases remain available for review rather than being guessed.

## Verification and limitations

The real installed library was backed up and reconciled. Watch/resume fields, personal ratings, favorites, collection entries, statuses and manual locks were compared before and after local reconciliation. A separate real-library copy completed two unchanged scans without new records or job revisions. Its filesystem pass took approximately 2–5 seconds in the observed runs; this is not a general performance guarantee.

The repaired normal-library health report showed 127 active releases, two retired parent records, eleven unmatched entries, twelve entries needing review, eleven missing covers and no unavailable sources or suspected duplicate AniList IDs. These categories overlap. Uncertain metadata remains unresolved; this update does not promise every placeholder is repaired.

Unchanged-file detection uses paths, filesystem identities and sizes rather than expensive content hashes. A same-size content rewrite retaining the same filesystem identity requires explicit rematching if its metadata identity changes. Linked/junction source trees are conservatively rejected for reconciliation; use an accessible dedicated source root. A source outside the successfully scanned root is never retired by that scan.

The installer and complete source are prepared with release verification logs and application captures. The installer is not run over the user's installed profile during build verification. Install the candidate, then rescan to refresh active views. Publishing requires a separate release step.
