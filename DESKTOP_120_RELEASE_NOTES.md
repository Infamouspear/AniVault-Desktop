# Desktop 1.2.0-rc.1

Artwork leads the All Anime, Home, Planning, and manga surfaces. The original
navigation, In Focus behavior, library database, and LAN service are retained.
Local anime poster thumbnails are decoded on first paint and use the existing
bounded pixmap cache. Card widgets are still created in batches in All Anime;
this is not a fully virtualized grid.

## Build and update testing

On Windows x64 with Python 3.12 and Inno Setup 6, run
`packaging/build_windows.ps1 -OfflineCandidate` for a local release candidate.
New guided AniList linking requires the publisher's public numeric client ID;
use `-AniListClientId` for a publisher build. Do not pass a token or secret.
The existing Windows workflow intentionally requires the configured client ID.

The source now targets the verified public Infamouspear/AniVault-Desktop
repository. The previously packaged offline candidate has no release feed.
Settings can check on demand
or automatically when opened. It only accepts published stable releases with
a matching versioned installer and GitHub SHA-256 digest. It opens the release
in a browser; AniVault never downloads or launches the installer.

Use a disposable Windows account or VM for upgrade testing. Install an older
build, seed a test database with media paths, progress and LAN settings, then
back it up. Download the new installer from the verified release page and
compare `Get-FileHash -Algorithm SHA256 <installer>` against the published
digest before opening the installer. After upgrade, verify version and retained
state. For a private repo, use an authenticated browser and a release checksum;
anonymous update discovery cannot access private release metadata. Keep the
repository private; a separately authorized public distribution feed is an
option if anonymous discovery is needed.

Also test offline, a missing installer asset, and a newer stable version.
Expect a clean error or a GitHub handoff, never an automatic installation.
Do not publish this candidate as stable until the Windows matrix passes.
