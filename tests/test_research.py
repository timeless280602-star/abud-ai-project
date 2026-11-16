import os
import unittest
from unittest.mock import patch

import httpx

from app import research


class ResearchTests(unittest.TestCase):
    def test_requires_an_explicit_command(self):
        self.assertIsNone(research.intent("Bisa cari web tentang cuaca?"))
        self.assertEqual(research.intent("Cek fakta: klaim publik"), "klaim publik")

    @patch.dict(os.environ, {"ABUD_TAVILY_API_KEY": "test-key"})
    @patch("app.research.httpx.post")
    def test_uses_search_excerpts_and_appends_real_links(self, post):
        search_result = httpx.Response(
            200, request=httpx.Request("POST", research.SEARCH_URL),
            json={"results": [
                {"title": "Sumber", "url": "https://example.org/article", "content": "<b>Bukti</b>."},
                {"url": "javascript:alert(1)", "content": "Bad link"},
            ]},
        )
        summary_result = httpx.Response(
            200, request=httpx.Request("POST", "https://example.org/chat"),
            json={"choices": [{"message": {"content": "Bukti terbatas [1]."}}]},
        )

        post.side_effect = [search_result, summary_result]

        result = research.reply("klaim publik")

        self.assertIn("Bukti terbatas [1].", result)
        self.assertIn("<https://example.org/article>", result)
        self.assertNotIn("javascript:", result)
        search, synthesize = post.call_args_list
        self.assertEqual(search.args[0], "https://api.tavily.com/search")
        self.assertEqual(search.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(search.kwargs["json"], {
            "query": "klaim publik",
            "search_depth": "basic",
            "max_results": 6,
            "auto_parameters": False,
        })
        payload = synthesize.kwargs["json"]
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["max_tokens"], 1200)
        self.assertIn("Bukti.", payload["messages"][1]["content"])

    @patch.dict(os.environ, {"ABUD_TAVILY_API_KEY": "test-key"})
    @patch("app.research.httpx.post")
    def test_keeps_sources_when_model_reports_truncation(self, post):
        post.side_effect = [
            httpx.Response(
                200, request=httpx.Request("POST", research.SEARCH_URL),
                json={"results": [
                    {"url": "https://example.org/article", "content": "Bukti."},
                ]},
            ),
            httpx.Response(
                200, request=httpx.Request("POST", "https://example.org/chat"),
                json={"choices": [{
                    "finish_reason": "length",
                    "message": {"content": "Raman mampu menganalisis"},
                }]},
            ),
        ]

        result = research.reply("perbandingan FTIR dan Raman")

        self.assertIn("Ringkasan otomatis terpotong.", result)
        self.assertIn("<https://example.org/article>", result)
        self.assertNotIn("Raman mampu menganalisis", result)
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {"ABUD_TAVILY_API_KEY": "test-key"})
    @patch("app.research.httpx.post")
    def test_quota_failure_skips_synthesis(self, post):
        for status in (429, 432):
            with self.subTest(status=status):
                post.reset_mock(return_value=True)
                post.return_value = httpx.Response(status)
                self.assertIn("kuota", research.reply("klaim publik"))
                post.assert_called_once()
