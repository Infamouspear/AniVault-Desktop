# AniVault V1.1.1 LAN foundation

This stabilization patch uses the complete delivered V1.1 source. See
`V111_RELEASE_NOTES.md` for upgrade instructions, fixes and deferred checks.

## Start and pair

1. Start AniVault normally and open Settings → AniVault Server.
2. Select this PC's private IPv4 address, leave port 8765 unless it is occupied,
   and click Start. Loopback 127.0.0.1 is for same-PC checks only.
3. If Windows asks about the firewall, allow AniVault on **Private networks only**.
   No firewall rule, router configuration, UPnP or port forwarding is created by the app.
4. Copy the displayed address. Open it on a phone or second PC on the same LAN.
5. Click Pair new device on the desktop. Enter the eight-digit code and a device
   name on the connection-test page. The code expires after two minutes and is
   consumed by one successful pairing. Failed attempts have a global rate limit.
6. Choose a title and an available episode from the diagnostic page, then Play.
   Use Progress Testing to read state, save a position, or mark watched/unwatched.
   This remains a testing page, not a mobile app or PWA.

The browser receives a host-only HttpOnly SameSite=Strict persistent cookie.
API clients receive a bearer token in the pairing response and should store it
in their platform's credential store. Send it only in `Authorization: Bearer …`.
Tokens in query strings are rejected. Sessions expire 90 days after the original
pairing; requests do not extend that deadline. Normal browser profiles retain the
cookie across restarts. Private browsing, cleared cookies or changing the server
host/IP can require pairing again. Valid legacy browser cookies are upgraded by
the session check without creating a duplicate device.
Normal device pairing survives desktop restarts. Revoke a selected device from
Settings to deny subsequent API requests and interrupt active file streams.

HTTP on a LAN is not encrypted. Use only a trusted private network. Other LAN
devices that can observe traffic could capture a bearer token. This is a local
foundation with no internet exposure or remote-access system, not TLS-based
remote authentication. Host checks, same-origin checks, no CORS, proxy-header
rejection, bounded request workers and timeouts are enabled.

Enabled state, address and port persist in the existing settings database.
An unavailable address or occupied port produces a visible startup failure;
the server never falls back to listening on every interface. Disable / Stop
persists the disabled state. Server work does not join network threads on the UI.

## API

All routes below require authentication except `/`, `/probe.js`, and `POST /pair`.
Requests with bodies use JSON and Content-Type `application/json` (16 KiB max).
Errors are JSON containing a stable `error` code. No raw SQLite, filesystem
browser, arbitrary file path or credentials/settings endpoint is exposed.

| Method | Route | Result/body |
| --- | --- | --- |
| POST | `/pair` | `{ "code": "12345678", "name": "Phone" }` → device ID + bearer token |
| GET | `/api/v1/session` | Device name, ID and fixed expiry; upgrades a valid legacy cookie |
| GET | `/api/v1/media/{id}/progress` | One scoped episode’s watched/resume state |
| GET | `/api/v1/info` | Name, version, direct-stream capability |
| GET | `/api/v1/library` | Scoped local anime/manga counts |
| GET | `/api/v1/anime`, `/api/v1/manga` | Local title metadata, progress, artwork routes |
| GET | `/api/v1/anime/{id}`, `/api/v1/manga/{id}` | Title and episodes/volumes |
| GET | `/api/v1/anime/{id}/episodes` | Episode IDs, season, number, availability, watched/resume state |
| GET | `/api/v1/manga/{id}/volumes` | Item IDs, volumes/chapters, page/completion state |
| GET | `/api/v1/{anime-or-manga}/{id}/progress` | Per-item progress |
| GET | `/api/v1/{anime-or-manga}/{id}/related` | Known local, scoped franchise members |
| GET | `/api/v1/franchises` | Unmixed scoped franchises and representative artwork routes |
| GET | `/api/v1/favorites`, `/api/v1/collections`, `/api/v1/statuses` | Existing organization state, including scoped saved/status metadata |
| GET | `/api/v1/continue-watching`, `/api/v1/continue-reading` | Titles with ongoing progress |
| GET | `/api/v1/recently-added`, `/api/v1/progress` | Recent titles / progress summaries |
| GET/HEAD | `/api/v1/media/{episode-id}` | Original video; Range/206, length, MIME type, 416 on invalid range |
| GET/HEAD | `/api/v1/{anime-or-manga}/{id}/artwork/{role}` | Cached/local `poster`, `banner`, `thumbnail`; 404 when uncached |
| PUT/POST | `/api/v1/media/{episode-id}/progress` | `{ "position_ms": 60000, "watched": true, "automatic": false }`; fields optional except body must contain an action |
| PUT/POST | `/api/v1/manga-items/{id}/progress` | `{ "page": 5, "total_pages": 100, "finished": false, "automatic": false }` |
| PUT/POST | `/api/v1/{anime-or-manga}/{id}/favorite` | `{ "favorite": true }` |
| PUT/POST | `/api/v1/{anime-or-manga}/{id}/status` | `{ "status": "Planning" }`; Watching, Completed, Planning, Paused, Dropped or null |

