import unittest
from unittest.mock import AsyncMock
from app.music_audius import AudiusCatalog, AudiusError, public_track


def record(**changes):
    return dict({
        "id": "V66vyPP", "title": "Example Track", "user": {"name": "Artist"},
        "duration": 212, "is_available": True, "is_stream_gated": False,
        "is_unlisted": False, "is_delete": False, "stream_conditions": None,
        "allowed_api_keys": None, "license": None,
    }, **changes)


class AudiusTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_track_fixed_origin_and_id(self):
        request = AsyncMock(return_value={"data": record()})
        result = await AudiusCatalog(request=request).track("V66vyPP")
        self.assertEqual(result.stream_url,
                         "https://api.audius.co/v1/tracks/V66vyPP/stream")
        request.assert_awaited_once_with("/tracks/V66vyPP")

    async def test_injected_id_rejected_before_request(self):
        request = AsyncMock()
        for bad in ["../track", "http://localhost", "foo?x=1", "a/b"]:
            with self.assertRaises(AudiusError):
                await AudiusCatalog(request=request).track(bad)
        request.assert_not_awaited()

    def test_fail_closed_for_restricted_or_unknown_access(self):
        for changes in [
            {"is_available": False}, {"is_stream_gated": True},
            {"is_stream_gated": None}, {"stream_conditions": {"gate": True}},
            {"allowed_api_keys": ["key"]}, {"access_authorities": ["gate"]},
            {"is_unlisted": True}, {"is_delete": True}, {"duration": 0},
        ]:
            with self.subTest(changes=changes), self.assertRaises(AudiusError):
                public_track(record(**changes))

    async def test_mismatched_id_rejected(self):
        with self.assertRaises(AudiusError):
            await AudiusCatalog(request=AsyncMock(return_value={
                "data": record(id="other")
            })).track("V66vyPP")

    async def test_search_returns_bounded_ids_not_stream_grants(self):
        request = AsyncMock(return_value={"data": [
            {"id": "good"}, {"id": "../x"}, {"id": "good"}, {"id": "next"},
            {"id": "third"}, {"id": "ignored"}
        ]})
        self.assertEqual(await AudiusCatalog(request=request).search("a & b"),
                         ["good", "next", "third"])
        request.assert_awaited_once_with("/tracks/search?query=a+%26+b&limit=5")
