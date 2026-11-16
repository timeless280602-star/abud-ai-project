# Web Chat conversation quality and streaming audit

Repository: `timeless280602-star/abud-ai-project`.
Base: latest `origin/dev`, verified as `5389fce3f96430bcf21894ed51c675b00a115bbb`.
Branch: `fix/web-chat-conversation-quality`.

## Confirmed findings

- Web Chat imported the complete Discord-oriented `SYSTEM_PROMPT`. Its memory-tool and automatic-saving instructions conflicted with the Web Chat restriction to explicit server-side personal saves. The new Web Chat prompt describes only the capabilities available in this path. Discord retains its existing prompt, tool permissions, mentions, guild memory and internal authentication.
- Personal/global reference data and raw response-feedback excerpts were inserted as system messages. Feedback explicitly encouraged using good examples as style guidance; examples therefore offered a path for repeating unwanted formatting. They are now lower-trust user reference messages with system-level interpretation rules. The current user request remains last, after the bounded conversation history.
- Project instructions already used a user message with scope restrictions. That ordering and authorization remain; the system prompt now explicitly describes project preferences as subordinate to security, identity and memory boundaries.
- Web Chat does not call `get_relevant_skills()` or the shared `is_internal_reply()`. The latter rejects JSON/list openings and broad technical keywords without regard to intent. Reusing it would reject legitimate code and technical discussion. No keyword blacklist, post-hoc rewriting, buffered validation or retry call was added.
- Conversation history remains the last 30 messages from the owned conversation. Regenerate excludes the replaced assistant message, retains the user turn, and replaces the previous answer only on successful persistence.
- Streaming failures previously lost exception diagnostics. The parser assumed each data line was a complete JSON event, lacked explicit shape validation, and accepted any finish reason, including token-limit truncation, as success.
- The frontend already reloaded authoritative history after streaming. This removes failed partials or restores the original answer after failed regeneration. When that reload also fails, temporary partials previously appeared without an incomplete label and could enable another Send. They are now labeled incomplete, cannot be rated, and require Regenerate. Readers are cancelled/released on exit.

## Hypotheses and limits

These code findings explain conflicting instructions and opportunities for style contamination; they do not prove which input caused the reported production responses. No production prompts, memories, router configuration or logs were inspected. Model defaults, upstream prompts or a particular memory/feedback example may also contribute. The previously observed 404/502 provider failures can explain interrupted generations, not robotic conversation by themselves.

Deterministic tests verify composition, boundaries and streaming behavior, not the wording of a live model. Before release, manually evaluate casual Indonesian, English, creative roles, multi-turn brainstorming, professional advice and coding against the configured gateway. Prompt guidance cannot guarantee that every upstream model obeys every style instruction. No legitimate technical output is silently removed, and no additional generation calls are made.

## Implementation

`app/web_chat.py` now owns a dedicated prompt and a small composition function. It preserves Bos Bara attribution and both official social links, matches the user's language/tone and requested perspective, encourages useful substantive collaboration, and discourages forced workflows, unrequested code and internal process metadata while allowing them as requested subject matter. Memory-action status comes from trusted server logic rather than reference text.

SSE frames support comments, CRLF and multi-line data. Invalid JSON/shapes, incomplete frames/streams, empty answers and non-success finish reasons fail without persisting an assistant answer. Sanitized logs contain stage, category, exception class, HTTP status, whether partial output exists, and elapsed milliseconds. They do not include exception messages, tracebacks, headers, URLs, credentials, prompts, reference data or conversation text. Categories distinguish upstream HTTP, upstream timeout, transport/connection, stream error, malformed stream, total generation timeout and internal failure.

The 120-second generation deadline, 30-second upstream read timeout and 10-second connect timeout remain. The lease lasts 150 seconds, beyond the generation budget. No measured evidence justified increasing timeouts. Explicit stream closure, a disconnect check before persistence, cancellation propagation and conditional lease cleanup preserve retryability. Existing transactional replacement and lease checks prevent stale/duplicate persisted replies. Failed partials can still appear transiently during streaming, but are never stored as completed answers.

## Security and compatibility

No database schema, authentication, project management, Discord, provider configuration, credentials or production environment was changed. Personal scope remains `web:<identity>`; Project-Only remains `web-project:<identity>:<project>`. Default projects retain personal/global behavior. Project-Only excludes global/personal/guild/other-project references. Archived memories remain excluded, explicit saves retain archived-memory restrictions, and feedback remains owned and scope-bound. Existing guarded moves, cross-user ownership, feedback ownership, archived conversations, stale leases and deletion semantics are covered by the regression suite.

## Validation

All AI/OAuth behavior in automated tests is mocked. SQLite databases and HTTPS certificates are disposable local test fixtures. Browser checks use installed Chromium and Playwright with the built frontend.

Run from the repository root unless a directory is specified:

| Command | Result |
| --- | --- |
| `python -m venv --system-site-packages .venv` | Created local validation environment. |
| `.venv/bin/python -m pip install -r requirements.txt` | Installed existing requirements; no dependency file changes. |
| `cd frontend && npm ci --cache /workspace/work/npm-cache` | Passed, 153 packages installed from the existing lockfile. |
| `ABUD_DATABASE_PATH=/workspace/work/test-bootstrap.db .venv/bin/python -m unittest discover -s tests -v` | Passed: 73 tests, 79.689 seconds. |
| `cd frontend && npm run build` | Passed: Vite 6.4.6, 7.62 seconds. |
| `.venv/bin/python tests/run_web_chat_e2e.py` | Passed: real HTTPS API, disposable SQLite/sessions, streaming, failure/regenerate, feedback, speech fixture, isolation and responsive UI. |
| `.venv/bin/python tests/run_web_chat_e2e.py web_projects_e2e.cjs` | Passed: Projects CRUD/organization, immutable modes, guarded moves, titles, archive/restore and responsive dialogs. |
| `.venv/bin/python tests/run_web_chat_e2e.py web_chat_browser.cjs` | Passed: mocked HTTP UI, truncated/malformed/error streams with failed history reload, incomplete labels, duplicate-send guard and regenerate. |
| `git diff --check` | Passed. |

The first pre-setup unittest run failed because dependencies were missing and the default `/app/data` path was unavailable. Default pip/npm installation paths were read-only; local venv/cache paths resolved this. Initial browser runs exposed two harness issues: local HTTPS certificate handling in the mock UI suite, and a missing wait for a new chat to open after API-side deletion. Both were fixed; the affected suites passed on rerun. Existing Authlib/FastAPI/Starlette deprecation warnings remain.

No automated suite was skipped. Live OAuth/provider evaluation, real Discord gateway interaction and production/staging smoke tests were not run; no live credentials were required or accessed.

## Release notes

Review and merge the PR into `dev` using the normal process. Before any separately authorized deployment, back up the database, build the frontend, run the checks below, and evaluate live conversational behavior and failure logging in staging. No new schema migration or dependency is required by this change. Confirm failed turns remain retryable and monitor sanitized failure categories. Rollback is an application-code rollback; stored memory/message formats are unchanged. No deployment, container restart, VPS/9Router change or database reset was performed for this task.
