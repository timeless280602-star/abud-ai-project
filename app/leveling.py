"""Persistent per-guild XP, cooldowns and duplicate suppression. No role rewards."""

import hashlib
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHAT_CAP = 1000
VOICE_CAP = 600
WIB = timezone(timedelta(hours=7))


class LevelingError(Exception):
    """Safe administrator/member-facing error."""


def level(total):
    return math.isqrt(max(0, total) // 100)


def progress(total):
    current = level(total)
    floor, ceiling = 100 * current * current, 100 * (current + 1) ** 2
    return current, total - floor, ceiling - floor


def fingerprint(content):
    text = unicodedata.normalize("NFKC", content).casefold().strip()
    if text.startswith(("/", "!", "?", ".", "$")):
        return None
    text = re.sub(r"https?://\S+|<@!?[0-9]+>|<@&[0-9]+>|<#\d+>|<a?:\w+:\d+>", "", text)
    words = "".join(c for c in text if c.isalnum())
    if len(words) < 8 or len(set(words)) < 4 or not any(c.isalpha() for c in words):
        return None
    return hashlib.sha256(words.encode()).hexdigest()


@dataclass(frozen=True)
class Award:
    guild: int
    member: int
    before: int
    after: int
    amount: int

    @property
    def leveled(self):
        return level(self.after) > level(self.before)


class LevelStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS guilds (
          guild INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
          chat INTEGER NOT NULL DEFAULT 1, voice INTEGER NOT NULL DEFAULT 1,
          announcement INTEGER);
        CREATE TABLE IF NOT EXISTS excluded (
          guild INTEGER NOT NULL, channel INTEGER NOT NULL, PRIMARY KEY(guild,channel));
        CREATE TABLE IF NOT EXISTS members (
          guild INTEGER NOT NULL, member INTEGER NOT NULL, name TEXT NOT NULL,
          xp INTEGER NOT NULL DEFAULT 0, chat_xp INTEGER NOT NULL DEFAULT 0,
          voice_xp INTEGER NOT NULL DEFAULT 0, last_chat REAL, last_voice REAL,
          day TEXT NOT NULL DEFAULT '', daily_chat INTEGER NOT NULL DEFAULT 0,
          daily_voice INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild,member));
        CREATE INDEX IF NOT EXISTS members_rank ON members(guild,xp DESC,member ASC);
        CREATE TABLE IF NOT EXISTS messages (
          guild INTEGER NOT NULL, member INTEGER NOT NULL, hash TEXT NOT NULL,
          received REAL NOT NULL, PRIMARY KEY(guild,member,hash));
        """)

    def config(self, guild):
        row = self.db.execute("SELECT * FROM guilds WHERE guild=?", (guild,)).fetchone()
        return (
            dict(row)
            if row
            else {
                "guild": guild,
                "enabled": 0,
                "chat": 1,
                "voice": 1,
                "announcement": None,
            }
        )

    def configure(self, guild, enabled, chat, voice, announcement):
        with self.db:
            self.db.execute(
                "INSERT INTO guilds VALUES(?,?,?,?,?) ON CONFLICT(guild) DO UPDATE SET enabled=excluded.enabled,chat=excluded.chat,voice=excluded.voice,announcement=excluded.announcement",
                (guild, int(enabled), int(chat), int(voice), announcement),
            )

    def excludes(self, guild):
        return [
            r[0]
            for r in self.db.execute(
                "SELECT channel FROM excluded WHERE guild=? ORDER BY channel", (guild,)
            )
        ]

    def exclude(self, guild, channel, enabled):
        with self.db:
            if enabled:
                self.db.execute(
                    "INSERT OR IGNORE INTO excluded VALUES(?,?)", (guild, channel)
                )
            else:
                self.db.execute(
                    "DELETE FROM excluded WHERE guild=? AND channel=?", (guild, channel)
                )

    def member(self, guild, member, name="Member"):
        row = self.db.execute(
            "SELECT * FROM members WHERE guild=? AND member=?", (guild, member)
        ).fetchone()
        return (
            dict(row)
            if row
            else {
                "guild": guild,
                "member": member,
                "name": name,
                "xp": 0,
                "chat_xp": 0,
                "voice_xp": 0,
            }
        )

    def rank(self, guild, member):
        row = self.member(guild, member)
        if row["xp"] == 0:
            return None
        return (
            1
            + self.db.execute(
                "SELECT count(*) FROM members WHERE guild=? AND (xp>? OR (xp=? AND member<?))",
                (guild, row["xp"], row["xp"], member),
            ).fetchone()[0]
        )

    def leaderboard(self, guild, page=1):
        return self.db.execute(
            "SELECT * FROM members WHERE guild=? AND xp>0 ORDER BY xp DESC,member ASC LIMIT 10 OFFSET ?",
            (guild, (page - 1) * 10),
        ).fetchall()

    def count(self, guild):
        return self.db.execute(
            "SELECT count(*) FROM members WHERE guild=? AND xp>0", (guild,)
        ).fetchone()[0]

    def award(self, guild, member, name, kind, now, *, content=None, amount=5):
        if kind not in ("chat", "voice"):
            raise ValueError("Unknown XP source")
        config = self.config(guild)
        if not config["enabled"] or not config[kind]:
            return None
        digest = fingerprint(content or "") if kind == "chat" else None
        if kind == "chat" and digest is None:
            return None
        if not 1 <= amount <= 25:
            raise ValueError("Invalid XP amount")
        day = datetime.fromtimestamp(now, WIB).date().isoformat()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO members(guild,member,name) VALUES(?,?,?)",
                (guild, member, name[:100]),
            )
            row = self.db.execute(
                "SELECT * FROM members WHERE guild=? AND member=?", (guild, member)
            ).fetchone()
            last = row["last_" + kind]
            if last is not None and now - last < 60:
                return None
            if digest:
                seen = self.db.execute(
                    "SELECT received FROM messages WHERE guild=? AND member=? AND hash=?",
                    (guild, member, digest),
                ).fetchone()
                if seen and now - seen[0] < 600:
                    return None
            chat_today = row["daily_chat"] if row["day"] == day else 0
            voice_today = row["daily_voice"] if row["day"] == day else 0
            today, cap = (
                (chat_today, CHAT_CAP) if kind == "chat" else (voice_today, VOICE_CAP)
            )
            earned = min(amount, cap - today)
            if earned <= 0:
                return None
            self.db.execute(
                "UPDATE members SET name=?,xp=xp+?,chat_xp=chat_xp+?,voice_xp=voice_xp+?,last_chat=?,last_voice=?,day=?,daily_chat=?,daily_voice=? WHERE guild=? AND member=?",
                (
                    name[:100],
                    earned,
                    earned if kind == "chat" else 0,
                    earned if kind == "voice" else 0,
                    now if kind == "chat" else row["last_chat"],
                    now if kind == "voice" else row["last_voice"],
                    day,
                    chat_today + (earned if kind == "chat" else 0),
                    voice_today + (earned if kind == "voice" else 0),
                    guild,
                    member,
                ),
            )
            if digest:
                self.db.execute(
                    "INSERT OR REPLACE INTO messages VALUES(?,?,?,?)",
                    (guild, member, digest, now),
                )
                # Retain at most ten hashes per member, without storing message text.
                self.db.execute(
                    "DELETE FROM messages WHERE guild=? AND member=? AND hash NOT IN (SELECT hash FROM messages WHERE guild=? AND member=? ORDER BY received DESC LIMIT 10)",
                    (guild, member, guild, member),
                )
            return Award(guild, member, row["xp"], row["xp"] + earned, earned)

    def close(self):
        self.db.close()
