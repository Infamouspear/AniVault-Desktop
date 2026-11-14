# AniVault V1.1.1-rc.1 — stability patch

## Baseline and installation

This patches the complete delivered `AniVault-V1.1-LAN-source.zip` (SHA-256
`dcef78a3b6d7bee872994c6f5c046b2829e95796e5d816a91c7bf7101fb1df59`).
No V1.0 substitution was used. Extract to a new source folder and build with the
included Windows instructions. This is source, not a compiled release installer.
Do not put databases, media, tokens or user settings into the source folder.

Close the installed app before replacing its binaries. Keep the existing
`%LOCALAPPDATA%/AnimeHub` directory. Existing database, library paths, progress,
collections, favorites and settings are retained. No database schema migration
was added. Metadata reconciliation updates only a matched title's explicit
adult flag; it does not reset artwork, progress or manual organization records.
Existing records in a now-incompatible organization scope remain stored and are
filtered, not silently moved or deleted.

Paired-device records gain a fixed expiry of 90 days from original pairing.
Existing valid bearer tokens are preserved. Visiting the new diagnostic page
upgrades a still-valid legacy cookie to persistent storage without extending the
expiry or creating another device. A cookie already lost by an old browser
session cannot be recovered: pair again and revoke obsolete entries in Settings.
Cleared cookies, private browsing and a changed server host/IP still require a
new pairing. Do not delete `lan-devices.json` as an upgrade step.

## Fixes

- Normal library cards now exclude explicitly Restricted titles even in Other
  or an unrelated folder. Search/organization, details, playback entry points and
  LAN metadata, artwork, episodes and progress share the same scope decision.
- Known adult cached matches protect legacy incomplete metadata; explicit fresh
  AniList classification updates reconcile matched local entries. Scanner commits
  invalidate desktop caches. Ecchi alone and folder names are not adult rules.
- Restricted Discovery uses the shared local detail/episode view immediately
  when a title is already in the vault. Normal Discovery navigation is preserved.
- Settings shows Running, Stopped, Starting or Error from the actual server
  lifecycle, current address/port and useful bind failures. Windows exclusive
  binding prevents a second listener from taking an occupied port.
- Browser sessions persist with fixed expiry. Valid repeated pairing does not
  duplicate a device or extend its expiry. Settings lists expired devices and
  tooltips show pairing date, expiry, ID and last connection this session.
- Timeline FFmpeg launches use CREATE_NO_WINDOW. A failed thumbnail receives
  backoff; rapid movement is debounced, one worker runs at a time, and caches are
  bounded. This prevents both console flashing and immediate failed-process loops.
- Diagnostic page offers normal title/episode selection, readable errors,
  playback status and real GET/PUT progress controls. Watched/unwatched and resume
  position update the desktop and persist. No automatic tracker or mobile app added.
- Windows builds isolate DLL discovery from unrelated tools on PATH. This fixed
  the observed test-build Qt startup failure caused by Poppler's incompatible ICU.

## Intentionally deferred / limits

- Fresh testing on a physical iPhone/second Windows PC, real-library codecs,
  VLC playback and scanner contention still require the supplied manual checklist.
- Fourteen existing baseline test failures remain; see V111_VERIFICATION.md.
- Unmatched/unknown titles cannot be reliably classified by name or genre. Match
  them to AniList to establish the adult flag; no broad Ecchi rule was introduced.
- Browser storage loss cannot be recovered by device name alone, which would
  weaken authentication. Old expired/revoked entries can be removed in Settings.
- HTTP remains trusted-LAN-only and unencrypted. No TLS, internet access,
  transcoding, full PWA or native mobile work was added.
- Container delivery does not imply browser codec support. A generated MPEG-4
  test clip was unsupported in the in-app browser; FFmpeg decoded the streamed
  MP4/MKV test data successfully. Use a compatible browser/player and codec.
- The packaged test was a windowed frozen test build using the patched full
  desktop modules and bundled FFmpeg, not a production installer acceptance run.
