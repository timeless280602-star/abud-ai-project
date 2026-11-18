"""Durable creator subscriptions; no Discord or provider dependencies."""

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


class NotificationError(Exception):
    """Safe to display to an administrator."""


def parse_account(platform, value):
    value = value.strip()
    if platform == "youtube" and re.fullmatch(r"UC[\w-]{22}", value):
        return "id", value
    if value.startswith("@"):
        value = (
            "https://www.youtube.com/"
            if platform == "youtube"
            else "https://www.tiktok.com/"
        ) + value
    parsed = urlsplit(value if "://" in value else "https://" + value)
    hosts = {
        "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com"},
        "tiktok": {"tiktok.com", "www.tiktok.com"},
    }
    try:
        port = parsed.port
    except ValueError:
        raise NotificationError("Port URL tidak valid.") from None
    if (
        platform not in hosts
        or parsed.scheme != "https"
        or parsed.hostname not in hosts[platform]
        or port not in (None, 443)
        or parsed.username
    ):
        raise NotificationError(
            "Gunakan link channel HTTPS YouTube/TikTok atau @handle yang sesuai platform."
        )
    parts = unquote(parsed.path).strip("/").split("/")
    if parts[0].startswith("@") and len(parts[0]) > 1:
        name = parts[0][1:]
        if not re.fullmatch(
            r"[\w.\-]{1,100}" if platform == "youtube" else r"[A-Za-z0-9_.]{1,100}",
            name,
        ):
            raise NotificationError("Handle channel tidak valid.")
        return "forHandle", "@" + name if platform == "youtube" else name.lower()
    if platform == "youtube" and len(parts) >= 2:
        if parts[0] == "channel" and re.fullmatch(r"UC[\w-]{22}", parts[1]):
            return "id", parts[1]
        if parts[0] == "user" and re.fullmatch(r"[\w.\-]{1,100}", parts[1]):
            return "forUsername", parts[1]
    raise NotificationError(
        "Gunakan link /@handle, /channel/UC…, atau /user/…; link video dan /c/ tidak didukung."
    )


@dataclass(frozen=True)
class Creator:
    platform: str
    account: str
    title: str
    uploads: str = ""


@dataclass(frozen=True)
class Event:
    platform: str
    account: str
    video: str
    kind: str
    title: str
    occurred: float

    @property
    def url(self):
        if self.platform == "youtube":
            return "https://www.youtube.com/watch?v=" + self.video
        return f"https://www.tiktok.com/@{self.account}/" + (
            "live" if self.kind == "live" else "video/" + self.video
        )


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
          id INTEGER PRIMARY KEY, guild INTEGER NOT NULL, destination INTEGER NOT NULL,
          platform TEXT NOT NULL, account TEXT NOT NULL, title TEXT NOT NULL,
          uploads TEXT NOT NULL, ping TEXT NOT NULL, events TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1, since REAL NOT NULL,
          UNIQUE(guild, platform, account));
        CREATE TABLE IF NOT EXISTS deliveries (
          subscription INTEGER NOT NULL, video TEXT NOT NULL, kind TEXT NOT NULL,
          delivered REAL NOT NULL, PRIMARY KEY(subscription, video, kind));
        CREATE TABLE IF NOT EXISTS pending (
          account TEXT NOT NULL, video TEXT NOT NULL, expires REAL NOT NULL,
          PRIMARY KEY(account,video));
        """)

    def add(self, guild, destination, creator, ping, events):
        self.validate(ping, events)
        with self.db:
            if (
                self.db.execute(
                    "SELECT count(*) FROM subscriptions WHERE guild=? AND platform=?",
                    (guild, creator.platform),
                ).fetchone()[0]
                >= 10
            ):
                raise NotificationError(
                    "Maksimal 10 akun per platform untuk setiap server. Hapus salah satu dulu."
                )
            try:
                cursor = self.db.execute(
                    "INSERT INTO subscriptions(guild,destination,platform,account,title,uploads,ping,events,since) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        guild,
                        destination,
                        creator.platform,
                        creator.account,
                        creator.title,
                        creator.uploads,
                        ping,
                        events,
                        time.time(),
                    ),
                )
            except sqlite3.IntegrityError:
                raise NotificationError(
                    "Akun sudah terdaftar di server ini. Gunakan /notify edit."
                ) from None
            return cursor.lastrowid

    @staticmethod
    def validate(ping, events):
        if ping not in ("none", "here", "everyone") or events not in (
            "live",
            "post",
            "both",
        ):
            raise NotificationError("Pilihan ping atau jenis notifikasi tidak valid.")

    def list(self, guild=None):
        return self.db.execute(
            "SELECT * FROM subscriptions"
            + (" WHERE guild=?" if guild is not None else "")
            + " ORDER BY id",
            (guild,) if guild is not None else (),
        ).fetchall()

    def get(self, guild, ident):
        row = self.db.execute(
            "SELECT * FROM subscriptions WHERE id=? AND guild=?", (ident, guild)
        ).fetchone()
        if not row:
            raise NotificationError("ID langganan tidak ditemukan di server ini.")
        return row

    def edit(self, guild, ident, destination, ping, events, enabled):
        old = self.get(guild, ident)
        self.validate(ping, events)
        since = time.time() if enabled and not old["enabled"] else old["since"]
        with self.db:
            self.db.execute(
                "UPDATE subscriptions SET destination=?,ping=?,events=?,enabled=?,since=? WHERE id=? AND guild=?",
                (destination, ping, events, int(enabled), since, ident, guild),
            )

    def remove(self, guild, ident):
        self.get(guild, ident)
        with self.db:
            self.db.execute(
                "DELETE FROM subscriptions WHERE id=? AND guild=?", (ident, guild)
            )
            self.db.execute("DELETE FROM deliveries WHERE subscription=?", (ident,))

    def wants(self, row, event):
        return (
            row["enabled"]
            and row["platform"] == event.platform
            and row["account"] == event.account
            and row["events"] in ("both", event.kind)
            and event.occurred >= row["since"]
            and not self.db.execute(
                "SELECT 1 FROM deliveries WHERE subscription=? AND video=? AND kind=?",
                (row["id"], event.video, event.kind),
            ).fetchone()
        )

    def delivered(self, row, event):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?)",
                (row["id"], event.video, event.kind, time.time()),
            )

    def pending(self, account):
        with self.db:
            self.db.execute("DELETE FROM pending WHERE expires < ?", (time.time(),))
        return [
            r[0]
            for r in self.db.execute(
                "SELECT video FROM pending WHERE account=?", (account,)
            )
        ]

    def watch(self, account, video, expires):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO pending VALUES(?,?,?)",
                (account, video, expires),
            )

    def unwatch(self, account, video):
        with self.db:
            self.db.execute(
                "DELETE FROM pending WHERE account=? AND video=?", (account, video)
            )

    def close(self):
        self.db.close()
