"""Private dashboard gateway. All mutations use the live bot's existing managers."""
import hmac
import logging
import re
import time
import discord
from aiohttp import web
from app.leveling import LevelingError
from app.onboarding import OnboardingError, parse_emoji
from app.ticket_store import TicketError
from app.creator_notifications import NotificationError, Event

log = logging.getLogger(__name__)
SAFE_ERRORS = (LevelingError, OnboardingError, TicketError, NotificationError, ValueError)
ID_FIELDS = {"guild", "channel", "announcement", "category", "support", "log",
             "destination", "panel_channel", "panel_message", "message", "role"}

def snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValueError("Pilih server, channel atau role yang valid.")
    result = int(value)
    if not 0 < result < 2**63:
        raise ValueError("ID tidak valid.")
    return result

def row_json(row):
    return {k: str(v) if k in ID_FIELDS and v is not None else v
            for k, v in dict(row).items()}

def toggle(data, key):
    value = data.get(key)
    if type(value) is not bool:
        raise ValueError("Pengaturan aktif/nonaktif tidak valid.")
    return value

def string(data, key, limit, default=None):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Isi pengaturan tidak valid atau terlalu panjang.")
    return value

def number(data, key="id"):
    value = data.get(key)
    if type(value) is not int or not 0 < value < 2**31:
        raise ValueError("ID konfigurasi tidak valid.")
    return value

def resource(guild, data, key, cls, optional=False):
    value = data.get(key)
    if optional and value in ("", None):
        return None
    ident = snowflake(value)
    obj = guild.get_role(ident) if cls is discord.Role else guild.get_channel(ident)
    if not isinstance(obj, cls) or obj.guild.id != guild.id:
        raise ValueError("Pilih channel atau role dari server ini.")
    return obj

def available(manager):
    return bool(manager.enabled and manager.store is not None)

def snapshot(guild, level, onboarding, tickets, notify, voice, music):
    gid = guild.id
    result = {
        "guild": {"id": str(gid), "name": guild.name},
        "channels": [{"id": str(c.id), "name": c.name,
                      "type": "text" if isinstance(c, discord.TextChannel) else
                      "voice" if isinstance(c, discord.VoiceChannel) else "category"}
                     for c in guild.channels if isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel))],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed],
        "leveling": None, "welcome": None, "ticket": None, "notifications": None,
        "panels": [], "available": {"leveling": available(level), "onboarding": available(onboarding),
            "ticket": available(tickets), "notifications": available(notify),
            "voice": voice.configured(), "music": bool(music.enabled)},
        "providers": {"youtube": bool(notify.key), "tiktok": len(notify.webhook_secret) >= 32},
        "sessions": {"voice": gid in voice.sessions, "music": gid in music.sessions},
    }
    if available(level):
        result["leveling"] = row_json(level.store.config(gid))
        result["leveling"]["excluded"] = [str(i) for i in level.store.excludes(gid)]
    if available(onboarding):
        result["welcome"] = row_json(onboarding.store.welcome(gid))
        result["panels"] = [dict(row_json(p), mappings=[row_json(m) for m in onboarding.store.mappings(p["id"])])
                            for p in onboarding.store.panels(gid)]
    if available(tickets):
        try:
            result["ticket"] = row_json(tickets.store.settings(gid))
        except TicketError:
            pass
    if available(notify):
        result["notifications"] = [row_json(r) for r in notify.store.list(gid)]
    return result

