"""Server-side clients for the optional local voice stack."""

import json
import os
from contextlib import aclosing

import httpx

MAX_AUDIO = 3 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav"}


def provider():
    return os.getenv("ABUD_VOICE_LLM_PROVIDER", "ollama")


def enabled():
    if not os.getenv("ABUD_VOICE_WORKER_URL"):
        return False
    if provider() == "router":
        return bool(os.getenv("NINE_ROUTER_API_KEY"))
    return provider() == "ollama" and all(os.getenv(key) for key in (
        "ABUD_VOICE_OLLAMA_URL", "ABUD_VOICE_OLLAMA_MODEL",
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
    messages = [{
        **messages[0],
        "content": messages[0]["content"]
        + "\nThis reply will be read aloud. Use concise natural prose in the user's language."
        + " The user may be speaking colloquial Indonesian. If the transcript is unclear,"
        + " ask a brief clarification instead of inventing their intent.",
    }, *messages[1:]]
    if provider() == "router":
        from app.web_chat import model_stream as router_stream

        async with aclosing(router_stream(messages)) as stream:
            async for text in stream:
                yield text
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5), trust_env=False) as client:
        async with client.stream(
            "POST",
            os.environ["ABUD_VOICE_OLLAMA_URL"].rstrip("/") + "/api/chat",
            json={
                "model": os.environ["ABUD_VOICE_OLLAMA_MODEL"],
                "messages": messages,
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
    if provider() != "ollama":
        return
    from app.web_chat import compose_messages

    messages = compose_messages(
        [], "", None, "",
        "No memory action was performed on this turn. Do not claim it was.",
    )
    messages.append({"role": "user", "content": "Halo"})
    async for _ in model_stream(messages, max_tokens=1):
        pass
