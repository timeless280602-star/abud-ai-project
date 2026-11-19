"""Persistent ticket entry/control buttons, short-lived forms and explicit close confirmation."""

import discord

from app.ticket_store import KINDS, TicketError


async def ui_error(interaction, manager, error):
    manager.failure(error)
    text = (
        str(error)
        if isinstance(error, TicketError)
        else "Operasi tiket belum selesai. Coba /ticket status; admin dapat memeriksa /ticket repair."
    )
    if interaction.response.is_done():
        await interaction.followup.send(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )
    else:
        await interaction.response.send_message(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )


def panel_embed(settings):
    embed = discord.Embed(
        title=discord.utils.escape_mentions(settings["title"]),
        description=discord.utils.escape_mentions(settings["description"]),
        color=0xEF4444,
    )
    embed.set_footer(
        text="Satu tiket aktif per member • Ruang privat bersama tim support"
    )
    return embed


class TicketPanel(discord.ui.View):
    def __init__(self, manager):
        super().__init__(timeout=None)
        button = discord.ui.Button(
            label="🎫 Buka Tiket",
            style=discord.ButtonStyle.primary,
            custom_id="abud:ticket:open:v1",
        )

        async def callback(interaction):
            try:
                manager.panel_check(interaction)
                await interaction.response.send_message(
                    "Pilih jenis bantuan, lalu isi ringkasan masalah.",
                    view=TicketKind(
                        manager, interaction.user.id, interaction.message.id
                    ),
                    ephemeral=True,
                )
            except Exception as error:  # noqa: BLE001 - safe interaction boundary
                await ui_error(interaction, manager, error)

        button.callback = callback
        self.add_item(button)


class TicketKind(discord.ui.View):
    def __init__(self, manager, owner, panel_message):
        super().__init__(timeout=120)
        select = discord.ui.Select(
            placeholder="Jenis bantuan",
            options=[
                discord.SelectOption(label=label, value=kind)
                for kind, label in KINDS.items()
            ],
        )

        async def callback(interaction):
            try:
                if interaction.user.id != owner:
                    raise TicketError("Form ini hanya untuk peminta tiket.")
                manager.panel_check(interaction, panel_message)
                await interaction.response.send_modal(
                    TicketForm(manager, owner, panel_message, select.values[0])
                )
            except Exception as error:  # noqa: BLE001 - safe interaction boundary
                await ui_error(interaction, manager, error)

        select.callback = callback
        self.add_item(select)


class TicketForm(discord.ui.Modal):
    def __init__(self, manager, owner, panel_message, kind):
        super().__init__(title="Buka Ticket Support", timeout=300)
        self.manager, self.owner, self.panel_message, self.kind = (
            manager,
            owner,
            panel_message,
            kind,
        )
        self.summary = discord.ui.TextInput(
            label="Ringkasan masalah",
            style=discord.TextStyle.paragraph,
            placeholder="Jelaskan bantuan yang kamu perlukan.",
            min_length=10,
            max_length=1200,
        )
        self.add_item(self.summary)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.owner:
                raise TicketError("Form ini hanya untuk peminta tiket.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            row = await self.manager.open(
                interaction, self.kind, str(self.summary), self.panel_message
            )
            await interaction.followup.send(
                f"Tiket #{row['id']:05d} siap: <#{row['channel']}>",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as error:  # noqa: BLE001 - never expose private exception bodies
            await ui_error(interaction, self.manager, error)


class CloseReason(discord.ui.Modal):
    def __init__(self, manager, owner):
        super().__init__(title="Alasan Penutupan Tiket", timeout=300)
        self.manager, self.owner = manager, owner
        self.reason = discord.ui.TextInput(
            label="Alasan penutupan",
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.owner:
                raise TicketError("Form ini hanya untuk peminta penutupan.")
            await request_close(interaction, self.manager, str(self.reason))
        except Exception as error:  # noqa: BLE001 - safe interaction boundary
            await ui_error(interaction, self.manager, error)


async def request_close(interaction, manager, reason):
    row = manager.context(interaction)
    if row["state"] not in ("open", "claimed") or not 3 <= len(reason.strip()) <= 500:
        raise TicketError("Tiket harus terbuka dan alasan penutupan 3–500 karakter.")
    view = ConfirmClose(manager, interaction.user.id, row["id"], reason.strip())
    await interaction.response.send_message(
        f"Tutup tiket #{row['id']:05d} menjadi baca-saja?\nAlasan: {discord.utils.escape_mentions(reason)[:500]}",
        view=view,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class ConfirmClose(discord.ui.View):
    def __init__(self, manager, actor, ident, reason):
        super().__init__(timeout=60)
        self.used = False
        confirm = discord.ui.Button(
            label="Ya, Tutup Tiket", style=discord.ButtonStyle.danger
        )
        cancel = discord.ui.Button(label="Batal", style=discord.ButtonStyle.secondary)

        async def callback(interaction, *, cancelled=False):
            try:
                if interaction.user.id != actor:
                    raise TicketError("Konfirmasi ini hanya untuk pemintanya.")
                if self.used or self.is_finished():
                    raise TicketError("Konfirmasi sudah dipakai atau kedaluwarsa.")
                self.used = True
                self.stop()
                if cancelled:
                    await interaction.response.edit_message(
                        content="Penutupan dibatalkan.", view=None
                    )
                    return
                row = manager.context(interaction)
                if row["id"] != ident:
                    raise TicketError("Konteks tiket berubah. Minta konfirmasi baru.")
                await interaction.response.defer(ephemeral=True, thinking=True)
                await manager.apply(interaction, "close", reason)
                await interaction.edit_original_response(
                    content="Tiket ditutup dan menjadi baca-saja.", view=None
                )
            except Exception as error:  # noqa: BLE001 - reauthorize at confirmation time
                await ui_error(interaction, manager, error)

        confirm.callback = callback

        async def abort(interaction):
            await callback(interaction, cancelled=True)

        cancel.callback = abort
        self.add_item(confirm)
        self.add_item(cancel)


class TicketControls(discord.ui.View):
    def __init__(self, manager, *, closed=None):
        super().__init__(timeout=None)
        for label, action in [
            ("Claim", "claim"),
            ("Unclaim", "unclaim"),
            ("Tutup Tiket", "close"),
            ("Reopen", "reopen"),
        ]:
            button = discord.ui.Button(
                label=label,
                custom_id=f"abud:ticket:{action}:v1",
                style=discord.ButtonStyle.danger
                if action == "close"
                else discord.ButtonStyle.secondary,
                disabled=closed is not None
                and (
                    (action == "reopen" and not closed)
                    or (action != "reopen" and closed)
                ),
            )

            async def callback(interaction, action=action):
                try:
                    manager.context(interaction, action=action, control_message=True)
                    if action == "close":
                        await interaction.response.send_modal(
                            CloseReason(manager, interaction.user.id)
                        )
                        return
                    await interaction.response.defer(ephemeral=True, thinking=True)
                    await manager.apply(interaction, action, control_message=True)
                    await interaction.followup.send(
                        "Status tiket diperbarui.", ephemeral=True
                    )
                except Exception as error:  # noqa: BLE001 - safe interaction boundary
                    await ui_error(interaction, manager, error)

            button.callback = callback
            self.add_item(button)
