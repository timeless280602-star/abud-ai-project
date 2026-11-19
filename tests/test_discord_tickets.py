"""Support ticket persistence, privacy, authorization and UI contracts without login."""

import asyncio
import importlib
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from app.discord_tickets import PARTICIPANT_PERMS, Tickets
from app.ticket_commands import install_ticket_commands
from app.ticket_store import TicketError, TicketStore
from app.ticket_ui import (
    ConfirmClose,
    TicketControls,
    TicketForm,
    TicketKind,
    TicketPanel,
)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "db")
        self.store = TicketStore(self.path)
        self.store.configure(1, True, 2, 10, 3, "Support", "Open ticket")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def reserve(self, owner=500):
        return self.store.reserve(1, owner, "community", "Private issue summary")

    def test_one_active_ticket_and_cooldown_survive_restart(self):
        row = self.reserve()
        self.store.close()
        self.store = TicketStore(self.path)
        with self.assertRaises(TicketError):
            self.reserve()
        self.store.state(1, row["id"], "closed", 500, "Selesai")
        with self.assertRaisesRegex(TicketError, "60 detik"):
            self.reserve()
        with patch("app.ticket_store.time.time", return_value=time.time() + 61):
            second = self.reserve()
        self.assertNotEqual(second["id"], row["id"])

    def test_reopen_unique_constraint_guild_scope_and_history(self):
        first = self.reserve()
        self.store.state(1, first["id"], "closed", 500, "Selesai")
        with patch("app.ticket_store.time.time", return_value=time.time() + 61):
            self.reserve()
        with self.assertRaises(TicketError):
            self.store.state(1, first["id"], "reopening", 600)
        with self.assertRaises(TicketError):
            self.store.get(2, first["id"])
        self.assertEqual(self.store.history(2), [])
        self.assertEqual(self.store.events(first["id"])[0]["reason"], "Selesai")

    def test_category_support_snapshot_and_historic_role_reservation(self):
        row = self.reserve()
        self.store.configure(1, True, 20, 30, 40, "New support", "New settings")
        self.assertEqual(self.store.get(1, row["id"])["support"], 10)
        self.assertIn((1, 10), self.store.reserved())
        self.assertIn((1, 30), self.store.reserved())
        self.store.attach(1, row["id"], 200)
        self.assertIn(200, self.store.protected())

    def test_pause_input_validation_and_server_channel_cap(self):
        with self.assertRaises(TicketError):
            self.store.reserve(1, 500, "bad", "Description")
        with self.assertRaises(TicketError):
            self.store.reserve(1, 500, "report", "short")
        for ident in range(50):
            self.reserve(ident + 1000)
        with self.assertRaisesRegex(TicketError, "50 channel"):
            self.reserve()
        self.store.configure(1, False, 2, 10, 3, "Support", "Open ticket")
        with self.assertRaisesRegex(TicketError, "dijeda"):
            self.reserve(9000)


def role(ident, *, managed=False, permissions=None):
    result = Mock(spec=discord.Role)
    result.id = ident
    result.managed = managed
    result.permissions = permissions or discord.Permissions.none()
    result.is_default.return_value = ident == 1
    result.is_bot_managed.return_value = managed
    result.tags = SimpleNamespace(bot_id=123 if managed else None)
    return result


