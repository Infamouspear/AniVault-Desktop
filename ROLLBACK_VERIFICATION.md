# Rollback verification

## Executed

- Full retained regression suite plus rollback tests: **145 passed**.
- Qt runtime tests run on Linux using PySide6's offscreen platform.
- Python compilation succeeds.
- Existing retained modules other than the UI entry-point module are byte-for-byte
  unchanged, including database/migrations, scanner/parser, AniList, metadata,
  integrated player, external playback, VLC loading and generic reader.

## Rollback runtime checks

- Start a window with no configured index, and with a deliberately invalid old
  index file. Normal navigation never reads/changes the retired file.
- Enter Restricted Home: no Doujin action, import/download buttons or live source
  client/provider registration. WebEngine modules are not imported.
- Open Restricted Saved and click an existing external card: cached/local detail
  appears without cover lookup or provider requests.
- Open Source dispatches the saved URL to the standard browser action (intercepted
  during tests; no external site was opened).
- Set Reading, add to a Restricted Collection, reopen the database, and confirm
  Saved identity/URL metadata, status, membership and reading progress/history.
- Remove from Saved: status and Collection membership remain; Collection detail
  still shows the entry.
- Normal Saved does not show Restricted external cards.
- Lock: return to normal theme/navigation, clear Restricted history, block stale
  source links/mutations/detail actions. Unlock restores the preserved entry.
- Unknown source IDs and sparse legacy records remain displayable.
- Locally cached cover files display without network fetch.
- Repeated Restricted Home entry reuses its cached page.
- Generic reader still displays local image pages through a source-neutral local
  page adapter. It is not reachable through the active external bookmark UI.

## Optional cleanup checks

- Verification alone does not alter the index.
- A verified metadata-only index is moved, never deleted, after explicit request.
- Main database and index status sidecar stay unchanged.
- Unknown tables/user-state fields, changed files or active SQLite sidecars are
  rejected. The file is left untouched.
- Nothing scans/verifies/quarantines the index on startup or page entry.

## Remaining platform verification

Actual Windows desktop browser launching and live VLC rendering were not tested
here. Their backend modules are unchanged and existing playback tests pass.
AniList network endpoints were mocked in UI tests; real account/API behavior is
not claimed as newly verified. The installed user database and 1.22 GB index
were not modified or available for an end-to-end Windows test.
