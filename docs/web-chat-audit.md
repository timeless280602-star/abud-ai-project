# Web chat integration audit — 2026-11-16

## Source of truth

Inspected remote branches and PRs #1, #2, #3, #4 and #5. `main` remains
`09d8365`; `dev` is `f8f2e10477a342e7f467f322e59d11ad236a864e`.
PR #3 originally pointed at `3b85f4c` and was five commits ahead/four behind dev.
It had no conversation comments or PR-triggered Actions runs returned by GitHub.
Merged dev into the existing feature branch (merge commit `2e2e75f`), retaining
both chat styles and new duplicate-review/archive styles at the only conflict.
Reviewed the auto-merged dashboard permissions, routes and startup integration.
No changes to main/dev, production data, Discord bot startup or live deployment.

## Findings fixed

- Latest archive semantics rejected explicit saves of archived text, aborting web
  inference. Web chat now emits `memory_not_saved`, keeps the archive intact and
  continues inference with an accurate memory-action status. Oversized explicit
  saves also report their 1000-character limit instead of silently doing nothing.
- A stale worker could replace an answer or clear a newer worker's response lease
  after its lease expired. Completion now checks the exact admitted lease inside
  a write transaction; cleanup only clears that lease. Thread deletion serializes
  its lease check and delete with inference admission.
- The composer allowed sending while thread history was loading. Sending and
  regeneration now wait for that history; stale load errors cannot override the
  current thread's error state.
- Dependency scanning found advisories in the environment's old pip installation.
  The API image now upgrades build/install tooling to pip >=26.2,<27 before
  installing application dependencies. No runtime dependency was added.

## Smart Memory compatibility

Ranked retrieval searches the entire authorized personal scope before limiting,
including records older than 100 newer records. Web personal ownership remains
`web:<identity UUID>`; Discord personal and all guild records are excluded.
Only active global knowledge is shared read-only, following existing application
semantics; web callers cannot supply scope/owner/permission fields or global writes.
Archive/restore, exact duplicate saves and metadata preservation use dev's shared
helpers. Optional semantic duplicate review remains in the authorized dashboard;
web saves do not invoke AI review or automatically merge/restore records.

Revision is the existing monotonic counter, not a content snapshot history.
PR #2 explicitly did not implement historical content snapshots. This integration
preserves that contract and does not claim a new history feature.

## Verification performed

All databases, TLS keys and sessions were disposable. OAuth/provider traffic was
mocked. No Discord bot was imported or started.

| Check | Result |
| --- | --- |
| Python 3.12 unittest discovery | 49 passed |
| Python 3.11 unittest discovery in built non-root image, network disabled | 49 passed |
| Authentication, CSRF, ownership, cross-user isolation | Passed in HTTP suite and local HTTPS browser test |
| Streaming, provider protocol/errors, regeneration, cancellation/lease cleanup | Passed; stale completion cannot replace existing answer or clear newer lease |
| Smart Memory ranking, metadata/revision, duplicates, archives, migrations | Passed existing regressions plus web integration cases |
| Frontend `npm ci` and production build | Passed |
| Mock-HTTP Chromium UI | Passed CRUD, Markdown/highlighting, regeneration, loading guard and archive notice |
| Responsive Chromium layouts | Passed overflow/composer checks at 320/390/768/1280px |
| Real HTTPS FastAPI + built React + real sessions/SQLite | Passed persistence, isolation, CSRF, streaming/error handling, regeneration, mobile and deletion |
| Docker image build | Passed using temporary Dockerfile with CA BuildKit secret; TLS verified |
| Isolated Compose staging | Passed health/startup, UID 10001, fresh named volume, web/archive schema, built assets and unauthenticated 401 |
| npm audit | No reported vulnerabilities |
| pip-audit after tooling upgrade / pip check | No known vulnerabilities / no broken requirements |
| `git diff --check` | Passed |

The unmodified Docker build initially failed because the environment's proxy CA
was absent inside the build. The successful build used a temporary Dockerfile
outside the repository mounting `/etc/ssl/certs/ca-certificates.crt` as a secret
only during npm/pip steps. No CA was committed or copied into image layers, and
TLS verification was never disabled. npm and audit caches were placed under
`/workspace/work` because the environment's home directory is read-only.

The Python 3.11 check streamed the tests into the disposable container's `/tmp`
(the initial read-only test bind mount was inaccessible to UID 10001).
Staging used the standalone Compose file with a distinct audit project name and
an image-only override. Only the API was started, bound to loopback port 18000,
with placeholder configuration and a newly created project volume. Its container,
network and test volume were removed after validation. No production mounts,
external 9router network, production container names or bot were used.

## Remaining release gates and limits

Real Google OAuth/profile setup, live 9router behavior and streaming through the
actual staging HTTPS proxy still require real staging credentials/hostname.
The local HTTPS check simulates provider account creation and inference only;
it does not establish live provider availability or proxy latency. No OS image
vulnerability scanner was run. No automated remote CI result is claimed.

Both OAuth providers remain required at startup, even for Google-only users.
Web memory lifecycle UI, autosave and Discord/web account linking remain outside
this feature. Conversation deletion does not erase separately saved memories.
SQLite scale/retention and public abuse controls still require operational review
before public scale. See `web-ai-chat.md` for limits and `../staging/README.md`
for deployment acceptance/rollback. Live deployment has not been performed.
