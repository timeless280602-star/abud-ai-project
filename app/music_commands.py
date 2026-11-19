"""Slash commands and explicit song selection for Abud Music."""

import discord
import wavelink
from discord import app_commands

from app.discord_music import now_embed, queue_embed
from app.music_session import MusicChoiceRequired, MusicError, duration
from app.music_providers import NAMES, PREFIXES

SOURCES = [app_commands.Choice(name=NAMES[p], value=p) for p in PREFIXES] + [
    app_commands.Choice(name="Audius", value="audius")
]
MODES = [
    app_commands.Choice(name=name, value=mode)
    for name, mode in [
        ("Mati", "off"),
        ("Lagu ini", "track"),
        ("Seluruh antrean", "queue"),
    ]
]


class SongSelection(discord.ui.View):
    def __init__(self, manager, requester, tracks):
        super().__init__(timeout=60)
        self.message = None
        self.requester = requester
        select = discord.ui.Select(
            placeholder="Pilih lagu untuk ditambahkan",
            options=[
                discord.SelectOption(
                    label=track.title[:100],
                    value=str(index),
                    description=f"{track.author} • {'LIVE' if track.is_stream else duration(track.length)}"[
                        :100
                    ],
                )
                for index, track in enumerate(tracks[:5])
            ],
        )

        async def callback(interaction):
            if interaction.user.id != requester:
                await interaction.response.send_message(
                    "Hasil pencarian ini untuk pemintanya. Gunakan /music search sendiri.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True)
            # Consume selection before I/O, so two clicks cannot enqueue the song twice.
            if self.is_finished():
                await interaction.followup.send(
                    "Pilihan sudah digunakan. Cari lagi untuk menambah lagu lain.",
                    ephemeral=True,
                )
                return
            self.stop()
            select.disabled = True
            try:
                await interaction.edit_original_response(view=self)
                track = tracks[int(select.values[0])]
                await manager.enqueue(interaction, [track])
                await interaction.followup.send(
                    f"Ditambahkan: {discord.utils.escape_mentions(track.title)[:150]}.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as error:  # noqa: BLE001 - never display upstream URLs or credentials
                await interaction.followup.send(
                    str(error)
                    if isinstance(error, MusicError)
                    else "Lagu belum bisa ditambahkan. Coba lagi.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        select.callback = callback
        self.add_item(select)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


def install_music_commands(tree, manager):
    group = app_commands.Group(
        name="music",
        description="Putar musik, kelola antrean, dan kontrol player Abud",
        guild_only=True,
    )

    async def defer(interaction):
        manager.require()
        manager.user_channel(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)

    async def confirm(interaction, text):
        await interaction.followup.send(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    async def play_request(interaction, query, source):
        await defer(interaction)
        try:
            tracks = await manager.play_query(interaction, query, source)
        except MusicChoiceRequired as choice:
            await send_selection(interaction, choice.tracks)
            return
        await confirm(
            interaction,
            f"🎶 {len(tracks)} lagu ditambahkan. Panel pemutar tersedia di channel sesi musik.",
        )

    @group.command(
        name="play",
        description="Putar judul/link lagu atau playlist; otomatis masuk voice kamu",
    )
    @app_commands.choices(source=SOURCES)
    async def play(
        interaction: discord.Interaction, query: str, source: str | None = None
    ):
        await play_request(interaction, query, source)

    @tree.command(
        name="play",
        description="Putar judul atau link provider musik aktif di voice kamu",
    )
    @app_commands.guild_only()
    @app_commands.choices(source=SOURCES)
    async def quick_play(
        interaction: discord.Interaction, query: str, source: str | None = None
    ):
        await play_request(interaction, query, source)

    @group.command(
        name="search",
        description="Cari lalu pilih satu dari lima hasil; tidak langsung memutar",
    )
    @app_commands.choices(source=SOURCES)
    async def search(
        interaction: discord.Interaction, query: str, source: str | None = None
    ):
        await defer(interaction)
        result = await manager.search(query, source)
        tracks = result.tracks if isinstance(result, wavelink.Playlist) else result
        await send_selection(interaction, tracks)

    async def send_selection(interaction, tracks):
        if not tracks:
            raise MusicError("Tidak ada lagu yang dapat dipilih.")
        view = SongSelection(manager, interaction.user.id, tracks)
        view.message = await interaction.followup.send(
            "Pilih satu lagu (berlaku 60 detik).", view=view, ephemeral=True, wait=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @group.command(
        name="queue", description="Lihat antrean lagu dengan nomor untuk remove/move"
    )
    async def queue(
        interaction: discord.Interaction, page: app_commands.Range[int, 1, 10] = 1
    ):
        await defer(interaction)
        await interaction.followup.send(
            embed=queue_embed(manager.active(interaction), page),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @group.command(
        name="nowplaying",
        description="Lihat judul, durasi, peminta lagu, dan status pemutar",
    )
    async def nowplaying(interaction: discord.Interaction):
        await defer(interaction)
        await interaction.followup.send(
            embed=now_embed(manager.active(interaction)),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def control(interaction, action, value=None):
        await defer(interaction)
        await manager.apply(interaction, action, value)
        await confirm(interaction, "Kontrol musik diperbarui.")

    @group.command(name="pause", description="Jeda lagu saat ini")
    async def pause(interaction: discord.Interaction):
        await control(interaction, "pause")

    @group.command(name="resume", description="Lanjutkan lagu yang dijeda")
    async def resume(interaction: discord.Interaction):
        await control(interaction, "resume")

    @group.command(
        name="skip", description="Lewati lagu saat ini, termasuk jika repeat aktif"
    )
    async def skip(interaction: discord.Interaction):
        await control(interaction, "skip")

    @group.command(
        name="previous", description="Putar lagi lagu sebelumnya dari riwayat sesi"
    )
    async def previous(interaction: discord.Interaction):
        await control(interaction, "previous")

    @group.command(
        name="stop",
        description="Hentikan musik dan kosongkan antrean; Abud tetap terhubung",
    )
    async def stop(interaction: discord.Interaction):
        await control(interaction, "stop")

    @group.command(
        name="leave", description="Tutup sesi musik dan keluarkan Abud dari voice"
    )
    async def leave(interaction: discord.Interaction):
        await control(interaction, "leave")

    @group.command(
        name="shuffle", description="Acak lagu yang menunggu tanpa mengubah lagu aktif"
    )
    async def shuffle(interaction: discord.Interaction):
        await control(interaction, "shuffle")

    @group.command(
        name="repeat",
        description="Ulangi satu lagu, seluruh antrean, atau matikan repeat",
    )
    @app_commands.choices(mode=MODES)
    async def repeat(interaction: discord.Interaction, mode: str):
        await control(interaction, "repeat", mode)

    @group.command(name="volume", description="Atur volume pemutar 0–100%")
    async def volume(
        interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]
    ):
        await control(interaction, "volume", percent)

    @group.command(
        name="seek", description="Lompat ke posisi detik pada lagu yang mendukung seek"
    )
    async def seek(
        interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 86400]
    ):
        await control(interaction, "seek", seconds)

    @group.command(
        name="remove", description="Hapus satu lagu dari antrean berdasarkan nomornya"
    )
    async def remove(
        interaction: discord.Interaction, position: app_commands.Range[int, 1, 100]
    ):
        await control(interaction, "remove", position)

    @group.command(
        name="move", description="Pindahkan nomor lagu ke posisi antrean yang dipilih"
    )
    async def move(
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1, 100],
        destination: app_commands.Range[int, 1, 100],
    ):
        await control(interaction, "move", (position, destination))

    @group.command(
        name="clear",
        description="Kosongkan lagu yang menunggu; lagu aktif tetap berjalan",
    )
    async def clear(interaction: discord.Interaction):
        await control(interaction, "clear")

    @group.error
    async def on_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        cause = getattr(error, "original", error)
        text = (
            str(cause)
            if isinstance(cause, MusicError)
            else "Layanan/sumber musik belum siap. Periksa Lavalink dan coba sumber lagu lain."
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )

    quick_play.error(on_error)
    tree.add_command(group)
