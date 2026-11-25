# AniVault Desktop 1.8.1

Simplified automatic **Airing in Your Vault** list and library card markers. No Watching or follow requirement. See [release notes and testing](DESKTOP_181_RELEASE_NOTES.md).

# AniVault Desktop 1.8.0

Initial D franchise navigation fix and persistent Airing Updates. See [release notes and testing instructions](DESKTOP_180_RELEASE_NOTES.md). Windows source builds use `packaging/build_windows.ps1`; development runs use `run_anivault.bat`. Earlier baseline notes below are historical.

# AniVault V1.1.2 Regression Fixes (1.1.2-rc.1)

Start with `V112_RELEASE_NOTES.md` and `V112_VERIFICATION.md`. This focused patch
uses the complete supplied V1.1.1 source. It fixes reader keyboard/fullscreen
input, player clicks and lifecycle cleanup, and Airing metadata clipping, with
Windows test-fixture corrections. LAN and Restricted behavior are preserved.

Run `run_anivault.bat` after installing `requirements.txt`. For development tests,
install pytest and run `python -m pytest tests -q` from this source directory.
For unattended GUI tests set `QT_QPA_PLATFORM=offscreen`.

Earlier verification documents below describe historical releases; use the V112
report for current automated Windows results. This is a source ZIP, not an installer.

# Historical V1.1.1 notes

Start with `V111_RELEASE_NOTES.md` and `V111_VERIFICATION.md`. This patches the
complete V1.1 source; it is not a reimplementation from V1.0. Includes shared
Restricted classification, immediate Restricted Discovery episodes, live server
status, persistent expiring browser sessions, diagnostic progress controls and
hidden/throttled FFmpeg previews. Earlier verification documents below are
historical baseline evidence, not fresh V1.1.1 results.

Rebuilt from the user-provided V1.0 source; the previous V1.1 workspace was not
recoverable in this session. Includes an optional private-interface LAN server,
pairing/revocation, scoped metadata/artwork, desktop-thread progress/state updates,
and seekable original-file video streaming. Server is off by default.

Start with **Settings → AniVault Server → Start**. See `V11_LAN_GUIDE.md` for
pairing, API routes and second-device checks, and `V11_VERIFICATION.md` for the
actual validation results and limitations. This is clean source and build
scripts, not a compiled installer or a claim of completed phone acceptance.

The following notes describe the preserved V1.0 baseline:

Your anime, your library.

This is a source release candidate, based on V0.9.1. It includes Windows build/installer definitions; it is **not yet a compiled or Windows-validated V1.0 installer**. See `RELEASE_VERIFICATION.md` and `WINDOWS_ACCEPTANCE.md` for evidence and remaining gates.

- Delayed hover, pinned single-click Focus View and double-click Full Details are preserved.
- A single pinned Lucide outline family replaces mixed sidebar symbols.
- Sidebar mascots coexist with page empty states; Restricted Home uses the supplied cinematic banner. The transparent Restricted mascot stays secondary.
- Settings → Appearance / Startup offers splash On/Off and Brief (1s), Standard (2.75s), Extended (5s). Startup waits for both readiness and minimum duration without blocking the event loop.
- Fresh accounts get empty personal state and short folder setup. Anime/Manga scanning is read-only; AniList is optional.
- Guided AniList linking opens the browser and accepts one authorization PIN/code. **A public publisher client ID remains required before shipping.** No client secret is used or bundled. Users do not register OAuth applications.
- Settings provides version/build/schema fingerprint, log-folder access, VLC compatibility check, and disposable artwork-cache refresh.
- Existing `%LOCALAPPDATA%/AnimeHub` data stays in its historical location. Release preflight checks integrity and creates a SQLite-aware backup before existing migrations; corruption fails safely instead of recreating the database.
- EXE/installer builds use only an explicit clean code/assets staging allowlist. Databases, settings, tokens, caches, logs, source media and personal paths are not build inputs.
- Uninstall retains user AppData. No file associations are claimed. Windows build targets x64 with no normal console.

## Run from source

