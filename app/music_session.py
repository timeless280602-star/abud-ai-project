"""Bounded, serialized music state with explicit end-event ownership."""

import asyncio
import copy
import random
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

from app.music_providers import LEGACY, source_for_link


class MusicError(Exception):
    """Actionable text that is safe to show to Discord users."""


def music_query(query, enabled=LEGACY):
    query = query.strip()
    if not query or len(query) > 300 or any(ord(c) < 32 for c in query):
        raise MusicError("Masukkan judul/link lagu, maksimal 300 karakter.")
    try:
        parsed = urlsplit(query)
        if not parsed.scheme:
            if parsed.netloc:
                raise ValueError()
            return query
        provider = source_for_link(query)
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or not provider):
            raise ValueError()
    except ValueError:
        raise MusicError("Gunakan judul lagu atau link HTTPS provider musik yang didukung.") from None
    if provider not in enabled:
        raise MusicError("Provider link ini belum diaktifkan oleh pengelola bot.")
    return query


def duration(milliseconds):
    seconds = max(0, milliseconds // 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    )


@dataclass(frozen=True)
class RequestedTrack:
    track: object
    requester: int
    allow_fallback: bool = False


class MusicSession:
    LIMIT = 100

    def __init__(self, player, owner, text_channel):
        self.player, self.owner, self.text_channel = player, owner, text_channel
        self.channel_id = player.channel.id
        self.queue = []
        self.history = deque(maxlen=20)
        self.current = None
        self.nonce = None
        self.repeat = "off"
        self.volume = 50
        self.failures = 0
        self.closed = False
        self.lock = asyncio.Lock()
        self.panel_lock = asyncio.Lock()
        self.idle_since = time.monotonic()

    async def enqueue(self, tracks, requester, *, allow_fallback=False):
        async with self.lock:
            if self.closed:
                raise MusicError("Sesi sudah ditutup. Gunakan /music play lagi.")
            if len(tracks) + len(self.queue) + bool(self.current) > self.LIMIT:
                raise MusicError(
                    "Batas antrean 100 lagu termasuk lagu aktif. Kurangi playlist/antrean dulu."
                )
            self.queue.extend(RequestedTrack(t, requester, allow_fallback) for t in tracks)
            self.idle_since = time.monotonic()
            if self.current is None:
                await self._next()

    async def _play(self, request):
        track = copy.copy(request.track)
        nonce = uuid4().hex
        track.extras = {"abud_music_nonce": nonce, "requester": request.requester}
        self.current, self.nonce = request, nonce
        self.idle_since = time.monotonic()
        try:
            await self.player.play(
                track, volume=self.volume, paused=False, add_history=False
            )
        except BaseException:
            self.current = self.nonce = None
            raise

    async def _next(self):
        self.current = self.nonce = None
        self.idle_since = time.monotonic()
        while self.queue and not self.closed:
            request = self.queue.pop(0)
            try:
                await self._play(request)
                return
            except Exception:  # noqa: BLE001 - provider errors are sanitized at this boundary
                self.failures += 1
                if self.failures >= 3:
                    self.repeat = "off"
                    await self.player.skip(force=True)
                    raise MusicError(
                        "Tiga lagu gagal diputar. Antrean ditahan; periksa sumber musik lalu coba /music skip."
                    ) from None
        if not self.closed:
            await self.player.skip(force=True)

    async def ended(self, nonce, reason):
        async with self.lock:
            if (
                self.closed
                or nonce != self.nonce
                or reason == "replaced"
                or not self.current
            ):
                return False
            finished = self.current
            if reason == "finished":
                self.failures = 0
                self.history.append(finished)
                if self.repeat == "track":
                    await self._play(finished)
                    return True
                if self.repeat == "queue":
                    self.queue.append(finished)
            elif reason == "loadFailed":
                self.failures += 1
                if self.failures >= 3:
                    self.current = self.nonce = None
                    self.idle_since = time.monotonic()
                    self.repeat = "off"
                    await self.player.skip(force=True)
                    raise MusicError(
                        "Pemutaran gagal tiga kali. Coba sumber lagu lain."
                    )
            await self._next()
            return True

    async def control(self, action, value=None):
        async with self.lock:
            if self.closed:
                raise MusicError("Sesi musik sudah ditutup.")
            if action in ("pause", "resume", "seek") and not self.current:
                raise MusicError("Belum ada lagu yang diputar.")
            if action == "pause":
                await self.player.pause(True)
                self.idle_since = time.monotonic()
            elif action == "resume":
                await self.player.pause(False)
                self.idle_since = time.monotonic()
            elif action == "skip":
                if self.current:
                    self.history.append(self.current)
                self.failures = 0
                await self._next()  # Explicit skip always bypasses repeat-track.
            elif action == "stop":
                self.queue.clear()
                self.repeat = "off"
                self.current = self.nonce = (
                    None  # Invalidate callbacks before stopping.
                )
                self.idle_since = time.monotonic()
                await self.player.skip(force=True)
            elif action == "previous":
                if not self.history:
                    raise MusicError("Belum ada riwayat lagu sebelumnya.")
                if self.current and len(self.queue) >= self.LIMIT - 1:
                    raise MusicError("Antrean penuh; hapus satu lagu dulu.")
                previous = self.history.pop()
                if self.current:
                    self.queue.insert(0, self.current)
                await self._play(previous)
            elif action == "shuffle":
                random.shuffle(self.queue)
            elif action == "repeat":
                if value not in ("off", "track", "queue"):
                    raise MusicError("Repeat harus off, track, atau queue.")
                self.repeat = value
            elif action == "volume":
                if not 0 <= value <= 100:
                    raise MusicError("Volume harus 0–100.")
                await self.player.set_volume(value)
                self.volume = value
            elif action == "seek":
                track = self.current.track
                if (
                    track.is_stream
                    or not track.is_seekable
                    or not 0 <= value * 1000 < track.length
                ):
                    raise MusicError(
                        "Posisi di luar durasi lagu, atau sumber ini tidak mendukung seek."
                    )
                await self.player.seek(value * 1000)
            elif action == "clear":
                self.queue.clear()
            elif action == "remove":
                if not 1 <= value <= len(self.queue):
                    raise MusicError("Nomor lagu tidak ditemukan di antrean.")
                self.queue.pop(value - 1)
            elif action == "move":
                source, destination = value
                if not 1 <= source <= len(self.queue) or not 1 <= destination <= len(
                    self.queue
                ):
                    raise MusicError("Nomor asal/tujuan di luar antrean.")
                self.queue.insert(destination - 1, self.queue.pop(source - 1))
            else:
                raise MusicError("Kontrol musik tidak dikenali.")
            return self

    async def close(self):
        async with self.lock:
            if self.closed:
                return
            self.closed = True
            self.current = self.nonce = None
            self.queue.clear()
            self.history.clear()
            await self.player.disconnect()
