import asyncio
import json
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.music_native import NativeCatalog, NativePlayer, NativeTrack, local_audio
from app.music_session import MusicError, MusicSession


class CatalogFixture:
    def __init__(self, root):
        self.root = root
        self.rows = [
            {"id": "tone", "title": "Test Tone", "artist": "ABUD", "approved": True},
            {"id": "second", "title": "Second Tone", "artist": "ABUD", "approved": True},
            {"id": "hidden", "title": "Hidden", "artist": "ABUD", "approved": False},
        ]
        for key in ("tone", "second"):
            with wave.open(str(root / (key + ".wav")), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b"\x00" * 48000 * 2 * 2)
        self.save()
        self.catalog = NativeCatalog(root)

    def save(self):
        (self.root / "catalog.json").write_text(json.dumps(self.rows))


class NativeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = CatalogFixture(Path(self.tmp.name))
        self.catalog = self.fx.catalog

    def test_search_only_approved(self):
        self.assertEqual([t.identifier for t in self.catalog.search("Test Tone")], ["tone"])
        self.assertEqual(self.catalog.search("Hidden"), [])
        self.assertEqual(self.catalog.search("tone")[0].length, 2000)
        self.assertFalse(self.catalog.search("tone")[0].is_seekable)

    def test_reject_url_and_arbitrary_path(self):
        for q in ("https://example.org/a.wav", "file:///etc/passwd", "//example.org/a.wav"):
            with self.assertRaises(MusicError):
                self.catalog.search(q)
        self.assertEqual(self.catalog.search("/etc/passwd"), [])

    def test_unsafe_manifest_id_rejected(self):
        self.fx.rows[0]["id"] = "../secret"
        self.fx.save()
        with self.assertRaises(MusicError):
            self.catalog.load()

    def test_symlink_audio_rejected(self):
        path = self.fx.root / "tone.wav"
        path.unlink()
        path.symlink_to(self.fx.root / "second.wav")
        with self.assertRaises(MusicError):
            self.catalog.load()

    def test_revoked_track_rejected_at_play(self):
        track = self.catalog.search("tone")[0]
        self.fx.rows[0]["approved"] = False
        self.fx.save()
        with self.assertRaises(MusicError):
            self.catalog.validate(track)

    def test_changed_file_rejected(self):
        track = self.catalog.search("tone")[0]
        with (self.fx.root / "tone.wav").open("ab") as out:
            out.write(b"x")
        with self.assertRaises(MusicError):
            self.catalog.validate(track)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_real_ffmpeg_decodes_pcm_offline(self):
        with wave.open(str(self.fx.root / "tone.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(b"\xff\x0f" * 48000 * 2)
        audio = local_audio(self.catalog.search("tone")[0], 50)
        try:
            packets = [audio.read() for _ in range(101)]
            self.assertEqual(audio.frames, 100)
            self.assertTrue(any(packets[0]))
            self.assertEqual(len(packets[0]), 3840)
            self.assertEqual(packets[-1], b"")
        finally:
            audio.cleanup()

    def test_non_native_rejected(self):
        with self.assertRaises(MusicError):
            self.catalog.validate(SimpleNamespace(identifier="tone"))


class NativePlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = CatalogFixture(Path(self.tmp.name))
        self.voice = Mock()
        self.voice.channel = SimpleNamespace(id=7)
        self.voice.guild = SimpleNamespace(id=11)
        self.voice.is_connected.return_value = True
        self.voice.is_paused.return_value = False
        self.voice.disconnect = AsyncMock()
        self.callbacks = []
        self.voice.play.side_effect = lambda audio, after: self.callbacks.append(after)
        self.sources = []
        def factory(track, volume):
            audio = Mock()
            audio.frames = 0
            self.sources.append(audio)
            return audio
        self.end = AsyncMock()
        self.player = NativePlayer(self.voice, self.fx.catalog, self.end, audio_factory=factory)
        self.track = self.fx.catalog.search("tone")[0]
        self.track.extras = {"abud_music_nonce": "one"}

    async def drain(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_finished_once(self):
        await self.player.play(self.track, volume=50)
        self.sources[-1].frames = 100
        self.assertEqual(self.player.position, 2000)
        self.callbacks[-1](None)
        self.callbacks[-1](None)
        await self.drain()
        self.end.assert_awaited_once_with(self.player, "one", "finished")

    async def test_zero_audio_reports_failure(self):
        await self.player.play(self.track, volume=50)
        self.callbacks[-1](None)
        await self.drain()
        self.end.assert_awaited_once_with(self.player, "one", "loadFailed")

    async def test_stale_callback_after_skip_ignored(self):
        await self.player.play(self.track, volume=50)
        await self.player.skip(force=True)
        self.callbacks[-1](None)
        await self.drain()
        self.end.assert_not_awaited()

    async def test_stale_callback_after_replace_ignored(self):
        await self.player.play(self.track, volume=50)
        old = self.callbacks[-1]
        self.track.extras = {"abud_music_nonce": "two"}
        await self.player.play(self.track, volume=50)
        old(RuntimeError("old"))
        self.sources[-1].frames = 100
        self.callbacks[-1](None)
        await self.drain()
        self.end.assert_awaited_once_with(self.player, "two", "finished")

    async def test_pause_volume_disconnect(self):
        await self.player.play(self.track, volume=50)
        await self.player.pause(True)
        self.voice.pause.assert_called_once()
        await self.player.pause(False)
        self.voice.resume.assert_called_once()
        await self.player.set_volume(25)
        self.assertEqual(self.sources[-1].volume, .25)
        await self.player.disconnect()
        self.voice.disconnect.assert_awaited_once_with(force=True)
        self.callbacks[-1](None)
        await self.drain()
        self.end.assert_not_awaited()

    async def test_shared_session_queue_and_repeat(self):
        session = MusicSession(self.player, 1, None)
        self.player.on_end = lambda player, nonce, reason: session.ended(nonce, reason)
        other = self.fx.catalog.search("second")[0]
        await session.enqueue([self.track, other], 1)
        self.assertEqual(session.current.track.identifier, "tone")
        self.sources[-1].frames = 100
        self.callbacks[-1](None)
        await self.drain()
        self.assertEqual(session.current.track.identifier, "second")
        await session.control("repeat", "track")
        self.sources[-1].frames = 100
        self.callbacks[-1](None)
        await self.drain()
        self.assertEqual(session.current.track.identifier, "second")
        await session.close()

    async def test_start_failure_cleans_decoder(self):
        self.voice.play.side_effect = RuntimeError("fail")
        with self.assertRaises(RuntimeError):
            await self.player.play(self.track, volume=50)
        self.sources[-1].cleanup.assert_called_once()
        self.assertIsNone(self.player.audio)


if __name__ == "__main__":
    unittest.main()
