# AniVault Desktop 1.8.1 — Simpler Airing Updates

## What changed

The bell now opens **Airing in Your Vault**: one compact row for each currently airing normal-library anime. Watching status and Follow/Unfollow are no longer required. Previous unfollow choices cannot hide an airing vault title.

Each row shows the local file count, the highest confidently identified local episode number, and the latest confirmed aired episode when schedule data is available. A newer aired episode that appears absent is highlighted as potentially missing. Unknown numbering stays neutral. The highest numbered episode does not imply every earlier episode is present.

Library posters have a small **Airing** marker. If a newer aired episode appears missing, it becomes **New ep N**. Franchise cards also summarize airing children. These overlays preserve poster size, title wrapping, selection, and double-click behavior.

The bell count now represents vault titles with a newer aired episode that appears missing, rather than unread notification count. Old read/dismissed history remains available behind **Episode history** and does not suppress the main vault list or markers. Non-local Discover follows are no longer part of automatic monitoring; old preference/history data is retained.

The seasonal Airing / Upcoming page remains a separate discovery view. This patch changes the bell's Airing Updates section.

## Why the attached title was missing

The available record for “I'm Dating a Dark Summoner” is identified as AniList 208025, normal content, and RELEASING, with six local files. It has no manual Watching status. The previous Watching-or-follow filter excluded it. Its copied record now appears automatically in the actual Qt vault-list UI without changing watch status or following.

## Checks and privacy

Checks refresh the airing status of identified normal-vault anime before retrieving official episode schedules. This allows a previously upcoming title to enter the list, and a finished title to leave it. Automatic startup checks, the configurable polling interval, manual checks, offline preservation, API backoff, and conservative episode matching are retained.

No downloads are performed. “Aired” still does not confirm that a downloadable release exists. The normal-vault list and badges exclude Restricted content. An authoritative adult reclassification removes a title from the list, clears stale normal focus/search suggestions, and safely refreshes the normal workspace.

No database tables or columns are added. Existing IDs, watch progress, ratings, favorites, collections, and old airing history remain stored. Only trusted airing-status metadata is refreshed. No server, player, manga, mobile, or web functionality is rewritten.

## Verification

- Full Windows regression suite: **456 passed**, no failures or skips, in 305.29 seconds.
- Final focused airing tests after the last privacy guard: **28 passed**, no failures or skips, in 20.07 seconds. The final added guard test was covered by this focused run; it was added after full-suite collection.
- The actual attached title's indexed record was copied read-only into an isolated test database and confirmed in the list with six local files.
- Live public AniList catalog/schedule query for its media ID succeeded and returned one catalog item and six schedule records. This validates the query, not download availability.
- Actual Qt screenshots using disposable fixtures were visually checked at normal and compact widths, including the poster markers. They are not claims about live broadcasts.
- Installer compilation, clean-bundle audit, and packaged HTTPS/AniList self-check results accompany this build. An installed in-place updater transition to 1.8.1 has not been exercised.

## Try it

1. Install the 1.8.1 setup file and open the bell. Currently airing titles in your normal vault should appear automatically, including the attached title.
2. Select **Check updates** to refresh status and episode schedules. No Watching status or follow action is needed.
3. Browse Anime. Airing titles should have the small marker, and a confidently missing latest aired episode should show **New ep N**.
4. Add that numbered episode and rescan. Reopen the list/library: availability and the marker should update.
5. Open a marked card by double-click, then test a franchise card. Existing navigation and playback controls should work normally.
6. Check offline and reopen the app. Cached statuses/history should remain. Restricted titles should never appear in the ordinary list or markers.

Build from source using `packaging/build_windows.ps1` with Windows x64, Python 3.12 and Inno Setup 6. Run automated tests with `python -m pytest tests -q`; unattended GUI checks use `QT_QPA_PLATFORM=offscreen`.

## Release status

1.8.1 is a local, tested candidate. It has not been published or installed during this task. Published stable 1.8.0 remains available for rollback. Screenshots, complete source, installer, test logs, and checksums are included in the delivery folder.
