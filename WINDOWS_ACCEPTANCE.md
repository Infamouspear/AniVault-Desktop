# V1.0 RC Windows acceptance — outstanding release gate

This checklist has **not been executed here**. The build environment is Linux and has no Windows runtime/compiler. Do not relabel RC as final V1.0 based only on source/Qt tests.

## Publisher setup

1. Register the AniVault public desktop application once with AniList using the PIN redirect `https://anilist.co/api/v2/oauth/pin`.
2. Supply its **public numeric client ID** to `packaging/build_windows.ps1` or repository variable `ANILIST_CLIENT_ID`. Never supply a client secret/access token. Normal users never perform this setup.
3. Build on Windows x64. Confirm the EXE's version/icon/no-console subsystem and the installer's fixed AppId.
4. Inspect the staged manifest and bundle audit. Do not add AppData, developer settings, databases, credentials, logs, cache, source media or user progress to the installer.

## Clean account / separate PC

- Install using a new Windows account or clean VM with no AniVault/AnimeHub AppData and no Python installed.
- Launch installed Start-menu/optional desktop shortcut; correct fox icon, no console, splash visible.
- Verify empty first-run setup, no developer titles/paths/history, normal theme, Restricted locked.
- Choose Anime folder; optional Manga folder; skip AniList; scan read-only and inspect source timestamps/checksums.
- Link AniList: browser opens correct AniVault approval, approve, paste only the displayed PIN/code, validate, account shown, restart persists. No OAuth developer configuration needed from users.
- Test missing VLC, 32-bit mismatch, and compatible 64-bit VLC. Errors are useful; external fallback works.
- Brief/Standard/Extended meet minimum duration and main readiness; Off launches directly. Preferences survive restart.
- Diagnostics shows app/build/schema fingerprint, opens log folder; artwork-cache refresh preserves library and metadata.

## Upgrade / data safety

- Back up real user data first, independently of the app.
- Launch over the existing development install using the retained `%LOCALAPPDATA%/AnimeHub` location.
- Verify backup and migration diagnostics; library, manual matches, anime progress/resume, manga progress/bookmarks, Favorites, Collections, franchises, status/Planning, Restricted data, external bookmarks and Downloads retained.
- Install over previous RC with the same AppId: one install, state retained.
- Uninstall removes binaries/shortcuts but retains all user AppData; reinstall restores it.
- Verify no video/CBZ/PDF associations are claimed.

## Product smoke tests

| Area | Required manual verification |
|---|---|
| Anime | Open/play, seek, subtitle/audio switching, speed, volume, native fullscreen and click input, next/previous, stop/close, 90% watch/resume persistence, external VLC, Extras |
| Manga | Open CBZ/PDF/folder/CBR where dependency available, Continue, natural order, single/spread, RTL/LTR, fit/zoom/pan, bookmarks, completion/un-completion, restart |
| Discover/search | Anime/Manga recommendations, pagination, global suggestions/thumbnails, local and remote details, franchise result, scope isolation |
| Home/Focus | Delayed hover, single-click pin, Continue, status/Favorite/Collection, double-click details, compact episode/item context |
| Art | Mascot/empty-state coexistence, three empty-state types, resize, 100/125/150/200% Windows scaling, safe Restricted banner/secondary cutout |
| Restricted | Enter/lock/unlock, no normal/private search/cache/art/data leakage, bookmarks retained, no live source/WebEngine startup |
| Downloads | Existing queue, cancel/retry, restart/recovery |
| Shutdown | Idle, active player, reader, scanner/download activity; bounded orderly close, no stranded process; reopen |

Record failures and evidence before claiming the 81-point brief complete. Linux/offscreen tests supplement these checks; they do not certify native HWND playback, taskbar, installer or real-account OAuth behavior.
