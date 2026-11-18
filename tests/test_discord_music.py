"""Music queue, callback ownership, access and Discord adapter contracts (no login)."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import wavelink
from discord import app_commands

from app.discord_music import Music, MusicControls, now_embed, queue_embed
from app.music_commands import SongSelection, install_music_commands
from app.music_session import MusicError, MusicSession, duration, music_query


def track(name="Track", *, stream=False):
    return wavelink.Playable(
        {
            "encoded": name,
            "info": {
                "identifier": name,
                "isSeekable": not stream,
                "author": "Artist",
                "length": 240000,
                "isStream": stream,
                "position": 0,
                "title": name,
                "uri": "https://soundcloud.com/artist/" + name,
                "artworkUrl": "https://cdn.example.com/cover.jpg",
                "sourceName": "soundcloud",
            },
            "pluginInfo": {},
            "userData": {},
        }
    )


def player():
    return SimpleNamespace(
        channel=SimpleNamespace(id=10, members=[SimpleNamespace(bot=False)]),
        guild=SimpleNamespace(id=1),
        paused=False,
        connected=True,
        position=42000,
        play=AsyncMock(),
        skip=AsyncMock(),
        pause=AsyncMock(),
        set_volume=AsyncMock(),
        seek=AsyncMock(),
        disconnect=AsyncMock(),
        cleanup=Mock(),
    )


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.player = player()
        self.session = MusicSession(self.player, 100, Mock())

    async def test_fifo_requester_and_fresh_nonce_do_not_modify_source(self):
        first, second = track("first"), track("second")
        await self.session.enqueue([first, second], 100)
        nonce = self.session.nonce
        played = self.player.play.call_args.args[0]
        self.assertEqual(played.extras.requester, 100)
        self.assertEqual(played.extras.abud_music_nonce, nonce)
        self.assertFalse(hasattr(first.extras, "abud_music_nonce"))
        self.assertEqual(self.player.play.call_args.kwargs["volume"], 50)
        await self.session.ended(nonce, "finished")
        self.assertEqual(self.session.current.track.title, "second")
        self.assertNotEqual(self.session.nonce, nonce)

    async def test_concurrent_enqueues_are_bounded_and_rejection_is_atomic(self):
        results = await asyncio.gather(
            self.session.enqueue([track()] * 70, 100),
            self.session.enqueue([track()] * 70, 200),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, MusicError) for r in results), 1)
        self.assertEqual(len(self.session.queue) + bool(self.session.current), 70)

    async def test_skip_and_duplicate_end_events_cannot_skip_new_track(self):
        await self.session.enqueue([track("a"), track("b"), track("c")], 100)
        old = self.session.nonce
        await self.session.control("skip")
        self.assertFalse(await self.session.ended(old, "finished"))
        self.assertEqual(self.session.current.track.title, "b")
        nonce = self.session.nonce
        self.assertFalse(await self.session.ended(nonce, "replaced"))
        await self.session.ended(nonce, "finished")
        self.assertFalse(await self.session.ended(nonce, "finished"))
        self.assertEqual(self.session.current.track.title, "c")

    async def test_repeat_track_queue_and_explicit_skip(self):
        await self.session.enqueue([track("a"), track("b")], 100)
        await self.session.control("repeat", "track")
        await self.session.ended(self.session.nonce, "finished")
        self.assertEqual(self.session.current.track.title, "a")
        await self.session.control("skip")
        self.assertEqual(self.session.current.track.title, "b")
        await self.session.control("repeat", "queue")
        await self.session.ended(self.session.nonce, "finished")
        self.assertEqual(self.session.current.track.title, "b")
        self.assertEqual(self.session.repeat, "queue")

    async def test_stop_wins_over_late_callback_and_never_restarts(self):
        await self.session.enqueue([track("a"), track("b")], 100)
        nonce = self.session.nonce
        await asyncio.gather(
            self.session.control("stop"), self.session.ended(nonce, "finished")
        )
        self.assertIsNone(self.session.current)
        self.assertEqual(self.session.queue, [])
        self.assertEqual(self.session.repeat, "off")
        self.player.skip.assert_awaited_with(force=True)

    async def test_volume_seek_stream_restrictions_and_pause(self):
        await self.session.enqueue([track()], 100)
        for value in (-1, 101):
            with self.assertRaises(MusicError):
                await self.session.control("volume", value)
        await self.session.control("volume", 0)
        self.player.set_volume.assert_awaited_once_with(0)
        await self.session.control("seek", 30)
        self.player.seek.assert_awaited_once_with(30000)
        with self.assertRaises(MusicError):
            await self.session.control("seek", 240)
        await self.session.control("pause")
        await self.session.control("resume")
        self.assertEqual(
            [c.args[0] for c in self.player.pause.call_args_list], [True, False]
        )
        await self.session.control("stop")
        await self.session.enqueue([track(stream=True)], 100)
        with self.assertRaises(MusicError):
            await self.session.control("seek", 10)

    async def test_queue_editing_preserves_playing_song_and_clear_keeps_it(self):
        await self.session.enqueue([track(name) for name in ["a", "b", "c", "d"]], 100)
        await self.session.control("move", (3, 1))
        self.assertEqual([r.track.title for r in self.session.queue], ["d", "b", "c"])
        await self.session.control("remove", 2)
        await self.session.control("shuffle")
        self.assertEqual({r.track.title for r in self.session.queue}, {"d", "c"})
        self.assertEqual(self.session.current.track.title, "a")
        with self.assertRaises(MusicError):
            await self.session.control("remove", 50)
        await self.session.control("clear")
        self.assertEqual(self.session.current.track.title, "a")
        self.assertEqual(self.session.queue, [])

    async def test_previous_requeues_current_with_requester(self):
        await self.session.enqueue([track("a")], 100)
        await self.session.enqueue([track("b")], 200)
        await self.session.ended(self.session.nonce, "finished")
        await self.session.control("previous")
        self.assertEqual(self.session.current.track.title, "a")
        self.assertEqual(self.session.current.requester, 100)
        self.assertEqual(self.session.queue[0].requester, 200)

    async def test_provider_errors_are_bounded_and_sanitized(self):
        self.player.play.side_effect = RuntimeError("SECRET PROVIDER URL")
        with self.assertRaisesRegex(MusicError, "Tiga lagu") as caught:
            await self.session.enqueue([track()] * 20, 100)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(self.player.play.await_count, 3)
        self.player.skip.assert_awaited_once()

    async def test_close_is_idempotent_and_blocks_late_additions(self):
        await self.session.enqueue([track()], 100)
        nonce = self.session.nonce
        await self.session.close()
        await self.session.close()
        self.player.disconnect.assert_awaited_once()
        self.assertFalse(await self.session.ended(nonce, "finished"))
        with self.assertRaises(MusicError):
            await self.session.enqueue([track()], 100)


class QueryTests(unittest.TestCase):
    def test_allowed_sources_and_untrusted_or_internal_schemes(self):
        for value in [
            "song title",
            "https://youtu.be/abcdefghijk",
            "https://soundcloud.com/artist/song",
            "https://artist.bandcamp.com/album/name",
        ]:
            self.assertEqual(music_query(value), value)
        for value in [
            "file:///etc/passwd",
            "https://127.0.0.1/audio",
            "http://soundcloud.com/x",
            "https://soundcloud.com.evil/x",
            "https://user@youtube.com/x",
            "ytsearch:injected",
            "https://youtube.com:123/x",
            "https://open.spotify.com/track/x",
            "",
        ]:
            with self.subTest(value=value), self.assertRaises(MusicError):
                music_query(value)
        self.assertEqual(duration(3661000), "1:01:01")


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice = SimpleNamespace(lock=asyncio.Lock(), sessions={})
        self.manager = Music(Mock(), self.voice)
        self.manager.enabled = True
        self.player = player()
        self.session = MusicSession(self.player, 100, Mock(send=AsyncMock()))
        self.manager.sessions[1] = self.session
        channel = Mock(spec=discord.VoiceChannel)
        channel.id = 10
        self.interaction = SimpleNamespace(
            guild_id=1,
            guild=Mock(),
            user=SimpleNamespace(
                id=100,
                voice=SimpleNamespace(channel=channel),
                guild_permissions=SimpleNamespace(manage_guild=False),
                roles=[],
            ),
            channel=Mock(),
            response=Mock(defer=AsyncMock(), send_message=AsyncMock()),
            followup=Mock(send=AsyncMock()),
        )

    async def asyncTearDown(self):
        self.manager.sessions.clear()
        for _, view in self.manager.panels.values():
            view.stop()
        self.manager.panels.clear()

    async def test_runtime_controls_same_channel_dj_owner_and_requester_skip(self):
        self.assertIs(self.manager.active(self.interaction, control=True), self.session)
        self.interaction.user.id = 200
        with self.assertRaises(MusicError):
            self.manager.active(self.interaction, control=True)
        await self.session.enqueue([track()], 200)
        self.manager.active(self.interaction, control=True, action="skip")
        with self.assertRaises(MusicError):
            self.manager.active(self.interaction, control=True, action="stop")
        self.interaction.user.roles = [SimpleNamespace(name="DJ")]
        self.manager.active(self.interaction, control=True)
        self.interaction.user.voice.channel.id = 20
        with self.assertRaises(MusicError):
            self.manager.active(self.interaction, control=True)
        self.interaction.guild_id = 2
        with self.assertRaises(MusicError):
            self.manager.active(self.interaction)

    async def test_stale_panel_cannot_control_replacement_session(self):
        old = MusicSession(player(), 100, Mock())
        with self.assertRaises(MusicError):
            self.manager.active(self.interaction, control=True, expected=old)

    async def test_music_cannot_connect_over_ai_voice(self):
        self.manager.sessions.clear()
        self.voice.sessions[1] = Mock()
        self.interaction.guild.voice_client = None
        with self.assertRaisesRegex(MusicError, "/leave"):
            await self.manager.enqueue(self.interaction, [track()])
        self.interaction.user.voice.channel.connect.assert_not_called()

    async def test_join_and_followup_enqueue_use_one_connection(self):
        self.manager.sessions.clear()
        self.interaction.guild.voice_client = None
        channel = self.interaction.user.voice.channel
        channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, connect=True, speak=True
        )
        self.interaction.channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, embed_links=True
        )
        channel.connect = AsyncMock(return_value=self.player)
        self.manager.ensure_node = AsyncMock(return_value=Mock())
        self.manager.panel = AsyncMock()
        await asyncio.gather(
            self.manager.enqueue(self.interaction, [track("a")]),
            self.manager.enqueue(self.interaction, [track("b")]),
        )
        channel.connect.assert_awaited_once()
        self.assertEqual(len(self.manager.sessions[1].queue), 1)
        self.assertTrue(self.player.autoplay == wavelink.AutoPlayMode.disabled)

    async def test_search_uses_chosen_node_and_prefix_no_network_on_invalid_url(self):
        self.manager.ensure_node = AsyncMock(return_value=Mock())
        with patch(
            "app.discord_music.wavelink.Pool.fetch_tracks",
            new=AsyncMock(return_value=[track()]),
        ) as fetch:
            await self.manager.search("song", "youtube")
            self.assertEqual(fetch.call_args.args[0], "ytsearch:song")
            with self.assertRaises(MusicError):
                await self.manager.search("https://localhost/private")
            self.assertEqual(fetch.await_count, 1)

    async def test_node_failed_connection_is_closed_and_can_retry(self):
        self.manager.password = "not-a-real-secret"
        node = Mock(status=wavelink.NodeStatus.DISCONNECTED, close=AsyncMock())
        with (
            patch("app.discord_music.wavelink.Node", return_value=node),
            patch(
                "app.discord_music.wavelink.Pool.connect",
                new=AsyncMock(side_effect=RuntimeError("provider")),
            ),
            self.assertRaises(RuntimeError),
        ):
            await self.manager.ensure_node()
        node.close.assert_awaited_once_with(eject=True)
        self.assertIsNone(self.manager.node)

    async def test_empty_channel_and_forced_move_cleanup(self):
        self.manager.leave = AsyncMock()
        member = SimpleNamespace(guild=SimpleNamespace(id=1), id=200)
        self.manager.client.user.id = 999
        self.player.channel.members = [SimpleNamespace(bot=True)]
        await self.manager.voice_state_update(
            member, Mock(), SimpleNamespace(channel=self.player.channel)
        )
        self.manager.leave.assert_awaited_once_with(1)
        self.manager.leave.reset_mock()
        member.id = 999
        await self.manager.voice_state_update(
            member, Mock(), SimpleNamespace(channel=None)
        )
        self.manager.leave.assert_awaited_once_with(1)

    async def test_player_panel_and_paginated_queue_content(self):
        await self.session.enqueue(
            [track("a")] + [track(str(i)) for i in range(15)], 100
        )
        embed = now_embed(self.session).to_dict()
        self.assertEqual(embed["title"], "a")
        self.assertEqual(embed["url"], "https://soundcloud.com/artist/a")
        self.assertIn("thumbnail", embed)
        self.assertIn("0:42 / 4:00", embed["fields"][0]["value"])
        page = queue_embed(self.session, 2).to_dict()
        self.assertIn("**11.**", page["description"])
        self.assertNotIn("**10.**", page["description"])
        with self.assertRaises(MusicError):
            queue_embed(self.session, 3)

    async def test_panel_buttons_enforce_same_runtime_access(self):
        await self.session.enqueue([track()], 100)
        self.interaction.user.id = 200
        view = MusicControls(self.manager, self.session)
        await view.children[3].callback(self.interaction)  # Stop.
        self.assertIsNotNone(self.session.current)
        self.assertIn("pemilik sesi", self.interaction.followup.send.call_args.args[0])
        view.stop()

    async def test_song_picker_is_private_and_only_queues_on_selection(self):
        manager = Mock(enqueue=AsyncMock())
        view = SongSelection(manager, 100, [track()])
        self.interaction.user.id = 200
        await view.children[0].callback(self.interaction)
        manager.enqueue.assert_not_awaited()
        self.interaction.response.send_message.assert_awaited_once()
        view.stop()

    async def test_concurrent_panel_updates_share_message_and_leave_removes_controls(
        self,
    ):
        await self.session.enqueue([track()], 100)
        message = Mock(edit=AsyncMock())
        self.session.text_channel.send = AsyncMock(return_value=message)
        await asyncio.gather(
            self.manager.panel(self.session), self.manager.panel(self.session)
        )
        self.session.text_channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        view = self.manager.panels[1][1]
        await self.manager.leave(1)
        self.assertTrue(view.is_finished())
        self.assertTrue(self.session.closed)
        self.assertNotIn(1, self.manager.panels)
        message.edit.assert_awaited_with(view=None)
        await self.manager.panel(self.session)
        self.session.text_channel.send.assert_awaited_once()

    async def test_idle_cleanup_continues_after_individual_guild_failure(self):
        second = MusicSession(player(), 100, Mock())
        self.manager.sessions[2] = second
        self.session.idle_since -= 181
        second.idle_since -= 181
        self.manager.leave = AsyncMock(side_effect=[RuntimeError("transport"), None])
        with self.assertLogs("app.discord_music", level="WARNING"):
            await self.manager.sweep()
        self.assertEqual([c.args[0] for c in self.manager.leave.call_args_list], [1, 2])

    async def test_stale_track_error_is_ignored_and_consecutive_errors_stop_retrying(
        self,
    ):
        await self.session.enqueue([track(str(i)) for i in range(5)], 100)
        old = self.player.play.call_args.args[0]
        await self.session.control("skip")
        self.manager.report = AsyncMock()
        self.manager.panel = AsyncMock()
        await self.manager.track_error(SimpleNamespace(player=self.player, track=old))
        self.manager.report.assert_not_awaited()
        for _ in range(3):
            await self.manager.track_error(
                SimpleNamespace(
                    player=self.player, track=self.player.play.call_args.args[0]
                )
            )
        self.assertIsNone(self.session.current)
        self.assertEqual(self.session.queue, [])
        self.assertEqual(self.manager.report.await_count, 3)

    async def test_transport_loss_reports_and_releases_only_its_music_session(self):
        self.manager.report = AsyncMock()
        self.manager.leave = AsyncMock()
        await self.manager.connection_lost(self.player)
        self.manager.leave.assert_awaited_once_with(1)
        self.manager.leave.reset_mock()
        await self.manager.connection_lost(player())
        self.manager.leave.assert_not_awaited()

    async def test_slash_registration_avoids_ai_command_collisions(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_music_commands(tree, self.manager)
        group = tree.get_command("music")
        names = {command.name for command in group.commands}
        self.assertEqual(len(names), 17)
        self.assertTrue({"play", "queue", "stop", "seek", "search", "repeat"} <= names)
        self.assertIsNone(tree.get_command("stop"))
        await client.close()
