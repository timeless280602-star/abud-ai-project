import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.music_audius import AudiusTrack
from app.music_audius_live import AudiusLiveProbe
from app.music_session import MusicError, RequestedTrack
from test_discord_music import track


class AudiusLiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.probe = AudiusLiveProbe()
        self.probe.enabled = True
        self.probe.guild, self.probe.user, self.probe.track_id = 1, 100, "V66vyPP"
        self.probe.catalog.track = AsyncMock(return_value=AudiusTrack(
            "V66vyPP", "Example", "Artist", 212, None, None
        ))

    def test_actor_and_url_guards(self):
        self.probe.require_actor(SimpleNamespace(guild_id=1, user=SimpleNamespace(id=100)))
        with self.assertRaises(MusicError):
            self.probe.require_actor(SimpleNamespace(guild_id=1, user=SimpleNamespace(id=101)))
        with self.assertRaises(MusicError):
            self.probe.check_enqueue([track(source="http")])
        self.probe.enabled = False
        with self.assertRaises(MusicError):
            self.probe.check_enqueue([track(source="http")])

    async def test_only_approved_track_loads_and_metadata_replaced(self):
        raw = track("raw", source="http", length=212160)
        with patch("app.music_audius_live.wavelink.Pool.fetch_tracks",
                   new=AsyncMock(return_value=[raw])) as fetch:
            for q in ["https://example.org/song", "unapproved title"]:
                with self.assertRaises(MusicError):
                    await self.probe.load(q, "audius", None)
            fetch.assert_not_awaited()
            loaded = (await self.probe.load("Example", "audius", None))[0]
            fetch.assert_awaited_once_with(self.probe.stream_url, node=None)
        self.assertEqual(loaded.encoded, raw.encoded)
        self.assertEqual(loaded.title, "Example")
        self.assertEqual(loaded.author, "Artist")
        self.probe.check_enqueue([loaded])
        self.probe.catalog.track.reset_mock()
        await self.probe.before_play(RequestedTrack(loaded, 100))
        self.probe.catalog.track.assert_awaited_once_with("V66vyPP")
        with self.assertRaises(MusicError):
            await self.probe.before_play(RequestedTrack(loaded, 101))

    async def test_bad_duration_or_source_is_rejected(self):
        for result in [track(source="http", length=10000),
                       track(source="youtube", length=212000)]:
            with patch("app.music_audius_live.wavelink.Pool.fetch_tracks",
                       new=AsyncMock(return_value=[result])):
                with self.assertRaises(MusicError):
                    await self.probe.load("V66vyPP", None, None)
