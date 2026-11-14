# AniVault Desktop 1.5.0

Personal ratings are private nullable integer half-points on existing anime and
manga records; 17 means 8.5, and NULL means Unrated. The additive SQLite migration
leaves existing rows intact. The scanner's existing upserts keep ratings for
retained identities. Removing a title record entirely also removes its rating.
AniList scores, watch status, and LAN API projections stay separate.

Status percentages use normal local titles as the denominator. The completion
ring uses watched / present indexed episodes; completed titles use assigned
status. Genre charts count distinct local anime per genre and can overlap.
Rating averages exclude Unrated; rating ties sort by title and stable key.
Genre averages show their sample counts. Historical activity is unavailable.

Manual checks: rate an anime in In Focus, open its details and change the score;
return to Home and verify the score. Repeat with a manga title, reopen the app,
then clear either score. Open Statistics and try a genre and Browse unrated anime.
Run with the sidebar expanded and collapsed. Keep 1.4.2 as the rollback build.
