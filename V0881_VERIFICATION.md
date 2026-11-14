# V0.8.8.1 verification

## Focused changes

Shared presentation components now cover Restricted equivalents rather than maintaining separate card layouts. Standard media and external bookmark cards are 228 × 460, with 210 × 258 artwork and reserved two-line title/metadata positions. Compact organization overview cards intentionally remain 270 × 204.

The Restricted palette's broad QWidget rule was overriding the shared transparent QLabel rule. An explicit transparent QLabel rule restores art visibility and removes text-bar backgrounds. Shared detail heroes paint aspect-preserving art beneath transparent child content and a restrained gradient. Restricted Home uses safe contain framing to preserve the complete focal image rather than cutting off faces at narrow widths; the hero remains inside the content scroll area. No video-player overlay architecture changed. Scanner, integrated player, AniList integration, recommendation engine and download engine modules are byte-for-byte unchanged from V0.8.8.

Collection/status mosaics read cached metadata paths as well as actual local row fields. At most four cover candidates are loaded through existing async artwork services. Local manga cover-generation callbacks also deliver to mosaic/search targets; obsolete callbacks are guarded. Status counts and art respond to the shared mutation signal. Unavailable art has a deliberate compact placeholder, while the create card has a plus treatment.

Franchise / Related cards reuse Anime, Manga and discovery components. Decorative child labels/progress pass input to the parent card; buttons retain independent input. Enter/Space activates cards. Local matches are ordered first and remain one click from their own detail/reader/player. Manual franchise suggestions retain an independent Add action. Scope filters and the existing one-hop cache/request pipeline are preserved; no new relation queries or recursive crawling were added. Child wheel containment remains in place.

## Restricted Saved migration

The one-time restricted_saved_planning_v0881 migration runs in a transaction. It archives every original Restricted AniList bookmark into restricted_saved_migration_archive. Explicit adult AniList entries without a meaningful manual status become Planning; existing local/remote status aliases are checked before changing anything. Existing meaningful statuses are preserved. Successfully handled rows are removed from the redundant saved_titles scope only.

External records remain in restricted_source_saved/metadata/history, with source identity, URL, status, collection membership and cached art unchanged. Invalid/ambiguous legacy AniList records are archived and retained, counted as skipped rather than deleted. No source files, watch/read progress, Favorites, manual matches, reader bookmarks or collections are rewritten by this migration. It is idempotent across restarts. Migration diagnostics contain compact counts, not private titles/history.

## Runtime and regression validation

- Full release suite: **293 passed**, 88.97 seconds.
- Targeted Restricted parity, migration, shared presentation and rollback checks: **75 passed**, 12.87 seconds, including final source-card, local-cover-target and palette checks.
- Actual Qt offscreen interactions test migration with all five statuses, local aliases, external bookmarks, collection memberships, source hashes and restart idempotence.
- Live Restricted pages verify Planning counts, absence of AniList Save/Saved controls, external-bookmark access, lock privacy and hero content scrolling.
- Async mosaic checks verify both status/custom art, in-place updates, generated local covers, and discarded deleted-page callbacks.
- Normal/Restricted related cards are tested at cover/title/metadata/empty-space coordinates plus keyboard activation. Local-first ordering and opposite-scope exclusion are asserted.
- Pixel checks verify hero artwork remains visible at wide/narrow sizes and labels no longer paint opaque bars.
- Synthetic-art rendered inspection compares Normal/Restricted Collections, Restricted Favorites, detail/related cards, manga details and narrow/wide Restricted Home. No user library or browsing history was used.
- Existing tests continue covering playback state/input teardown, scanner/extras, reader modes/progress/bookmarks/PDF/CBZ, reversible completion, titles, search covers, navigation, discovery pagination, sync safety and download restart/finalization.

## Limits and manual acceptance

Qt offscreen on Linux cannot verify native Windows VLC rendering/audio/subtitles/fullscreen, OS input ownership or multi-monitor behavior. Repeat those smoke checks on the user's Windows build. No user database was supplied; migrations were verified with copied synthetic upgrade fixtures. CBR needs a supported UnRAR/7-Zip backend; PDF uses pypdfium2. Long-running network behavior is exercised with controlled fixtures rather than a user's authenticated account.

Artwork is asynchronous: a cover appears only if it exists in cache/local media or the existing AniList image request succeeds. Missing art is not fabricated. Contain-framed heroes may leave deliberate background margins for unusually shaped artwork.

No live nHentai/hanime, WebEngine, metadata-index worker, source discovery or source reader was activated. External Saved bookmark records remain intact. User source media remain read-only. V0.8 features are frozen; V0.9 work was not begun.
