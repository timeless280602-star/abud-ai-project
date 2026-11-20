# Community leveling

Abud's Discord leveling is chat-only. It awards XP for eligible community messages,
provides rank cards and a per-server leaderboard, and can announce level-ups.
There are no role rewards, automatic role changes, voice-channel XP, audio capture,
transcription, or Discord music playback.

The feature defaults off globally. Each server must opt in using an administrator-only
setup command. Creating or updating this configuration does not change live VPS
settings or guild state.

## Commands

| Command | Purpose |
| --- | --- |
| `/rank [member]` | Public PNG rank card with total/chat XP and server rank |
| `/leaderboard [page]` | Public per-server XP ranking, ten participants per page |
| `/leveling setup enabled:true` | Enable chat XP and configure announcements |
| `/leveling setup enabled:true chat:false` | Disable chat XP |
| `/leveling setup enabled:true announcement:#levels` | Opt into level-up notifications |
| `/leveling setup enabled:true notify:false` | Disable level-up notifications |
| `/leveling setup enabled:false` | Pause XP earning without deleting totals |
| `/leveling exclude channel:#channel` | Exclude a text channel and its threads |
| `/leveling include channel:#channel` | Remove a channel exclusion |
| `/leveling config` | View settings, XP limits and excluded channels |

Rank cards are rendered in memory with Pillow and DejaVu fonts. The bot needs Send
Messages, Attach Files and View Channel where `/rank` is used, and Embed Links for
leaderboards and announcements. Commands are guild-only; bots do not receive XP.
Administrator permissions are enforced at runtime for setup, config and exclusions.

Announcements are disabled until a text channel is selected. Notifications do not ping
users or roles. Delivery failure does not roll back committed XP or retry the award.

## XP and anti-farming

- Chat awards **15–25 XP** with a per-member, per-server 60-second cooldown.
- The daily chat cap is **1,000 XP**, resetting at midnight WIB.
- Bot, webhook, DM and system messages do not count. Short, command-like, URL-only,
  mention-only, emoji-only and repetitive content is rejected.
- Normalized message fingerprints prevent the same message earning repeatedly within
  ten minutes. At most ten hashes per member are retained; raw message text is not stored
  by the leveling feature.
- Excluded text channels also exclude their threads through the parent channel ID.
- Level thresholds use total XP: level L starts at 100 × L².
- The heuristic reduces obvious farming but cannot prevent every coordinated or
  semantically varied spam attempt.

Historical voice-related XP columns remain in the SQLite schema for compatibility with
existing databases, but Discord leveling no longer awards, displays or processes voice XP.
The setup path explicitly disables the legacy voice source.

## Persistence and deployment

SQLite WAL database in the dedicated `abud-leveling` volume at
`/app/leveling/levels.db`, owned by bot UID 10001. Back up the volume before replacing
it. Non-Compose installs must set `ABUD_LEVELING_DB` to a writable persistent path.
Settings, exclusions, per-server member IDs/display names, totals, chat counters,
cooldowns and duplicate hashes are stored. No raw chat text is stored by this feature.

Set `ABUD_LEVELING_ENABLED=true` only when ready to enable the module globally. Then
an administrator opts the server in with `/leveling setup enabled:true`. Keep
announcements disabled or use a test channel during initial acceptance. This branch
does not change the VPS or enable the feature.

## Acceptance checks

1. Verify the bot image includes Pillow/fonts and UID 10001 can write the persistent DB.
2. Confirm no XP before global and per-server opt-in.
3. Test chat cooldowns, duplicate messages, excluded channels and threads.
4. Confirm level-up announcements are opt-in and never ping members.
5. Restart the bot and verify settings, totals and anti-farming state persist.
6. Confirm non-admins cannot change settings and XP never grants, edits or removes roles.
7. Confirm the Discord bot no longer registers music or voice playback commands. The
   separate browser-based Voice Chat feature remains independent.
