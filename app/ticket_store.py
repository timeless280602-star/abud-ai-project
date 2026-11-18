"""Durable support ticket state, reservations and lifecycle audit history."""

import sqlite3
import time
from pathlib import Path
from uuid import uuid4

KINDS = {"community": "Bantuan Komunitas", "store": "Kendala Toko", "report": "Laporan"}
ACTIVE = ("creating", "open", "claimed", "closing", "reopening", "error")


class TicketError(Exception):
    """Safe to display inside a Discord interaction."""


class TicketStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
          guild INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, category INTEGER NOT NULL,
          support INTEGER NOT NULL, log INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
          panel_channel INTEGER, panel_message INTEGER);
        CREATE TABLE IF NOT EXISTS tickets (
          id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL, owner INTEGER NOT NULL,
          support INTEGER NOT NULL, log INTEGER NOT NULL, category INTEGER NOT NULL,
          kind TEXT NOT NULL, summary TEXT NOT NULL, nonce TEXT NOT NULL,
          channel INTEGER UNIQUE, control INTEGER, state TEXT NOT NULL,
          claimant INTEGER, created REAL NOT NULL, updated REAL NOT NULL,
          closer INTEGER, reason TEXT NOT NULL DEFAULT '');
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_ticket ON tickets(guild,owner)
          WHERE state IN ('creating','open','claimed','closing','reopening','error');
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ticket INTEGER NOT NULL,
          action TEXT NOT NULL, actor INTEGER NOT NULL, happened REAL NOT NULL,
          reason TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS ticket_events ON events(ticket,id DESC);
        """)

    def settings(self, guild):
        row = self.db.execute(
            "SELECT * FROM settings WHERE guild=?", (guild,)
        ).fetchone()
        if not row:
            raise TicketError("Ticket Support belum dikonfigurasi oleh admin server.")
        return row

    def configure(self, guild, enabled, category, support, log, title, description):
        if not 1 <= len(title) <= 100 or not 1 <= len(description) <= 1500:
            raise TicketError(
                "Judul panel 1–100 karakter dan deskripsi 1–1500 karakter."
            )
        with self.db:
            self.db.execute(
                "INSERT INTO settings(guild,enabled,category,support,log,title,description) VALUES(?,?,?,?,?,?,?) ON CONFLICT(guild) DO UPDATE SET enabled=excluded.enabled,category=excluded.category,support=excluded.support,log=excluded.log,title=excluded.title,description=excluded.description",
                (guild, int(enabled), category, support, log, title, description),
            )

    def panel(self, guild, channel, message):
        with self.db:
            self.db.execute(
                "UPDATE settings SET panel_channel=?,panel_message=? WHERE guild=?",
                (channel, message, guild),
            )

    def get(self, guild, ident):
        row = self.db.execute(
            "SELECT * FROM tickets WHERE id=? AND guild=?", (ident, guild)
        ).fetchone()
        if not row:
            raise TicketError("Tiket tidak ditemukan di server ini.")
        return row

    def by_channel(self, guild, channel):
        return self.db.execute(
            "SELECT * FROM tickets WHERE guild=? AND channel=?", (guild, channel)
        ).fetchone()

    def active(self, guild, owner):
        return self.db.execute(
            "SELECT * FROM tickets WHERE guild=? AND owner=? AND state IN ('creating','open','claimed','closing','reopening','error')",
            (guild, owner),
        ).fetchone()

    def reserve(self, guild, owner, kind, summary):
        settings = self.settings(guild)
        if not settings["enabled"]:
            raise TicketError("Pembukaan tiket sedang dijeda oleh admin.")
        if kind not in KINDS or not 10 <= len(summary.strip()) <= 1200:
            raise TicketError(
                "Pilih jenis bantuan dan tulis ringkasan 10–1200 karakter."
            )
        if self.active(guild, owner):
            raise TicketError(
                "Kamu sudah memiliki satu tiket aktif. Selesaikan tiket itu dulu."
            )
        now = time.time()
        previous = self.db.execute(
            "SELECT max(created) FROM tickets WHERE guild=? AND owner=?", (guild, owner)
        ).fetchone()[0]
        if previous is not None and now - previous < 60:
            raise TicketError(
                "Tunggu 60 detik sejak pembukaan terakhir sebelum membuat tiket baru."
            )
        count = self.db.execute(
            "SELECT count(*) FROM tickets WHERE guild=? AND state NOT IN ('deleted','failed')",
            (guild,),
        ).fetchone()[0]
        if count >= 50:
            raise TicketError(
                "Batas 50 channel tiket tercapai. Admin perlu membersihkan arsip lama terlebih dahulu."
            )
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO tickets(guild,owner,support,log,category,kind,summary,nonce,state,created,updated) VALUES(?,?,?,?,?,?,?,?,'creating',?,?)",
                (
                    guild,
                    owner,
                    settings["support"],
                    settings["log"],
                    settings["category"],
                    kind,
                    summary.strip(),
                    uuid4().hex,
                    now,
                    now,
                ),
            )
            self.event(cursor.lastrowid, "requested", owner)
        return self.get(guild, cursor.lastrowid)

    def event(self, ident, action, actor, reason=""):
        self.db.execute(
            "INSERT INTO events(ticket,action,actor,happened,reason) VALUES(?,?,?,?,?)",
            (ident, action, actor, time.time(), reason[:500]),
        )

    def attach(self, guild, ident, channel, control=None):
        with self.db:
            self.db.execute(
                "UPDATE tickets SET channel=?,control=COALESCE(?,control),updated=? WHERE guild=? AND id=?",
                (channel, control, time.time(), guild, ident),
            )

    def state(self, guild, ident, state, actor, reason="", claimant=None):
        current = self.get(guild, ident)
        if state in ("closing", "closed"):
            claimant = current["claimant"]
        if state not in (*ACTIVE, "closed", "deleted", "failed"):
            raise ValueError("Unknown ticket state")
        with self.db:
            try:
                self.db.execute(
                    "UPDATE tickets SET state=?,claimant=?,updated=?,closer=CASE WHEN ? IN ('closing','closed') THEN ? ELSE closer END,reason=CASE WHEN ? IN ('closing','closed') THEN ? ELSE reason END WHERE guild=? AND id=?",
                    (
                        state,
                        claimant,
                        time.time(),
                        state,
                        actor,
                        state,
                        reason[:500],
                        guild,
                        ident,
                    ),
                )
            except sqlite3.IntegrityError:
                raise TicketError(
                    "Pembuka sudah memiliki tiket aktif lain. Tiket lama belum bisa dibuka kembali."
                ) from None
            self.event(ident, state, actor, reason)
        return self.get(guild, ident)

    def history(self, guild, page=1):
        return self.db.execute(
            "SELECT * FROM tickets WHERE guild=? ORDER BY id DESC LIMIT 10 OFFSET ?",
            (guild, (page - 1) * 10),
        ).fetchall()

    def events(self, ident):
        return self.db.execute(
            "SELECT * FROM events WHERE ticket=? ORDER BY id DESC LIMIT 20", (ident,)
        ).fetchall()

    def protected(self):
        return frozenset(
            r[0]
            for r in self.db.execute(
                "SELECT channel FROM tickets WHERE channel IS NOT NULL"
            )
        )

    def reserved(self):
        return frozenset(
            (r[0], r[1])
            for r in self.db.execute(
                "SELECT guild,support FROM settings UNION SELECT guild,support FROM tickets"
            )
        )

    def tracked(self):
        return self.db.execute(
            "SELECT * FROM tickets WHERE channel IS NOT NULL AND state NOT IN ('deleted','failed')"
        ).fetchall()

    def pending(self):
        return self.db.execute(
            "SELECT * FROM tickets WHERE state IN ('creating','closing','reopening')"
        ).fetchall()

    def close(self):
        self.db.close()
