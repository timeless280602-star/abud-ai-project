import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import database, tools


class MemoryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db_patch = patch.object(database, 'DATABASE_PATH', Path(self.temp.name) / 'memory.db')
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_database()

    def test_legacy_migration_preserves_records_and_is_idempotent(self):
        # A pre-metadata database, with identical IDs in each independent scope.
        legacy = Path(self.temp.name) / 'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.executescript('''
                CREATE TABLE users(user_id TEXT PRIMARY KEY, username TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE guilds(guild_id TEXT PRIMARY KEY, guild_name TEXT, owner_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO users VALUES ('alice', 'Alice', 'old', 'old');
                INSERT INTO guilds VALUES ('guild-a', 'A', 'alice', 'old', 'old');
                CREATE TABLE memories(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, content TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE guild_memories(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE, content TEXT NOT NULL, created_by_user_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE global_memories(id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'general', content TEXT NOT NULL, created_by_user_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO memories VALUES (42, 'alice', 'kopi personal', 'created', 'updated');
                INSERT INTO guild_memories VALUES (42, 'guild-a', 'kopi guild', 'alice', 'created', 'updated');
                INSERT INTO global_memories VALUES (42, 'beverage', 'kopi global', 'alice', 'created', 'updated');
            ''')
        with patch.object(database, 'DATABASE_PATH', legacy):
            with database.get_connection() as db:
                before = {table: dict(db.execute(f'SELECT * FROM {table}').fetchone()) for table in ('memories', 'guild_memories', 'global_memories')}
            database.init_database()
            database.init_database()
            with database.get_connection() as db:
                for table, original in before.items():
                    self.assertEqual(dict(db.execute(f'SELECT * FROM {table}').fetchone()), {**original, 'source': 'unknown', 'revision': 0})
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertGreater(database.save_memory('alice', 'baru', source='direct'), 42)
            self.assertEqual(database.search_memories('personal', 'kopi', user_id='alice')[0]['revision'], 0)

    def test_sources_duplicates_and_edits_in_all_scopes(self):
        cases = [
            (lambda text, source: database.save_memory('alice', text, source=source), lambda mid: database.update_memory('alice', mid, 'baru'), lambda: database.get_memories('alice')),
            (lambda text, source: database.save_guild_memory('guild-a', text, 'alice', source=source), lambda mid: database.update_guild_memory('guild-a', mid, 'baru'), lambda: database.get_guild_memories('guild-a')),
            (lambda text, source: database.save_global_memory(text, 'general', 'alice', source=source), lambda mid: database.update_global_memory(mid, 'baru', 'edited'), lambda: database.get_global_memories()),
        ]
        for save, edit, read in cases:
            mid = save('kopi', 'auto')
            self.assertEqual((read()[0]['source'], read()[0]['revision']), ('auto', 1))
            self.assertEqual(save('kopi', 'dashboard'), mid)
            self.assertEqual((read()[0]['source'], read()[0]['revision']), ('auto', 1))
            self.assertTrue(edit(mid))
            self.assertEqual((read()[0]['source'], read()[0]['revision']), ('auto', 2))
            # Each accepted edit creates a revision, including equal-text edits.
            self.assertTrue(edit(mid))
            self.assertEqual(read()[0]['revision'], 3)
        database.init_database()
        self.assertEqual(database.get_global_memories()[0]['revision'], 3)

    def test_metadata_does_not_weaken_scope_or_source_validation(self):
        personal = database.save_memory('alice', 'kopi', source='direct')
        guild = database.save_guild_memory('guild-a', 'kopi', source='dashboard')
        self.assertFalse(database.update_memory('bob', personal, 'changed'))
        self.assertFalse(database.update_guild_memory('guild-b', guild, 'changed'))
        self.assertEqual(database.get_memories('alice')[0]['revision'], 1)
        self.assertEqual(database.get_guild_memories('guild-a')[0]['revision'], 1)
        for source in ('forged', None, 12):
            with self.assertRaises(ValueError):
                database.save_memory('bob', 'invalid', source=source)
            with self.assertRaises(ValueError):
                database.save_guild_memory('guild-b', 'invalid', source=source)
            with self.assertRaises(ValueError):
                database.save_global_memory('invalid', source=source)
        self.assertEqual(database.get_memories('bob'), [])
        with self.assertRaises(ValueError):
            tools.execute_tool('save_memory', {'scope': 'personal', 'content': 'kopi', 'source': 'dashboard'}, {'user_id': 'alice'})
        with database.get_connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE memories SET source = 'forged'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE memories SET revision = -1')

    def test_tool_and_direct_command_source(self):
        main = self.load_main()
        tools.save_memory_tool('personal', 'tool memory', {'user_id': 'alice'})
        self.assertEqual(database.get_memories('alice')[0]['source'], 'tool')
        main.build_memory_commands('ingat bahwa direct memory', 'alice')
        self.assertEqual(database.get_memories('alice')[0]['source'], 'direct')
        main.build_memory_commands('ingat untuk server guild memory', 'alice', 'guild-a', True)
        self.assertEqual(database.get_guild_memories('guild-a')[0]['source'], 'direct')
        main.build_memory_commands('ingat global global memory', tools.GLOBAL_MEMORY_OWNER_ID)
        self.assertEqual(database.get_global_memories()[0]['source'], 'direct')

    def test_auto_save_marks_backend_source_ignoring_model_source(self):
        main = self.load_main()
        response = {'choices': [{'message': {'content': json.dumps({'memories': [{'scope': 'personal', 'content': 'kopi', 'source': 'dashboard'}]})}}]}
        with patch.dict(os.environ, {'NINE_ROUTER_API_KEY': 'test-only'}), patch.object(main.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            result = main.auto_save_memory_endpoint(main.AutoSaveRequest(message='Saya suka kopi', user_id='alice'))
        self.assertEqual(len(result['memory_events']), 1)
        self.assertEqual(database.get_memories('alice')[0]['source'], 'auto')

    def test_dashboard_source_and_metadata_response(self):
        main = self.load_main()
        from fastapi.testclient import TestClient
        identity = {'identity_id': 'test-creator', 'is_creator': True, 'permissions': []}
        with patch.object(main, '_memory_dashboard_identity', return_value=(identity, tools.GLOBAL_MEMORY_OWNER_ID)), patch.object(main.dashboard_auth, 'require_same_origin'), patch.object(main, '_memory_audit'):
            client = TestClient(main.app)
            response = client.post('/dashboard/memory', json={'scope': 'personal', 'content': 'kopi', 'source': 'auto', 'revision': 999})
            self.assertEqual(response.status_code, 200)
            row = client.get('/dashboard/memory?q=kopi').json()['items'][0]
            self.assertEqual((row['source'], row['revision']), ('dashboard', 1))
            response = client.put('/dashboard/memory', json={'scope': 'personal', 'memory_id': row['id'], 'content': 'kopi susu'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/dashboard/memory?q=kopi').json()['items'][0]['revision'], 2)

    @staticmethod
    def load_main():
        config = {name: 'test-only' for name in ('DISCORD_OAUTH_CLIENT_ID', 'DISCORD_OAUTH_CLIENT_SECRET', 'GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET', 'ABUD_SESSION_SECRET')}
        config['ABUD_BASE_URL'] = 'https://abud.example.test'
        with patch.dict(os.environ, config):
            return importlib.import_module('app.main')
