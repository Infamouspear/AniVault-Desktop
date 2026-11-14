# V1.1.2 Windows regression verification

Started from the supplied complete AniVault-V1.1.1-source.zip, SHA-256
`0ee5be9f88ab73b72538032ab824923bc08fd886ce46691fcd889e2767fbf702`.
The supplied test_results.txt reported 380 passed and 14 failed. No baseline
reversion occurred. Source identity: 1.1.2-rc.1; no data/schema migration.

## Complete Windows result

400 passed in 255.73s (0:04:15). **0 failures, 0 skips.**

All 394 original tests plus six new regressions ran together on Windows using
Python 3.12 and PySide6 6.11.2, with QT_QPA_PLATFORM=offscreen. Socket/network tests
ran with local network access. The original suite separately passed 394/394;
the six additions separately passed 6/6 before this final combined run.

Reproduce from the extracted source directory after installing requirements.txt
and pytest:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests -q --tb=short
```

The verification runtime used PYTHONPATH to locate its dependency directory and
source folder. No exclusions were added to the final suite invocation. Headless
GUI automation is not native GPU/VLC rendering or second-device acceptance.
No new installer was built; existing manual acceptance gates remain in
WINDOWS_ACCEPTANCE.md.

## Disposition of every original failure

| Original test | Classification | Evidence and correction |
|---|---|---|
| `test_integrated_player.py::test_fullscreen_mode_uses_video_only_canvas_and_overlay` | Outdated expectation + lifecycle bug | Windows windowed native overlay intentionally polls pointer position. Preserve polling while visible; assert it stops on close, and fix hide/close cleanup. |
| `test_integrated_player.py::test_teardown_is_guarded_and_native_release_is_nonblocking` | Test bug | Fake exposed only X11 set_xwindow. Add set_hwnd/set_nsobject. Keep nonblocking and diagnostic assertions; add absence of teardown exceptions. |
| `test_live_source_rollback.py::test_cleanup_explicit_recoverable_and_main_database_untouched` | Test fixture bug | SQLite context manager commits but does not close. Explicitly close generated-index connection before moving its folder. Production inspection already closes connections. |
| `test_local_manga_reader.py::test_reader_runtime_resume_bookmarks_and_modes` | Application input bug | Canvas arrow key was swallowed or shortcut unavailable. Route canvas/viewport keys through existing actions, claiming ShortcutOverride to avoid double dispatch. |
| `test_local_manga_reader.py::test_main_window_reader_fullscreen_navigation_privacy` | Application input bug | Same shortcut/focus issue affected F/Escape; retain actual fullscreen/sidebar/privacy assertions. |
| `test_manga_polish.py::test_toolbar_reclaims_viewport_and_keyboard_stays_live` | Application input bug | Same event route fixes keyboard navigation with toolbar hidden; existing viewport geometry assertions retained. |
| `test_manga_polish.py::test_settings_live_page_and_reader_fullscreen` | Environment issue + application input bug | Offscreen Qt discovered zero font families: Settings overflow was 288px. Loading installed Segoe UI reduced overflow to zero without resizing or relaxing assertions. F/Escape also uses corrected reader input. |
| `test_metadata.py::MetadataTests::test_full_52_series_metadata_pass` | Test fixture bug | Close caller-owned Database in finally before TemporaryDirectory cleanup. All 52-series metadata assertions retained. |
| `test_metadata.py::MetadataTests::test_initial_d_bundle_rescan_has_one_card_and_preserves_match` | Test fixture bug | Leaked fixture SQLite connection caused WinError 32; close deterministically. Identity and preserved-match assertions retained. |
| `test_metadata.py::MetadataTests::test_rescan_does_not_query_existing_match` | Test fixture bug | Leaked fixture SQLite connection; close in finally. Existing lookup-not-called assertion retained. |
| `test_metadata.py::MetadataTests::test_rescan_matches_existing_unresolved_series` | Test fixture bug | Leaked fixture SQLite connection; close in finally. Existing selected-ID/log assertions retained. |
| `test_v06.py::test_video_single_click_and_double_click_are_disambiguated` | Application input bug | Windows Qt surface ignored releases. Enable fallback surface clicks, wait full system double-click interval on both surfaces, consume trailing double-click release. |
| `test_v06.py::test_watching_this_season_card_has_unclipped_footer` | Application layout bug | Destructive one-line elision removed episode number. Keep full text in two lines within same card height; rebalance note/metadata heights. |
| `test_v076.py::test_multiple_unnumbered_primary_videos_become_stable_episodes` | Test portability bug | Replace slash-only string split with Path.name; native Windows application paths and episode ordering already correct. |

## Additional checks and preservation

Six new behavior regressions cover both video input surfaces with a double-click
longer than the old 180ms timer; hide/show/close with queued clicks and overlays;
ordinary/adult Airing badges with episode 999 and footer bounds; reader LTR/RTL
single dispatch, fullscreen single dispatch, and disabled input after shutdown.

Themed Airing cards were rendered and visually inspected at the unchanged 460px
height: complete episode numbers, adult/library indicators and two-line notes fit.
The Settings probe measured zero horizontal overflow with real Windows fonts.

Only app.py card metadata, integrated_player.py, local_manga_reader.py and version.py
changed in application Python source. LAN transport, Restricted classification,
pairing/session handling, streaming, scanner/database and progress-service modules
are byte-identical to V1.1.1. Their existing tests ran in the complete suite.
Scanner workers already close their own connections in finally, and retired cache
inspection uses contextlib.closing. Shared Database ownership was not changed to
hide fixture leaks. Assertions on episode ordering, metadata preservation,
privacy and teardown logs remain; no tests were skipped or marked expected-failure.

The source ZIP is allowlisted and excludes dependency environments, bytecode,
databases, user media, caches, compiled binaries and transient logs. Its manifest
lists SHA-256 hashes for included source files; ZIP integrity and every entry hash
were checked after packaging.

## Final pytest output

```text
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 54%]
........................................................................ [ 72%]
........................................................................ [ 90%]
........................................                                 [100%]
400 passed in 255.73s (0:04:15)
```
