# V0.8.6 verification

## Scope

Built from the V0.8.5 Discovery baseline. This patch changes Planning/organization
presentation, detail relationships, fullscreen window restoration, and adds a
generic Downloads queue. Scanner/parser, playback decoding, watch tracking,
AniList progress synchronization, manga scanning/rendering and recommendation
ranking remain unchanged.

## Migration and user-data safety

`saved_planning_v086` gates an atomic one-time upgrade. Valid normal Saved AniList
rows are archived in `normal_saved_migration_archive`; a missing status becomes
Planning. Existing AniList/local/manga status aliases take precedence. Invalid or
mis-scoped legacy records are retained rather than deleted. Restricted Saved and
source bookmarks never enter this migration.

A populated database was copied before upgrade. Tests compare anime/media,
manual overrides, Collections/memberships, legacy Franchises/memberships, external
bookmarks and manga records before/after. Existing Completed and Paused statuses,
watched flags, Favorites and resume positions survive. Reopening the migrated
copy is idempotent. Source fixture bytes are unchanged.

## Runtime checks

Offscreen Qt tests exercise actual widgets, clicks, navigation and event-loop
delivery, rather than only checking source text:

- Planning headings distinguish Anime and Manga; normal cards/details have no
  Save button; Restricted cards retain Save.
- Related rows are deduplicated and scoped, distinguish local/nonlocal entries,
  open local anime/manga or informational details, and reuse cached results.
  Multiple viewers share an in-flight lookup; failures fan out, and callbacks
  safely ignore deleted panels. Malformed edges are skipped.
- A 35-file Extras fixture remains accessible in the original Extras list,
  separately from Information/Related. Files retain their original bytes.
- Manga recommendations render the same visible explanation component as anime,
  with the original media/status line retained. Ranking was not changed.
- Reader/player fullscreen hide resize handles, prevent maximize commands while
  fullscreen, and restore windowed geometry and original chrome visibility.
- Restricted Home is reused on repeat entry without new section requests; lock
  restores normal navigation and retains strict adult-only request variables.
  Themes are window-scoped; transitions no longer repolish unrelated closed
  windows or change the application's global stylesheet.
- Downloads rows update in place and the page is reused across navigation.

## Real local HTTP transfer tests

An actual loopback HTTP server supplies deterministic direct-file responses:

- Two queued files complete serially and match the original byte content.
- Final files appear only after full response validation; `.part` is removed on
  success. Existing destinations and pre-existing partials are rejected.
- Pause/resume sends Range + If-Range using the saved validator and produces an
  exact final file. Ignored Range responses fail without altering the partial.
- Servers without safe resume disable Pause; Cancel/Retry still work.
- HTTP 503, truncated responses, unknown sizes, cancellation and retry are tested.
- Restart recovery reconciles partial byte counts, resumes successfully, handles
  missing partials and preserves Completed entries.
- Shutdown returns in under 250 ms in the test; a destination created by another
  writer during a transfer is never overwritten.
- Removing a finished row leaves the completed file untouched.

Completion is persisted through a dedicated short-lived SQLite connection before
UI delivery, so closing the UI cannot discard an already-finalized result.
The background worker never uses the UI SQLite connection.

## Results

The final complete suite passed: **254 passed in 73.28 seconds**, with no failures.
Command: `QT_QPA_PLATFORM=offscreen PYTHONPATH=/tmp/anivault-v086-deps:. python -m pytest -q`.
The final theme-scoping assertion also passed in a focused runtime check.
Compilation of all application modules passed. Detail/download presentation was
rendered for visual inspection with synthetic local records.

The earlier regression run's legacy Saved assertion was updated to verify the
new Planning migration and archived original metadata. The finished suite checks
the new expected behavior, rather than retaining an obsolete normal Saved UI.

## Practical limits

- This environment provides Linux/offscreen Qt. Native Windows libVLC rendering,
  Windows filesystem finalization, multiple monitors and real-world fullscreen
  input still require the user's Windows smoke test. Existing player surface and
  overlay architecture were not redesigned.
- Related UI/request behavior is tested with controlled AniList responses. Live
  availability and exact Chainsaw Man/Reze Arc records depend on AniList; failures
  retain a clean Retry state and do not modify local metadata/progress.
- Downloads are direct-file HTTP/HTTPS only, one active transfer, no authentication
  headers, streaming conversion, automatic acquisition or site-specific adapters.
  URLs may contain normal query parameters but are not printed in diagnostics.
- Range support alone is insufficient: resumption also needs a validator. Retry
  starts over if the server cannot safely resume or the remote file changed.
- A forced process termination at the final filesystem/SQLite boundary can leave
  a completed destination requiring inspection; collisions are always refused.
  No partial file is presented as a successful completed transfer.
- Cancel/Retry and page changes stay responsive, but an outstanding socket read
  can take up to the configured five-second I/O timeout to stop in its worker.
- No user-owned Saved/bookmark/Collection/Franchise/source files were removed.