Automatic video completion fills earlier episodes using the existing desktop
rule and cannot unwatch or lower AniList progress. Explicit watched/unwatched
actions can decrease progress. Manga automatic updates cannot undo completion
or lower the saved page; explicit page and finished state updates can do so.
Reads use short read-only SQLite snapshots. Mutations queue to Qt's database-owning
thread and use the existing data methods and AniList sync policy. They invalidate
desktop presentation caches and refresh supported idle library/detail views.
Active playback and reading are not replaced by a background client update.

## Restricted Archive

Normal routes filter Restricted records before serialization and do not emit raw
AniList metadata, nested relations, source paths or private cached artwork paths.
Mixed-scope franchise labels are omitted. Retired external bookmarks are not
exposed as local LAN media.

For explicit Restricted access, unlock the archive on the desktop, select a
paired device in Settings, and click Grant Restricted until lock. That device
can then use `/api/v1/restricted/...` with the same route structure. A normal
pairing never grants Restricted access. Locking the archive, stopping the server,
or restarting the app invalidates grants. Unlocking again does not restore them.
Authorization is rechecked on queued writes and each streaming chunk.

Artwork is served only from recognized artwork/manga caches or a title's indexed
manga folder, with an image-extension allowlist; it is never fetched from a URL
submitted by a client. Uncached artwork must first be loaded/cached by the desktop.
Thumbnail requests may fall back to the title cover. Streaming resolves an indexed
video ID, requires the file to remain inside its title folder, opens it read-only,
and copies at most 64 KiB per chunk. It does not transcode, copy or modify media.
Only one byte range per request is supported. MKV/codec support depends on the
client: a compatible native player may be required even when HTTP seeking works.

## Second-device acceptance (manual)

1. On a separate trusted LAN device, pair and retrieve library, poster, detail,
   episodes and progress responses. Verify Restricted titles/art are absent.
2. Play a real MP4, then a compatible MKV in an appropriate player. Seek forward,
   backward and near the end. Verify network responses are 206 with matching
   Content-Range/Length and source files remain unchanged.
3. Update position, watched/unwatched, favorite/status and manga page/finished
   state. Verify desktop reflects the result without restarting.
4. Restart AniVault. Use the saved native-client token to reconnect. Verify
   Restricted access is denied until a fresh desktop grant.
5. Grant Restricted, begin a private stream, lock the archive and verify access
   and ongoing transfer stop. Unlock again; the old grant must still fail.
6. Revoke the device, test an invalid token, a missing file and a malformed range.
   Verify denial/safe errors, then Disable / Stop and confirm the port is closed.
7. During concurrent streams, use desktop navigation, scanner and playback and
   verify responsiveness on your target Windows PC.

Automated local HTTP tests do not substitute for this Windows-to-phone check.
No second physical device is controlled by this build task.

## Build

Use the included Windows build scripts and existing `WINDOWS_ACCEPTANCE.md`.
Version: 1.1.1-rc.1. This deliverable is source, not a compiled installer. The
baseline packaging still requires the publisher's public AniList client ID for
guided linking; it never accepts an access token or client secret as release
configuration. No personal database, device store, logs, downloads queue, media
or cache should be included in source/release bundles.
