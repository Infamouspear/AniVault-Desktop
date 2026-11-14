# Release-candidate gates

V1.0 RC preserves the V0.9.1 presentation and stable media/data backends.

Before a distributable V1.0 can be labeled complete:

- Supply the publisher's registered public AniList client ID with PIN redirect; never a secret/token.
- Build EXE and installer on Windows x64 from the clean staging allowlist.
- Run clean-account installation, guided account linking, native VLC and DPI tests.
- Upgrade over the previous RC and verify state, then uninstall without removing AppData.

No server, mobile/PWA, profiles, live adult sources, cloud sync or other major subsystem is included in this release pass.
