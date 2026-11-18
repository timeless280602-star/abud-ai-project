# Creator notifications (draft)

This adds `/notify` to the Discord bot. No live services are enabled by this branch.
The PR is stacked on the Discord voice draft so the next release can be tested together.

## Administrator experience

- `/notify add platform:youtube url:https://www.youtube.com/@creator destination:#announcements ping:none events:both`
- `/notify list` lists IDs, destinations, ping, filters, pause state, and worker health.
- `/notify edit ident:1 ping:here events:live` changes only the supplied settings.
- `/notify edit ident:1 enabled:false` pauses; `enabled:true` resumes from that time.
- `/notify test ident:1` posts a preview in the destination **without pinging anyone**.
- `/notify remove ident:1` deletes a subscription in the current server.

All commands require Administrator at runtime as well as by default in Discord.
Limits are **10 YouTube channels per guild**, plus 10 optional TikTok accounts. Paused
subscriptions count toward the limit. The same account in different guilds is allowed;
a duplicate within a guild must be edited instead. Destination must be a normal text
channel in the same guild. Abud needs View Channel, Send Messages, Embed Links, and
Mention Everyone if `here` or `everyone` is selected. Ordinary user/role pings from
creator titles are suppressed. No message is sent on registration.

Notifications show the actual live/video title as the clickable embed heading, a large
thumbnail below it, and a **Watch Live** link button (**Watch Video** for uploads).
The heading and button share the same canonical destination. YouTube thumbnails come
from the video's API metadata at the best available resolution, falling back to the
video's standard thumbnail URL if needed. Link buttons need no running interaction
handler. TikTok thumbnails require the external provider to include the optional
`thumbnail` HTTPS URL; without it, the notification still has its title and button.

YouTube accepts `/@handle`, `/channel/UC…`, `/user/…`, a bare channel ID or `@handle`.
Legacy `/c/…` and video links are rejected with guidance rather than guessed.
Posts mean public **videos and Shorts**, not text/image Community posts. Upcoming
streams and ended-stream archives are not reported as new uploads. A live alert is
emitted only once an observed stream is actually live. Events older than registration
or resume time are suppressed, including streams already live when registered.

## Configuration for later acceptance

Set in `.env`, then rebuild/recreate the bot when the batch is ready:

```dotenv
ABUD_NOTIFICATIONS_ENABLED=true
YOUTUBE_API_KEY=YOUR_YOUTUBE_DATA_API_V3_KEY
ABUD_NOTIFICATIONS_INTERVAL=300
```

Enable YouTube Data API v3 in the key's Google Cloud project. Do not enter API keys in
Discord. The polling interval has a minimum of 300 seconds. The official channels API
resolves handles; uploads playlist discovery and batched videos API read publication
and liveStreamingDetails. Up to 50 recent uploads plus retained upcoming/live IDs are
checked. Retained IDs survive restart and expire after 90 days without observation.
No expensive `search.list` request is made. Sources shared across guilds are polled once.
For 10 sources with <=50 watched videos each, playlist + status requests cost roughly
5,760 units/day at five-minute intervals, excluding setup and extra status batches.
Quotas are shared across all guilds using the key; additional distinct sources increase
cost. HTTP 403/429 pauses provider requests for an hour; worker and subscriptions remain.

Detection is polling-based, not instant. Upload playlists are the discovery source;
YouTube can delay exposing a new live stream there. Live discovery timing and whether
public streams are exposed during broadcast must be verified with real test channels
before promising full live coverage. Short streams, more than 50 uploads during downtime,
or content absent from the uploads playlist may be missed. This implementation does not
claim guaranteed detection of every live broadcast. WebSub is not substituted for live
status: its documented events concern uploads/title/description changes.

Subscription settings and successful deliveries persist in the bot's dedicated Compose
volume `abud-notifications`, owned by UID 10001, separate from the API's memory database.
Back it up before replacing the volume. For non-Compose use, set `ABUD_NOTIFICATIONS_DB`
to a writable persistent path. Never run two bot replicas against the same database:
serialization covers only one process. Failed sends are not marked delivered and are
retried on later observations; a failed live send can be lost if the broadcast ends
before a successful retry. Discord send success followed by a process crash before the
SQLite write can duplicate a delivery; exactly-once delivery is not guaranteed.

## Optional TikTok provider integration

TikTok is an **external-provider webhook adapter**, not a built-in account scraper or
an official TikTok live subscription. The Display API requires creator authorization
and does not supply the equivalent arbitrary-channel live detection used here. An
operator must connect a provider that detects public live/post events and converts
them into this schema; no provider has been selected, bought or connected by this PR.
Without it, TikTok monitoring is not operational.

Set a random `ABUD_TIKTOK_WEBHOOK_SECRET` of at least 32 characters. `/notify add
platform:tiktok url:https://www.tiktok.com/@creator ...` then registers the account;
the provider must also be configured to monitor that account. Expose only
`POST /internal/notifications/tiktok` on port 8765 through an HTTPS reverse proxy with
body/rate limits. Do **not** expose the other internal bot routes or the whole port.
No public endpoint or proxy is deployed by this branch.

The exact raw UTF-8 JSON body:

```json
{"account":"creator","id":"1234567890123456789","kind":"post","title":"New video","occurred_at":1795003200}
```

- `kind`: `live` or `post`.
- `id`: numeric video ID for posts; stable numeric room/session ID for a live broadcast.
  Repeated checks of the same live must reuse its ID, and the next live must use a new ID.
- `occurred_at`: Unix seconds at publication/live start (not observation time), within
  the last 24 hours and no more than 60 seconds in the future.
- `account`: TikTok handle without `@` (case insensitive).
- `thumbnail` (optional): HTTPS image URL, at most 2,048 characters. Include the actual
  live/video thumbnail; this adapter does not invent a TikTok cover image.
- `X-Abud-Timestamp`: current Unix seconds, accepted within five minutes.
- `X-Abud-Signature`: lowercase hex HMAC-SHA256(secret, timestamp + `.` + exact raw body).

Only registered, active subscriptions receive events. Duplicate events are suppressed
per subscription, session/video ID and kind. The adapter constructs canonical TikTok
links and ignores any provider-supplied URLs. A 503 requires retry with a fresh signed
timestamp and the same event ID; previously successful destinations are skipped. A 200
means accepted, possibly with no matching subscriptions. Provider credentials remain
outside Discord. Authentication failures return 401; malformed events return 400.

## Acceptance when the batch is ready

Local contract tests use provider and Discord doubles, never real pings or accounts.
Before deploy, validate Compose and writable volume permissions in the built image.
In an isolated guild, register a channel, run preview, then publish a public video/Short
and start a scheduled and an unscheduled live. Verify the actual thumbnail, clickable title and Watch Live button all reference the
correct broadcast. Check an upload uses Watch Video. Measure detection latency and verify the
channel exposes each active stream in the uploads API. Confirm upcoming and ended
streams do not produce upload alerts. Repeat with no ping, here and everyone; check a
missing Mention Everyone permission blocks configuration. Restart the bot to check
settings/deduplication, pause/resume, remove a destination, exhaust a test provider and
reconnect Discord. Check two guilds and concurrent events. TikTok acceptance additionally
requires real provider events, bad signatures, repeated events and 503 retries.

References:
- https://developers.google.com/youtube/data/reference/rest/v3/channels/list
- https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list
- https://developers.google.com/youtube/data/reference/rest/v3/videos
- https://developers.google.com/youtube/data/guides/push_notifications
- https://developers.tiktok.com/docs/en/display-api-overview
- https://developers.tiktok.com/docs/en/display-api-get-started
