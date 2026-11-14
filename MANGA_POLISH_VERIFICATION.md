# V0.8.3 verification and limits

## Runtime coverage

Final supported-runtime result: **203 passed in 233.32 seconds; exit code 0**.
Runtime: PySide6/Qt 6.11.2, Linux, QT_QPA_PLATFORM=offscreen.
Run application dependencies from requirements.txt; tests additionally need pytest.

Qt offscreen tests exercise real reader widgets, mouse/keyboard events,
Settings controls, background scans and database persistence.

- Single-page and spread click navigation in both LTR and RTL; center dead zone.
- Wheel zoom without page changes, left-button drag pan without click-to-turn,
  source hashes unchanged after reading interactions.
- Hidden toolbar reclaims viewport height; page fit grows; keyboard navigation,
  fit and bookmark shortcuts remain available.
- Reading preferences survive reopening the database and configure a new reader.
  Changing global preferences does not create or alter book-progress rows.
- Actual Settings page saves Reading options, fits a narrow window without
  horizontal scrolling, and supports reader fullscreen entry/exit.
- Completion logs once across repeated redraws; final page and completion resume.
- Continue Reading card reopens the active volume at its stored page; untouched
  titles are excluded; Recently Read includes previously opened/read titles.
- Favorites update the existing card and page rather than recreating the grid.
- Manual/local cover wins over AniList, and AniList wins over a generated image.
- Release annotations, years, resolutions, decimals and bracketed chapter labels.
- Exact normalized loose-volume grouping, unchanged IDs after a parser update,
  rescan dedupe, preserved Collection membership and manual status.
- If normalization would merge distinct existing records, those records are
  retained separately so their statuses and memberships cannot be orphaned.
- Existing CBZ/PDF/image-folder reader, source errors, bounded cache, bookmarks,
  missing files, Restricted locking and manga matching tests remain included.
- The broader anime/player/Discover/organization regression suite is retained.

Visual inspection used neutral generated test pages. Windowed and fullscreen
Fit Page preserve aspect ratio and use almost all available height. Reading
settings and manga detail/item labels were inspected in actual Qt screenshots.
Portrait content necessarily has side space on a widescreen display.

## Compatibility / source safety

A populated V0.8.2 database fixture opened in V0.8.3 with all 20 existing
table contents unchanged. No new schema or progress store is introduced.
This was a disposable fixture, not the user's production database.

Reader/scanner source IO remains read-only. Thumbnails and temporary data stay
in AniVault-owned cache; book files are never renamed, rewritten, recompressed,
converted or extracted beside the source. Reader progress/bookmarks, manual
status, Favorites and Collections remain distinct.

The anime parser/scanner, video player, AniList discovery/query pipeline and
watch-progress sync implementation files are unchanged. App changes are confined
to reader fullscreen wiring and Settings layout/Reading controls.

## Dependency and platform limits

- Requirements pin PySide6/Qt 6.11.2. An exploratory run with Qt 6.12 completed
  test assertions but crashed during process shutdown; it is not the supported
  runtime for this build. This observation does not identify the crash's cause.
- Live AniList MANGA search returned HTTP 403 in this environment. Controlled
  asynchronous query responses verify the actual match dialog; real-server
  matching and remote artwork still need a machine with working AniList access.
- CBR needs rarfile plus a compatible decompressor (UnRAR recommended). The
  decompressor is unavailable here; graceful dependency errors are verified,
  successful CBR decoding is not. PDF uses pypdfium2 from requirements.
- Linux/offscreen tests do not establish Windows native-chrome, GPU or real VLC
  decoding behavior. A Windows smoke test is still needed.
- Decoded page cache remains bounded to five pages/96 MiB, longest edge 3,072 px.
  100% zoom refers to the decoded image rather than unlimited source resolution.
- Continue Reading requires a partially read item beyond page 1, or completed
  items plus remaining available items. Opening a book alone does not complete it.
- Existing separately persisted groups are not forcibly merged by cleaner
  naming. Source moves/renames are not guessed as relocations.
- Automatic manga AniList progress sync, live external sources and the V0.9
  sidebar overhaul remain deferred. ROADMAP.md records the navigation work.
