# AniVault Desktop 1.8.2 — Consolidated fixes and request review queue

## Category filtering

The All Categories dropdown compared semantic labels such as Airing and Movies directly against the scanner's folder-category column. In the available indexed data, all 83 rows used the folder category Other, despite metadata correctly identifying TV series, films, and OVAs. This caused false empty results.

Categories now use metadata and local watch state. TV Anime, Web Anime, Movies and Specials use format; Airing and Finished use AniList release status; Watching uses the explicit local status or existing partial-progress fallback; Unwatched uses local watched progress. Finished airing is separate from the Completed watch-status chip. Other covers remaining/unidentified formats. Folder category is retained as a fallback for an unidentified movie. No library records are rewritten to force a category.

Search, category, genre, watch state, format and year combine. Genuine empty results include Clear filters. The separate manga library remains separate. A read-only check of actual normal-library metadata found 63 TV entries, 4 web anime, 10 movies, 4 specials/OVAs and 1 remaining/unidentified entry.

## Relationships

The old button refreshed explicit AniList relationships asynchronously. Its effect was easy to miss: it provided little start/error feedback, worked in batches, and visible regrouping depended on the current view and scroll position.

The control is now **Refresh relationships**. It selects the existing Franchises view, checks known normal-library AniList IDs, and displays progress, group counts, empty-identification guidance, rate-limit feedback and failure feedback. Active filters still apply. Existing groups survive failed checks. It does not invent a new grouping system, join titles by similar names, or fetch Restricted relationships through normal browsing.

## Sidebar

PRIMARY now contains Home, Anime, Manga, Favorites, Collections and Statistics, in that order. ORGANIZE and standalone Planning are removed. Discover and System destinations are retained. Planning and all other status lists remain in Collections, with existing routes and saved statuses preserved. Planning routes highlight Collections.

Optional configurable nested status shortcuts are deferred. The present fixed-height sidebar would become crowded with all five enabled; a navigation scrolling/layout redesign is outside this focused patch. Expanded and collapsed navigation remain supported.

## Anime Requests

- Active Queue is the default. Its virtual list renders visible rows instead of creating buttons and artwork widgets for every request. Search, status filtering, sorting, artwork, format, year, request date and status remain available.
- Approve sets Approved; Decline sets Declined; Downloaded sets Available. Each action archives the record immediately and removes it from Active Queue, without a separate removal step or confirmation dialog.
- History retains original identity, metadata, details, notes and request date, plus final status and processing date. It supports search, status filters, Restore and explicit confirmed permanent deletion.
- Undo restores the prior status/archive state and original ordering. A revision guard prevents an older Undo from overwriting a subsequent decision or automatic update.
- Review removes/inserts rows without rebuilding the entire page and preserves scroll position. A/D/L act on the selected request; Enter opens details. Right-click provides details/notes, Discover, local-title access where matched, restore and permanent deletion.
- Approved history entries can later be marked Downloaded. Decision history in the details dialog preserves the earlier approval even after Available.
- Downloaded is the operator's explicit confirmation that the release has been obtained; it does not start a download or assert that every episode is present. Manual requests without AniList IDs can use it. Automatic detection remains more conservative.
- If a scan holds the SQLite write lock, quick review reports that the database is busy and keeps the request intact, rather than waiting for the normal multi-second timeout. Undo can be retried after the scan.

Requests never automatically add titles to Planning. Feedback retains its separate tab, records, editor, statuses and removal workflow.

## Automatic scan detection

After a completed library scan, a batched exact AniList-ID match can mark Requested, Under Review or Approved anime requests Available and archive them. A normal local release must have present indexed primary playable media. Available means that the exact release is present, not that its season is complete.

Different seasons, related releases, similar names, manga, Restricted entries and ambiguous duplicate local matches cannot fulfil a request. Manual requests without an ID are left for manual review. Declined requests are not automatically reversed. Repeated scans do not add duplicate transitions. Revision checks preserve a newer review decision that races with a scan. Approval history is retained when an Approved request becomes Available.

## Migration and data preservation

An atomic, repeatable migration adds archived, processed_at and revision fields to desktop_requests, creates desktop_request_events, adds supporting indexes and records a completion marker. It does not rebuild or reset the request table. Existing Approved, Available and Declined anime requests move to History; other existing records remain active. Feedback states are unchanged.

Legacy processing dates use the record's previous updated timestamp, the best information available before this feature. Exact older decision times cannot be reconstructed. New processing events have their own timestamps. Request timestamps remain UTC, as in the previous editor.

A read-only copy of the available database verified that all **178 existing request/feedback records** retained every original field exactly through migration and repeat startup. A separate 183-request migration fixture covers legacy processed states. An interrupted-migration test verifies rollback and successful retry. No changes were made to the installed user database during development.

## Verification

**Full Windows regression: 474 passed, 0 failed, 0 skipped, in 342.56 seconds (5 minutes 42 seconds). Final focused checks: 31 passed in 28.56 seconds after the scan-lock guard and final UI wording.** The new lock-contention test was added after full-suite collection and is included in that focused result. The old standalone-Planning highlight expectation was updated to the explicitly requested Collections destination. Focused tests cover categories, combined filters/reset, relationship progress and privacy, sidebar/status routes, 183-record migration, interruption recovery, review/archive/Undo/Restore, approval history, exact scan matching, decision races, confirmed deletion, Feedback independence, a 1,500-row virtual list, and scan-lock responsiveness.

Actual Qt screenshots use disposable fixtures, not personal library or request data. Normal and compact layouts were visually inspected. The clean-bundle audit passed, packaged HTTPS and read-only AniList checks exited 0, and Inno Setup compiled the final 1.8.2 installer successfully. A production installed updater transition to 1.8.2 has not been exercised.

## Manual check

1. Install 1.8.2, open Anime, and select Movies, TV Anime, Web Anime, Specials and Airing. Combine a genre/status filter, then use Clear filters on an empty result.
2. Select Individual Titles and click Refresh relationships. Confirm Franchises is selected and status text reports checking/completion or a clear error. Clear category/genre filters to see all available groups.
3. Confirm Collections is immediately below Favorites, with no ORGANIZE or standalone Planning. Open Planning inside Collections and test collapsed navigation.
4. In Requests & Feedback, process disposable requests with Approve, Decline and Downloaded. They should immediately leave Active Queue, retain your scroll position and appear in History.
5. Use Undo, then Restore from History. Verify original dates/notes remain and requests do not get added to Planning.
6. Reopen the app and search/filter History. Open details to review the decision timeline. Test deletion only with a disposable entry and confirm Cancel keeps it.
7. Scan one exact requested normal release. Verify Available in History. A different season, similarly named release or manga must not satisfy the request. A declined request should stay declined.
8. Confirm Feedback records and statuses, Restricted isolation, player/resume, manga, metadata, pairing/streaming and Check for Updates still behave normally.

Run development checks with `python -m pytest tests -q`; set `QT_QPA_PLATFORM=offscreen` for unattended GUI tests. Build with `packaging/build_windows.ps1` on Windows x64 using Python 3.12 and Inno Setup 6.

## Release status

1.8.2 is a local, tested candidate until published through the established personal GitHub release workflow. Stable 1.8.1 remains available for rollback. No GitHub release or installed application was changed during this task. AniVault Remote and AniVault Web were not resumed.
