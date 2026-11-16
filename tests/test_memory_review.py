import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from app import database, memory_review


class MemoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db_patch = patch.object(database, 'DATABASE_PATH', Path(self.temp.name) / 'memory.db')
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_database()

    def test_wording_unicode_reordering_negation_numbers_and_unrelated(self):
        self.assertEqual(memory_review.wording_match('KOPI susu', 'susu kopi')['similarity'], 1)
        self.assertEqual(memory_review.wording_match('Straße CAFÉ', 'STRASSE cafe\u0301')['similarity'], 1)
        self.assertIsNotNone(memory_review.wording_match('Saya suka kopi susu', 'Saya suka kopi ssu'))
        for proposed, existing in [('Saya suka kopi susu', 'Saya tidak suka kopi susu'), ('Jadwal rapat jam 10', 'Jadwal rapat jam 11')]:
            self.assertEqual(memory_review.wording_match(proposed, existing)['relation'], 'possible_conflict')
        self.assertIsNone(memory_review.wording_match('kopi susu', 'deploy aplikasi python'))
        self.assertIsNone(memory_review.wording_match('!!!', 'kopi susu'))

    def test_scope_category_exclusion_and_older_candidates(self):
        old = database.save_memory('alice', 'Saya suka kopi susu')
        database.save_memory('bob', 'Saya suka kopi susu')
        for i in range(105):
            database.save_memory('alice', f'tugas unik deploy {i}')
        rows = database.find_similar_memories('personal', 'susu kopi suka saya', user_id='alice')
        self.assertEqual([r['id'] for r in rows], [old])
        self.assertEqual(database.find_similar_memories('personal', 'Saya suka kopi susu', user_id='alice', exclude_memory_id=old), [])
        database.save_guild_memory('guild-b', 'Saya suka kopi susu')
        self.assertEqual(database.find_similar_memories('guild', 'Saya suka kopi susu', guild_id='guild-a'), [])
        database.save_global_memory('Saya suka kopi susu', category='private-category')
        self.assertEqual(database.find_similar_memories('global', 'Saya suka kopi susu'), [])
        self.assertEqual(len(database.find_similar_memories('global', 'Saya suka kopi susu', category='private-category')), 1)
        self.assertEqual(database.find_similar_memories('personal', 'Saya suka kopi susu'), [])
        self.assertEqual(database.find_similar_memories('guild', 'Saya suka kopi susu'), [])

    def test_ai_pool_can_include_paraphrases_without_shared_words(self):
        mid = database.save_memory('alice', 'Bekerja sebagai pengembang perangkat lunak')
        self.assertEqual(database.find_similar_memories('personal', 'Profesi programmer', user_id='alice'), [])
        rows = database.find_similar_memories('personal', 'Profesi programmer', user_id='alice', include_unmatched=True)
        self.assertEqual([row['id'] for row in rows], [mid])
        self.assertEqual(rows[0]['similarity'], 0)

    def test_candidates_read_only_bounded_and_validated(self):
        for i in range(15):
            database.save_memory('alice', f'Saya suka kopi susu setiap pagi {i}')
        with database.get_connection() as db:
            before = [tuple(r) for r in db.execute('SELECT * FROM memories')]
        self.assertEqual(len(database.find_similar_memories('personal', 'Saya suka kopi susu setiap pagi', user_id='alice', limit=999)), 10)
        with database.get_connection() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM memories')])
        for content in ('', ' ', 'x' * 1001, None):
            with self.assertRaises(ValueError):
                database.find_similar_memories('personal', content, user_id='alice')
        for mid in (True, -1, '1'):
            with self.assertRaises(ValueError):
                database.find_similar_memories('personal', 'kopi', user_id='alice', exclude_memory_id=mid)
        with self.assertRaises(ValueError):
            database.find_similar_memories('unknown', 'kopi')
        with self.assertRaises(ValueError):
            database.find_similar_memories('personal', 'kopi', limit=True)

    def test_http_authorization_origin_and_no_ai_before_grants(self):
        main = self.load_main()
        from fastapi.testclient import TestClient
        identity = {'is_creator': False, 'permissions': []}
        client = TestClient(main.app)
        payload = {'scope': 'personal', 'content': 'kopi susu', 'use_ai': True}
        headers = {'Origin': main.dashboard_auth.BASE_URL}
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')), patch.object(main, 'review_meaning', new_callable=AsyncMock) as ai, patch.object(main, '_memory_verify_guild', new_callable=AsyncMock) as verify:
            self.assertEqual(client.post('/dashboard/memory/similar', json=payload).status_code, 403)
            self.assertEqual(client.post('/dashboard/memory/similar', json=payload, headers=headers).status_code, 403)
            identity['permissions'] = [{'permission': 'memory.guild.view', 'scope_type': 'guild', 'scope_id': '101'}]
            self.assertEqual(client.post('/dashboard/memory/similar', json={**payload, 'scope': 'guild', 'guild_id': '202'}, headers=headers).status_code, 403)
            self.assertEqual(client.post('/dashboard/memory/similar', json={**payload, 'scope': 'global'}, headers=headers).status_code, 403)
            ai.assert_not_awaited()
            verify.assert_not_awaited()
            from fastapi import HTTPException
            verify.side_effect = HTTPException(503, 'Verification unavailable')
            self.assertEqual(client.post('/dashboard/memory/similar', json={**payload, 'scope': 'guild', 'guild_id': '101'}, headers=headers).status_code, 503)
            ai.assert_not_awaited()
        with patch.object(main.dashboard_auth, 'get_current_identity', return_value=None):
            self.assertEqual(client.post('/dashboard/memory/similar', json=payload, headers=headers).status_code, 401)

    def test_http_only_authorized_records_reach_ai_and_no_memory_mutation(self):
        main = self.load_main()
        from fastapi.testclient import TestClient
        identity = {'is_creator': False, 'permissions': [{'permission': 'memory.personal.view', 'scope_type': 'global', 'scope_id': '*'}]}
        database.save_memory('alice', 'kopi susu')
        database.save_memory('bob', 'kopi susu RAHASIA')
        database.save_guild_memory('101', 'kopi susu GUILD')
        with database.get_connection() as db:
            before = [tuple(r) for r in db.execute('SELECT * FROM memories')]
        async def review(content, candidates):
            self.assertEqual([r['content'] for r in candidates], ['kopi susu'])
            return candidates, 'complete'
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')), patch.object(main, 'review_meaning', side_effect=review) as ai:
            client = TestClient(main.app)
            args = {'headers': {'Origin': main.dashboard_auth.BASE_URL}, 'json': {'scope': 'personal', 'content': 'KOPI SUSU', 'use_ai': True}}
            result = client.post('/dashboard/memory/similar', **args)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['ai_status'], 'complete')
            ai.assert_awaited_once()
            args['json']['use_ai'] = False
            self.assertEqual(client.post('/dashboard/memory/similar', **args).json()['ai_status'], 'not_requested')
            self.assertEqual(ai.await_count, 1)
            args['json']['content'] = ' '
            self.assertEqual(client.post('/dashboard/memory/similar', **args).status_code, 400)
        with database.get_connection() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM memories')])

    @staticmethod
    def load_main():
        config = {name: 'test-only' for name in ('DISCORD_OAUTH_CLIENT_ID', 'DISCORD_OAUTH_CLIENT_SECRET', 'GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET', 'ABUD_SESSION_SECRET')}
        config['ABUD_BASE_URL'] = 'https://abud.example.test'
        with patch.dict(os.environ, config):
            return importlib.import_module('app.main')


