# V1.1 verification — rebuilt LAN source

## Provenance

New implementation from `AniVault-V1.0-source.zip`, SHA-256:
`0bfc80c87dc92c07207b372878aa63d640a440e85bf1ef779bb294e84f2b796d`.
The old V1.1 Work artifact could not be retrieved; this deliverable does not
claim its task-2 files survived. Synced project sources were left untouched.

## Automated results (Windows x64; Qt offscreen)

Final complete suite: **14 failed, 362 passed in 378.52s (0:06:18)**.
All **43 LAN tests passed** in the final suite. The earlier focused LAN run
passed 41 tests; two additional corruption/revocation checks are included in the
final suite. No tests were skipped or removed to obtain these results.

The 14 remaining original-suite failures were reproduced on **untouched V1.0**
in this same Windows environment. There are no newly failing test identities
relative to that comparison. This is not a fully passing suite or a declaration
of production acceptance. Existing failures were left outside the requested
server scope. They concern Windows open-file cleanup, POSIX path assumptions,
offscreen player/reader interaction and layout assertions.

LAN coverage includes:
- Real HTTP authentication, pairing cookies, rate limits, revocation and restart.
- Scoped metadata, favorites/status/collections, title details and read-only DB snapshots.
- Restricted grant, lock/relock/restart and media/artwork isolation.
- Host, Origin, proxy-header and arbitrary-path/URL-token rejection.
- Full and HEAD responses, exact lengths/types, bounded byte ranges and 416 errors.
- Generated MPEG-4 video in MP4/MKV containers; downloaded bytes decoded by FFmpeg.
- Forward/backward ranges and seeking in a sparse file larger than 2 GiB.
- Source hash/mtime preservation and rejection of missing files.
- Desktop-thread progress updates using an actual Window plus existing state methods.
- Explicit progress decreases, automatic non-decrease rules and AniList sync flags.
- Server start/stop, private-bind validation, paired-token persistence, interrupted revoked streams.
- Corrupt paired-device state preserved with server safely disabled.

The Server Settings panel was rendered and visually inspected with a Windows
font loaded for offscreen rendering. Application modules compile successfully.

## Remaining acceptance

No separate physical phone/PC was controlled. Windows-to-phone discovery,
firewall behavior, real-library playback codecs, concurrent scanner/playback
responsiveness and live AniList-account synchronization remain manual checks.
Use `V11_LAN_GUIDE.md`. Local HTTP/FFmpeg validation does not prove every browser
can play MKV or every codec; there is no transcoding.

This bundle contains source and Windows build scripts, **not an installer**.
It excludes test runtimes, databases, device stores, logs, caches and media.
The existing build process still requires a publisher public AniList client ID.

## Reproduced V1.0 failing tests

- `test_integrated_player.py::test_fullscreen_mode_uses_video_only_canvas_and_overlay`
- `test_integrated_player.py::test_teardown_is_guarded_and_native_release_is_nonblocking`
- `test_live_source_rollback.py::test_cleanup_explicit_recoverable_and_main_database_untouched`
- `test_local_manga_reader.py::test_main_window_reader_fullscreen_navigation_privacy`
- `test_local_manga_reader.py::test_reader_runtime_resume_bookmarks_and_modes`
- `test_manga_polish.py::test_settings_live_page_and_reader_fullscreen`
- `test_manga_polish.py::test_toolbar_reclaims_viewport_and_keyboard_stays_live`
- `test_metadata.py::MetadataTests::test_full_52_series_metadata_pass`
- `test_metadata.py::MetadataTests::test_initial_d_bundle_rescan_has_one_card_and_preserves_match`
- `test_metadata.py::MetadataTests::test_rescan_does_not_query_existing_match`
- `test_metadata.py::MetadataTests::test_rescan_matches_existing_unresolved_series`
- `test_v06.py::test_video_single_click_and_double_click_are_disambiguated`
- `test_v06.py::test_watching_this_season_card_has_unclipped_footer`
- `test_v076.py::test_multiple_unnumbered_primary_videos_become_stable_episodes`
