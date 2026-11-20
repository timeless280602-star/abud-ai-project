"""Community leveling integration. Never assigns, edits or removes roles."""

import asyncio
import logging
import os
import random
import sqlite3
import time

import discord
from discord import app_commands

from app.level_card import rank_card
from app.leveling import CHAT_CAP, LevelingError, LevelStore, level

log = logging.getLogger(__name__)


class Leveling:
    def __init__(self, client):
        self.client = client
        self.enabled = os.getenv("ABUD_LEVELING_ENABLED", "false").lower() == "true"
        self.path = os.getenv("ABUD_LEVELING_DB", "/app/leveling/levels.db")
        self.store = None
        self.last_error = None

    def require(self, guild=None):
        if not self.enabled or self.store is None:
            raise LevelingError("Leveling belum diaktifkan oleh pengelola bot.")
        if guild is None:
            raise LevelingError("Leveling tersedia di server Discord.")

    async def start(self):
        if not self.enabled:
            return
        if self.store is None:
            try:
                self.store = LevelStore(self.path)
            except (OSError, sqlite3.Error) as error:
                self.last_error = type(error).__name__
                log.warning("Leveling startup failed (%s)", type(error).__name__)
                return
    async def close(self):
        if self.store:
            self.store.close()
            self.store = None

    async def message(self, message):
        if (
            not self.enabled
            or self.store is None
            or not message.guild
            or message.author.bot
            or message.webhook_id
            or message.type
            not in (discord.MessageType.default, discord.MessageType.reply)
        ):
            return
        try:
            excluded = self.store.excludes(message.guild.id)
            if (
                message.channel.id in excluded
                or getattr(message.channel, "parent_id", None) in excluded
            ):
                return
            award = self.store.award(
                message.guild.id,
                message.author.id,
                message.author.display_name,
                "chat",
                time.time(),
                content=message.content,
                amount=random.randint(15, 25),
            )
            if award and award.leveled:
                await self.announce(message.guild, message.author, award)
        except Exception as error:  # noqa: BLE001 - leveling must not interrupt chat/AI
            self.last_error = type(error).__name__
            log.warning("Chat XP failed (%s)", type(error).__name__)

    async def announce(self, guild, member, award):
        channel_id = self.store.config(guild.id)["announcement"]
        channel = guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return
        embed = discord.Embed(
            title="🎉 Naik level!",
            description=f"**{discord.utils.escape_markdown(discord.utils.escape_mentions(member.display_name))[:120]}** sekarang **Level {level(award.after)}**!",
            color=0xEF4444,
        )
        embed.set_footer(text=f"Abud • {award.after:,} XP • /rank untuk lihat progres")
        try:
            await channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            # XP is already committed; notification failure cannot duplicate the award.
            self.last_error = "AnnouncementPermissionOrDelivery"
            log.warning("Level-up announcement failed")


