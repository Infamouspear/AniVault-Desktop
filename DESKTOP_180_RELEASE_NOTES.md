# AniVault Desktop 1.8.0 — Initial D navigation and Airing Updates

This update continues from stable Desktop 1.7.1. It does not change AniVault Remote, the web client, or the LAN server API.

## Initial D diagnosis

The failure was reproduced using a read-only copy of the available indexed Initial D records and cached explicit relationships. A related item outside the displayed franchise could resolve to another local release. The franchise renderer then treated that local `Card` as a remote `SeasonCard` and accessed its remote-only `note` field. An `AttributeError` interrupted page construction before navigation completed.

The renderer now accepts both local and remote related cards, labels local matches as In Vault, and skips unresolved identities safely. Invalid metadata IDs do not prevent valid franchise groups from being constructed. There are no title-specific exceptions and no changes to scanning, metadata associations, database IDs, watch progress, ratings, favorites, or collections.

The corrected Qt UI opened both actual indexed groups and all 13 Initial D releases by double-click, with 90 indexed media records in the isolated reproduction. This verifies navigation and detail routing against the available records. It does not assert that every underlying file was played.

## Airing Updates

- Top-bar notification bell with unread count and a full notification center. Compact cards include artwork, title, episode, local airing time, availability, Open title, Mark as read, and Dismiss.
- View all, Unread only, Mark all as read, and a link to the existing seasonal Airing page.
- Normal Home has a compact unread-count shortcut. No second full feed.
- Default monitoring covers currently airing normal local anime with an explicit Watching status and valid AniList identification.
- Follow/Unfollow Airing Updates is independent of watch status. Use normal title details or the normal title context menu. Airing cards also have a follow context menu and status indicators.
- Explicit unfollow overrides automatic Watching monitoring until followed again. Discover results are never followed automatically.
- Startup checks run after initialization, with hourly checks thereafter. Settings can disable automatic checks or choose an interval from 15 minutes to 24 hours. Manual checks remain available.
- Checks use the existing background queue and official [AniList airing schedules](https://docs.anilist.co/reference/object/airingschedule). They do not block UI rendering or query on each render. Concurrent checks are suppressed; retries back off after failures/rate limits.
- Initial checks cover the preceding 30 days. After a longer offline gap, checks extend back to the last successful check, with overlap. The next 14 days of schedule data reconcile postponements; future episodes do not create early notifications.
- An alert is identified by AniList media ID and episode, independent of a changed airing timestamp. Rescheduling preserves read/dismissed state. A previously aired alert moved into the future is hidden until its corrected time.
- Previously stored history survives network failures. A partial/invalid API response does not replace saved history.

## Local episode matching

Matching uses season-specific AniList IDs and present indexed media, rather than file counts or watched progress. Numbered gaps are retained. Missing files are excluded. Filename episode evidence is checked against the index, and ambiguous scan fallbacks, combined packs, mixed seasons, unidentified videos, and uncertain numbering receive a neutral message. Extras do not count as ordinary episodes. Local matches and availability refresh after index changes.

An episode having aired does not confirm a downloadable release. Messages say “aired,” “may be missing,” or “check for a new release.” No downloading, torrent integration, or transcoding is included.

## Data and privacy

The migration only creates two tables if absent:

- `airing_follows`: media ID, explicit enabled/disabled preference, normal metadata snapshot, update time.
- `airing_updates`: unique media ID/episode, airing time, creation time, metadata snapshot, availability, read state, and dismissed state.

No existing records are rewritten by this migration. Dismissed rows remain as deduplication records. Repeated startup/migration is safe. Existing startup backup and installer/updater behavior is retained.

Restricted content is rejected when following, selecting monitoring candidates, accepting API results, reading history, and opening alerts. Private local IDs, saved titles, and private status metadata are excluded from ordinary matching. Unknown adult classification is not eligible for following. The bell and notification center are unavailable inside the Restricted workspace. Notification data is not added to LAN/mobile responses, logs, or Windows toasts. If a trusted schedule response reclassifies a followed title as adult, old notification/follow metadata is reduced to an opaque ID tombstone and excluded from normal history.

Native Windows notifications are deferred. The in-app notification center is the supported notification mechanism for this release.

## Verification

Final Windows regression: **452 passed, 0 failed, 0 skipped**, in 407.08 seconds (6 minutes 47 seconds), on the final 1.8.0 source. The earlier full run passed 443 tests before additional edge-case coverage was added. The date-formatting failure discovered in an intermediate run was corrected and covered by the final passing run.

The clean Windows bundle audit passed. Packaged HTTPS initialization and the packaged read-only AniList network check both exited 0. Inno Setup compiled successfully. The application and installer both report 1.8.0. All 82 staged application inputs match the delivered source, with the public JSON configuration compared semantically because staging normalizes whitespace. The focused tests cover schedule boundaries, pagination, postponed broadcasts, deduplication, restart, read/dismissed state, explicit unfollow, offline failure, real background-worker responsiveness, gaps, packs, unidentified media, season identity, migration preservation, Restricted isolation, and local/remote franchise navigation.

The official schedule query was accepted by the live public AniList API using a finished public reference title and returned zero schedule rows. Notification behavior uses deterministic fixtures rather than pretending a live broadcast occurred during this run. Screenshots show the actual Qt UI with disposable fixtures, not real airing claims or personal library data.

## Manual testing

1. Install the supplied 1.8.0 Windows setup file, then confirm the version in Settings. Your existing app data is preserved.
2. In Anime, double-click Initial D and Initial D Legend groups. Open stages and films, navigate back, and confirm episode lists, metadata, and playback controls. Compare a second ordinary franchise.
3. Open an identified normal anime and select Follow Airing Updates. Alternatively, set a currently airing local anime to Watching. Check Settings → Airing Updates and use Check for Airing Updates.
4. Open the bell. Confirm actual aired episodes, local time, artwork, and availability. A title with no recent official episode schedules correctly produces no alert.
5. Mark one alert read, filter unread, dismiss another, and restart. Repeat checks and verify alerts are not duplicated or dismissed alerts recreated.
6. Add a known numbered episode to the normal library and rescan. Reopen the bell and confirm availability changes. An ambiguous pack should use the neutral message.
7. Unfollow a title. New schedules must not create alerts for it even if its status remains Watching. Existing history remains available.
8. Check while offline, navigate through the app during a check, and then reconnect. Previously saved history must remain intact.
9. Enter and lock Restricted Archive. Its titles and artwork must never appear in ordinary notifications or Home previews. The ordinary notification center remains separate from seasonal Airing.

For development, install `requirements.txt` and pytest, then run `python -m pytest tests -q`. For unattended GUI checks set `QT_QPA_PLATFORM=offscreen`. Build the Windows installer using `packaging/build_windows.ps1` on Windows x64 with Python 3.12 and Inno Setup 6.

## Release status and rollback

1.8.0 is a local, tested release candidate until explicitly published through the established GitHub Releases workflow. The personal repository latest release was verified as [stable 1.7.1](https://github.com/Infamouspear/AniVault-Desktop/releases/tag/v1.7.1); no remote branch, tag, or release was changed during this task. The previous stable 1.7.1 release and installer are retained as rollback options. This delivery does not overwrite the installed app or publish a GitHub release automatically. As with earlier builds, packaged HTTPS initialization and bundle checks are separate from testing an installed in-place update on this PC.
