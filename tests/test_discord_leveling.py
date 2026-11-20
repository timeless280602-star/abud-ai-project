"""Leveling persistence, anti-farming and role-free UI contracts."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands
from PIL import Image

from app.discord_leveling import Leveling, install_leveling_commands
from app.level_card import rank_card
from app.leveling import (
    CHAT_CAP,
    VOICE_CAP,
    Award,
    LevelingError,
    LevelStore,
    fingerprint,
    level,
    progress,
)

BASE = datetime.fromisoformat("2026-11-18T01:00:00+00:00").timestamp()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "level.db")
        self.store = LevelStore(self.path)
        self.store.configure(1, True, True, True, None)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def chat(
        self, now=BASE, content="Selamat datang teman semua", member=10, amount=20
    ):
        return self.store.award(
            1, member, "Member", "chat", now, content=content, amount=amount
        )

    def test_level_boundaries_and_progress(self):
        self.assertEqual(
            [level(x) for x in [0, 99, 100, 399, 400, 900]], [0, 0, 1, 1, 2, 3]
        )
        self.assertEqual(progress(150), (1, 50, 300))
        self.assertTrue(Award(1, 10, 99, 120, 21).leveled)
        self.assertFalse(Award(1, 10, 120, 140, 20).leveled)

    def test_low_effort_commands_emojis_urls_and_duplicate_normalization(self):
        for text in [
            "hi",
            "aaaaaaaaaaaaaaaa",
            "123456789",
            "😀😀😀😀😀😀😀😀",
            "https://example.com/verylong-url",
            "/play linkyoutube",
            "!rank user",
            "<@12345678>",
        ]:
            self.assertIsNone(fingerprint(text), text)
        self.assertEqual(
            fingerprint("Halo semua, selamat datang!"),
            fingerprint("HALO  SEMUA SELAMAT DATANG..."),
        )

    def test_cooldown_and_duplicate_hash_survive_restart_without_message_text(self):
        self.assertIsNotNone(self.chat())
        self.assertIsNone(self.chat(BASE + 30, "Ini adalah pesan berbeda"))
        self.store.close()
        self.store = LevelStore(self.path)
        self.assertIsNone(self.chat(BASE + 61, "SELAMAT DATANG, TEMAN SEMUA!!"))
        self.assertIsNotNone(self.chat(BASE + 62, "Ini adalah pesan berbeda"))
        self.assertIsNotNone(self.chat(BASE + 601))
        hashes = self.store.db.execute("SELECT hash FROM messages").fetchall()
        self.assertTrue(all(len(r[0]) == 64 for r in hashes))
        self.assertEqual(self.store.member(1, 10)["xp"], 60)

    def test_chat_and_voice_have_independent_cooldowns_and_caps(self):
        for i in range(150):
            self.chat(BASE + i * 60, f"Pembahasan komunitas nomor {i}", amount=25)
            self.store.award(1, 10, "Member", "voice", BASE + i * 60, amount=5)
        row = self.store.member(1, 10)
        self.assertEqual(
            (row["chat_xp"], row["voice_xp"], row["xp"]),
            (CHAT_CAP, VOICE_CAP, CHAT_CAP + VOICE_CAP),
        )

    def test_daily_cap_resets_at_midnight_wib_and_award_is_clipped(self):
        near_midnight = datetime.fromisoformat("2026-11-18T16:59:00+00:00").timestamp()
        self.chat(near_midnight)
        self.store.db.execute(
            "UPDATE members SET daily_chat=? WHERE guild=1 AND member=10",
            (CHAT_CAP - 3,),
        )
        self.store.db.commit()
        award = self.chat(near_midnight + 1, "Pesan baru tapi cooldown")
        self.assertIsNone(award)
        # An earlier time with enough cooldown can only earn the remaining cap.
        self.store.db.execute("UPDATE members SET last_chat=?", (near_midnight - 120,))
        self.store.db.commit()
        award = self.chat(near_midnight + 1, "Percakapan berbeda kali ini")
        self.assertEqual(award.amount, 3)
        award = self.chat(near_midnight + 121, "Sudah masuk hari berikutnya")
        self.assertEqual(award.amount, 20)

    def test_guild_and_source_opt_in_pause_preserves_xp(self):
        self.assertIsNone(
            self.store.award(
                2, 10, "X", "chat", BASE, content="Bincang komunitas baru", amount=20
            )
        )
        self.chat()
        self.store.configure(1, False, True, True, None)
        self.assertIsNone(self.chat(BASE + 61, "Bincang komunitas saat jeda"))
        self.store.configure(1, True, False, True, None)
        self.assertIsNone(self.chat(BASE + 122, "Bincang komunitas chat mati"))
        self.assertIsNotNone(self.store.award(1, 10, "X", "voice", BASE + 122))
        self.assertEqual(self.store.member(1, 10)["xp"], 25)

    def test_stable_tie_ranking_is_isolated_by_guild(self):
        self.chat(member=20)
        self.chat(member=10)
        self.assertEqual(self.store.rank(1, 10), 1)
        self.assertEqual(self.store.rank(1, 20), 2)
        self.assertIsNone(self.store.rank(1, 99))
        self.assertEqual(self.store.leaderboard(2), [])
        self.assertEqual([r["member"] for r in self.store.leaderboard(1)], [10, 20])

    def test_duplicate_history_is_bounded(self):
        for i in range(20):
            self.chat(BASE + i * 61, f"Percakapan yang berbeda nomor {i}")
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM messages").fetchone()[0], 10
        )

    def test_rank_card_is_a_real_bounded_png_with_long_unicode_name(self):
        result = rank_card("🎮 Cindy Astuti 日本語 " * 15, 550, 450, 100, 3)
        with Image.open(result) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (960, 300))
        self.assertLess(len(result.getvalue()), 200000)


def voice_member(ident, channel, **flags):
    state = SimpleNamespace(
        channel=channel,
        self_mute=False,
        mute=False,
        self_deaf=False,
        deaf=False,
        afk=False,
        suppress=False,
    )
    for name, value in flags.items():
        setattr(state, name, value)
    return SimpleNamespace(
        id=ident,
        display_name=f"Member {ident}",
        bot=False,
        voice=state,
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
        edit=AsyncMock(),
    )


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 1
        self.guild.unavailable = False
        self.guild.afk_channel = None
        self.channel = Mock(spec=discord.VoiceChannel)
        self.channel.id = 100
        self.first = voice_member(10, self.channel)
        self.second = voice_member(20, self.channel)
        self.channel.members = [self.first, self.second]
        self.guild.voice_channels = [self.channel]
        self.client = Mock(guilds=[self.guild], is_ready=Mock(return_value=True))
        self.manager = Leveling(self.client)
        self.manager.enabled = True
        self.manager.path = str(Path(self.temp.name) / "db")
        self.manager.store = LevelStore(self.manager.path)
        self.manager.store.configure(1, True, True, True, None)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    def message(self, content="Selamat datang teman semua"):
        return SimpleNamespace(
            guild=self.guild,
            author=self.first,
            webhook_id=None,
            type=discord.MessageType.default,
            channel=SimpleNamespace(id=200, parent_id=None),
            content=content,
        )

    async def test_chat_counts_community_messages_and_excludes_bots_webhooks_dm_system(
        self,
    ):
        await self.manager.message(self.message())
        self.assertGreater(self.manager.store.member(1, 10)["chat_xp"], 0)
        for kind in ["bot", "webhook", "dm", "system"]:
            message = self.message("Percakapan berbeda yang panjang")
            message.author = voice_member(30, self.channel)
            if kind == "bot":
                message.author.bot = True
            if kind == "webhook":
                message.webhook_id = 999
            if kind == "dm":
                message.guild = None
            if kind == "system":
                message.type = discord.MessageType.new_member
            await self.manager.message(message)
        self.assertEqual(self.manager.store.member(1, 30)["xp"], 0)

    async def test_parent_channel_exclusion_also_blocks_threads(self):
        self.manager.store.exclude(1, 200, True)
        message = self.message()
        message.channel = SimpleNamespace(id=201, parent_id=200)
        await self.manager.message(message)
        self.assertEqual(self.manager.store.member(1, 10)["xp"], 0)

    async def test_level_notice_is_opt_in_never_pings_and_never_changes_roles(self):
        await self.manager.announce(self.guild, self.first, Award(1, 10, 90, 110, 20))
        self.guild.get_channel.assert_not_called()
        self.manager.store.configure(1, True, True, True, 500)
        destination = Mock(send=AsyncMock())
        self.guild.get_channel.return_value = destination
        await self.manager.announce(self.guild, self.first, Award(1, 10, 90, 110, 20))
        payload = destination.send.call_args.kwargs
        self.assertIn("Level 1", payload["embed"].description)
        self.assertFalse(payload["allowed_mentions"].everyone)
        self.assertFalse(payload["allowed_mentions"].users)
        self.first.add_roles.assert_not_awaited()
        self.first.remove_roles.assert_not_awaited()
        self.first.edit.assert_not_awaited()

    async def test_notice_failure_cannot_rollback_or_repeat_xp(self):
        self.manager.store.configure(1, True, True, True, 500)
        error = discord.Forbidden(Mock(status=403, reason="Forbidden"), "no permission")
        self.guild.get_channel.return_value = Mock(send=AsyncMock(side_effect=error))
        for i in range(4):
            self.manager.store.award(
                1,
                10,
                "Member",
                "chat",
                BASE + i * 60,
                content=f"Bincang komunitas berbeda {i}",
                amount=25,
            )
        award = Award(1, 10, 75, 100, 25)
        with self.assertLogs("app.discord_leveling", level="WARNING"):
            await self.manager.announce(self.guild, self.first, award)
        self.assertEqual(self.manager.store.member(1, 10)["xp"], 100)
        self.assertIsNone(
            self.manager.store.award(
                1,
                10,
                "Member",
                "chat",
                BASE + 181,
                content="Tidak boleh tambah saat cooldown",
                amount=25,
            )
        )

    async def test_lifecycle_start_reuses_worker_and_restart_keeps_settings(self):
        await self.manager.start()
        first_task = self.manager.task
        await self.manager.start()
        self.assertIs(self.manager.task, first_task)
        await self.manager.close()
        self.assertTrue(first_task.cancelled())
        await self.manager.start()
        self.assertTrue(self.manager.store.config(1)["enabled"])
        self.assertIsNot(self.manager.task, first_task)

    async def test_admin_setup_preserves_options_and_notification_permission_is_validated(
        self,
    ):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_leveling_commands(tree, self.manager)
        interaction = SimpleNamespace(
            guild=self.guild,
            guild_id=1,
            permissions=SimpleNamespace(administrator=True),
            response=Mock(defer=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )
        setup = tree.get_command("leveling").get_command("setup")
        await setup.callback(interaction, True, chat=False)
        self.assertFalse(self.manager.store.config(1)["chat"])
        self.assertFalse(self.manager.store.config(1)["voice"])
        destination = Mock(spec=discord.TextChannel)
        destination.id = 500
        destination.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, embed_links=False
        )
        self.guild.get_channel.return_value = destination
        with self.assertRaises(LevelingError):
            await setup.callback(interaction, True, announcement=destination)
        self.assertIsNone(self.manager.store.config(1)["announcement"])
        destination.permissions_for.return_value.embed_links = True
        await setup.callback(interaction, True, announcement=destination)
        self.assertEqual(self.manager.store.config(1)["announcement"], 500)
        self.assertFalse(self.manager.store.config(1)["chat"])
        await setup.callback(interaction, True, notify=False)
        self.assertIsNone(self.manager.store.config(1)["announcement"])
        self.first.add_roles.assert_not_awaited()
        await client.close()

    async def test_rank_and_leaderboard_commands_deliver_png_and_guild_only_data(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_leveling_commands(tree, self.manager)
        self.manager.store.award(
            1,
            10,
            "Member 10",
            "chat",
            BASE,
            content="Bincang bersama komunitas",
            amount=20,
        )
        interaction = SimpleNamespace(
            guild=self.guild,
            guild_id=1,
            user=self.first,
            response=Mock(defer=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )
        await tree.get_command("rank").callback(interaction)
        payload = interaction.followup.send.call_args.kwargs
        self.assertEqual(payload["file"].filename, "abud-rank.png")
        with Image.open(payload["file"].fp) as image:
            self.assertEqual(image.size, (960, 300))
        payload["file"].close()
        await tree.get_command("leaderboard").callback(interaction)
        description = interaction.followup.send.call_args.kwargs["embed"].description
        self.assertIn("20 XP", description)
        self.assertIn("Member 10", description)
        self.first.add_roles.assert_not_awaited()
        self.first.remove_roles.assert_not_awaited()
        await client.close()

    async def test_commands_register_admin_controls_and_no_role_commands(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_leveling_commands(tree, self.manager)
        self.assertTrue(tree.get_command("rank").guild_only)
        self.assertTrue(tree.get_command("leaderboard").guild_only)
        group = tree.get_command("leveling")
        self.assertEqual(
            {c.name for c in group.commands}, {"setup", "config", "exclude", "include"}
        )
        self.assertTrue(group.default_permissions.administrator)
        interaction = SimpleNamespace(
            guild=self.guild,
            guild_id=1,
            permissions=SimpleNamespace(administrator=False),
            response=Mock(defer=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )
        with self.assertRaises(LevelingError):
            await group.get_command("setup").callback(interaction, True)
        self.assertTrue(self.manager.store.config(1)["enabled"])
        await client.close()
