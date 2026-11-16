# PR #9 — staging acceptance and release gate

Status: automated CI passed at commit `592d981cb1e0cd1965c265308e30437bf24b5a1a`. This is **not** proof of live provider, OAuth or reverse-proxy compatibility.

## Safe deployment boundary

- Do not merge, deploy, restart or modify production without separate explicit approval.
- Stage only in a separate checkout and the isolated `compose.staging.yaml` project; never use the production `compose.yaml` or production database.
- Before any staging deployment obtain the operator's approval, staging hostname, HTTPS/reverse-proxy access, credentials stored server-side, and a verified reachable image provider endpoint/model. Do not paste secrets in issues or chat.
- Keep `ABUD_IMAGE_PROVIDER` empty until the provider contract is verified.

## Provider contract gate (staging only)

1. Check the **deployed** router version and available image models. For 9Router, inspect `/v1/models/image` and `/v1/models/info?id=<model>` using server-side authorized access. Upstream documentation is not sufficient.
2. Verify image endpoint is HTTPS and accepts Bearer auth, `model`, `prompt`, `n` and `response_format: b64_json`; verify actual synchronous JSON `data[].b64_json` responses. SSE and URL-only outputs are unsupported.
3. Verify supported batch maximum and rejection/timeout behavior with a **non-production** test account and controlled spending. Do not retry ambiguous requests automatically.
4. Configure `ABUD_IMAGE_PROVIDER=openai-compatible-b64`, `ABUD_IMAGE_ENDPOINT`, `ABUD_IMAGE_MODEL`, `ABUD_IMAGE_API_KEY`, `ABUD_IMAGE_MAX_COUNT` only after verification; restrict the staging origin and test accounts.

## Staging smoke test

- Validate `docker compose -f compose.staging.yaml config --quiet` before starting any container; ensure the stack uses only its own named volume and port 127.0.0.1:18000.
- Verify HTTPS OAuth, completed profile, ordinary text chat streaming and no browser-exposed API keys.
- Generate one image and a verified batch; preview, download, reload, regenerate without new provider dispatch, and verify second-user requests return 404.
- Confirm ten successful images consume the ordinary user's rolling 24h quota, with accurate WIB next-slot notice; ordinary text remains available.
- Verify the established Creator identity has no image quota charges across Projects; check private URLs remain isolated.
- Verify failed and ambiguous provider outcomes, recovery procedure, restart durability, Project-only boundaries, mobile layout and filesystem permissions.
- Record evidence for each gate (date, commit, model identifier, result) **without** keys, personal prompts or private images.
- Review backup/restore of SQLite + generated_images, retention/storage capacity, and safe rollback before production release.

## Current evidence and blockers

- GitHub Actions PR run 43936165903: backend, frontend build/tests, and disposable HTTPS Chromium image E2E all passed. Browser E2E uses a local image fixture, not the live provider.
- The actual deployed provider model, staging OAuth, HTTPS proxy, filesystem volume and live quota behavior remain **unverified**.
- No production deployment or merge has been performed by this preparation.

**Release decision: HOLD production until every live staging gate above is verified and a separate explicit deployment authorization is given.**
