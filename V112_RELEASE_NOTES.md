# AniVault V1.1.2 regression fixes (1.1.2-rc.1)

This focused patch starts from the supplied complete AniVault-V1.1.1-source.zip,
SHA-256 `0ee5be9f88ab73b72538032ab824923bc08fd886ce46691fcd889e2767fbf702`.
No V1.0 fallback or reimplementation was used. See V112_VERIFICATION.md for the
Windows suite results and the disposition of all fourteen supplied failures.

## Application changes

- Reader canvas/viewport keyboard events reach the existing navigation and
  fullscreen actions even when scroll focus or a tool window prevents shortcut
  activation. Shortcut override handling prevents duplicate dispatch; shutdown
  still disables input. Direction, saved position and Restricted scope remain intact.
- Native Windows windowed video retains pointer polling while visible. Hiding
  stops overlay/pointer/preview and deferred-click timers; showing restores the
  appropriate overlay. Closing invokes the existing guarded, asynchronous VLC
  teardown and cancels pending clicks.
- Both video input surfaces respect the Windows double-click interval. The
  release following a double-click cannot enqueue a playback toggle. Qt surface
  clicks also work on Windows when the native input overlay is not receiving input.
- Airing card metadata keeps the episode number on a second line instead of
  destructively eliding it. Adult/library indicators stay together. The fixed card
  size is preserved by moving six pixels from the note slot to the metadata slot.

## Test and environment corrections

Temporary SQLite fixture connections are explicitly closed before Windows file
removal. Application scanner connections already close in their owning worker;
callers retain ownership of the shared Database. No database schema changed.
Basename assertions now use pathlib instead of assuming slash separators.
The fake VLC player implements the Windows/macOS detach methods as well as X11;
actual teardown logging is still asserted, including absence of teardown errors.
The fullscreen expectation accounts for Windows windowed overlay polling and
adds a shutdown timer assertion. Headless Windows tests load installed Segoe UI
only when offscreen Qt discovers zero fonts; the original layout assertions remain.

## Scope and delivery

LAN server, pairing/session isolation, media streaming, Restricted classification
and progress synchronization source are unchanged. The complete regression suite
covers their existing behavior. This ZIP contains source, tests, assets and build
scripts; it is not a newly compiled installer. Real-device playback, GPU/native VLC
rendering and second-device acceptance remain manual acceptance checks. Version
stays explicitly release-candidate rather than claiming those checks occurred.
