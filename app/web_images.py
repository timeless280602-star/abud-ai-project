"""Private image artifacts and atomic rolling quota; no Discord integration."""
import asyncio
import base64
import binascii
import io
import json
import os
import re
import time
import uuid
import warnings
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from PIL import Image
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app import database

LIMIT = 10
WINDOW = 86400
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000


class ProviderError(Exception):
    def __init__(self, code, message, uncertain=False):
        self.code, self.message, self.uncertain = code, message, uncertain


def intent(text):
    # Deliberately require a direct imperative, never scan quoted/docs/example text.
    if "\n" in text or "\r" in text:
        return None
    match = re.fullmatch(
        r'(?:please\s+|tolong\s+)?(?:generate|create|draw|buatkan|buat|bikin|gambarkan)\s+'
        r'(?:(a|an|one|two|three|four|five|six|seven|eight|nine|ten|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|\d+)\s+)?'
        r'(?:images?|pictures?|gambar|ilustrasi)(?:\s+(?:of|tentang|of a))?\s+([^\n]+)',
        text.strip(), re.IGNORECASE)
    if not match:
        # Indonesian "gambarkan naga ..." already names the action unambiguously.
        match = re.fullmatch(r'(?:tolong\s+)?gambarkan\s+([^\n]+)', text.strip(), re.IGNORECASE)
        if not match:
            return None
        count, prompt = 1, match[1]
    else:
        words = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
                 'satu': 1, 'dua': 2, 'tiga': 3, 'empat': 4, 'lima': 5, 'enam': 6,
                 'tujuh': 7, 'delapan': 8, 'sembilan': 9, 'sepuluh': 10}
        raw = (match[1] or '1').lower()
        count, prompt = words.get(raw, int(raw) if raw.isdigit() else 1), match[2]
    if any(c in prompt for c in ('"', '`', '“', '”')) or re.search(
            r'\b(?:example|contoh|documentation|dokumentasi|code|kode|prompt|how to|cara|meaning|artinya)\b', prompt, re.I):
        return None
    return count, prompt.strip()