class MeaningReviewTests(unittest.IsolatedAsyncioTestCase):
    async def run_response(self, raw):
        response = httpx.Response(200, json={'choices': [{'message': {'content': raw}}]}, request=httpx.Request('POST', 'https://router.example.test'))
        client = AsyncMock()
        client.post.return_value = response
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test-only'}), patch.object(memory_review.httpx, 'AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            result = await memory_review.review_meaning('kopi susu', [{'id': 7, 'content': 'susu kopi', 'source': 'direct'}])
        return result, client

    async def test_ai_annotations_keep_original_content_and_use_existing_router(self):
        result, client = await self.run_response(json.dumps({'matches': [{'id': 7, 'relation': 'duplicate', 'reason': 'Fakta sama', 'content': 'malicious replacement'}]}))
        self.assertEqual(result[1], 'complete')
        self.assertEqual(result[0][0]['content'], 'susu kopi')
        self.assertEqual(result[0][0]['ai_relation'], 'duplicate')
        request = client.post.call_args.kwargs['json']
        self.assertNotIn('tools', request)
        self.assertEqual(json.loads(request['messages'][1]['content'])['candidates'], [{'id': 7, 'content': 'susu kopi'}])

    async def test_invalid_or_hallucinated_output_falls_back(self):
        invalid = [
            'not JSON', json.dumps({'matches': []}),
            json.dumps({'matches': [{'id': 99, 'relation': 'duplicate', 'reason': 'x'}]}),
            json.dumps({'matches': [{'id': True, 'relation': 'duplicate', 'reason': 'x'}]}),
            json.dumps({'matches': [{'id': 7, 'relation': 'delete', 'reason': 'x'}]}),
            json.dumps({'matches': [{'id': 7, 'relation': 'duplicate', 'reason': ''}]}),
        ]
        for raw in invalid:
            result, _ = await self.run_response(raw)
            self.assertEqual(result[1], 'unavailable')
            self.assertNotIn('ai_relation', result[0][0])

    async def test_timeout_missing_key_and_empty_candidates(self):
        candidates = [{'id': 7, 'content': 'susu kopi'}]
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': ''}), patch.object(memory_review.httpx, 'AsyncClient') as factory:
            self.assertEqual(await memory_review.review_meaning('kopi susu', candidates), (candidates, 'not_configured'))
            factory.assert_not_called()
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test-only'}), patch.object(memory_review.httpx, 'AsyncClient') as factory:
            client = AsyncMock()
            client.post.side_effect = httpx.TimeoutException('timeout')
            factory.return_value.__aenter__.return_value = client
            self.assertEqual(await memory_review.review_meaning('kopi susu', candidates), (candidates, 'unavailable'))
            factory.reset_mock()
            self.assertEqual(await memory_review.review_meaning('kopi susu', []), ([], 'complete'))
            factory.assert_not_called()
