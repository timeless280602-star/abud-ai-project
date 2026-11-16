# Native Web Chat image generation

Direct English/Indonesian imperatives route to an image adapter inside ordinary
Web Chat, before text completion or memory lookup. Examples: `Buatkan gambar
kucing astronot.`, `Generate an image of a futuristic city.`, `Gambarkan naga
merah di atas gunung.`, `Buat dua gambar pemandangan Jepang.`
Questions, quotes, multiline documentation, examples and ambiguous instructions
remain text chat. The conservative deterministic parser intentionally does not
recognize every paraphrase. Image editing, gallery and Discord images are excluded.

## Audit and provider compatibility

Audited `app/auth.py`, `database.py`, `web_chat.py`, `web_projects.py`, existing
9Router callers in `main.py`, React chat/API/choices/organization, Python/browser
tests, Dockerfiles and both Compose configurations. Chat currently calls
`/v1/chat/completions` with `Abud-Combo`; this is not an image model contract.
No deployed router credentials, model inventory or live provider are available in
this workspace. No live image request or paid fallback was made.

Upstream source at commit `1855aa44473e88feac9d3f131b9c0c5fc9706b68` confirms:

- [Image API documentation](https://github.com/decolua/9router/blob/1855aa44473e88feac9d3f131b9c0c5fc9706b68/skills/9router-image/SKILL.md): discover models through `/v1/models/image` and their capabilities through `/v1/models/info?id=...`; image POST uses `/v1/images/generations`.
- [Route](https://github.com/decolua/9router/blob/1855aa44473e88feac9d3f131b9c0c5fc9706b68/src/app/api/v1/images/generations/route.js): a separate image handler, not chat completions.
- Documented request: Bearer authorization, `model`, `prompt`, provider-dependent
  `n`, `response_format: "b64_json"`. Response: `{"data":[{"b64_json":"..."}]}`.
  Providers differ: Gemini/HuggingFace may ignore `n`; Codex can return SSE.
  These differences must be verified against the deployed version/model.

**Deployed compatibility and supported models remain unverified. Generation is
disabled by default.** Upstream documentation is not proof of deployed capability.
The adapter supports only a verified synchronous JSON/base64 image model.
URL-only, binary and SSE model responses are unsupported. Provider URLs are never
fetched, preventing provider-image SSRF. Redirects are rejected. There is no
implicit OpenAI or other paid provider selection.

## Operator configuration (staging first)

Set these server-only variables in the existing `.env` (see `.env.example`):

| Variable | Setup |
| --- | --- |
| `ABUD_IMAGE_PROVIDER` | Empty disables images. Set `openai-compatible-b64` only after verification. |
| `ABUD_IMAGE_ENDPOINT` | Full verified HTTPS image POST URL, including route. No userinfo, query, fragment or redirects. |
| `ABUD_IMAGE_MODEL` | Exact model ID discovered and verified by operator; no default image model. |
| `ABUD_IMAGE_API_KEY` | Provider Bearer key. Never put in React, logs or Git. |
| `ABUD_IMAGE_MAX_COUNT` | Verified per-request maximum, 1–10; default 1. This is a batch-size bound, including for Creator, not a daily limit. |

Verify deployment version, model discovery, auth, `n`, base64 format, rejection
codes and partial response behavior using provider documentation and staging.
Configure the endpoint/model explicitly; do not copy `Abud-Combo` or invent a
route for an older router. The adapter sends an idempotency key, but never assumes
the provider honors it. No automatic retry. HTTP errors are sanitized. Missing or
invalid configuration yields `image_provider_unavailable`; no quota charge.
Only 400/401/403/404/422/429 are treated as definitive provider rejections.
Transport failures, unexpected statuses, invalid outer JSON and dispatch timeouts
are ambiguous and require reconciliation. URLs/payloads/prompts/keys are not logged.

## Creator authorization audit and bypass

The repository already provides a trusted mapping:
`auth._is_creator_identity(db, identity_id)` queries `auth_accounts` for the
established Discord owner ID. Image routing reuses this helper with the identity
returned by `web_chat.identity(request)`. This verifies the server-side hashed
session, expiry, revocation, account disabled state, completed profile and origin.
The creator lookup runs inside the same SQLite transaction as turn admission.

Discord OAuth obtains identity from the authorized `users/@me` provider response;
Google obtains its subject from validated OIDC userinfo. `get_or_create_identity`
uses provider + stable subject, creates a separate identity for each new provider
account, and never auto-links by matching email. Registration/profile routes do
not let a client write OAuth provider IDs. A Google account with a matching email
is not automatically Creator. Creator must sign in to the established linked
owner identity. New sessions of that identity retain the mapping.

No new personal account ID or credentials are introduced. No new allowlist/env
variable is needed because the secure existing mapping is present. Frontend
`is_creator`, username, display name, email, cookies containing role flags and
project instructions never enter the quota decision; extra request fields are
rejected. Existing auth/owner configuration remains unchanged.

Creator jobs use `running` status with **zero reserved slots** and images have **charged=0**. Job
records track idempotency/work state, not Creator quota reservations. Creator
successes, failures and ambiguous jobs never generate quota events or reset times,
and cannot change anyone else's counters. The bypass applies to all conversations
and Projects. Existing text-chat anti-spam, provider batch limits, request size bounds,
authentication and private conversation/Project ownership still apply. Unlimited
images confer no permission to read another identity's images or conversations.

## Rolling quota, concurrency and recovery

Ordinary identities share 10 successful image slots across all conversations and
Projects. UTC epoch timestamps are recorded for each durable, validated image.
Only records with `charged=1 AND created_at > now - 86400` consume successful
slots. Equality at exactly 24 hours expires that image's slot. No midnight reset,
background expiry job or deletion of old images is required.

`BEGIN IMMEDIATE` serializes admission across SQLite connections/workers. Admission
counts successful slots plus all active reservations, then reserves the whole
batch. Partial results charge only durable valid images and release unused slots.
Definitive failures release the whole reservation. History and quota metadata
survive restart. Deleting chats/Projects does not erase successful quota charges or
pending jobs. A conversation lease prevents simultaneous sends to the same chat;
image jobs uniquely bind the original user message. The existing per-minute text
anti-spam limit remains; trusted Creator image requests bypass the count cap, and
exhausted ordinary image requests always reach the structured quota notification. Regenerate replays the result
without another provider call (including failed/ambiguous requests). Submit a new
explicit prompt for a genuinely new image or after a definitive failure.
Frontend submissions also have a UUID request key; repeated keys are rejected.

Ambiguous upstream failures/cancellation keep unused reservations and job status
`unknown`. A process death may leave `reserved`. Both count indefinitely until an
operator reconciles. There is deliberately no automatic timeout-based release:
a timeout cannot prove no images were generated. This conservative behavior can
reduce availability but prevents request flooding/duplicate upstream generations.
The original message cannot be retried into another generation. Text chat remains
available after a completed error response; a process crash may require Regenerate
and operator reconciliation before that chat can continue.

Recovery procedure:

1. Back up SQLite and private images together; inspect the affected job's ID,
   provider idempotency key (same ID), identity, requested/reserved counts and
   provider-side audit state. Never print secrets or private prompts.
2. If provider confirms **no generation occurred**, stop traffic for that identity
   and use an administrative SQLite transaction to set only that job to `failed`,
   `reserved=0`. Keep the job row for deduplication. Never clear all reservations.
3. If generation succeeded, recover/validate artifacts through an operator-reviewed
   import and record each successful image with its actual UTC success timestamp,
   correct ownership and charged flag before releasing outstanding slots. This PR
   does not automate provider-specific recovery or provide a public reconcile API.
4. If outcome cannot be verified, retain the hold. Do not guess a reset time or
   re-dispatch the original prompt. Creator holds always reserve zero slots.

Timeouts: 10s connect, 90s HTTP inactivity, 100s total provider call. Payloads:
maximum 8 MiB per decoded image, 16 million pixels, static PNG/JPEG/WebP only;
Pillow verifies and decodes bytes. Outer response is bounded by requested count.
Disk writes use random UUID filenames, fsync and atomic replace before committing
metadata. Disk/metadata failures fail closed; orphan files remain private.

## Notifications and UX

SSE adds `image_loading`, `images`, `image_quota`, `image_failure` and structured
image `error` codes. Existing text `delta`/`done` framing is preserved. A quota
notice appears only when successful count reaches ten or a new image request
finds all slots occupied. Oversized batches with some availability ask for fewer
images; no persistent quota counter/badge/progress bar is added.

`reset_at` is UTC ISO 8601, calculated from the earliest active successful image
plus 24h. It names the next slot, not a reset of every slot. Pending reservations
are explicitly identified; when no release time can be proven, `reset_at=null`
and the UI asks for administrator confirmation rather than inventing a time.
`imageQuotaMessage` accepts an explicit timezone; there is no existing user timezone
preference, so the UI uses Asia/Jakarta/WIB. Ordinary message timestamps retain
their existing device-timezone behavior. Notifications are emitted once per live
request event, not on history reload/regeneration of a successful image.

Validated artifacts render inside assistant messages with accessible preview and
same-origin authenticated download. Conversation reload obtains artifact metadata
from the authorized history endpoint. No binary data is placed in chat text.

## Storage, retention, migrations and rollback

Images live in `generated_images/` beside `ABUD_DATABASE_PATH`. Existing production
Compose mounts `/opt/abud/data:/app/data`; staging mounts its separate data directory.
Both already persist SQLite and its sibling image directory. UID/GID 10001 needs
write access. Do not expose this directory with a reverse-proxy/static public alias.
Back up the database (including consistent WAL handling) and directory together.
Capacity planning must account for unlimited Creator storage and 8 MiB per image.

Startup adds nullable `web_messages.request_id` and its unique index, plus
`web_image_jobs`, `web_images` and indexes. It does not rewrite memories, feedback,
messages or Project data. Existing rows preserve NULL request IDs. Quota metadata
is separate from message lifetime; deleting a conversation nulls image references
and immediately prevents retrieval, while retaining accounting. Current retention
is indefinite private disk retention (including deleted-chat files and write
orphans); no automated deletion in this PR. An operator may remove unreferenced
files after confirming backups/retention obligations, but must keep quota/job
metadata and all referenced artifacts. Expired quota slots do not delete history.

Rollback: disable the adapter first by clearing `ABUD_IMAGE_PROVIDER`, stop image
traffic and reconcile in-flight jobs. Roll back application/frontend together.
Leave additive tables/column/files in place; old code ignores them, and dropping
them loses quota history/deduplication. Old UI cannot render artifacts. Restoring a
pre-feature DB loses later messages/charges; prefer a forward fix. Do not merge or
deploy automatically. This task makes no production changes.

## Validation and manual smoke test

```sh
ABUD_DATABASE_PATH="$PWD/work/bootstrap.db" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python tests/run_web_chat_e2e.py
.venv/bin/python tests/run_web_chat_e2e.py web_chat_browser.cjs
.venv/bin/python tests/run_web_chat_e2e.py web_chat_choices.cjs
.venv/bin/python tests/run_web_chat_e2e.py web_chat_images.cjs
```

The browser harness uses disposable HTTPS sessions/SQLite/files and deterministic
text/image fixtures, never paid providers or live OAuth. Test dependencies include
Playwright, Chromium and openssl. See PR validation results for executed counts.

On authorized staging after provider verification: sign in with an ordinary
account, generate English/Indonesian single/batch images, preview/download and
reload; verify Project-only boundaries and access rejection in a second account.
Reach ten successes across Projects and confirm one notice with the real next slot
in WIB, then reject another image while text/choices still work. Verify independent
24h expiry against stored UTC records (never alter production clocks/data). Sign in
with the established Creator identity in a new session, generate >10 images across
Projects and confirm no quota notification/reservation/charge; verify another
user's private URLs remain inaccessible. Exercise provider failure, partial result,
regeneration, concurrent tabs, missing config and restart. Check 390px and desktop
layouts, no persistent quota indicator, and durable volume/backup permissions.
Live provider/OAuth/proxy acceptance remains pending operator configuration.

Executed in the disposable development workspace: 92 Python tests passed, 66
frontend tests passed, Vite production build passed, and all four browser commands
above passed. Browser/provider-contract tests use fixtures/MockTransport. Live
provider, live OAuth, production proxy and production deployment were not tested.
