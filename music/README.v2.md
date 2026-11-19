# Music v2 — staging foundation

Jockie-inspired, not Jockie backend reproduction. Existing audio transport and queue are retained.
Default provider order remains soundcloud,youtube,bandcamp. Configure ABUD_MUSIC_PROVIDERS
and optionally ABUD_MUSIC_SEARCH_SOURCE only after source-specific authorization and playback validation.
A Deezer-first order starts with deezer only when an authorized source is registered.
Catalog links do not prove streaming availability; source label is the catalog, not the underlying stream.
Spotify/Apple Music/Tidal are mirroring sources according to LavaSrc, not direct streams.
The optional plugin profile loads pinned artifacts with all new sources disabled; do not deploy it
until isolated compatibility verification. LavaSearch endpoint is not required by this router.
No secrets in Git. Do not procure unofficial keys or cookies, open HTTP/local sources, or use unauthorized public nodes.
ABUD_MUSIC_PLAYBACK_FALLBACK defaults false; opt-in retries at most once for an implicit title request
that fails within five seconds, with strict ISRC or title/artist/duration matching. No playlist, explicit
source, selected picker entry or direct link substitution. Matching is heuristic, not rights validation.
Acceptance: isolated offline tests, plugin boot and /v4/info, authorized catalog lookup
(Deezer reference 585433102), actual Discord audio playback, nonce/queue correctness, full CI and rollback plan.
No production change is made by this PR.
