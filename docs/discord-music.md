# Abud Music (draft)

Jockie Music's public command catalogue informed the playback/queue workflow. This is
Abud's own implementation and panel, not a copy of Jockie's proprietary code or branding.
The feature is disabled by default. No Discord login, provider account, node, ping or
VPS deployment is performed by creating this draft.

## User experience

Join a normal voice channel, then use `/music play query:judul lagu`. Abud connects
in music mode and shows one shared Now Playing panel with a clickable song title,
artwork (when supplied by the source), artist, elapsed/total time, requester, upcoming
count, volume and repeat mode. Panel buttons: Pause/Resume, Skip, Shuffle, Stop, Queue.
Position is a snapshot refreshed by commands/track changes, not a continuously edited
progress bar. Source metadata can omit artwork. Messages never mass-mention users.

| Command | Behavior |
| --- | --- |
| `/music play query source` | First search result or supported URL/playlist; auto-join |
| `/music search query source` | Private picker with five results, expires in 60 seconds |
| `/music queue page` | Numbered upcoming queue, ten tracks per page |
| `/music nowplaying` | Current track and playback state |
| `/music pause`, `/music resume` | Pause or resume playback |
| `/music skip` | Next track; bypasses repeat-track |
| `/music previous` | Play previous track, put interrupted track back at queue front |
| `/music stop` | Stop and clear queue/repeat, stay connected until idle cleanup |
| `/music leave` | Stop, discard session and disconnect |
| `/music shuffle` | Shuffle only upcoming tracks |
| `/music repeat mode` | `off`, `track`, `queue` |
| `/music volume percent` | 0–100; default 50 |
| `/music seek seconds` | Absolute position for seekable finite tracks |
| `/music remove position` | Remove numbered upcoming item |
| `/music move position destination` | Move an upcoming item |
| `/music clear` | Clear upcoming tracks while current track continues |

Everyone in the same voice channel can add tracks and read the queue. Playback/queue
controls require the session owner, Manage Server permission, or a role named `DJ`
(case insensitive). A track's requester can also skip that track. Controls and buttons
check membership and permissions at the time of use; administrators in another channel
cannot unexpectedly control the session. Only the requester can use their song picker.
Old-session buttons cannot affect replacement sessions. Bot permissions: View Channel,
Connect and Speak in voice; View Channel, Send Messages and Embed Links in the text
channel where the session is opened.

The bot has one voice connection per guild. AI conversation and music are separate modes:
use `/leave` to close an AI session before starting music, or `/music leave` before
starting AI with `/join`. `/stop` still controls AI answers; `/music stop` controls music.
Joining is serialized through the existing voice manager's lock. Music does not listen
to or transcribe members; it joins self-deafened and does not require Whisper/Piper.

## Runtime and limits

Wavelink **3.5.2**, Lavalink **4.2.2** (default Ubuntu image, including DAVE support).
A private optional Lavalink service handles decoding/Discord audio independently of
AI inference. Base sources are SoundCloud and Bandcamp; title search defaults to
SoundCloud. HTTPS URLs are limited to supported music hosts. Raw HTTP/local/file
sources are disabled at Lavalink and the command rejects internal schemes/unknown hosts.
The implementation does not download or store audio files.

- At most two music sessions per bot process and 100 tracks per session including current.
- Playlists exceeding available capacity are rejected atomically, not silently truncated
  by the queue. A source may itself expose only a bounded portion of a playlist (YouTube
  config loads one page, up to 100 entries).
- History keeps 20 tracks; session queues/history are RAM-only and discarded on restart.
- At most two simultaneous searches, with 15-second search/node timeouts.
- Three consecutive failures stop automatic attempts; user can retry with another source.
- Empty voice channels or forced move/disconnect close the session. Empty queue disconnects
  after three minutes; paused sessions disconnect after 30 minutes. Watchdog checks every
  five seconds and continues across individual guild cleanup failures.
