# Web chat message controls and personal feedback

## Behavior

- Enter sends the composer draft; Shift+Enter inserts a newline. IME composition
  confirmation is ignored. Empty, busy, loading and pending-failed-turn guards
  are identical to the Send button.
- Every message renders its UTC `created_at` using the browser's locale/time zone,
  with the date, minute and zone label. Stored timestamps are unchanged. Pending
  messages display a provisional client time, replaced by server time on refresh.
- Saved assistant responses have Copy, Rate response and Read aloud actions.
  Rating choices appear only after opening Rate response. Good response immediately
  saves feedback. Bad response requires a nonblank reason (maximum 500 characters)
  and explicit submission. The saved rating survives reload. Changing a rating
  replaces the existing feedback and revises the same memory, without duplicates.

## Read aloud

Uses browser `speechSynthesis` and installed/browser-provided voices, without a
new backend service, paid API or dependency. It reads rendered message text rather
than Markdown syntax, timestamps or controls. It uses sentence-sized chunks and
supports Stop reading; opening another thread, sending/regenerating or leaving
chat cancels playback. Speech failures produce a retryable UI message.

Language selection is a lightweight heuristic: Indonesian/English word scoring,
Japanese/Korean/Chinese/Arabic script detection and device-language fallback. It
selects a matching available voice, otherwise lets the browser choose for the
requested language. Mixed-language text and short ambiguous text can be detected
incorrectly; voice availability/pronunciation depend on the user's device/browser.
This is not a universal language detector. Browser/OS voices may use their own
speech services; the application does not send text to a new TTS backend.

## Private feedback memory

`POST /web/chat/conversations/{cid}/messages/{message_id}/feedback` accepts only
`rating: "good" | "bad"` and optional `reason`. It enforces the existing real
session, profile, exact-Origin and conversation ownership checks, rejects rating
user messages or responses from other threads, and rejects changes during a stream.

Startup adds `web_response_feedback` and an owner index. Existing message tables,
IDs, timestamps and content are preserved. Feedback plus a personal memory are
written atomically with `BEGIN IMMEDIATE`. Repeated identical feedback is
idempotent, including simultaneous requests. Metadata is server-controlled:
source `direct`, revision 1 initially, increasing when feedback changes.

Personal memory ownership is `web:<identity UUID>`. The memory contains the
rating, bounded question/answer excerpts and the user's reason, encoded as JSON
within the web memory size limit. Unusually escape-heavy feedback may require
shortening. No model is invoked to guess a user's preferences or rewrite reasons.

The latest ten active feedback memories are included explicitly in future web
inference context for that identity, even when the next question has different
keywords. Good examples guide style and bad feedback identifies user-reported
mistakes to avoid. Ratings are not factual proof or global model training; model
weights are unchanged and improvement is not guaranteed. No guild/Discord/global
memory is written, and another user's feedback is never included.

Archiving excludes the memory from both ranked retrieval and feedback context;
restore re-enables it. Archived feedback cannot be silently revived by re-rating.
Deleting the personal memory removes its feedback association. Regenerating a
response clears the rating from the new answer while retaining the original
feedback as a personal preference. Deleting a conversation also retains that
separately saved memory, consistent with existing explicit memory saves.

## Verification and rollout

Python 3.12 and Python 3.11 (built non-root Docker image, no network): 54 tests
passed, including five new feedback tests covering authorization, input checks,
idempotency/concurrency, revision updates, future-context isolation, archive/
restore/delete, regeneration and thread deletion. Frontend production build and
Docker build passed. The environment proxy CA was mounted as a BuildKit secret
for Docker dependency steps with TLS verification enabled; no CA is committed.

The HTTPS browser harness checks Enter/Shift+Enter/IME, Jakarta/New York-local timestamps,
hidden rating choices, good/bad submission, reload persistence, ownership, English
and Indonesian voice selection, stop/error behavior, and responsive feedback UI,
in addition to existing chat integration checks. OAuth/AI and the speech engine
are mocked; FastAPI, sessions, feedback API and SQLite are real. Audible output
still needs checking on an actual user's device.

Run `python -m unittest discover -s tests -v` with a disposable
`ABUD_DATABASE_PATH`, `npm --prefix frontend run build`, then
`python tests/run_web_chat_e2e.py` with Playwright/Chromium installed.

The change is not automatically deployed to the VPS. Before replacing only the
API container, take a fresh consistent SQLite backup and retain the currently
running image for rollback. API startup applies the additive schema. The existing
bot and 9router containers need no restart. Verify timestamps, keyboard behavior,
ratings and actual device audio after updating production.
