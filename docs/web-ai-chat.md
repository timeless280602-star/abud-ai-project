# Web AI Chat MVP

## Repository audit and implementation

Based on `dev` commit `2360e09ac9d5d22595e0f63af2813656b75110b1` (including
Smart Memory ranked search and the newly merged source/revision metadata).
The initial audit started at `9cce2aa`; the feature was rebased when dev advanced.

The repository consists of a single FastAPI service (`app/main.py`), SQLite
helpers (`app/database.py`), session/OAuth/password/profile authentication
(`app/auth.py`), a React/Vite dashboard (`frontend/src/main.jsx`, `style.css`),
Discord gateway/bot (`app/bot.py`), memory/calculator tools, a read-only skill
engine, Docker/Compose definitions, and unittest suites. No AGENTS.md was present.

Existing Google OAuth creates an independent UUID identity using provider ID,
never automatically links accounts by email, and issues hashed server-side
sessions with Secure/HttpOnly cookies. Completed Google-only identities previously
hit the dashboard permission denial screen. The web chat is available after the
existing profile setup without changing administrative dashboard permissions.
Existing navigation modules, login/landing and profile UI remain available.

Discord `/chat` is internal-key authenticated and constructs Discord-specific
instructions, trusts bot-supplied IDs and permissions, and stores history by
Discord context. Calling it directly from a browser would cross trust boundaries.
`app/web_chat.py` therefore adds a session-authenticated router while reusing the
Abud system prompt, SQLite connection helper, memory functions, Google login,
9router environment settings and existing FastAPI application. It does not import
or start the Discord bot. Existing internal APIs, bot, tools and dashboard memory
permission checks remain unchanged.

The existing conversations table is a flat Discord message log. New additive
`web_conversations`, `web_messages`, and `web_chat_limits` tables support named
threads without migrating or mixing Discord history. Startup creates these tables
idempotently after the existing database initialization. Production data was never
opened or modified during development.

## Endpoints

All paths begin with `/web/chat/conversations`:

| Method/path | Behavior |
| --- | --- |
| GET / | List the current identity's threads, newest activity first |
| POST / | Create; optional `title` (1–100 characters) |
| GET /{id} | Retrieve owned thread and ordered messages |
| PATCH /{id} | Rename with `title` |
| DELETE /{id} | Delete owned thread and cascade its messages |
| POST /{id}/messages | Send `message` or `{ "regenerate": true }` |

The streaming endpoint returns SSE `data:` JSON events: `delta` with `text`,
`memory_saved`, `done`, or a generic `error`. Validation and permission failures
before streaming use standard HTTP errors. The frontend consumes POST streams
with fetch, supports Markdown/highlighted code, message copying, regeneration,
loading/error states, and responsive conversation navigation. Markdown renders
without raw HTML. Chat and Markdown/highlighting are loaded as a separate chunk.
The frontend lockfile records the three new rendering dependencies and transitives.

## Security and memory

- Every endpoint resolves the existing session; revoked, expired, disabled or
  missing sessions fail. Profile completion is required. No dashboard admin grant
  or Discord account is required.
- All mutations enforce the existing exact `ABUD_BASE_URL` Origin check.
- Every operation checks thread ownership; inaccessible IDs return 404. Request
  schemas reject unknown fields, including user IDs, guild IDs and permissions.
- SQL uses bound parameters. Foreign keys cascade thread deletion.
- Personal memory uses the server-derived namespace `web:<identity UUID>`.
  Existing Smart Memory search ranks only that owner. Explicit Indonesian save
  requests and English `remember [that] ...` requests (up to 1000 characters) use
  the existing save helper with source `direct`. Saving precedes model inference;
  the UI receives confirmation even if inference subsequently fails. Duplicate
  saves use existing deduplication. Regeneration does not repeat memory writes.
- Read-only global knowledge is supplied as in Discord chat. Guild memories and
  Discord personal memories are never supplied. No guild/global writes, account
  linking, privileged tools, shell, or internal API credentials are exposed.
- Memory is reference data; the model has no tools and cannot authorize actions.
- Ten accepted inference requests per identity per fixed 60-second window,
  persisted in SQLite; rejected/failed inference attempts count too. A transaction
  serializes admission. Each thread has a crash-expiring 150-second response lease.
- HTTP connect timeout 10 seconds, read timeout 30 seconds, overall inference
  timeout 120 seconds; assistant output capped at 60,000 characters / 4096 tokens.
  Maximum 200 conversations and 400 persisted messages per thread. Model context
  uses the most recent 30 messages, five matching personal memories and 20 global
  memories (memory text capped at 12,000 characters).
- User messages persist before inference. Partial failed responses are not saved;
  retry via Regenerate. A failed regeneration preserves the previous answer.
  Successful replacement is transactional. Provider errors/keys are not sent to
  the browser. Cancellation releases the lease, and a worker crash expires it.

## Validation

Run from repository root with a disposable import-time database path:

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
cd frontend
npm ci
npm run build
```

Actual results on Python 3.12: **24 tests passed**, including the 19 existing
memory/tool/metadata tests. New tests exercise real Google-provider identities and
session cookies against isolated SQLite, thread CRUD, cross-user denial, CSRF,
revoked sessions, input spoofing, unchanged internal-key protection, persisted SSE
history, regeneration, memory isolation/source, generic provider failure, pending
turn retries, busy leases, rate limits and OpenAI SSE parsing/incomplete streams.
OAuth and provider network traffic are mocked; TestClient never starts a bot.
Existing Authlib/Starlette/FastAPI deprecation warnings remain.

`npm run build` and `git diff --check` passed. Build chunks are approximately
227 KB dashboard JS and 305 KB chat JS before gzip, with no chunk-size warning.
Headless Chromium/Playwright checked Google-only navigation, create/send,
Markdown/highlighted code, regeneration, rename/delete, 390px viewport overflow,
and no JavaScript exceptions, using mocked HTTP responses.

The browser check is retained as `tests/web_chat_browser.cjs`; run Vite on port
5173, then `node tests/web_chat_browser.cjs` in an environment with Playwright and
Chromium at `/usr/bin/chromium`. Playwright is a test tool, not a runtime dependency.

## Deployment requirements and limitations

No deployment, merge, production SQLite operation, or second Discord bot was
performed. Deploy only after review and explicit approval using the existing
release process; do not run this production-bound Compose file for development.

Before rollout, back up the deployment database, configure the existing HTTPS
`ABUD_BASE_URL`, OAuth callbacks/session secret and server-side `NINE_ROUTER_*`
settings, build the frontend, and start the API to apply additive schema creation.
The existing auth module still requires both Google and Discord OAuth configuration
at startup, even though web users never need Discord accounts. Keep those existing
server settings. Ensure the reverse proxy streams SSE without buffering and allows
requests longer than 120 seconds. Use Python 3.11+ (existing Docker target: 3.11).
Verify real Google sign-in, profile completion and 9router token streaming in
staging; no live OAuth, live AI, image build or production deployment was tested.

The MVP does not implement automatic memory extraction, web memory editing/listing/
deletion UI, or Discord/web identity linking. Deleting a conversation does not
forget saved personal memory; memory lifecycle controls are follow-up work.
Only explicit saves are supported, and model text can still be inaccurate.
SQLite admission/leases work across workers sharing one database; horizontal
instances with separate databases require a shared store. Account/IP-wide abuse
controls and retention policies need operational configuration before public scale.
Automated tests do not establish live proxy latency, visual completeness on every
device, or OAuth-provider availability.
