"""Transport boundaries: HTTP auth, Discord controls, PCM playback, DAVE decoding."""

import asyncio
import io
import json
import os
import unittest
import wave
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord
from aiohttp import web
from discord import app_commands
from discord.ext.voice_recv.opus import PacketDecoder

from app.discord_voice import (
    DiscordVoice,
    GuildVoice,
    VoiceError,
    VoiceServices,
    install_voice_commands,
)


def wav_fixture():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setframerate(22050)
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.writeframes(b"\x00" * 4410)
    return output.getvalue()


class HTTPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.status = 200
        self.bad_audio = False

        async def handle(request):
            self.calls.append((request.path, dict(request.headers), await request.read()))
            if self.status != 200:
                return web.Response(status=self.status, text="PRIVATE_PROVIDER_BODY")
            if request.path == "/transcribe":
                return web.json_response({"text": "Abud halo"})
            if request.path == "/chat":
                return web.json_response({"reply": "Halo!"})
            return web.Response(body=b"invalid" if self.bad_audio else wav_fixture())

        async def health(request):
            return web.json_response({"status": "healthy"})

        app = web.Application()
        app.router.add_post("/{path}", handle)
        app.router.add_get("/health", health)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
        self.service = VoiceServices(
            self.url + "/chat",
            self.url,
            "fixture-key",
            lambda user, text: {"user_id": str(user), "message": text},
        )

    async def asyncTearDown(self):
        await self.service.close()
        await self.runner.cleanup()

    async def test_wav_roundtrip_and_api_identity_only_send_key_to_api(self):
        self.assertEqual(await self.service.transcribe(wav_fixture()), "Abud halo")
        self.assertEqual(await self.service.reply(44, "halo"), "Halo!")
        audio = await self.service.synthesize("Halo!")
        self.assertEqual(audio, wav_fixture())
        self.assertNotIn("Authorization", self.calls[0][1])
        self.assertEqual(self.calls[1][1]["Authorization"], "Bearer fixture-key")
        self.assertEqual(json.loads(self.calls[1][2]), {"user_id": "44", "message": "halo"})
        self.assertNotIn("Authorization", self.calls[2][1])

    async def test_busy_failure_and_invalid_audio_are_safe(self):
        self.status = 429
        with self.assertRaisesRegex(VoiceError, "sibuk"):
            await self.service.transcribe(wav_fixture())
        self.status = 500
        with self.assertRaises(VoiceError) as failure:
            await self.service.reply(1, "halo")
        self.assertNotIn("PRIVATE_PROVIDER_BODY", str(failure.exception))
        self.status = 200
        self.bad_audio = True
        with self.assertRaisesRegex(VoiceError, "tidak valid"):
            await self.service.synthesize("Halo!")

    async def test_oversize_upstream_response_is_bounded(self):
        with (
            patch("app.discord_voice.MAX_RESPONSE", 8),
            self.assertRaisesRegex(VoiceError, "terlalu besar"),
        ):
            await self.service.transcribe(wav_fixture())

    async def test_failed_join_notice_rolls_back_and_allows_retry(self):
        channel = Mock(spec=discord.VoiceChannel)
        channel.id = 44
        channel.permissions_for.return_value = NS(
            view_channel=True, connect=True, speak=True, send_messages=True
        )
        channel.send = AsyncMock(side_effect=RuntimeError("notice failed"))
        member = NS(id=55, voice=NS(channel=channel))
        guild = NS(id=10, me=NS(id=100), voice_client=None)
        vc = Mock(channel=channel, guild=guild, disconnect=AsyncMock())
        channel.connect = AsyncMock(return_value=vc)
        manager = DiscordVoice(NS(user=NS(id=100)), self.url + "/chat", "fixture")
        interaction = NS(guild_id=10, guild=guild, user=member)
        env = {"ABUD_DISCORD_VOICE_ENABLED": "true", "ABUD_DISCORD_VOICE_WORKER_URL": self.url}
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(RuntimeError, "notice failed"):
                await manager.join(interaction)
            self.assertEqual(manager.sessions, {})
            vc.disconnect.assert_awaited_once_with(force=True)
            vc.listen.assert_not_called()
            channel.send.side_effect = None
            await manager.join(interaction)
            self.assertIn(10, manager.sessions)
            vc.listen.assert_called_once()
            with self.assertRaisesRegex(VoiceError, "sudah terhubung"):
                await manager.join(interaction)
            await manager.close()

    async def test_join_checks_permissions_before_connecting(self):
        channel = Mock(spec=discord.VoiceChannel)
        channel.permissions_for.return_value = NS(
            view_channel=True, connect=True, speak=False, send_messages=True
        )
        channel.connect = AsyncMock()
        manager = DiscordVoice(NS(), self.url + "/chat", "fixture")
        interaction = NS(user=NS(voice=NS(channel=channel)), guild=NS(me=NS()))
        with (
            patch.dict(
                os.environ,
                {"ABUD_DISCORD_VOICE_ENABLED": "true", "ABUD_DISCORD_VOICE_WORKER_URL": self.url},
            ),
            self.assertRaisesRegex(VoiceError, "izin"),
        ):
            await manager.join(interaction)
        channel.connect.assert_not_called()


class DiscordLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.channel = NS(id=12, send=AsyncMock(), members=[])
        self.member = NS(
            id=55,
            display_name="Tester",
            bot=False,
            voice=NS(channel=self.channel, mute=False, self_mute=False),
            guild_permissions=NS(administrator=False, manage_guild=False),
        )
        self.guild = NS(
            id=10,
            name="Guild",
            owner_id=99,
            get_member=lambda uid: self.member if uid == 55 else None,
        )
        self.member.guild = self.guild
        self.vc = Mock(channel=self.channel, guild=self.guild)
        self.vc.is_connected.return_value = True
        self.vc.is_listening.return_value = True
        self.vc.disconnect = AsyncMock()
        self.manager = DiscordVoice(NS(user=NS(id=100)), "http://api.test/chat", "fixture-key")
        self.session = GuildVoice(self.manager, self.vc, 55, "http://worker.test")
        self.manager.sessions[10] = self.session
        self.interaction = NS(guild_id=10, user=self.member)

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_payload_uses_real_member_guild_channel_and_permissions(self):
        payload = self.session.payload(55, "halo")
        self.assertEqual(
            (payload["user_id"], payload["guild_id"], payload["channel_id"]), ("55", "10", "12")
        )
        self.assertEqual(payload["response_mode"], "voice")
        self.assertFalse(payload["can_manage_guild_memory"])
        self.member.guild_permissions.administrator = True
        self.assertTrue(self.session.payload(55, "halo")["can_manage_guild_memory"])
        self.member.voice.channel = NS(id=13)
        with self.assertRaises(VoiceError):
            self.session.payload(55, "halo")

    async def test_controls_require_same_channel_and_leave_owner_or_manager(self):
        self.assertIs(self.manager.active(self.interaction, control=True), self.session)
        self.session.owner_id = 99
        with self.assertRaises(VoiceError):
            self.manager.active(self.interaction, control=True)
        self.member.guild_permissions.manage_guild = True
        self.assertIs(self.manager.active(self.interaction, control=True), self.session)
        self.member.voice.channel = NS(id=13)
        with self.assertRaises(VoiceError):
            self.manager.active(self.interaction)

    async def test_kick_cleans_connection_http_and_all_tasks(self):
        self.session.start()
        tasks = list(self.session.core.tasks)
        await self.manager.voice_state_update(
            NS(id=100, guild=self.guild), NS(channel=self.channel), NS(channel=None)
        )
        self.assertEqual(self.manager.sessions, {})
        self.vc.disconnect.assert_awaited_once_with(force=True)
        self.assertTrue(self.session.services.http.closed)
        self.assertTrue(all(task.done() for task in tasks))
        self.assertTrue(self.session.core.collector.paused)

    async def test_departing_member_is_unenrolled_and_empty_channel_closes(self):
        self.member.voice.channel = None
        await self.manager.voice_state_update(
            self.member, NS(channel=self.channel), NS(channel=None)
        )
        self.assertNotIn(55, self.session.core.collector.allowed)
        self.assertNotIn(10, self.manager.sessions)

    async def test_disabled_feature_does_not_open_connection(self):
        with (
            patch.dict(os.environ, {"ABUD_DISCORD_VOICE_ENABLED": "false"}),
            self.assertRaisesRegex(VoiceError, "belum diaktifkan"),
        ):
            await self.manager.join(self.interaction)

    async def test_ffmpeg_decodes_real_wav_and_stop_preserves_receiver(self):
        output = []

        def play(source, after):
            # Production's AudioPlayer reads on a thread; use the same boundary here.
            async def read_source():
                output.append(await asyncio.to_thread(source.read))
                after(None)

            asyncio.create_task(read_source())

        self.vc.play.side_effect = play
        await self.session.play(wav_fixture())
        self.assertEqual(len(output[0]), 3840)
        self.vc.stop_playing.assert_called()
        self.vc.stop.assert_not_called()
        self.vc.stop_listening.assert_not_called()

    async def test_commands_are_guild_only_and_distinct_from_existing_text_commands(self):
        client = discord.Client(intents=discord.Intents.default())
        tree = app_commands.CommandTree(client)
        install_voice_commands(tree, self.manager)
        self.assertEqual(
            {cmd.name for cmd in tree.get_commands()},
            {"join", "leave", "listen", "stop", "voice-status"},
        )
        self.assertTrue(all(cmd.guild_only for cmd in tree.get_commands()))
        await client.close()


class DaveReceiveTests(unittest.TestCase):
    """Exercise the installed pinned receiver, not a copied implementation."""

    def setUp(self):
        self.session = Mock(ready=True)
        self.session.decrypt.return_value = b"plain-opus"
        self.member = NS(id=55)
        self.vc = NS(
            _connection=NS(dave_protocol_version=1, dave_session=self.session),
            _get_id_from_ssrc=lambda ssrc: 55,
            guild=NS(get_member=lambda uid: self.member),
        )
        sink = NS(wants_opus=lambda: True, voice_client=self.vc)
        self.decoder = PacketDecoder(NS(sink=sink), 7)
        self.packet = Mock(sequence=3, timestamp=960, decrypted_data=b"encrypted")
        self.packet.is_silence.return_value = False

    def test_ciphertext_is_decrypted_with_actual_speaker_id(self):
        data = self.decoder._process_packet(self.packet)
        self.assertIs(data.source, self.member)
        self.assertEqual(data.opus, b"plain-opus")
        self.assertEqual(self.session.decrypt.call_args.args[0], 55)

    def test_failed_decryption_drops_packet_before_opus(self):
        self.session.decrypt.side_effect = RuntimeError("bad packet")
        self.assertIsNone(self.decoder._process_packet(self.packet))
        self.assertEqual(self.decoder._last_seq, 3)

    def test_fec_peek_decrypts_once_then_reuses_plaintext(self):
        self.assertTrue(self.decoder._dave_decrypt(self.packet, peek=True))
        self.assertTrue(self.decoder._dave_decrypt(self.packet))
        self.session.decrypt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
