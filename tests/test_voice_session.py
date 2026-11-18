"""Voice lifecycle contracts with bounded PCM and cancellable provider doubles."""

import asyncio
import io
import struct
import time
import unittest
import wave
from unittest.mock import AsyncMock, Mock

from app.voice_session import (
    BYTES_PER_SECOND,
    AudioCollector,
    VoiceSession,
    addressed_text,
    pcm_wav,
    speech_text,
)

FRAME = struct.pack("<h", 1200) * 1920
SILENCE = b"\x00" * 3840


class CaptureTests(unittest.TestCase):
    def test_only_enrolled_speakers_produce_separate_wav_recordings(self):
        collector = AudioCollector()
        collector.enroll(1)
        collector.enroll(2)
        for frame in range(20):
            for speaker in (1, 2, 3):
                collector.feed(speaker, FRAME if speaker == 1 else FRAME[::-1], 10 + frame * 0.02)
        ready = dict(collector.ready(12))
        self.assertEqual(set(ready), {1, 2})
        self.assertNotEqual(ready[1], ready[2])
        with wave.open(io.BytesIO(pcm_wav(ready[1]))) as wav:
            self.assertEqual(
                (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (48000, 2, 2)
            )
        self.assertEqual(collector.ready(13), [])

    def test_silence_and_clicks_are_not_transcribed(self):
        collector = AudioCollector()
        collector.enroll(1)
        collector.feed(1, SILENCE, 10)
        self.assertEqual(collector.buffers, {})
        collector.feed(1, FRAME, 11)
        self.assertEqual(collector.ready(13), [])

    def test_overlong_speech_is_bounded_and_discarded_until_a_pause(self):
        collector = AudioCollector()
        collector.enroll(1)
        for frame in range(601):
            collector.feed(1, FRAME, 10 + frame * 0.02)
        self.assertLessEqual(len(collector.buffers[1].pcm), BYTES_PER_SECOND * 12)
        self.assertEqual(collector.ready(22), [])
        collector.feed(1, FRAME, 22.1)
        self.assertEqual(collector.buffers, {})
        for frame in range(20):
            collector.feed(1, FRAME, 24 + frame * 0.02)
        self.assertEqual(len(collector.ready(26)), 1)

    def test_unenroll_pause_and_speaker_limit_release_memory(self):
        collector = AudioCollector()
        for user in range(8):
            collector.enroll(user)
        with self.assertRaises(ValueError):
            collector.enroll(9)
        collector.feed(0, FRAME, 10)
        collector.enroll(0, False)
        self.assertNotIn(0, collector.buffers)
        collector.enroll(9)
        collector.clear(paused=True)
        collector.feed(9, FRAME, 10)
        self.assertEqual(collector.buffers, {})

    def test_addressing_requires_word_at_start_and_preserves_request(self):
        self.assertEqual(addressed_text("Halo Abud, bantu gw dong!"), "bantu gw dong!")
        self.assertEqual(addressed_text("ABUD"), "")
        self.assertIsNone(addressed_text("tadi Abud bilang apa?"))
        self.assertIsNone(addressed_text("Abudiman lagi main"))

    def test_spoken_output_is_bounded_and_omits_code_urls_and_snowflakes(self):
        output = speech_text(
            "**Halo** [panduan](https://example.test) <@1234> ```python\nprint(1)``` https://secret.test"
        )
        self.assertIn("Halo panduan", output)
        self.assertNotIn("print(1)", output)
        self.assertNotIn("https", output)
        self.assertNotIn("1234", output)
        self.assertLessEqual(len(speech_text("panjang " * 900)), 901)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.active = {1, 2}
        self.services = Mock(
            transcribe=AsyncMock(return_value="Abud, halo"),
            reply=AsyncMock(return_value="Halo juga!"),
            synthesize=AsyncMock(return_value=b"audio"),
        )
        self.play = AsyncMock()
        self.report = AsyncMock()
        self.stop_playing = Mock()
        self.session = VoiceSession(
            self.services,
            eligible=lambda user: user in self.active and user in self.session.collector.allowed,
            play=self.play,
            stop_playing=self.stop_playing,
            report=self.report,
        )
        for user in self.active:
            self.session.collector.enroll(user)
        self.session.start()

    async def asyncTearDown(self):
        await self.session.close()
        self.assertTrue(all(task.done() for task in self.session.tasks))

    async def drain(self):
        await asyncio.wait_for(self.session.queue.join(), 1)

    async def test_serial_turns_keep_speaker_identity(self):
        for user in (1, 2):
            self.session.enqueue(user, FRAME * 20)
        await self.drain()
        self.assertEqual(
            [call.args for call in self.services.reply.await_args_list], [(1, "halo"), (2, "halo")]
        )
        self.assertEqual(self.session.completed, 2)
        self.assertEqual(self.play.await_count, 2)
        self.assertFalse(self.session.collector.paused)

    async def test_unaddressed_audio_never_calls_ai_or_tts(self):
        self.services.transcribe.return_value = "lagi ngobrol dengan teman"
        self.session.enqueue(1, FRAME)
        await self.drain()
        self.services.reply.assert_not_awaited()
        self.play.assert_not_awaited()

    async def test_stop_cancels_processing_discards_queue_then_accepts_new_turn(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def hanging(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.services.transcribe.side_effect = hanging
        self.session.enqueue(1, FRAME)
        await asyncio.wait_for(started.wait(), 1)
        self.session.enqueue(2, FRAME)
        await self.session.stop()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(self.session.queue.empty())
        self.services.reply.assert_not_awaited()
        self.services.transcribe.side_effect = None
        self.session.enqueue(2, FRAME)
        await self.drain()
        self.assertEqual(self.session.completed, 1)

    async def test_full_queue_and_stale_turns_are_dropped(self):
        for _ in range(4):
            self.session.enqueue(1, FRAME)
        self.assertEqual(self.session.dropped, 1)
        await self.drain()
        self.session.queue.put_nowait((1, FRAME, time.monotonic() - 31))
        await self.drain()
        self.assertEqual(self.session.dropped, 2)
        self.assertEqual(self.services.reply.await_count, 3)

    async def test_unenroll_removes_queued_audio_even_after_immediate_reenroll(self):
        self.session.enqueue(1, FRAME)
        self.session.enqueue(2, FRAME)
        await self.session.unenroll(1)
        self.session.collector.enroll(1)
        await self.drain()
        self.assertEqual([call.args[0] for call in self.services.reply.await_args_list], [2])

    async def test_member_leaving_during_asr_cannot_get_a_spoken_reply(self):
        async def transcribe(_):
            self.active.remove(1)
            return "Abud halo"

        self.services.transcribe.side_effect = transcribe
        self.session.enqueue(1, FRAME)
        await self.drain()
        self.services.reply.assert_not_awaited()

    async def test_timeout_reports_failure_and_next_turn_recovers(self):
        async def hanging(_):
            await asyncio.Event().wait()

        self.session.turn_timeout = 0.02
        self.services.transcribe.side_effect = hanging
        self.session.enqueue(1, FRAME)
        await self.drain()
        self.assertIsInstance(self.report.await_args.args[0], TimeoutError)
        self.services.transcribe.side_effect = None
        self.session.enqueue(2, FRAME)
        await self.drain()
        self.assertEqual(self.session.completed, 1)

    async def test_stop_during_playback_resumes_capture(self):
        started = asyncio.Event()

        async def playing(_):
            started.set()
            await asyncio.Event().wait()

        self.play.side_effect = playing
        self.session.enqueue(1, FRAME)
        await asyncio.wait_for(started.wait(), 1)
        self.assertTrue(self.session.collector.paused)
        self.session.collector.feed(2, FRAME)
        self.assertEqual(self.session.collector.buffers, {})
        await self.session.stop()
        self.assertFalse(self.session.collector.paused)
        self.assertFalse(any(task.done() for task in self.session.tasks))

    async def test_provider_error_does_not_kill_consumer(self):
        self.services.synthesize.side_effect = [RuntimeError("provider"), b"audio"]
        self.session.enqueue(1, FRAME)
        self.session.enqueue(2, FRAME)
        await self.drain()
        self.assertEqual(self.report.await_count, 1)
        self.assertEqual(self.session.completed, 1)


if __name__ == "__main__":
    unittest.main()
