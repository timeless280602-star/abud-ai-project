"""Opt-in single-track Audius maintenance mode. No generic URL playback."""
import asyncio
import os
from urllib.parse import urlsplit
import wavelink
from app.music_audius import AudiusCatalog, AudiusError, checked_id
from app.music_providers import normalized
from app.music_session import MusicError


class AudiusLiveProbe:
    def __init__(self):
        self.enabled = os.getenv("ABUD_MUSIC_AUDIUS_TEST", "false").lower() == "true"
        self.catalog = AudiusCatalog()
        self.guild = self.user = self.track_id = None
        if self.enabled:
            try:
                self.guild = int(os.getenv("ABUD_MUSIC_AUDIUS_TEST_GUILD", ""))
                self.user = int(os.getenv("ABUD_MUSIC_AUDIUS_TEST_USER", ""))
                self.track_id = checked_id(os.getenv("ABUD_MUSIC_AUDIUS_TEST_TRACK", ""))
                if self.guild <= 0 or self.user <= 0:
                    raise ValueError()
            except (ValueError, AudiusError):
                raise ValueError("Invalid Audius maintenance identifiers") from None

    def require_actor(self, context):
        if self.enabled and (context.guild_id != self.guild or context.user.id != self.user):
            raise MusicError("Musik sedang dalam maintenance test terbatas.")

    @property
    def stream_url(self):
        return "https://api.audius.co/v1/tracks/" + checked_id(self.track_id) + "/stream"

    async def metadata(self):
        try:
            return await self.catalog.track(self.track_id)
        except AudiusError as error:
            raise MusicError(str(error)) from None

    async def load(self, query, source, node):
        if not self.enabled or source not in (None, "audius"):
            raise MusicError("Mode uji Audius belum aktif atau provider tidak sesuai.")
        # Do not accept raw URL or arbitrary stream path, even during maintenance.
        if urlsplit(query).scheme or urlsplit(query).netloc or not query.strip() or len(query) > 300:
            raise MusicError("Gunakan judul atau ID track Audius yang disetujui.")
        t = await self.metadata()
        if normalized(query) not in (
            normalized(t.id), normalized(t.title), normalized(t.title + " " + t.artist)
        ):
            raise MusicError("Track tidak termasuk uji Audius yang disetujui.")
        return [await self.load_track(t, node)]

    async def load_track(self, t, node):
        result = await wavelink.Pool.fetch_tracks(t.stream_url, node=node)
        if isinstance(result, wavelink.Playlist) or len(result) != 1:
            raise MusicError("Audio Audius belum bisa dimuat.")
        track = result[0]
        if (track.source != "http" or track.is_stream
                or abs(track.length - t.duration * 1000) > 3000):
            raise MusicError("Metadata audio tidak sesuai dengan track Audius.")
        # Encoded payload is unchanged. Only the display fields are supplied
        # from independently validated metadata, not from user input.
        data = {
            "encoded": track.encoded,
            "info": {
                "identifier": t.id, "isSeekable": track.is_seekable,
                "author": t.artist, "length": track.length, "isStream": False,
                "position": 0, "title": t.title, "uri": t.stream_url,
                "artworkUrl": None, "sourceName": "http", "isrc": t.isrc,
            },
            "pluginInfo": {}, "userData": {},
        }
        return wavelink.Playable(data)

    def check_enqueue(self, tracks):
        if self.enabled:
            if any(t.source != "http" or t.uri != self.stream_url for t in tracks):
                raise MusicError("Hanya track Audius uji yang disetujui.")
        elif any(t.source == "http" for t in tracks):
            raise MusicError("HTTP audio tidak diizinkan.")

    async def before_play(self, request):
        self.check_enqueue([request.track])
        if self.enabled:
            if request.requester != self.user:
                raise MusicError("Peminta track tidak diizinkan.")
            await self.metadata()


class AudiusCatalogMode(AudiusLiveProbe):
    """Opt-in Audius-only pilot. HTTP source must be private and exclusive."""
    def __init__(self):
        super().__init__()
        self.dynamic = os.getenv("ABUD_MUSIC_AUDIUS_CATALOG", "false").lower() == "true"
        if self.dynamic:
            if self.enabled:
                raise ValueError("Audius test and catalog modes are mutually exclusive")
            if os.getenv("ABUD_MUSIC_AUDIUS_TERMS_ACCEPTED", "").lower() != "true":
                raise ValueError("Review Audius terms and confirm authorized use")
            try:
                self.guild = int(os.getenv("ABUD_MUSIC_AUDIUS_GUILD", ""))
                if self.guild <= 0:
                    raise ValueError()
            except ValueError:
                raise ValueError("Invalid Audius catalog guild") from None
            self.enabled = True
        self.load_slots = asyncio.Semaphore(2)

    def require_actor(self, context):
        if self.dynamic:
            if context.guild_id != self.guild:
                raise MusicError("Katalog Audius belum aktif di server ini.")
        else:
            super().require_actor(context)

    async def load(self, query, source, node):
        if not self.dynamic:
            return await super().load(query, source, node)
        query = query.strip()
        if source not in (None, "audius"):
            raise MusicError("Mode katalog ini hanya mendukung Audius.")
        if (not query or len(query) > 300 or any(ord(c) < 32 for c in query)
                or urlsplit(query).scheme or urlsplit(query).netloc):
            raise MusicError("Gunakan judul dan artis, bukan URL audio.")
        try:
            ids = await self.catalog.search(query)
        except AudiusError as error:
            raise MusicError(str(error)) from None

        async def load_one(identifier):
            try:
                async with asyncio.timeout(12), self.load_slots:
                    t = await self.catalog.track(identifier)
                    return await self.load_track(t, node)
            except (AudiusError, MusicError, TimeoutError, wavelink.WavelinkException):
                return None

        # Bounded concurrency; preserve provider result order.
        results = await asyncio.gather(*(load_one(i) for i in ids[:5]))
        playable = [t for t in results if t is not None]
        if not playable:
            raise MusicError("Tidak ada track Audius yang dapat diputar.")
        return playable

    def check_enqueue(self, tracks):
        if not self.dynamic:
            return super().check_enqueue(tracks)
        for t in tracks:
            try:
                identifier = checked_id(t.identifier)
            except AudiusError:
                raise MusicError("ID track Audius tidak valid.") from None
            if (t.source != "http" or t.is_stream
                    or t.uri != "https://api.audius.co/v1/tracks/" + identifier + "/stream"):
                raise MusicError("Hanya track resmi Audius yang dapat diputar.")

    async def before_play(self, request):
        if not self.dynamic:
            return await super().before_play(request)
        self.check_enqueue([request.track])
        try:
            t = await self.catalog.track(request.track.identifier)
        except AudiusError as error:
            raise MusicError(str(error)) from None
        if (normalized(t.title) != normalized(request.track.title)
                or normalized(t.artist) != normalized(request.track.author)
                or abs(t.duration * 1000 - request.track.length) > 3000):
            raise MusicError("Metadata Audius berubah; cari ulang lagu.")
