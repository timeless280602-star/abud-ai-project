import os
import re
import json
import asyncio
import urllib.request
import urllib.error
import hmac

import discord
from discord import app_commands
from aiohttp import web

from app.discord_voice import DiscordVoice, install_voice_commands
from app.discord_notifications import Notifications, install_notification_commands
from app.discord_music import Music
from app.music_commands import install_music_commands


TOKEN = os.getenv("DISCORD_TOKEN")
INTERNAL_API_KEY = os.getenv("ABUD_INTERNAL_API_KEY", "")
API_URL = os.getenv(
    "ABUD_API_URL",
    "http://abud-api:8000/chat"
)

MEMORY_DELETE_URL = API_URL.rsplit("/", 1)[0] + "/memory/delete"
AUTO_SAVE_URL = API_URL.rsplit("/", 1)[0] + "/memory/auto-save"

GLOBAL_MEMORY_OWNER_ID = 1357798812168618044

VERIFY_HOST = os.getenv("ABUD_BOT_VERIFY_HOST", "0.0.0.0")
VERIFY_PORT = int(os.getenv("ABUD_BOT_VERIFY_PORT", "8765"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN belum dikonfigurasi.")

if not INTERNAL_API_KEY:
    raise RuntimeError("ABUD_INTERNAL_API_KEY belum dikonfigurasi.")


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


class AbudClient(discord.Client):
    async def close(self):
        try:
            try:
                await notification_manager.close()
            finally:
                try:
                    await music_manager.close()
                finally:
                    await voice_manager.close()
        finally:
            try:
                runner = getattr(self, "_verification_gateway_runner", None)
                if runner:
                    await runner.cleanup()
            finally:
                await super().close()


client = AbudClient(intents=intents)
tree = app_commands.CommandTree(client)
voice_manager = DiscordVoice(client, API_URL, INTERNAL_API_KEY)
install_voice_commands(tree, voice_manager)
notification_manager = Notifications(client)
install_notification_commands(tree, notification_manager)
music_manager = Music(client, voice_manager)
install_music_commands(tree, music_manager)



def can_use_mass_mention(user, guild):
    """Hanya Server Owner atau Administrator yang boleh mass mention."""
    if guild is None or user is None:
        return False

    if user.id == guild.owner_id:
        return True

    return (
        isinstance(user, discord.Member)
        and user.guild_permissions.administrator
    )


def prepare_mention_content(content, user, guild, mentioned_roles=None):
    """Validasi mention user/role; mass mention tetap dibatasi."""
    content = str(content or "")
    can_mass = can_use_mass_mention(user, guild)

    if not can_mass:
        content = re.sub(
            r"@(everyone|here)\b",
            lambda match: "@\u200b" + match.group(1),
            content,
            flags=re.IGNORECASE
        )

    role_ids = {
        str(item.get("id"))
        for item in (mentioned_roles or [])
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }

    allowed_roles = []
    can_mention_all_roles = (
        isinstance(user, discord.Member)
        and user.guild_permissions.mention_everyone
    )

    if guild:
        for role_id in role_ids:
            role = guild.get_role(int(role_id))
            if not role or role.is_default():
                continue

            if role.mentionable or can_mention_all_roles:
                allowed_roles.append(role)
            else:
                content = re.sub(
                    rf"<@&{re.escape(role_id)}>",
                    lambda _match, name=role.name: "@\u200b" + name,
                    content
                )

    allowed_mentions = discord.AllowedMentions(
        everyone=can_mass,
        users=True,
        roles=allowed_roles,
        replied_user=False
    )
    return content, allowed_mentions

def can_manage_guild_memory(user, guild):
    if guild is None:
        return False

    if user.id == guild.owner_id:
        return True

    return (
        isinstance(user, discord.Member)
        and user.guild_permissions.administrator
    )


def ask_abud(message, author, guild, channel, mentioned_users=None, mentioned_roles=None):
    is_dm = guild is None

    payload = {
        "message": message,
        "user_id": str(author.id),
        "username": getattr(author, "display_name", author.name),

        "guild_id": str(guild.id) if guild else None,
        "guild_name": guild.name if guild else None,
        "guild_owner_id": str(guild.owner_id) if guild else None,

        "channel_id": str(channel.id) if channel else None,
        "context_type": "dm" if is_dm else "guild",

        "can_manage_guild_memory": can_manage_guild_memory(
            author, guild
        ),
        "mentioned_users": mentioned_users or [],
        "mentioned_roles": mentioned_roles or []
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INTERNAL_API_KEY}"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result





def is_calling_mentioned_users(message):
    if not isinstance(message, str):
        return False

    return bool(re.search(
        r"\b(?:ping|panggil|tag|mention|sapa|ajak|undang)\b",
        message,
        re.IGNORECASE
    ))


def ensure_target_mentions(answer, message, mentioned_users, mentioned_roles=None):
    """Pastikan semua user dan role yang dituju benar-benar disebut."""
    if not is_calling_mentioned_users(message):
        return answer

    answer = str(answer or "").strip()
    seen = set()

    for target_type, items in (
        ("user", mentioned_users or []),
        ("role", mentioned_roles or [])
    ):
        for item in items:
            if not isinstance(item, dict):
                continue

            target_id = str(item.get("id", ""))
            if not target_id.isdigit():
                continue

            key = (target_type, target_id)
            if key in seen:
                continue
            seen.add(key)

            target_name = str(
                item.get("display_name")
                or item.get("name")
                or item.get("username")
                or ""
            ).strip()

            token = (
                f"<@&{target_id}>"
                if target_type == "role"
                else f"<@{target_id}>"
            )

            if token in answer:
                continue

            replaced = False
            if target_name:
                pattern = re.compile(
                    r"@" + re.escape(target_name) + r"(?!\w)",
                    re.IGNORECASE
                )
                answer, count = pattern.subn(
                    lambda _match, value=token: value,
                    answer
                )
                replaced = count > 0

            if not replaced:
                label = "Role" if target_type == "role" else "Woy"
                suffix = f"{label} {token}, dicariin nih!"
                answer = f"{answer}\n{suffix}" if answer else suffix

    return answer

def auto_save_abud(message, author, guild, channel):
    is_dm = guild is None

    payload = {
        "message": message,
        "user_id": str(author.id),
        "username": getattr(author, "display_name", author.name),

        "guild_id": str(guild.id) if guild else None,
        "guild_name": guild.name if guild else None,
        "guild_owner_id": str(guild.owner_id) if guild else None,

        "channel_id": str(channel.id) if channel else None,
        "context_type": "dm" if is_dm else "guild",

        "can_manage_guild_memory": can_manage_guild_memory(
            author, guild
        )
    }

    req = urllib.request.Request(
        AUTO_SAVE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INTERNAL_API_KEY}"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=75) as response:
        return json.loads(response.read().decode("utf-8"))


async def run_auto_save(message, author, guild, channel):
    """
    Berjalan di background agar tidak menahan jawaban utama Abud.
    """

    try:
        result = await asyncio.to_thread(
            auto_save_abud,
            message,
            author,
            guild,
            channel
        )

        events = result.get("memory_events", [])

        # Auto-Save tetap menyimpan Memory secara otomatis,
        # tetapi tidak mengirim notifikasi DM untuk setiap hasil.
        if events:
            print(f"Auto-Save: {len(events)} memory event(s) tersimpan.")

    except Exception as error:
        print(
            f"Background auto-save error: "
            f"{type(error).__name__}: {error}"
        )


async def send_long_message(message, content, mentioned_roles=None):
    content = str(content).strip()

    if not content:
        content = "Maaf, aku belum mendapatkan jawaban."

    content, allowed_mentions = prepare_mention_content(
        content,
        message.author,
        message.guild,
        mentioned_roles
    )

    chunks = [
        content[i:i + 1900]
        for i in range(0, len(content), 1900)
    ]

    for index, chunk in enumerate(chunks):
        if index == 0:
            await message.reply(
                chunk,
                allowed_mentions=allowed_mentions
            )
        else:
            await message.channel.send(
                chunk,
                allowed_mentions=allowed_mentions
            )


async def send_interaction_result(interaction, prompt, ephemeral=True):
    if not interaction.response.is_done():
        await interaction.response.defer(
            ephemeral=ephemeral,
            thinking=True
        )

    try:
        result = await asyncio.to_thread(
            ask_abud,
            prompt,
            interaction.user,
            interaction.guild,
            interaction.channel
        )

        answer = result.get("reply", "Maaf, aku belum mendapatkan jawaban.")
        memory_events = result.get("memory_events", [])

        answer, allowed_mentions = prepare_mention_content(
            answer,
            interaction.user,
            interaction.guild
        )

        chunks = [
            answer[i:i + 1900]
            for i in range(0, len(answer), 1900)
        ]

        if not chunks:
            chunks = ["Maaf, aku belum mendapatkan jawaban."]

        for chunk in chunks:
            await interaction.followup.send(
                chunk,
                ephemeral=ephemeral,
                allowed_mentions=allowed_mentions
            )

        await notify_memory_events(
            interaction.user,
            memory_events,
            interaction.guild
        )

        # Auto-save berjalan setelah jawaban terkirim.
        asyncio.create_task(
            run_auto_save(
                prompt,
                interaction.user,
                interaction.guild,
                interaction.channel
            )
        )

        return memory_events

    except urllib.error.HTTPError as error:
        print(f"Abud API HTTP error: {error.code}")
        await interaction.followup.send(
            "Maaf, Abud sedang mengalami gangguan pada layanan AI.",
            ephemeral=True
        )

    except Exception as error:
        print(f"Abud error: {type(error).__name__}: {error}")
        await interaction.followup.send(
            "Maaf, Abud belum bisa memproses perintahmu. Coba lagi.",
            ephemeral=True
        )

    return []


async def deny(interaction, message):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# =========================================================
# MEMORY DELETE BUTTON & NOTIFICATION
# =========================================================

def delete_memory_api(payload):
    req = urllib.request.Request(
        MEMORY_DELETE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INTERNAL_API_KEY}"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


class MemoryDeleteView(discord.ui.View):
    def __init__(self, owner_id, scope, memory_id, guild_id=None):
        super().__init__(timeout=86400)
        self.owner_id = int(owner_id)
        self.scope = str(scope)
        self.memory_id = int(memory_id)
        self.guild_id = str(guild_id) if guild_id else None

    @discord.ui.button(
        label="Hapus",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def delete_button(self, interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Tombol ini hanya bisa digunakan oleh pemilik Memory.",
                ephemeral=True
            )
            return

        guild = None
        can_manage = False
        context_type = "dm"

        if self.scope == "guild":
            if not self.guild_id:
                await interaction.response.send_message(
                    "Guild tidak ditemukan. Memory tidak dihapus.",
                    ephemeral=True
                )
                return

            try:
                guild = client.get_guild(int(self.guild_id))
                if guild is None:
                    guild = await client.fetch_guild(int(self.guild_id))

                member = guild.get_member(interaction.user.id)
                if member is None:
                    member = await guild.fetch_member(interaction.user.id)

                can_manage = can_manage_guild_memory(member, guild)
                context_type = "guild"

            except (discord.HTTPException, discord.NotFound):
                await interaction.response.send_message(
                    "Abud tidak dapat memverifikasi keanggotaan atau izin server.",
                    ephemeral=True
                )
                return

        payload = {
            "scope": self.scope,
            "memory_id": self.memory_id,
            "user_id": str(interaction.user.id),
            "guild_id": self.guild_id if self.scope == "guild" else None,
            "context_type": context_type,
            "can_manage_guild_memory": can_manage
        }

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await asyncio.to_thread(delete_memory_api, payload)

            for child in self.children:
                child.disabled = True

            await interaction.edit_original_response(view=self)
            await interaction.followup.send(
                "Memory berhasil dihapus.",
                ephemeral=True
            )

        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get(
                    "detail", "Penghapusan ditolak oleh API."
                )
            except Exception:
                detail = "Penghapusan ditolak oleh API."

            await interaction.followup.send(
                f"Tidak dapat menghapus Memory: {detail}",
                ephemeral=True
            )

        except Exception as error:
            print(f"Memory delete error: {type(error).__name__}: {error}")
            await interaction.followup.send(
                "Terjadi gangguan saat menghapus Memory.",
                ephemeral=True
            )


async def notify_memory_events(user, events, guild=None):
    for event in events or []:
        scope = event.get("scope")
        memory_id = event.get("memory_id")

        if scope not in ("personal", "guild", "global") or not memory_id:
            continue

        guild_id = None
        if scope == "guild":
            if guild is None:
                continue
            guild_id = str(guild.id)

        labels = {
            "personal": "Personal Memory",
            "guild": "Guild Memory",
            "global": "Global Memory"
        }

        view = MemoryDeleteView(
            owner_id=user.id,
            scope=scope,
            memory_id=memory_id,
            guild_id=guild_id
        )

        try:
            await user.send(
                f"✅ {labels[scope]} berhasil disimpan.",
                view=view
            )
        except discord.Forbidden:
            print(f"Tidak bisa mengirim notifikasi DM ke user {user.id}.")
        except discord.HTTPException as error:
            print(f"Memory notification error: {error}")


# =========================================================
# CHAT
# =========================================================

@tree.command(
    name="chat",
    description="Berbicara langsung dengan Abud."
)
@app_commands.describe(pesan="Pesan yang ingin kamu sampaikan kepada Abud")
async def chat_command(interaction: discord.Interaction, pesan: str):
    await send_interaction_result(
        interaction,
        pesan,
        ephemeral=False
    )


# =========================================================
# MEMORY
# =========================================================

@tree.command(
    name="memory",
    description="Simpan, lihat, atau hapus Memory Abud."
)
@app_commands.describe(
    permintaan="Contoh: tampilkan memory saya, ingat bahwa ..., hapus memory ..."
)
async def memory_command(
    interaction: discord.Interaction,
    permintaan: str = "Tampilkan Personal Memory saya"
):
    await send_interaction_result(
        interaction,
        permintaan,
        ephemeral=True
    )


# =========================================================
# HELP
# =========================================================

@tree.command(
    name="help",
    description="Lihat panduan penggunaan Abud."
)
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Panduan Abud",
        description="Chat, Memory, dan percakapan suara bersama Abud:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="/chat",
        value="Berbicara dan meminta bantuan Abud seperti biasa.",
        inline=False
    )

    embed.add_field(
        name="/memory",
        value=(
            "Mengelola Memory menggunakan bahasa natural. "
            "Contoh: `tampilkan Personal Memory saya`, "
            "`ingat bahwa saya suka ...`, atau `hapus memory ...`."
        ),
        inline=False
    )

    embed.add_field(
        name="/help",
        value="Menampilkan panduan ini.",
        inline=False
    )

    embed.add_field(
        name="Voice channel",
        value=(
            "`/join` masuk; `/listen aktif:True` aktifkan suaramu; "
            "`/listen aktif:False` berhenti didengar; `/stop` hentikan jawaban; "
            "`/voice-status` status; `/leave` keluar. "
            "Awali setiap pertanyaan dengan ‘Abud’, maksimal 12 detik. "
            "Pembuka sesi atau pengelola server dapat menutup sesi."
        ),
        inline=False
    )

    embed.add_field(
        name="Hak akses Memory",
        value=(
            "Personal Memory hanya bisa dikelola pemilik akun. "
            "Guild Memory hanya bisa ditulis atau diubah Server Owner "
            "dan Administrator. Global Memory hanya bisa dikelola Bos Bara."
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )




# =========================================================
# INTERNAL DISCORD VERIFICATION GATEWAY
# =========================================================

async def verify_guild_member(request):
    expected_key = INTERNAL_API_KEY
    supplied_key = request.headers.get("Authorization", "")

    if not expected_key or not hmac.compare_digest(
        supplied_key,
        f"Bearer {expected_key}"
    ):
        return web.json_response(
            {"detail": "Unauthorized"},
            status=401
        )

    try:
        payload = await request.json()
        guild_id = int(payload.get("guild_id", 0))
        user_id = int(payload.get("user_id", 0))
    except (ValueError, TypeError, AttributeError):
        return web.json_response(
            {"detail": "Invalid request"},
            status=400
        )

    if guild_id <= 0 or user_id <= 0:
        return web.json_response(
            {"detail": "Invalid Discord IDs"},
            status=400
        )

    if not client.is_ready():
        return web.json_response(
            {"detail": "Discord bot is not ready"},
            status=503
        )

    try:
        guild = client.get_guild(guild_id)

        if guild is None:
            guild = await client.fetch_guild(guild_id)

        member = None

        if isinstance(guild, discord.Guild):
            member = guild.get_member(user_id)

        if member is None:
            member = await guild.fetch_member(user_id)

        owner_id = int(guild.owner_id)

        return web.json_response({
            "verified": True,
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "guild_owner_id": str(owner_id),
            "user_id": str(user_id),
            "is_member": True,
            "is_owner": user_id == owner_id,
            "is_admin": bool(
                member.guild_permissions.administrator
            )
        })

    except discord.NotFound:
        return web.json_response({
            "verified": True,
            "is_member": False,
            "is_owner": False,
            "is_admin": False
        })

    except discord.Forbidden:
        return web.json_response(
            {"detail": "Discord verification forbidden"},
            status=403
        )

    except discord.HTTPException:
        return web.json_response(
            {"detail": "Discord API unavailable"},
            status=502
        )



async def network_status(request):
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {INTERNAL_API_KEY}"

    if not INTERNAL_API_KEY or not hmac.compare_digest(
        supplied, expected
    ):
        return web.json_response(
            {"detail": "Unauthorized"},
            status=401
        )

    ready = client.is_ready()
    latency = client.latency

    latency_ms = (
        round(latency * 1000)
        if ready and latency != float("inf")
        else None
    )

    return web.json_response({
        "status": "online" if ready else "offline",
        "ready": ready,
        "discord_latency_ms": latency_ms,
        "guild_count": len(client.guilds) if ready else 0,
    })


async def start_verification_gateway():
    if getattr(client, "_verification_gateway_started", False):
        return

    app = web.Application(client_max_size=16 * 1024)
    app.router.add_get(
        "/internal/status",
        network_status
    )
    app.router.add_post(
        "/internal/verify/guild-member",
        verify_guild_member
    )

    app.router.add_post("/internal/notifications/tiktok", notification_manager.webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        VERIFY_HOST,
        VERIFY_PORT
    )

    await site.start()

    client._verification_gateway_runner = runner
    client._verification_gateway_started = True

    print(
        "Discord Verification Gateway aktif "
        f"di {VERIFY_HOST}:{VERIFY_PORT}"
    )



GUILD_SYNC_URL = API_URL.rsplit("/", 1)[0] + "/internal/guild-sync"


def sync_guild_to_api(guild, is_present=True):
    payload = {
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        "owner_id": str(guild.owner_id),
        "is_present": bool(is_present),
    }

    req = urllib.request.Request(
        GUILD_SYNC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INTERNAL_API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result


async def sync_all_guilds_to_api():
    if not client.is_ready():
        return

    success = 0
    failed = 0

    for guild in client.guilds:
        try:
            await asyncio.to_thread(sync_guild_to_api, guild, True)
            success += 1
        except Exception as error:
            failed += 1
            print(
                f"Guild sync gagal ({guild.id}): "
                f"{type(error).__name__}"
            )

    print(
        f"Guild sync selesai: {success} berhasil, {failed} gagal."
    )


# =========================================================
# BOT EVENTS
# =========================================================

@client.event
async def on_ready():
    print(f"Abud berhasil login sebagai {client.user}")
    print(f"Abud API: {API_URL}")

    try:
        await start_verification_gateway()
    except Exception as error:
        print(
            "Discord Verification Gateway gagal aktif: "
            f"{type(error).__name__}: {error}"
        )

    if not getattr(client, "_slash_commands_synced", False):
        try:
            synced = await tree.sync()
            client._slash_commands_synced = True
            print(f"Slash Commands berhasil disinkronkan: {len(synced)}")
        except Exception as error:
            print(f"Slash Command sync error: {error}")

    await notification_manager.start()
    await music_manager.start()
    await sync_all_guilds_to_api()

    print("Personal / Guild / Global Memory aktif.")


@client.event
async def on_guild_join(guild):
    try:
        await asyncio.to_thread(sync_guild_to_api, guild, True)
        print(f"Guild baru disinkronkan: {guild.name} ({guild.id})")
    except Exception as error:
        print(
            f"Guild join sync gagal ({guild.id}): "
            f"{type(error).__name__}: {error}"
        )


@client.event
async def on_guild_remove(guild):
    await music_manager.leave(guild.id)
    await voice_manager.leave(guild.id)
    try:
        await asyncio.to_thread(sync_guild_to_api, guild, False)
        print(f"Guild ditandai tidak aktif: {guild.id}")
    except Exception as error:
        print(
            f"Guild remove sync gagal ({guild.id}): "
            f"{type(error).__name__}: {error}"
        )


@client.event
async def on_voice_state_update(member, before, after):
    await voice_manager.voice_state_update(member, before, after)
    await music_manager.voice_state_update(member, before, after)


@client.event
async def on_wavelink_track_end(payload):
    await music_manager.track_end(payload)


@client.event
async def on_wavelink_track_exception(payload):
    await music_manager.track_error(payload)


@client.event
async def on_wavelink_track_stuck(payload):
    await music_manager.track_error(payload)


@client.event
async def on_wavelink_websocket_closed(payload):
    await music_manager.connection_lost(payload.player)


@client.event
async def on_wavelink_node_disconnected(payload):
    await music_manager.node_lost(payload)


@client.event
async def on_message(message):
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = (
        client.user in message.mentions
        if client.user else False
    )

    # Deteksi panggilan nama Abud atau Bud dalam kalimat.
    # Harus berupa kata utuh, bukan bagian dari kata lain.
    is_called_by_name = bool(
        re.search(
            r"(?<!\w)(?:abud|bud)(?!\w)",
            message.content,
            re.IGNORECASE
        )
    )

    if not (is_dm or is_mentioned or is_called_by_name):
        return

    # Simpan target user dan role sebelum token Discord dibersihkan.
    mentioned_users = [
        {
            "id": str(target.id),
            "display_name": getattr(target, "display_name", target.name),
            "username": target.name
        }
        for target in message.mentions
        if not client.user or target.id != client.user.id
    ]

    mentioned_roles = [
        {
            "id": str(role.id),
            "name": role.name,
            "mentionable": bool(role.mentionable)
        }
        for role in message.role_mentions
        if not role.is_default()
    ]

    content = message.content

    # Ubah mention user menjadi nama yang dapat dibaca AI.
    for target in mentioned_users:
        target_id = re.escape(target["id"])
        target_name = target["display_name"]
        content = re.sub(
            rf"<@!?{target_id}>",
            lambda _match: f"@{target_name}",
            content
        )

    # Ubah mention role menjadi nama yang dapat dibaca AI.
    for role in mentioned_roles:
        role_id = re.escape(role["id"])
        role_name = role["name"]
        content = re.sub(
            rf"<@&{role_id}>",
            lambda _match: f"@{role_name}",
            content
        )

    # Hapus hanya mention Abud sendiri.
    if client.user:
        content = re.sub(
            rf"<@!?{client.user.id}>",
            "",
            content
        )

    content = content.strip()

    if not content:
        await message.reply("Halo! Ada yang bisa Abud bantu?")
        return

    try:
        async with message.channel.typing():
            answer = await asyncio.to_thread(
                ask_abud,
                content,
                message.author,
                message.guild,
                message.channel,
                mentioned_users,
                mentioned_roles
            )

        reply_text = ensure_target_mentions(
            answer.get("reply", ""),
            content,
            mentioned_users,
            mentioned_roles
        )
        await send_long_message(
            message,
            reply_text,
            mentioned_roles
        )
        memory_events = answer.get("memory_events", [])
        await notify_memory_events(
            message.author,
            memory_events,
            message.guild
        )

        # Tidak menunggu proses ekstraksi Memory.
        asyncio.create_task(
            run_auto_save(
                content,
                message.author,
                message.guild,
                message.channel
            )
        )

    except urllib.error.HTTPError as error:
        print(f"Abud API HTTP error: {error.code}")
        await message.reply(
            "Maaf, Abud sedang mengalami gangguan pada layanan AI."
        )

    except Exception as error:
        print(f"Abud error: {type(error).__name__}: {error}")
        await message.reply(
            "Maaf, Abud belum bisa memproses pesanmu. Coba lagi sebentar."
        )


if __name__ == "__main__":
    client.run(TOKEN)