def member(ident, guild, roles=(), admin=False):
    result = Mock(spec=discord.Member)
    result.id = ident
    result.guild = guild
    result.bot = False
    result.pending = False
    result.roles = list(roles)
    result.guild_permissions = discord.Permissions(administrator=admin)
    return result


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 1
        self.guild.owner_id = 999
        self.guild.unavailable = False
        self.everyone = role(1)
        self.support = role(10)
        self.common = role(20, permissions=discord.Permissions(view_channel=True))
        self.bot_role = role(30, managed=True)
        self.guild.roles = [self.everyone, self.support, self.common, self.bot_role]
        for item in self.guild.roles:
            item.guild = self.guild
        self.guild.default_role = self.everyone
        self.guild.me = member(123, self.guild, [self.bot_role])
        self.guild.me.guild_permissions = discord.Permissions(
            **{
                name: True
                for name in (*PARTICIPANT_PERMS, "manage_channels", "manage_roles")
            }
        )
        self.owner = member(500, self.guild)
        self.agent = member(600, self.guild, [self.support])
        self.other_agent = member(601, self.guild, [self.support])
        self.admin = member(999, self.guild, admin=True)
        self.outsider = member(700, self.guild)
        self.members = {
            500: self.owner,
            600: self.agent,
            601: self.other_agent,
            999: self.admin,
            700: self.outsider,
        }
        self.guild.get_role.side_effect = {
            10: self.support,
            1: self.everyone,
            20: self.common,
            30: self.bot_role,
        }.get
        self.guild.fetch_member = AsyncMock(
            side_effect=lambda ident: self.members[ident]
        )
        self.category = Mock(spec=discord.CategoryChannel)
        self.category.id = 2
        self.category.guild = self.guild
        self.log_channel = Mock(spec=discord.TextChannel)
        self.log_channel.id = 3
        self.log_channel.guild = self.guild
        self.log_channel.overwrites = {}
        self.log_channel.permissions_for.side_effect = lambda target: (
            discord.Permissions(
                view_channel=target.id in (10, 30, 123, 999),
                send_messages=True,
                embed_links=True,
            )
        )
        self.log_channel.send = AsyncMock()
        self.panel_channel = Mock(spec=discord.TextChannel)
        self.panel_channel.id = 4
        self.panel_channel.guild = self.guild
        self.panel_channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, send_messages=True, embed_links=True
        )
        self.panel_message = SimpleNamespace(
            id=400,
            author=SimpleNamespace(id=123),
            jump_url="https://discord.com/channels/1/4/400",
            edit=AsyncMock(),
        )
        self.panel_channel.fetch_message = AsyncMock(return_value=self.panel_message)
        self.panel_channel.send = AsyncMock(return_value=self.panel_message)
        self.channels = {2: self.category, 3: self.log_channel, 4: self.panel_channel}
        self.guild.get_channel.side_effect = self.channels.get
        self.guild.fetch_channel = AsyncMock(
            side_effect=lambda ident: self.channels[ident]
        )
        self.guild.fetch_channels = AsyncMock(
            side_effect=lambda: list(self.channels.values())
        )

        async def create(name, **kwargs):
            ident = 200 + len([key for key in self.channels if key >= 200])
            channel = Mock(spec=discord.TextChannel)
            channel.id = ident
            channel.name = name
            channel.guild = self.guild
            channel.topic = kwargs["topic"]
            channel.overwrites = kwargs["overwrites"]
            message = SimpleNamespace(
                id=1000 + ident, author=SimpleNamespace(id=123), edit=AsyncMock()
            )
            channel.send = AsyncMock(return_value=message)
            channel.fetch_message = AsyncMock(return_value=message)

            async def edit(**changes):
                if "overwrites" in changes:
                    channel.overwrites = changes["overwrites"]
                return channel

            channel.edit = AsyncMock(side_effect=edit)
            self.channels[ident] = channel
            return channel

        self.guild.create_text_channel = AsyncMock(side_effect=create)
        self.client = Mock(user=SimpleNamespace(id=123))
        self.client.get_guild.return_value = self.guild
        self.manager = Tickets(self.client)
        self.manager.enabled = True
        self.manager.path = str(Path(self.temp.name) / "db")
        self.manager.store = TicketStore(self.manager.path)
        self.manager.store.configure(
            1, True, 2, 10, 3, "Support", "Open private ticket"
        )
        self.manager.store.panel(1, 4, 400)
        self.manager.snapshots()

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    def context(self, who=None, channel=None, message=None):
        channel = channel or self.panel_channel
        return SimpleNamespace(
            guild=self.guild,
            guild_id=1,
            user=who or self.owner,
            channel=channel,
            channel_id=channel.id,
            message=message or self.panel_message,
            response=Mock(
                defer=AsyncMock(),
                send_message=AsyncMock(),
                edit_message=AsyncMock(),
                send_modal=AsyncMock(),
                is_done=Mock(return_value=True),
            ),
            followup=Mock(send=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

    async def opened(self):
        row = await self.manager.open(
            self.context(), "community", "Sensitive order issue summary", 400
        )
        return row, self.channels[row["channel"]]

    async def test_private_channel_created_with_explicit_acl_not_category_inheritance(
        self,
    ):
        row, channel = await self.opened()
        acl = self.guild.create_text_channel.call_args.kwargs["overwrites"]
        self.assertEqual(
            set(acl), {self.everyone, self.guild.me, self.owner, self.support}
        )
        self.assertFalse(acl[self.everyone].view_channel)
        self.assertTrue(acl[self.owner].send_messages)
        self.assertFalse(acl[self.owner].create_private_threads)
        self.assertEqual(row["state"], "open")
        self.assertTrue(self.manager.protected(channel))
        self.assertNotIn("Sensitive", str(self.log_channel.send.call_args))

    async def test_double_open_is_serialized_and_only_one_channel_is_created(self):
        results = await asyncio.gather(
            self.opened(), self.opened(), return_exceptions=True
        )
        self.assertEqual(sum(isinstance(result, TicketError) for result in results), 1)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_claim_unclaim_authorization_and_claimant_ownership(self):
        _row, channel = await self.opened()
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(channel=channel), "claim")
        claimed = await self.manager.apply(self.context(self.agent, channel), "claim")
        self.assertEqual(claimed["claimant"], 600)
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(self.other_agent, channel), "claim")
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(self.other_agent, channel), "unclaim")
        unclaimed = await self.manager.apply(
            self.context(self.admin, channel), "unclaim"
        )
        self.assertEqual(unclaimed["state"], "open")
        self.assertIsNone(unclaimed["claimant"])

    async def test_close_is_read_only_reopen_staff_only_and_existing_ticket_blocks_reopen(
        self,
    ):
        _row, channel = await self.opened()
        await self.manager.apply(
            self.context(channel=channel), "close", "Masalah selesai"
        )
        for target in [self.owner, self.support]:
            self.assertFalse(channel.overwrites[target].send_messages)
            self.assertFalse(channel.overwrites[target].send_messages_in_threads)
        self.assertTrue(channel.overwrites[self.guild.me].send_messages)
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(channel=channel), "reopen")
        await self.manager.apply(self.context(self.agent, channel), "reopen")
        self.assertTrue(channel.overwrites[self.owner].send_messages)
        await self.manager.apply(self.context(channel=channel), "close", "Selesai lagi")
        with patch("app.ticket_store.time.time", return_value=time.time() + 61):
            await self.opened()
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(self.agent, channel), "reopen")

    async def test_close_requires_explicit_actor_confirmation_and_cancel_does_not_close(
        self,
    ):
        row, channel = await self.opened()
        view = ConfirmClose(self.manager, 500, row["id"], "Selesai")
        await view.children[0].callback(self.context(self.outsider, channel))
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "open")
        await view.children[1].callback(self.context(channel=channel))
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "open")
        view = ConfirmClose(self.manager, 500, row["id"], "Selesai")
        actor = self.context(channel=channel)
        await view.children[0].callback(actor)
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "closed")
        count = len(self.manager.store.events(row["id"]))
        await view.children[0].callback(actor)
        self.assertEqual(len(self.manager.store.events(row["id"])), count)

    async def test_wrong_guild_channel_control_and_pending_member_are_rejected(self):
        row, channel = await self.opened()
        outsider = self.context(self.outsider, channel)
        with self.assertRaises(TicketError):
            self.manager.context(outsider)
        other = self.context(self.agent, channel, SimpleNamespace(id=9999))
        with self.assertRaises(TicketError):
            self.manager.context(other, control_message=True)
        self.owner.pending = True
        with self.assertRaises(TicketError):
            self.manager.panel_check(self.context(), 400)
        self.owner.pending = False
        with self.assertRaises(TicketError):
            self.manager.panel_check(self.context(), 999)
        with self.assertRaises(TicketError):
            self.manager.store.get(2, row["id"])

    async def test_public_or_overly_broad_log_channel_is_rejected(self):
        self.log_channel.permissions_for.side_effect = lambda target: (
            discord.Permissions(view_channel=True, send_messages=True, embed_links=True)
        )
        with self.assertRaises(TicketError):
            self.manager.validate_log(self.guild, 3, 10)
        self.log_channel.permissions_for.side_effect = lambda target: (
            discord.Permissions(
                view_channel=target.id in (10, 20, 123),
                send_messages=True,
                embed_links=True,
            )
        )
        with self.assertRaises(TicketError):
            self.manager.validate_log(self.guild, 3, 10)

    async def test_unsafe_support_binding_and_lost_bot_permissions_block_creation(self):
        self.manager.reaction_role_bound = lambda guild, role: True
        with self.assertRaises(TicketError):
            await self.opened()
        self.guild.create_text_channel.assert_not_awaited()
        self.manager.reaction_role_bound = lambda guild, role: False
        self.guild.me.guild_permissions.manage_roles = False
        with self.assertRaises(TicketError):
            await self.opened()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_interrupted_close_is_recovered_without_duplicate_ticket(self):
        row, channel = await self.opened()
        original_edit = channel.edit.side_effect
        channel.edit.side_effect = RuntimeError("private token")
        with self.assertRaises(RuntimeError):
            await self.manager.apply(self.context(channel=channel), "close", "Selesai")
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "closing")
        channel.edit.side_effect = original_edit
        await self.manager.repair(self.guild, row["id"], 999)
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "closed")
        self.assertFalse(channel.overwrites[self.owner].send_messages)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_ambiguous_create_never_creates_another_channel_and_repair_uses_marker(
        self,
    ):
        original = self.guild.create_text_channel.side_effect

        async def ambiguous(*args, **kwargs):
            await original(*args, **kwargs)
            raise TimeoutError("unknown ack")

        self.guild.create_text_channel.side_effect = ambiguous
        with (
            self.assertLogs("app.discord_tickets", level="WARNING"),
            self.assertRaises(TicketError),
        ):
            await self.opened()
        row = self.manager.store.active(1, 500)
        self.assertIsNone(row["channel"])
        with self.assertRaises(TicketError):
            await self.opened()
        self.guild.create_text_channel.assert_awaited_once()
        repaired = await self.manager.repair(self.guild, row["id"], 999)
        self.assertEqual(repaired["state"], "open")
        self.assertIsNotNone(repaired["channel"])

    async def test_missing_channel_reservation_waits_before_admin_release(self):
        row = self.manager.store.reserve(1, 500, "report", "A private report summary")
        with self.assertRaises(TicketError):
            await self.manager.repair(self.guild, row["id"], 999)
        with patch("app.discord_tickets.time.time", return_value=time.time() + 301):
            repaired = await self.manager.repair(self.guild, row["id"], 999)
        self.assertEqual(repaired["state"], "failed")

    async def test_channel_marker_mismatch_never_changes_unrelated_channel(self):
        _row, channel = await self.opened()
        channel.topic = "An unrelated channel"
        with self.assertRaises(TicketError):
            await self.manager.apply(self.context(self.agent, channel), "claim")
        channel.edit.assert_not_awaited()

    async def test_disabled_module_restores_protected_metadata_and_persistent_views_once(
        self,
    ):
        _row, channel = await self.opened()
        await self.manager.start()
        self.assertEqual(self.client.add_view.call_count, 2)
        self.assertTrue(all(view.is_persistent() for view in self.manager.views))
        await self.manager.start()
        self.assertEqual(self.client.add_view.call_count, 2)
        await self.manager.close()
        self.manager.enabled = False
        await self.manager.start()
        self.assertTrue(self.manager.protected(channel))
        self.assertTrue(self.manager.reserved_role(1, 10))
        self.assertEqual(self.manager.views, [])

    async def test_offline_channel_deletion_reconciliation_releases_reservation_without_deleting_resources(
        self,
    ):
        row, channel = await self.opened()
        self.channels.pop(channel.id)
        await self.manager.recover_pending()
        self.assertIsNone(self.manager.store.active(1, 500))
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "deleted")
        channel.delete.assert_not_called()

    async def test_manual_channel_deletion_releases_active_slot_but_keeps_history(self):
        row, channel = await self.opened()
        await self.manager.channel_deleted(channel)
        self.assertEqual(self.manager.store.get(1, row["id"])["state"], "deleted")
        self.assertIsNone(self.manager.store.active(1, 500))
        self.assertTrue(self.manager.reserved_role(1, 10))

    async def test_controls_and_panel_are_persistent_and_no_transcript_or_ai_commands(
        self,
    ):
        panel = TicketPanel(self.manager)
        controls = TicketControls(self.manager, closed=True)
        self.assertTrue(panel.is_persistent())
        self.assertTrue(controls.is_persistent())
        self.assertTrue(controls.children[0].disabled)
        self.assertFalse(controls.children[3].disabled)
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_ticket_commands(tree, self.manager)
        names = {c.name for c in tree.get_command("ticket").commands}
        self.assertTrue(
            {"setup", "panel", "claim", "close", "reopen", "history"} <= names
        )
        self.assertFalse({"transcript", "rating", "ai"} & names)
        panel.stop()
        controls.stop()
        await client.close()

    async def test_kind_picker_and_form_preserve_owner_and_route_to_shared_service(
        self,
    ):
        picker = TicketKind(self.manager, 500, 400)
        picker.children[0]._values = ["store"]
        interaction = self.context()
        await picker.children[0].callback(interaction)
        form = interaction.response.send_modal.call_args.args[0]
        self.assertIsInstance(form, TicketForm)
        self.assertEqual(form.kind, "store")
        form.summary._value = "Order support private question"
        await form.on_submit(interaction)
        row = self.manager.store.active(1, 500)
        self.assertEqual(row["kind"], "store")
        self.assertEqual(row["state"], "open")
        picker.stop()
        form.stop()

    async def test_failure_after_channel_creation_keeps_privacy_and_can_be_repaired(
        self,
    ):
        with (
            patch.object(
                self.manager.store,
                "attach",
                side_effect=sqlite3.OperationalError("private path"),
            ),
            self.assertLogs("app.discord_tickets", level="WARNING"),
            self.assertRaises(TicketError),
        ):
            await self.opened()
        channel = next(c for ident, c in self.channels.items() if ident >= 200)
        self.assertTrue(self.manager.protected(channel))
        row = self.manager.store.active(1, 500)
        self.assertIsNone(row["channel"])
        repaired = await self.manager.repair(self.guild, row["id"], 999)
        self.assertEqual(repaired["channel"], channel.id)
        self.assertEqual(repaired["state"], "open")
        self.assertEqual(self.guild.create_text_channel.await_count, 1)

    async def test_support_role_cannot_be_selected_through_public_reaction_roles(self):
        from app.discord_onboarding import Onboarding
        from app.onboarding import OnboardingError, OnboardingStore

        onboarding = Onboarding(self.client)
        onboarding.store = OnboardingStore(str(Path(self.temp.name) / "onboarding"))
        onboarding.role_reserved = self.manager.reserved_role
        with self.assertRaises(OnboardingError):
            onboarding.check_role(self.guild, self.support)
        panel = onboarding.store.create(1, "Unsafe support choice", "", "multiple")
        onboarding.store.bind(1, panel, "u:🎮", "🎮", 10)
        self.manager.reaction_role_bound = onboarding.has_role_binding
        with self.assertRaises(TicketError):
            self.manager.validate_resources(self.guild, 2, 10, 3)
        await onboarding.close()

    async def test_log_delivery_failure_does_not_undo_ticket_state_or_copy_private_text(
        self,
    ):
        self.log_channel.send.side_effect = discord.Forbidden(
            Mock(status=403, reason="Forbidden"), "failed log"
        )
        with self.assertLogs("app.discord_tickets", level="WARNING"):
            row, channel = await self.opened()
        self.assertEqual(row["state"], "open")
        self.assertEqual(
            self.manager.store.get(1, row["id"])["summary"],
            "Sensitive order issue summary",
        )
        await self.manager.apply(self.context(self.agent, channel), "claim")
        with self.assertLogs("app.discord_tickets", level="WARNING"):
            closed = await self.manager.apply(
                self.context(channel=channel), "close", "Private closure explanation"
            )
        self.assertEqual(closed["state"], "closed")
        self.assertEqual(closed["claimant"], 600)
        for call in self.log_channel.send.call_args_list:
            payload = call.kwargs["embed"].to_dict()
            self.assertNotIn("Sensitive", str(payload))
            self.assertNotIn("Private closure", str(payload))

    async def test_admin_only_setup_and_republish_after_panel_message_deletion(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_ticket_commands(tree, self.manager)
        with self.assertRaises(TicketError):
            await (
                tree.get_command("ticket")
                .get_command("setup")
                .callback(self.context(self.owner), True)
            )
        await (
            tree.get_command("ticket")
            .get_command("setup")
            .callback(
                self.context(self.admin),
                True,
                category=self.category,
                support=self.support,
                log_channel=self.log_channel,
            )
        )
        self.panel_channel.fetch_message.side_effect = discord.NotFound(
            Mock(status=404, reason="Not Found"), "deleted"
        )
        await self.manager.publish(self.guild, self.panel_channel)
        self.panel_channel.send.assert_awaited_once()
        await client.close()

    async def test_ticket_messages_do_not_enter_ai_music_or_leveling(self):
        _row, channel = await self.opened()
        with patch.dict(
            os.environ, {"DISCORD_TOKEN": "offline", "ABUD_INTERNAL_API_KEY": "offline"}
        ):
            bot = importlib.import_module("app.bot")
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False),
            channel=channel,
            content="Abud, secret issue",
        )
        with (
            patch.object(bot, "ticket_manager", self.manager),
            patch.object(bot.leveling_manager, "message", new=AsyncMock()) as xp,
            patch.object(bot, "handle_music_message", new=AsyncMock()) as music,
            patch.object(bot, "ask_abud") as ask,
        ):
            await bot.on_message(message)
        xp.assert_not_awaited()
        music.assert_not_awaited()
        ask.assert_not_called()
        chat_command = SimpleNamespace(name="chat", root_parent=None)
        interaction = self.context(channel=channel)
        interaction.command = chat_command
        with patch.object(bot, "ticket_manager", self.manager):
            self.assertFalse(await bot.tree.interaction_check(interaction))
            interaction.command = SimpleNamespace(
                name="close", root_parent=SimpleNamespace(name="ticket")
            )
            self.assertTrue(await bot.tree.interaction_check(interaction))
