"""Welcome/panel persistence and role/emoji policy, separate from leveling."""

import re
import sqlite3
import unicodedata
from pathlib import Path

import discord

DEFAULT_WELCOME = "Halo {member}, selamat datang di **{server}**! Kenalkan dirimu dan baca aturan komunitas ya."
SAFE_PERMISSIONS = discord.Permissions(
    **{
        name: True
        for name in (
            "view_channel",
            "send_messages",
            "send_messages_in_threads",
            "read_message_history",
            "add_reactions",
            "embed_links",
            "attach_files",
            "use_external_emojis",
            "use_external_stickers",
            "connect",
            "speak",
            "stream",
            "use_voice_activation",
            "change_nickname",
            "use_application_commands",
            "request_to_speak",
            "create_public_threads",
            "create_private_threads",
            "send_voice_messages",
            "send_polls",
            "use_soundboard",
            "use_external_sounds",
            "use_embedded_activities",
            "use_external_apps",
        )
    }
).value


class OnboardingError(Exception):
    """Safe error text for administrators."""


def emoji_key(emoji):
    ident = getattr(emoji, "id", None)
    return (
        f"c:{ident}"
        if ident
        else "u:" + str(emoji).replace("\ufe0f", "").replace("\ufe0e", "")
    )


def parse_emoji(text, guild):
    text = text.strip()
    # Discord's :name: shorthand is not expanded by a plain web input.
    # Resolve only unique, usable emojis from this guild, never external IDs.
    shorthand = re.fullmatch(r":([A-Za-z0-9_]{2,32}):", text)
    if shorthand:
        matches = [emoji for emoji in guild.emojis
                   if emoji.name.casefold() == shorthand.group(1).casefold()
                   and emoji.is_usable()]
        if len(matches) == 1:
            return emoji_key(matches[0]), str(matches[0])
        if len(matches) > 1:
            raise OnboardingError("Nama custom emoji ganda. Pilih emoji dari daftar server.")
        raise OnboardingError("Custom emoji tidak ditemukan atau tidak bisa digunakan Abud. Pilih emoji dari daftar server, atau gunakan emoji Unicode seperti 🎮.")
    if re.fullmatch(r"<a?:\w{2,32}:\d{1,22}>", text):
        ident = discord.PartialEmoji.from_str(text).id
        emoji = guild.get_emoji(ident)
        if not emoji or not emoji.is_usable():
            raise OnboardingError(
                "Custom emoji harus berasal dari server ini dan bisa digunakan Abud."
            )
        return emoji_key(emoji), str(emoji)
    if (
        not text
        or len(text) > 64
        or any(c.isspace() for c in text)
        or not any(unicodedata.category(c) == "So" or c == "\u20e3" for c in text)
    ):
        raise OnboardingError(
            "Pilih satu emoji dari daftar, atau tempel emoji Unicode (mis. 🎮). Untuk custom emoji gunakan :nama_emoji: dari server ini."
        )
    if any(c.isalpha() or c in "<>:@" for c in text):
        raise OnboardingError("Format emoji tidak valid.")
    return emoji_key(text), text


def blocked_permission_names(value):
    blocked = value & ~SAFE_PERMISSIONS
    names = [name.replace("_", " ").title()
             for name, enabled in discord.Permissions(blocked) if enabled]
    return ", ".join(names) or "Izin khusus"


def validate_role(guild, role, actor=None):
    if (
        not role
        or role.guild.id != guild.id
        or role.is_default()
        or role.managed
        or not guild.me
        or not guild.me.guild_permissions.manage_roles
        or role >= guild.me.top_role
    ):
        raise OnboardingError(
            "Pilih role biasa di bawah role tertinggi Abud. Abud memerlukan Manage Roles."
        )
    if actor and actor.id != guild.owner_id and role >= actor.top_role:
        raise OnboardingError(
            "Role pilihan harus berada di bawah role tertinggi admin yang mengaturnya."
        )
    if role.permissions.value & ~SAFE_PERMISSIONS:
        raise OnboardingError(
            "Role dengan izin administrasi/moderasi atau izin khusus tidak boleh dipilih sendiri: " + blocked_permission_names(role.permissions.value) + "."
        )
    for channel in guild.channels:
        allow, _ = channel.overwrites_for(role).pair()
        if allow.value & ~SAFE_PERMISSIONS:
            raise OnboardingError(
                "Role ini memberi izin khusus lewat channel overwrite: " + blocked_permission_names(allow.value) + " (channel " + channel.name + ")."
            )
    return role


class OnboardingStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS welcome (
          guild INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, channel INTEGER,
          template TEXT NOT NULL, ping INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS panels (
          id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL, title TEXT NOT NULL,
          description TEXT NOT NULL, mode TEXT NOT NULL, channel INTEGER, message INTEGER UNIQUE,
          enabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS mappings (
          panel INTEGER NOT NULL, emoji TEXT NOT NULL, display TEXT NOT NULL, role INTEGER NOT NULL,
          PRIMARY KEY(panel,emoji), UNIQUE(panel,role));
        CREATE TABLE IF NOT EXISTS claims (
          panel INTEGER NOT NULL, guild INTEGER NOT NULL, member INTEGER NOT NULL,
          emoji TEXT NOT NULL, role INTEGER NOT NULL, PRIMARY KEY(panel,member,emoji));
        CREATE INDEX IF NOT EXISTS claims_role ON claims(guild,member,role);
        CREATE TABLE IF NOT EXISTS welcomed (
          guild INTEGER NOT NULL, member INTEGER NOT NULL, joined TEXT NOT NULL,
          PRIMARY KEY(guild,member));
        CREATE TABLE IF NOT EXISTS owned (
          guild INTEGER NOT NULL, member INTEGER NOT NULL, role INTEGER NOT NULL,
          PRIMARY KEY(guild,member,role));
        """)

    def welcome(self, guild):
        row = self.db.execute(
            "SELECT * FROM welcome WHERE guild=?", (guild,)
        ).fetchone()
        return (
            dict(row)
            if row
            else {
                "guild": guild,
                "enabled": 0,
                "channel": None,
                "template": DEFAULT_WELCOME,
                "ping": 0,
            }
        )

    def set_welcome(self, guild, enabled, channel, template, ping):
        if not 1 <= len(template) <= 1500:
            raise OnboardingError("Pesan welcome harus berisi 1–1500 karakter.")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO welcome VALUES(?,?,?,?,?)",
                (guild, int(enabled), channel, template, int(ping)),
            )

    def create(self, guild, title, description, mode):
        if (
            mode not in ("single", "multiple")
            or not 1 <= len(title) <= 100
            or len(description) > 1500
        ):
            raise OnboardingError(
                "Judul 1–100 karakter, deskripsi maksimal 1500, mode single/multiple."
            )
        with self.db:
            if len(self.panels(guild)) >= 10:
                raise OnboardingError(
                    "Maksimal 10 panel per server. Hapus panel lama dulu."
                )
            return self.db.execute(
                "INSERT INTO panels(guild,title,description,mode) VALUES(?,?,?,?)",
                (guild, title, description, mode),
            ).lastrowid

    def welcomed(self, guild, member, joined):
        row = self.db.execute(
            "SELECT joined FROM welcomed WHERE guild=? AND member=?", (guild, member)
        ).fetchone()
        return bool(row and row[0] == joined)

    def mark_welcomed(self, guild, member, joined):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO welcomed VALUES(?,?,?)", (guild, member, joined)
            )

    def panels(self, guild):
        return self.db.execute(
            "SELECT * FROM panels WHERE guild=? ORDER BY id", (guild,)
        ).fetchall()

    def panel(self, guild, ident):
        row = self.db.execute(
            "SELECT * FROM panels WHERE guild=? AND id=?", (guild, ident)
        ).fetchone()
        if not row:
            raise OnboardingError("Panel tidak ditemukan di server ini.")
        return row

    def by_message(self, guild, message):
        return self.db.execute(
            "SELECT * FROM panels WHERE guild=? AND message=? AND enabled=1",
            (guild, message),
        ).fetchone()

    def mappings(self, panel):
        return self.db.execute(
            "SELECT * FROM mappings WHERE panel=? ORDER BY rowid", (panel,)
        ).fetchall()

    def bind(self, guild, panel, emoji, display, role):
        row = self.panel(guild, panel)
        if row["enabled"]:
            raise OnboardingError(
                "Nonaktifkan panel sebelum mengubah pasangan emoji–role."
            )
        with self.db:
            if len(self.mappings(panel)) >= 20 and not any(
                m["emoji"] == emoji for m in self.mappings(panel)
            ):
                raise OnboardingError("Maksimal 20 pilihan per panel.")
            try:
                self.db.execute(
                    "INSERT INTO mappings VALUES(?,?,?,?) ON CONFLICT(panel,emoji) DO UPDATE SET display=excluded.display,role=excluded.role",
                    (panel, emoji, display, role),
                )
            except sqlite3.IntegrityError:
                raise OnboardingError(
                    "Role sudah dipakai pada emoji lain di panel ini."
                ) from None

    def unbind(self, guild, panel, emoji):
        if self.panel(guild, panel)["enabled"]:
            raise OnboardingError(
                "Nonaktifkan panel sebelum mengubah pasangan emoji–role."
            )
        with self.db:
            self.db.execute(
                "DELETE FROM mappings WHERE panel=? AND emoji=?", (panel, emoji)
            )

    def remember(self, guild, panel, channel, message):
        with self.db:
            self.db.execute(
                "UPDATE panels SET channel=?,message=? WHERE id=? AND guild=?",
                (channel, message, panel, guild),
            )

    def activate(self, guild, panel, channel, message):
        self.panel(guild, panel)
        with self.db:
            self.db.execute(
                "UPDATE panels SET channel=?,message=?,enabled=1 WHERE id=? AND guild=?",
                (channel, message, panel, guild),
            )

    def disable(self, guild, panel):
        self.panel(guild, panel)
        with self.db:
            self.db.execute(
                "UPDATE panels SET enabled=0 WHERE id=? AND guild=?", (panel, guild)
            )

    def delete(self, guild, panel):
        self.panel(guild, panel)
        with self.db:
            self.db.execute("DELETE FROM panels WHERE guild=? AND id=?", (guild, panel))
            self.db.execute("DELETE FROM mappings WHERE panel=?", (panel,))
            self.db.execute("DELETE FROM claims WHERE panel=?", (panel,))

    def claims(self, panel, member):
        return self.db.execute(
            "SELECT * FROM claims WHERE panel=? AND member=?", (panel, member)
        ).fetchall()

    def claim(self, panel, guild, member, emoji, role, *, owned=False):
        with self.db:
            self.db.execute(
                "INSERT INTO claims VALUES(?,?,?,?,?) ON CONFLICT(panel,member,emoji) DO UPDATE SET role=excluded.role",
                (panel, guild, member, emoji, role),
            )
            if owned:
                self.db.execute(
                    "INSERT OR IGNORE INTO owned VALUES(?,?,?)", (guild, member, role)
                )

    def unclaim(self, panel, member, emoji):
        with self.db:
            self.db.execute(
                "DELETE FROM claims WHERE panel=? AND member=? AND emoji=?",
                (panel, member, emoji),
            )

    def owned(self, guild, member, role):
        return bool(
            self.db.execute(
                "SELECT 1 FROM owned WHERE guild=? AND member=? AND role=?",
                (guild, member, role),
            ).fetchone()
        )

    def references(self, guild, member, role):
        return self.db.execute(
            "SELECT count(*) FROM claims WHERE guild=? AND member=? AND role=?",
            (guild, member, role),
        ).fetchone()[0]

    def release(self, guild, member, role):
        with self.db:
            self.db.execute(
                "DELETE FROM owned WHERE guild=? AND member=? AND role=?",
                (guild, member, role),
            )

    def forget_member(self, guild, member):
        with self.db:
            self.db.execute(
                "DELETE FROM claims WHERE guild=? AND member=?", (guild, member)
            )
            self.db.execute(
                "DELETE FROM owned WHERE guild=? AND member=?", (guild, member)
            )

    def close(self):
        self.db.close()
