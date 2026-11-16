# Interactive Web Chat choices

This frontend enhancement derives optional choices from assistant text. It does not
require or guarantee selectable model responses. PR #7's conversational instructions,
backend SSE validation, persistence, authentication and memory scopes are unchanged.

## Detection

`chatChoices.js` accepts 2–8 sequential A–H or 1–8 labels with consistent `)` or `.`
punctuation, optional Markdown bullets/bold markers, or plain Markdown bullets.
Numeric and plain bullet groups require an explicit Indonesian/English decision cue
outside the list (for example “Pilihlah tindakan yang kamu inginkan”, “Pilihlah salah
satu tindakan”, “Apa yang akan kamu lakukan selanjutnya?”, “Kamu mau pilih yang mana?”,
“Choose your action” or “What would you like to do next?”). A preceding cue must be
within 280 characters of the options. With a nearby cue, descriptions may start with
“Kamu…” or “You…”; no opening action verb is required. Without a cue, bare alphabetic
lists qualify only when every description begins with a recognized action verb.
A short decision question can follow the group. Adjacent continuations indented by
2–3 spaces are included; ambiguous wrapping is rejected. Each description is capped
at 600 characters. Original Markdown remains untouched above the controls.

Code fences, blockquotes, JSON-style delimiters, tables, technical/procedural vocabulary,
example contexts, missing/skipped/mixed labels, over-eight groups, ambiguous trailing
prose and ordinary numbered lists are rejected. These conservative heuristics favor
false negatives. They are not semantic classification: unusual wording, other languages,
long descriptions, multiple lists or a technical term in a legitimate decision can hide
controls. A finite action vocabulary prevents bare documentation headings becoming UI.

## Selection and prompts

Native buttons expose `aria-pressed`, visible focus and selected borders/backgrounds.
Tab focuses controls; Space/Enter toggles a choice. The count is announced through a
status region. At two choices, unselected buttons disable until a selection is removed.
Buttons wrap on narrow screens and render descriptions as React text, never HTML or
links. Selecting does not send. “Lanjutkan dengan pilihan” confirms one combined message.
Selection order is preserved; incompatible actions are left for the assistant to resolve.

Examples:

- `Saya memilih opsi A: Open the door. Lanjutkan berdasarkan pilihan ini.`
- `Saya memilih opsi B: Wait; lalu opsi A: Open the door. Lanjutkan berdasarkan gabungan kedua pilihan ini secara masuk akal.`

An explicit story/scene cue changes “Lanjutkan” to “Lanjutkan cerita”. Otherwise wording
stays general. Descriptions are untrusted quoted choice data in an ordinary user message;
there are no hidden instructions or frontend commands. The UI never executes descriptions,
opens their URLs or calls tools. The existing model remains responsible for interpreting
user text under its existing instructions.

## Lifecycle and isolation

Only the last message can expose controls, and only if it is an assistant message with a
persisted ID and no incomplete flag. Streaming placeholders never qualify. Successful
terminal SSE handling and authoritative history reload precede activating a new answer.
Older lists remain ordinary Markdown. Reload derives choices without storing selections.
Regenerated message IDs are excluded as described below.
The existing conversation endpoint handles sends and regenerate, including project scope,
ownership, memory boundaries and persisted user messages; there is no new API or migration.

Choice submission and the composer share `send()`, a synchronous ref guard and existing
busy/lease protections. Navigation guards prevent switching during sends; version and
source-message checks reject stale handlers. Conversation/project/message keys reset
selections on navigation or a changed response. Regenerate immediately invalidates the
current assistant message's controls before making the request. The controls unmount,
clearing selections. An in-memory set plus tab-scoped `sessionStorage` records only the
conversation/message IDs (no text, Project instructions, memory or selections). Failed,
rejected or truncated Regenerate attempts cannot reactivate the restored original response,
including after history reconciliation, switching chats and page reloads in the same tab.
A successful replacement has a new persisted message ID and may expose fresh, unselected
choices even if its text is identical. Source-message checks also reject invalidated IDs.
Locks release in `finally`.

Invalidation is local to the browser tab, not stored on the server or synchronized across
devices. Closing the tab or clearing its storage removes it. If browser policy/quota blocks
session storage, in-memory invalidation still protects the mounted chat and history reloads,
but cannot survive a full page reload. Existing backend scope and ownership remain the
security boundary; this UI metadata grants no permissions.

On rejected requests, history reconciliation preserves the selected choices when no turn
was persisted, so confirmation can retry. If a user turn was persisted but generation
failed, Send stays blocked and Regenerate retries that turn. If reconciliation fails,
choices stay disabled until history is loaded again; reopen the chat to reconcile before
retrying. Network uncertainty never causes an automatic repeat submission.

## Validation and manual checklist

No new dependencies. Unit checks use Node's built-in runner (`cd frontend && npm test`).
Browser suites use the repository's existing Playwright/Chromium HTTPS runner with isolated
SQLite, mocked OAuth/AI and no production services. Run after `npm ci && npm run build`:

```sh
ABUD_DATABASE_PATH=/tmp/abud-bootstrap.db .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/run_web_chat_e2e.py
.venv/bin/python tests/run_web_chat_e2e.py web_chat_browser.cjs
.venv/bin/python tests/run_web_chat_e2e.py web_projects_e2e.cjs
.venv/bin/python tests/run_web_chat_e2e.py web_chat_choices.cjs
git diff --check
```

Manual checks:

- Try A), A., numeric and Markdown decisions in English and Indonesian; ensure guides,
  code, quotes and ambiguous lists remain text.
- Select/deselect with mouse and keyboard; try three options; confirm reversed order.
- Confirm once/double-click; try composer submission during the same send.
- Verify one user message, streamed answer and persistence after reload.
- Switch chats/projects, regenerate, and reload progressed history; old selections must clear.
- Simulate rejection, interrupted generation and failed history reload; use the documented retry path.
- Check focus, screen-reader selected/count announcements and 320/390/768/1280px layouts.

The existing app uses a dark Web Chat palette; this feature follows it. Live provider
conversation quality, live OAuth, actual screen-reader narration and real Discord gateway
behavior require separate manual evaluation. No deployment or production configuration
change is part of this feature.

Validation for this change: `npm ci`, `npm test` (63 cases), `npm run build`, the
full Python suite (76 tests), all four browser/E2E commands above, and
`git diff --check` passed. The chat E2E suite additionally verifies combined-choice
message persistence and inactive old choices after reload through the real local API.
Existing Authlib deprecation warnings remain. The new browser suite initially needed
its project-button selector corrected to include the existing memory-mode label;
the corrected suite passed, including rejection plus failed-history reconciliation.
Review follow-up also covers the exact Indonesian roleplay structure, English/Indonesian
pronoun-led options and nearby questions, plus negative procedural/code/quoted/technical
cases. Browser regressions cover successful, rejected, error, truncated and unreconciled
Regenerate, history/page reloads, conversation isolation and storage-disabled fallback.
The API-backed suite confirms a failed Regenerate retains the original persisted response
without reactivating its controls; successful retry replaces its ID and clears selection.
No live-provider or production checks were run.
