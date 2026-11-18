"""Private support-ticket channel lifecycle and stateless persistent controls."""

import asyncio
import logging
import os
import time
from pathlib import Path

import discord

from app.ticket_store import KINDS, TicketError, TicketStore

log = logging.getLogger(__name__)
PARTICIPANT_PERMS = (
    "view_channel",
    "read_message_history",
    "send_messages",
    "embed_links",
    "attach_files",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
    "send_messages_in_threads",
)


def ticket_overwrites(guild, owner, support, *, closed=False):
    member = discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=not closed,
        embed_links=not closed,
        attach_files=not closed,
        add_reactions=not closed,
        create_public_threads=False,
        create_private_threads=False,
        send_messages_in_threads=False,
    )
    bot = discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=True,
        embed_links=True,
        attach_files=True,
    )
    result = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: bot,
        support: member,
    }
    if owner:
        result[owner] = member
    return result


def staff(member, support_id):
    return bool(
        member
        and (
            getattr(getattr(member, "guild_permissions", None), "administrator", False)
            or any(role.id == support_id for role in getattr(member, "roles", []))
        )
    )


def control_embed(row):
    embed = discord.Embed(
        title=f"🎫 Tiket #{row['id']:05d} • {row['state']}",
        description=discord.utils.escape_mentions(row["summary"])[:1200],
        color=0xEF4444,
    )
    embed.add_field(name="Jenis", value=KINDS[row["kind"]])
    embed.add_field(name="Pembuka", value=f"<@{row['owner']}>")
    embed.add_field(
        name="Petugas",
        value=f"<@{row['claimant']}>" if row["claimant"] else "Belum diklaim",
    )
    if row["reason"]:
        embed.add_field(
            name="Alasan penutupan terakhir",
            value=discord.utils.escape_mentions(row["reason"])[:500],
            inline=False,
        )
    embed.set_footer(
        text="Privat untuk pembuka, tim support, dan bot. Administrator mengikuti izin Discord."
    )
    return embed


