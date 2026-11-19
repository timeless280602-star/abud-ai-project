# Ticket Support (draft)

This implements the approved first version: panel/button, help form, private channel,
claim/unclaim, confirmed close with reason, staff reopen, one active ticket/member,
status history/logs, and persistent configuration/buttons. Transcripts, ratings, FAQ AI,
automatic ticket deletion and automatic closure are not included. No live channel, guild
setting, support role, message or deployment is changed by preparing this branch.

## Member and staff flow

1. A member clicks **Buka Tiket** on the current public support panel.
2. A private selector offers Community Help, Store Issue or Report. A modal collects a
   10–1,200 character summary. The form/picker belongs to the requesting member and expires
   after five/two minutes respectively; opening a form does not reserve a ticket.
3. Submission rechecks panel/settings/membership. Abud creates `ticket-00001` using
   explicit private overwrites **in the creation request**. It does not create a public
   room and hide it later, nor copy the category's other role/member overrides.
4. A private control embed shows ticket number, kind, summary, owner, state and agent.
   Support may Claim; another staff member cannot steal a claim. The claimant or an
   Administrator may Unclaim. Claims do not change channel membership.
5. The opener or support can request Close. A reason (3–500 characters) and an explicit
   **Ya, Tutup Tiket** confirmation are required. Cancel/expiry changes nothing. The
   final click rechecks actor, channel, authorization and current state.
6. Closure makes the channel read-only for the opener and support role, retains its
   conversation and last agent, and updates the control buttons. The bot remains able
   to update status. Discord Administrators bypass channel restrictions as usual.
7. Only support/Admin may Reopen. It is blocked if the opener already has another active
   ticket, has left the guild, or has not completed membership screening.

Only the opener, selected support role and bot get explicit access. Native Discord
Administrators (including other administrator bots) retain access. Privileged humans
can manually change channel permissions; this module cannot make data secret from guild
administrators. Routine ticket actions restore the canonical privacy overwrites rather
than inheriting later category changes. Creating threads in ticket rooms is denied.

Limits: one active/reserved ticket per member per guild, 60 seconds between opening
requests, and 50 existing/reserved ticket channels per guild including closed archives.
There is no automatic archive deletion. Administrators can manually delete old Discord
channels when retention is no longer needed; history is retained, the active/capacity
slot is released, and startup checks authoritative guild channel listings for deletions
missed while offline. API failures are not interpreted as proof of channel deletion.

## Administrator configuration

After the later batch activation, create/select a trusted staff-only role, ticket category,
and **private** support log channel. Review existing holders before selecting any staff
role. Abud does not create or grant the support role itself.

```text
/ticket setup enabled:true category:TICKETS support:@Support log_channel:#ticket-log
/ticket preview
/ticket panel channel:#support
/ticket config
```

Optional setup fields change title/description. Later setup calls preserve omitted
values. `enabled:false` pauses **new** tickets; staff can still handle existing ones.
Changing category, support or log applies to future tickets; historical tickets keep
those IDs so a reconfiguration does not silently grant a new team access to old cases.
Old public panels stop accepting requests if a new panel is published elsewhere. Publish
in the same channel edits/reuses the known message, or replaces a deleted panel message.

The log channel must hide @everyone and ordinary roles/members, while allowing the
configured support/Admin and Abud. Validation examines role permissions and explicit
member overwrites, including ordinary roles with View Channel. The bot rechecks log
privacy before every status notification and never falls back to a public channel.

### Existing commands

| Command | Authorization and effect |
| --- | --- |
| `/ticket setup`, `preview`, `panel`, `config` | Administrator configuration/publication |
| `/ticket status` | Opener or ticket's support; status and control refresh in that room |
| `/ticket claim`, `unclaim` | Support; unclaim another agent requires Administrator |
| `/ticket close reason:...` | Opener/support; displays confirmation, does not close immediately |
| `/ticket reopen` | Ticket's support/Admin; closed tickets only |
| `/ticket history [ident] [page]` | Authorized support/Admin; private lifecycle metadata/reasons |
| `/ticket repair ident:...` | Administrator recovery of interrupted operations |

Discord status logs include ticket ID, opener/action actor, state and channel link only.
They omit the private problem summary and closure reason. The SQLite history contains
creation time, lifecycle actors, agent claims, close/reopen actions and closure reasons;
up to 20 recent events are shown for one ticket, split into bounded private replies.
A list is ten cases/page; new staff cannot see cases assigned to a historical support
role unless they also hold it or are an Administrator. Log delivery failures do not
undo committed ticket state. No full conversation transcript is captured/exported.

## Bot permissions and privacy integration

