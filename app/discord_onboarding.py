"""Opt-in welcomes and reaction-role execution on uncached gateway events."""

import asyncio
import logging
import os
import sqlite3

import discord

from app.onboarding import (
    OnboardingError,
    OnboardingStore,
    emoji_key,
    parse_emoji,
    validate_role,
)

log = logging.getLogger(__name__)


def welcome_embed(member, template, *, test=False):
    values = {
        "member": f"<@{member.id}>",
        "name": discord.utils.escape_markdown(
            discord.utils.escape_mentions(member.display_name)
        ),
        "server": discord.utils.escape_markdown(
            discord.utils.escape_mentions(member.guild.name)
        ),
        "count": str(member.guild.member_count)
        if member.guild.member_count is not None
        else "—",
    }
    # Simultaneous literal substitution: replacement text is never interpreted as a template.
    import re

    description = re.sub(
        r"\{(member|name|server|count)\}",
        lambda match: values[match.group(1)],
        template,
    )
    embed = discord.Embed(
        title="UJI SAMBUTAN" if test else "👋 Selamat datang!",
        description=description[:4000],
        color=0xEF4444,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Abud • Community")
    return embed


def panel_embed(panel, mappings, *, active=None):
    lines = [f"{item['display']} → <@&{item['role']}>" for item in mappings]
    description = (
        discord.utils.escape_mentions(panel["description"]) + "\n\n" + "\n".join(lines)
    ).strip()
    embed = discord.Embed(
        title=discord.utils.escape_mentions(panel["title"]),
        description=description or "Belum ada pilihan emoji–role.",
        color=0xEF4444,
    )
    enabled = bool(panel["enabled"]) if active is None else active
    mode = "Satu pilihan" if panel["mode"] == "single" else "Boleh beberapa pilihan"
    status = (
        "Hapus reaksi untuk melepas role pilihan" if enabled else "DRAFT / NONAKTIF"
    )
    embed.set_footer(text=f"Abud • Panel #{panel['id']} • {mode} • {status}")
    return embed


class Onboarding:
    def __init__(self, client):
        self.client = client
        self.enabled = os.getenv("ABUD_ONBOARDING_ENABLED", "false").lower() == "true"
        self.path = os.getenv("ABUD_ONBOARDING_DB", "/app/onboarding/community.db")
        self.store = None
        self.lock = asyncio.Lock()
        self.welcome_lock = asyncio.Lock()
        self.last_error = None
        self.role_reserved = lambda guild, role: False

    async def start(self):
        if self.enabled and self.store is None:
            try:
                self.store = OnboardingStore(self.path)
            except (OSError, sqlite3.Error) as error:
                self.failure(error)

    def check_role(self, guild, role, actor=None):
        if role and self.role_reserved(guild.id, role.id):
            raise OnboardingError(
                "Role support Ticket tidak boleh menjadi pilihan reaction role publik."
            )
        return validate_role(guild, role, actor)

    def has_role_binding(self, guild, role):
        if self.store is None:
            return False
        return bool(
            self.store.db.execute(
                "SELECT 1 FROM mappings JOIN panels ON panels.id=mappings.panel WHERE panels.guild=? AND mappings.role=? LIMIT 1",
                (guild, role),
            ).fetchone()
        )

    def require(self, guild=None):
        if not self.enabled or self.store is None:
            raise OnboardingError(
                "Welcome/Reaction Roles belum diaktifkan oleh pengelola bot."
            )
        if guild is None:
            raise OnboardingError("Fitur ini tersedia di server Discord.")

    def failure(self, error):
        self.last_error = (
            str(error) if isinstance(error, OnboardingError) else type(error).__name__
        )
        log.warning("Onboarding operation failed (%s)", type(error).__name__)

    async def close(self):
        async with self.lock, self.welcome_lock:
            if self.store:
                self.store.close()
                self.store = None

    def channel(self, guild, ident, *, reactions=False, single=False):
        channel = guild.get_channel(ident)
        if not isinstance(channel, discord.TextChannel) or not guild.me:
            raise OnboardingError("Pilih text channel yang tersedia di server ini.")
        permissions = channel.permissions_for(guild.me)
        needed = ["view_channel", "send_messages", "embed_links"]
        if reactions:
            needed.extend(["read_message_history", "add_reactions"])
        if single:
            needed.append("manage_messages")
        if not all(getattr(permissions, key) for key in needed):
            raise OnboardingError(
                "Izin channel Abud belum lengkap: " + ", ".join(needed) + "."
            )
        return channel

    async def welcome(self, member, *, test=False):
        async with self.welcome_lock:
            return await self._welcome(member, test=test)

    async def _welcome(self, member, *, test=False):
        if not self.enabled or self.store is None or member.bot:
            return False
        try:
            config = self.store.welcome(member.guild.id)
            if not config["enabled"]:
                return False
            joined = getattr(member, "joined_at", None)
            token = joined.isoformat() if joined else None
            if (
                not test
                and token
                and self.store.welcomed(member.guild.id, member.id, token)
            ):
                return False
            channel = self.channel(member.guild, config["channel"])
            ping = bool(config["ping"] and not test)
            await channel.send(
                content=f"<@{member.id}>" if ping else None,
                embed=welcome_embed(member, config["template"], test=test),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=[member] if ping else False,
                    roles=False,
                    replied_user=False,
                ),
            )
            if not test and token:
                self.store.mark_welcomed(member.guild.id, member.id, token)
            return True
        except Exception as error:  # noqa: BLE001 - optional welcoming must not break member events
            self.failure(error)
            return False

    async def publish(self, guild, ident, channel_id, actor):
        self.require(guild)
        async with self.lock:
            panel = self.store.panel(guild.id, ident)
            if panel["channel"] and panel["channel"] != channel_id:
                raise OnboardingError(
                    "Panel yang sudah diterbitkan memakai channel tetap. Buat panel baru untuk channel lain."
                )
            channel = self.channel(
                guild, channel_id, reactions=True, single=panel["mode"] == "single"
            )
            mappings = self.store.mappings(ident)
            if not mappings:
                raise OnboardingError(
                    "Tambahkan minimal satu pasangan emoji–role sebelum publish."
                )
            for item in mappings:
                self.check_role(guild, guild.get_role(item["role"]), actor)
                parse_emoji(item["display"], guild)
            message = None
            self.store.disable(guild.id, ident)
            try:
                if panel["message"]:
                    message = await channel.fetch_message(panel["message"])
                    if message.author.id != self.client.user.id:
                        raise OnboardingError("Pesan panel bukan milik Abud.")
                    await message.edit(
                        embed=panel_embed(panel, mappings, active=False),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    message = await channel.send(
                        embed=panel_embed(panel, mappings, active=False),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    # Save the new message before seeding, so failed publishes can retry it.
                    self.store.remember(guild.id, ident, channel_id, message.id)
                for item in mappings:
                    await message.add_reaction(item["display"])
                self.store.activate(guild.id, ident, channel_id, message.id)
                await message.edit(embed=panel_embed(panel, mappings, active=True))
            except BaseException:
                self.store.disable(guild.id, ident)
                raise
            return message

    async def disable(self, guild, ident):
        async with self.lock:
            if self.store is None:
                return
            panel = self.store.panel(guild.id, ident)
            self.store.disable(guild.id, ident)
            if panel["message"]:
                try:
                    channel = self.channel(guild, panel["channel"])
                    message = await channel.fetch_message(panel["message"])
                    await message.edit(
                        embed=panel_embed(
                            panel, self.store.mappings(ident), active=False
                        )
                    )
                except discord.NotFound:
                    pass
                except (discord.HTTPException, OnboardingError) as error:
                    self.failure(error)

    async def withdraw(self, guild, member, claim):
        role = guild.get_role(claim["role"])
        owned = self.store.owned(guild.id, member.id, claim["role"])
        last = self.store.references(guild.id, member.id, claim["role"]) <= 1
        if owned and last and role and any(r.id == role.id for r in member.roles):
            self.check_role(guild, role)
            await member.remove_roles(
                role, reason="Abud: reaction role withdrawn", atomic=True
            )
        self.store.unclaim(claim["panel"], member.id, claim["emoji"])
        if owned and last:
            self.store.release(guild.id, member.id, claim["role"])

    async def reaction(self, payload, *, added):
        if (
            not self.enabled
            or self.store is None
            or not payload.guild_id
            or payload.user_id == self.client.user.id
            or getattr(payload, "burst", False)
        ):
            return
        try:
            async with self.lock:
                if self.store is None:
                    return
                panel = self.store.by_message(payload.guild_id, payload.message_id)
                if not panel or payload.channel_id != panel["channel"]:
                    return
                guild = self.client.get_guild(payload.guild_id)
                if not guild:
                    return
                key = emoji_key(payload.emoji)
                claims = self.store.claims(panel["id"], payload.user_id)
                existing = next((c for c in claims if c["emoji"] == key), None)
                mapping = next(
                    (m for m in self.store.mappings(panel["id"]) if m["emoji"] == key),
                    None,
                )
                if (added and mapping is None) or (not added and existing is None):
                    return
                # Fetch fresh membership/roles; raw removals do not carry a Member object.
                member = await guild.fetch_member(payload.user_id)
                if member.bot or (added and member.pending):
                    return
                if not added:
                    await self.withdraw(guild, member, existing)
                    return
                self.channel(
                    guild,
                    panel["channel"],
                    reactions=True,
                    single=panel["mode"] == "single",
                )
                role = self.check_role(guild, guild.get_role(mapping["role"]))
                old_claims = (
                    [c for c in claims if c["emoji"] != key]
                    if panel["mode"] == "single"
                    else []
                )
                # Validate any role we may remove before adding the new choice.
                for claim in (
                    [existing] if existing and existing["role"] != role.id else []
                ) + old_claims:
                    old_role = guild.get_role(claim["role"])
                    if old_role and self.store.owned(guild.id, member.id, old_role.id):
                        self.check_role(guild, old_role)
                owned = not any(r.id == role.id for r in member.roles)
                if owned:
                    await member.add_roles(
                        role, reason="Abud: reaction role selected", atomic=True
                    )
                try:
                    if existing and existing["role"] != role.id:
                        await self.withdraw(guild, member, existing)
                    self.store.claim(
                        panel["id"], guild.id, member.id, key, role.id, owned=owned
                    )
                except BaseException:
                    if owned:
                        try:
                            await member.remove_roles(
                                role,
                                reason="Abud: undo unrecorded reaction role",
                                atomic=True,
                            )
                        except discord.HTTPException as rollback_error:
                            self.failure(rollback_error)
                    raise
                if old_claims:
                    message = await guild.get_channel(panel["channel"]).fetch_message(
                        panel["message"]
                    )
                    for claim in old_claims:
                        await self.withdraw(guild, member, claim)
                        old_mapping = next(
                            (
                                m
                                for m in self.store.mappings(panel["id"])
                                if m["emoji"] == claim["emoji"]
                            ),
                            None,
                        )
                        if old_mapping:
                            await message.remove_reaction(
                                old_mapping["display"], member
                            )
        except discord.NotFound:
            # Left guild/deleted message: no speculative changes to another member/message.
            return
        except Exception as error:  # noqa: BLE001 - never expose tokens or raw provider errors in Discord
            self.failure(error)

    async def invalidated(self, guild_id, message_ids):
        if not self.enabled or self.store is None or not guild_id:
            return
        panels = []
        async with self.lock:
            if self.store is None:
                return
            for ident in message_ids:
                panel = self.store.by_message(guild_id, ident)
                if panel:
                    self.store.disable(guild_id, panel["id"])
                    panels.append(panel["id"])
        guild = self.client.get_guild(guild_id)
        if guild:
            for ident in panels:
                try:
                    await self.disable(guild, ident)
                except OnboardingError:
                    pass  # Administrator may have deleted this config concurrently.

    async def member_left(self, guild_id, member_id):
        if self.store:
            async with self.lock:
                if self.store:
                    self.store.forget_member(guild_id, member_id)
