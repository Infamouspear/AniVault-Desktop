# AniVault Desktop 1.9.2

This update fixes incorrect movie counts and source ownership after reorganizing a combined movie folder into separate releases.

- Library, collection, franchise and continue-watching counts exclude missing files. Missing-file history remains available internally for offline drives and diagnostics.
- A source rename requires its complete original filesystem identity set. Moving one movie out of a collection no longer renames the whole collection to that movie.
- Verified moved files retain their media IDs, watch progress, resume positions and classification overrides when moving between release folders.
- Movie cards use movie counts and display extras separately.
- A single movie with an OVA subfolder can identify its parent movie independently of the extras. Metadata jobs follow moved files and reject outdated ownership.

Validation: 521 regression tests passed across the main run and the permission-enabled rerun of localhost/Windows integration checks; 68 focused scanner, metadata and grouping checks passed. Release packaging checks are recorded with the delivery assets.

Update through Settings → Check for Updates, then install the offered update. Rescan after reorganizing folders to reconcile moved files. Ambiguous identities remain available for manual review. This release does not automatically delete historical library records or reset confirmed matches.
