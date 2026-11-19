"""Opt-in single-track Audius maintenance mode. No generic URL playback."""
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
        return [wavelink.Playable(data)]

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
