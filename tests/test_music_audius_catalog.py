import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.music_audius import AudiusTrack, AudiusError
from app.music_audius_live import AudiusCatalogMode
from app.music_session import MusicError, RequestedTrack
from test_discord_music import track


class AudiusCatalogModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.dict(os.environ, {"ABUD_MUSIC_AUDIUS_CATALOG": "true",
                       "ABUD_MUSIC_AUDIUS_TEST": "false",
                       "ABUD_MUSIC_AUDIUS_TERMS_ACCEPTED": "true",
                       "ABUD_MUSIC_AUDIUS_GUILD": "1"}):
            self.mode = AudiusCatalogMode()
        self.mode.catalog.search = AsyncMock(return_value=["good", "gated", "wrong"])
        self.mode.catalog.track = AsyncMock(side_effect=[
            AudiusTrack("good", "Example", "Artist", 212, None, None),
            AudiusError("Restricted"),
            AudiusTrack("wrong", "Other", "Other artist", 200, None, None),
        ])

    def test_guild_guard(self):
        self.mode.require_actor(SimpleNamespace(guild_id=1))
        with self.assertRaises(MusicError):
            self.mode.require_actor(SimpleNamespace(guild_id=2))

    def test_operator_ack_required(self):
        with patch.dict(os.environ, {"ABUD_MUSIC_AUDIUS_CATALOG": "true",
                        "ABUD_MUSIC_AUDIUS_TEST": "false",
                        "ABUD_MUSIC_AUDIUS_TERMS_ACCEPTED": "false"}):
            with self.assertRaises(ValueError):
                AudiusCatalogMode()

    async def test_invalid_query_and_other_providers_rejected(self):
        for query, provider in [("https://example.com", None),
                                ("//example.com", None),
                                ("Example", "youtube")]:
            with self.assertRaises(MusicError):
                await self.mode.load(query, provider, None)
        self.mode.catalog.search.assert_not_awaited()

    async def test_search_validates_each_candidate_and_checks_duration(self):
        with patch("app.music_audius_live.wavelink.Pool.fetch_tracks",
                   new=AsyncMock(return_value=[track(source="http", length=212160)])) as fetch:
            result = await self.mode.load("Example", "audius", None)
        self.assertEqual([t.identifier for t in result], ["good"])
        self.assertEqual(fetch.await_count, 2)
        self.mode.check_enqueue(result)
        with self.assertRaises(MusicError):
            self.mode.check_enqueue([track(source="http")])

    async def test_recheck_access_before_play(self):
        with patch("app.music_audius_live.wavelink.Pool.fetch_tracks",
                   new=AsyncMock(return_value=[track(source="http", length=212160)])):
            result = await self.mode.load("Example", None, None)
        self.mode.catalog.track = AsyncMock(side_effect=AudiusError("Restricted"))
        with self.assertRaises(MusicError):
            await self.mode.before_play(RequestedTrack(result[0], 100))
        self.mode.catalog.track.assert_awaited_once_with("good")
