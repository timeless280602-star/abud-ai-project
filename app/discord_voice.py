"""Discord voice transport and slash commands. No audio is written to disk."""

import asyncio
import io
import json
import logging
import os
import time

import aiohttp
import discord
from discord import app_commands

from app.voice_session import VoiceSession
from app.music_session import MusicError

log = logging.getLogger(__name__)
MAX_RESPONSE = 16 * 1024 * 1024


class VoiceError(Exception):
    """An actionable error safe to display without upstream response bodies."""


async def decode_wav(audio):
    """Decode before playback with bounded duration and deterministic process cleanup."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "pipe",
        "-threads",
        "1",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-t",
        "60",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-f",
        "s16le",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(10):
            pcm, _ = await process.communicate(audio)
        if process.returncode != 0 or not pcm:
            raise VoiceError("Audio jawaban tidak bisa diputar.")
        return pcm
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


class VoiceServices:
    def __init__(self, api_url, worker_url, key, payload):
        self.api_url, self.worker_url, self.key, self.payload = (
            api_url,
            worker_url.rstrip("/"),
            key,
            payload,
        )
        self.http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=95, connect=5), trust_env=False
        )

    async def request(self, url, *, content=None, content_type=None, payload=None, auth=False):
        headers = {"Authorization": f"Bearer {self.key}"} if auth else {}
        if content_type:
            headers["Content-Type"] = content_type
        async with self.http.post(
            url, data=content, json=payload, headers=headers, allow_redirects=False
        ) as response:
            if response.status != 200:
                if response.status == 429:
                    raise VoiceError("Layanan suara sedang sibuk. Coba panggil Abud lagi sebentar.")
                raise VoiceError("Layanan suara/AI belum merespons. Coba lagi sebentar.")
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                if len(data) + len(chunk) > MAX_RESPONSE:
                    raise VoiceError(
                        "Respons suara terlalu besar. Coba pertanyaan yang lebih singkat."
                    )
                data.extend(chunk)
            return bytes(data)

    async def transcribe(self, audio):
        data = await self.request(
            self.worker_url + "/transcribe", content=audio, content_type="audio/wav"
        )
        text = json.loads(data).get("text", "")
        if not isinstance(text, str) or len(text) > 6000:
            raise VoiceError("Ucapan belum terbaca dengan jelas. Coba ulangi lebih singkat.")
        return text

    async def reply(self, user_id, prompt):
        data = await self.request(self.api_url, payload=self.payload(user_id, prompt), auth=True)
        reply = json.loads(data).get("reply", "")
        if not isinstance(reply, str) or not reply.strip():
            raise VoiceError("Abud belum mendapat jawaban. Coba panggil lagi.")
        return reply

    async def synthesize(self, text):
        data = await self.request(
            self.worker_url + "/synthesize", content=text.encode(), content_type="text/plain"
        )
        if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
            raise VoiceError("Audio jawaban tidak valid. Coba lagi sebentar.")
        return data

    async def close(self):
        await self.http.close()


class DiscordVoice:
    def __init__(self, client, api_url, key):
        self.client, self.api_url, self.key = client, api_url, key
        self.sessions = {}
        self.lock = asyncio.Lock()

    def configured(self):
        return os.getenv("ABUD_DISCORD_VOICE_ENABLED", "").lower() in ("1", "true", "yes") and bool(
            os.getenv("ABUD_DISCORD_VOICE_WORKER_URL")
        )

    def active(self, interaction, *, control=False):
        session = self.sessions.get(interaction.guild_id)
        if not session:
            raise VoiceError("Abud belum masuk voice channel. Gunakan /join dulu.")
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel or voice.channel.id != session.vc.channel.id:
            raise VoiceError("Masuk ke voice channel yang sama dengan Abud dulu.")
        if (
            control
            and interaction.user.id != session.owner_id
            and not interaction.user.guild_permissions.manage_guild
        ):
            raise VoiceError("Kontrol ini untuk pembuka sesi atau pengelola server.")
        return session

    async def join(self, interaction):
        if not self.configured():
            raise VoiceError("Voice Abud belum diaktifkan di server bot.")
        channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
        if not isinstance(channel, discord.VoiceChannel):
            raise VoiceError("Masuk ke voice channel biasa dulu, lalu gunakan /join.")
        if not all(
            getattr(channel.permissions_for(interaction.guild.me), perm)
            for perm in ("view_channel", "connect", "speak", "send_messages")
        ):
            raise VoiceError(
                "Abud perlu izin View Channel, Connect, Speak, dan Send Messages di voice channel itu."
            )
        # Receiver is imported lazily so an optional voice dependency cannot break text chat.
        from discord.ext import voice_recv

        async with self.lock:
            if interaction.guild_id in self.sessions or interaction.guild.voice_client:
                raise VoiceError("Abud sudah terhubung. Gunakan /leave di sesi sebelumnya dulu.")
            if len(self.sessions) >= 2:
                raise VoiceError(
                    "Dua sesi voice Abud sedang aktif. Coba lagi setelah salah satunya selesai."
                )
            # Verify the worker before connecting/listening. It has no public ports.
            worker_url = os.environ["ABUD_DISCORD_VOICE_WORKER_URL"].rstrip("/")
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5), trust_env=False
                ) as http,
                http.get(worker_url + "/health", allow_redirects=False) as response,
            ):
                if response.status != 200:
                    raise VoiceError("Whisper/Piper belum siap. Coba /join lagi sebentar.")
            vc = await channel.connect(
                cls=voice_recv.VoiceRecvClient, timeout=20, reconnect=True, self_deaf=False
            )
            session = None
            try:
                session = GuildVoice(self, vc, interaction.user.id, worker_url)
                # Publish the listening notice in the actual voice channel before capture starts.
                await channel.send(
                    "🎙️ Abud masuk! Suaramu akan diproses menjadi teks untuk dijawab AI. "
                    "Pembuka sesi sudah aktif; member lain gunakan `/listen aktif:True`. "
                    "Awali setiap pertanyaan dengan **Abud**, maksimal 12 detik. "
                    "`/listen aktif:False` berhenti didengar; `/stop` hentikan jawaban; `/leave` keluar.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self.sessions[interaction.guild_id] = session
                session.start()
            except BaseException:
                self.sessions.pop(interaction.guild_id, None)
                if session:
                    await session.close()
                else:
                    await vc.disconnect(force=True)
                raise

    async def leave(self, guild_id):
        async with self.lock:
            session = self.sessions.pop(guild_id, None)
            if session:
                await session.close()

    async def voice_state_update(self, member, before, after):
        session = self.sessions.get(member.guild.id)
        if not session:
            return
        if member.id == self.client.user.id:
            if (
                not after.channel
                or after.channel.id != session.channel_id
                or after.deaf
                or after.self_deaf
            ):
                await self.leave(member.guild.id)
            return
        if (
            before.channel
            and before.channel.id == session.channel_id
            and (not after.channel or after.channel.id != session.channel_id)
        ):
            await session.unenroll(member.id)
        if not any(not person.bot for person in session.vc.channel.members):
            await self.leave(member.guild.id)

    async def close(self):
        for guild_id in list(self.sessions):
            await self.leave(guild_id)


class GuildVoice:
    def __init__(self, manager, vc, owner_id, worker_url):
        self.manager, self.vc, self.owner_id = manager, vc, owner_id
        self.channel_id = vc.channel.id
        self.services = VoiceServices(manager.api_url, worker_url, manager.key, self.payload)
        self.core = VoiceSession(
            self.services,
            eligible=self.eligible,
            play=self.play,
            stop_playing=vc.stop_playing,
            report=self.report,
        )
        self.core.collector.enroll(owner_id)
        self.watchdog = None
        self.last_error = 0

    def eligible(self, user_id):
        member = self.vc.guild.get_member(user_id)
        voice = getattr(member, "voice", None)
        return bool(
            not self.core.closed
            and self.vc.is_connected()
            and member
            and not member.bot
            and user_id in self.core.collector.allowed
            and voice
            and voice.channel
            and voice.channel.id == self.channel_id
        )

    def payload(self, user_id, prompt):
        if not self.eligible(user_id):
            raise VoiceError("Pembicara sudah meninggalkan sesi.")
        member, guild = self.vc.guild.get_member(user_id), self.vc.guild
        return {
            "message": prompt,
            "user_id": str(user_id),
            "username": member.display_name,
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "guild_owner_id": str(guild.owner_id),
            "channel_id": str(self.channel_id),
            "context_type": "guild",
            "response_mode": "voice",
            "can_manage_guild_memory": user_id == guild.owner_id
            or member.guild_permissions.administrator,
        }

    def start(self):
        from discord.ext import voice_recv

        core = self.core

        class Sink(voice_recv.AudioSink):
            def wants_opus(self):
                return False

            def write(self, user, data):
                if user and not user.bot and not core.closed:
                    core.collector.feed(user.id, data.pcm)

            def cleanup(self):
                core.collector.clear()

        # Receiver callbacks run on another thread. Cleanup is handled by the watchdog.
        self.vc.listen(Sink())
        core.start()
        self.watchdog = asyncio.create_task(self._watch())

    async def play(self, audio):
        source = discord.PCMAudio(io.BytesIO(await decode_wav(audio)))
        loop = asyncio.get_running_loop()
        finished = loop.create_future()

        def after(error):
            def settle():
                if not finished.done():
                    finished.set_exception(error) if error else finished.set_result(None)

            if not loop.is_closed():
                loop.call_soon_threadsafe(settle)

        try:
            self.vc.play(source, after=after)
            await asyncio.wait_for(finished, timeout=80)
        finally:
            self.vc.stop_playing()  # VoiceRecvClient.stop() would also stop listening.
            source.cleanup()

    async def report(self, error):
        # Avoid recording transcripts, credentials, provider bodies, or raw audio in logs.
        log.warning("Discord voice turn failed (%s)", type(error).__name__)
        if time.monotonic() - self.last_error < 30:
            return
        self.last_error = time.monotonic()
        text = (
            str(error)
            if isinstance(error, VoiceError)
            else "Abud belum bisa menjawab suara. Coba panggil lagi sebentar."
        )
        try:
            await self.vc.channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def unenroll(self, user_id):
        await self.core.unenroll(user_id)

    async def _watch(self):
        try:
            while not self.core.closed:
                await asyncio.sleep(2)
                if (
                    not self.vc.is_connected()
                    or not self.vc.is_listening()
                    or (
                        self.core.state == "listening"
                        and time.monotonic() - self.core.last_activity > 300
                    )
                ):
                    await self.manager.leave(self.vc.guild.id)
                    return
        except asyncio.CancelledError:
            pass

    async def close(self):
        if self.watchdog and self.watchdog is not asyncio.current_task():
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
        await self.core.close()
        try:
            self.vc.stop_listening()
            await self.vc.disconnect(force=True)
        finally:
            await self.services.close()


def install_voice_commands(tree, manager, *, music_manager=None):
    async def run(interaction, action):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            text = await action()
        except (VoiceError, MusicError) as error:
            text = str(error)
        except Exception as error:  # noqa: BLE001 - slash-command boundary must sanitize failures
            log.warning("Discord voice command failed (%s)", type(error).__name__)
            text = "Voice belum siap. Periksa layanan Whisper/Piper, koneksi Discord, dan izin bot."
        await interaction.followup.send(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @tree.command(name="join", description="Ajak Abud ngobrol di voice channel kamu.")
    @app_commands.guild_only()
    async def join(interaction: discord.Interaction):
        async def action():
            await manager.join(interaction)
            return "Abud siap! Ucapkan ‘Abud’ di awal setiap pertanyaan."

        await run(interaction, action)

    @tree.command(name="leave", description="Putuskan koneksi Abud dari voice channel, bukan server.")
    @app_commands.guild_only()
    async def leave(interaction: discord.Interaction):
        async def action():
            guild_id = interaction.guild_id
            if guild_id is None:
                raise VoiceError("Gunakan command ini di server Discord.")
            if music_manager is not None and guild_id in music_manager.sessions:
                route = "music"
            elif guild_id in manager.sessions:
                route = "voice"
            else:
                log.info("Voice-only leave: guild=%s route=none outcome=no_session", guild_id)
                return "Abud belum masuk voice channel. Tidak ada sesi musik atau AI voice aktif."
            log.info("Voice-only leave: guild=%s route=%s outcome=requested", guild_id, route)
            try:
                if route == "music":
                    await music_manager.apply(interaction, "leave")
                else:
                    manager.active(interaction, control=True)
                    await manager.leave(guild_id)
            except (MusicError, VoiceError):
                log.info("Voice-only leave: guild=%s route=%s outcome=rejected", guild_id, route)
                raise
            log.info("Voice-only leave: guild=%s route=%s outcome=completed", guild_id, route)
            return "Sesi selesai. Abud keluar dari voice channel, bukan dari server."

        await run(interaction, action)

    @tree.command(
        name="listen", description="Aktifkan atau matikan pemrosesan suaramu di sesi Abud."
    )
    @app_commands.guild_only()
    @app_commands.describe(aktif="True: dengarkan suaraku; False: berhenti mendengarkan.")
    async def listen(interaction: discord.Interaction, aktif: bool):
        async def action():
            session = manager.active(interaction)
            if aktif:
                try:
                    session.core.collector.enroll(interaction.user.id)
                except ValueError as error:
                    raise VoiceError(str(error)) from None
            else:
                await session.unenroll(interaction.user.id)
            return (
                "Suaramu aktif. Awali pertanyaan dengan ‘Abud’."
                if aktif
                else "Abud berhenti memproses suaramu."
            )

        await run(interaction, action)

    @tree.command(name="stop", description="Hentikan jawaban dan antrean tanpa keluar dari voice.")
    @app_commands.guild_only()
    async def stop(interaction: discord.Interaction):
        async def action():
            await manager.active(interaction).core.stop()
            return "Jawaban dan antrean dihentikan. Abud tetap siap mendengarkan."

        await run(interaction, action)

    @tree.command(
        name="voice-status", description="Lihat koneksi, pendengar, dan antrean voice Abud."
    )
    @app_commands.guild_only()
    async def status(interaction: discord.Interaction):
        async def action():
            session = manager.active(interaction)
            core = session.core
            labels = {
                "listening": "Siap mendengarkan",
                "transcribing": "Membaca ucapan",
                "thinking": "Menyiapkan jawaban",
                "synthesizing": "Membuat suara",
                "speaking": "Sedang berbicara",
            }
            return (
                f"🎙️ **{labels[core.state]}**\nPendengar aktif: {len(core.collector.allowed)}/8"
                f" · Antrean: {core.queue.qsize()}/3\nJawaban selesai: {core.completed}"
                f" · Antrean penuh/kedaluwarsa: {core.dropped}\nPanggilan: **Abud** · Batas ucapan: **12 detik**"
            )

        await run(interaction, action)
