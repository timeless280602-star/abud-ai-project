"""Administrator-only configuration; previews precede reaction-panel publication."""

import discord
from discord import app_commands

from app.discord_onboarding import panel_embed, welcome_embed
from app.onboarding import OnboardingError, parse_emoji


def install_onboarding_commands(tree, manager):
    async def guard(interaction):
        manager.require(interaction.guild)
        if not interaction.permissions.administrator:
            raise OnboardingError("Pengaturan ini hanya untuk Administrator server.")
        await interaction.response.defer(ephemeral=True)

    async def confirm(interaction, text, **kwargs):
        await interaction.followup.send(
            text,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
            **kwargs,
        )

    async def error(interaction, error):
        cause = getattr(error, "original", error)
        manager.failure(cause)
        text = (
            str(cause)
            if isinstance(cause, OnboardingError)
            else "Operasi belum berhasil. Periksa izin Abud, emoji, role, dan channel."
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )

    welcome = app_commands.Group(
        name="welcome",
        description="Atur sambutan otomatis member baru",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @welcome.command(
        name="setup", description="Atur welcome, channel, pesan dan ping member baru"
    )
    @app_commands.describe(template="Placeholder: {member}, {name}, {server}, {count}")
    async def setup(
        interaction: discord.Interaction,
        enabled: bool,
        channel: discord.TextChannel | None = None,
        template: str | None = None,
        ping: bool | None = None,
    ):
        await guard(interaction)
        old = manager.store.welcome(interaction.guild_id)
        destination = channel.id if channel else old["channel"]
        if enabled:
            manager.channel(interaction.guild, destination)
        manager.store.set_welcome(
            interaction.guild_id,
            enabled,
            destination,
            template if template is not None else old["template"],
            ping if ping is not None else old["ping"],
        )
        await confirm(
            interaction,
            "Pengaturan welcome tersimpan. Gunakan /welcome preview atau /welcome test.",
        )

    @welcome.command(
        name="preview", description="Lihat contoh welcome secara privat tanpa ping"
    )
    async def preview(interaction: discord.Interaction):
        await guard(interaction)
        config = manager.store.welcome(interaction.guild_id)
        await confirm(
            interaction,
            "Preview untuk akunmu:",
            embed=welcome_embed(interaction.user, config["template"], test=True),
        )

    @welcome.command(
        name="test",
        description="Kirim contoh welcome akunmu ke channel tujuan tanpa ping",
    )
    async def test(interaction: discord.Interaction):
        await guard(interaction)
        if not await manager.welcome(interaction.user, test=True):
            raise OnboardingError(
                "Welcome belum aktif atau pengiriman gagal. Periksa /welcome config dan izin channel."
            )
        await confirm(interaction, "Contoh welcome terkirim tanpa ping.")

    @welcome.command(
        name="config", description="Lihat status welcome dan kebutuhan intent member"
    )
    async def config(interaction: discord.Interaction):
        await guard(interaction)
        settings = manager.store.welcome(interaction.guild_id)
        channel = (
            f"<#{settings['channel']}>" if settings["channel"] else "belum dipilih"
        )
        await confirm(
            interaction,
            f"Welcome: {'aktif' if settings['enabled'] else 'mati'} · channel {channel} · ping member {bool(settings['ping'])}\nServer Members Intent harus aktif di Developer Portal.\nGangguan terakhir: {manager.last_error or 'tidak tercatat'}",
        )

    welcome.error(error)
    tree.add_command(welcome)

    reaction = app_commands.Group(
        name="reactionrole",
        description="Kelola panel pilihan role melalui emoji",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @reaction.command(
        name="create", description="Buat draft panel; belum memposting pesan publik"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Boleh beberapa role", value="multiple"),
            app_commands.Choice(name="Satu pilihan", value="single"),
        ]
    )
    async def create(
        interaction: discord.Interaction,
        title: str,
        description: str = "Pilih emoji untuk mendapatkan role:",
        mode: str = "multiple",
    ):
        await guard(interaction)
        ident = manager.store.create(interaction.guild_id, title, description, mode)
        await confirm(
            interaction,
            f"Draft panel #{ident} dibuat. Tambahkan pilihan dengan /reactionrole bind, lalu preview dan publish.",
        )

    @reaction.command(
        name="bind", description="Tentukan emoji dan role pada panel yang belum aktif"
    )
    async def bind(
        interaction: discord.Interaction, panel: int, emoji: str, role: discord.Role
    ):
        await guard(interaction)
        async with manager.lock:
            manager.check_role(interaction.guild, role, interaction.user)
            key, display = parse_emoji(emoji, interaction.guild)
            manager.store.bind(interaction.guild_id, panel, key, display, role.id)
        await confirm(
            interaction, "Pasangan emoji–role tersimpan. Preview panel sebelum publish."
        )

    @reaction.command(
        name="unbind", description="Hapus pasangan emoji dari panel yang belum aktif"
    )
    async def unbind(interaction: discord.Interaction, panel: int, emoji: str):
        await guard(interaction)
        key, _ = parse_emoji(emoji, interaction.guild)
        async with manager.lock:
            manager.store.unbind(interaction.guild_id, panel, key)
        await confirm(
            interaction, "Pasangan dihapus. Role member yang sudah ada tidak diubah."
        )

    @reaction.command(
        name="preview",
        description="Tinjau isi panel secara privat, tanpa ping atau perubahan role",
    )
    async def panel_preview(interaction: discord.Interaction, panel: int):
        await guard(interaction)
        definition = manager.store.panel(interaction.guild_id, panel)
        await confirm(
            interaction,
            "Preview panel:",
            embed=panel_embed(definition, manager.store.mappings(panel)),
        )

    @reaction.command(
        name="publish",
        description="Terbitkan/aktifkan panel dan tambahkan emoji pilihannya",
    )
    async def publish(
        interaction: discord.Interaction, panel: int, channel: discord.TextChannel
    ):
        await guard(interaction)
        message = await manager.publish(
            interaction.guild, panel, channel.id, interaction.user
        )
        await confirm(interaction, "Panel aktif: " + message.jump_url)

    @reaction.command(
        name="disable",
        description="Jeda panel; tidak mencabut role member secara massal",
    )
    async def disable(interaction: discord.Interaction, panel: int):
        await guard(interaction)
        await manager.disable(interaction.guild, panel)
        await confirm(interaction, "Panel dinonaktifkan. Role member dipertahankan.")

    @reaction.command(
        name="delete",
        description="Hapus konfigurasi panel; role dan pesan lama tetap ada",
    )
    async def delete(interaction: discord.Interaction, panel: int):
        await guard(interaction)
        async with manager.lock:
            manager.store.delete(interaction.guild_id, panel)
        await confirm(
            interaction,
            "Konfigurasi panel dihapus. Pesan lama tidak lagi diproses dan role dipertahankan.",
        )

    @reaction.command(
        name="list", description="Lihat panel server ini dan gangguan terakhir"
    )
    async def panels(interaction: discord.Interaction):
        await guard(interaction)
        rows = manager.store.panels(interaction.guild_id)
        lines = [
            f"#{row['id']} · {discord.utils.escape_mentions(row['title'])} · {row['mode']} · {'aktif' if row['enabled'] else 'draft/jeda'}"
            for row in rows
        ]
        await confirm(
            interaction,
            ("\n".join(lines) or "Belum ada panel.")
            + "\nGangguan terakhir: "
            + (manager.last_error or "tidak tercatat"),
        )

    reaction.error(error)
    tree.add_command(reaction)
