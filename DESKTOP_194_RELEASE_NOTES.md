# AniVault Desktop 1.9.4 — Local identity and Picture Drama fixes

Status: local candidate, not published. Version 1.9.3 remains the stable rollback release.

## Confirmed causes and changes

The database paths were intact. The organization layer collapsed different local records by AniList ID, then pointed both local aliases at the first presentation. Local records now retain independent identities in Home, search, favorites, collections, card navigation and playback. Remote metadata IDs remain aliases only when unambiguous. An online title with multiple possible local sources no longer chooses an arbitrary folder. New status and collection edits on duplicate matches use local keys; historical remote choices remain stored rather than being guessed away.

Picture Drama and equivalent picture/visual-drama terminology now produce a dedicated release hint. Explicit drama terminology must agree with candidate titles/synonyms, and regular TV candidates cannot satisfy that constraint. Special-format searches use the existing shared scheduler and persistent caches, with precise and shorter franchise queries. Ordinary TV searches also reject unrequested picture/visual dramas. R2-style sequel identifiers are recognized as season evidence.

An actual API verification retrieved IDs 5163 and 132317 and selected 5163 for R2 Picture Drama with the existing confidence policy, using two requests. No confidence threshold was lowered. Suspicious shared AniList associations are flagged in Scanner Review. Entering a numeric AniList ID or anime URL in its search field retrieves the scoped identity for explicit confirmation against the selected local source.

Fractional source identifiers are stored in the additive `media.episode_label` TEXT column. The original digits, including zero and trailing zeros, remain exact. `Decimal` comparison orders the labels without binary floating-point conversion. `media.episode` remains an integer playback/progress ordinal for fractional collections; ordinary integer episode numbering remains compatible. Labels appear in detail lists, player titles, In Focus previews, scanner diagnostics and the LAN episode response. Distinct files are retained even when their numeric labels compare equally. Automatic old classifications are refreshed on rescan; explicit manual classification overrides are preserved.

## Actual library repair

A verified SQLite backup was created before repairing the installed library. The repair preserved media IDs, watched flags, watch timestamps, resume positions, favorite/rating fields and independent source paths.

- Local 149: AniList 2904, 25 main episodes; correct regular R2 source retained.
- Local 174: manually confirmed AniList 1953 and its lock preserved; all nine Picture Drama files are playable with original Stage labels.
- Local 175: independently verified AniList 5163 applied; all nine files are playable with original Turn labels.
- Local 177: AniList 132317 retained; Last Moratorium remains a separate one-file release, with source label 12.06.

The nine Season 1 labels are 0.25, 3.25, 4.33, 6.75, 8.75, 9.33, 9.75, 22.25 and 23.95. The nine R2 labels are 0.56, 0.923, 7.19, 9.34, 12.31, 12.59, 19.02, 22.05 and 25.01.

Migration adds a column rather than rebuilding the media table. Existing populated libraries receive a pre-episode-identifiers backup before that migration, and scanning retains its normal pre-scan backup. The installed repair additionally has a named before-geass-identity194 backup. No source media file was written, renamed or deleted.

## Validation and limits

Tests cover exact local card navigation, Open Folder, direct-ID confirmation, independent statuses and memberships, correct special retrieval, false TV match rejection, decimal ordering, nine-file rescans, preserved watch/resume state and normal playback rules. A real database copy was verified before the installed repair. Final regression logs, application captures and packaged-build checks accompany the delivery.

Old shared remote statuses/memberships cannot always be attributed to one local source reliably; they are preserved for review. A manually overridden classification is not silently changed. Uncertain metadata remains reviewable. Installing this build is necessary for the new label display and library-wide identity behavior; older builds do not understand the added label field.

The candidate is not automatically installed or published. Update publication is a separate step, and 1.9.3 remains available for rollback.
