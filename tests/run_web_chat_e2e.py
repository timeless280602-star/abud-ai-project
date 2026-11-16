"""Local HTTPS/browser integration check; never starts Discord or contacts OAuth/AI.

Run after frontend build: python tests/run_web_chat_e2e.py
Requires Node with Playwright, Chromium and openssl on PATH.
"""

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix="abud-e2e-") as directory:
        work = Path(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"https://127.0.0.1:{port}"
        os.environ.update(
            ABUD_DATABASE_PATH=str(work / "test.db"),
            ABUD_BASE_URL=url,
            ABUD_INTERNAL_API_KEY="test-only-internal",
            **{
                key: "test-only"
                for key in (
                    "DISCORD_OAUTH_CLIENT_ID",
                    "DISCORD_OAUTH_CLIENT_SECRET",
                    "GOOGLE_OAUTH_CLIENT_ID",
                    "GOOGLE_OAUTH_CLIENT_SECRET",
                    "ABUD_SESSION_SECRET",
                )
            },
        )
        from app import auth, database, web_chat
        from app.main import app
        import uvicorn

        database.init_database()
        web_chat.init_schema()
        tokens = []
        for name in ("alice", "bob"):
            owner = auth.get_or_create_identity(
                "google", {"id": name, "email_verified": True}
            )
            with database.get_connection() as db:
                db.execute(
                    "INSERT INTO auth_local_credentials(identity_id,username,username_normalized,password_hash,profile_completed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        owner,
                        name,
                        name,
                        "unused",
                        database.utc_now(),
                        database.utc_now(),
                        database.utc_now(),
                    ),
                )
            tokens.append(auth.create_session(owner))

        async def fixture_stream(messages):
            if messages[-1]["content"] == "[test-id]":
                yield "Halo, saya bisa membantu Anda dengan pertanyaan ini."
                return
            if messages[-1]["content"] == "[test-error]":
                yield "partial"
                raise TimeoutError("private fixture error")
            for text in ("Hello ", "**world**", "\n```js\nconst x = 1;\n```"):
                yield text
                await asyncio.sleep(0.1)

        web_chat.model_stream = fixture_stream
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(work / "key.pem"),
                "-out",
                str(work / "cert.pem"),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                ssl_keyfile=str(work / "key.pem"),
                ssl_certfile=str(work / "cert.pem"),
                log_level="error",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Local API did not start")
                time.sleep(0.05)
            subprocess.run(
                ["node", str(root / "tests/web_chat_e2e.cjs")],
                input=json.dumps({"url": url, "tokens": tokens}),
                text=True,
                check=True,
                timeout=90,
                cwd=root,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
