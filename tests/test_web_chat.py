"""HTTP integration checks with real sessions and disposable SQLite only."""

import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WebChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {
            k: "test-only"
            for k in (
                "DISCORD_OAUTH_CLIENT_ID",
                "DISCORD_OAUTH_CLIENT_SECRET",
                "GOOGLE_OAUTH_CLIENT_ID",
                "GOOGLE_OAUTH_CLIENT_SECRET",
                "ABUD_SESSION_SECRET",
            )
        }
        config.update(
            ABUD_BASE_URL="https://abud.example.test",
            ABUD_DATABASE_PATH=str(Path(self.temp.name) / "bootstrap.db"),
            ABUD_INTERNAL_API_KEY="internal-test",
        )
        env = patch.dict(os.environ, config)
        env.start()
        self.addCleanup(env.stop)
        self.main = importlib.import_module("app.main")
        from app import auth, database, web_chat

        self.auth, self.db, self.web = auth, database, web_chat
        dbpatch = patch.object(
            database, "DATABASE_PATH", Path(self.temp.name) / "test.db"
        )
        dbpatch.start()
        self.addCleanup(dbpatch.stop)
        database.init_database()
        web_chat.init_schema()
        from fastapi.testclient import TestClient

        self.client = TestClient(self.main.app, base_url=auth.BASE_URL)
        self.alice, self.alice_token = self.user("alice")
        self.bob, self.bob_token = self.user("bob")
        self.client.cookies.set(auth.SESSION_COOKIE, self.alice_token)
        self.headers = {"Origin": auth.BASE_URL}

    def user(self, name):
        owner = self.auth.get_or_create_identity(
            "google",
            {"id": name, "email": name + "@example.test", "email_verified": True},
        )
        with self.db.get_connection() as db:
            db.execute(
                "INSERT INTO auth_local_credentials(identity_id,username,username_normalized,password_hash,profile_completed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    owner,
                    name,
                    name,
                    "unused",
                    self.db.utc_now(),
                    self.db.utc_now(),
                    self.db.utc_now(),
                ),
            )
        return owner, self.auth.create_session(owner)

    def create(self):
        r = self.client.post("/web/chat/conversations", json={}, headers=self.headers)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def send(self, cid, **body):
        return self.client.post(
            f"/web/chat/conversations/{cid}/messages",
            json=body or {"message": "Hello"},
            headers=self.headers,
        )

    def test_google_session_crud_and_isolation(self):
        cid = self.create()
        self.assertFalse(self.client.get("/auth/me").json()["discord_linked"])
        self.assertEqual(
            self.client.patch(
                "/web/chat/conversations/" + cid,
                json={"title": "Work"},
                headers=self.headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/web/chat/conversations").json()[0]["title"], "Work"
        )
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        self.assertEqual(self.client.get("/web/chat/conversations").json(), [])
        for method, body in [
            ("get", None),
            ("patch", {"title": "Stolen"}),
            ("delete", None),
        ]:
            options = {"headers": self.headers}
            if body:
                options["json"] = body
            self.assertEqual(
                getattr(self.client, method)(
                    "/web/chat/conversations/" + cid, **options
                ).status_code,
                404,
            )
        self.assertEqual(self.send(cid).status_code, 404)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.assertEqual(
            self.client.delete(
                "/web/chat/conversations/" + cid, headers=self.headers
            ).status_code,
            200,
        )

    def test_auth_csrf_validation_and_internal_api_unchanged(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/web/chat/conversations").status_code, 401)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.assertEqual(
            self.client.post("/web/chat/conversations", json={}).status_code, 403
        )
        cid = self.create()
        for body in (
            {"message": " "},
            {"message": "x" * 6001},
            {"message": "Hi", "user_id": self.bob},
            {"message": "Hi", "guild_id": "123"},
        ):
            self.assertEqual(self.send(cid, **body).status_code, 422)
        self.assertEqual(
            self.client.post("/chat", json={"message": "Hi"}).status_code, 401
        )
        with self.db.get_connection() as db:
            db.execute(
                "UPDATE dashboard_sessions SET revoked_at=? WHERE identity_id=?",
                (self.db.utc_now(), self.alice),
            )
        self.assertEqual(self.client.get("/web/chat/conversations").status_code, 401)

    def test_stream_history_regeneration_and_memory_boundaries(self):
        cid = self.create()
        seen = []
        self.db.register_user("web:" + self.bob)
        self.db.save_memory("web:" + self.bob, "private-secret")
        self.db.save_guild_memory("guild-other", "guild-secret")

        async def stream(messages):
            seen.extend(messages)
            yield "Hello "
            yield "**world**"

        with patch.object(self.web, "model_stream", stream):
            response = self.send(cid, message="ingat kopi susu")
            self.assertIn('"type": "delta"', response.text)
            self.assertIn('"type": "done"', response.text)
            self.assertIn('"type": "memory_saved"', response.text)
            self.assertEqual(self.send(cid, regenerate=True).status_code, 200)
        history = self.client.get("/web/chat/conversations/" + cid).json()["messages"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(history[-1]["content"], "Hello **world**")
        self.assertNotIn("private-secret", str(seen))
        self.assertNotIn("guild-secret", str(seen))
        self.assertEqual(len(self.db.get_memories("web:" + self.alice)), 1)
        self.assertEqual(self.db.get_memories(self.alice), [])

    def test_error_retry_rate_limit_and_busy(self):
        cid = self.create()

        async def fail(messages):
            yield "partial"
            raise RuntimeError("SECRET provider failure")

        with patch.object(self.web, "model_stream", fail):
            r = self.send(cid)
        self.assertIn('"type": "error"', r.text)
        self.assertNotIn("SECRET", r.text)
        history = self.client.get("/web/chat/conversations/" + cid).json()["messages"]
        self.assertEqual(len(history), 1)
        self.assertEqual(self.send(cid).status_code, 409)
        with self.db.get_connection() as db:
            db.execute(
                "UPDATE web_conversations SET lease_until=? WHERE id=?", (10**12, cid)
            )
        self.assertEqual(self.send(cid, regenerate=True).status_code, 409)
        self.assertEqual(
            self.client.delete(
                "/web/chat/conversations/" + cid, headers=self.headers
            ).status_code,
            409,
        )
        with self.db.get_connection() as db:
            db.execute("UPDATE web_conversations SET lease_until=0 WHERE id=?", (cid,))
            db.execute(
                "UPDATE web_chat_limits SET count=10 WHERE identity_id=?", (self.alice,)
            )
        self.assertEqual(self.send(cid, regenerate=True).status_code, 429)


class RouterStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_sse_protocol_and_incomplete_stream(self):
        import httpx
        from app import web_chat

        client_type = httpx.AsyncClient
        bodies = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n',
            'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n',
            'data: {"error":{"message":"private upstream error"}}\n\n',
        ]
        for index, body in enumerate(bodies):

            def respond(request):
                self.assertEqual(
                    request.headers["Authorization"], "Bearer test-router-key"
                )
                self.assertTrue(__import__("json").loads(request.content)["stream"])
                return httpx.Response(200, text=body)

            transport = httpx.MockTransport(respond)

            def make_client(**kwargs):
                return client_type(transport=transport, **kwargs)

            with patch.dict(
                os.environ, {"NINE_ROUTER_API_KEY": "test-router-key"}
            ), patch.object(web_chat.httpx, "AsyncClient", make_client):
                if index == 0:
                    self.assertEqual(
                        [s async for s in web_chat.model_stream([])], ["Hello"]
                    )
                else:
                    with self.assertRaises(RuntimeError):
                        _ = [s async for s in web_chat.model_stream([])]


if __name__ == "__main__":
    unittest.main()
