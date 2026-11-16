# Isolated web-chat staging (prepared, not deployed)

`compose.staging.yaml` is a **standalone** stack with one API service, a new named
volume, and loopback-only port 18000. It does not include a Discord bot, production
bind mounts, production container names or production ports. Do not combine it
with `compose.yaml`, copy production SQLite into it, or attach production data.
The image prepares `/app/data` for the existing non-root UID so the new volume is
writable without a privileged initialization container. Frontend builds use the
committed lockfile through `npm ci`.

Before deployment, choose a staging hostname/server, configure HTTPS and private
access at the reverse proxy, and review the commands below. The application is
**not deployed** by committing this directory. Live server changes require the
user's explicit deployment approval.

## Server configuration

1. Use a separate checkout of `feature/web-ai-chat`. Copy `staging/.env.example`
   to repository-root `.env.staging`, set mode 600, and populate it on the server.
   Keep credentials out of chat, Git and screenshots. Generate distinct staging
   session/internal secrets; do not copy production sessions or data.
2. Set `ABUD_BASE_URL` to the exact HTTPS origin without a trailing slash.
   Register Google OAuth redirect URI `<origin>/auth/google/callback` and Discord
   OAuth redirect URI `<origin>/auth/discord/callback`. Google-only testers need
   no Discord account; the existing auth module still needs Discord OAuth client
   configuration at startup. A Discord **bot token is not needed**.
3. Set a container-reachable staging `NINE_ROUTER_BASE_URL`, key and model. Docker
   localhost is the container itself. This stack intentionally does not join the
   production 9router network. Review any required network attachment separately
   once the target infrastructure is known.
4. Configure the staging HTTPS reverse proxy using `nginx.conf.example` as a
   location snippet. Keep staging restricted to testers. Validate Nginx config
   before reloading. If a network restriction is used, permit the testers' OAuth
   return requests from their browser. Do not enable proxy buffering for SSE.

## Reviewable commands (run only after deployment approval)

From the staging checkout root, with Docker Compose v2:

```sh
# Validation only; does not start containers. --quiet avoids printing secrets.
docker compose -f compose.staging.yaml config --quiet

# Build and start only the isolated staging API.
docker compose -f compose.staging.yaml up -d --build api

docker compose -f compose.staging.yaml ps
curl --fail http://127.0.0.1:18000/health
```

Use `docker compose -f compose.staging.yaml` consistently. Running plain
`docker compose up` would select the existing production-bound stack.
The named volume is scoped to project `abud-web-chat-staging`. The image tag is
also staging-specific. No host data directories are mounted. A different server
or a port collision requires reviewing the stack before use.

## Acceptance checks with real services

- HTTPS login page loads; Google login returns to the staging origin. Complete
  the existing username/password profile setup. AI Chat opens without Discord.
- Create a conversation and send a prompt. Text arrives incrementally through the
  actual reverse proxy and 9router. Inspect browser Network for SSE and confirm no
  API credential is present in browser requests or responses.
- Reload and reopen the thread. Rename, copy an answer, regenerate and delete it.
- Log in as a second Google tester. The first tester's threads are absent; a
  request for a known first-tester thread ID returns 404.
- Ask to remember a harmless preference; observe personal-memory confirmation.
  Guild data must be absent. Do not test with personal secrets or production data.
- Check 390px mobile layout, highlighted code blocks and Markdown links. Confirm
  a simulated router outage produces a generic retryable error, then restore the
  staging-only router and retry. Never interrupt the production router for a test.
- Record actual sign-in/streaming/latency results. Local mocks passing does not
  establish these live-service results.

## Stop / rollback

```sh
# Stops staging only and preserves its test database for inspection.
docker compose -f compose.staging.yaml down
```

Do not add `--volumes` unless intentional deletion of staging test data has been
approved. To roll back code, use the previously reviewed staging image/commit and
restart this same stack. The initial web schema is additive; do not remove tables
from a live database manually. No production rollback is needed for this staging
stack. Merge and production release remain separate approval steps.

## Preparation validation results

- `docker compose -f compose.staging.yaml config --quiet` passed using the
  placeholder example environment. No real credentials were supplied.
- Effective Compose configuration was checked: only `api`, loopback port 18000,
  one project-scoped named volume and no host bind mounts.
- `.env.staging` is excluded by Git; the placeholder example is tracked.
- A local image build was attempted but **did not complete**: the Docker build
  environment rejected the package-index TLS chain with
  `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`.
  No TLS verification bypass was applied. The target build host must trust its
  configured package proxy/CA, then rerun the build. This is not a passing image
  build result; image startup and live staging remain unverified.