async def administer(guild, actor, action, data, level, onboarding, tickets, notify):
    gid = guild.id
    if action == "leveling.save":
        level.require(guild)
        channel = resource(guild, data, "announcement", discord.TextChannel, True)
        if channel:
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise LevelingError("Izin bot pada channel pengumuman belum lengkap.")
        level.store.configure(gid, toggle(data, "enabled"), toggle(data, "chat"),
                              toggle(data, "voice"), channel.id if channel else None)
        level.forget(gid)
        level.sync_voice(guild)
    elif action == "leveling.exclude":
        level.require(guild)
        channel = resource(guild, data, "channel", (discord.TextChannel, discord.VoiceChannel))
        level.store.exclude(gid, channel.id, toggle(data, "excluded"))
        level.sync_voice(guild)
    elif action == "welcome.save":
        onboarding.require(guild)
        enabled = toggle(data, "enabled")
        channel = resource(guild, data, "channel", discord.TextChannel, optional=not enabled)
        if enabled:
            onboarding.channel(guild, channel.id)
        onboarding.store.set_welcome(gid, enabled, channel.id if channel else None,
                                     string(data, "template", 1500), toggle(data, "ping"))
    elif action == "welcome.test":
        onboarding.require(guild)
        if not await onboarding.welcome(actor, test=True):
            raise OnboardingError("Contoh belum terkirim. Aktifkan welcome dan periksa izin channel.")
    elif action.startswith("reaction."):
        onboarding.require(guild)
        if action == "reaction.create":
            async with onboarding.lock:
                onboarding.store.create(gid, string(data, "title", 100),
                    string(data, "description", 1500), string(data, "mode", 8))
        elif action in ("reaction.bind", "reaction.unbind"):
            ident = number(data)
            key, display = parse_emoji(string(data, "emoji", 100), guild)
            async with onboarding.lock:
                if action == "reaction.bind":
                    role = resource(guild, data, "role", discord.Role)
                    onboarding.check_role(guild, role, actor)
                    onboarding.store.bind(gid, ident, key, display, role.id)
                else:
                    onboarding.store.unbind(gid, ident, key)
        elif action == "reaction.publish":
            channel = resource(guild, data, "channel", discord.TextChannel)
            await onboarding.publish(guild, number(data), channel.id, actor)
        elif action == "reaction.disable":
            await onboarding.disable(guild, number(data))
        elif action == "reaction.delete":
            async with onboarding.lock:
                onboarding.store.delete(gid, number(data))
        else:
            raise ValueError("Aksi tidak tersedia.")
    elif action == "ticket.save":
        tickets.require(guild)
        await tickets.configure(guild, toggle(data, "enabled"),
            resource(guild, data, "category", discord.CategoryChannel),
            resource(guild, data, "support", discord.Role),
            resource(guild, data, "log", discord.TextChannel),
            string(data, "title", 100), string(data, "description", 1500))
    elif action == "ticket.publish":
        tickets.require(guild)
        await tickets.publish(guild, resource(guild, data, "channel", discord.TextChannel))
    elif action.startswith("notify."):
        notify.require()
        if action == "notify.add":
            destination = resource(guild, data, "destination", discord.TextChannel)
            ping = string(data, "ping", 8)
            events = string(data, "events", 8)
            if ping not in ("none", "here", "everyone") or events not in ("live", "post", "both"):
                raise NotificationError("Jenis notifikasi tidak valid.")
            notify.destination(gid, destination.id, ping)
            if not notify.key:
                raise NotificationError("YouTube belum dikonfigurasi pengelola bot.")
            creator = await notify.youtube.resolve(string(data, "url", 500))
            notify.store.add(gid, destination.id, creator, ping, events)
        elif action == "notify.edit":
            ident = number(data)
            notify.store.get(gid, ident)
            dest = resource(guild, data, "destination", discord.TextChannel)
            ping, events = string(data, "ping", 8), string(data, "events", 8)
            enabled = toggle(data, "enabled")
            if ping not in ("none", "here", "everyone") or events not in ("live", "post", "both"):
                raise NotificationError("Jenis notifikasi tidak valid.")
            if enabled:
                notify.destination(gid, dest.id, ping)
            notify.store.edit(gid, ident, dest.id, ping, events, enabled)
        elif action == "notify.remove":
            notify.store.remove(gid, number(data))
        elif action == "notify.test":
            row = notify.store.get(gid, number(data))
            await notify.send(row, Event(row["platform"], row["account"], "", "live",
                         "Contoh tampilan notifikasi Abud", time.time()), test=True)
        else:
            raise ValueError("Aksi tidak tersedia.")
    else:
        raise ValueError("Aksi tidak tersedia.")

def install_dashboard_gateway(app, client, key, level, onboarding, tickets, notify, voice, music):
    async def handle(request):
        if not key or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + key):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        if not client.is_ready():
            return web.json_response({"detail": "Bot belum siap."}, status=503)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Permintaan tidak valid.")
            guild = client.get_guild(snowflake(payload.get("guild_id")))
            actor_id = snowflake(payload.get("user_id"))
            action = payload.get("action")
            data = payload.get("data", {})
            if not isinstance(action, str) or not isinstance(data, dict):
                raise ValueError("Permintaan tidak valid.")
            if not guild:
                return web.json_response({"detail": "Bot tidak berada di server ini."}, status=403)
            # Fresh member fetch for every request, not browser-supplied permissions.
            actor = await guild.fetch_member(actor_id)
            if not actor.guild_permissions.administrator:
                return web.json_response({"detail": "Hanya Administrator server."}, status=403)
            if action != "read":
                await administer(guild, actor, action, data, level, onboarding, tickets, notify)
                log.info("Discord dashboard action=%s guild=%s actor=%s", action, guild.id, actor.id)
                return web.json_response({"ok": True})
            return web.json_response(snapshot(guild, level, onboarding, tickets, notify, voice, music))
        except discord.NotFound:
            return web.json_response({"detail": "Server atau anggota tidak ditemukan."}, status=403)
        except SAFE_ERRORS as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        except discord.Forbidden:
            return web.json_response({"detail": "Izin Discord tidak cukup."}, status=403)
        except Exception:
            log.exception("Discord dashboard operation failed")
            return web.json_response({"detail": "Operasi gagal. Muat ulang untuk memeriksa status sebelum mencoba lagi."}, status=503)
    app.router.add_post("/internal/dashboard/discord", handle)
