"""Real-session projects, memory boundaries, additive migration and title races."""
import asyncio
import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import test_web_chat as fixtures
from app import web_projects


class ProjectTests(unittest.TestCase):
    setUp = fixtures.WebChatTests.setUp
    user = fixtures.WebChatTests.user
    create = fixtures.WebChatTests.create
    send = fixtures.WebChatTests.send

    def project(self, mode='default', **fields):
        response = self.client.post('/web/chat/projects', json={'name': 'Research', 'memory_mode': mode, **fields}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def chat(self, pid=None):
        r = self.client.post('/web/chat/conversations', json={'project_id': pid}, headers=self.headers)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()['id']

    def action(self, cid, action, body):
        return self.client.patch(f'/web/chat/conversations/{cid}/{action}', json=body, headers=self.headers)

    def answer(self, cid, message='Hello', **kwargs):
        seen = []
        async def stream(messages):
            seen.extend(messages)
            yield 'Project reply'
        with patch.object(self.web, 'model_stream', stream):
            response = self.send(cid, **({'message': message} if not kwargs else kwargs))
        self.assertIn('"type": "done"', response.text)
        return seen

    def test_project_crud_ownership_validation_and_immutable_mode(self):
        pid = self.project('project_only', description='Private work', instructions='Use Indonesian')
        url = '/web/chat/projects/' + pid
        self.assertEqual(self.client.get('/web/chat/projects').json()[0]['conversation_count'], 0)
        self.assertEqual(self.client.patch(url, json={'name': 'Updated', 'instructions': 'Use English'}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(url).json()['memory_mode'], 'project_only')
        self.assertEqual(self.client.patch(url, json={'name': 'Updated', 'memory_mode': 'default'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.patch(url, json={'name': '  '}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post('/web/chat/projects', json={'name': 'No CSRF'}).status_code, 403)
        self.assertEqual(self.client.post('/web/chat/projects', json={'name': 'Spoof', 'identity_id': self.bob}, headers=self.headers).status_code, 422)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        self.assertEqual(self.client.get('/web/chat/projects').json(), [])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, json={'name': 'Stolen'}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.request('DELETE', url, json={'conversations': 'delete'}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(url + '/conversations').status_code, 404)
        self.assertEqual(self.client.post('/web/chat/conversations', json={'project_id': pid}, headers=self.headers).status_code, 404)

    def test_pin_archive_restore_and_group_lists(self):
        pid = self.project()
        c1, c2 = self.chat(), self.chat()
        inside = self.chat(pid)
        self.answer(c1)
        self.assertEqual(self.action(c1, 'pin', {'enabled': True}).status_code, 200)
        self.assertEqual(self.client.get('/web/chat/conversations').json()[0]['id'], c1)
        self.assertEqual(self.action(c1, 'archive', {'enabled': True}).status_code, 200)
        self.assertEqual([c['id'] for c in self.client.get('/web/chat/conversations').json()], [c2])
        self.assertEqual(self.send(c1, message='Must restore').status_code, 409)
        self.assertEqual(self.client.get('/web/chat/conversations?archived=true').json()[0]['id'], c1)
        self.assertEqual(self.action(c1, 'archive', {'enabled': False}).status_code, 200)
        self.assertEqual(self.client.get('/web/chat/conversations/' + c1).json()['messages'][-1]['content'], 'Project reply')
        self.assertEqual(self.action(c1, 'pin', {'enabled': False}).status_code, 200)
        self.assertEqual([c['id'] for c in self.client.get(f'/web/chat/projects/{pid}/conversations').json()], [inside])
        self.assertEqual(self.client.get('/web/chat/projects').json()[0]['conversation_count'], 1)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        for action in ('pin', 'archive'):
            self.assertEqual(self.action(c1, action, {'enabled': True}).status_code, 404)
        self.assertEqual(self.action(c1, 'project', {'project_id': None}).status_code, 404)

    def test_moves_preserve_history_and_block_scope_crossings(self):
        default1, default2 = self.project(), self.project()
        private1, private2 = self.project('project_only'), self.project('project_only')
        cid = self.chat()
        self.answer(cid)
        before = self.client.get('/web/chat/conversations/' + cid).json()['messages']
        for pid in (default1, default2, None):
            self.assertEqual(self.action(cid, 'project', {'project_id': pid}).status_code, 200)
            self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['messages'], before)
        self.assertEqual(self.action(cid, 'project', {'project_id': private1}).status_code, 409)
        empty = self.chat()
        for pid in (private1, private2, default1, None, private1):
            self.assertEqual(self.action(empty, 'project', {'project_id': pid}).status_code, 200)
        self.answer(empty, 'remember secret research note')
        for pid in (private2, default1, None):
            self.assertEqual(self.action(empty, 'project', {'project_id': pid}).status_code, 409)
        self.assertEqual(self.action(empty, 'project', {'project_id': private1}).status_code, 200)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        bob_project = self.project()
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.assertEqual(self.action(cid, 'project', {'project_id': bob_project}).status_code, 404)

    def test_project_only_retrieval_writes_instructions_and_feedback_boundaries(self):
        p1 = self.project('project_only', instructions='PRIVATE instructions: concise Indonesian')
        p2 = self.project('project_only')
        default = self.project(instructions='DEFAULT project instruction')
        scope1 = web_projects.memory_scope(self.alice, {'id': p1, 'memory_mode': 'project_only'})
        scope2 = web_projects.memory_scope(self.alice, {'id': p2, 'memory_mode': 'project_only'})
        for owner, value in [('web:' + self.alice, 'personal SECRET'), (scope2, 'other project SECRET'), ('web:' + self.bob, 'other user SECRET')]:
            self.db.save_memory(owner, value)
        self.db.save_global_memory('global SECRET')
        self.db.save_guild_memory('123', 'guild SECRET')
        c1 = self.chat(p1)
        seen = self.answer(c1, 'remember isolated SECRET')
        text = str(seen)
        self.assertIn('isolated SECRET', text)
        self.assertIn('PRIVATE instructions', text)
        for absent in ('personal SECRET', 'other project SECRET', 'other user SECRET', 'global SECRET', 'guild SECRET'):
            self.assertNotIn(absent, text)
        self.assertEqual(self.db.get_memories(scope1)[0]['content'], 'isolated SECRET')
        self.assertNotIn('isolated SECRET', str(self.db.get_memories('web:' + self.alice)))
        mid = self.client.get('/web/chat/conversations/' + c1).json()['messages'][-1]['id']
        r = self.client.post(f'/web/chat/conversations/{c1}/messages/{mid}/feedback', json={'rating': 'bad', 'reason': 'Private feedback SECRET'}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('Private feedback SECRET', self.web.feedback_context(self.alice, scope1))
        self.assertNotIn('Private feedback SECRET', self.web.feedback_context(self.alice))
        own = self.answer(self.chat(p1), 'isolated')
        self.assertIn('Private feedback SECRET', str(own))
        other = str(self.answer(self.chat(p2), 'SECRET'))
        self.assertNotIn('isolated SECRET', other)
        self.assertNotIn('Private feedback SECRET', other)
        self.assertNotIn('PRIVATE instructions', other)
        normal = str(self.answer(self.chat(default), 'SECRET'))
        self.assertIn('personal SECRET', normal)
        self.assertIn('global SECRET', normal)
        self.assertIn('DEFAULT project instruction', normal)
        self.assertNotIn('Private feedback SECRET', normal)
        self.assertNotIn('isolated SECRET', normal)
        self.assertNotIn('other project SECRET', normal)

    def test_project_delete_requires_choice_and_preserves_or_deletes_explicitly(self):
        pid = self.project()
        c1 = self.chat(pid)
        self.answer(c1)
        self.db.save_memory('web:' + self.alice, 'Keep this personal memory')
        url = '/web/chat/projects/' + pid
        self.assertEqual(self.client.delete(url, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.request('DELETE', url, json={'conversations': 'keep'}, headers=self.headers).status_code, 200)
        self.assertIsNone(self.client.get('/web/chat/conversations/' + c1).json()['project_id'])
        self.assertEqual(len(self.client.get('/web/chat/conversations/' + c1).json()['messages']), 2)
        pid = self.project('project_only')
        c2 = self.chat(pid)
        self.answer(c2, 'remember project note')
        scope = web_projects.memory_scope(self.alice, {'id': pid, 'memory_mode': 'project_only'})
        url = '/web/chat/projects/' + pid
        self.assertEqual(self.client.request('DELETE', url, json={'conversations': 'keep'}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.get('/web/chat/conversations/' + c2).status_code, 200)
        self.assertEqual(self.client.request('DELETE', url, json={'conversations': 'delete'}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/web/chat/conversations/' + c2).status_code, 404)
        self.assertEqual(self.db.get_memories(scope), [])
        self.assertEqual(self.db.get_memories('web:' + self.alice)[0]['content'], 'Keep this personal memory')
        with self.db.get_connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_busy_mutations_are_rejected(self):
        pid = self.project()
        cid = self.chat(pid)
        with self.db.get_connection() as db:
            db.execute('UPDATE web_conversations SET lease_until=? WHERE id=?', (10**12, cid))
        for action, body in [('pin', {'enabled': True}), ('archive', {'enabled': True}), ('project', {'project_id': None})]:
            self.assertEqual(self.action(cid, action, body).status_code, 409)
        self.assertEqual(self.client.request('DELETE', '/web/chat/projects/' + pid, json={'conversations': 'delete'}, headers=self.headers).status_code, 409)

    def test_legacy_schema_migration_preserves_messages_and_manual_titles(self):
        with self.db.get_connection() as db:
            db.execute('DROP TABLE web_response_feedback')
            db.execute('DROP TABLE web_messages')
            db.execute('DROP TABLE web_conversations')
            db.execute('CREATE TABLE web_conversations(id TEXT PRIMARY KEY,identity_id TEXT NOT NULL,title TEXT NOT NULL,updated_at TEXT NOT NULL,lease_until REAL NOT NULL DEFAULT 0)')
            db.execute('INSERT INTO web_conversations VALUES (?,?,?,?,0)', ('legacy', self.alice, 'Manual legacy title', self.db.utc_now()))
            db.execute("CREATE TABLE web_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)")
            db.execute('INSERT INTO web_messages(conversation_id,role,content,created_at) VALUES (?,?,?,?)', ('legacy', 'user', 'Old text', self.db.utc_now()))
        self.web.init_schema()
        self.web.init_schema()
        loaded = self.client.get('/web/chat/conversations/legacy').json()
        self.assertEqual(loaded['title'], 'Manual legacy title')
        self.assertEqual(loaded['messages'][0]['content'], 'Old text')
        self.assertIsNone(loaded['project_id'])
        with self.db.get_connection() as db:
            self.assertEqual(db.execute("SELECT title_state FROM web_conversations WHERE id='legacy'").fetchone()[0], 'manual')

    def test_title_fallback_only_once_and_manual_rename_wins(self):
        cid = self.chat()
        self.answer(cid, 'Bantu gue bikin strategi pemasaran kopi')
        title = self.client.get('/web/chat/conversations/' + cid).json()['title']
        self.assertEqual(title, 'Strategi pemasaran kopi')
        self.answer(cid, 'A different topic')
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['title'], title)
        self.client.patch('/web/chat/conversations/' + cid, json={'title': 'My chosen title'}, headers=self.headers)
        asyncio.run(self.web.generate_title(cid, self.alice, 'original', title))
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['title'], 'My chosen title')

    def test_ai_title_success_failure_and_manual_rename_race(self):
        cid = self.chat()
        self.answer(cid, 'Help me create a marketing strategy')
        fallback = self.client.get('/web/chat/conversations/' + cid).json()['title']
        client_type = httpx.AsyncClient
        def response(request):
            payload = json.loads(request.content)
            self.assertEqual(payload['max_tokens'], 40)
            self.assertLessEqual(len(payload['messages'][-1]['content']), 1000)
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Coffee marketing plan'}}]})
        def make_client(**kwargs):
            return client_type(transport=httpx.MockTransport(response), **kwargs)
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test'}), patch.object(self.web.httpx, 'AsyncClient', make_client):
            asyncio.run(self.web.generate_title(cid, self.alice, 'Some prompt', fallback))
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['title'], 'Coffee marketing plan')
        self.client.patch('/web/chat/conversations/' + cid, json={'title': 'Manual'}, headers=self.headers)
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test'}), patch.object(self.web.httpx, 'AsyncClient', make_client):
            asyncio.run(self.web.generate_title(cid, self.alice, 'Some prompt', 'Coffee marketing plan'))
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['title'], 'Manual')
        async def fail(*args, **kwargs):
            raise httpx.ReadTimeout('private detail')
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test'}), patch.object(httpx.AsyncClient, 'post', fail):
            asyncio.run(self.web.generate_title(cid, self.alice, 'Some prompt', 'Manual'))
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['title'], 'Manual')

    def test_title_provider_failure_keeps_fallback_and_manual_race_is_guarded(self):
        cid = self.chat()
        self.answer(cid, 'Bantu bikin rencana belajar')
        fallback = self.client.get('/web/chat/conversations/' + cid).json()['title']
        client_type = httpx.AsyncClient
        for kind in ('timeout', 'bad_output', 'manual_race'):
            def respond(request):
                if kind == 'timeout':
                    raise httpx.ReadTimeout('private timeout')
                if kind == 'manual_race':
                    self.client.patch('/web/chat/conversations/' + cid, json={'title': 'Manual wins'}, headers=self.headers)
                title = 'x' * 81 if kind == 'bad_output' else 'AI generated title'
                return httpx.Response(200, json={'choices': [{'message': {'content': title}}]})
            def make_client(**kwargs):
                return client_type(transport=httpx.MockTransport(respond), **kwargs)
            with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test'}), patch.object(self.web.httpx, 'AsyncClient', make_client):
                asyncio.run(self.web.generate_title(cid, self.alice, 'original', fallback))
            title = self.client.get('/web/chat/conversations/' + cid).json()['title']
            self.assertEqual(title, 'Manual wins' if kind == 'manual_race' else fallback)

    def test_title_job_does_not_block_first_stream_chunk(self):
        cid = self.chat()
        async def exercise():
            from types import SimpleNamespace
            from unittest.mock import AsyncMock
            release = asyncio.Event()
            async def title(*args):
                await release.wait()
            async def stream(messages):
                yield 'Immediate answer'
            request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
            with patch.object(self.web, 'identity', return_value=self.alice), patch.object(self.web, 'generate_title', title), patch.object(self.web, 'model_stream', stream):
                response = self.web.send(cid, request, self.web.Turn(message='First topic'))
                chunk = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
                self.assertIn('Immediate answer', chunk)
                self.assertFalse(release.is_set())
                await response.body_iterator.aclose()
                release.set()
                if self.web.title_tasks:
                    await asyncio.gather(*self.web.title_tasks)
        asyncio.run(exercise())

    def test_concurrent_additive_startup_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        cid = self.chat()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.web.init_schema(), range(2)))
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).status_code, 200)
