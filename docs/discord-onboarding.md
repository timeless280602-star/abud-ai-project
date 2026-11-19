# Welcome and Reaction Roles (draft)

Abud can welcome new human members and let members select pre-approved roles by reacting
to an administrator-published message. These are **self-selected roles**, entirely
independent of the leveling module. XP/level-ups still never grant, remove or edit roles.
This module does not add moderation bans, kicks, timeouts, autoroles on join or AutoMod.

The feature defaults off. No real channel, member role, welcome, reaction or Discord
Developer Portal setting is changed by preparing this draft.

## Welcome

Administrator commands:

- `/welcome setup enabled:true channel:#welcome`
- `/welcome setup enabled:true template:Hai {member}, selamat datang di {server}!`
- `/welcome setup enabled:true ping:true` opts into pinging only the joining member.
- `/welcome setup enabled:false` pauses, preserving other settings.
- `/welcome preview` shows a private preview for the requesting admin.
- `/welcome test` sends a sample for the requesting admin in the configured channel,
  **without pinging**, even when real welcomes are configured to ping.
- `/welcome config` shows status and the last sanitized module error.

Allowed template tokens: `{member}` (member mention), `{name}` (display name), `{server}`,
`{count}` (Discord's reported member count, or a dash if unavailable). Templates are
1–1,500 characters. Substitution is literal and simultaneous; no code/format expression
is evaluated, and inserted names cannot introduce further token substitution.

The welcome embed has a red Abud accent, welcome title and joining member's Discord
avatar thumbnail. Bots are ignored. Default ping is off; everyone/role pings are always
disabled. Real welcomes only run on join events, not a scan of existing members. The
last successful join timestamp per member is persisted to suppress duplicate join
notices across restarts; a real later rejoin can receive another welcome. Preview/test
does not change that record. A crash after Discord accepts a send but before SQLite
records it can duplicate a notice. Failed welcome delivery is recorded as an error,
not retried automatically. No welcome backlog is delivered after downtime.

## Reaction role workflow

Only Administrators can configure panels; role/emoji/channel checks also run at runtime.
Roles must already exist: Abud does not create roles or change their permissions.

1. `/reactionrole create title:Pilih game mode:multiple` creates a **database draft**,
   without posting a public message. Optional description supports up to 1,500 characters.
2. `/reactionrole bind panel:1 emoji:🎮 role:@Gamer` selects an existing server role.
   Repeat for other choices. Unicode and usable custom emoji from this server are supported.
3. `/reactionrole preview panel:1` shows the embed privately without pinging/assigning roles.
4. `/reactionrole publish panel:1 channel:#pilih-role` posts the panel, seeds its emoji,
   and activates raw reaction handlers. A failed publish stays disabled; retry reuses the
   remembered message rather than posting a duplicate when possible.
5. `/reactionrole list` shows this guild's panel IDs, modes and state.
6. `/reactionrole disable panel:1` pauses handling and marks the panel nonactive where
   the bot can edit its message. It preserves roles already assigned.
7. `/reactionrole unbind panel:1 emoji:🎮` removes a mapping from an inactive panel.
   Rebind as needed, preview and publish again. Live mapping edits are rejected until paused.
8. `/reactionrole delete panel:1` deletes the configuration, not member roles or the old
   public message. An administrator can delete the old message separately.

A panel's channel stays fixed after its first post. To use another channel, create a new
panel. Limits: ten panels per guild, twenty choices per panel. Drafts/disabled panels count
until deleted. `single` or `multiple` mode is chosen on creation; create a new panel to
change modes. A role cannot occupy two emoji slots in the same panel; the same role in
other panels is supported through shared claim reference counting.

### Selection and withdrawal

- `multiple`: members can hold several selected roles.
- `single`: selecting another emoji withdraws previous bot-owned choices in that panel
  and removes the member's old reaction markers. This mode additionally requires Manage
  Messages so the UI reflects the active selection. This does not strip preexisting or
  independently granted roles just to enforce a one-role appearance.
- Removing a normal reaction releases the corresponding choice. Abud removes a role
  only if it originally added that role and no other recorded panel claim still needs it.
- Roles held before the reaction are not marked bot-owned and are not removed on unreact.
  Atomic role endpoints affect only the selected role, preserving unrelated roles.
- Fresh membership/roles are fetched for each relevant event; raw reaction handlers work
  on messages absent from the Discord message cache. Events are serialized to prevent
  repeated add/remove events from corrupting claim ownership. Bots, pending membership
  screening, DMs, other messages/channels/guilds and super/burst reactions are ignored.
- Member departure clears claim/provenance records, so a later join's manually assigned
  roles cannot be mistaken for an old bot grant.
- Config changes do not backfill existing reaction selections or revoke roles en masse.
  Members may need to remove/re-add their reaction after a mapping change.

## Permission policy

Abud needs View Channel, Send Messages and Embed Links for welcomes and panel messages;
Read Message History and Add Reactions for reaction panels; Manage Messages for single
mode. It needs **Manage Roles**, with its highest role above every self-selectable role.
An admin configuring a role must also be above it, unless they are the guild owner.
The bot does not need Administrator for these features.

Reaction roles reject @everyone, managed/integration roles, roles at/above Abud's highest
role, and roles granting privileges outside a conservative allowlist of ordinary chat/
voice/media participation. Administrator, moderation/management, mass mention, pinning,
slowmode bypass and unknown future permission bits are rejected. Role-specific channel
permission overwrites are checked too, preventing a zero-permission guild role from
carrying channel moderation privileges through an overwrite. Role/overwrite safety and
bot hierarchy are rechecked on additions and bot-owned withdrawals against Discord's
current cached guild state. Role/permission changes can block an existing mapping until
an admin repairs it; the bot does not attempt to strip a newly privileged role automatically.

These checks cover native Discord permissions, not privileges another bot gives to
arbitrarily named roles. Administrators must review cross-bot access when choosing roles
(e.g. a role another bot treats as staff). Panel configuration is not exposed as an LLM
action and does not trust model-supplied member/guild identities.

## Failure and lifecycle behavior

If all reactions, one whole emoji's reactions, or a panel message are cleared/deleted,
its handler is disabled without mass role removal. Republish to restore a usable panel;
existing member roles/claims are preserved. Disabling/deleting configuration is not an
implicit command to revoke members' roles. Discord/API failures preserve withdrawal
tracking so a later explicit reaction retry can succeed. If an assignment cannot be
recorded, Abud attempts to undo just that unrecorded addition. Failed single-choice
cleanup may temporarily leave more than one role until a retry/admin correction.

Discord mutations and SQLite commits are not one atomic transaction. Crashes or lost API
acknowledgements can leave a role without complete provenance; no exactly-once guarantee
is claimed. There is no background reconciliation of missed reactions/role changes during
bot downtime. If a moderator manually removes a bot-owned role and reassigns the same role
while its old claim exists, ownership cannot distinguish the manual reassignment; use a
fresh panel/claim or review the saved configuration. Real guild acceptance should cover
this operational limitation before enabling access-sensitive roles.

State is stored in a dedicated SQLite WAL database at `/app/onboarding/community.db`,
with Compose volume `abud-onboarding`, owned by UID 10001. It stores welcome settings,
last successful join timestamps, panel definitions/message IDs, mappings and member role
claim/provenance IDs, not chat history. Back up the volume before replacing it. Non-Compose
installs can set `ABUD_ONBOARDING_DB`. Run one bot process per database. Runtime errors
are sanitized into `/welcome config` or `/reactionrole list` and logged by exception type.

## Enable for the later batch test

```dotenv
ABUD_ONBOARDING_ENABLED=true
```

Before starting a bot with this flag, enable **Server Members Intent** in the Discord
Developer Portal for its application. The code requests Members only with this flag;
Reactions is also enabled. Startup does not bulk-chunk all guild members. Reactions use
fresh REST membership, while welcome/member departure events need the members gateway
intent. With the feature off, the earlier bot does not acquire a new privileged intent.
Rebuild/recreate with the persistent volume, then configure the guild through the above
admin commands. This branch does not perform those steps or deploy to the VPS.

## Later acceptance checklist

1. Build the image and validate Compose/volume write permissions. Register welcome,
   reactionrole, leveling/rank, music/play, notify and existing AI commands together.
2. Use an actual second account joining a test guild; check avatar/template/member count,
   no default ping, opt-in member-only ping and preview/test without ping. Restart and
   retry duplicate/rejoin events; check missing channel permissions.
3. Publish Unicode and custom emoji panels in multiple and single modes. Check assignment,
   unreact withdrawal, manual preexisting roles, two panels referencing the same role,
   rapid toggles, noncached messages, member leave/rejoin and a bot/pending member.
4. Try unsafe roles, managed roles, role hierarchy limits and a channel moderation
   overwrite. Change an approved role to privileged after publishing; confirm it stops
   being self-selectable. Check an ordinary member cannot configure/publish panels.
5. Remove bot Manage Roles/Manage Messages, interrupt the bot/database, clear/delete a
   panel and retry publish. Confirm no broad role wipe or changes to unrelated roles.
6. Restart the bot and inspect persistence; document any offline missed-event/manual
   ownership corrections before using access-sensitive roles. Verify a level-up still
   never assigns a role and all other Abud modules continue working.

References:
- https://discordpy.readthedocs.io/en/stable/intents.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.on_raw_reaction_add
- https://discordpy.readthedocs.io/en/stable/api.html#discord.on_member_join
- https://docs.discord.com/developers/topics/permissions