Use Python 3.12 x64, install `requirements.txt`, then run `python main.py`. Desktop VLC with compatible architecture is required for integrated playback; use Settings → Check VLC Runtime. Existing external VLC fallback remains available. PDF support is provided by pypdfium2; CBR may require a compatible local unrar/unar/7-Zip extraction tool in addition to rarfile. Source media is never rewritten.

## Windows release build

On Windows x64 with Python 3.12 and Inno Setup 6 installed:

```powershell
.\packaging\build_windows.ps1 -AniListClientId <registered-public-client-id>
```

The publisher registers AniVault once with AniList, using `https://anilist.co/api/v2/oauth/pin` as the registered redirect. Supply **only the public numeric client ID**, not the client secret or an access token. The build fails if the ID is absent or if public configuration contains secret/extra fields. `assets/release-public.json` intentionally has an empty ID in this candidate.

Build outputs: `dist/AniVault/AniVault.exe` and `dist/installer/AniVault-1.0.0-rc.1-Setup.exe`. These do not exist until the Windows build runs. The optional manual GitHub workflow uses repository variable `ANILIST_CLIENT_ID`, not developer credentials. No repository is published by this bundle.

The installer uses one stable AppId, per-user binaries under `%LOCALAPPDATA%/Programs/AniVault`, optional desktop and Start-menu shortcuts, and no AppData removal during uninstall. Application data remains separately under `%LOCALAPPDATA%/AnimeHub` to preserve previous installs.

## Previous implementation notes

The following historical notes describe earlier releases; this RC's branding and release behavior above supersede them.

# AniVault V0.9.1 — Focus View Polish + Supplied Branding

Based on the working V0.9.0 build.

- **Hover:** a 280 ms delay previews a title. Moving away cancels pending previews.
- **Click:** pins that card in Focus View. Other hover activity cannot replace it.
- **Double-click:** opens Full Details; franchise/group cards open their existing overview. **Enter** opens, **Space** selects. Live search suggestions retain direct navigation.
- Use **Pinned** to unpin and resume hover previews. Close × hides the panel until intentional card selection. Navigation/scope changes cancel pending input and release the old pin.
- Larger cover treatment, readable status/progress and a prominent **Continue Watching / Continue Reading** action. Quick status, Favorite, Collection and cached related actions remain.
- Compact episode context: up to three nearby episodes, or current/next local manga items. No full episode dump or redundant Full Details button in the preview.
- Manga Continue Reading cards provide a direct Continue Reading button; double-click consistently opens series details.
- Hidden/retired cards cannot use delayed mouse input to navigate. Resizing still uses persistent grid cards and hides the rail in narrow windows.

## Supplied branding

The supplied little fox, Restricted cutout, icon, splash and three empty-state illustrations are integrated. See **ASSET_PLACEMENT.md** for scope, size, transparency and small-window rules.

Splash is startup-only. Dense grids prioritize media art. Empty states use one main illustration, suppressing sidebar decoration on that page. Restricted Vee stays in Restricted views; the hero contains the complete supplied cutout over a shared gradient. PNG copies preserve the original pixels and transparency; the Windows ICO is a multi-resolution derivative. The supplied All Caught Up image is opaque and remains unchanged.

## Launch / upgrade

Extract into its own folder and run **run_anivault.bat**. Keep the existing AniVault data directory; no fresh user database is bundled. Dependencies and database migrations are unchanged. Source anime/manga files remain read-only.

## Verification / limitations

See **V091_VERIFICATION.md** for runtime tests and the backend/source-art audit. Windows taskbar/Alt+Tab, hardware-specific VLC/fullscreen and real user media still need manual acceptance. No installer, chatbot, new playback engine or live external-source integration was added. Manga AniList chapter sync remains deferred.

## Previous release history

# AniVault V0.9.0 — Media Hub UI

Built on **V0.8.8.1**, using the supplied concept as direction for the native PySide desktop application.

