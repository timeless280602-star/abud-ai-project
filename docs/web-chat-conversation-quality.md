# Web Chat conversation quality and streaming audit

## Follow-up: broad build requests and unsolicited introductions

The Web Chat prompt now explicitly confines creator attribution and profile links to
questions about the creator. Ordinary requests start with the requested help, including
when earlier assistant turns repeatedly introduced Abud. A broad request to build an
agent first establishes its intended job with one useful question; an already specified
goal or explicit code request proceeds without restarting discovery. Programming
answers must distinguish executable behavior from illustrative scaffolding: displaying
a function-call name does not execute the function or complete an agent's task.

The style guidance explicitly covers unsolicited `ponytail:` code comments and
`skipped:` / `add when:` footers. Legitimate discussion of these terms remains allowed.
This is prompt guidance, not an output filter: it does not rewrite or censor code, add
model calls, change streaming, or guarantee a provider's wording. Text and voice use
the same composition function. There is no frontend, database or provider-config change.

Manual acceptance after deployment: start a new conversation with “bisa bantu gw bikin
ai agent?”, then specify its job and platform, then explicitly request runnable code.
Check that the first answer establishes the missing goal without promotions or a
generic snippet; later answers use the supplied context and describe implemented code
honestly. Also ask who created Abud and confirm the correct attribution and profiles.
Automated composition/stream tests do not substitute for this live model check.

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

## PR #7 follow-up: terminal SSE semantics

The previous parser returned immediately on `finish_reason: "stop"`. That could hide a later error, malformed trailer, contradictory failure reason or transport reset and persist the earlier text as a successful response. It also rejected `delta: null` terminal chunks and complete terminal payloads missing the last blank SSE delimiter.

The parser now consumes trailers until `[DONE]` or clean EOF. Successful text completion requires either `[DONE]` without any preceding failure, or an explicit `stop` and a clean end of the HTTP stream. Empty text still fails in `send()`. Content-only EOF, usage-only trailers without a completion marker, invalid/truncated JSON, transport failures (including after `stop`), unknown/non-success finish reasons, contradictory reasons and new content after `stop` all fail. A received failure is never overridden by a later `[DONE]`. Unsupported tool-call finishes remain failures because Web Chat has no tools.

Compatible variants include terminal `delta` as an object, null or omitted; usage-only trailers with `choices: []`; comments/CRLF/multi-line data; and a complete final payload without a final blank delimiter. A final payload must still contain a valid success marker; accepting EOF framing never makes content-only EOF successful. Reasons in the choice, delta or top-level chunk are checked together so one cannot conceal a failure in another location.

Public 9Router references inspected at commit `1855aa44473e88feac9d3f131b9c0c5fc9706b68`:

- [Documented chat streaming shape](https://github.com/decolua/9router/blob/1855aa44473e88feac9d3f131b9c0c5fc9706b68/skills/9router-chat/SKILL.md): content chunks followed by `[DONE]`, without requiring a finish reason in the example. Requiring both markers would reject this supported shape.
- [SSE chunk builder](https://github.com/decolua/9router/blob/1855aa44473e88feac9d3f131b9c0c5fc9706b68/open-sse/utils/sse.js): choice-level finish reason.
- [Qoder coalescer](https://github.com/decolua/9router/blob/1855aa44473e88feac9d3f131b9c0c5fc9706b68/open-sse/shared/qoder/sse.js): usage after finish, and reasons originating in the choice, delta or top-level chunk; valuable deltas may be forwarded as-is.

The deployed 9Router version and production traffic were not inspected. These are compatibility references, not a claim that the production gateway emits every tested variant. Native Anthropic/Gemini/Responses event protocols are not inferred at this `/chat/completions` endpoint. A gateway that falsely reports a normal terminal marker while suppressing all upstream failure evidence cannot be diagnosed from that marker alone.

Regression cases run through both the actual HTTP/SSE parser and authenticated persistence/regeneration endpoints using disposable SQLite. They verify no completed assistant message on failures, lease cleanup, successful regeneration without duplicate messages, and preservation of the original answer when regeneration encounters a transport reset after `stop`.

Follow-up validation (all passed):

- `ABUD_DATABASE_PATH=/workspace/work/test-bootstrap.db .venv/bin/python -m unittest discover -s tests -v`: 76 tests, 34.819 seconds; includes 33 terminal-protocol variants tested at both parser and persistence boundaries, empty-response handling, and post-stop transport resets.
- `cd frontend && npm run build`: Vite build succeeded in 16.55 seconds.
- `.venv/bin/python tests/run_web_chat_e2e.py`: passed.
- `.venv/bin/python tests/run_web_chat_e2e.py web_projects_e2e.cjs`: passed.
- `.venv/bin/python tests/run_web_chat_e2e.py web_chat_browser.cjs`: passed.
- `git diff --check`: passed.

One full run was interrupted after the existing 10 ms deadline fixture stalled during partial-chunk ASGI delivery/disconnect polling. The fixture now expires while waiting for the provider, avoiding that unrelated cancellation-scope timing race. Partial-failure behavior remains covered separately. The full suite passed on rerun; production timeout implementation was not changed. No live provider calls, production changes or deployment were performed.
