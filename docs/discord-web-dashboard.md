# Discord Bot workspace dashboard

Open the new sidebar category **Komunitas → Discord Bot** (/#discord-bot).
Log in with a completed account linked to Discord. Select a guild in which the
bot is present and the account is Owner/Administrator. This dedicated workspace
does not grant access to any other ABUD dashboard module, memory, provider
credentials, or global flags. Every action authenticates the existing site
session, checks same-origin JSON, resolves the linked Discord identity on the
server, and fetches the current Discord member through the private bot gateway.
The gateway requires the internal bearer secret and runs only allowlisted
actions; browser identity/permissions and guild resources are never trusted.
No new publicly published bot port or database is required.

## UI
- Leveling: enabled, chat/voice XP, optional announcements, channel exclusions.
- Welcome: enabled, channel, message template, mention, local preview and
  send-test (requires saved settings).
- Reaction roles: draft panels, emoji/role mappings, publish, disable, delete.
  Existing manager checks role hierarchy and blocks staff/support roles.
- Tickets: enabled, category, support role, private log, panel copy and publish.
  No private ticket contents exposed in this dashboard.
- YouTube notification subscriptions: add, edit, pause, test without ping and
  remove. Existing TikTok subscriptions may be managed, but creating a TikTok
  subscription requires the provider and existing slash command.
- AI voice and music: availability and per-guild session presence, usage help.
  These features currently have global enable flags, not durable per-guild
  settings. Consent and playback/session controls remain in Discord.

Writes use the existing bot managers/stores, not a duplicate web database.
The UI refreshes after successful writes. Multiple administrators can edit
the same settings; there is no optimistic concurrency/merge of unsaved forms.
A timeout may mean an action already succeeded; reload before retrying.
Audit metadata is written to existing dashboard audit logs on successful writes;
the bot also records action, actor and guild without payload or credentials.

## Before release
Run frontend npm ci, npm test, npm run build; run Python unittest discovery
with the existing CI configuration. Test on staging with fake/isolated data.
Test anonymous access, Google-only accounts, regular members, admins in guild A
but not B, revoked admin, invalid cross-guild IDs, CSRF origin, missing internal
key, unavailable bot, role safety and private ticket log. Test desktop/mobile
and all saves, reloads, publish and test actions in a test server.
Do not deploy this branch until CI and live authorization checks pass.
The web API and bot must be upgraded together, preserving the currently enabled
voice/music/YouTube Compose overlays and all data volumes. Keep Ollama stopped.
Adventure is out of scope.

## Invite ABUD
The login page, Command Center and Discord workspace link to the public
`/discord/invite` route, which redirects to Discord guild installation with
the running bot's actual application ID. No login to the ABUD website is
required to start an invite. The user's Discord account must have permission
to install apps in the selected guild. The link requests bot and
applications.commands scopes, without Administrator, Manage Guild or
Mention Everyone. Manage Messages supports single-choice reaction roles;
thread permissions support private ticket ACLs. Optional @everyone/@here
notification permission can be granted by a guild admin if desired.
Check Guild Install and Public Bot in the actual bot's Developer Portal;
an invite link cannot override a private application or installation settings.
After authorization, return to the existing tab and refresh the server list.
Only guild owners/administrators can use the settings even if another
member has permission to install a bot. Test public redirect and actual
installation in a disposable guild. The link is unavailable when the bot
gateway cannot provide its application ID. No tokens are sent to Discord
or the browser by this route; only public installation parameters.

### Reaction emoji picker
Choose a common Unicode emoji or a usable custom emoji listed from the selected server. The manual field accepts pasted emoji and unique `:name:` shorthand for custom emojis in that server; ambiguous or unavailable names are rejected. The backend still validates the selected emoji and role before storing a mapping. Existing panels are unchanged.