- Grouped sidebar: Primary, Discover, Organize, System and the unlock-only Restricted entry. Saved is available in Discover; Franchise Groups remain accessible from Collections.
- Persistent global header search with local-first, franchise-aware anime/manga suggestions, cached thumbnails and **Ctrl+K**. Back/Forward controls share existing navigation history. Page-specific library filters and advanced Discover search remain available.
- Artwork-led Home with compact Recently Added, Continue Watching, Recently Watched and manga shelves when populated. Top Picks reuse loaded Discover data or the existing recommendation request/cache for meaningful profiles.
- Contextual right rail on wide browsing pages: highlight/focus a card to preview its poster, synopsis, progress, status, local episodes/volumes and quick actions. Close the rail with ×; highlighting another title reopens it. Narrow windows, full details, settings and playback/reading views hide it.
- Shared full-bleed hero rendering for Home, Discover, detail pages and Restricted Home. Aspect ratio is preserved through focal cropping, with a readability gradient rather than contained artwork and black margins.
- The rail uses existing local IDs for playback/reading and keeps full detail/relations workflows. It does not create local records for remote metadata.
- Restricted scope changes clear the persistent search/selection UI; lock preserves private data and restores normal navigation.

## Launch / upgrade

Extract this build into its own folder and run **run_anivault.bat**. Keep the existing AniVault-owned data directory. Dependencies and database schema are unchanged from V0.8.8.1; no fresh database is bundled. Source media remain read-only.

## Verification / limits

See **V09_VERIFICATION.md**. Native Windows VLC rendering/fullscreen and real-library visual acceptance still need manual testing on Windows. Manga progress remains local; AniList chapter progress sync is deferred because reader pages cannot safely be interpreted as chapters. Staff/character data are not fetched for the preview rail. The rail exposes up to 48 local items; full details retain the complete list.

## Baseline release history

# AniVault V0.8.8.1 — Pre-V0.9 UI Parity Hotfix

- Restricted AniList Saved entries migrate to **Planning** when no meaningful status exists. Watching/Reading, Completed, Paused, Dropped and existing Planning are preserved. Original bookmark metadata is archived locally; genuine external bookmarks, source URLs, statuses and Collections remain intact.
- Restricted discovery/detail cards no longer expose Save/Saved. External records remain accessible through **External Bookmarks** when present.
- Normal and Restricted Collections/status cards share cover mosaics, including cached local art, asynchronous AniList covers and generated local manga covers. Counts/art update through the shared status signal.
- Fixed the Restricted stylesheet cascade that painted opaque backgrounds behind labels. Shared detail heroes keep artwork aspect-safe, with transparent content and restrained gradients. Restricted Home's hero remains part of the scrolling page.
- Franchise / Related panels use full-size shared media cards, with whole-card pointer/keyboard activation, local titles first, metadata-only titles second and visible relation/media labels. Child scrolling stays contained; loading/empty panels do not reserve a giant blank region.
- Existing V0.8.8 manga completion, clean titles, separate Favorites, search covers, status controls, responsive grids and secondary **+ Collection** actions remain in place. External bookmark cards now use the same media-card geometry.

Launch with `run_anivault.bat`. Dependencies are unchanged. Keep your existing AniVault-owned data directory when upgrading; migrations run when the database opens. Never replace it with a fresh database. Source media are read-only.

See **V0881_VERIFICATION.md** for tests, migration details and remaining native Windows acceptance checks. V0.8 feature scope remains frozen; no V0.9 features or live external-source systems were added.

## Previous release notes

# AniVault V0.8.8 — Final Stabilization + V0.8.7 Cleanup

## New in V0.8.8

- Standard Anime, Manga, discovery, organization and franchise cards share 228 × 460 dimensions, 210 × 258 artwork, two-line title slots and fixed metadata/footer positions. Responsive grids reuse cards; compact Home/Related/collection-overview components retain their purpose-specific layouts.
- Favorites has separate Anime Favorites and Manga Favorites sections. Manga summaries avoid stacked volume/chapter totals; full counts remain in details.
- Manga display titles consistently prefer matched metadata, explicit titles, cleaned parsed names, then raw fallback. Source names and paths are untouched.
- Local manga volumes/items support **Mark Finished / Mark Unfinished** from the row context menu, plus a selected-item toggle. Resume pages, bookmarks and manual series status are preserved. Item completion counts update in place.
- **+ Collection** is a compact secondary detail action. Colored status controls remain primary, and all collection actions continue to work.
- Search suggestions include fixed lazy-loaded cover thumbnails. Text appears first; only visible rows request artwork. Cached loaders, stale-response/privacy guards and media-only suggestions remain in use.
- Nested Related, Extras and manga-item panels contain wheel input at their boundaries while retaining normal keyboard navigation.
- Franchise overview cards no longer use taller wrappers. Local titles remain first, followed by informational AniList-only relations. Empty episode names produce only Episode N.
- Startup logs a compact read-only integrity audit. Suspect records are reported rather than destructively cleaned. Existing worker shutdown and Restricted isolation are retained.