The bot needs guild-level Manage Channels, Manage Roles, View Channel, Read Message
History, Send Messages, Embed Links, Attach Files, Add Reactions, Create Public Threads,
Create Private Threads and Send Messages in Threads. The thread flags are needed to
explicitly **deny** thread operations in the new room, because Discord validates allowed
and denied overwrite bits against bot permissions. The bot does not need Administrator,
and no Manage Roles overwrite is injected on channel creation. A category and channels
must be accessible to the bot. Real API validation remains in the acceptance checklist.

Staff roles used by this module, including historical roles protecting old archives,
are reserved from Abud reaction-role binding, publishing and runtime grants/withdrawals.
Setup rejects roles currently mapped by the running onboarding module. Existing holders
and permissions granted by other bots still require admin review; this is not a migration
or cleanup tool for an untrusted role previously assigned manually.

Managed ticket channels and their threads bypass Abud's automatic message pipeline:
no AI chat request, music execution, XP award or automatic memory save. Other Abud slash
commands are blocked there; `/ticket` remains available. Identification uses saved channel
IDs plus a non-sensitive `abud-ticket:` topic marker, protecting channels even before a
create's metadata write completes. IDs are reloaded even if the ticket module is paused
on a subsequent run; the topic marker also protects rooms if the database is unavailable.
This isolates Abud, not unrelated bots or human staff. No FAQ/AI integration is activated.

## Persistence, restart and recovery

A dedicated SQLite WAL volume `abud-tickets` stores guild settings, panel/channel/control
IDs, a random operation marker, the initial form summary, support/log/category snapshots,
status/agent/timestamps and lifecycle reasons. Raw subsequent ticket conversation remains
in Discord. Store the volume securely and back it up; it contains private form data.
The default path is `/app/tickets/tickets.db`, writable by bot UID 10001. Non-Compose
installs may set `ABUD_TICKETS_DB`. Run one bot process per database.

Panel/control buttons use fixed custom IDs, timeout=None and persistent view registration
at startup. Forms and close confirmations intentionally do not survive a restart; request
another form/confirmation. Stale control-message IDs cannot authorize operations. A missing
control message can be restored with `/ticket status` in a stable ticket room.

Ticket creation reserves an ID/active slot before calling Discord. Ambiguous errors keep
the reservation rather than creating another channel. A private topic marker identifies
the exact operation without putting the problem summary in a channel name/topic. Admin
`/ticket repair` searches a fresh channel list for that marker: one match is resumed,
multiple matches require manual review, and no match only releases the reservation after
five minutes. It never deletes an unknown channel. Close/reopen persist transition intent
before permission edits; known interrupted transitions resume in a background startup job.

Discord operations and SQLite are not atomic. A crash/lost acknowledgement can still leave
an orphan channel/control message or stale status log; manual review may be needed. Recovery
is conservative, not an exactly-once guarantee. A channel whose marker is changed is not
modified by repair/actions. Recovery depends on existing support/category access and the
bot's permissions. User-visible success follows actual channel/state operations, not form
parsing alone. Errors shown in Discord/logs omit raw HTTP bodies, credentials and summaries.

## Activation and later acceptance

```dotenv
ABUD_TICKETS_ENABLED=true
```

Rebuild/recreate with the new persistent volume only when the batch is approved for live
testing. Tickets itself does not add a privileged gateway intent; it uses interaction
member data, REST membership and ordinary guild/channel events. Welcome's existing
Members Intent requirement is unchanged. No activation/deployment is performed here.

Before release:

1. Build the image, validate merged Compose and UID 10001's volume access. Register ticket,
   onboarding, leveling, music, notifications and AI commands together.
2. With a non-Administrator bot and real test accounts, inspect the new room's ACL at
   creation: opener/support/bot visible, an ordinary member and unrelated role excluded.
   Test a public category and confirm its extra permissions were not copied.
3. Open via button/type/form, double-click/submit concurrently and check the per-member
   limit/cooldown. Inspect summary privacy in channel, log and bot/API/memory traffic.
4. Exercise agent claim conflicts, unclaim, close reason/confirmation/cancel/expiry,
   read-only owner/support, native Administrator bypass, reopen and the active-ticket rule.
5. Restart and reuse old panel/control buttons. Interrupt creation/permission updates,
   delete a control/panel/channel while offline and test conservative recovery without
   duplicate channels or unintended deletions. Check the 50-channel archive cap.
6. Rotate support/log/category settings, verify historical staff boundaries, public log
   rejection and reaction-role reservation. Remove bot permissions; ensure errors do not
   claim success or reveal private text. Test independent guilds and the full feature batch.

References:
- https://discordpy.readthedocs.io/en/stable/api.html#discord.Guild.create_text_channel
- https://discordpy.readthedocs.io/en/stable/api.html#discord.Client.add_view
- https://docs.discord.com/developers/resources/guild#create-guild-channel
- https://docs.discord.com/developers/topics/permissions
