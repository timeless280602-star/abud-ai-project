"""Run with ABUD_DATABASE_PATH pointing to a disposable local path."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app import database, tools


class MemoryDatabaseSetup:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'memory.db'
        self.db_patch = patch.object(database, 'DATABASE_PATH', self.path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_database()
        self.context = {'user_id': 'alice', 'guild_id': 'guild-a', 'context_type': 'guild'}


class MemorySearchTests(MemoryDatabaseSetup, unittest.TestCase):
    def test_phrase_then_word_overlap_then_newest(self):
        phrase = database.save_memory('alice', 'Minum KOPI susu setiap pagi')
        overlap = database.save_memory('alice', 'susu dengan kopi')
        partial = database.save_memory('alice', 'kopi hitam')
        newest = database.save_memory('alice', 'kopi sore')
        database.save_memory('alice', 'kopian bersusu')
        rows = database.search_memories('personal', 'kopi susu', user_id='alice')
        self.assertEqual([r['id'] for r in rows], [phrase, overlap, newest, partial])

    def test_unicode_casefold_normalization_and_phrase_whitespace(self):
        memory_id = database.save_memory('alice', 'Straße CAFÉ\n  susu')
        for query in ('STRASSE', 'cafe\u0301 SUSU', 'ＣＡＦÉ susu'):
            with self.subTest(query=query):
                self.assertEqual(database.search_memories('personal', query, user_id='alice')[0]['id'], memory_id)

    def test_old_matches_are_ranked_before_limit_and_tool_shape_stays_stable(self):
        old = database.save_memory('alice', 'kopi susu')
        for i in range(110):
            database.save_memory('alice', f'kopi catatan {i}')
        result = tools.execute_tool('search_memory', {'scope': 'personal', 'query': 'kopi susu'}, self.context)
        self.assertEqual(result['results'][0], {'id': old, 'content': 'kopi susu'})
        self.assertEqual(result['total_found'], 5)
        self.assertEqual(len(result['results']), 5)

    def test_personal_and_guild_isolation(self):
        database.save_memory('bob', 'rahasia kopi susu')
        database.save_guild_memory('guild-b', 'rahasia kopi susu')
        for scope in ('personal', 'guild'):
            self.assertEqual(tools.search_memory(scope, 'kopi', self.context)['results'], [])
        own = database.save_guild_memory('guild-a', 'kopi susu')
        self.assertEqual(tools.search_memory('guild', 'kopi', self.context)['results'][0]['id'], own)
        self.assertEqual(tools.search_memory('guild', 'kopi', {**self.context, 'context_type': 'dm'})['results'], [])
        self.assertEqual(tools.search_memory('personal', 'kopi', {})['results'], [])
        with self.assertRaises(ValueError):
            tools.search_memory('global', 'kopi', self.context)
        self.assertEqual(database.search_memories('personal', 'kopi'), [])
        self.assertEqual(database.search_memories('guild', 'kopi'), [])

    def test_global_category_empty_query_and_literal_special_characters(self):
        old = database.save_global_memory('Minuman pagi', category='KOPI SUSU')
        new = database.save_global_memory('kopi hitam')
        self.assertEqual(database.search_memories('global', 'kopi susu')[0]['id'], old)
        self.assertEqual(database.search_memories('global', '  ')[0]['id'], new)
        for query in ('%_', '!!!', "' OR 1=1 --", 'tidakada'):
            self.assertEqual(database.search_memories('global', query), [])

    def test_limits_validation_and_content_truncation(self):
        for i in range(105):
            database.save_memory('alice', f'kopi {i} ' + 'x' * 600)
        for limit, expected in ((-1, 1), (0, 1), (2, 2), (10000, 100)):
            self.assertEqual(len(database.search_memories('personal', 'kopi', user_id='alice', limit=limit)), expected)
        for limit in (True, None, '5', 1.5):
            with self.assertRaises(ValueError):
                database.search_memories('personal', 'kopi', limit=limit)
        for query in (None, 123, 'a' * 201):
            with self.assertRaises(ValueError):
                database.search_memories('personal', query, user_id='alice')
        for query in ('', 'a', 'a' * 101, None):
            with self.assertRaises(ValueError):
                tools.search_memory('personal', query, self.context)
        self.assertEqual(len(tools.search_memory('personal', 'kopi', self.context)['results'][0]['content']), 500)
        with self.assertRaises(ValueError):
            database.search_memories('unknown', 'kopi')

    def test_existing_database_reopen_preserves_schema_and_data(self):
        memory_id = database.save_memory('alice', 'kopi susu')
        with database.get_connection() as db:
            before = [tuple(r) for r in db.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name')]
            data = [tuple(r) for r in db.execute('SELECT * FROM memories')]
        self.assertEqual(database.search_memories('personal', 'SUSU kopi', user_id='alice')[0]['id'], memory_id)
        database.init_database()
        with database.get_connection() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name')])
            self.assertEqual(data, [tuple(r) for r in db.execute('SELECT * FROM memories')])


class DashboardSearchTests(MemoryDatabaseSetup, unittest.TestCase):
    # Share only database setup; tests below exercise the real HTTP permission flow.
    def test_dashboard_permissions_and_ranked_results(self):
        config = {name: 'test-only' for name in ('DISCORD_OAUTH_CLIENT_ID', 'DISCORD_OAUTH_CLIENT_SECRET', 'GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET', 'ABUD_SESSION_SECRET')}
        config['ABUD_BASE_URL'] = 'https://abud.example.test'
        with patch.dict(os.environ, config):
            main = importlib.import_module('app.main')
        from fastapi.testclient import TestClient
        identity = {'is_creator': False, 'permissions': []}
        old = database.save_memory('alice', 'kopi susu')
        for i in range(105):
            database.save_memory('alice', f'kopi {i}')
        database.save_guild_memory('guild-a', 'kopi susu')
        database.save_global_memory('kopi susu')
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')), patch.object(main, '_memory_verify_guild', new_callable=AsyncMock) as verify:
            # No lifespan: never start services, OAuth calls or Discord.
            client = TestClient(main.app)
            self.assertEqual(client.get('/dashboard/memory?q=kopi').status_code, 403)
            identity['permissions'] = [{'permission': 'memory.personal.view', 'scope_type': 'global', 'scope_id': '*'}]
            result = client.get('/dashboard/memory?q=kopi%20susu')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['items'][0]['id'], old)
            self.assertEqual(result.json()['count'], 100)
            self.assertEqual(client.get('/dashboard/memory?scope=guild&guild_id=guild-a&q=kopi').status_code, 403)
            verify.assert_not_awaited()
            identity['permissions'] = [{'permission': 'memory.guild.view', 'scope_type': 'guild', 'scope_id': 'guild-a'}]
            self.assertEqual(client.get('/dashboard/memory?scope=guild&guild_id=guild-a&q=kopi').status_code, 200)
            verify.assert_awaited_once_with('guild-a', 'alice')
            self.assertEqual(client.get('/dashboard/memory?scope=guild&guild_id=guild-b&q=kopi').status_code, 403)
            self.assertEqual(verify.await_count, 1)
            from fastapi import HTTPException
            verify.side_effect = HTTPException(status_code=403, detail='Not a member')
            self.assertEqual(client.get('/dashboard/memory?scope=guild&guild_id=guild-a&q=kopi').status_code, 403)
            self.assertEqual(client.get('/dashboard/memory?scope=global&q=kopi').status_code, 403)
            # Creator privilege alone does not replace linked Discord identity.
            identity['is_creator'] = True
            self.assertEqual(client.get('/dashboard/memory?scope=global&q=kopi').status_code, 403)
        with patch.object(main.dashboard_auth, 'get_current_identity', return_value=None):
            self.assertEqual(client.get('/dashboard/memory?q=kopi').status_code, 401)
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, None)):
            self.assertEqual(client.get('/dashboard/memory?q=kopi').status_code, 403)
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, main.dashboard_auth.CREATOR_DISCORD_ID)):
            self.assertEqual(client.get('/dashboard/memory?scope=global&q=kopi').status_code, 200)
            self.assertEqual(client.get('/dashboard/memory?q=' + 'x' * 201).status_code, 400)


if __name__ == '__main__':
    unittest.main()
