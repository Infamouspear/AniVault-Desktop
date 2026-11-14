# AniVault Desktop 1.6.0

Normal Discover anime cards and details now offer Request Anime. Clicking its
status opens the existing record. Requests do not affect Planning, Favorites,
ownership or watch progress. An exact, unique normal AniList match with a
present indexed episode allows marking a request Available.

The additive desktop_requests table stores anime requests and feedback with
separate workflows. A unique nullable AniList ID prevents duplicate provider
requests without joining similarly named releases. Local media deletion and
rescans do not cascade into request history. The old prototype had no durable
records to migrate. Requests remain desktop-only; there are no new LAN routes
or automatic uploads. Existing public artwork URLs use the desktop cache.

Manual check: request a normal anime in Discover, reopen the request from the
same button, edit its notes/status, restart, and verify persistence. Verify
Planning is unchanged. Create a manual request and a feedback entry and test
search, status filters, sorting, and removal. Keep 1.5.0 as the rollback build.
