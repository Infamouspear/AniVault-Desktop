# V0.8.2 Local Manga verification

## Executed checks

The automated suite runs with PySide6 on Linux using Qt's offscreen platform.
It exercises actual widgets/event loops as well as storage and scanner logic.
Final result: **184 passed in 78.67 seconds**.

- Actual Manga sidebar navigation, root-manager dialog and background scan.
- CBZ/PDF/image-folder indexing, CBR identification without opening it,
  natural volume/chapter order including decimal chapters, conservative series
  grouping and repeat-scan deduplication.
- Root overlap protection, unavailable roots, missing/reappearing books.
- Existing reader progress/bookmarks adopted without a second progress store.
- Reader resume, completion, explicit reading-direction labels, thumbnails,
  shared Collection/status pages and Restricted locking/privacy.
- Wide-window responsive grid and lightweight volume/chapter list.
- Actual AniList match dialog using a controlled asynchronous MANGA response;
  manual type validation, explicit adult scoping, ecchi remaining normal.
- Source-file hashes unchanged after scanning/reconciliation.
- Prior reader and application regression tests remain included.

An additional migration check created a database using the unmodified V0.8.1
Database/ReaderStore, populated a collection, setting, private reading progress
and bookmark, then opened it with V0.8.2. Contents of all 17 prior tables were
unchanged; the three new manga tables were present. This used a disposable
fixture, not the user's production database.

## State and source safety

New tables: manga_roots, manga_series, manga_items. Items reference existing
manga_reader_state identities; bookmarks and completion are not copied into
another progress system. Manual statuses and memberships reuse the shared
organization model. AniList manga reading-progress sync is not implemented.

Source archives, PDFs and image folders are read-only. Scans read directory
metadata; reader/cover decoding opens sources without rewriting them. Artwork,
preferences, thumbnails and temporary data belong in AniVault's owned data
directory. No source rename, conversion, extraction beside media or recompression.

## Performance checks

A synthetic 1,000-item library, with no archive decoding, measured about 100 ms
for scan, 25 ms for reconciliation and 46 ms for detail-page construction.
These are environment-specific measurements, not real-book decode guarantees.
The detail list uses lightweight Qt list items instead of a widget/button set
per book. Covers are generated only for visible cards in a bounded queue;
distant card pixmaps are released. The existing scaled artwork cache is reused.

## Limits and remaining machine checks

- Live AniList access returned HTTP 403 in this environment. Search/manual-ID
  wiring and errors were tested, but real-server matching remains unverified.
- CBR requires rarfile and a compatible RAR decompressor, preferably UnRAR on
  PATH. No decompressor was available here; graceful dependency failure was
  tested, successful real CBR decoding was not.
- PDF uses pypdfium2, included in requirements. CBZ/PDF/image-folder decoding
  and reader modes are covered by the reader tests.
- Windows-native chrome, GPU rendering, VLC playback and real desktop input
  still need a Windows smoke test. Stable VLC/anime scanner code was not changed.
- Source moves/renames retain old missing records but are not guessed as
  relocations. Grouping is deliberately conservative for ambiguous layouts.
- Existing reader decoded images remain capped at a 3,072 px longest edge
  and five pages/96 MiB; full-resolution pixel inspection is not provided.
- Manga Favorites are local to the Manga view; anime Favorites remain separate.
- The live-source rollback remains in effect: no nHentai/hanime discovery,
  browser initialization, metadata index or download system is reintroduced.
