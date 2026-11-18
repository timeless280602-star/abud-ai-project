"""Lavalink music transport, access checks and reusable Discord player panels."""

import asyncio
import logging
import os
import time
from urllib.parse import urlsplit

import discord
import wavelink

from app.music_session import MusicError, MusicSession, duration, music_query

log = logging.getLogger(__name__)


def safe_link(value):
    try:
        url = urlsplit(value or "")
        return (
            value
            if url.scheme == "https" and url.hostname and not url.username
            else None
        )
    except ValueError:
        return None


def now_embed(session):
    current = session.current
    if not current:
        return discord.Embed(
            title="🎵 Antrean selesai",
            description="Tambahkan lagu dengan `/music play`.",
            color=0xEF4444,
        )
    track = current.track
    embed = discord.Embed(
        title=discord.utils.escape_mentions(track.title)[:256],
        url=safe_link(track.uri),
        description=discord.utils.escape_mentions(track.author or "Unknown artist")[
            :1000
        ],
        color=0xEF4444,
    )
    embed.set_author(
        name="ABUD MUSIC • Paused"
        if session.player.paused
        else "ABUD MUSIC • Now Playing"
    )
    artwork = safe_link(track.artwork)
    if artwork:
        embed.set_thumbnail(url=artwork)
    length = "LIVE" if track.is_stream else duration(track.length)
    embed.add_field(
        name="Posisi / durasi", value=f"{duration(session.player.position)} / {length}"
    )
    embed.add_field(name="Diminta oleh", value=f"<@{current.requester}>")
    embed.add_field(
        name="Antrean · volume · repeat",
        value=f"{len(session.queue)} lagu · {session.volume}% · {session.repeat}",
        inline=False,
    )
    embed.set_footer(
        text="Kontrol: pemilik sesi / DJ / Manage Server • Skip juga boleh oleh peminta lagu"
    )
    return embed


