"""Opt-in native playback of operator-approved local PCM WAV files.

No URL fetching, extractor, login, remote playlist or arbitrary user path.
The catalog and media must be mounted read-only from a trusted operator.
"""
import asyncio
import json
import logging
import re
import stat
import wave
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import discord

from app.music_providers import normalized
from app.music_session import MusicError

# client.run() configures the discord logger by default, not the root logger.
log = logging.getLogger("discord.abud.music_native")
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_BYTES = 512 * 1024 * 1024
MAX_TRACKS = 1000


@dataclass
class NativeTrack:
    identifier: str
    title: str
    author: str
    length: int
    path: Path = field(repr=False)
    fingerprint: tuple = field(repr=False)
    source: str = "native"
    uri: str | None = None
    artwork: str | None = None
    isrc: str | None = None
    is_stream: bool = False
    is_seekable: bool = False
    extras: dict = field(default_factory=dict)


class NativeCatalog:
    def __init__(self, root=Path("/app/music-library")):
        self.root = Path(root)

    def _regular(self, path, maximum):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size <= 0
                or info.st_size > maximum or path.resolve() != path.absolute()):
            raise ValueError("Invalid local file")
        return info

    def _load(self):
        manifest = self.root / "catalog.json"
        self._regular(manifest, 512 * 1024)
        rows = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_TRACKS:
            raise ValueError("Invalid local catalog")
        result = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("approved") is not True:
                continue
            key, title, artist = (row.get(k) for k in ("id", "title", "artist"))
            if (not isinstance(key, str) or not ID.fullmatch(key) or key in result
                    or not all(isinstance(v, str) and 0 < len(v.strip()) <= 200
                               and not any(ord(c) < 32 for c in v) for v in (title, artist))):
                raise ValueError("Invalid local track metadata")
            path = self.root / (key + ".wav")
            info = self._regular(path, MAX_BYTES)
            with wave.open(str(path), "rb") as wav:
                rate, frames = wav.getframerate(), wav.getnframes()
                if (wav.getcomptype() != "NONE" or wav.getnchannels() not in (1, 2)
                        or wav.getsampwidth() != 2 or rate not in (44100, 48000)
                        or not rate <= frames <= rate * 1800
                        or frames * wav.getnchannels() * 2 > info.st_size):
                    raise ValueError("Invalid local PCM WAV")
                length = frames * 1000 // rate
            result[key] = NativeTrack(key, title.strip(), artist.strip(), length, path,
                                      (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
        return result

    def load(self):
        try:
            return self._load()
        except (OSError, ValueError, TypeError, wave.Error, EOFError):
            raise MusicError("Katalog audio lokal belum siap.") from None

    def search(self, query):
        query = query.strip()
        if (not query or len(query) > 300 or any(ord(c) < 32 for c in query)
                or urlsplit(query).scheme or urlsplit(query).netloc):
            raise MusicError("Gunakan judul audio lokal yang disetujui; URL belum didukung.")
        q = normalized(query)
        if not q:
            raise MusicError("Masukkan judul audio lokal.")
        rows = list(self.load().values())
        exact = [t for t in rows if q in (normalized(t.identifier), normalized(t.title),
                 normalized(t.title + " " + t.author), normalized(t.author + " " + t.title))]
        others = [t for t in rows if t not in exact and q in normalized(t.title + " " + t.author)]
        return (exact + others)[:5]

    def validate(self, track):
        if not isinstance(track, NativeTrack):
            raise MusicError("Hanya audio lokal yang disetujui.")
        current = self.load().get(track.identifier)
        if not current or any(getattr(track, k) != getattr(current, k) for k in
                              ("title", "author", "length", "path", "fingerprint", "source",
                               "uri", "artwork", "is_stream", "is_seekable")):
            raise MusicError("Audio lokal berubah atau tidak lagi disetujui.")
        return current


class CountedAudio(discord.PCMVolumeTransformer):
    def __init__(self, source, volume):
        super().__init__(source, volume=volume)
        self.frames = 0

    def read(self):
        data = super().read()
        if data:
            self.frames += 1
        return data


class LocalPCM(discord.FFmpegPCMAudio):
    """Close the decoder pipe even when FFmpeg has already exited."""
    def cleanup(self):
        process = getattr(self, "_process", None)
        stdout = getattr(process, "stdout", None)
        try:
            super().cleanup()
        finally:
            if stdout is not None:
                stdout.close()


def local_audio(track, volume):
    # Force WAV demuxer, forbid all network protocols, never invoke a shell.
    pcm = LocalPCM(
        str(track.path), before_options="-nostdin -protocol_whitelist file,pipe -f wav",
        options="-vn -sn -dn -loglevel error", stderr=None,
    )
    try:
        return CountedAudio(pcm, volume / 100)
    except BaseException:
        pcm.cleanup()
        raise


class NativePlayer:
    """MusicSession player adapter. Callbacks are bound to a single generation."""
    def __init__(self, voice, catalog, on_end, *, audio_factory=local_audio):
        self.voice, self.catalog, self.on_end = voice, catalog, on_end
        self.audio_factory = audio_factory
        self.loop = asyncio.get_running_loop()
        self.generation = 0
        self.audio = None
        self.length = 0
        self.closed = False
        self.events = set()

    @property
    def guild(self):
        return self.voice.guild

    @property
    def channel(self):
        return self.voice.channel

    @property
    def connected(self):
        return not self.closed and self.voice.is_connected()

    @property
    def paused(self):
        return self.voice.is_paused()

    @property
    def position(self):
        return min(self.length, self.audio.frames * 20) if self.audio else 0

    async def wait_voice_ready(self):
        # discord.py 2.7.1 marks the transport connected after receiving the
        # secret key, before DAVE MLS setup necessarily completes.
        state = getattr(self.voice, "_connection", None)
        for _ in range(80):
            if not self.connected:
                raise MusicError("Voice channel terputus.")
            version = getattr(state, "dave_protocol_version", None)
            ready = getattr(state, "can_encrypt", False)
            if type(version) is not int or version < 0:
                raise MusicError("Status enkripsi voice tidak dapat diperiksa.")
            if version == 0 or ready is True:
                log.info("Native voice ready: dave_version=%s encrypted_ready=%s",
                         version, ready is True)
                return
            await asyncio.sleep(0.1)
        log.warning("Native voice not ready: DAVE negotiation timed out")
        raise MusicError("Enkripsi voice Discord belum siap; coba lagi.")

    async def play(self, track, *, volume, paused=False, add_history=False):
        if not self.connected:
            raise MusicError("Voice channel tidak terhubung.")
        checked = self.catalog.validate(track)
        nonce = track.extras.get("abud_music_nonce")
        if not nonce:
            raise MusicError("Sesi audio tidak valid.")
        await self.wait_voice_ready()
        await self.skip(force=True)
        generation = self.generation
        audio = self.audio_factory(checked, volume)
        self.audio, self.length = audio, checked.length

        def after(error):
            # Discord's audio thread catches transport/encoder exceptions itself.
            # Record only class and counts, never raw provider data or voice secrets.
            log.info("Native audio ended: frames=%s expected_ms=%s error=%s",
                     audio.frames, checked.length, type(error).__name__ if error else "none")
            reason = ("loadFailed" if error or audio.frames == 0
                      or audio.frames * 20 + 1000 < checked.length else "finished")
            try:
                self.loop.call_soon_threadsafe(self._ended, generation, nonce, reason)
            except RuntimeError:
                pass  # loop is shutting down

        try:
            self.voice.play(audio, after=after)
            log.info("Native audio started: expected_ms=%s", checked.length)
            if paused:
                self.voice.pause()
        except BaseException:
            self.generation += 1
            self.voice.stop()
            self.audio = None
            audio.cleanup()
            raise

    def _ended(self, generation, nonce, reason):
        if self.closed or generation != self.generation:
            return
        self.generation += 1  # at most one event for this playback
        self.audio = None
        task = self.loop.create_task(self.on_end(self, nonce, reason))
        self.events.add(task)
        task.add_done_callback(self._event_done)

    def _event_done(self, task):
        self.events.discard(task)
        if not task.cancelled() and task.exception():
            log.warning("Native audio event failed (%s)", type(task.exception()).__name__)

    async def skip(self, *, force=False):
        self.generation += 1
        self.voice.stop()
        self.audio = None
        self.length = 0

    async def pause(self, value):
        if value:
            self.voice.pause()
        else:
            self.voice.resume()

    async def set_volume(self, value):
        if self.audio:
            self.audio.volume = value / 100

    async def seek(self, position):
        raise MusicError("Audio lokal belum mendukung seek.")

    async def disconnect(self):
        self.closed = True
        await self.skip(force=True)
        try:
            await self.voice.disconnect(force=True)
        finally:
            self.voice.cleanup()

    def cleanup(self):
        self.closed = True
        self.generation += 1
        self.voice.stop()
        self.audio = None
        self.voice.cleanup()
