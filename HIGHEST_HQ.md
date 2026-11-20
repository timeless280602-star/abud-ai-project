# The Highest HQ — foundation deployment

This is the initial feature branch, not a production deployment. Do not replace a newer VPS checkout with the older main branch. Review and merge/rebase the change against the branch actually running on the VPS. Back up the ABUD data directory before rebuilding.

- Public entrance: https://abud.web.id/highest/
- No ABUD/Discord identity is accepted by HQ.
- New signups are community only. Admin review with rank and position is mandatory for internal access.
- Admin role is distinct from IC rank. An admin can manage membership without becoming an approved IC member.
- Original user-supplied logo must be copied to app/highest_web/logo.png before image build.
- Database: /app/data/highest.db by default, persisted by existing ABUD data volume.
- Set HIGHEST_ORIGIN=https://abud.web.id (or ensure ABUD_BASE_URL matches).
- Set HIGHEST_YOUTUBE_API_KEY and HIGHEST_LIVE_INTERVAL (default 3600 seconds). YouTube search uses 100 quota units per check per channel, so configure interval/quotas for roster size.
- TikTok requires a real HTTPS provider endpoint and bearer token: HIGHEST_TIKTOK_STATUS_URL and HIGHEST_TIKTOK_STATUS_TOKEN. Adapter expects GET username query parameter and JSON live boolean. No provider is included or verified. Failed checks show unavailable.
- After creating an HQ account, VPS operator grants the first HQ admin using:
  docker exec abud-api python -c "from app.highest import bootstrap_admin; bootstrap_admin('your_username')"
- Rebuild only the API after merging, installing the original logo, and configuring environment:
  docker compose up -d --build --no-deps abud-api
- Smoke-test direct HQ login, ABUD homepage button, pending membership 403, approval, revocation, rank ordering and live status. Phase 2 includes rank-scoped treasury, inventory/vault, completed crafting, IC case files and audit. Admin must grant each rank explicit module permission. Treasury uses two different members for submission and review. Inventory and crafting are manual IC ledger records, not synced to the game server. Advanced community, evidence attachments, crafting approvals and remaining planned modules are not implemented.

- Rank All Access uses a wildcard grant for all registered internal operations, including future modules that use the same permission guard. Disable it to restore the existing custom module permissions. It never grants website administration or bypasses membership approval or the no-self-review rule.

- Phase 3 initial community features: moderated moments and POVs, creator verification, creator studio, lore/character/recap wiki, moderated text feed, clip likes/bookmarks, streamer follow and all-time clip leaderboard. Spoiler markers are UI disclosure, not authorization. No external analytics, actual live notifications, comments, uploads or creator channel ownership checks yet. Admin verifies creator identity manually.