class Tickets:
    def __init__(self, client):
        self.client = client
        self.enabled = os.getenv("ABUD_TICKETS_ENABLED", "false").lower() == "true"
        self.path = os.getenv("ABUD_TICKETS_DB", "/app/tickets/tickets.db")
        self.store = None
        self.lock = asyncio.Lock()
        self.views = []
        self.recovery = None
        self.channels = frozenset()
        self.support_roles = frozenset()
        self.last_error = None
        self.reaction_role_bound = lambda guild, role: False

    def require(self, guild):
        if not self.enabled or self.store is None:
            raise TicketError("Ticket Support belum diaktifkan oleh pengelola bot.")
        if guild is None:
            raise TicketError("Ticket Support tersedia di server Discord.")

    def snapshots(self):
        self.channels = self.store.protected()
        self.support_roles = self.store.reserved()

    def protected(self, channel):
        if channel is None:
            return False
        parent = getattr(channel, "parent", None)
        return (
            channel.id in self.channels
            or getattr(channel, "parent_id", None) in self.channels
            or str(getattr(channel, "topic", "") or "").startswith("abud-ticket:")
            or str(getattr(parent, "topic", "") or "").startswith("abud-ticket:")
        )

    def reserved_role(self, guild, role):
        return (guild, role) in self.support_roles

    def failure(self, error):
        self.last_error = (
            str(error) if isinstance(error, TicketError) else type(error).__name__
        )
        log.warning("Ticket operation failed (%s)", type(error).__name__)

    async def start(self):
        # Even a paused module loads existing protected channel IDs for AI isolation.
        if self.store is None and (self.enabled or Path(self.path).is_file()):
            try:
                self.store = TicketStore(self.path)
                self.snapshots()
            except Exception as error:  # noqa: BLE001 - optional module startup must not stop other features
                self.failure(error)
                return
        if self.enabled and self.store and not self.views:
            from app.ticket_ui import TicketControls, TicketPanel

            self.views = [TicketPanel(self), TicketControls(self)]
            for view in self.views:
                self.client.add_view(view)
            self.recovery = asyncio.create_task(
                self.recover_pending(), name="ticket-recovery"
            )

    async def close(self):
        if self.recovery:
            self.recovery.cancel()
            await asyncio.gather(self.recovery, return_exceptions=True)
            self.recovery = None
        for view in self.views:
            view.stop()
        self.views = []
        async with self.lock:
            if self.store:
                self.store.close()
                self.store = None

    def validate_resources(self, guild, category_id, support_id, log_id):
        category = guild.get_channel(category_id)
        support = guild.get_role(support_id)
        if (
            not isinstance(category, discord.CategoryChannel)
            or not support
            or support.is_default()
            or support.managed
        ):
            raise TicketError(
                "Pilih kategori tiket dan role support biasa dari server ini."
            )
        if self.reaction_role_bound(guild.id, support.id):
            raise TicketError(
                "Role support sedang dipakai pada reaction role. Pilih role staff khusus yang tidak bisa diambil sendiri."
            )
        if not guild.me or not all(
            getattr(guild.me.guild_permissions, name)
            for name in (*PARTICIPANT_PERMS, "manage_channels", "manage_roles")
        ):
            raise TicketError(
                "Izin bot belum lengkap: Manage Channels, Manage Roles dan izin chat/media/thread untuk membuat serta mengunci channel tiket."
            )
        if guild.default_role.permissions.administrator:
            raise TicketError(
                "@everyone memiliki Administrator; tiket privat tidak dapat dijamin pada konfigurasi server ini."
            )
        self.validate_log(guild, log_id, support_id)
        return category, support

    def validate_log(self, guild, ident, support_id):
        channel = guild.get_channel(ident)
        if not isinstance(channel, discord.TextChannel):
            raise TicketError("Pilih text channel log privat di server ini.")
        if channel.permissions_for(guild.default_role).view_channel:
            raise TicketError("Channel log tidak boleh terlihat oleh @everyone.")
        permissions = channel.permissions_for(guild.me)
        if not (
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        ):
            raise TicketError(
                "Bot perlu View Channel, Send Messages, dan Embed Links di channel log."
            )
        for role in guild.roles:
            bot_role = (
                role.managed
                and role.is_bot_managed()
                and getattr(role.tags, "bot_id", None) == self.client.user.id
            )
            if (
                role.id != support_id
                and not bot_role
                and not role.permissions.administrator
                and channel.permissions_for(role).view_channel
            ):
                raise TicketError(
                    "Channel log harus privat untuk support/admin dan Abud, bukan role/member umum."
                )
        for target, overwrite in channel.overwrites.items():
            if (
                overwrite.view_channel is True
                and not isinstance(target, discord.Role)
                and target.id not in (guild.me.id, guild.owner_id)
                and not staff(target, support_id)
            ):
                raise TicketError(
                    "Channel log memiliki akses member di luar tim support."
                )
        return channel

    async def configure(
        self, guild, enabled, category, support, log_channel, title, description
    ):
        self.require(guild)
        async with self.lock:
            if enabled:
                self.validate_resources(guild, category.id, support.id, log_channel.id)
            self.store.configure(
                guild.id,
                enabled,
                category.id,
                support.id,
                log_channel.id,
                title,
                description,
            )
            self.snapshots()

    def panel_check(self, interaction, expected_message=None):
        self.require(interaction.guild)
        settings = self.store.settings(interaction.guild_id)
        message_id = (
            expected_message
            if expected_message is not None
            else getattr(interaction.message, "id", None)
        )
        if (
            not settings["enabled"]
            or settings["panel_message"] != message_id
            or settings["panel_channel"] != interaction.channel_id
        ):
            raise TicketError(
                "Panel ini tidak aktif. Gunakan panel Ticket Support terbaru."
            )
        if interaction.user.bot or interaction.user.pending:
            raise TicketError("Selesaikan screening server sebelum membuka tiket.")
        return settings

    async def publish(self, guild, channel):
        self.require(guild)
        async with self.lock:
            settings = self.store.settings(guild.id)
            if not settings["enabled"] or channel.guild.id != guild.id:
                raise TicketError(
                    "Aktifkan konfigurasi tiket dan pilih channel panel di server ini."
                )
            self.validate_resources(
                guild, settings["category"], settings["support"], settings["log"]
            )
            permissions = channel.permissions_for(guild.me)
            if not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
            ):
                raise TicketError(
                    "Abud perlu View Channel, Send Messages, dan Embed Links di channel panel."
                )
            from app.ticket_ui import TicketPanel, panel_embed

            message = None
            if settings["panel_channel"] == channel.id and settings["panel_message"]:
                try:
                    message = await channel.fetch_message(settings["panel_message"])
                except discord.NotFound:
                    pass
            if message:
                if message.author.id != self.client.user.id:
                    raise TicketError("Pesan panel bukan milik Abud.")
                await message.edit(embed=panel_embed(settings), view=TicketPanel(self))
            else:
                message = await channel.send(
                    embed=panel_embed(settings),
                    view=TicketPanel(self),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            self.store.panel(guild.id, channel.id, message.id)
            return message

    async def open(self, interaction, kind, summary, panel_message):
        self.panel_check(interaction, panel_message)
        async with self.lock:
            settings = self.panel_check(interaction, panel_message)
            category, support = self.validate_resources(
                interaction.guild,
                settings["category"],
                settings["support"],
                settings["log"],
            )
            previous = self.store.active(interaction.guild_id, interaction.user.id)
            if previous:
                location = (
                    f" <#{previous['channel']}>"
                    if previous["channel"]
                    else " Menunggu pemeriksaan admin."
                )
                raise TicketError("Kamu sudah memiliki satu tiket aktif." + location)
            row = self.store.reserve(
                interaction.guild_id, interaction.user.id, kind, summary
            )
            try:
                channel = await interaction.guild.create_text_channel(
                    f"ticket-{row['id']:05d}",
                    category=category,
                    topic=self.topic(row),
                    overwrites=ticket_overwrites(
                        interaction.guild, interaction.user, support
                    ),
                    reason=f"Abud ticket #{row['id']}",
                )
                self.channels = self.channels | {channel.id}
                self.store.attach(row["guild"], row["id"], channel.id)
                self.snapshots()
                row = self.store.get(row["guild"], row["id"])
                await self.refresh(interaction.guild, row, channel)
                row = self.store.state(row["guild"], row["id"], "open", row["owner"])
                await self.refresh(interaction.guild, row, channel)
                await self.audit(interaction.guild, row, "Dibuka", row["owner"])
                return row
            except (discord.Forbidden, discord.NotFound) as error:
                if not self.store.get(row["guild"], row["id"])["channel"]:
                    self.store.state(row["guild"], row["id"], "failed", row["owner"])
                self.failure(error)
                raise TicketError(
                    "Pembuatan tiket belum selesai. Admin perlu memeriksa izin/status tiket sebelum mencoba lagi."
                ) from None
            except Exception as error:  # noqa: BLE001 - preserve reservations on ambiguous external failures
                self.failure(error)
                raise TicketError(
                    "Pembuatan tiket perlu dipulihkan admin dengan /ticket repair. Permintaan disimpan agar tidak membuat channel ganda."
                ) from None

    @staticmethod
    def topic(row):
        return f"abud-ticket:{row['id']}:{row['nonce']}"

    def context(self, interaction, *, action=None, control_message=False):
        self.require(interaction.guild)
        row = self.store.by_channel(interaction.guild_id, interaction.channel_id)
        if not row:
            raise TicketError(
                "Gunakan perintah ini di channel tiket yang dikelola Abud."
            )
        if (
            control_message
            and getattr(interaction.message, "id", None) != row["control"]
        ):
            raise TicketError(
                "Panel kontrol lama tidak berlaku. Gunakan /ticket status."
            )
        is_staff = staff(interaction.user, row["support"])
        if action in ("claim", "unclaim", "reopen") and not is_staff:
            raise TicketError("Kontrol ini hanya untuk tim support atau Administrator.")
        if (
            action not in ("claim", "unclaim", "reopen")
            and interaction.user.id != row["owner"]
            and not is_staff
        ):
            raise TicketError("Tiket ini hanya untuk pembuka dan tim support.")
        return row

    async def channel_for(self, guild, row):
        if not row["channel"]:
            raise TicketError(
                "Channel tiket belum tercatat. Admin gunakan /ticket repair."
            )
        channel = await guild.fetch_channel(row["channel"])
        if (
            not isinstance(channel, discord.TextChannel)
            or channel.guild.id != guild.id
            or channel.topic != self.topic(row)
        ):
            raise TicketError(
                "Identitas channel tiket berubah. Tidak ada channel yang dimodifikasi."
            )
        return channel

    async def acl(self, guild, row, channel, *, closed):
        support = guild.get_role(row["support"])
        if not support:
            raise TicketError(
                "Role support tiket ini sudah tidak tersedia. Admin perlu memeriksanya."
            )
        try:
            owner = await guild.fetch_member(row["owner"])
        except discord.NotFound:
            if not closed:
                raise TicketError(
                    "Pembuka sudah keluar server; tiket belum bisa dibuka kembali."
                ) from None
            owner = None
        if owner and owner.pending and not closed:
            raise TicketError(
                "Pembuka perlu menyelesaikan screening server sebelum tiket dapat dibuka kembali."
            )
        return await channel.edit(
            overwrites=ticket_overwrites(guild, owner, support, closed=closed),
            reason=f"Abud ticket #{row['id']} {'close' if closed else 'open'}",
        )

    async def apply(self, interaction, action, reason="", *, control_message=False):
        async with self.lock:
            row = self.context(
                interaction, action=action, control_message=control_message
            )
            if action in ("claim", "unclaim"):
                if row["state"] not in ("open", "claimed"):
                    raise TicketError("Tiket tidak dalam keadaan terbuka.")
                if action == "claim":
                    if row["claimant"] and row["claimant"] != interaction.user.id:
                        raise TicketError(
                            "Tiket sudah diklaim staf lain. Minta petugas/admin melakukan unclaim dulu."
                        )
                    if row["claimant"] == interaction.user.id:
                        return row
                elif not row["claimant"]:
                    return row
                elif (
                    row["claimant"] != interaction.user.id
                    and not interaction.user.guild_permissions.administrator
                ):
                    raise TicketError(
                        "Unclaim hanya untuk petugas yang mengklaim atau Administrator."
                    )
            elif action == "close":
                if (
                    row["state"] not in ("open", "claimed")
                    or not 3 <= len(reason.strip()) <= 500
                ):
                    raise TicketError(
                        "Tiket harus terbuka dan alasan penutupan 3–500 karakter."
                    )
            elif action == "reopen":
                if row["state"] != "closed":
                    raise TicketError("Hanya tiket tertutup yang dapat dibuka kembali.")
                active = self.store.active(row["guild"], row["owner"])
                if active:
                    raise TicketError("Pembuka sudah memiliki tiket aktif lain.")
            else:
                raise TicketError("Kontrol tiket tidak dikenal.")
            channel = await self.channel_for(interaction.guild, row)
            if action in ("close", "reopen"):
                row = self.store.state(
                    row["guild"],
                    row["id"],
                    "closing" if action == "close" else "reopening",
                    interaction.user.id,
                    reason,
                )
            channel = await self.acl(
                interaction.guild, row, channel, closed=action == "close"
            )
            next_state = {
                "claim": "claimed",
                "unclaim": "open",
                "close": "closed",
                "reopen": "open",
            }[action]
            row = self.store.state(
                row["guild"],
                row["id"],
                next_state,
                interaction.user.id,
                reason,
                claimant=interaction.user.id if action == "claim" else None,
            )
            await self.refresh(interaction.guild, row, channel)
            await self.audit(interaction.guild, row, action, interaction.user.id)
            return row

    async def refresh(self, guild, row, channel=None):
        channel = channel or await self.channel_for(guild, row)
        from app.ticket_ui import TicketControls

        view = TicketControls(self, closed=row["state"] == "closed")
        if row["control"]:
            try:
                message = await channel.fetch_message(row["control"])
                if message.author.id != self.client.user.id:
                    raise TicketError("Pesan kontrol bukan milik Abud.")
                await message.edit(embed=control_embed(row), view=view)
                return
            except discord.NotFound:
                pass
        message = await channel.send(
            embed=control_embed(row),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.store.attach(row["guild"], row["id"], channel.id, message.id)

    async def audit(self, guild, row, action, actor):
        try:
            channel = self.validate_log(guild, row["log"], row["support"])
            # Deliberately omit the private summary and closure reason from Discord logs.
            embed = discord.Embed(
                title=f"Ticket #{row['id']:05d} • {action}",
                description=f"Pembuka <@{row['owner']}> · pelaku <@{actor}>\nStatus: **{row['state']}** · channel <#{row['channel']}>",
                color=0xEF4444,
            )
            await channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except Exception as error:  # noqa: BLE001 - audit delivery cannot undo the ticket transaction
            self.failure(error)

    async def repair(self, guild, ident, actor):
        async with self.lock:
            row = self.store.get(guild.id, ident)
            if row["state"] not in ("creating", "error", "closing", "reopening"):
                raise TicketError(
                    "Tiket ini tidak memiliki operasi yang perlu dipulihkan."
                )
            if not row["channel"]:
                matches = [
                    c
                    for c in await guild.fetch_channels()
                    if isinstance(c, discord.TextChannel) and c.topic == self.topic(row)
                ]
                if len(matches) > 1:
                    raise TicketError(
                        "Ditemukan lebih dari satu channel dengan marker tiket; admin perlu meninjau manual."
                    )
                if not matches:
                    if time.time() - row["created"] < 300:
                        raise TicketError(
                            "Tunggu lima menit dari permintaan awal sebelum melepas reservasi tanpa channel."
                        )
                    self.store.state(guild.id, ident, "failed", actor)
                    return self.store.get(guild.id, ident)
                self.store.attach(guild.id, ident, matches[0].id)
                self.snapshots()
                row = self.store.get(guild.id, ident)
            channel = await self.channel_for(guild, row)
            closing = row["state"] == "closing"
            channel = await self.acl(guild, row, channel, closed=closing)
            row = self.store.state(
                guild.id,
                ident,
                "closed" if closing else "open",
                row["closer"] if closing and row["closer"] else actor,
                row["reason"],
            )
            await self.refresh(guild, row, channel)
            await self.audit(guild, row, "Dipulihkan", actor)
            return row

    async def recover_pending(self):
        # Reconcile channel deletions missed while the bot was offline, without deleting
        # any Discord resource. Hold the lock so a fresh create cannot race this snapshot.
        async with self.lock:
            rows = self.store.tracked()
            for guild_id in {row["guild"] for row in rows}:
                guild = self.client.get_guild(guild_id)
                if not guild or getattr(guild, "unavailable", False):
                    continue
                try:
                    channels = {channel.id for channel in await guild.fetch_channels()}
                    for row in rows:
                        if row["guild"] == guild_id and row["channel"] not in channels:
                            self.store.state(
                                guild_id, row["id"], "deleted", self.client.user.id
                            )
                except Exception as error:  # noqa: BLE001 - API failure is not evidence of deletion
                    self.failure(error)
        for row in self.store.pending():
            if not row["channel"]:
                continue  # Ambiguous creates require explicit admin /ticket repair.
            guild = self.client.get_guild(row["guild"])
            if guild:
                try:
                    await self.repair(guild, row["id"], self.client.user.id)
                except Exception as error:  # noqa: BLE001 - one interrupted operation must not block others
                    self.failure(error)

    async def channel_deleted(self, channel):
        if self.store:
            async with self.lock:
                if self.store:
                    row = self.store.by_channel(channel.guild.id, channel.id)
                    if row:
                        self.store.state(
                            row["guild"], row["id"], "deleted", self.client.user.id
                        )
