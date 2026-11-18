"""Ticket administration, lifecycle commands and restricted status history."""

import discord
from discord import app_commands

from app.discord_tickets import control_embed, staff
from app.ticket_store import TicketError
from app.ticket_ui import panel_embed, request_close, ui_error


def install_ticket_commands(tree, manager):
    group = app_commands.Group(
        name="ticket",
        description="Ticket Support privat dan pengaturan admin",
        guild_only=True,
    )

    async def guard(interaction, *, admin=False):
        manager.require(interaction.guild)
        if admin and not interaction.user.guild_permissions.administrator:
            raise TicketError("Pengaturan tiket hanya untuk Administrator.")
        await interaction.response.defer(ephemeral=True, thinking=True)

    async def reply(interaction, text="", **kwargs):
        await interaction.followup.send(
            text,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
            **kwargs,
        )

    @group.command(
        name="setup",
        description="Admin: atur kategori privat, role support, log, dan isi panel",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(
        interaction: discord.Interaction,
        enabled: bool,
        category: discord.CategoryChannel | None = None,
        support: discord.Role | None = None,
        log_channel: discord.TextChannel | None = None,
        title: str | None = None,
        description: str | None = None,
    ):
        await guard(interaction, admin=True)
        try:
            old = manager.store.settings(interaction.guild_id)
        except TicketError:
            old = None
        category = category or (
            interaction.guild.get_channel(old["category"]) if old else None
        )
        support = support or (
            interaction.guild.get_role(old["support"]) if old else None
        )
        log_channel = log_channel or (
            interaction.guild.get_channel(old["log"]) if old else None
        )
        if (
            not category
            or not support
            or not log_channel
            or any(
                item.guild.id != interaction.guild_id
                for item in (category, support, log_channel)
            )
        ):
            raise TicketError(
                "Pilih category, support dan log_channel dari server ini saat pengaturan pertama."
            )
        await manager.configure(
            interaction.guild,
            enabled,
            category,
            support,
            log_channel,
            title
            if title is not None
            else (old["title"] if old else "🎫 Pusat Bantuan Abud"),
            description
            if description is not None
            else (
                old["description"]
                if old
                else "Butuh bantuan? Buka tiket privat bersama tim support."
            ),
        )
        await reply(
            interaction,
            "Pengaturan tiket tersimpan. Preview lalu publish panel melalui /ticket panel.",
        )

    @group.command(
        name="preview",
        description="Admin: tinjau panel secara privat tanpa membuat channel",
    )
    @app_commands.default_permissions(administrator=True)
    async def preview(interaction: discord.Interaction):
        await guard(interaction, admin=True)
        await reply(
            interaction, embed=panel_embed(manager.store.settings(interaction.guild_id))
        )

    @group.command(
        name="panel", description="Admin: terbitkan tombol Buka Tiket di channel tujuan"
    )
    @app_commands.default_permissions(administrator=True)
    async def panel(interaction: discord.Interaction, channel: discord.TextChannel):
        await guard(interaction, admin=True)
        message = await manager.publish(interaction.guild, channel)
        await reply(interaction, "Panel tiket siap: " + message.jump_url)

    @group.command(
        name="config", description="Admin: lihat konfigurasi dan kondisi modul tiket"
    )
    @app_commands.default_permissions(administrator=True)
    async def config(interaction: discord.Interaction):
        await guard(interaction, admin=True)
        row = manager.store.settings(interaction.guild_id)
        await reply(
            interaction,
            f"Tiket: {'aktif' if row['enabled'] else 'jeda'}\nKategori <#{row['category']}> · support <@&{row['support']}> · log <#{row['log']}>\nBatas: 1 tiket aktif/member, cooldown 60 detik, 50 channel tiket tersimpan/server.\nGangguan terakhir: {manager.last_error or 'tidak tercatat'}",
        )

    @group.command(
        name="status",
        description="Lihat status tiket ini dan segarkan panel kontrolnya",
    )
    async def status(interaction: discord.Interaction):
        await guard(interaction)
        async with manager.lock:
            row = manager.context(interaction)
            if row["state"] in ("open", "claimed", "closed"):
                channel = await manager.channel_for(interaction.guild, row)
                channel = await manager.acl(
                    interaction.guild, row, channel, closed=row["state"] == "closed"
                )
                await manager.refresh(interaction.guild, row, channel)
        await reply(interaction, embed=control_embed(row))

    async def action(interaction, operation):
        await guard(interaction)
        await manager.apply(interaction, operation)
        await reply(interaction, "Status tiket diperbarui.")

    @group.command(name="claim", description="Support: ambil penanganan tiket ini")
    async def claim(interaction: discord.Interaction):
        await action(interaction, "claim")

    @group.command(
        name="unclaim",
        description="Support: lepas klaim sendiri; admin dapat melepas klaim staf lain",
    )
    async def unclaim(interaction: discord.Interaction):
        await action(interaction, "unclaim")

    @group.command(
        name="close",
        description="Minta konfirmasi penutupan dengan alasan; tidak menghapus channel",
    )
    async def close(interaction: discord.Interaction, reason: str):
        await request_close(interaction, manager, reason)

    @group.command(name="reopen", description="Support: buka kembali tiket tertutup")
    async def reopen(interaction: discord.Interaction):
        await action(interaction, "reopen")

    @group.command(
        name="history",
        description="Support: lihat metadata/riwayat tiket server ini secara privat",
    )
    async def history(
        interaction: discord.Interaction,
        ident: int | None = None,
        page: app_commands.Range[int, 1, 10000] = 1,
    ):
        await guard(interaction)
        if ident is not None:
            row = manager.store.get(interaction.guild_id, ident)
            if not staff(interaction.user, row["support"]):
                raise TicketError(
                    "Riwayat lengkap hanya untuk support tiket atau Administrator."
                )
            lines = [
                f"<t:{int(event['happened'])}:f> · {event['action']} · <@{event['actor']}>"
                + (
                    ": " + discord.utils.escape_mentions(event["reason"])[:200]
                    if event["reason"]
                    else ""
                )
                for event in manager.store.events(ident)
            ]
            # Paginate to stay below Discord's message limit even with long reasons.
            pages = [""]
            for line in lines:
                if len(pages[-1]) + len(line) > 1800:
                    pages.append("")
                pages[-1] += line + "\n"
            for text in pages:
                await reply(interaction, text or "Belum ada riwayat.")
            return
        config = manager.store.settings(interaction.guild_id)
        if not staff(interaction.user, config["support"]):
            raise TicketError("Daftar tiket hanya untuk support atau Administrator.")
        rows = manager.store.history(interaction.guild_id, page)
        # Old tickets may use a different support role: do not expose them to new staff.
        rows = [row for row in rows if staff(interaction.user, row["support"])]
        lines = [
            f"#{r['id']:05d} · {r['state']} · pembuka <@{r['owner']}> · <t:{int(r['created'])}:f>"
            for r in rows
        ]
        await reply(
            interaction,
            "\n".join(lines)
            or "Tidak ada tiket yang dapat ditampilkan pada halaman ini.",
        )

    @group.command(
        name="repair",
        description="Admin: pulihkan operasi tiket yang terputus tanpa menghapus channel",
    )
    @app_commands.default_permissions(administrator=True)
    async def repair(interaction: discord.Interaction, ident: int):
        await guard(interaction, admin=True)
        row = await manager.repair(interaction.guild, ident, interaction.user.id)
        await reply(interaction, f"Tiket #{row['id']:05d}: {row['state']}.")

    @group.error
    async def error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        await ui_error(interaction, manager, getattr(error, "original", error))

    tree.add_command(group)