def queue_embed(session, page=1):
    pages = max(1, (len(session.queue) + 9) // 10)
    if not 1 <= page <= pages:
        raise MusicError(f"Pilih halaman 1–{pages}.")
    lines = []
    for number, item in enumerate(
        session.queue[(page - 1) * 10 : page * 10], (page - 1) * 10 + 1
    ):
        title = discord.utils.escape_markdown(
            discord.utils.escape_mentions(item.track.title)
        )[:100]
        lines.append(
            f"**{number}.** {title} · {'LIVE' if item.track.is_stream else duration(item.track.length)} · <@{item.requester}>"
        )
    embed = discord.Embed(
        title=f"🎶 Antrean Abud • {len(session.queue)}/100 lagu",
        description="\n".join(lines) or "Antrean kosong.",
        color=0xEF4444,
    )
    if session.current:
        embed.add_field(
            name="Sekarang",
            value=discord.utils.escape_mentions(session.current.track.title)[:256],
        )
    embed.set_footer(
        text=f"Halaman {page}/{pages} • nomor dimulai dari lagu berikutnya"
    )
    return embed


class Music:
    def __init__(self, client, voice):
        self.client, self.voice = client, voice
        self.enabled = os.getenv("ABUD_MUSIC_ENABLED", "false").lower() == "true"
        self.uri = os.getenv("ABUD_LAVALINK_URL", "http://abud-lavalink:2333")
        self.password = os.getenv("ABUD_LAVALINK_PASSWORD", "")
        self.search_source = os.getenv("ABUD_MUSIC_SEARCH_SOURCE", "soundcloud")
        self.sessions = {}
        self.node = None
        self.node_lock = asyncio.Lock()
        self.search_slots = asyncio.Semaphore(2)
        self.watchdog = None
        self.panels = {}

    def require(self):
        if not self.enabled:
            raise MusicError("Musik belum diaktifkan oleh pengelola bot.")

    async def start(self):
        if self.enabled and not self.watchdog:
            self.watchdog = asyncio.create_task(self.watch(), name="music-watchdog")

    async def ensure_node(self):
        self.require()
        async with self.node_lock:
            if self.node and self.node.status == wavelink.NodeStatus.CONNECTED:
                return self.node
            if not self.password:
                raise MusicError(
                    "Layanan musik belum dikonfigurasi oleh pengelola bot."
                )
            if self.node and self.sessions:
                raise MusicError(
                    "Koneksi pemutar sedang pulih. Tunggu sebentar atau tutup sesi musik dulu."
                )
            if self.node:
                await self.node.close(eject=True)
            self.node = wavelink.Node(
                uri=self.uri,
                password=self.password,
                identifier="abud-music",
                retries=1,
                inactive_player_timeout=None,
            )
            try:
                async with asyncio.timeout(15):
                    await wavelink.Pool.connect(nodes=[self.node], client=self.client)
                if self.node.status != wavelink.NodeStatus.CONNECTED:
                    raise MusicError("Lavalink belum terhubung. Coba lagi sebentar.")
            except BaseException:
                await self.node.close(eject=True)
                self.node = None
                raise
            return self.node

    async def search(self, query, source=None):
        query = music_query(query)
        node = await self.ensure_node()
        source = source or self.search_source
        if source not in ("youtube", "soundcloud"):
            raise MusicError("Sumber pencarian harus YouTube atau SoundCloud.")
        prefix = "ytsearch:" if source == "youtube" else "scsearch:"
        identifier = query if urlsplit(query).scheme else prefix + query
        async with asyncio.timeout(15), self.search_slots:
            result = await wavelink.Pool.fetch_tracks(identifier, node=node)
        if not result:
            raise MusicError(
                "Lagu tidak ditemukan atau sumber tidak tersedia. Coba judul/link atau sumber lain."
            )
        return result

    def user_channel(self, interaction):
        channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
        if not interaction.guild or not isinstance(channel, discord.VoiceChannel):
            raise MusicError("Masuk ke voice channel biasa dulu.")
        return channel

    def active(self, interaction, *, control=False, action=None, expected=None):
        self.require()
        session = self.sessions.get(interaction.guild_id)
        if (
            not session
            or session.closed
            or (expected is not None and session is not expected)
        ):
            raise MusicError("Sesi musik ini sudah selesai. Gunakan /music play.")
        if self.user_channel(interaction).id != session.channel_id:
            raise MusicError("Masuk ke voice channel yang sama dengan Abud dulu.")
        privileged = (
            interaction.user.id == session.owner
            or interaction.user.guild_permissions.manage_guild
            or any(role.name.casefold() == "dj" for role in interaction.user.roles)
        )
        owns_track = (
            action == "skip"
            and session.current
            and session.current.requester == interaction.user.id
        )
        if control and not (privileged or owns_track):
            raise MusicError(
                "Kontrol ini untuk pemilik sesi, role DJ, atau pengelola server. Peminta lagu juga boleh skip lagunya sendiri."
            )
        return session

    async def enqueue(self, interaction, tracks):
        self.require()
        channel = self.user_channel(interaction)
        if not tracks or len(tracks) > MusicSession.LIMIT:
            raise MusicError("Pilih 1–100 lagu per permintaan/playlist.")
        # Shared lock prevents simultaneous music/AI joins creating competing connections.
        async with self.voice.lock:
            session = self.sessions.get(interaction.guild_id)
            created = False
            if not session:
                if (
                    interaction.guild_id in self.voice.sessions
                    or interaction.guild.voice_client
                ):
                    raise MusicError(
                        "Abud sedang di mode voice lain. Tutup sesi AI dengan /leave sebelum mulai musik."
                    )
                if len(self.sessions) >= 2:
                    raise MusicError(
                        "Dua sesi musik sedang aktif. Coba lagi setelah salah satunya selesai."
                    )
                perms = channel.permissions_for(interaction.guild.me)
                if not (perms.view_channel and perms.connect and perms.speak):
                    raise MusicError(
                        "Abud perlu izin View Channel, Connect, dan Speak di voice channel."
                    )
                text = interaction.channel
                perms = text.permissions_for(interaction.guild.me)
                if not (
                    perms.view_channel and perms.send_messages and perms.embed_links
                ):
                    raise MusicError(
                        "Abud perlu View Channel, Send Messages, dan Embed Links untuk panel musik."
                    )
                node = await self.ensure_node()
                # Recheck member position after network I/O before connecting.
                if self.user_channel(interaction).id != channel.id:
                    raise MusicError(
                        "Voice channel berubah saat mencari lagu. Coba /music play lagi."
                    )
                player = await channel.connect(
                    cls=lambda client, channel: wavelink.Player(
                        client, channel, nodes=[node]
                    ),
                    timeout=20,
                    self_deaf=True,
                    reconnect=True,
                )
                player.autoplay = wavelink.AutoPlayMode.disabled
                player.inactive_timeout = None
                session = MusicSession(player, interaction.user.id, text)
                self.sessions[interaction.guild_id] = session
                created = True
            else:
                self.active(interaction)
            try:
                await session.enqueue(tracks, interaction.user.id)
            except BaseException:
                if created:
                    self.sessions.pop(interaction.guild_id, None)
                    await session.close()
                raise
        await self.panel(session)
        return session

    async def panel(self, session):
        async with session.panel_lock:
            await self._panel(session)

    async def _panel(self, session):
        if session.closed:
            return
        guild_id = session.player.guild.id
        old = self.panels.get(guild_id)
        view = MusicControls(self, session)
        try:
            if old:
                await old[0].edit(embed=now_embed(session), view=view)
                old[1].stop()
                self.panels[guild_id] = (old[0], view)
            else:
                message = await session.text_channel.send(
                    embed=now_embed(session),
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self.panels[guild_id] = (message, view)
        except discord.HTTPException:
            view.stop()
            if old:
                old[1].stop()
                self.panels.pop(guild_id, None)

    async def apply(self, interaction, action, value=None, *, expected=None):
        session = self.active(
            interaction, control=True, action=action, expected=expected
        )
        if action == "leave":
            await self.leave(interaction.guild_id)
        else:
            await session.control(action, value)
            await self.panel(session)

    async def leave(self, guild_id):
        async with self.voice.lock:
            session = self.sessions.pop(guild_id, None)
            if not session:
                return
            try:
                async with asyncio.timeout(10):
                    await session.close()
            except Exception:  # noqa: BLE001 - always release Discord's local voice registration
                session.player.cleanup()
                try:
                    await session.player.guild.change_voice_state(channel=None)
                except (discord.HTTPException, discord.ClientException):
                    pass
            async with session.panel_lock:
                panel = self.panels.pop(guild_id, None)
                if panel:
                    panel[1].stop()
                    try:
                        await panel[0].edit(view=None)
                    except discord.HTTPException:
                        pass

    async def track_end(self, payload):
        session = self.for_player(payload.player)
        if not session:
            return
        try:
            if await session.ended(
                getattr(payload.track.extras, "abud_music_nonce", None), payload.reason
            ):
                await self.panel(session)
        except Exception as error:  # noqa: BLE001 - event boundary must not expose provider data
            await self.report(session, error)

    def for_player(self, player):
        session = (
            self.sessions.get(player.guild.id) if player and player.guild else None
        )
        return (
            session
            if session and session.player is player and not session.closed
            else None
        )

    async def track_error(self, payload):
        session = self.for_player(payload.player)
        if session:
            # Nonce invalidation also makes a subsequent loadFailed end event harmless.
            async with session.lock:
                if (
                    getattr(payload.track.extras, "abud_music_nonce", None)
                    != session.nonce
                ):
                    return
                await self.report(
                    session,
                    MusicError(
                        "Sumber lagu gagal atau macet; Abud mencoba lagu berikutnya."
                    ),
                )
                session.failures += 1
                if session.failures >= 3:
                    session.queue.clear()
                    session.repeat = "off"
                try:
                    await session._next()
                except MusicError as error:
                    await self.report(session, error)
            await self.panel(session)

    async def report(self, session, error):
        log.warning("Music action failed (%s)", type(error).__name__)
        try:
            await session.text_channel.send(
                str(error)
                if isinstance(error, MusicError)
                else "Layanan musik sedang bermasalah. Coba lagu/sumber lain.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass

    async def connection_lost(self, player):
        session = self.for_player(player)
        if session:
            await self.report(
                session,
                MusicError(
                    "Koneksi audio terputus. Sesi ditutup; gunakan /music play untuk mulai lagi."
                ),
            )
            await self.leave(player.guild.id)

    async def node_lost(self, payload):
        if payload.node is self.node:
            for session in list(self.sessions.values()):
                await self.connection_lost(session.player)

    async def voice_state_update(self, member, before, after):
        session = self.sessions.get(member.guild.id)
        if not session:
            return
        if (
            member.id == self.client.user.id
            and (not after.channel or after.channel.id != session.channel_id)
            or not any(not person.bot for person in session.player.channel.members)
        ):
            await self.leave(member.guild.id)

    async def sweep(self):
        for guild_id, session in list(self.sessions.items()):
            try:
                if (
                    not session.player.connected
                    or not any(not m.bot for m in session.player.channel.members)
                    or (
                        not session.current
                        and time.monotonic() - session.idle_since >= 180
                    )
                    or (
                        session.player.paused
                        and time.monotonic() - session.idle_since >= 1800
                    )
                ):
                    await self.leave(guild_id)
            except Exception as error:  # noqa: BLE001 - one broken guild must not stop cleanup of others
                log.warning("Music cleanup failed (%s)", type(error).__name__)

    async def watch(self):
        while True:
            await asyncio.sleep(5)
            await self.sweep()

    async def close(self):
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
            self.watchdog = None
        for guild_id in list(self.sessions):
            await self.leave(guild_id)
        if self.node:
            await self.node.close(eject=True)
            self.node = None


class MusicControls(discord.ui.View):
    def __init__(self, manager, session):
        super().__init__(timeout=None)
        self.manager, self.session = manager, session
        for label, action, style in [
            ("⏯ Pause / Resume", "toggle", discord.ButtonStyle.primary),
            ("⏭ Skip", "skip", discord.ButtonStyle.secondary),
            ("🔀 Shuffle", "shuffle", discord.ButtonStyle.secondary),
            ("⏹ Stop", "stop", discord.ButtonStyle.danger),
            ("📜 Queue", "queue", discord.ButtonStyle.secondary),
        ]:
            button = discord.ui.Button(label=label, style=style)

            async def callback(interaction, action=action):
                await interaction.response.defer(ephemeral=True)
                try:
                    if action == "queue":
                        current = manager.active(interaction, expected=session)
                        await interaction.followup.send(
                            embed=queue_embed(current),
                            ephemeral=True,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        return
                    resolved = (
                        ("resume" if session.player.paused else "pause")
                        if action == "toggle"
                        else action
                    )
                    await manager.apply(interaction, resolved, expected=session)
                    await interaction.followup.send(
                        "Kontrol musik diperbarui.", ephemeral=True
                    )
                except Exception as error:  # noqa: BLE001 - sanitize UI failures
                    await interaction.followup.send(
                        str(error)
                        if isinstance(error, MusicError)
                        else "Kontrol gagal. Coba lagi setelah layanan musik siap.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

            button.callback = callback
            self.add_item(button)