Launch with `run_anivault.bat`. Dependencies are unchanged. CBR requires a supported UnRAR/7-Zip backend; PDF uses pypdfium2. See [V088_VERIFICATION.md](V088_VERIFICATION.md) for validation and remaining Windows checks.

## Previous release notes

# AniVault V0.8.7 — Performance, Reliability + UI/UX Polish

## New in V0.8.7

- All Anime defaults to franchise cards for two or more local anime joined by explicit AniList anime-to-anime relationships. Individual Titles remains available. Name similarity and manga/source relations never establish membership.
- Franchise overviews retain independent titles, useful release/relation ordering, format, In Vault/AniList-only labels, status, progress and relation labels. Opening a child uses the normal detail/playback route.
- Global search suggestions prioritize scoped local media, collapse broad franchise matches, and expand specific child searches. Remote suggestions are debounced and cached.
- Manga display titles prefer matched AniList metadata and remove release noise only for presentation; stored identities and source names remain unchanged.
- Favorites routing, clean episode labels, Related cards, non-local details, direct status controls and Collections cover previews are polished. Discover filters are compact and responsive.
- Library pages reuse cards and batch status reads. Poster memory/disk caches are bounded. Restricted hero artwork scrolls with its page; privacy and data scopes remain separate.
- Worker shutdown retains live owners until work finishes, suppresses late UI callbacks and avoids blocking the visible window. Downloads reject duplicate active destinations.

Use `run_anivault.bat` on Windows. No additional dependency is required beyond the existing build. CBR still needs a supported UnRAR/7-Zip backend. See [V087_VERIFICATION.md](V087_VERIFICATION.md) for measured checks and Windows runtime limitations.

## Previous release notes

# AniVault V0.8.6 — Downloads Manager + Detail-page Related Media

## New in V0.8.6

- Normal AniList anime/manga now use **Planning** for watch/read later. Normal
  Saved navigation and large Save buttons are removed. On upgrade, Saved titles
  without a status become Planning; existing statuses win. Original Saved rows
  are archived locally before removing the redundant relationship. Restricted
  Saved and external bookmarks are unchanged.
- Mixed status lists show separate **Anime**, **Manga**, and, where needed,
  External Bookmarks sections. Status, Favorites and Collections remain separate.
- **Franchise / Related** lives on anime and manga details. It uses explicit,
  one-hop AniList relations, shows media/relation type, local availability and
  status, and opens the appropriate local or informational detail page. It uses
  the existing background request queue, per-scope cache and global cooldown.
  Manual franchise navigation/actions are retired; old records remain stored.
- Anime details retain **Extras → Information → Related** as separate right-hand
  panels. Bonus files never become metadata relationships. Manga and anime
  recommendation cards share a readable explanation line, without hiding their
  existing status/local metadata. Recommendation ranking is unchanged.
- Player and reader fullscreen hide resize handles and title chrome, guard system
  resize/move actions and restore the previous geometry and chrome visibility.
- **Downloads** accepts user-requested direct HTTP/HTTPS files. One background
  transfer runs at a time; queued, active, paused, completed, failed and cancelled
  rows persist. Transfers use `.part` files and refuse destination collisions.
  Progress, bytes, speed and ETA update asynchronously. Pause/resume requires
  Range support plus a strong ETag or Last-Modified validator; unsafe resume fails
  cleanly and offers Retry. Cancelled partials remain until Retry starts over.
  Remove Entry/Clear Completed remove queue records, never completed files.
