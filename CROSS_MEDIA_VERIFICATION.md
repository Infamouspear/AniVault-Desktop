# AniVault V0.8.4 verification

## Changes

Shared, read-only organization resolution now covers local anime, local manga,
Saved AniList entries and Restricted external bookmarks. It batches catalog
reads and caches the result by SQLite mutation count and privacy scope.
Collections/status lists reuse the existing card and detail components.

Global header search is local: it searches title aliases, synonyms, genres and
known identity aliases. Discovery search remains the separate AniList search.
Results label media type and In Vault/Saved/External/Missing state. This release
does not add the V0.9 sidebar redesign or reintroduce live external sources.

## Identity and state

- Deduplication is presentation-only. AniList aliases are resolved within media
  type and scope; source bookmarks use source + external ID. No local records,
  source paths, watch progress, reader progress or Saved metadata are merged.
- Local/Saved aliases appear once in search/Collections/status views. Legacy
  duplicate membership rows are preserved but not counted twice. Explicit
  relationship removal handles all certain aliases; anime/manga data remains.
- Manga status uses Reading while storing the existing Watching enum. A local
  explicit status takes priority over an older remote alias; explicit user
  changes update existing aliases. Matching/import never rewrites statuses.
- Favorites uses the existing anime and manga flags, not another table. It
  presents both local media types in one view. Nonlocal/external Favorites are
  not added because no generic Favorite storage existed for those records.
- Saved remains bookmarks, not downloaded media. Manga matches now link to the
  local manga detail page; unknown remote titles never create local records.
- Collection previews and counts come from valid scoped entities. Restricted
  Search/Favorites/Saved/Collections obey the lock; old private alias metadata
  cannot be used as a normal Collection preview.
- Missing manga retains progress, status, Favorites and membership. Anime
  availability uses the existing scanner present flags. No new scanning occurs
  when opening an organization page.

## Verification performed

Tests used Linux offscreen Qt/PySide6 6.11.2, the pinned supported runtime.

| Check | Result |
|---|---|
| Full regression suite during implementation | 214 passed; exit 0 |
| Follow-up organization/status/rollback/manga-polish suite | 50 passed; exit 0 |
| Final cross-media tests after latest changes | 17 passed; exit 0 |
| V0.8.3 populated fixture reopened by V0.8.4 | All 20 tables identical |
| Source fixture hashes before/after reopen | Identical |
| Catalog with 250 additional Saved entries | At most 10 SELECTs, not one query per card |
| Mixed Collection screenshot | Inspected with existing app stylesheet |

The test runs overlap; counts should not be added together. Final new tests
cover mixed-media Collection rendering/navigation, Saved-to-local linking,
duplicate alias membership, explicit status changes, live counts without page
replacement, Favorites, missing/reappearing manga, restart/rescan persistence,
Restricted search/locking and cached Saved relinking after a local match.
Legacy Saved manga with a known manga format but absent type is normalized for
display without rewriting the stored record.
An explicit Collection removal also removes its matching legacy membership row,
so the old compatibility migration cannot resurrect it on restart. Other legacy
memberships remain intact; there is no automatic membership cleanup.

Existing scanner, parser, metadata, player, reader, chapter skipping and AniList
watch-sync implementation files remain unchanged. Their regression tests are
included in the full suite. Anime/manga manual matching flows remain in place;
cached explicit cross-media relations can be displayed without changing anime
franchise membership or requesting additional relation data.

## Database and source safety

No V0.8.4 schema migration, table consolidation or destructive startup operation
is introduced. Existing organizational schemas and flags remain authoritative.
The migration check used a populated V0.8.3 fixture with anime watch/resume state,
manga reader state/bookmarks, matching, Favorites, Collections, franchises,
Saved and external Restricted bookmarks. It did not use the user's live DB.

Organization actions only change AniVault-owned database state. They perform no
media rename, move, conversion, recompression or file rewrite. Keep the existing
app-data directory when installing this build; do not replace the database.

## Practical limits

Windows/native-HWND VLC rendering, GPU playback and the user's actual library
were not accessible here. Their implementation is unchanged; a Windows smoke
test is still appropriate. Real RAR decoding requires an optional local UnRAR
dependency; graceful missing-tool behavior remains tested.

When multiple independent local records share one AniList identity, organization
views choose a representative while keeping every local record and its separate
progress. All Anime and the Manga library retain their existing local entries.
No uncertain record merge or fuzzy franchise matching is attempted.

Local global search uses a batched in-memory catalog, not full-text indexing or
remote search. Very large libraries may warrant a future FTS index. Scoped
catalog caches are invalidated by writes through AniVault's database connection;
external simultaneous database editing is not a supported refresh mechanism.
