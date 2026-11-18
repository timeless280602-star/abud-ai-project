"""Discord administration, polling lifecycle and optional TikTok provider webhook."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit

import discord
from aiohttp import web
from discord import app_commands

from app.creator_notifications import (
    Creator,
    Event,
    NotificationError,
    Store,
    parse_account,
)
from app.creator_providers import YouTube, session

log = logging.getLogger(__name__)
PING = [
    app_commands.Choice(name=n, value=v)
    for n, v in [("Tanpa ping", "none"), ("@here", "here"), ("@everyone", "everyone")]
]
EVENTS = [
    app_commands.Choice(name=n, value=v)
    for n, v in [
        ("Live dan video baru", "both"),
        ("Live saja", "live"),
        ("Video baru saja", "post"),
    ]
]
PLATFORMS = [
    app_commands.Choice(name=n, value=v)
    for n, v in [("YouTube", "youtube"), ("TikTok (provider webhook)", "tiktok")]
]


class Notifications:
    def __init__(self, client):
        self.client = client
        self.enabled = (
            os.getenv("ABUD_NOTIFICATIONS_ENABLED", "false").lower() == "true"
        )
        self.path = os.getenv("ABUD_NOTIFICATIONS_DB", "/app/notifications/creators.db")
        self.key = os.getenv("YOUTUBE_API_KEY", "")
        self.webhook_secret = os.getenv("ABUD_TIKTOK_WEBHOOK_SECRET", "")
        self.interval = max(300, int(os.getenv("ABUD_NOTIFICATIONS_INTERVAL", "300")))
        self.store = self.http = self.youtube = self.task = None
        self.lock = asyncio.Lock()
        self.last_poll = None
        self.last_error = None

    def require(self):
        if not self.enabled or self.store is None:
            raise NotificationError(
                "Notifikasi belum aktif. Pengelola bot perlu mengaktifkan ABUD_NOTIFICATIONS_ENABLED."
            )

    async def start(self):
        if not self.enabled or self.task is not None:
            return
        self.store = Store(self.path)
        self.http = session()
        self.youtube = YouTube(self.http, self.key, self.store)
        self.task = asyncio.create_task(self.run(), name="creator-notifications")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.http:
            await self.http.close()
        if self.store:
            self.store.close()
        self.task = self.http = self.store = None

    async def run(self):
        while True:
            await self.client.wait_until_ready()
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - keep worker alive without logging credential-bearing provider exceptions
                self.last_error = (
                    f"Gangguan pemantauan ({type(error).__name__}); akan dicoba ulang."
                )
                log.warning("Creator poll failed: %s", type(error).__name__)
            await asyncio.sleep(self.interval)

    async def poll(self):
        rows = self.store.list()
        sources = {
            (r["account"], r["title"], r["uploads"])
            for r in rows
            if r["enabled"] and r["platform"] == "youtube"
        }
        errors = []
        for account, title, uploads in sorted(sources):
            try:
                for event in await self.youtube.poll(
                    Creator("youtube", account, title, uploads)
                ):
                    await self.dispatch(event)
            except Exception as error:  # noqa: BLE001 - keep worker alive without logging credential-bearing provider exceptions
                errors.append(type(error).__name__)
        self.last_poll = time.time()
        self.last_error = (
            ("Gangguan provider/pengiriman: " + ", ".join(sorted(set(errors))))
            if errors
            else None
        )

    def destination(self, guild_id, channel_id, ping):
        guild = self.client.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if not isinstance(channel, discord.TextChannel) or guild.me is None:
            raise NotificationError(
                "Channel tujuan tidak tersedia. Pilih text channel di server ini."
            )
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            raise NotificationError(
                "Abud perlu izin View Channel, Send Messages, dan Embed Links di channel tujuan."
            )
        if ping != "none" and not perms.mention_everyone:
            raise NotificationError(
                "Abud perlu izin Mention Everyone untuk menggunakan @here/@everyone."
            )
        return channel

    async def send(self, row, event, *, test=False):
        channel = self.destination(
            row["guild"], row["destination"], "none" if test else row["ping"]
        )
        label = "🔴 Sedang live" if event.kind == "live" else "🎬 Video baru"
        embed = discord.Embed(
            title=(
                ("UJI NOTIFIKASI — " if test else "")
                + discord.utils.escape_mentions(event.title)
            )[:256],
            description=label,
            url=(
                ("https://www.youtube.com/channel/" + row["account"])
                if event.platform == "youtube"
                else ("https://www.tiktok.com/@" + row["account"])
            )
            if test
            else event.url,
            color=0xEF4444 if event.kind == "live" else 0x2563EB,
        )
        embed.set_author(name=discord.utils.escape_mentions(row["title"])[:256])
        thumbnail = event.thumbnail
        if (
            not thumbnail
            and event.platform == "youtube"
            and re.fullmatch(r"[A-Za-z0-9_-]{11}", event.video)
        ):
            thumbnail = f"https://i.ytimg.com/vi/{event.video}/hqdefault.jpg"
        if thumbnail:
            try:
                image = urlsplit(thumbnail)
                if image.scheme == "https" and image.hostname and not image.username:
                    embed.set_image(url=thumbnail)
            except ValueError:
                pass  # A malformed optional image must not block the notification.
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Watch Live" if event.kind == "live" else "Watch Video",
                style=discord.ButtonStyle.link,
                url=embed.url,
            )
        )
        embed.set_footer(text=f"Abud • {event.platform} • langganan #{row['id']}")
        # Tests never ping. Only the explicitly selected literal is in message content.
        ping = row["ping"] if not test else "none"
        await channel.send(
            content="@" + ping if ping != "none" else None,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                everyone=ping != "none", users=False, roles=False, replied_user=False
            ),
        )

    async def dispatch(self, event):
        async with self.lock:
            failed = False
            for row in self.store.list():
                if self.store.wants(row, event):
                    try:
                        await self.send(row, event)
                        self.store.delivered(row, event)
                    except (discord.HTTPException, NotificationError):
                        failed = True
            if failed:
                raise NotificationError(
                    "Sebagian notifikasi gagal dikirim; akan dicoba ulang."
                )

    async def webhook(self, request):
        if not self.enabled or self.store is None or len(self.webhook_secret) < 32:
            raise web.HTTPServiceUnavailable()
        raw = await request.read()
        stamp = request.headers.get("X-Abud-Timestamp", "")
        signature = request.headers.get("X-Abud-Signature", "")
        if not stamp.isdigit() or abs(time.time() - int(stamp)) > 300:
            raise web.HTTPUnauthorized()
        expected = hmac.new(
            self.webhook_secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(
            signature, expected
        ):
            raise web.HTTPUnauthorized()
        try:
            data = json.loads(raw)
            account = data["account"].lower().removeprefix("@")
            video, kind = data["id"], data["kind"]
            occurred = float(data["occurred_at"])
            if (
                not re.fullmatch(r"[a-z0-9_.]{1,100}", account)
                or not re.fullmatch(r"[0-9]{1,64}", video)
                or kind not in ("live", "post")
                or not time.time() - 86400 <= occurred <= time.time() + 60
                or not isinstance(data["title"], str)
                or len(data["title"]) > 4000
            ):
                raise ValueError()
            thumbnail = data.get("thumbnail", "")
            if not isinstance(thumbnail, str) or len(thumbnail) > 2048:
                raise ValueError()
            event = Event(
                "tiktok", account, video, kind, data["title"], occurred, thumbnail
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            raise web.HTTPBadRequest(text="Invalid event") from None
        try:
            await self.dispatch(event)
        except NotificationError:
            raise web.HTTPServiceUnavailable(text="Retry delivery") from None
        return web.json_response({"accepted": True})


def install_notification_commands(tree, manager):
    group = app_commands.Group(
        name="notify",
        description="Notifikasi live dan video kreator",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    async def guard(interaction):
        if not interaction.guild or not interaction.permissions.administrator:
            raise NotificationError(
                "Pengaturan notifikasi hanya untuk Administrator server."
            )
        manager.require()
        await interaction.response.defer(ephemeral=True)

    @group.command(
        name="add",
        description="Daftarkan link channel; maksimal 10 akun per platform/server",
    )
    @app_commands.choices(platform=PLATFORMS, ping=PING, events=EVENTS)
    async def add(
        interaction: discord.Interaction,
        platform: str,
        url: str,
        destination: discord.TextChannel,
        ping: str = "none",
        events: str = "both",
    ):
        await guard(interaction)
        manager.destination(interaction.guild_id, destination.id, ping)
        if platform not in ("youtube", "tiktok"):
            raise NotificationError("Platform tidak didukung.")
        if platform == "youtube":
            creator = await manager.youtube.resolve(url)
        else:
            if len(manager.webhook_secret) < 32:
                raise NotificationError(
                    "Provider TikTok belum dihubungkan oleh pengelola bot."
                )
            _, account = parse_account("tiktok", url)
            creator = Creator("tiktok", account, "@" + account)
        ident = manager.store.add(
            interaction.guild_id, destination.id, creator, ping, events
        )
        await interaction.followup.send(
            f"Terdaftar #{ident}: {discord.utils.escape_mentions(creator.title)} → {destination.mention}. Jenis: {events}; ping: {ping}. Hanya kejadian setelah pendaftaran yang dikirim.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @group.command(name="list", description="Lihat langganan dan kondisi pemantauan")
    async def list_subscriptions(interaction: discord.Interaction):
        await guard(interaction)
        rows = manager.store.list(interaction.guild_id)
        lines = [
            f"#{r['id']} {r['platform']} · {discord.utils.escape_mentions(r['title'])[:65]} → <#{r['destination']}> · {r['events']} · ping {r['ping']} · {'aktif' if r['enabled'] else 'jeda'}"
            for r in rows
        ]
        status = manager.last_error or (
            "Pemantauan berjalan."
            if manager.last_poll
            else "Menunggu pemeriksaan pertama."
        )
        if not manager.key:
            status += " YouTube API key belum dikonfigurasi."
        pages = [""]
        for line in (lines or ["Belum ada langganan."]) + [status]:
            if len(pages[-1]) + len(line) > 1800:
                pages.append("")
            pages[-1] += line + "\n"
        for page in pages:
            await interaction.followup.send(
                page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )

    @group.command(
        name="edit",
        description="Ubah tujuan, ping, jenis notifikasi atau jeda langganan",
    )
    @app_commands.choices(ping=PING, events=EVENTS)
    async def edit(
        interaction: discord.Interaction,
        ident: int,
        destination: discord.TextChannel | None = None,
        ping: str | None = None,
        events: str | None = None,
        enabled: bool | None = None,
    ):
        await guard(interaction)
        row = manager.store.get(interaction.guild_id, ident)
        target = destination.id if destination else row["destination"]
        ping = ping if ping is not None else row["ping"]
        active = enabled if enabled is not None else bool(row["enabled"])
        if active:
            manager.destination(interaction.guild_id, target, ping)
        manager.store.edit(
            interaction.guild_id, ident, target, ping, events or row["events"], active
        )
        await interaction.followup.send(
            f"Langganan #{ident} diperbarui.", ephemeral=True
        )

    @group.command(name="remove", description="Hapus langganan dari server ini")
    async def remove(interaction: discord.Interaction, ident: int):
        await guard(interaction)
        manager.store.remove(interaction.guild_id, ident)
        await interaction.followup.send(f"Langganan #{ident} dihapus.", ephemeral=True)

    @group.command(
        name="test", description="Kirim contoh ke channel tujuan, tanpa ping"
    )
    async def test(interaction: discord.Interaction, ident: int):
        await guard(interaction)
        row = manager.store.get(interaction.guild_id, ident)
        # Canonical account URL for a preview; no invented content ID.
        event = Event(
            row["platform"],
            row["account"],
            "",
            "live",
            "Contoh tampilan notifikasi Abud",
            time.time(),
        )
        await manager.send(row, event, test=True)
        await interaction.followup.send("Contoh terkirim tanpa ping.", ephemeral=True)

    @group.error
    async def on_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        cause = getattr(error, "original", error)
        message = (
            str(cause)
            if isinstance(cause, NotificationError)
            else "Operasi gagal. Periksa izin bot dan kondisi provider, lalu coba lagi."
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.response.send_message(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )

    tree.add_command(group)
