"""Feedback is private, transactional personal memory, never global training."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

# Reuse the real-session/disposable-DB fixture without rediscovering its tests.
import test_web_chat as chat_tests


def answered(self, text="Here is a concise answer."):
    cid = self.create()
    async def stream(messages):
        yield text
    with patch.object(self.web, 'model_stream', stream):
        self.send(cid, message='Explain simply')
    messages = self.client.get('/web/chat/conversations/' + cid).json()['messages']
    return cid, messages


def rate(self, cid, mid, body, **options):
    return self.client.post(f'/web/chat/conversations/{cid}/messages/{mid}/feedback',
                            json=body, headers=options.pop('headers', self.headers), **options)


class FeedbackTests(unittest.TestCase):
    setUp = chat_tests.WebChatTests.setUp
    user = chat_tests.WebChatTests.user
    create = chat_tests.WebChatTests.create
    send = chat_tests.WebChatTests.send

    def test_idempotent_rating_and_replacement_update_one_memory(self):
        cid, messages = answered(self)
        mid = messages[-1]['id']
        for _ in range(2):
            self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 200)
        memories = self.db.get_memories('web:' + self.alice)
        self.assertEqual(len(memories), 1)
        self.assertEqual((memories[0]['source'], memories[0]['revision']), ('direct', 1))
        self.assertEqual(json.loads(memories[0]['content'])['rating'], 'good')
        result = rate(self, cid, mid, {'rating': 'bad', 'reason': 'Use shorter examples'})
        self.assertEqual(result.status_code, 200, result.text)
        memory = self.db.get_memories('web:' + self.alice)[0]
        self.assertEqual(memory['id'], memories[0]['id'])
        self.assertEqual(memory['revision'], 2)
        self.assertEqual(json.loads(memory['content'])['reason'], 'Use shorter examples')
        loaded = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        self.assertEqual((loaded['rating'], loaded['feedback_reason']), ('bad', 'Use shorter examples'))
        self.assertEqual(self.db.get_memories(self.alice), [])
        self.assertEqual(self.db.get_global_memories(), [])

    def test_feedback_auth_ownership_origin_and_validation(self):
        cid, messages = answered(self)
        mid = messages[-1]['id']
        self.client.cookies.clear()
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 401)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 404)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}, headers={}).status_code, 403)
        self.assertEqual(rate(self, self.create(), mid, {'rating': 'good'}).status_code, 404)
        self.assertEqual(rate(self, cid, messages[0]['id'], {'rating': 'good'}).status_code, 404)
        for body in ({'rating': 'bad'}, {'rating': 'bad', 'reason': '  '},
                     {'rating': 'bad', 'reason': 'x' * 501}, {'rating': 'great'},
                     {'rating': 'good', 'user_id': self.bob}, {'rating': 'good', 'reason': 'unexpected'}):
            self.assertEqual(rate(self, cid, mid, body).status_code, 422)
        self.assertEqual(self.db.get_memories('web:' + self.alice), [])

    def test_feedback_guides_future_threads_only_for_its_owner_and_active_memory(self):
        cid, messages = answered(self)
        mid = messages[-1]['id']
        rate(self, cid, mid, {'rating': 'bad', 'reason': 'Unique feedback: use short paragraphs'})
        self.assertIn('Unique feedback', self.web.feedback_context(self.alice))
        self.assertEqual(self.web.feedback_context(self.bob), '')
        seen = []
        async def stream(context):
            seen.extend(context)
            yield 'Next answer'
        with patch.object(self.web, 'model_stream', stream):
            self.send(self.create(), message='A different topic')
        self.assertIn('Unique feedback', str(seen))
        memory = self.db.get_memories('web:' + self.alice)[0]
        self.db.set_memory_archived('personal', memory['id'], True, user_id='web:' + self.alice)
        self.assertEqual(self.web.feedback_context(self.alice), '')
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 409)
        self.db.set_memory_archived('personal', memory['id'], False, user_id='web:' + self.alice)
        self.assertIn('Unique feedback', self.web.feedback_context(self.alice))
        self.db.delete_memory('web:' + self.alice, memory['id'])
        self.assertEqual(self.web.feedback_context(self.alice), '')

    def test_feedback_survives_regeneration_and_thread_delete_as_personal_memory(self):
        cid, messages = answered(self)
        mid = messages[-1]['id']
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 200)
        async def stream(context):
            yield 'New answer'
        with patch.object(self.web, 'model_stream', stream):
            self.send(cid, regenerate=True)
        loaded = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        self.assertIsNone(loaded['rating'])
        self.assertEqual(rate(self, cid, mid, {'rating': 'good'}).status_code, 404)
        self.client.delete('/web/chat/conversations/' + cid, headers=self.headers)
        self.assertEqual(len(self.db.get_memories('web:' + self.alice)), 1)
        self.assertIn('Here is a concise answer', self.web.feedback_context(self.alice))
        self.web.init_schema()
        self.web.init_schema()
        with self.db.get_connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_concurrent_duplicate_feedback_has_one_memory(self):
        cid, messages = answered(self)
        mid = messages[-1]['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: rate(self, cid, mid, {'rating': 'good'}).status_code, range(2)))
        self.assertEqual(results, [200, 200])
        self.assertEqual(len(self.db.get_memories('web:' + self.alice)), 1)
