# V1.1.1 verification

## Executed checks

- Complete regression suite: **380 passed, 14 failed**, 267.72 seconds.
- Final authentication/LAN rerun after the legacy-cookie upgrade change:
  **61 passed**, 50.48 seconds.
- Affected desktop/organization plus LAN/stability run: **78 passed**,
  111.20 seconds, after correcting both newly introduced regressions.
- No failing test identity in the full run differs from the 14 failures recorded
  for the complete V1.1 baseline. These failures were also reproduced against
  untouched V1.0 earlier in this chat. They were not skipped or relabeled as passes.
- Final source modules compile; ZIP integrity and source hashes verified.

The full run preceded the last small cookie-header upgrade; the final focused
rerun covers that changed path. This is not a claim that the entire suite passed.

## Synthetic security and state coverage

Fixtures exercise public and Restricted titles in Other/unrelated folders,
legacy incomplete metadata with known cached matches, explicit reclassification,
Ecchi without adult status, unmatched records and scanner-connection cache
invalidation. Exact known IDs are checked through title details, episodes,
artwork, direct media and progress. Normal requests are denied; explicitly granted
Restricted requests succeed and fail again after lock/revocation.

Authentication tests cover anonymous/invalid/expired sessions, bad pairing codes,
fixed expiry, persistent-cookie attributes, legacy tokens, server restarts,
re-pair deduplication, device revocation and subsequent media denial. Normal API
reads remain path/credential-free and Restricted data is not serialized.

Tests also execute valid/invalid/suffix/open-ended/unsatisfiable ranges, HEAD,
missing files, generated MP4/MKV data and FFmpeg decoding, seeking beyond 2 GiB,
concurrent requests, client interruption, occupied-port failure, stop/restart,
local-only binds, main-thread progress writes and readback/reopened-database
persistence. No personal library or device data was used.

## Packaged Windows preview test

A windowed PyInstaller test build containing the patched desktop modules and
bundled FFmpeg was actually executed on Windows. Result: frozen=True,
version=1.1.1-rc.1, three FFmpeg preview processes, three rendered previews,
CREATE_NO_WINDOW on every launch, and zero newly visible ConsoleWindowClass
windows detected while previews ran. It also rendered Settings and closed.

The first packaged test failed before Qt initialized and showed a startup popup.
Investigation traced it to Poppler's incompatible ICU DLL being selected from
PATH. Cleaning the build search path fixed dependency preflight and the frozen
rerun. The release build script contains that same isolation. The final test
harness records startup exceptions to a file instead of displaying a popup.
This was a test build, not a signed production installer or full VLC acceptance.

## Browser diagnostic interaction

Executed in the in-app browser against a temporary synthetic server:
pairing, public-title selection (private title absent), episode/media ID selection,
GET progress, saving 12.5 seconds and reading back 12500 ms, marking watched,
marking unwatched, and retaining the valid session after page reload.

Playback of the generated MPEG-4 codec sample was attempted and the browser
reported no supported source. It is not counted as successful browser playback;
HTTP data/ranges and FFmpeg decode tests passed separately. Existing historical
physical-iPhone MP4/MKV tests were supplied by the user and were not rerun here.
Browser close/reopen persistence is covered by cookie attributes/server restart
checks; a physical Safari restart still needs a fresh manual check.

## Known baseline failures and deferred checks

The following failures remain and keep this source a release candidate:
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

They include Windows file-lock cleanup, platform-specific path expectations,
and offscreen reader/player/geometry assertions. No unrelated player/reader
rewrite was added to hide these failures.

Fresh physical-device streaming/seeking, Safari storage behavior, real media
codecs, active VLC playback/scanner contention, and a production installer on a
clean Windows account remain manual acceptance items. Follow V11_LAN_GUIDE.md
and WINDOWS_ACCEPTANCE.md. Unknown unmatched titles still need an authoritative
AniList match; neither Ecchi nor a folder name alone determines Restricted scope.

## Provenance and contents

Baseline ZIP SHA-256:
`dcef78a3b6d7bee872994c6f5c046b2829e95796e5d816a91c7bf7101fb1df59`.
No V1.0 substitution, personal-data changes or schema migration were performed.
The source ZIP excludes runtimes, databases, device credentials, logs, caches,
test media and generated test builds. SOURCE_MANIFEST.json hashes every packaged
source file. See V111_RELEASE_NOTES.md for upgrading and intentional deferrals.
