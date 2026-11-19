"""Offline universal leave routing: never bypass existing session controls."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord import app_commands

from app.discord_voice import install_voice_commands, VoiceError
from app.music_session import MusicError


class UniversalLeaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = discord.Client(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self.client)
        self.voice = Mock(leave=AsyncMock())
        self.music = Mock(sessions={}, apply=AsyncMock())
        install_voice_commands(self.tree, self.voice, music_manager=self.music)
        self.command = self.tree.get_command("leave")
        self.interaction = SimpleNamespace(
            guild_id=1,
            response=Mock(defer=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )

    async def asyncTearDown(self):
        await self.client.close()

    async def test_music_leave_routes_to_existing_permission_checks(self):
        self.music.sessions[1] = object()
        await self.command.callback(self.interaction)
        self.music.apply.assert_awaited_once_with(self.interaction, "leave")
        self.voice.active.assert_not_called()
        self.voice.leave.assert_not_awaited()
        self.assertIn("musik", self.interaction.followup.send.call_args.args[0])

    async def test_rejected_music_leave_never_falls_back_to_voice(self):
        self.music.sessions[1] = object()
        self.music.apply.side_effect = MusicError("Kontrol ini untuk pemilik sesi.")
        await self.command.callback(self.interaction)
        self.voice.leave.assert_not_awaited()
        self.voice.active.assert_not_called()
        self.assertIn("pemilik sesi", self.interaction.followup.send.call_args.args[0])

    async def test_ai_voice_leave_unchanged(self):
        await self.command.callback(self.interaction)
        self.voice.active.assert_called_once_with(self.interaction, control=True)
        self.voice.leave.assert_awaited_once_with(1)
        self.music.apply.assert_not_awaited()

    async def test_no_session_reports_existing_voice_error(self):
        self.voice.active.side_effect = VoiceError("Abud belum masuk voice channel.")
        await self.command.callback(self.interaction)
        self.voice.leave.assert_not_awaited()
        self.music.apply.assert_not_awaited()
        self.assertIn("belum masuk", self.interaction.followup.send.call_args.args[0])
