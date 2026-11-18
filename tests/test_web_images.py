"""Real session, SQLite and filesystem checks; image provider is disposable fixture only."""
import asyncio
import base64
import concurrent.futures
import io
import json
import os
import time
import uuid
import unittest

import httpx
from unittest.mock import AsyncMock, patch

import test_web_chat as fixtures
from app import web_images as images
from PIL import Image


def png():
    output = io.BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
    return {'b64_json': base64.b64encode(output.getvalue()).decode()}


class ImageTests(unittest.TestCase):
    setUp = fixtures.WebChatTests.setUp
    user = fixtures.WebChatTests.user
    create = fixtures.WebChatTests.create
    send = fixtures.WebChatTests.send

    def clear_rate(self):
        with self.db.get_connection() as db:
            db.execute('DELETE FROM web_chat_limits')

    def generate(self, cid=None, count=1, **body):
        self.clear_rate()  # Image quota tests are independent of existing chat anti-spam.
        cid = cid or self.create()
        async def provider(prompt, n, key):
            return [png() for _ in range(n)]
        with patch.object(images, 'provider_generate', provider):
            response = self.send(cid, **(body or {'message': f'Generate {count} images of a cat'}))
        self.assertEqual(response.status_code, 200, response.text)
        return cid, response

    def usage(self, owner=None, now=None):
        with self.db.get_connection() as db:
            return images.quota(db, owner or self.alice, now or time.time())

    def project_chat(self):
        pid = self.client.post('/web/chat/projects', json={'name': 'Private', 'memory_mode': 'project_only'}, headers=self.headers).json()['id']
        return self.client.post('/web/chat/conversations', json={'project_id': pid}, headers=self.headers).json()['id']

    def creator(self):
        # Reuse trusted established mapping, never introduce a personal identifier.
        with self.db.get_connection() as db:
            now = self.db.utc_now()
            db.execute('INSERT INTO auth_accounts(identity_id,provider,provider_user_id,created_at,updated_at) VALUES (?,?,?,?,?)',
                       (self.alice, 'discord', self.auth.CREATOR_DISCORD_ID, now, now))

    def test_first_nine_tenth_eleventh_shared_projects_and_text_chat(self):
        for n in range(1, 11):
            _, r = self.generate(self.project_chat() if n % 2 else None)
            self.assertEqual('"type": "image_quota"' in r.text, n == 10)
            self.assertEqual(self.usage()[:2], (n, 0))
        cid, blocked = self.generate()
        self.assertIn('image_quota_exhausted', blocked.text)
        self.assertEqual(self.usage()[:2], (10, 0))
        async def text(messages):
            yield 'Text remains available'
        self.clear_rate()
        with patch.object(self.web, 'model_stream', text):
            self.assertIn('Text remains available', self.send(cid, message='Hello').text)

    def test_creator_unlimited_across_sessions_projects_no_notifications_or_charges(self):
        self.creator()
        for n in range(12):
            self.client.cookies.set(self.auth.SESSION_COOKIE, self.auth.create_session(self.alice))
            _, response = self.generate(self.project_chat() if n % 2 else None)
            self.assertNotIn('image_quota', response.text)
            self.assertNotIn('reset_at', response.text)
            self.assertIn('"type": "images"', response.text)
        self.assertEqual(self.usage()[:2], (0, 0))
        with self.db.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM web_images WHERE charged=0').fetchone()[0], 12)
            self.assertEqual(db.execute('SELECT SUM(reserved) FROM web_image_jobs').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM web_image_jobs WHERE status='reserved'").fetchone()[0], 0)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        _, response = self.generate(count=10)
        self.assertIn('image_quota', response.text)
        self.assertEqual(self.usage(self.bob)[:2], (10, 0))

    def test_spoofing_parameters_names_emails_cookies_and_sessions(self):
        cid = self.create()
        for field in ('is_creator', 'full_control', 'identity_id', 'email', 'role', 'creator'):
            self.assertEqual(self.send(cid, message='Generate image of a cat', **{field: True}).status_code, 422)
        with self.db.get_connection() as db:
            db.execute("UPDATE auth_identities SET display_name='Creator',email='creator@example.test' WHERE identity_id=?", (self.alice,))
            db.execute("UPDATE auth_local_credentials SET username='Creator' WHERE identity_id=?", (self.alice,))
            db.execute("UPDATE auth_accounts SET email='creator@example.test',display_name='Creator' WHERE identity_id=?", (self.alice,))
        self.client.cookies.set('is_creator', 'true')
        self.client.cookies.set('full_control', 'true')
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.auth.create_session(self.alice))
        _, r = self.generate(cid, count=10)
        self.assertIn('image_quota', r.text)
        _, r = self.generate(self.project_chat())
        self.assertIn('image_quota_exhausted', r.text)
        self.client.cookies.set(self.auth.SESSION_COOKIE, 'forged')
        self.assertEqual(self.send(cid, message='Generate image of cat').status_code, 401)

    def test_expiry_exact_independent_no_midnight_reset_and_restart(self):
        self.generate(count=2)
        with self.db.get_connection() as db:
            rows = db.execute('SELECT id FROM web_images ORDER BY rowid').fetchall()
            db.execute('UPDATE web_images SET created_at=? WHERE id=?', (100000, rows[0][0]))
            db.execute('UPDATE web_images SET created_at=? WHERE id=?', (107200, rows[1][0]))
        self.web.init_schema()  # Additive startup, no quota loss.
        self.assertEqual(self.usage(now=172800)[:2], (2, 0))
        self.assertEqual(self.usage(now=186399)[:2], (2, 0))
        self.assertEqual(self.usage(now=186400)[:2], (1, 0))
        self.assertEqual(self.usage(now=193600)[:2], (0, 0))

    def test_partial_failure_release_and_missing_configuration(self):
        cid = self.create()
        with patch.object(images, 'provider_generate', AsyncMock(return_value=[png(), {'b64_json': 'invalid'}, {'url': 'http://169.254.169.254/'}])):
            response = self.send(cid, message='Buat tiga gambar kucing')
        self.assertIn('Generated 1 of 3', response.text)
        self.assertEqual(self.usage()[:2], (1, 0))
        with patch.dict(os.environ, {'ABUD_IMAGE_PROVIDER': ''}):
            response = self.send(self.create(), message='Generate image of a cat')
        self.assertIn('unavailable', response.text)
        self.assertEqual(self.usage()[:2], (1, 0))
        with patch.object(images, 'provider_generate', AsyncMock(return_value=[])):
            response = self.send(self.create(), message='Generate image of a cat')
        self.assertIn('No image quota was charged', response.text)
        self.assertEqual(self.usage()[:2], (1, 0))

    def test_unknown_timeout_holds_quota_and_regenerate_never_duplicates(self):
        cid = self.create()
        provider = AsyncMock(side_effect=images.ProviderError('image_generation_unknown', 'Contact administrator', True))
        with patch.object(images, 'provider_generate', provider):
            self.send(cid, message='Generate 10 images of a cat')
            self.send(cid, regenerate=True)
        self.assertEqual(provider.await_count, 1)
        self.assertEqual(self.usage()[:2], (0, 10))
        _, r = self.generate()
        self.assertIn('"reset_at": null', r.text)
        self.web.init_schema()
        self.assertEqual(self.usage()[:2], (0, 10))

    def test_creator_failure_does_not_affect_other_users_and_cannot_access_images(self):
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        self.generate(count=3)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.creator()
        with patch.object(images, 'provider_generate', AsyncMock(side_effect=images.ProviderError('image_generation_unknown', 'Unknown', True))):
            r = self.send(self.create(), message='Generate 10 images of a cat')
        self.assertNotIn('image_quota', r.text)
        self.assertEqual(self.usage()[:2], (0, 0))
        self.assertEqual(self.usage(self.bob)[:2], (3, 0))
        with self.db.get_connection() as db:
            image_id = db.execute('SELECT id FROM web_images WHERE identity_id=?', (self.bob,)).fetchone()[0]
        self.assertEqual(self.client.get('/web/chat/images/' + image_id).status_code, 404)

    def test_private_download_durable_history_and_delete_cannot_reset_quota(self):
        cid, _ = self.generate(self.project_chat())
        self.web.init_schema()
        message = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        url = message['images'][0]['url']
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn('attachment', self.client.get(url + '?download=true').headers['content-disposition'])
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.bob_token)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.alice_token)
        self.assertEqual(self.client.delete('/web/chat/conversations/' + cid, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.usage()[:2], (1, 0))

    def test_duplicate_key_and_regenerate_success_are_idempotent(self):
        cid, response = self.generate(request_id=str(uuid.uuid4()), message='Generate image of a cat')
        provider = AsyncMock()
        with patch.object(images, 'provider_generate', provider):
            self.assertIn('"type": "done"', self.send(cid, regenerate=True).text)
        provider.assert_not_called()
        self.assertEqual(self.usage()[:2], (1, 0))
        with self.db.get_connection() as db:
            key = db.execute('SELECT request_id FROM web_messages WHERE conversation_id=? AND role=?', (cid, 'user')).fetchone()[0].split(':', 1)[1]
        self.assertEqual(self.send(cid, message='Generate image of a cat', request_id=key).status_code, 409)
        self.assertEqual(len(self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]['images']), 1)

    def test_concurrent_reservations_across_conversations_cannot_exceed_ten(self):
        cids = [self.create() for _ in range(4)]
        async def provider(prompt, n, key):
            await asyncio.sleep(.05)
            return [png() for _ in range(n)]
        def run(cid):
            return self.send(cid, message='Generate 3 images of a cat')
        with patch.object(images, 'provider_generate', provider), concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, cids))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(self.usage()[:2], (9, 0))
        self.assertEqual(sum('"type": "images"' in r.text for r in results), 3)

    def test_intent_positive_and_negative(self):
        for text, count in [('Buatkan gambar kucing astronot.', 1), ('Generate an image of a futuristic city.', 1),
                            ('Gambarkan naga merah di atas gunung.', 1), ('Buat dua gambar pemandangan Jepang.', 2),
                            ('Please create 4 pictures of mountains', 4)]:
            self.assertEqual(images.intent(text)[0], count, text)
        for text in ['Hello', 'What is in this image?', 'Bagaimana cara membuat gambar?',
                     '"Generate an image of a cat"', 'Example: Generate image of a cat',
                     'Generate image example for documentation', 'Create something',
                     'Generate an image of "cat"', 'Explain: buatkan gambar kucing',
                     'Can you generate an image?', 'Generate image\nof cat']:
            self.assertIsNone(images.intent(text), text)

    def test_payload_validation_rejects_url_svg_corruption_and_oversize(self):
        self.assertEqual(images.validate_image(png()['b64_json'])[1][1], 'image/png')
        for value in ['http://localhost/image', base64.b64encode(b'<svg/>').decode(), 'x' * (images.MAX_BYTES * 2), '', None]:
            with self.assertRaises(ValueError):
                images.validate_image(value)

    def test_rapid_eleventh_request_reports_image_quota_and_creator_remains_unlimited(self):
        async def provider(prompt, n, key):
            return [png() for _ in range(n)]
        with patch.object(images, 'provider_generate', provider):
            for _ in range(10):
                self.assertIn('"type": "images"', self.send(self.create(), message='Generate image of a cat').text)
            response = self.send(self.create(), message='Generate image of a cat')
            self.assertEqual(response.status_code, 200)
            self.assertIn('image_quota_exhausted', response.text)
            self.creator()
            for _ in range(12):
                response = self.send(self.project_chat(), message='Generate image of a cat')
                self.assertEqual(response.status_code, 200)
                self.assertIn('"type": "images"', response.text)
                self.assertNotIn('image_quota', response.text)
        self.assertEqual(self.usage()[:2], (10,0))

    def test_adapter_contract_and_fail_closed_errors(self):
        config = {'ABUD_IMAGE_PROVIDER': 'openai-compatible-b64',
                  'ABUD_IMAGE_ENDPOINT': 'https://images.example.test/v1/images/generations',
                  'ABUD_IMAGE_MODEL': 'verified-model', 'ABUD_IMAGE_API_KEY': 'fixture-key',
                  'ABUD_IMAGE_MAX_COUNT': '2'}
        actual_client = httpx.AsyncClient
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.headers['authorization'], 'Bearer fixture-key')
            self.assertEqual(request.headers['idempotency-key'], 'job-key')
            self.assertEqual(json.loads(request.content), {'model':'verified-model', 'prompt':'cat', 'n':2, 'response_format':'b64_json'})
            return httpx.Response(200, json={'data':[png()]})
        def client(**kwargs):
            return actual_client(transport=httpx.MockTransport(handler), **kwargs)
        with patch.dict(os.environ, config), patch.object(images.httpx, 'AsyncClient', client):
            result = asyncio.run(images.provider_generate('cat', 2, 'job-key'))
            self.assertEqual(len(result), 1)
        self.assertEqual(len(requests), 1)
        for status, uncertain in [(400,False), (401,False), (403,False), (404,False), (422,False), (429,False), (500,True), (302,True)]:
            def failure_client(**kwargs):
                return actual_client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={})), **kwargs)
            with patch.dict(os.environ, config), patch.object(images.httpx, 'AsyncClient', failure_client):
                with self.assertRaises(images.ProviderError) as caught:
                    asyncio.run(images.provider_generate('cat', 1, 'key'))
                self.assertEqual(caught.exception.uncertain, uncertain)
        for override in [{'ABUD_IMAGE_PROVIDER':''}, {'ABUD_IMAGE_ENDPOINT':'http://localhost/image'},
                         {'ABUD_IMAGE_ENDPOINT':'https://user:pass@host/image'}, {'ABUD_IMAGE_MAX_COUNT':'99'},
                         {'ABUD_IMAGE_MODEL':''}]:
            with patch.dict(os.environ, {**config, **override}):
                with self.assertRaises(images.ProviderError) as caught:
                    asyncio.run(images.provider_generate('cat', 1, 'key'))
                self.assertEqual(caught.exception.code, 'image_provider_unavailable')

    def test_creator_revoked_or_disabled_session_cannot_generate(self):
        self.creator()
        cid = self.create()
        with self.db.get_connection() as db:
            db.execute('UPDATE dashboard_sessions SET revoked_at=? WHERE identity_id=?', (self.db.utc_now(),self.alice))
        self.assertEqual(self.send(cid, message='Generate image of a cat').status_code,401)
        self.client.cookies.set(self.auth.SESSION_COOKIE, self.auth.create_session(self.alice))
        with self.db.get_connection() as db:
            db.execute('UPDATE auth_identities SET disabled_at=? WHERE identity_id=?', (self.db.utc_now(),self.alice))
        self.assertEqual(self.send(cid, message='Generate image of a cat').status_code,401)
        self.assertEqual(self.usage()[:2],(0,0))

    def test_regenerate_replays_original_artifacts_without_mutation(self):
        cid, original = self.generate(count=2)
        before = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        self.assertEqual(len(before['images']), 2)
        before_quota = self.usage()[:2]
        provider = AsyncMock(side_effect=AssertionError('Regenerate must not call provider'))
        with patch.object(images, 'provider_generate', provider):
            replay = self.send(cid, regenerate=True)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertIn('"type": "images"', replay.text)
        self.assertIn('Generated 2 of 2', replay.text)
        provider.assert_not_called()
        after = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['images'], before['images'])
        self.assertEqual(self.usage()[:2], before_quota)
        for artifact in before['images']:
            self.assertEqual(self.client.get(artifact['url']).status_code, 200)
            self.assertEqual(self.client.get(artifact['url'] + '?download=true').status_code, 200)
        self.web.init_schema()
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]['images'], before['images'])

    def test_partial_success_regenerate_replays_only_saved_images(self):
        cid = self.create()
        with patch.object(images, 'provider_generate', AsyncMock(return_value=[png(), {'b64_json': 'invalid'}])):
            response = self.send(cid, message='Generate 2 images of a cat')
        self.assertIn('Generated 1 of 2', response.text)
        before = self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1]
        with patch.object(images, 'provider_generate', AsyncMock(side_effect=AssertionError('duplicate generation'))) as provider:
            replay = self.send(cid, regenerate=True)
        provider.assert_not_called()
        self.assertIn('"type": "images"', replay.text)
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json()['messages'][-1], before)
        self.assertEqual(self.usage()[:2], (1, 0))

    def test_additive_migration_preserves_existing_history_and_project(self):
        cid = self.project_chat()
        async def text(messages):
            yield 'Existing reply'
        with patch.object(self.web, 'model_stream', text):
            self.send(cid, message='Existing question')
        before = self.client.get('/web/chat/conversations/' + cid).json()
        # Simulate pre-feature schema, keeping all ordinary production-style data.
        with self.db.get_connection() as db:
            db.execute('DROP INDEX idx_web_turn_request')
            db.execute('ALTER TABLE web_messages DROP COLUMN request_id')
            db.execute('DROP TABLE web_images')
            db.execute('DROP TABLE web_image_jobs')
        self.web.init_schema()
        self.web.init_schema()
        self.assertEqual(self.client.get('/web/chat/conversations/' + cid).json(), before)
        self.generate(cid)
        self.assertEqual(self.usage()[:2], (1,0))


if __name__ == '__main__':
    unittest.main()
