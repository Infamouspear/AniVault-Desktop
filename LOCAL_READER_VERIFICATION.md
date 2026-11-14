# V0.8.1 Local Reader verification

Environment: Linux, Qt offscreen, PySide6 6.11.2, pypdfium2 5.14.0,
Pillow 12.3.0, rarfile 4.5. Tests exercise actual Qt widgets, queued worker
signals, decoded images and PDFium output, rather than only source inspection.

Final result: **158 tests passed** (145 existing regressions + 13 local reader
tests), in 68.11 seconds. Test command:

`QT_QPA_PLATFORM=offscreen PYTHONPATH=<test-dependencies>:AniVault-V0.8.1-LocalReader python -m pytest AniVault-V0.8.1-LocalReader/tests -q`

## Executed checks

- CBZ natural ordering (`1`, `2`, `10`), ignoring unrelated archive members.
- Source byte hashes/content and modification timestamps unchanged after reads.
- Folder ordering and nonrecursive JPG/PNG/WEBP reading.
- On-demand PDF decode plus PDF use in the live single/spread reader.
- Resume and bookmarks after closing/reopening the database and reader.
- Single/spread, odd final page, single-cover pairing and RTL/LTR image order.
- Actual keyboard RTL/LTR arrows, fullscreen F and Escape in the main window.
- Fit Page/Fit Width, 100%, manual zoom, mouse pan and wheel page navigation.
- 300-page CBZ keeps only a bounded page cache; jumping loads nearby pages.
- Missing/corrupt/empty sources and recovery past an individual corrupt page.
- Opening a one-page book does not complete it; explicit navigation does.
- Additive reader migration preserves pre-existing anime/Favorite/AniList data.
- Scoped identity, navigation cleanup and Restricted lock preserve reading
  state while closing the reader and restoring normal UI.
- Missing CBR tool produces the documented clear dependency error.
- Reader UI was rendered and visually inspected at 980 × 740.
- Existing rollback regression suite covers scanner, metadata, player logic,
  AniList, watch state, Collections/Franchises and Restricted isolation.

## Source safety

Readers open files/archives read-only. ZIP/RAR members are read as streams;
folders are listed nonrecursively; PDFium renders without saving a document.
No rename/move/rewrite/recompression or extraction beside source files.
Reading state/preferences/bookmarks reside in the main app database. Only
AniVault-owned cache directories are used for any temporary helper files.

## Limits / platform verification

- No RAR backend was present here. Actual compressed CBR rendering needs a
  Windows/local test with UnRAR installed; graceful unavailability was tested.
- Windows display/DPI and GPU/native VLC playback were not exercised here.
  No player/scanner/AniList request implementation was changed.
- Decoded images are capped to 3072px longest edge. PDF is rasterized on demand
  at up to 2× page units within that cap. Password prompts are not implemented;
  encrypted/password-protected inputs fail cleanly.
- Reader controls remain visible in fullscreen for predictable interaction.
- Path-based identity does not follow file moves. No manga library/scanner,
  live sources, downloading or media conversion was introduced.