def init_schema():
    with database.get_connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS web_image_jobs (
            id TEXT PRIMARY KEY, identity_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, user_message_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL, reserved INTEGER NOT NULL, requested INTEGER NOT NULL,
            created_at REAL NOT NULL, response_message_id INTEGER,
            error_code TEXT, error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_image_reservations ON web_image_jobs(identity_id,status);
        CREATE TABLE IF NOT EXISTS web_images (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES web_image_jobs(id),
            identity_id TEXT NOT NULL, conversation_id TEXT REFERENCES web_conversations(id) ON DELETE SET NULL,
            message_id INTEGER REFERENCES web_messages(id) ON DELETE SET NULL,
            filename TEXT NOT NULL, media_type TEXT NOT NULL, created_at REAL NOT NULL,
            charged INTEGER NOT NULL CHECK(charged IN (0,1))
        );
        CREATE INDEX IF NOT EXISTS idx_image_message ON web_images(message_id);
        CREATE INDEX IF NOT EXISTS idx_image_quota ON web_images(identity_id,charged,created_at);
        ''')


def quota(db, owner, now):
    rows = db.execute('SELECT created_at FROM web_images WHERE identity_id=? AND charged=1 AND created_at>? ORDER BY created_at',
                      (owner, now - WINDOW)).fetchall()
    held = db.execute("SELECT COALESCE(SUM(reserved),0) FROM web_image_jobs WHERE identity_id=? AND status IN ('reserved','unknown')", (owner,)).fetchone()[0]
    return len(rows), held, (rows[0][0] + WINDOW if rows else None)


def quota_notice(db, owner, now):
    used, held, reset = quota(db, owner, now)
    if used + held < LIMIT:
        return None
    return {'code': 'image_quota_exhausted',
            'reset_at': datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else None,
            'pending': bool(held), 'limit': LIMIT}


def storage():
    # Kept next to SQLite, covered by the existing /app/data volume.
    path = database.DATABASE_PATH.parent / 'generated_images'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def validate_image(encoded):
    if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES * 4 // 3 + 4):
        raise ValueError('Invalid payload')
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > MAX_BYTES:
            raise ValueError('Image too large')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                kind = image.format
                if kind not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Unsupported image')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (binascii.Error, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Invalid image') from exc
    return data, {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'), 'WEBP': ('webp', 'image/webp')}[kind]


async def provider_generate(prompt, count, job_id):
    """Explicit opt-in OpenAI-compatible b64 adapter, never assumes 9Router support."""
    endpoint = os.getenv('ABUD_IMAGE_ENDPOINT', '').strip()
    model = os.getenv('ABUD_IMAGE_MODEL', '').strip()
    key = os.getenv('ABUD_IMAGE_API_KEY', '')
    parts = urlsplit(endpoint)
    if (os.getenv('ABUD_IMAGE_PROVIDER') != 'openai-compatible-b64' or not model or not key
            or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise ProviderError('image_provider_unavailable', 'Image generation is unavailable. Ask the administrator to configure a verified image provider.')
    try:
        maximum = int(os.getenv('ABUD_IMAGE_MAX_COUNT', '1'))
        if not 1 <= maximum <= 10:
            raise ValueError
    except ValueError:
        raise ProviderError('image_provider_unavailable', 'Image provider configuration is invalid.')
    if not 1 <= count <= maximum:
        raise ProviderError('image_invalid_request', f'This provider supports 1–{maximum} images per request.')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=False) as client:
            async with client.stream('POST', endpoint, headers={'Authorization': f'Bearer {key}', 'Idempotency-Key': job_id},
                                     json={'model': model, 'prompt': prompt, 'n': count, 'response_format': 'b64_json'}) as response:
                if response.status_code in (400, 401, 403, 404, 422, 429):
                    raise ProviderError('image_generation_failed', 'The image provider rejected this request. Contact the administrator if it persists.')
                if response.status_code != 200:
                    raise ProviderError('image_generation_unknown', 'Image generation could not be confirmed. Do not retry this turn; contact the administrator.', True)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > count * (MAX_BYTES * 4 // 3 + 4096):
                        raise ValueError('Response too large')
                payload = json.loads(body)
                values = payload['data']
                if not isinstance(values, list) or len(values) > count:
                    raise ValueError('Invalid response')
                return values
    except ProviderError:
        raise
    except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
        # Once dispatched, transport/protocol failure is ambiguous. Never auto-retry.
        raise ProviderError('image_generation_unknown', 'Image generation could not be confirmed. Contact the administrator before retrying.', True) from exc


def artifacts(db, message_id):
    return [{'id': r['id'], 'url': '/web/chat/images/' + r['id']} for r in db.execute(
        'SELECT id FROM web_images WHERE message_id=? ORDER BY rowid', (message_id,))]


async def generate(owner, cid, user_message_id, count, prompt, creator, replace_id=None):
    """All callers supply identity and Creator status obtained from authenticated session."""
    from app.web_chat import event, owned
    now = time.time()
    job_id = str(uuid.uuid4())
    early = []
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        owned(db, cid, owner)
        existing = db.execute('SELECT * FROM web_image_jobs WHERE user_message_id=? AND identity_id=?', (user_message_id, owner)).fetchone()
        if existing:
            if existing['status'] in ('reserved', 'running', 'unknown'):
                early.append(event('error', code='image_generation_unknown', message='This image request is pending reconciliation. Contact the administrator before retrying.'))
            else:
                # Regenerate is a read-only replay: preserve the original assistant
                # message ID and all image foreign keys, even for partial batches.
                if existing['response_message_id']:
                    response = db.execute(
                        'SELECT content FROM web_messages WHERE id=? AND conversation_id=? AND role=?',
                        (existing['response_message_id'], cid, 'assistant'),
                    ).fetchone()
                    if response:
                        early.append(event('delta', text=response['content']))
                        saved_images = artifacts(db, existing['response_message_id'])
                        if saved_images:
                            early.append(event('images', images=saved_images))
                early.append(event('done'))
        elif not 1 <= count <= 10:
            early.append(event('error', code='image_invalid_request', message='Request 1–10 images at a time.'))
        elif not creator:
            used, held, reset = quota(db, owner, now)
            if used + held + count > LIMIT:
                notice = quota_notice(db, owner, now)
                if notice:
                    early.append(event('image_quota', **notice))
                else:
                    early.append(event('error', code='image_invalid_request', message='Request fewer images; this batch exceeds the available slots.'))
                # Finish the turn so ordinary text chat remains available.
                if replace_id:
                    db.execute('DELETE FROM web_messages WHERE id=? AND conversation_id=?', (replace_id, cid))
                db.execute('INSERT INTO web_messages(conversation_id,role,content,created_at) VALUES (?,?,?,?)',
                           (cid, 'assistant', 'Image generation limit reached for this request. Ordinary text chat remains available.', database.utc_now()))
                early.append(event('done'))
        if not early:
            db.execute('INSERT INTO web_image_jobs(id,identity_id,conversation_id,user_message_id,status,reserved,requested,created_at) VALUES (?,?,?,?,?,?,?,?)',
                       (job_id, owner, cid, user_message_id, 'running' if creator else 'reserved', 0 if creator else count, count, now))
    if early:
        for frame in early:
            yield frame
        return
    yield event('image_loading')
    result, failure = [], None
    try:
        async with asyncio.timeout(100):
            values = await provider_generate(prompt, count, job_id)
        if not isinstance(values, list) or len(values) > count:
            raise ProviderError('image_generation_unknown', 'Image response could not be verified. Contact the administrator.', True)
        for value in values:
            try:
                data, (extension, media_type) = validate_image(value.get('b64_json'))
            except (ValueError, AttributeError):
                continue  # Partial results: only durable validated images count.
            image_id = str(uuid.uuid4())
            filename = image_id + '.' + extension
            path = storage() / filename
            # Atomic durable replace before committing metadata. Orphans are private.
            temporary = path.with_suffix('.tmp')
            with temporary.open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            result.append((image_id, filename, media_type, time.time()))
        if not result:
            raise ProviderError('image_generation_failed', 'The provider returned no usable images. No image quota was charged.')
    except asyncio.CancelledError:
        with database.get_connection() as db:
            db.execute("UPDATE web_image_jobs SET status='unknown' WHERE id=?", (job_id,))
        raise
    except ProviderError as exc:
        failure = exc
    except Exception:
        failure = ProviderError('image_generation_unknown', 'Image generation could not be saved. Contact the administrator.', True)
    frames = []
    with database.get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        owned(db, cid, owner)
        if replace_id:
            db.execute('DELETE FROM web_messages WHERE id=? AND conversation_id=?', (replace_id, cid))
        answer = (f'Generated {len(result)} of {count} requested images.' if result else failure.message)
        mid = db.execute('INSERT INTO web_messages(conversation_id,role,content,created_at) VALUES (?,?,?,?)',
                         (cid, 'assistant', answer, database.utc_now())).lastrowid
        for image_id, filename, media_type, created_at in result:
            db.execute('INSERT INTO web_images VALUES (?,?,?,?,?,?,?,?,?)',
                       (image_id, job_id, owner, cid, mid, filename, media_type, created_at, int(not creator)))
        uncertain = bool(failure and failure.uncertain)
        db.execute('UPDATE web_image_jobs SET status=?,reserved=?,response_message_id=?,error_code=?,error_message=? WHERE id=?',
                   ('unknown' if uncertain else 'success' if result else 'failed',
                    max(0, count - len(result)) if uncertain and not creator else 0,
                    mid, failure.code if failure else None, failure.message if failure else None, job_id))
        frames.append(event('delta', text=answer))
        if result:
            frames.append(event('images', images=artifacts(db, mid)))
            if not creator:
                used, _, _ = quota(db, owner, time.time())
                notice = quota_notice(db, owner, time.time()) if used >= LIMIT else None
                if notice:
                    frames.append(event('image_quota', **notice))
    for frame in frames:
        yield frame
    if failure and failure.uncertain and not result:
        yield event('error', code=failure.code, message=failure.message)
    else:
        if failure:
            yield event('image_failure', code=failure.code, message=failure.message)
        yield event('done')


def image_response(image_id, owner, download=False):
    with database.get_connection() as db:
        row = db.execute('SELECT i.* FROM web_images i JOIN web_conversations c ON c.id=i.conversation_id '
                         'JOIN web_messages m ON m.id=i.message_id AND m.conversation_id=c.id '
                         'WHERE i.id=? AND i.identity_id=? AND c.identity_id=?', (image_id, owner, owner)).fetchone()
        if not row:
            raise HTTPException(404, 'Image not found.')
        path = storage() / row['filename']
        if not path.is_file():
            raise HTTPException(404, 'Image not found.')
        return FileResponse(path, media_type=row['media_type'], filename=row['filename'] if download else None,
                            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                                     'Content-Security-Policy': "default-src 'none'; sandbox"})
