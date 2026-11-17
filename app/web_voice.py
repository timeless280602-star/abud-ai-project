"""Server-side clients for the optional local voice stack."""

import json
import os

import httpx

MAX_AUDIO = 3 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav"}


def enabled():
    return all(os.getenv(key) for key in (
        "ABUD_VOICE_WORKER_URL", "ABUD_VOICE_OLLAMA_URL", "ABUD_VOICE_OLLAMA_MODEL"
    ))


async def worker(path, *, content, content_type):
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5), trust_env=False) as client:
        response = await client.post(
            os.environ["ABUD_VOICE_WORKER_URL"].rstrip("/") + path,
            content=content,
            headers={"Content-Type": content_type},
        )
        response.raise_for_status()
        return response


async def model_stream(messages, *, max_tokens=512):
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5), trust_env=False) as client:
        async with client.stream(
            "POST",
            os.environ["ABUD_VOICE_OLLAMA_URL"].rstrip("/") + "/api/chat",
            json={
                "model": os.environ["ABUD_VOICE_OLLAMA_MODEL"],
                "messages": [{
                    **messages[0],
                    "content": messages[0]["content"]
                    + "\nThis reply will be read aloud. Use concise natural prose in the user's language.",
                }, *messages[1:]],
                "stream": True,
                "keep_alive": "30m",
                "options": {"num_predict": max_tokens},
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                frame = json.loads(line)
                if frame.get("error"):
                    raise RuntimeError("Local model failed")
                if part := frame.get("message", {}).get("content"):
                    yield part
                if frame.get("done") is True:
                    return
            raise RuntimeError("Local model stream ended early")


async def warmup():
    """Load the model and evaluate the shared prompt before serving voice turns."""
    from app.web_chat import compose_messages

    messages = compose_messages(
        [], "", None, "",
        "No memory action was performed on this turn. Do not claim it was.",
    )
    messages.append({"role": "user", "content": "Halo"})
    async for _ in model_stream(messages, max_tokens=1):
        pass
