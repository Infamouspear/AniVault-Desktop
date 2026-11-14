# AniVault 1.0.0-rc.1 verification

## Status

Application source and clean Windows build definitions are prepared. **No Windows EXE/installer was compiled or executed in this environment.** This remains RC, not final V1.0.

Release blockers:

- Registered public AniList client ID is not supplied. Guided PIN linking is prepared; build intentionally fails rather than silently shipping unconfigured login. Only the numeric public ID is needed, never a secret/token.
- Windows x64 build and clean-account/upgrade/uninstall/native-playback acceptance remain outstanding.

## Implemented

- Existing pinned/delayed Focus View preserved; compact continuation controls and double-click detail routes unchanged.
- Pinned Lucide 0.468.0 SVG icons and upstream license; active accent rendering at device pixel ratio.
- Normal sidebar art independent of empty-state/hero art. Dedicated image/text/action layout retains existing responsive shrinking.
- Provided Restricted banner restored byte-for-byte. Entire foreground face/body preserved at hero height; scenic-only background from the same asset fills wide space without duplicating the figure. Transparent cutout stays in sidebar.
- Splash On/Off and 1/2.75/5s minimum, readiness gating and a precise Qt timer; no blocking sleep/progress bar.
- Blank first-run root inputs, optional manga/account setup, read-only initial scanning when Start is selected. Existing databases skip new-install setup.
- Guided browser authorization + PIN/code entry. Linked credentials are not echoed in Settings; validation writes user-local DB only. Existing list refresh/disconnect/sync remain.
- About/diagnostic info, log folder, VLC architecture check, disposable artwork-cache refresh.
- Historical AppData retained. Pre-migration quick-check + SQLite backup includes committed WAL state. Corrupt/unrecognized DB fails without recreation. Non-destructive release/schema fingerprint marker.
- Clean staged code/assets allowlist, SHA256 manifest, post-bundle private-state rejection, x64/no-console PyInstaller definition, fixed-ID per-user Inno installer, optional desktop/Start-menu icons, no associations and no AppData uninstall deletion.
- No live source, WebEngine, snapshot jobs or new subsystem added. Existing external bookmarks and manual retired-cache cleanup remain useful, user-triggered paths.

## Automated and visual evidence

- Full regression suite: 333 passed in 104.33 seconds (final clean run).
- New safety/runtime coverage: corruption is retained; backup contains synthetic committed state; release marker avoids repeated backup; empty setup/skip, splash minimum/Off/readiness and settings persistence, sidebar icons/art coexistence, nonoverlapping empty states, guided authorization URL, no credential echo, explicit staging excludes deliberately planted personal files, secret/blank public config rejected, private-state bundle audit rejects DBs.
- Qt offscreen 125/150/200% scaling: 4 relevant layout/icon tests passed at each factor. This is not native Windows DPI validation.
- Rendered and inspected first-run, empty search plus sidebar mascot, Restricted Home and wide 2560×1440 hero. No user database/media was used in these visual checks.
- Stable backends byte-identical to V0.9.1: database, scanner, integrated player, playback, local reader, manga library, AniList integration, recommendations, Downloads.

## Distribution safety

Source archive includes application, approved art, tests with synthetic data, documentation and packaging definitions. It contains no developer DB/settings/tokens/logs/cache/library/download state. Installer inputs are narrower: code + explicit approved assets and dependency runtime/license metadata only. The source archive itself is not an installer.

No user-owned files were deleted and no source media was modified. No real user DB/media was supplied, so real-state upgrade and native media acceptance remain manual gates.

## Dependencies / limits

Desktop VLC remains external; compatible architecture discovery and external fallback are retained. PDF uses pypdfium2. CBR uses rarfile and may require a local unrar/unar/7-Zip backend. Existing reader/player integration was regression-tested in synthetic/offscreen tests, not native Windows decoding.

Publisher OAuth registration must use AniList's public-client implicit/PIN flow; no client secret is bundled. Guided live account authorization cannot be validated until the public ID is configured. No Windows signing certificate was supplied; signing/SmartScreen trust is not claimed.

References: https://docs.anilist.co/guide/auth/ ; https://pyinstaller.org/en/stable/usage.html ; https://jrsoftware.org/ishelp/ ; bundled Lucide icon license.
