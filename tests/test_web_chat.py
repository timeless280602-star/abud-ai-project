"""HTTP integration checks with real sessions and disposable SQLite only."""

import importlib
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace


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

    def test_archived_memory_save_does_not_abort_inference_or_restore(self):
        owner = "web:" + self.alice
        mid = self.db.save_memory(owner, "coffee preference", source="direct")
        self.db.set_memory_archived("personal", mid, True, user_id=owner)
        seen = []

        async def stream(messages):
            seen.extend(messages)
            yield "No memory was restored."

        with patch.object(self.web, "model_stream", stream):
            response = self.send(self.create(), message="remember coffee preference")
        self.assertIn('"type": "done"', response.text)
        self.assertIn('"type": "memory_not_saved"', response.text)
        self.assertNotIn('"type": "memory_saved"', response.text)
        self.assertIn("not saved or restored", str(seen))
        self.assertEqual(self.db.get_memories(owner), [])
        archived = self.db.search_memories("personal", "", user_id=owner, archived=True)
        self.assertEqual([(m["id"], m["revision"], m["source"]) for m in archived], [(mid, 1, "direct")])

    def test_ranked_active_memory_context_and_restore_metadata(self):
        owner = "web:" + self.alice
        mid = self.db.save_memory(owner, "coffee preference", source="dashboard")
        self.db.update_memory(owner, mid, "coffee preference revised")
        archived = self.db.save_memory(owner, "coffee archived secret")
        self.db.set_memory_archived("personal", archived, True, user_id=owner)
        global_id = self.db.save_global_memory("global archived secret")
        self.db.set_memory_archived("global", global_id, True)
        self.db.save_global_memory("public knowledge")
        for i in range(105):
            self.db.save_memory(owner, f"unrelated {i}")
        seen = []

        async def stream(messages):
            seen.extend(messages)
            yield "Answer"

        with patch.object(self.web, "model_stream", stream):
            self.assertIn('"type": "done"', self.send(self.create(), message="coffee preference").text)
        context = seen[1]["content"]
        self.assertIn("coffee preference revised", context)
        self.assertIn("public knowledge", context)
        self.assertNotIn("archived secret", context)
        self.db.set_memory_archived("personal", mid, True, user_id=owner)
        self.db.set_memory_archived("personal", mid, False, user_id=owner)
        self.assertEqual(self.db.save_memory(owner, "coffee preference revised", source="direct"), mid)
        record = self.db.search_memories("personal", "coffee preference", user_id=owner)[0]
        self.assertEqual((record["source"], record["revision"]), ("dashboard", 2))

    def test_stale_worker_cannot_replace_answer_or_release_new_lease(self):
        cid = self.create()

        async def success(messages):
            yield "Original answer"

        with patch.object(self.web, "model_stream", success):
            self.send(cid)

        async def stale(messages):
            with self.db.get_connection() as db:
                db.execute("UPDATE web_conversations SET lease_until=? WHERE id=?", (10**12, cid))
            yield "Stale replacement"

        with patch.object(self.web, "model_stream", stale):
            response = self.send(cid, regenerate=True)
        self.assertIn('"type": "error"', response.text)
        history = self.client.get("/web/chat/conversations/" + cid).json()["messages"]
        self.assertEqual(history[-1]["content"], "Original answer")
        with self.db.get_connection() as db:
            self.assertEqual(db.execute("SELECT lease_until FROM web_conversations WHERE id=?", (cid,)).fetchone()[0], 10**12)

    def test_stream_close_releases_lease_and_preserves_retryable_user_turn(self):
        cid = self.create()

        async def stream(messages):
            yield "Partial answer"
            yield "Never consumed"

        async def exercise():
            request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
            with patch.object(self.web, "identity", return_value=self.alice), patch.object(self.web, "model_stream", stream):
                response = self.web.send(cid, request, self.web.Turn(message="Hello"))
                self.assertIn('"type": "delta"', await anext(response.body_iterator))
                await response.body_iterator.aclose()

        asyncio.run(exercise())
        history = self.client.get("/web/chat/conversations/" + cid).json()["messages"]
        self.assertEqual([m["role"] for m in history], ["user"])
        with self.db.get_connection() as db:
            self.assertEqual(db.execute("SELECT lease_until FROM web_conversations WHERE id=?", (cid,)).fetchone()[0], 0)
        with patch.object(self.web, "model_stream", stream):
            self.assertIn('"type": "done"', self.send(cid, regenerate=True).text)

    def test_expired_disabled_and_incomplete_accounts(self):
        cid = self.create()
        with self.db.get_connection() as db:
            db.execute(
                "UPDATE dashboard_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE identity_id=?",
                (self.alice,),
            )
        self.assertEqual(self.send(cid).status_code, 401)
        token = self.auth.create_session(self.alice)
        self.client.cookies.set(self.auth.SESSION_COOKIE, token)
        with self.db.get_connection() as db:
            db.execute(
                "UPDATE auth_identities SET disabled_at=? WHERE identity_id=?",
                (self.db.utc_now(), self.alice),
            )
        self.assertEqual(self.client.get("/web/chat/conversations").status_code, 401)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        with self.db.get_connection() as db:
            db.execute(
                "DELETE FROM auth_local_credentials WHERE identity_id=?", (self.bob,)
            )
        self.assertEqual(
            self.client.post(
                "/web/chat/conversations", json={}, headers=self.headers
            ).status_code,
            403,
        )

    def test_failed_regeneration_preserves_answer_and_releases_lease(self):
        cid = self.create()

        async def success(messages):
            yield "Original answer"

        async def timeout(messages):
            yield "Incomplete replacement"
            raise TimeoutError("private timeout details")

        with patch.object(self.web, "model_stream", success):
            self.assertIn('"type": "done"', self.send(cid).text)
        before = self.client.get("/web/chat/conversations/" + cid).json()["messages"]
        with patch.object(self.web, "model_stream", timeout):
            response = self.send(cid, regenerate=True)
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn("private timeout details", response.text)
        self.assertEqual(
            self.client.get("/web/chat/conversations/" + cid).json()["messages"], before
        )
        with self.db.get_connection() as db:
            self.assertEqual(
                db.execute(
                    "SELECT lease_until FROM web_conversations WHERE id=?", (cid,)
                ).fetchone()[0],
                0,
            )
        with patch.object(self.web, "model_stream", success):
            self.assertIn('"type": "done"', self.send(cid, regenerate=True).text)
        self.assertEqual(
            len(self.client.get("/web/chat/conversations/" + cid).json()["messages"]), 2
        )

    def test_schema_reopen_and_thread_delete_preserve_discord_data(self):
        self.db.register_user("discord-user")
        self.db.save_message("discord-user", "user", "Discord history")
        cid = self.create()
        self.web.init_schema()
        self.web.init_schema()
        self.assertEqual(
            self.client.get("/web/chat/conversations/" + cid).status_code, 200
        )

        async def success(messages):
            yield "Web answer"

        with patch.object(self.web, "model_stream", success):
            self.send(cid)
        self.assertEqual(
            self.client.delete(
                "/web/chat/conversations/" + cid, headers=self.headers
            ).status_code,
            200,
        )
        with self.db.get_connection() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM web_messages WHERE conversation_id=?", (cid,)
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT content FROM conversations WHERE user_id=?",
                    ("discord-user",),
                ).fetchone()[0],
                "Discord history",
            )


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
