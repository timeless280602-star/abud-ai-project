"""Internal /chat voice mode keeps existing auth, memory boundaries, and history."""

import io
import json
import os
import unittest
from unittest.mock import patch

import test_web_chat as fixtures


class DiscordVoiceAPITests(unittest.TestCase):
    setUp = fixtures.WebChatTests.setUp
    user = fixtures.WebChatTests.user

    def body(self, **overrides):
        return {
            "message": "apa kabar",
            "user_id": "111",
            "username": "Tester",
            "guild_id": "222",
            "guild_name": "Guild",
            "guild_owner_id": "333",
            "channel_id": "444",
            "context_type": "guild",
            "response_mode": "voice",
            **overrides,
        }

    def test_voice_route_requires_existing_internal_key(self):
        self.assertEqual(self.client.post("/chat", json=self.body()).status_code, 401)

    def test_voice_prompt_and_history_are_isolated_per_speaker_and_channel(self):
        captured = []
        self.db.save_memory("111", "suka kopi")
        self.db.save_memory("999", "PRIVATE_BOB_MEMORY")

        def respond(request, **kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(
                json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "Baik, lu gimana?"},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ).encode()
            )

        with (
            patch.dict(os.environ, {"NINE_ROUTER_API_KEY": "fixture"}),
            patch.object(self.main.urllib.request, "urlopen", respond),
        ):
            for message in ("apa kabar", "lanjut obrolannya"):
                result = self.client.post(
                    "/chat",
                    json=self.body(message=message),
                    headers={"Authorization": "Bearer internal-test"},
                )
                self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(captured[0]["max_tokens"], 350)
        self.assertIn("MODE VOICE CHANNEL", captured[0]["messages"][0]["content"])
        self.assertIn("suka kopi", json.dumps(captured[0]["messages"]))
        self.assertNotIn("PRIVATE_BOB_MEMORY", json.dumps(captured[0]["messages"]))
        self.assertTrue(any(m["role"] == "assistant" for m in captured[1]["messages"]))
        self.assertEqual(
            len(
                self.db.get_recent_messages(
                    "111", guild_id="222", channel_id="444", context_type="guild"
                )
            ),
            4,
        )
        self.assertEqual(
            self.db.get_recent_messages(
                "999", guild_id="222", channel_id="444", context_type="guild"
            ),
            [],
        )
        self.assertEqual(
            self.db.get_recent_messages(
                "111", guild_id="222", channel_id="555", context_type="guild"
            ),
            [],
        )

    def test_text_mode_keeps_existing_model_budget_and_no_voice_prompt(self):
        captured = []

        def respond(request, **kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(
                b'{"choices":[{"message":{"content":"Halo"},"finish_reason":"stop"}]}'
            )

        with (
            patch.dict(os.environ, {"NINE_ROUTER_API_KEY": "fixture"}),
            patch.object(self.main.urllib.request, "urlopen", respond),
        ):
            body = self.body()
            del body["response_mode"]
            result = self.client.post(
                "/chat", json=body, headers={"Authorization": "Bearer internal-test"}
            )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn("max_tokens", captured[0])
        self.assertNotIn("MODE VOICE CHANNEL", captured[0]["messages"][0]["content"])

    def test_unknown_response_mode_is_rejected(self):
        result = self.client.post(
            "/chat",
            json=self.body(response_mode="arbitrary"),
            headers={"Authorization": "Bearer internal-test"},
        )
        self.assertEqual(result.status_code, 422)


if __name__ == "__main__":
    unittest.main()