- Interrupted queue entries recover paused; completed entries remain completed.
  Downloads do not initialize network workers until a transfer is requested and
  do not wait for network I/O on application shutdown.
- Theme switching is limited to AniVault's window and owned dialogs, avoiding
  application-wide repolishing of unrelated windows. Restricted artwork/page
  caches remain isolated. Theme/entry/lock timing and
  download/migration/relation errors are logged in `playback_diagnostics.log`.
  No live nHentai/hanime, metadata index or WebEngine subsystem was reintroduced.

Use the existing `run_anivault.bat` launcher on Windows. No new dependency is
required for this patch. The existing reader still needs an available UnRAR/7-Zip
backend for CBR; CBZ, PDF and image folders use the existing local dependencies.
See [V086_VERIFICATION.md](V086_VERIFICATION.md) for tests and platform limits.

## New in V0.8.5

- Discover offers Anime and Manga in both normal and Restricted scopes.
  Recommended For You uses scoped local activity and organization, rather than
  treating Saved entries as equally strong interests. Favorites have the strongest
  base weight; consumed progress, completed/active statuses and recent activity
  also matter. Saved/Planning are weak signals. Collection membership adds a small
  bonus to an existing interest. Dropped entries do not seed preferences.
- Candidate ranking uses weighted genres and non-spoiler AniList tags. Popularity
  breaks ties instead of overpowering affinity. Ordering is deterministic; new
  View All pages append without globally rearranging earlier results.
- Recommendations exclude existing local titles, completed/heavily consumed and
  dropped targets, wrong media/scope, and duplicate AniList IDs. Other discovery
  sections still show In Vault markers and preserve ordinary browsing behavior.
- Concise recommendation reasons appear when backed by actual consumption,
  Favorites/status affinity, or explicit cached AniList relations. Cached relation
  nodes can recommend the other media type; similar names never create relations.
  Reasons are presentation data and are not saved into persistent title metadata.
- Profiles and Discover landing pages are cached for 15 minutes, keyed by scope
  and media type. Meaningful changes invalidate the profile; unrelated settings
  do not reshuffle it. Refresh Recommendations rebuilds from current local signals
  and requests fresh recommendation pages through the existing deduplication and
  rate-limit protection; unrelated discovery page caches remain available.
- Restricted lock guards apply to Discover and View All directly. Normal and
  Restricted profiles/catalogs cannot contribute signals to each other. External
  Saved bookmarks remain cached organizational records with normal-browser source
  links; no old provider, index, WebEngine or hanime subsystem is activated.

See `DISCOVERY_VERIFICATION.md` for tests and practical limitations.

## Local Manga

Open **Library → Manga → Roots…**, add one or more manga folders, then
choose **Rescan Manga**. Scanning is explicit and runs in the background;
opening the page or starting AniVault does not rescan archives. The Manga
page also offers **Open Manga / Comic** for opening a book directly.

## New in V0.8.4

- The header search now finds local anime, local manga and Saved AniList entries
  together. Restricted search stays inside its scope, including cached external
  bookmarks. Results explicitly label Anime/Manga/External and In Vault/Saved/
  Missing; no network discovery request is made by local global search.
- Sidebar **Favorites** displays both local anime and local manga using their
  existing Favorite flags. Media-specific filters remain available; no new
  Favorite table or destructive migration is introduced.
- Collections and status lists resolve mixed media through one batched catalog.
  Saved manga matched locally opens the normal manga detail/reader flow.
  Certain local/Saved aliases display once without merging stored records.
- Collection counts and preview art use only valid entries in the collection's
  scope. Duplicate legacy alias rows remain stored, but do not inflate displayed
  counts. Explicit Remove from Collection removes the matching relationships
  only; Saved, status, progress and media are untouched.
- Reading/Watching labels stay media-specific. Saved manga status is recognized
  by its local version; explicit changes synchronize an existing status alias.
  Status still does not mark episodes/pages complete or change AniList progress.
- Saved offers Anime/Manga/External filtering. Local manga gets an In Vault link
  on cards and remote metadata details; nonlocal records remain informational.
  Cached Restricted Saved refreshes after relevant local mutations.
