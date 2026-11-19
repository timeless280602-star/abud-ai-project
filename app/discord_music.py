"""Lavalink music transport, access checks and reusable Discord player panels."""

import asyncio
import logging
import os
import time
from urllib.parse import urlsplit

import discord
import wavelink

from app.music_session import MusicError, MusicSession, RequestedTrack, duration, music_query
from app.music_audius_live import AudiusCatalogMode
from app.music_providers import (
    NAMES as PROVIDER_NAMES, PREFIXES, DIRECT, provider_order, same_recording, source_for_link, normalized,
)

log = logging.getLogger(__name__)


def provider_failure(source, details):
    """Classify upstream errors without returning raw provider data."""
    name = PROVIDER_NAMES.get(source, "Sumber musik")
    text = details.casefold()
    if "sign in to confirm" in text or "requires login" in text:
        return f"{name} meminta verifikasi atau login."
    if "sig function" in text or "signature cipher" in text:
        return f"{name} mengalami masalah signature audio."
    if "supported format" in text or "supported audio stream" in text:
        return f"{name} tidak menyediakan format audio yang didukung."
    if "status code: 403" in text or "http 403" in text:
        return f"{name} menolak akses audio (403)."
    if "video is unavailable" in text:
        return f"{name}: video tidak tersedia."
    if "timeout" in text or "timed out" in text:
        return f"{name} melewati batas waktu."
    return f"{name} gagal memuat audio."


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
        url=None if track.source == "http" else safe_link(track.uri),
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
    embed.add_field(name="Sumber track", value="Audius" if track.source == "http" else PROVIDER_NAMES.get(track.source, "Lainnya"))
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
    NODE_CONNECT_TIMEOUT = 15

    def __init__(self, client, voice):
        self.client, self.voice = client, voice
        self.enabled = os.getenv("ABUD_MUSIC_ENABLED", "false").lower() == "true"
        self.uri = os.getenv("ABUD_LAVALINK_URL", "http://abud-lavalink:2333")
        self.password = os.getenv("ABUD_LAVALINK_PASSWORD", "")
        self.providers = provider_order(os.getenv("ABUD_MUSIC_PROVIDERS", "soundcloud,youtube,bandcamp"))
        self.search_source = os.getenv("ABUD_MUSIC_SEARCH_SOURCE") or next(
            (p for p in self.providers if p in PREFIXES), ""
        )
        self.playback_fallback = os.getenv("ABUD_MUSIC_PLAYBACK_FALLBACK", "false").lower() == "true"
        self.audius_probe = AudiusCatalogMode()
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
            # Wavelink 3.5.2 logs unsanitized upstream exception bodies here.
            # track_error emits a safe diagnosis instead.
            logging.getLogger("TrackException").setLevel(logging.CRITICAL)
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
                async with asyncio.timeout(self.NODE_CONNECT_TIMEOUT):
                    await wavelink.Pool.connect(nodes=[self.node], client=self.client)
                    # Wavelink opens the websocket before its reader receives READY.
                    while self.node.status == wavelink.NodeStatus.CONNECTING:
                        await asyncio.sleep(0.05)
                    if self.node.status != wavelink.NodeStatus.CONNECTED:
                        raise MusicError("Lavalink belum terhubung. Coba lagi sebentar.")
            except BaseException as error:
                try:
                    await self.node.close(eject=True)
                finally:
                    self.node = None
                if isinstance(error, TimeoutError):
                    raise MusicError(
                        "Lavalink belum siap dalam batas waktu. Coba lagi sebentar."
                    ) from None
                raise
            return self.node

    async def search(self, query, source=None):
        if self.audius_probe.enabled:
            node = await self.ensure_node()
            try:
                async with asyncio.timeout(30), self.search_slots:
                    return await self.audius_probe.load(query, source, node)
            except (TimeoutError, wavelink.WavelinkException):
                raise MusicError("Audio Audius belum bisa dimuat.") from None
        if source == "audius":
            raise MusicError("Audius masih dalam pengujian terbatas.")
        query = music_query(query, self.providers)
        preferred = source or self.search_source
        direct = bool(urlsplit(query).scheme)
        if source is not None and (source not in PREFIXES or source not in self.providers):
            raise MusicError("Provider pencarian ini belum aktif.")
        if direct:
            provider = source_for_link(query)
            if source is not None and source != provider:
                raise MusicError("Pilihan provider tidak cocok dengan link lagu.")
            providers = [provider]
        else:
            if preferred not in PREFIXES or preferred not in self.providers:
                raise MusicError("Provider pencarian default belum aktif.")
            providers = [preferred]
            if source is None:
                providers.extend(p for p in self.providers if p in PREFIXES and p != preferred)
        node = await self.ensure_node()
        failures = []
        try:
            async with asyncio.timeout(30), self.search_slots:
                for provider in providers:
                    identifier = query if direct else PREFIXES[provider] + query
                    try:
                        async with asyncio.timeout(15):
                            result = await wavelink.Pool.fetch_tracks(identifier, node=node)
                    except wavelink.LavalinkLoadException as error:
                        failures.append(provider_failure(provider, f"{error.error} {error.cause}"))
                    except TimeoutError:
                        failures.append(provider_failure(provider, "timeout"))
                    except wavelink.WavelinkException:
                        raise MusicError("Koneksi layanan musik bermasalah. Coba lagi sebentar.") from None
                    else:
                        if result and (not isinstance(result, wavelink.Playlist) or result.tracks):
                            return result
                        failures.append(f"{PROVIDER_NAMES.get(provider, 'Sumber musik')}: tidak ada hasil.")
        except TimeoutError:
            raise MusicError("Pencarian musik melewati batas waktu. Coba lagi sebentar.") from None
        raise MusicError(" ".join(failures) + " Coba judul/link atau sumber lain.")

    async def play_query(self, context, query, source=None):
        """Execute a real user request; text chat and slash commands share this path."""
        self.require()
        self.user_channel(context)
        if context.guild_id in self.sessions:
            self.active(context)
        elif context.guild_id in self.voice.sessions or context.guild.voice_client:
            raise MusicError(
                "Abud sedang di mode voice lain. Tutup sesi AI dengan /leave sebelum mulai musik."
            )
        result = await self.search(query, source)
        if self.audius_probe.dynamic:
            # Never silently substitute a cover or unrelated search hit.
            q = normalized(query)
            exact = [t for t in result if q in (normalized(t.title),
                     normalized(t.title + ' ' + t.author), normalized(t.author + ' ' + t.title))]
            if not exact:
                raise MusicError("Tidak ada judul/artis yang cocok persis. Gunakan /music search untuk memilih hasil.")
            result = exact
        tracks = result.tracks if isinstance(result, wavelink.Playlist) else result[:1]
        allow_fallback = (not self.audius_probe.enabled and self.playback_fallback and source is None
                          and not urlsplit(query.strip()).scheme
                          and not isinstance(result, wavelink.Playlist))
        await self.enqueue(context, tracks, allow_fallback=allow_fallback)
        return tracks

    def user_channel(self, interaction):
        self.audius_probe.require_actor(interaction)
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

    async def enqueue(self, interaction, tracks, *, allow_fallback=False):
        self.require()
        channel = self.user_channel(interaction)
        if not tracks or len(tracks) > MusicSession.LIMIT:
            raise MusicError("Pilih 1–100 lagu per permintaan/playlist.")
        self.audius_probe.check_enqueue(tracks)
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
                session = MusicSession(player, interaction.user.id, text,
                                       before_play=self.audius_probe.before_play)
                self.sessions[interaction.guild_id] = session
                created = True
            else:
                self.active(interaction)
            try:
                await session.enqueue(tracks, interaction.user.id, allow_fallback=allow_fallback)
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
        if payload.reason == "loadFailed" and self.playback_fallback:
            await self.track_error(payload)
            return
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

    async def resolve_alternative(self, original):
        """One bounded search for a matching recording from enabled direct sources."""
        if not self.node or self.node.status != wavelink.NodeStatus.CONNECTED or original.is_stream:
            return None
        try:
            async with asyncio.timeout(8), self.search_slots:
                for provider in self.providers:
                    if provider == original.source or provider not in DIRECT or provider not in PREFIXES:
                        continue
                    try:
                        async with asyncio.timeout(3):
                            query = f"{original.title} {original.author}"[:300]
                            found = await wavelink.Pool.fetch_tracks(PREFIXES[provider] + query, node=self.node)
                    except (TimeoutError, wavelink.LavalinkLoadException):
                        continue
                    if isinstance(found, wavelink.Playlist):
                        continue
                    for candidate in found[:5]:
                        if candidate.source == provider and same_recording(original, candidate):
                            return candidate
        except (TimeoutError, wavelink.WavelinkException):
            pass
        return None

    async def track_error(self, payload):
        session = self.for_player(payload.player)
        if session:
            # Nonce invalidation also makes a subsequent loadFailed end event harmless.
            async with session.lock:
                if (
                    session.closed or not session.current or not session.nonce
                    or getattr(payload.track.extras, "abud_music_nonce", None) != session.nonce
                ):
                    return
                exception = getattr(payload, "exception", None)
                if isinstance(exception, dict):
                    details = " ".join(str(exception.get(k) or "") for k in ("message", "cause"))
                    message = provider_failure(payload.track.source, details)
                elif getattr(payload, "threshold", None) is not None:
                    message = f"{PROVIDER_NAMES.get(payload.track.source, 'Sumber musik')} macet."
                else:
                    message = provider_failure(payload.track.source, "")
                log.warning("Music provider failure: %s", message)
                current = session.current
                if (self.playback_fallback and current.allow_fallback
                        and not current.track.is_stream
                        and 0 <= session.player.position <= 5000):
                    candidate = await self.resolve_alternative(current.track)
                    if candidate is not None:
                        try:
                            await session._play(RequestedTrack(candidate, current.requester))
                        except Exception:
                            pass
                        else:
                            await self.report(session, MusicError(message + " Mencoba rekaman yang sama dari "
                                + PROVIDER_NAMES.get(candidate.source, "provider lain") + "."))
                            await self.panel(session)
                            return
                await self.report(session, MusicError(message + " Abud mencoba lagu berikutnya."))
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
