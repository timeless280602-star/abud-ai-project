# Discord voice channel

Abud can join an ordinary guild voice channel, transcribe enrolled speakers with
the existing private Whisper worker, answer through the existing authenticated
`/chat` API (9router), and read the answer using Piper. The web voice provider
setting does not change Discord's chat provider. This branch starts from the
restored release `c105773`; the separate web prompt PR #20 is not included.

## Commands

| Command | Behavior |
| --- | --- |
| `/join` | Join the caller's ordinary voice channel. Enroll the caller after posting the listening notice in that channel's text chat. |
| `/listen aktif:True` | Enroll your own audio in the current session. |
| `/listen aktif:False` | Forget your pending audio and cancel your current turn. |
| `/stop` | Cancel the current HTTP/audio work and clear the queue; keep listening. Any member in the same channel may interrupt. |
| `/voice-status` | Private status: phase, enrolled speakers, queue, completed/dropped turns. |
| `/leave` | Disconnect and release buffers, tasks, HTTP clients and audio processes. Requires the session opener or Manage Server, in the same channel. |

Every utterance must start with **Abud**, optionally preceded by `halo`, `hai`,
`hey`, `hei`, `oke`, `ok` or `woy`. For example: “Abud, kasih ide acara Discord
malam ini.” This is a **transcript activation phrase**: enrolled speakers' audio
is sent to Whisper before the phrase is checked. It is not an offline wake-word
detector. Ungreeted transcripts do not reach the chat model or Piper.

The receive transport decrypts incoming Discord packets, but only enrolled
members' PCM enters application buffers/Whisper. Enrollment is voluntary per
member and resets on departure, session closure, bot restart, or a bot move.
Bot/unknown speakers are ignored. No audio files or transcripts are written to
the bot's disk/logs. Addressed turns and model answers use the existing API's
persistent conversation history and memory rules, isolated by user/guild/channel.
Voice does not invoke the text bot's background auto-save or DM notification path.
Explicit memory requests retain the existing API permission checks.

## Bounds and lifecycle

- One session per guild; at most two sessions per bot process (the default bot
  container has 256 MB RAM), eight enrolled members per session.
- PCM: 48 kHz stereo 16-bit; maximum 12 seconds per utterance, 0.8 seconds silence
  to finish, at least 0.3 seconds of signal. Overlong utterances are discarded
  until the speaker pauses, avoiding a truncated actionable request.
- Three pending turns, one active turn; pending audio expires after 30 seconds.
  Excess turns are dropped and counted in status. Members retain separate buffers
  and API identities. Overlapping human speech is not mixed together.
- Capture pauses during Abud's playback to limit echo. Use `/stop` for an
  interruption; automatic spoken barge-in is not implemented.
- Voice asks the model for 1–3 sentences, caps generation at 350 tokens, removes
  Markdown/code/URLs/mention tokens from spoken output and caps it at 900 characters.
- Per-turn deadline: 120 seconds. HTTP operations and audio subprocesses have
  additional timeouts and size/duration limits. `/stop` cancels the local request;
  it cannot undo an operation the API has already completed.
- Empty channels, bot disconnection/move/deafen, receiver failure or five minutes
  without accepted audio close the session. `/join` can start a new session.
- On provider errors, the turn is dropped and a safe notice is posted at most
  once per 30 seconds. Later turns can proceed. A busy Whisper/Piper worker is not
  retried automatically, preventing stale responses and duplicate API actions.

## Deployment

1. Keep the existing production environment, database and bot token. The bot still
   needs `DISCORD_TOKEN`, `ABUD_INTERNAL_API_KEY` and `ABUD_API_URL`; the API needs
   its existing 9router configuration. OAuth app credentials are not voice tokens.
2. Prepare the Piper model `.onnx` **and** `.onnx.json` in the existing voice model
   directory as described in `docs/web-voice-chat.md`. Set `ABUD_WHISPER_LANGUAGE=id`
   for Indonesian and `ABUD_DISCORD_VOICE_ENABLED=true`. For non-Compose installs,
   also set `ABUD_DISCORD_VOICE_WORKER_URL` to a trusted private worker address.
3. Build/restart from the reviewed commit using both Compose files:

   ```sh
   docker compose -f compose.yaml -f compose.voice.yaml up -d --build abud-api abud-voice abud-bot
   ```

   This explicitly uses only Whisper/Piper for Discord; Ollama is not required.
   Whisper/Piper initialization can take time. `/join` checks `/health` and asks
   the user to retry while the worker is unavailable. The worker has no published
   ports; the bot and worker share the private `voice` network.
4. Give the bot View Channel, Connect, Speak and Send Messages in the target
   voice channel. Keep the existing application-command scope. The bot enables
   voice-state events; no new privileged intent is requested. Check the bot's
   startup log for successful slash-command sync. Stage channels are unsupported.
5. Run the live acceptance sequence below before treating the release as ready.

## Voice dependency selection

Discord requires DAVE for normal voice calls. `discord.py[voice]==2.7.1` supplies
the connection/send support and `davey==0.2.0` the encryption implementation.
The upstream `discord-ext-voice-recv` release does not yet merge receive-side
DAVE support. The bot therefore pins the source reviewed in upstream PR #65:

`idoldange/discord-ext-voice-recv@4da8413355893ed93798be9b4f3a07bc083875f6`.

This remains an experimental receive dependency. The code delegates decryption
to the established discord.py DAVE session; it does not implement a new crypto
protocol or patch library internals at runtime. Installed-source tests exercise
speaker-key selection, dropping undecryptable frames and decrypt-once FEC handling.
They do not establish a live Discord MLS session. Revisit the pin when the
upstream package publishes equivalent support; do not switch to an unpinned HEAD.

Primary references:

- https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx
- https://github.com/Rapptz/discord.py/blob/v2.7.1/docs/whats_new.rst
- https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/65

## Verification and live acceptance

Run with Python 3.11, FFmpeg and libopus installed:

```sh
python -m pip install -r requirements.txt -r requirements-bot.txt
ABUD_DATABASE_PATH=/tmp/abud-discord-tests.db python -m unittest discover -s tests -p 'test_*.py' -v
```

Automated checks use disposable SQLite, deterministic provider doubles, a real
local HTTP server, real FFmpeg PCM conversion and the installed pinned receiver.
CI also builds the bot Docker image and imports its voice/Opus runtime without
logging into Discord. These checks do not test an actual guild connection,
Whisper recognition quality, Piper intelligibility, or live 9router answers.

Live acceptance (two members, a test guild):

1. `/join`: notice appears in the voice channel, bot stays connected with DAVE.
2. Opener: “Abud, halo.” Hear a coherent Indonesian answer. Check status returns
   to listening. Say a sentence without “Abud”; hear no answer.
3. Second member speaks before `/listen`: no answer. Opt in, speak an addressed
   question, and verify the response/history uses that member's identity.
4. Both ask questions: hear serial replies. `/stop` during playback and during
   inference; hear no pending reply and verify a new question still works.
5. `/listen aktif:False` and depart/rejoin: prior queued audio is not answered.
6. Simulate worker failure: safe notice, then recovery on the next question.
7. Kick/move/deafen Abud, empty the channel, and let it idle for five minutes;
   verify cleanup and that `/join` can create a fresh working connection.

No production deployment or live Discord acceptance is implied by a passing CI run.