- Anime detail now exposes manual status, availability and Collection links,
  with a Status / Collections menu; contextual local menus include Remove from
  Saved where appropriate. Cached explicit AniList anime/manga relations can be
  displayed, without adding manga to anime franchises or issuing extra requests.
- Existing external bookmarks remain offline-capable organizational records.
  Open Source uses the normal browser. No live-source integrations return.

See `CROSS_MEDIA_VERIFICATION.md` for verification and practical limits.

## Preserved from V0.8.3

- **Settings → Reading** controls direction, single/spread layout, single cover,
  fit mode and persistent toolbar. Press Save Settings; choices survive restart.
- Fit Page uses the available viewport with a small margin and preserved aspect
  ratio. Hidden controls reclaim their space; fullscreen hides the reader header.
  Portrait pages still require side space on a widescreen monitor.
- Click the left/right viewport edges to turn pages in the chosen reading
  direction, including spreads. A small center dead zone prevents accidental turns.
- Wheel up/down zooms instead of turning pages. Drag pans; movement beyond Qt's
  drag threshold suppresses click-to-turn. Zoom aims to retain the point under
  the cursor, subject to scrollbar bounds.
- **T** toggles the toolbar. Right-click exposes navigation, fit, bookmarks,
  retry, fullscreen and Back. Keyboard reading works with controls hidden.
- Continue Reading excludes untouched and fully completed series and opens
  the correct active book directly. Recently Read includes finished books.
- Manga details display matched/local titles, last read, Collection links,
  readable item progress and cached metadata. Favorites update existing cards.
- Parsing ignores release-group/edition annotations and implausible year/
  resolution numbers, supports bracketed chapter labels and retains useful
  trailing chapter titles. Exact cleaned loose-volume titles group together;
  no fuzzy franchise/title merging is introduced.
- Covers now reliably prefer manual/local cover, AniList cover, generated
  thumbnail, then placeholder. Local cover/folder/poster artwork is read in
  place; generated thumbnails stay in AniVault's cache and refresh after a
  detected source modification.

See `MANGA_POLISH_VERIFICATION.md` for the V0.8.3 baseline verification.

## Local manga library

- Index CBZ, CBR, PDF and nonrecursive image folders. Volume/chapter labels
  accept decimals; filenames and pages use deterministic natural ordering.
  Named series folders and generic volume/chapter containers are grouped
  conservatively. No fuzzy title merging or source renaming is performed.
- Search, page-local sorting, Continue Reading, manual Reading/Planning/
  Completed/Paused/Dropped statuses, reading progress, Recently Added and
  manga Favorites. Favorites are accessible through the shared sidebar view
  and the existing media-specific filters. Manual status and actual reading completion are separate.
- Detail pages list readable items, resume the existing reader, expose Open
  Folder and reuse the shared Collections/status organization system.
- Existing reader progress and bookmarks are reused, including books opened
  before they were scanned. Rescans retain matching, status, favorites and
  collection membership. Missing items retain state and are labelled Missing.
- Normal and Restricted roots are explicit. Restricted Local Manga is available
  within the unlocked Archive; locking closes its reader and hides its data.
  An explicit adult AniList match makes a title Restricted; ecchi alone does not.
- AniList matching searches MANGA only, supports a manual ID and unmatching.
  Matches persist locally. Manga reading-progress synchronization is deferred.
- Covers use manual artwork, cached AniList artwork, then a lazily generated
  first-page thumbnail or placeholder. Source decoding happens in a bounded
  background queue; scanning itself does not extract pages or download covers.
- Source roots may not overlap each other, the anime root or AniVault's data
  directory. The scanner does not follow directory symlinks.

## Local reader

- CBZ is read directly; folders use nonrecursive natural image ordering.
- PDF pages render on demand through pypdfium2 (PDFium).
- CBR uses rarfile plus a separately installed RAR decompressor on PATH.
  **UnRAR is recommended**. Install it, restart AniVault, and reopen the book.
  Missing tools produce a clear reader error, not a crash. Other rarfile
  backends may have limited RAR-version support.
