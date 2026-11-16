import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from app import database, tools
import test_memory_metadata as metadata_tests


class MemoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db_patch = patch.object(database, 'DATABASE_PATH', Path(self.temp.name) / 'memory.db')
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_database()

    def test_archive_restore_all_scopes_preserve_content_metadata(self):
        cases = [
            ('personal', lambda: database.save_memory('alice', 'kopi susu', source='direct'), lambda: database.get_memories('alice'), {'user_id': 'alice'}),
            ('guild', lambda: database.save_guild_memory('101', 'kopi susu', 'alice', source='dashboard'), lambda: database.get_guild_memories('101'), {'guild_id': '101'}),
            ('global', lambda: database.save_global_memory('kopi susu', created_by_user_id='alice', source='auto'), database.get_global_memories, {}),
        ]
        for scope, save, read, owner in cases:
            with self.subTest(scope=scope):
                mid = save()
                before = read()[0]
                self.assertTrue(database.set_memory_archived(scope, mid, True, **owner))
                self.assertEqual(read(), [])
                self.assertEqual(database.search_memories(scope, 'kopi susu', **owner), [])
                self.assertEqual(database.find_similar_memories(scope, 'kopi susu', include_unmatched=True, **owner), [])
                archived = database.search_memories(scope, 'kopi susu', archived=True, **owner)[0]
                self.assertTrue(archived['archived_at'])
                self.assertEqual({**archived, 'archived_at': None}, before)
                self.assertFalse(database.set_memory_archived(scope, mid, True, **owner))
                self.assertEqual(database.search_memories(scope, '', archived=True, **owner)[0]['archived_at'], archived['archived_at'])
                self.assertTrue(database.set_memory_archived(scope, mid, False, **owner))
                self.assertEqual(read()[0], before)
                self.assertEqual(database.search_memories(scope, '', archived=True, **owner), [])

    def test_save_edit_delete_cannot_bypass_archive(self):
        cases = [
            ('personal', lambda: database.save_memory('alice', 'kopi susu'), lambda mid: database.update_memory('alice', mid, 'changed'), lambda mid: database.delete_memory('alice', mid), {'user_id': 'alice'}),
            ('guild', lambda: database.save_guild_memory('101', 'kopi susu'), lambda mid: database.update_guild_memory('101', mid, 'changed'), lambda mid: database.delete_guild_memory('101', mid), {'guild_id': '101'}),
            ('global', lambda: database.save_global_memory('kopi susu'), lambda mid: database.update_global_memory(mid, 'changed'), database.delete_global_memory, {}),
        ]
        for scope, save, edit, delete, owner in cases:
            mid = save()
            database.set_memory_archived(scope, mid, True, **owner)
            with self.assertRaises(database.ArchivedMemoryError):
                save()
            self.assertFalse(edit(mid))
            self.assertFalse(delete(mid))
            self.assertEqual(database.search_memories(scope, '', archived=True, **owner)[0]['content'], 'kopi susu')
        with self.assertRaises(database.ArchivedMemoryError):
            tools.save_memory_tool('personal', 'kopi susu', {'user_id': 'alice'})
        self.assertEqual(tools.search_memory('personal', 'kopi susu', {'user_id': 'alice'})['results'], [])
        self.assertEqual(tools.list_memory_tool('personal', {'user_id': 'alice'})['memories'], [])

    def test_restore_conflict_is_atomic_under_concurrent_restores(self):
        mid = database.save_memory('alice', 'kopi susu')
        database.set_memory_archived('personal', mid, True, user_id='alice')
        # Legacy databases may contain identical duplicates; preserve both archives.
        with database.get_connection() as db:
            second = db.execute('''INSERT INTO memories(user_id, content, created_at, updated_at, source, revision, archived_at)
                SELECT user_id, content, created_at, updated_at, source, revision, archived_at FROM memories WHERE id = ?''', (mid,)).lastrowid
        def restore(target):
            try:
                return database.set_memory_archived('personal', target, False, user_id='alice')
            except database.ArchivedMemoryError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(restore, [mid, second]))
        self.assertCountEqual(results, [True, 'conflict'])
        self.assertEqual(len(database.get_memories('alice')), 1)
        self.assertEqual(len(database.search_memories('personal', '', archived=True, user_id='alice')), 1)

    def test_owner_guards_validation_and_restart_preservation(self):
        mid = database.save_memory('alice', 'kopi susu')
        self.assertFalse(database.set_memory_archived('personal', mid, True, user_id='bob'))
        self.assertFalse(database.set_memory_archived('personal', mid, True))
        for mid_invalid, state in [(True, True), (0, True), ('1', True), (mid, 'false')]:
            with self.assertRaises(ValueError):
                database.set_memory_archived('personal', mid_invalid, state, user_id='alice')
        with self.assertRaises(ValueError):
            database.search_memories('personal', '', user_id='alice', archived='false')
        database.set_memory_archived('personal', mid, True, user_id='alice')
        with database.get_connection() as db:
            before = [tuple(row) for row in db.execute('SELECT * FROM memories')]
        database.init_database()
        database.init_database()
        with database.get_connection() as db:
            self.assertEqual(before, [tuple(row) for row in db.execute('SELECT * FROM memories')])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_dashboard_archive_permissions_origin_membership_and_owner(self):
        main = metadata_tests.MemoryMetadataTests.load_main()
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        headers = {'Origin': main.dashboard_auth.BASE_URL}
        payload = {'scope': 'personal', 'memory_id': database.save_memory('bob', 'foreign memory'), 'archived': True}
        identity = {'identity_id': 'reader', 'is_creator': False, 'permissions': [{'permission': 'memory.personal.view', 'scope_type': 'global', 'scope_id': '*'}]}
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')), patch.object(main, '_memory_verify_guild', new_callable=AsyncMock) as verify:
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload).status_code, 403)
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 403)
            identity['permissions'][0]['permission'] = 'memory.personal.manage'
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 404)
            identity['permissions'] = [{'permission': 'memory.guild.manage', 'scope_type': 'guild', 'scope_id': '101'}]
            self.assertEqual(client.post('/dashboard/memory/archive', json={**payload, 'scope': 'guild', 'guild_id': '202'}, headers=headers).status_code, 403)
            verify.assert_not_awaited()
            from fastapi import HTTPException
            verify.side_effect = HTTPException(503, 'Unavailable')
            self.assertEqual(client.post('/dashboard/memory/archive', json={**payload, 'scope': 'guild', 'guild_id': '101'}, headers=headers).status_code, 503)
            self.assertEqual(client.post('/dashboard/memory/archive', json={**payload, 'scope': 'global'}, headers=headers).status_code, 403)
            identity['is_creator'] = True
            self.assertEqual(client.post('/dashboard/memory/archive', json={**payload, 'scope': 'global'}, headers=headers).status_code, 403)
        with patch.object(main.dashboard_auth, 'get_current_identity', return_value=None):
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 401)
        self.assertEqual(database.get_memories('bob')[0]['content'], 'foreign memory')

    def test_dashboard_archive_restore_audit_and_duplicate_save_conflict(self):
        main = metadata_tests.MemoryMetadataTests.load_main()
        from fastapi.testclient import TestClient
        identity = {'identity_id': 'operator', 'is_creator': False, 'permissions': [{'permission': 'memory.personal.manage', 'scope_type': 'global', 'scope_id': '*'}]}
        mid = database.save_memory('alice', 'kopi susu', source='direct')
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')):
            client = TestClient(main.app)
            headers = {'Origin': main.dashboard_auth.BASE_URL}
            payload = {'scope': 'personal', 'memory_id': mid, 'archived': True}
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
            self.assertEqual(client.get('/dashboard/memory').json()['items'], [])
            self.assertEqual(client.get('/dashboard/memory?archived=true&q=kopi').json()['items'][0]['id'], mid)
            self.assertEqual(client.post('/dashboard/memory', json={'scope': 'personal', 'content': 'kopi susu'}, headers=headers).status_code, 409)
            payload['archived'] = False
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
            self.assertEqual(client.get('/dashboard/memory').json()['items'][0]['revision'], 1)
            self.assertEqual(client.get('/dashboard/memory?archived=true').json()['items'], [])
        with database.get_connection() as db:
            actions = [row[0] for row in db.execute('SELECT action FROM dashboard_audit_logs ORDER BY id')]
        self.assertEqual(actions, ['memory.archive', 'memory.restore'])

    def test_dashboard_guild_and_global_archive_restore(self):
        main = metadata_tests.MemoryMetadataTests.load_main()
        from fastapi.testclient import TestClient
        identity = {'identity_id': 'guild-operator', 'is_creator': False, 'permissions': [{'permission': 'memory.guild.view', 'scope_type': 'guild', 'scope_id': '101'}]}
        mid = database.save_guild_memory('101', 'guild fact', source='direct')
        client = TestClient(main.app)
        headers = {'Origin': main.dashboard_auth.BASE_URL}
        payload = {'scope': 'guild', 'guild_id': '101', 'memory_id': mid, 'archived': True}
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, 'alice')), patch.object(main, '_memory_verify_guild', new_callable=AsyncMock):
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 403)
            identity['permissions'][0]['permission'] = 'memory.guild.manage'
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
            self.assertEqual(client.get('/dashboard/memory?scope=guild&guild_id=101&archived=true').json()['items'][0]['id'], mid)
            payload['archived'] = False
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
        mid = database.save_global_memory('global fact')
        payload = {'scope': 'global', 'memory_id': mid, 'archived': True}
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, tools.GLOBAL_MEMORY_OWNER_ID)):
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
            self.assertEqual(client.get('/dashboard/memory?scope=global&archived=true').json()['items'][0]['id'], mid)
            payload['archived'] = False
            self.assertEqual(client.post('/dashboard/memory/archive', json=payload, headers=headers).status_code, 200)
        self.assertEqual(database.get_guild_memories('101')[0]['source'], 'direct')
        self.assertEqual(database.get_global_memories()[0]['id'], mid)

    def test_auto_save_does_not_revive_archived_memory(self):
        main = metadata_tests.MemoryMetadataTests.load_main()
        mid = database.save_memory('alice', 'kopi susu')
        database.set_memory_archived('personal', mid, True, user_id='alice')
        response = {'choices': [{'message': {'content': json.dumps({'memories': [{'scope': 'personal', 'content': 'kopi susu'}]})}}]}
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test-only'}), patch.object(main.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            result = main.auto_save_memory_endpoint(main.AutoSaveRequest(message='Saya suka kopi susu', user_id='alice'))
        self.assertEqual(result['memory_events'], [])
        self.assertEqual(database.get_memories('alice'), [])
        self.assertEqual(len(database.search_memories('personal', '', archived=True, user_id='alice')), 1)

    def test_chat_memory_blocks_exclude_archives_in_all_scopes(self):
        main = metadata_tests.MemoryMetadataTests.load_main()
        database.save_memory('alice', 'PERSONAL_ACTIVE')
        mid = database.save_memory('alice', 'PERSONAL_ARCHIVE')
        database.set_memory_archived('personal', mid, True, user_id='alice')
        database.save_guild_memory('101', 'GUILD_ACTIVE')
        mid = database.save_guild_memory('101', 'GUILD_ARCHIVE')
        database.set_memory_archived('guild', mid, True, guild_id='101')
        database.save_global_memory('GLOBAL_ACTIVE')
        mid = database.save_global_memory('GLOBAL_ARCHIVE')
        database.set_memory_archived('global', mid, True)
        response = {'choices': [{'message': {'role': 'assistant', 'content': 'Halo'}}]}
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test-only'}), patch.object(main.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as router:
            main.chat(main.ChatRequest(message='Halo', user_id='alice', guild_id='101', context_type='guild'))
        messages = json.loads(router.call_args.args[0].data)['messages']
        memory_context = '\n'.join(message['content'] for message in messages)
        for scope in ('PERSONAL', 'GUILD', 'GLOBAL'):
            self.assertIn(scope + '_ACTIVE', memory_context)
            self.assertNotIn(scope + '_ARCHIVE', memory_context)
