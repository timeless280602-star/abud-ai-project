"""Welcome and reaction-role policy/ownership contracts without a Discord login."""

import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from app.discord_onboarding import Onboarding, panel_embed
from app.onboarding import (
    OnboardingError,
    OnboardingStore,
    emoji_key,
    parse_emoji,
    validate_role,
)
from app.onboarding_commands import install_onboarding_commands


class Role:
    def __init__(self, guild, ident, position=5, **permissions):
        self.guild, self.id, self.position = guild, ident, position
        self.permissions = discord.Permissions(**permissions)
        self.managed = False

    def __ge__(self, other):
        return self.position >= other.position

    def is_default(self):
        return self.id == self.guild.id


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "db")
        self.store = OnboardingStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_guild_scope_limits_and_persistent_drafts(self):
        ident = self.store.create(1, "Games", "Choose", "multiple")
        self.store.bind(1, ident, "u:🎮", "🎮", 10)
        self.store.close()
        self.store = OnboardingStore(self.path)
        self.assertEqual(self.store.mappings(ident)[0]["role"], 10)
        with self.assertRaises(OnboardingError):
            self.store.panel(2, ident)
        for _ in range(9):
            self.store.create(1, "Games", "Choose", "multiple")
        with self.assertRaises(OnboardingError):
            self.store.create(1, "Overflow", "", "multiple")
        self.store.create(2, "Other", "", "single")

    def test_mapping_limit_duplicate_roles_and_active_edit_guard(self):
        panel = self.store.create(1, "Test", "", "multiple")
        for i in range(20):
            self.store.bind(1, panel, str(i), str(i), i + 100)
        with self.assertRaises(OnboardingError):
            self.store.bind(1, panel, "extra", "extra", 999)
        with self.assertRaises(OnboardingError):
            self.store.bind(1, panel, "0", "0", 101)
        self.store.activate(1, panel, 100, 200)
        with self.assertRaises(OnboardingError):
            self.store.unbind(1, panel, "0")
        self.assertIsNone(self.store.by_message(2, 200))

    def test_ownership_shared_claims_and_member_leave_persist(self):
        first = self.store.create(1, "One", "", "multiple")
        second = self.store.create(1, "Two", "", "multiple")
        self.store.claim(first, 1, 10, "u:🎮", 100, owned=True)
        self.store.claim(second, 1, 10, "u:🎧", 100)
        self.store.close()
        self.store = OnboardingStore(self.path)
        self.assertTrue(self.store.owned(1, 10, 100))
        self.assertEqual(self.store.references(1, 10, 100), 2)
        self.store.unclaim(first, 10, "u:🎮")
        self.assertEqual(self.store.references(1, 10, 100), 1)
        self.store.forget_member(1, 10)
        self.assertFalse(self.store.owned(1, 10, 100))
        self.assertEqual(self.store.references(1, 10, 100), 0)

    def test_no_destructive_role_cleanup_when_configuration_is_deleted(self):
        panel = self.store.create(1, "One", "", "multiple")
        self.store.claim(panel, 1, 10, "u:🎮", 100, owned=True)
        self.store.delete(1, panel)
        self.assertEqual(self.store.panels(1), [])
        # Provenance retained; deleting config does not pretend a role was removed.
        self.assertTrue(self.store.owned(1, 10, 100))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 1
        self.guild.owner_id = 999
        self.guild.name = "Community {member}"
        self.guild.member_count = 42
        self.guild.channels = []
        self.guild.me = SimpleNamespace(
            id=123,
            top_role=SimpleNamespace(position=20),
            guild_permissions=discord.Permissions(manage_roles=True),
        )
        self.guild.me.top_role = Role(self.guild, 900, 20)
        self.roles = {
            10: Role(self.guild, 10, send_messages=True),
            20: Role(self.guild, 20),
            30: Role(self.guild, 30),
        }
        self.guild.get_role.side_effect = self.roles.get
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id = 100
        self.channel.guild = self.guild
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            add_reactions=True,
            manage_messages=True,
        )
        self.message = SimpleNamespace(
            id=200,
            author=SimpleNamespace(id=123),
            jump_url="https://discord.com/channels/1/100/200",
            edit=AsyncMock(),
            add_reaction=AsyncMock(),
            remove_reaction=AsyncMock(),
        )
        self.channel.send = AsyncMock(return_value=self.message)
        self.channel.fetch_message = AsyncMock(return_value=self.message)
        self.guild.get_channel.return_value = self.channel
        self.member = SimpleNamespace(
            id=500,
            guild=self.guild,
            display_name="Gamer @everyone",
            bot=False,
            pending=False,
            roles=[],
            display_avatar=SimpleNamespace(
                url="https://cdn.discordapp.com/embed/avatars/0.png"
            ),
        )

        async def add(role, **kwargs):
            self.member.roles.append(role)

        async def remove(role, **kwargs):
            self.member.roles = [r for r in self.member.roles if r.id != role.id]

        self.member.add_roles = AsyncMock(side_effect=add)
        self.member.remove_roles = AsyncMock(side_effect=remove)
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.client = Mock(user=SimpleNamespace(id=123))
        self.client.get_guild.return_value = self.guild
        self.manager = Onboarding(self.client)
        self.manager.enabled = True
        self.manager.path = str(Path(self.temp.name) / "db")
        self.manager.store = OnboardingStore(self.manager.path)
        self.actor = SimpleNamespace(id=999, top_role=Role(self.guild, 800, 15))
        self.panel = self.manager.store.create(
            1, "Choose games", "React to choose", "multiple"
        )
        self.manager.store.bind(1, self.panel, "u:🎮", "🎮", 10)
        self.manager.store.activate(1, self.panel, 100, 200)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    def payload(self, emoji="🎮", message=200, channel=100, guild=1, user=500):
        return SimpleNamespace(
            guild_id=guild,
            message_id=message,
            channel_id=channel,
            user_id=user,
            emoji=discord.PartialEmoji(name=emoji),
            burst=False,
        )

    def test_role_policy_rejects_admin_moderation_managed_hierarchy_and_overwrites(
        self,
    ):
        self.assertIs(
            validate_role(self.guild, self.roles[10], self.actor), self.roles[10]
        )
        for permission in [
            "administrator",
            "ban_members",
            "manage_roles",
            "manage_messages",
            "moderate_members",
            "mention_everyone",
            "pin_messages",
        ]:
            with (
                self.subTest(permission=permission),
                self.assertRaises(OnboardingError),
            ):
                validate_role(
                    self.guild, Role(self.guild, 50, **{permission: True}), self.actor
                )
        dangerous = Role(self.guild, 50)
        dangerous.permissions = discord.Permissions(1 << 62)
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, dangerous)
        dangerous.permissions = discord.Permissions.none()
        dangerous.managed = True
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, dangerous)
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, Role(self.guild, 1))
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, Role(self.guild, 50, 20))
        non_owner = SimpleNamespace(id=600, top_role=Role(self.guild, 700, 4))
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, self.roles[10], non_owner)
        self.guild.channels = [
            SimpleNamespace(
                overwrites_for=lambda role: discord.PermissionOverwrite(
                    manage_messages=True
                )
            )
        ]
        with self.assertRaises(OnboardingError):
            validate_role(self.guild, self.roles[10])

    def test_emoji_validation_and_custom_id_stability(self):
        self.assertEqual(parse_emoji("❤️", self.guild)[0], emoji_key("❤"))
        self.assertEqual(parse_emoji("👩‍💻", self.guild)[0], emoji_key("👩‍💻"))
        custom = Mock(id=123456789012345777, is_usable=Mock(return_value=True))
        custom.__str__ = Mock(return_value="<:game:123456789012345777>")
        self.guild.get_emoji.return_value = custom
        self.assertEqual(
            parse_emoji("<:game:123456789012345777>", self.guild), ("c:123456789012345777", "<:game:123456789012345777>")
        )
        self.guild.get_emoji.return_value = None
        for text in ["not an emoji", ":)", "🎮 hello", "<:remote:123456789012345999>"]:
            with self.assertRaises(OnboardingError):
                parse_emoji(text, self.guild)

    async def test_add_remove_duplicate_events_and_restart_ownership(self):
        await asyncio.gather(
            self.manager.reaction(self.payload(), added=True),
            self.manager.reaction(self.payload(), added=True),
        )
        self.member.add_roles.assert_awaited_once()
        self.assertTrue(self.manager.store.owned(1, 500, 10))
        self.manager.store.close()
        self.manager.store = OnboardingStore(self.manager.path)
        await self.manager.reaction(self.payload(), added=False)
        self.member.remove_roles.assert_awaited_once()
        self.assertEqual(self.member.roles, [])
        await self.manager.reaction(self.payload(), added=False)
        self.assertEqual(self.member.remove_roles.await_count, 1)
        self.assertGreaterEqual(self.guild.fetch_member.await_count, 3)

    async def test_preexisting_manual_role_is_not_removed(self):
        self.member.roles = [self.roles[10], self.roles[30]]
        await self.manager.reaction(self.payload(), added=True)
        self.member.add_roles.assert_not_awaited()
        await self.manager.reaction(self.payload(), added=False)
        self.member.remove_roles.assert_not_awaited()
        self.assertEqual({r.id for r in self.member.roles}, {10, 30})

    async def test_single_choice_switch_only_removes_bot_owned_previous_role(self):
        self.manager.store.disable(1, self.panel)
        self.manager.store.db.execute(
            "UPDATE panels SET mode='single' WHERE id=?", (self.panel,)
        )
        self.manager.store.db.commit()
        self.manager.store.bind(1, self.panel, "u:🎧", "🎧", 20)
        self.manager.store.activate(1, self.panel, 100, 200)
        self.member.roles = [self.roles[30]]
        await self.manager.reaction(self.payload(), added=True)
        await self.manager.reaction(self.payload("🎧"), added=True)
        self.assertEqual({r.id for r in self.member.roles}, {20, 30})
        self.message.remove_reaction.assert_awaited_once_with("🎮", self.member)
        await self.manager.reaction(self.payload(), added=False)
        self.assertEqual({r.id for r in self.member.roles}, {20, 30})

    async def test_multiple_choice_and_shared_role_reference_counting(self):
        other = self.manager.store.create(1, "Other", "", "multiple")
        self.manager.store.bind(1, other, "u:🎧", "🎧", 10)
        self.manager.store.activate(1, other, 100, 201)
        await self.manager.reaction(self.payload(), added=True)
        await self.manager.reaction(self.payload("🎧", message=201), added=True)
        await self.manager.reaction(self.payload(), added=False)
        self.member.remove_roles.assert_not_awaited()
        await self.manager.reaction(self.payload("🎧", message=201), added=False)
        self.member.remove_roles.assert_awaited_once()

    async def test_runtime_permission_change_blocks_privilege_escalation(self):
        self.roles[10].permissions.administrator = True
        with self.assertLogs("app.discord_onboarding", level="WARNING"):
            await self.manager.reaction(self.payload(), added=True)
        self.member.add_roles.assert_not_awaited()
        self.assertIn("izin", self.manager.last_error)

    async def test_wrong_message_channel_guild_bots_pending_and_burst_are_ignored(self):
        for payload in [
            self.payload(message=999),
            self.payload(channel=999),
            self.payload(guild=2),
            self.payload(user=123),
        ]:
            await self.manager.reaction(payload, added=True)
        self.guild.fetch_member.assert_not_awaited()
        self.member.pending = True
        await self.manager.reaction(self.payload(), added=True)
        self.member.pending = False
        self.member.bot = True
        await self.manager.reaction(self.payload(), added=True)
        self.member.bot = False
        burst = self.payload()
        burst.burst = True
        await self.manager.reaction(burst, added=True)
        self.member.add_roles.assert_not_awaited()

    async def test_clearing_or_deleting_panel_disables_without_mass_role_removal(self):
        await self.manager.reaction(self.payload(), added=True)
        await self.manager.invalidated(1, [200])
        self.assertIsNone(self.manager.store.by_message(1, 200))
        await self.manager.reaction(self.payload(), added=False)
        self.member.remove_roles.assert_not_awaited()

    async def test_member_leave_clears_provenance_and_rejoin_preserves_manual_role(
        self,
    ):
        await self.manager.reaction(self.payload(), added=True)
        await self.manager.member_left(1, 500)
        self.assertFalse(self.manager.store.owned(1, 500, 10))
        await self.manager.reaction(self.payload(), added=True)
        await self.manager.reaction(self.payload(), added=False)
        self.member.remove_roles.assert_not_awaited()

    async def test_publish_checks_policy_before_post_and_failed_seeding_reuses_message(
        self,
    ):
        self.message.id = 202  # A new Discord message has a unique snowflake.
        new = self.manager.store.create(1, "New", "", "multiple")
        self.manager.store.bind(1, new, "u:🎮", "🎮", 10)
        error = discord.Forbidden(
            Mock(status=403, reason="Forbidden"), "missing reaction permission"
        )
        self.message.add_reaction.side_effect = error
        with self.assertRaises(discord.Forbidden):
            await self.manager.publish(self.guild, new, 100, self.actor)
        self.assertFalse(self.manager.store.panel(1, new)["enabled"])
        self.message.add_reaction.side_effect = None
        await self.manager.publish(self.guild, new, 100, self.actor)
        self.channel.send.assert_awaited_once()
        self.assertTrue(self.manager.store.panel(1, new)["enabled"])
        self.assertEqual(self.message.edit.call_args.kwargs["embed"].title, "New")
        with self.assertRaises(OnboardingError):
            await self.manager.publish(self.guild, new, 999, self.actor)

    async def test_unsafe_role_cannot_be_published(self):
        self.manager.store.disable(1, self.panel)
        self.roles[10].permissions.manage_roles = True
        with self.assertRaises(OnboardingError):
            await self.manager.publish(self.guild, self.panel, 100, self.actor)
        self.channel.send.assert_not_awaited()
        self.channel.fetch_message.assert_not_awaited()

    async def test_welcome_template_does_not_recurse_and_ping_only_targets_joiner(self):
        self.assertFalse(await self.manager.welcome(self.member))
        self.manager.store.set_welcome(
            1, True, 100, "Halo {member}, {server}! {count} member.", True
        )
        self.assertTrue(await self.manager.welcome(self.member))
        payload = self.channel.send.call_args.kwargs
        self.assertEqual(payload["content"], "<@500>")
        self.assertEqual(payload["allowed_mentions"].users, [self.member])
        self.assertFalse(payload["allowed_mentions"].everyone)
        self.assertFalse(payload["allowed_mentions"].roles)
        self.assertIn("Community {member}", payload["embed"].description)
        self.assertIn("42 member", payload["embed"].description)
        await self.manager.welcome(self.member, test=True)
        self.assertIsNone(self.channel.send.call_args.kwargs["content"])
        self.member.add_roles.assert_not_awaited()

    async def test_welcome_permission_failure_is_sanitized(self):
        self.manager.store.set_welcome(1, True, 100, "Hallo {member}", False)
        self.channel.permissions_for.return_value.send_messages = False
        with self.assertLogs("app.discord_onboarding", level="WARNING"):
            self.assertFalse(await self.manager.welcome(self.member))
        self.channel.send.assert_not_awaited()

    async def test_admin_only_commands_preview_and_no_leveling_coupling(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_onboarding_commands(tree, self.manager)
        self.assertTrue(tree.get_command("welcome").default_permissions.administrator)
        self.assertTrue(tree.get_command("reactionrole").guild_only)
        interaction = SimpleNamespace(
            guild=self.guild,
            guild_id=1,
            user=self.actor,
            permissions=SimpleNamespace(administrator=False),
            response=Mock(defer=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )
        with self.assertRaises(OnboardingError):
            await (
                tree.get_command("reactionrole")
                .get_command("create")
                .callback(interaction, "Nope")
            )
        interaction.permissions.administrator = True
        await (
            tree.get_command("reactionrole")
            .get_command("preview")
            .callback(interaction, self.panel)
        )
        self.channel.send.assert_not_awaited()
        self.member.add_roles.assert_not_awaited()
        self.assertFalse(
            interaction.followup.send.call_args.kwargs["allowed_mentions"].roles
        )
        self.assertIn(
            "DRAFT",
            panel_embed(
                self.manager.store.panel(1, self.panel), [], active=False
            ).footer.text,
        )
        await client.close()

    async def test_duplicate_join_notice_survives_restart_but_rejoin_is_new(self):
        self.manager.store.set_welcome(1, True, 100, "Halo {member}", False)
        self.member.joined_at = datetime.fromisoformat("2026-11-18T10:00:00+00:00")
        await asyncio.gather(
            self.manager.welcome(self.member), self.manager.welcome(self.member)
        )
        self.channel.send.assert_awaited_once()
        self.manager.store.close()
        self.manager.store = OnboardingStore(self.manager.path)
        self.assertFalse(await self.manager.welcome(self.member))
        self.member.joined_at += timedelta(hours=1)
        self.assertTrue(await self.manager.welcome(self.member))
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_unrecorded_role_addition_is_rolled_back_when_database_write_fails(
        self,
    ):
        with patch.object(
            self.manager.store,
            "claim",
            side_effect=sqlite3.OperationalError("private db path"),
        ), self.assertLogs("app.discord_onboarding", level="WARNING") as logs:
            await self.manager.reaction(self.payload(), added=True)
        self.assertEqual(self.member.roles, [])
        self.member.remove_roles.assert_awaited_once()
        self.assertNotIn("private db path", " ".join(logs.output))
        self.assertFalse(self.manager.store.owned(1, 500, 10))

    async def test_role_api_failures_do_not_pretend_assignment_or_removal_succeeded(
        self,
    ):
        denied = discord.Forbidden(
            Mock(status=403, reason="Forbidden"), "permission denied"
        )
        original_add = self.member.add_roles.side_effect
        self.member.add_roles.side_effect = denied
        with self.assertLogs("app.discord_onboarding", level="WARNING"):
            await self.manager.reaction(self.payload(), added=True)
        self.assertEqual(self.manager.store.claims(self.panel, 500), [])
        self.member.add_roles.side_effect = original_add
        await self.manager.reaction(self.payload(), added=True)
        original_remove = self.member.remove_roles.side_effect
        self.member.remove_roles.side_effect = denied
        with self.assertLogs("app.discord_onboarding", level="WARNING"):
            await self.manager.reaction(self.payload(), added=False)
        self.assertEqual(len(self.manager.store.claims(self.panel, 500)), 1)
        self.assertTrue(self.manager.store.owned(1, 500, 10))
        self.member.remove_roles.side_effect = original_remove
        await self.manager.reaction(self.payload(), added=False)
        self.assertEqual(self.member.roles, [])

    async def test_single_mode_requires_reaction_cleanup_permission_before_assignment(
        self,
    ):
        self.manager.store.db.execute(
            "UPDATE panels SET mode='single' WHERE id=?", (self.panel,)
        )
        self.manager.store.db.commit()
        self.channel.permissions_for.return_value.manage_messages = False
        with self.assertLogs("app.discord_onboarding", level="WARNING"):
            await self.manager.reaction(self.payload(), added=True)
        self.member.add_roles.assert_not_awaited()

    async def test_remapped_emoji_withdraws_original_claim_before_tracking_new_role(
        self,
    ):
        await self.manager.reaction(self.payload(), added=True)
        self.manager.store.disable(1, self.panel)
        self.manager.store.bind(1, self.panel, "u:🎮", "🎮", 20)
        self.manager.store.activate(1, self.panel, 100, 200)
        await self.manager.reaction(self.payload(), added=True)
        self.assertEqual([r.id for r in self.member.roles], [20])
        self.assertTrue(self.manager.store.owned(1, 500, 20))
        self.assertFalse(self.manager.store.owned(1, 500, 10))
        await self.manager.reaction(self.payload(), added=False)
        self.assertEqual(self.member.roles, [])

    async def test_startup_and_close_are_idempotent(self):
        old = self.manager.store
        await self.manager.start()
        self.assertIs(old, self.manager.store)
        await self.manager.close()
        await self.manager.close()
        with (
            patch(
                "app.discord_onboarding.OnboardingStore",
                side_effect=OSError("private path"),
            ),
            self.assertLogs("app.discord_onboarding", level="WARNING"),
        ):
            await self.manager.start()
        self.assertIsNone(self.manager.store)