- JPG/JPEG, PNG and WEBP are supported; BMP/TIFF use available Qt plugins.
- Single/spread, optional single cover, RTL/LTR, Fit Page/Fit Width,
  100%/manual zoom, drag-to-pan and fullscreen.
- Left/Right follow reading direction; Page Down/Space advance, Page Up goes
  back, Home/End go first/last, F toggles fullscreen, Escape exits fullscreen.
  Wheel zooms. P fits the page, W fits width, 0 resets zoom; +/− zoom.
  Buttons labelled Previous/Next always mean earlier/later in reading order.
  B toggles a page bookmark; T toggles the persistent toolbar.
- Last successfully displayed page resumes automatically. Bookmarks and
  completion persist independently of anime watch state. Opening alone does
  not complete a book; navigate to the final page/spread to finish. For a
  one-page item, press Next after reading it to mark completion.
- Preferences are global; item state uses a canonical path identity, reused by
  library items and retained through explicit scope changes. Moving/renaming a
  source book is not automatically matched to its old identity; the old missing
  record retains progress. Restricted-origin reading stays private.
- One background worker owns source handles. Only the current spread and
  nearby pages are requested; decoded cache is bounded to five pages/96 MiB.
  Very large pages are downscaled to a 3072px longest edge for memory safety;
  100% refers to the decoded image. PDF rasterization is capped similarly.
  Corrupt individual pages can be retried or skipped.
- Temporary reader files live in AniVault's cache and are cleaned per session.
  No permanent archive extraction or PDF conversion is performed.

Install/update dependencies with `python -m pip install -r requirements.txt`.
This build pins Qt/PySide6 6.11.2, the tested runtime, rather than installing
an unverified newer Qt release.
PDFium and Pillow are included through those requirements; UnRAR is optional
and installed separately. Keep the existing app-data database.

`LOCAL_MANGA_VERIFICATION.md` records the V0.8.2 baseline.
`LOCAL_READER_VERIFICATION.md` records the V0.8.1 reader baseline.

## V0.8 rollback remains in effect

The live-source experiment is concluded. Restricted Archive now focuses on
AniList anime/manga and AniVault-owned organization.

## Preserved

- Normal library, scanner, player, watch/resume state, AniList and Discover.
- Restricted AniList anime/manga, isolated recommendations and lock behavior.
- Restricted Saved, statuses and Collections.
- Existing external records (including nHentai): source identity, title, cached
  metadata, source URL, status, Collection membership and reading history.
- The retired source-neutral reader component remains dormant, with no live
  source or external navigation action. The new local reader is independent.

## External bookmarks

Open **Restricted Saved → External Bookmarks** or a Restricted Collection.
Cards/details use stored metadata and already-cached artwork only. Actions:
Open Source, Set Status, Add to Collection, Remove from Saved.
Open Source launches the ordinary system browser, not WebEngine.
Removing a bookmark from Saved does not clear its status or Collection links.

## Removed

Doujin discovery/navigation, source clients/parsers, embedded-source browser,
source-reader launch flow, local metadata provider, snapshot download/import/
update controls and workers, source-specific discovery recommendations.
No hanime integration or live-source implementation plan is included.
No large index is required or opened during ordinary operation.

## Install / safety

Run this folder as the new application build. Keep the existing AniVault app
data directory and main `anime_hub.db`; do not replace it with a fresh database.
V0.8.4 reuses the existing manga root/series/item, reader-state/bookmark
and shared organization tables; it adds no schema migration. Existing anime, Saved, status and organization
records are preserved. No automatic data deletion.
Old application builds are independent; stop using them for live-source work.

The retired `doujin_index.db` is left untouched. Optional Settings action:
**Move verified retired source cache aside…**. Only when requested, a background
job validates the generated schema and every metadata record. Unexpected
tables/fields, active SQLite sidecars, symlinks or changed files cause refusal.
After verification and confirmation, the index is moved to a recoverable
`retired-source-cache/<timestamp>/` folder. Nothing is deleted. Delete that
folder manually to reclaim disk space, or restore the file if needed.
The main database, metadata/status sidecar and media folders are never moved.

## Verification

See `ROLLBACK_VERIFICATION.md` for executed tests and remaining platform checks.