- Queue mutation is serialized; each play has a unique nonce sent through Lavalink's
  userData. Stale/duplicate/replaced end events cannot advance a newer session track.
- Node loss can interrupt playback; sessions are not transparently restored after a node
  restart. Close/reopen a session after recovery. Reconnecting node clients are handled
  by Wavelink; no success is reported solely because a websocket reconnect was attempted.

This is the core player, not full Jockie feature parity. Spotify/Apple Music links,
recommended autoplay/radio, lyrics, scheduled departure, effects/equalizer, durable
session restoration and multiple Abud bot accounts in one server are outside this draft.
Spotify is rejected with guidance to search the song title or use a supported link.

## Configuration for the later batch test

```dotenv
ABUD_MUSIC_ENABLED=true
ABUD_LAVALINK_PASSWORD=YOUR_RANDOM_PRIVATE_SECRET
ABUD_MUSIC_SEARCH_SOURCE=soundcloud
```

Compose supplies `ABUD_LAVALINK_URL=http://abud-lavalink:2333`. For a non-Compose setup,
configure this URL and password for your private node. Use the optional
`compose.music.yaml` overlay alongside the existing base/voice overlays as needed.
The node has no published ports; do not expose its REST/websocket endpoint publicly.
The overlay requires a password instead of providing a shared default. JVM heap is
capped at 512 MiB, with a 768 MiB container limit in addition to the bot/AI workloads.
Measure real memory, CPU and network use on the target VPS before enabling the batch.

The overlays are examples for review, not an instruction to deploy this branch now.
No Docker engine is available in the current editing environment; local validation is
limited to configuration structure and Python contracts. CI builds the bot image and
validates the overlays. Node boot, image/native library compatibility and audible DAVE
handshake remain part of later acceptance.

### Optional YouTube

Add `compose.music.youtube.yaml` after the music overlay. It pins youtube-source
**1.18.2**, disables Lavalink's deprecated built-in YouTube source, and enables the
plugin. Use `/music play ... source:youtube` or set search source to `youtube` after
acceptance. A YouTube Data API key from the notification feature is not used for music.
YouTube extraction can fail due to provider/client changes, rate limits and unavailable
content. Upstream has unresolved playback issues; this draft does not claim reliable
YouTube playback until a real test on the target node succeeds. Plugin download at boot
requires Maven access. No OAuth cookies, PO tokens, external cipher service or paid
provider is configured by this draft. If the source needs those, evaluate separately;
do not treat metadata/search success as proof of audio playback.

## Later acceptance checklist

1. Validate base + music + voice Compose and optional YouTube overlay with dummy secrets.
   Build the bot image; start a private Lavalink node only when the batch is authorized
   for testing. Check image version, DAVE native support, password rejection and no public port.
2. In a test guild, search and select a SoundCloud song, play a link and a small playlist.
   Confirm audible playback, correct title/artwork, duration and requester, then test
   pause/resume, seek, zero/normal volume and all queue commands.
3. Check repeat-track, repeat-queue, previous, skip during playback, stop during a track
   transition and repeated clicks. Confirm no surprise restart or double advance.
4. Test two guilds, DJ/owner/ordinary/requester controls, a member outside the channel,
   a stale panel, full queue, missing permissions and empty/paused idle disconnect.
5. Interrupt a source/node, force-move/kick the bot and reconnect; verify cleanup and
   that a new session can start. AI `/join` and music must refuse overlapping connections
   and work after the other mode leaves. No voice transcription occurs during music.
6. Test YouTube separately (search, direct track, playlist, long track) and verify sound;
   keep that source disabled if provider playback is unreliable on the VPS.

References:
- https://www.jockiemusic.com/commands
- https://github.com/PythonistaGuild/Wavelink/releases
- https://github.com/lavalink-devs/Lavalink/blob/master/CHANGELOG.md
- https://lavalink.dev/getting-started/docker.html
- https://github.com/lavalink-devs/youtube-source
