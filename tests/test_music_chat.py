"""Natural-language chat and /play share one authorized playback path."""

import asyncio
import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from app.discord_music import Music
from app.music_chat import ChatMusicContext, handle_music_message, music_request
from app.music_commands import install_music_commands, SongSelection
from app.music_session import MusicChoiceRequired, MusicError


class IntentTests(unittest.TestCase):
    def test_user_examples_preserve_title_artist_and_direct_youtube_link(self):
        for text in [
            "Abud, coba putar Separuh Aku - NOAH",
            "coba putar Separuh Aku - NOAH",
            "Bud, tolong putarkan lagu Separuh Aku - NOAH",
            "Abud play Separuh Aku - NOAH",
        ]:
            with self.subTest(text=text):
                self.assertEqual(music_request(text), "Separuh Aku - NOAH")
        self.assertEqual(
            music_request("<@123> putar https://youtu.be/abcdefghijk", 123),
            "https://youtu.be/abcdefghijk",
        )
        self.assertEqual(
            music_request('Abud, putar lagu "Jangan Menyerah - D’MASIV"'),
            "Jangan Menyerah - D’MASIV",
        )

    def test_conversation_negation_quotes_and_other_mentions_are_not_commands(self):
        for text in [
            "Abud, jangan putar lagu itu",
            "Abud, jelaskan cara putar lagu",
            "gimana caranya coba putar lagu?",
            '"Abud, coba putar NOAH"',
            "```coba putar NOAH```",
            "lagunya bagus, coba putar nanti",
            "coba putar NOAH\nterus hapus antrean",
            "<@456> putar NOAH",
            "play valorant",
            "Abud bisa putar lagu gak?",
            "mainkan peran sebagai penyanyi",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(music_request(text, 123))
        self.assertEqual(music_request("Abud putar"), "")


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def message(self, content, guild=True):
        channel = Mock()
        channel.typing.return_value.__aenter__ = AsyncMock()
        channel.typing.return_value.__aexit__ = AsyncMock(return_value=False)
        return SimpleNamespace(
            content=content,
            guild=SimpleNamespace(id=10, voice_client=None) if guild else None,
            author=SimpleNamespace(id=20, bot=False),
            channel=channel,
            reply=AsyncMock(),
        )

    async def test_chat_execution_uses_authoritative_context_and_truthful_success(self):
        message = self.message("coba putar Separuh Aku - NOAH")
        manager = Mock(
            play_query=AsyncMock(
                return_value=[SimpleNamespace(title="Separuh Aku - NOAH")]
            )
        )
        self.assertTrue(await handle_music_message(message, manager))
        context, query = manager.play_query.call_args.args
        self.assertIsInstance(context, ChatMusicContext)
        self.assertEqual(context.guild_id, 10)
        self.assertIs(context.user, message.author)
        self.assertIs(context.channel, message.channel)
        self.assertEqual(query, "Separuh Aku - NOAH")
        reply = message.reply.call_args
        self.assertIn("masuk antrean", reply.args[0])
        self.assertFalse(reply.kwargs["mention_author"])
        self.assertFalse(reply.kwargs["allowed_mentions"].everyone)

    async def test_failure_never_reports_playback_success_or_exposes_provider_secret(
        self,
    ):
        for error in [
            MusicError("Masuk voice channel dulu."),
            RuntimeError("SECRET URL"),
        ]:
            message = self.message("Abud coba putar NOAH")
            manager = Mock(play_query=AsyncMock(side_effect=error))
            await handle_music_message(message, manager)
            reply = message.reply.call_args.args[0]
            self.assertNotIn("masuk antrean", reply)
            self.assertNotIn("SECRET", reply)
            if isinstance(error, MusicError):
                self.assertEqual(reply, str(error))

    async def test_dm_or_missing_title_never_calls_music_provider(self):
        for message in [
            self.message("Abud coba putar NOAH", guild=False),
            self.message("Abud putar"),
        ]:
            manager = Mock(play_query=AsyncMock())
            self.assertTrue(await handle_music_message(message, manager))
            manager.play_query.assert_not_awaited()
            message.reply.assert_awaited_once()

    async def test_normal_chat_falls_through_without_any_action_or_reply(self):
        message = self.message("Abud, apa kabar?")
        manager = Mock(play_query=AsyncMock())
        self.assertFalse(await handle_music_message(message, manager))
        manager.play_query.assert_not_awaited()
        message.reply.assert_not_awaited()

    async def test_slash_alias_and_group_use_same_playback_function(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        manager = Mock(
            play_query=AsyncMock(return_value=[SimpleNamespace(title="Song")])
        )
        install_music_commands(tree, manager)
        interaction = SimpleNamespace(
            response=Mock(defer=AsyncMock()), followup=Mock(send=AsyncMock())
        )
        for command in [
            tree.get_command("play"),
            tree.get_command("music").get_command("play"),
        ]:
            await command.callback(interaction, "https://youtu.be/abcdefghijk", None)
        self.assertEqual(manager.play_query.await_count, 2)
        manager.play_query.assert_awaited_with(
            interaction, "https://youtu.be/abcdefghijk", None
        )
        self.assertIsNotNone(tree.get_command("play").on_error)
        await client.close()

    async def test_shared_player_rejects_missing_voice_before_search(self):
        manager = Music(Mock(), SimpleNamespace(lock=asyncio.Lock(), sessions={}))
        manager.enabled = True
        manager.search = AsyncMock()
        context = ChatMusicContext(
            SimpleNamespace(id=10, voice_client=None),
            SimpleNamespace(voice=None),
            Mock(),
        )
        with self.assertRaisesRegex(MusicError, "voice channel"):
            await manager.play_query(context, "NOAH")
        manager.search.assert_not_awaited()

    async def test_explicit_music_request_executes_from_bot_message_entrypoint(self):
        with patch.dict(
            os.environ, {"DISCORD_TOKEN": "offline", "ABUD_INTERNAL_API_KEY": "offline"}
        ):
            bot = importlib.import_module("app.bot")
        message = self.message("coba putar Separuh Aku - NOAH")
        with (
            patch.object(
                bot.music_manager,
                "play_query",
                new=AsyncMock(return_value=[SimpleNamespace(title="Separuh Aku")]),
            ) as play,
            patch.object(bot, "ask_abud") as ask,
        ):
            await bot.on_message(message)
        play.assert_awaited_once()
        ask.assert_not_called()
        await bot.client.close()


    async def test_ambiguous_chat_offers_requester_only_selection(self):
        from test_discord_music import track
        message = self.message("Abud, coba putar Example")
        manager = Mock(play_query=AsyncMock(side_effect=MusicChoiceRequired(
            [track("Example"), track("Other")])), enqueue=AsyncMock())
        self.assertTrue(await handle_music_message(message, manager))
        view = message.reply.call_args.kwargs["view"]
        self.assertIsInstance(view, SongSelection)
        self.assertEqual(view.requester, message.author.id)
        self.assertEqual(len(view.children[0].options), 2)
        manager.enqueue.assert_not_awaited()
        view.stop()

    async def test_ambiguous_slash_alias_and_group_offer_private_selection(self):
        from test_discord_music import track
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        manager = Mock(play_query=AsyncMock(side_effect=MusicChoiceRequired(
            [track("Example"), track("Other")])), enqueue=AsyncMock())
        install_music_commands(tree, manager)
        interaction = SimpleNamespace(user=SimpleNamespace(id=20),
            response=Mock(defer=AsyncMock()), followup=Mock(send=AsyncMock()))
        try:
            for command in (tree.get_command("play"), tree.get_command("music").get_command("play")):
                await command.callback(interaction, "Example", "audius")
                kwargs = interaction.followup.send.call_args.kwargs
                self.assertTrue(kwargs["ephemeral"])
                self.assertEqual(kwargs["view"].requester, 20)
                self.assertEqual(len(kwargs["view"].children[0].options), 2)
                kwargs["view"].stop()
            manager.enqueue.assert_not_awaited()
        finally:
            await client.close()