def install_leveling_commands(tree, manager):
    async def guard(interaction, *, admin=False):
        manager.require(interaction.guild)
        if admin and not interaction.permissions.administrator:
            raise LevelingError("Pengaturan leveling hanya untuk Administrator server.")
        await interaction.response.defer(ephemeral=admin)

    async def failure(interaction, error):
        cause = getattr(error, "original", error)
        text = (
            str(cause)
            if isinstance(cause, LevelingError)
            else "Leveling belum bisa diproses. Coba lagi sebentar."
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )

    @tree.command(
        name="rank", description="Lihat kartu XP, level, dan peringkat komunitas"
    )
    @app_commands.guild_only()
    async def rank(
        interaction: discord.Interaction, member: discord.Member | None = None
    ):
        await guard(interaction)
        target = member or interaction.user
        if target.bot:
            raise LevelingError("Bot tidak ikut leveling.")
        row = manager.store.member(interaction.guild_id, target.id, target.display_name)
        position = manager.store.rank(interaction.guild_id, target.id)
        image = await asyncio.to_thread(
            rank_card,
            target.display_name,
            row["xp"],
            row["chat_xp"],
            position,
        )
        await interaction.followup.send(
            file=discord.File(image, filename="abud-rank.png"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    rank.error(failure)

    @tree.command(
        name="leaderboard",
        description="Lihat sepuluh member dengan XP tertinggi per halaman",
    )
    @app_commands.guild_only()
    async def leaderboard(
        interaction: discord.Interaction, page: app_commands.Range[int, 1, 1000] = 1
    ):
        await guard(interaction)
        pages = max(1, (manager.store.count(interaction.guild_id) + 9) // 10)
        if page > pages:
            raise LevelingError(f"Pilih halaman 1–{pages}.")
        rows = manager.store.leaderboard(interaction.guild_id, page)
        lines = [
            f"**{(page - 1) * 10 + i}.** {discord.utils.escape_markdown(discord.utils.escape_mentions(row['name']))[:60]} · Level {level(row['xp'])} · **{row['xp']:,} XP**"
            for i, row in enumerate(rows, 1)
        ]
        embed = discord.Embed(
            title="🏆 Leaderboard Abud",
            description="\n".join(lines)
            or "Belum ada XP. Mulai ngobrol bersama komunitas!",
            color=0xEF4444,
        )
        embed.set_footer(text=f"Halaman {page}/{pages} • XP khusus server ini")
        await interaction.followup.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

    leaderboard.error(failure)

    group = app_commands.Group(
        name="leveling",
        description="Atur XP komunitas tanpa role hadiah",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @group.command(
        name="setup",
        description="Aktifkan/jeda leveling dan atur sumber XP serta notifikasinya",
    )
    async def setup(
        interaction: discord.Interaction,
        enabled: bool,
        chat: bool | None = None,
        announcement: discord.TextChannel | None = None,
        notify: bool | None = None,
    ):
        await guard(interaction, admin=True)
        config = manager.store.config(interaction.guild_id)
        channel_id = announcement.id if announcement else config["announcement"]
        if notify is False:
            channel_id = None
        if notify is True and not channel_id:
            raise LevelingError(
                "Pilih channel announcement untuk mengaktifkan notifikasi level-up."
            )
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise LevelingError(
                    "Channel notifikasi harus text channel di server ini."
                )
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise LevelingError(
                    "Abud perlu View Channel, Send Messages, dan Embed Links di channel notifikasi."
                )
        manager.store.configure(
            interaction.guild_id,
            enabled,
            chat if chat is not None else config["chat"],
            False,
            channel_id,
        )
        await interaction.followup.send(
            "Pengaturan leveling tersimpan. Level dan XP tidak memberikan role apa pun.",
            ephemeral=True,
        )

    @group.command(
        name="exclude",
        description="Kecualikan satu text channel dari perolehan XP",
    )
    async def exclude(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await guard(interaction, admin=True)
        if channel.guild.id != interaction.guild_id:
            raise LevelingError("Pilih channel dari server ini.")
        manager.store.exclude(interaction.guild_id, channel.id, True)
        await interaction.followup.send("Channel dikecualikan dari XP.", ephemeral=True)

    @group.command(
        name="include",
        description="Izinkan kembali channel yang sebelumnya dikecualikan",
    )
    async def include(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await guard(interaction, admin=True)
        if channel.guild.id != interaction.guild_id:
            raise LevelingError("Pilih channel dari server ini.")
        manager.store.exclude(interaction.guild_id, channel.id, False)
        await interaction.followup.send(
            "Channel diizinkan kembali mendapat XP.", ephemeral=True
        )

    @group.command(
        name="config",
        description="Lihat status, batas XP, dan channel yang dikecualikan",
    )
    async def config(interaction: discord.Interaction):
        await guard(interaction, admin=True)
        settings = manager.store.config(interaction.guild_id)
        description = (
            f"Leveling: {'aktif' if settings['enabled'] else 'jeda'}\nChat XP: {bool(settings['chat'])}\n"
            f"Chat: 15–25 XP/menit, maks {CHAT_CAP}/hari\n"
            f"Notifikasi: {'<#' + str(settings['announcement']) + '>' if settings['announcement'] else 'mati'}\nBatas harian mengikuti WIB. Tidak ada role hadiah."
        )
        excluded = manager.store.excludes(interaction.guild_id)
        if excluded:
            description += "\nDikecualikan: " + ", ".join(
                f"<#{ident}>" for ident in excluded[:30]
            )
            if len(excluded) > 30:
                description += f" dan {len(excluded) - 30} channel lainnya."
        if manager.last_error:
            description += "\nGangguan terakhir: " + manager.last_error
        await interaction.followup.send(
            embed=discord.Embed(
                title="Pengaturan Leveling Abud",
                description=description,
                color=0xEF4444,
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    group.error(failure)
    tree.add_command(group)
