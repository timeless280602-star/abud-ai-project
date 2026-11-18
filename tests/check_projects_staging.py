"""Disposable local Compose acceptance check. No live OAuth/AI, production or bot.

Build an image first, then: python tests/check_projects_staging.py --image IMAGE
Uses only the local managed Docker socket. Removes only its fresh test volume.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='abud-web-chat-projects:local')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = 'abud-projects-check-' + secrets.token_hex(4)
    origin = 'https://projects-check.example.invalid'
    # Do not replace or attach an already-running staging service.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', 18000))
    with tempfile.TemporaryDirectory(prefix='abud-projects-check-') as directory:
        work = Path(directory)
        env_file = work / 'check.env'
        values = {
            'ABUD_BASE_URL': origin, 'ABUD_SESSION_SECRET': secrets.token_urlsafe(48),
            'ABUD_INTERNAL_API_KEY': secrets.token_urlsafe(48),
            'GOOGLE_OAUTH_CLIENT_ID': 'local-test', 'GOOGLE_OAUTH_CLIENT_SECRET': 'local-test',
            'DISCORD_OAUTH_CLIENT_ID': 'local-test', 'DISCORD_OAUTH_CLIENT_SECRET': 'local-test',
            'NINE_ROUTER_BASE_URL': 'http://127.0.0.1:9/disabled', 'NINE_ROUTER_API_KEY': '',
        }
        descriptor = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as target:
            target.write(''.join(f'{key}={value}\n' for key, value in values.items()))
        override = work / 'override.json'
        override.write_text(json.dumps({'services': {'api': {'image': args.image, 'restart': 'no'}}}))
        env = {**os.environ, 'ABUD_STAGING_ENV_FILE': str(env_file)}
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            env.pop(key, None)
        base = ['docker', '--host=unix:///var/run/docker.sock', 'compose', '-p', project,
                '-f', str(root / 'compose.staging.yaml'), '-f', str(override)]

        def compose(*arguments, **options):
            return subprocess.run([*base, *arguments], env=env, cwd=root, check=True, **options)

        config = json.loads(compose('config', '--format', 'json', capture_output=True, text=True).stdout)
        assert set(config['services']) == {'api'}
        api = config['services']['api']
        assert api['image'] == args.image
        assert 'container_name' not in api
        assert api['environment']['ABUD_DATABASE_PATH'] == '/app/data/abud_staging.db'
        assert api['environment']['NINE_ROUTER_API_KEY'] == ''
        assert len(api['ports']) == 1 and api['ports'][0]['host_ip'] == '127.0.0.1'
        assert all(volume['type'] == 'volume' for volume in api['volumes'])
        assert all(not network.get('external') for network in config.get('networks', {}).values())
        assert all(not volume.get('external') and volume['name'].startswith(project + '_')
                   for volume in config['volumes'].values())

        def request(path, method='GET', body=None, token=None, csrf=origin):
            headers = {}
            if token:
                headers['Cookie'] = 'abud_session=' + token
            if csrf is not None:
                headers['Origin'] = csrf
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers['Content-Type'] = 'application/json'
            req = urllib.request.Request('http://127.0.0.1:18000' + path, data=data, headers=headers, method=method)
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read().decode()
                content = json.loads(raw) if response.headers.get('Content-Type', '').startswith('application/json') else raw
                return response.status, content

        try:
            compose('up', '-d', '--no-build', '--pull', 'never', 'api')
            deadline = time.monotonic() + 20
            while True:
                try:
                    assert request('/health')[0] == 200
                    break
                except (OSError, AssertionError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Disposable staging API failed to become healthy')
                    time.sleep(0.2)
            setup = '''import json, os
from app import auth, database
assert os.getuid()==10001
with database.get_connection() as db:
 assert db.execute('SELECT COUNT(*) FROM web_projects').fetchone()[0]==0
 assert db.execute('SELECT COUNT(*) FROM web_conversations').fetchone()[0]==0
tokens=[]
for name in ('alice','bob'):
 owner=auth.get_or_create_identity('google', {'id':name,'email_verified':True})
 now=database.utc_now()
 with database.get_connection() as db:
  db.execute('INSERT INTO auth_local_credentials(identity_id,username,username_normalized,password_hash,profile_completed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)', (owner,name,name,'unused',now,now,now))
 tokens.append(auth.create_session(owner))
print(json.dumps(tokens))'''
            tokens = json.loads(compose('exec', '-T', 'api', 'python', '-c', setup, capture_output=True, text=True).stdout)
            alice, bob = tokens
            assert request('/web/chat/projects')[0] == 401
            assert request('/web/chat/projects', 'POST', {'name': 'CSRF'}, alice, None)[0] == 403
            path = '/web/chat/projects'
            status, private = request(path, 'POST', {'name': 'Private research', 'memory_mode': 'project_only',
                                                       'description': 'Keep description', 'instructions': 'Keep instructions'}, alice)
            assert status == 201
            pid = private['id']
            project_url = path + '/' + pid
            assert request(project_url, 'PATCH', {'name': 'Renamed research'}, alice)[0] == 200
            settings = request(project_url, token=alice)[1]
            assert settings['description'] == 'Keep description' and settings['instructions'] == 'Keep instructions'
            assert request(project_url, token=bob)[0] == 404
            assert request(project_url, 'PATCH', {'name': 'Changed', 'memory_mode': 'default'}, alice)[0] == 422
            status, chat = request('/web/chat/conversations', 'POST', {'project_id': pid}, alice)
            assert status == 201
            cid = chat['id']
            chat_url = '/web/chat/conversations/' + cid
            assert request(chat_url, token=bob)[0] == 404
            assert request(chat_url + '/pin', 'PATCH', {'enabled': True}, alice)[0] == 200
            # Provider intentionally unavailable; explicit project memory must survive the retryable error.
            status, stream = request(chat_url + '/messages', 'POST', {'message': 'remember isolated staging preference'}, alice)
            assert status == 200 and '"type": "memory_saved"' in stream and '"type": "error"' in stream
            assert request(chat_url + '/project', 'PATCH', {'project_id': None}, alice)[0] == 409
            assert request(chat_url + '/archive', 'PATCH', {'enabled': True}, alice)[0] == 200
            assert request(project_url + '/conversations', token=alice)[1] == []
            archived = request('/web/chat/conversations?archived=true', token=alice)[1]
            assert archived[0]['id'] == cid and archived[0]['project_id'] == pid
            assert request(chat_url + '/archive', 'PATCH', {'enabled': False}, alice)[0] == 200
            assert request(chat_url, token=alice)[1]['messages'][0]['content'] == 'remember isolated staging preference'
            compose('restart', 'api')
            deadline = time.monotonic() + 20
            while True:
                try:
                    assert request('/health')[0] == 200
                    assert request(chat_url, token=alice)[1]['pinned'] == 1
                    break
                except (OSError, AssertionError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Staging API failed after restart')
                    time.sleep(0.2)
            integrity = '''from app import database
with database.get_connection() as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 rows=db.execute('SELECT user_id,content FROM memories').fetchall()
 scope=db.execute("SELECT 'web-project:' || identity_id || ':' || id FROM web_projects").fetchone()[0]
 assert len(rows)==1 and rows[0]['user_id']==scope
 assert rows[0]['content']=='isolated staging preference'
 assert db.execute('SELECT lease_until FROM web_conversations').fetchone()[0]==0
print('PASS: SQLite integrity, dedicated project memory and released response lease')'''
            compose('exec', '-T', 'api', 'python', '-c', integrity)
            assert request(project_url, token=alice)[0] == 200
            assert request(chat_url, token=alice)[1]['pinned'] == 1
            assert request(project_url, 'DELETE', {'conversations': 'keep'}, alice)[0] == 409
            assert request(project_url, 'DELETE', {'conversations': 'delete'}, alice)[0] == 200
            assert request(chat_url, token=alice)[0] == 404
            print('PASS: isolated Compose staging, non-root startup, auth/CSRF/ownership, immutable mode, rename preservation, pin/archive/restore, scope move guard, provider failure, restart persistence and explicit delete')
        finally:
            compose('down', '--volumes')  # Only this randomly named, newly created test stack.


if __name__ == '__main__':
    main()
