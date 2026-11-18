# Community leveling (draft, without role rewards)

Abud awards community XP, displays level/rank cards and a leaderboard, and can announce
level-ups. **There are no role rewards:** no role mappings, automatic role grants/removals,
role-based XP boosts or Manage Roles permission requirement. This is independent of the
music player's existing DJ access controls.

The feature defaults off globally and each guild must opt in. No guild setting, role,
Discord message, live bot session or VPS deployment is changed by creating this draft.

## Commands

| Command | Purpose |
| --- | --- |
| `/rank [member]` | Public PNG rank card with XP progress, total/chat/voice XP and server rank |
| `/leaderboard [page]` | Public per-guild XP ranking, ten participants per page |
| `/leveling setup enabled:true` | Administrator enables the guild with chat + voice defaults |
| `/leveling setup enabled:true chat:false` | Disable chat XP; preserve other existing options |
| `/leveling setup enabled:true announcement:#levels` | Opt into level-up notifications in that channel |
| `/leveling setup enabled:true notify:false` | Disable level-up notifications without disabling XP |
| `/leveling setup enabled:false` | Pause earning XP; retain saved totals and rank queries |
| `/leveling exclude channel:#channel` | Exclude a normal text/voice channel from XP |
| `/leveling include channel:#channel` | Remove that exclusion |
| `/leveling config` | Administrator sees settings, fixed XP limits and excluded channels |

Rank cards use an original dark/red Abud design rendered in memory with Pillow. No
avatar fetch, remote image service or message-content screenshot is involved. The bot
needs Send Messages, Attach Files and View Channel where `/rank` is used; Embed Links
for leaderboard/announcements. Missing delivery permissions produce a safe error; they
do not modify XP. Commands are guild-only; bots never receive XP/ranks. Administrator
permissions are enforced at runtime for setup/config/exclusions, beyond Discord's default
command visibility.

Announcements are off until a text channel is selected. They include the name and new
level without pinging users, roles, here or everyone. Failures do not roll back committed
XP and are not retried, avoiding duplicate awards. No notification is posted for an
existing level after a restart. Multiple thresholds crossed in one award would produce
one notice for the final level.

## XP rules and anti-farming

- Chat: random **15–25 XP**, at most once every **60 seconds** per member/guild.
- Voice: **5 XP** for an observed continuous eligible minute, checked every 15 seconds.
- Daily caps: **1,000 chat XP** and **600 voice XP**, separately, reset at midnight WIB.
- Level `L` starts at `100 × L²` total XP: level 1 at 100, level 2 at 400, level 3 at 900.
  There are no rewards/role assignments associated with a level threshold.
- Bot, webhook, DM and system messages do not count. Ordinary message replies count.
  Slash/prefix-style commands, URL-only, mention-only, emoji-only, very short, numeric-only
  and highly repetitive content is rejected. At least eight alphanumeric characters,
  four distinct normalized characters and one letter must remain after removing URLs,
  mentions and custom emoji.
- Text is normalized for case/spacing/punctuation. The same normalized message cannot
  earn again within ten minutes. Only ten hashes and award timestamps per participant
  are retained, not raw message text. Cooldowns and hashes survive restart. Edits are
  not processed as new messages. This heuristic does not determine semantic quality
  and cannot prevent coordinated farming or all variations of spam.
- Excluding a text channel also excludes its threads via parent ID. Voice exclusions
  refer to normal voice channels; category exclusions are not part of this version.
- Voice requires **at least two eligible humans in the same regular voice channel**.
  Bots, AFK channel, self/server mute, self/server deaf, AFK and suppressed members are
  excluded. A solo eligible user earns nothing even if a bot or muted user is present.
  Stage channels are not included. Abud does not need to join a voice channel for XP.
- Voice tracks presence/state, not actual speech: no recording/transcription or audio
  analysis is added. Two unmuted accounts can still remain idle; caps limit earning,
  but this is not proof of human activity. Members who self-mute while listening to
  music do not earn voice XP under these rules.
- Ineligible periods, channel moves, guild unavailable states, disconnects, reconnects
  and startup reset continuity. There is no credit for offline time or backfilling
  long tick delays. Repeated ticks have a persisted source cooldown as an extra guard.

## Persistence and integration

SQLite WAL database in dedicated Compose volume `abud-leveling` at
`/app/leveling/levels.db`, owned by bot UID 10001. Back up the volume before replacing
it. Non-Compose installs must set `ABUD_LEVELING_DB` to a writable persistent path.
Settings, exclusions, per-guild member IDs/display names, totals/source breakdowns,
WIB daily counters, cooldowns and duplicate hashes are stored. No raw chat text is
stored by this feature. Each guild's totals and ranking are independent; ties use
member ID order. Historical participants remain on the leaderboard after leaving;
names are snapshots refreshed when XP is awarded, not an authoritative current roster.
The version has no XP imports, manual adjustments, reset, seasonal wipe or scheduled
competition. Pausing does not erase data.

Run one bot process per database; the implementation serializes transactions within
one event loop, not across competing bot replicas. Rank-card rendering runs in a worker
thread using an immutable snapshot, without sharing SQLite connections with that thread.
The bot image includes DejaVu fonts and Pillow; no generated cards are saved to disk.

Community messages reach leveling before the bot-name/music/AI dispatch gate, so members
do not need to call Abud to earn chat XP. Existing chat/music/AI behavior follows afterward.
Voice-state processing updates XP eligibility before music/AI cleanup. Gateway disconnection
clears XP timing without changing existing voice managers. The XP worker is singleton on
reconnect; module errors are sanitized and do not prevent other chat/voice handlers.
Existing Message Content and Voice States intents are used; no privileged Members or
Presence intent is added. The bot relies on Discord's cached voice members and must
have access to the channels being tracked.

## Enable only when the batch is ready

```dotenv
ABUD_LEVELING_ENABLED=true
```

Rebuild the bot image to install Pillow/fonts and include the writable leveling volume.
Then an administrator opts the guild in with `/leveling setup enabled:true`. Keep
announcements off or use a test channel for initial acceptance. This branch does not
perform those steps or change the VPS. Global disable stops earning and hides runtime
queries behind a clear disabled response; guild pause preserves visible historical ranks.

## Later acceptance

1. Build the image, validate merged Compose and verify UID 10001 can open the persistent
   leveling database and read fonts. Ensure rank, leaderboard, leveling, play, music,
   notify and existing voice commands register together.
2. In a test guild, confirm no XP before opt-in. Enable chat and send varied messages
   over several minutes, spam duplicates, edit old messages and try excluded threads.
   Check cooldown, source caps and an opt-in level-up notice without pings.
3. Exercise two real human voice accounts: eligible minute, solo, bot companion, muted/
   deafened/AFK, move, disconnect/reconnect and unavailable channels. Verify continuity
   resets and that no audio capture or bot voice join is started by leveling.
4. Check `/rank` including a never-active member and `/leaderboard` pagination/ties.
   Restart the bot; verify settings, XP, exclusions and anti-farm state remain.
5. Verify a non-admin cannot change settings and a configured announcement channel
   with removed permissions does not lose/duplicate XP. Test two guilds for isolation.
6. Check music/chat/AI still function alongside XP, and inspect guild roles before/after
   level-ups: **no role is granted, removed, edited or rewarded**.
