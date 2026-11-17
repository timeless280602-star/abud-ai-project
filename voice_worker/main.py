"""Private Whisper and Piper service for Abud."""

import asyncio
import io
import os
import subprocess
import wave
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from faster_whisper import WhisperModel
from piper import PiperVoice
from starlette.concurrency import run_in_threadpool

AUDIO_FORMATS = {
    "audio/webm": "matroska", "audio/ogg": "ogg", "audio/mp4": "mov", "audio/wav": "wav",
}
MAX_SECONDS = 30
SAMPLE_RATE = 16000
compute = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    app.state.whisper = WhisperModel(
        os.getenv("ABUD_WHISPER_MODEL", "base"), device="cpu", compute_type="int8", cpu_threads=2,
    )
    app.state.piper = PiperVoice.load(Path(os.environ["ABUD_PIPER_MODEL"]))
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health():
    return {"status": "healthy"}


async def read_bounded(request, maximum):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "Payload too large")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Empty payload")
    return bytes(data)


def recognize(model, data, format_name):
    try:
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe",
             "-threads", "1", "-f", format_name, "-i", "pipe:0", "-t", str(MAX_SECONDS + 1),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=10,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise HTTPException(422, "Invalid recording") from None
    if not decoded:
        raise HTTPException(422, "Empty recording")
    if len(decoded) > SAMPLE_RATE * 2 * MAX_SECONDS:
        raise HTTPException(413, "Recording exceeds 30 seconds")
    samples = np.frombuffer(decoded, dtype="<i2").astype(np.float32) / 32768.0
    segments, _ = model.transcribe(
        samples, vad_filter=True, condition_on_previous_text=False, beam_size=2, hotwords="Abud",
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def speak(voice, text):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        voice.synthesize_wav(text, wav)
    return output.getvalue()


@app.post("/transcribe")
async def transcribe(request: Request):
    format_name = AUDIO_FORMATS.get(request.headers.get("content-type", "").split(";", 1)[0])
    if not format_name:
        raise HTTPException(415, "Unsupported media type")
    data = await read_bounded(request, 3 * 1024 * 1024)
    if compute.locked():
        raise HTTPException(429, "Voice worker busy")
    async with compute:
        text = await run_in_threadpool(recognize, request.app.state.whisper, data, format_name)
    return {"text": text}


@app.post("/synthesize")
async def synthesize(request: Request):
    try:
        text = (await read_bounded(request, 9600)).decode().strip()
    except UnicodeDecodeError:
        raise HTTPException(422, "Invalid text") from None
    if not text or len(text) > 2400:
        raise HTTPException(422, "Invalid text length")
    if compute.locked():
        raise HTTPException(429, "Voice worker busy")
    async with compute:
        audio = await run_in_threadpool(speak, request.app.state.piper, text)
    return Response(audio, media_type="audio/wav")
