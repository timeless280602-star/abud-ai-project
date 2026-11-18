"""Bounded, per-speaker voice turns; independent of Discord's transport threads."""

import asyncio
import io
import re
import threading
import time
import wave
from array import array
from dataclasses import dataclass, field

RATE = 48000
FRAME_BYTES = 3840  # Discord PCM: 20 ms, stereo, signed 16-bit, 48 kHz.
BYTES_PER_SECOND = RATE * 4
WAKE_WORD = re.compile(r"^(?:(?:hey|hei|hai|halo|oke|ok|woy)\s+)?abud\b[\s,.:!?-]*", re.IGNORECASE)


def addressed_text(text):
    """Activation is checked on the transcript, not an always-on local wake model."""
    match = WAKE_WORD.match(text.strip())
    return text.strip()[match.end() :].strip() if match else None


def pcm_wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return output.getvalue()


def speech_text(text, maximum=900):
    """Keep speech bounded; don't read markdown links, code or Discord IDs aloud."""
    text = re.sub(
        r"```.*?```", " Kode lengkap lebih cocok lewat chat teks. ", text, flags=re.DOTALL
    )
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+|<[@#][^>]+>|@everyone|@here", "", text)
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > maximum:
        text = text[:maximum].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return text


@dataclass
class Recording:
    started: float
    last_voice: float
    pcm: bytearray = field(default_factory=bytearray)
    voiced_frames: int = 0


class AudioCollector:
    """One bounded buffer per enrolled speaker. Called by the RTP and event threads."""

    def __init__(self, *, silence=0.8, maximum=12, minimum=0.3, threshold=200):
        self.silence, self.maximum, self.minimum, self.threshold = (
            silence,
            maximum,
            minimum,
            threshold,
        )
        self.allowed = set()
        self.buffers = {}
        self.blocked = {}  # discard an overlong utterance until the speaker pauses
        self.paused = False
        self.lock = threading.Lock()

    def enroll(self, user_id, enabled=True):
        with self.lock:
            if enabled:
                if user_id not in self.allowed and len(self.allowed) >= 8:
                    raise ValueError("Maksimal 8 pendengar aktif per sesi.")
                self.allowed.add(user_id)
            else:
                self.allowed.discard(user_id)
            self.buffers.pop(user_id, None)
            self.blocked.pop(user_id, None)

    def clear(self, *, paused=None):
        with self.lock:
            self.buffers.clear()
            self.blocked.clear()
            if paused is not None:
                self.paused = paused

    def feed(self, user_id, pcm, now=None):
        if len(pcm) != FRAME_BYTES:
            return
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.paused or user_id not in self.allowed:
                return
            samples = array("h", pcm)
            samples = samples[::8]
            voiced = sum(value * value for value in samples) / len(samples) >= self.threshold**2
            if user_id in self.blocked:
                if voiced and now - self.blocked[user_id] < self.silence:
                    self.blocked[user_id] = now
                    return
                if not voiced:
                    return
                self.blocked.pop(user_id, None)
            recording = self.buffers.get(user_id)
            if recording is None:
                if not voiced:
                    return
                recording = self.buffers[user_id] = Recording(now, now)
            # Fill DTX gaps with silence without exceeding the recording limit.
            target = min(
                int((now - recording.started) * BYTES_PER_SECOND),
                int(self.maximum * BYTES_PER_SECOND),
            )
            target -= target % 4
            gap = target - len(recording.pcm)
            if gap > 0:
                recording.pcm.extend(b"\x00" * gap)
            remaining = int(self.maximum * BYTES_PER_SECOND) - len(recording.pcm)
            recording.pcm.extend(pcm[: max(0, remaining)])
            if voiced:
                recording.last_voice = now
                recording.voiced_frames += 1

    def ready(self, now=None):
        now = time.monotonic() if now is None else now
        result = []
        with self.lock:
            for user_id, recording in list(self.buffers.items()):
                overlong = now - recording.started >= self.maximum
                if not overlong and now - recording.last_voice < self.silence:
                    continue
                del self.buffers[user_id]
                if overlong:
                    # A long monologue must not become a truncated actionable request.
                    self.blocked[user_id] = recording.last_voice
                    continue
                if recording.voiced_frames * 0.02 >= self.minimum:
                    result.append((user_id, bytes(recording.pcm)))
        return result


class VoiceSession:
    """A single consumer serializes ASR -> chat -> TTS -> playback for a guild."""

    def __init__(self, services, *, eligible, play, stop_playing, report, turn_timeout=120):
        self.services = services
        self.eligible, self.play, self.stop_playing, self.report = (
            eligible,
            play,
            stop_playing,
            report,
        )
        self.turn_timeout = turn_timeout
        self.collector = AudioCollector()
        self.queue = asyncio.Queue(maxsize=3)
        self.closed = False
        self.state = "listening"
        self.last_activity = time.monotonic()
        self.completed = 0
        self.dropped = 0
        self.current = None
        self.speaker = None
        self.tasks = []
        self.interrupting = False
        self.control_lock = asyncio.Lock()

    def start(self):
        self.tasks = [asyncio.create_task(self._collect()), asyncio.create_task(self._consume())]

    def enqueue(self, user_id, pcm):
        if self.closed or self.interrupting or not self.eligible(user_id):
            return
        self.last_activity = time.monotonic()
        try:
            self.queue.put_nowait((user_id, pcm, time.monotonic()))
        except asyncio.QueueFull:
            self.dropped += 1

    async def _collect(self):
        while not self.closed:
            for user_id, pcm in self.collector.ready():
                self.enqueue(user_id, pcm)
            await asyncio.sleep(0.1)

    async def _consume(self):
        while not self.closed:
            user_id, pcm, queued_at = await self.queue.get()
            try:
                if time.monotonic() - queued_at > 30:
                    self.dropped += 1
                    continue
                if not self.eligible(user_id):
                    continue
                self.speaker = user_id
                self.current = asyncio.create_task(self._turn(user_id, pcm))
                await self.current
            except asyncio.CancelledError:
                if self.closed:
                    return
            except Exception as error:  # noqa: BLE001 - one failed provider turn must not kill the queue
                await self.report(error)
            finally:
                self.current, self.speaker = None, None
                self.state = "listening"
                self.queue.task_done()

    async def _turn(self, user_id, pcm):
        async with asyncio.timeout(self.turn_timeout):
            self.state = "transcribing"
            transcript = await self.services.transcribe(pcm_wav(pcm))
            prompt = addressed_text(transcript)
            if prompt is None or not self.eligible(user_id):
                return
            self.state = "thinking"
            reply = await self.services.reply(user_id, prompt or "Halo Abud")
            text = speech_text(reply)
            if not text or not self.eligible(user_id):
                return
            self.state = "synthesizing"
            audio = await self.services.synthesize(text)
            if not self.eligible(user_id):
                return
            self.state = "speaking"
            self.collector.clear(paused=True)
            try:
                await self.play(audio)
                self.completed += 1
            finally:
                self.collector.clear(paused=False)
                self.last_activity = time.monotonic()

    async def stop(self):
        """Interrupt only playback, preserving the receive connection."""
        async with self.control_lock:
            self.interrupting = True
            self.collector.clear(paused=True)
            try:
                # Drain before yielding, or the consumer could pick up another turn
                # while we are awaiting cancellation of the current one.
                while not self.queue.empty():
                    self.queue.get_nowait()
                    self.queue.task_done()
                if self.current:
                    self.current.cancel()
                    await asyncio.gather(self.current, return_exceptions=True)
                self.stop_playing()
            finally:
                self.collector.clear(paused=self.closed)
                self.state = "listening"
                self.interrupting = False

    async def unenroll(self, user_id):
        self.collector.enroll(user_id, False)
        # Forget queued recordings too, including if this member rejoins immediately.
        retained = []
        while not self.queue.empty():
            item = self.queue.get_nowait()
            self.queue.task_done()
            if item[0] != user_id:
                retained.append(item)
        for item in retained:
            self.queue.put_nowait(item)
        if self.speaker == user_id and self.current:
            self.current.cancel()
            await asyncio.gather(self.current, return_exceptions=True)
            self.stop_playing()

    async def close(self):
        self.closed = True
        await self.stop()
        self.collector.clear(paused=True)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
