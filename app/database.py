
import os
import re
import unicodedata
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

from app.memory_review import wording_match

DATABASE_PATH = Path(
    os.getenv("ABUD_DATABASE_PATH", "/app/data/abud_memory.db")
)

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database():
    # Aktifkan WAL di luar transaksi.
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    finally:
        connection.close()

    with get_connection() as db:
        # ==========================================
        # USERS
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # ==========================================
        # GUILDS
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id TEXT PRIMARY KEY,
                guild_name TEXT,
                owner_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # ==========================================
        # BOT GUILD PRESENCE
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS bot_guild_presence (
                guild_id TEXT PRIMARY KEY,
                guild_name TEXT,
                owner_id TEXT,
                is_present INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)

        # ==========================================
        # CONVERSATIONS
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # Migrasi tabel lama secara aman.
        existing_columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(conversations)"
            ).fetchall()
        }

        migrations = {
            "context_type": (
                "ALTER TABLE conversations "
                "ADD COLUMN context_type TEXT NOT NULL DEFAULT 'legacy'"
            ),
            "guild_id": (
                "ALTER TABLE conversations ADD COLUMN guild_id TEXT"
            ),
            "channel_id": (
                "ALTER TABLE conversations ADD COLUMN channel_id TEXT"
            )
        }

        for column, sql in migrations.items():
            if column not in existing_columns:
                db.execute(sql)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_context
            ON conversations(
                user_id,
                context_type,
                guild_id,
                channel_id,
                id DESC
            )
        """)

        # ==========================================
        # PERSONAL MEMORY
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user
            ON memories(user_id, id DESC)
        """)

        # ==========================================
        # GUILD MEMORY
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS guild_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by_user_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(guild_id)
                    REFERENCES guilds(guild_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_guild_memories
            ON guild_memories(guild_id, id DESC)
        """)

        # ==========================================
        # GLOBAL MEMORY
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS global_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL DEFAULT 'general',
                content TEXT NOT NULL,
                created_by_user_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_global_memories
            ON global_memories(category, id DESC)
        """)


        # Additive migration: legacy provenance and revision history are unknown.
        for table in ("memories", "guild_memories", "global_memories"):
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            if "source" not in columns:
                db.execute(f"""
                    ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL
                    DEFAULT 'unknown' CHECK(source IN ('unknown', 'direct', 'tool', 'auto', 'dashboard'))
                """)
            if "revision" not in columns:
                db.execute(f"""
                    ALTER TABLE {table} ADD COLUMN revision INTEGER NOT NULL
                    DEFAULT 0 CHECK(revision >= 0)
                """)

            if "archived_at" not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN archived_at TEXT")

        # ==========================================
        # DASHBOARD AUTHENTICATION
        # ==========================================

        db.execute("""
            CREATE TABLE IF NOT EXISTS auth_identities (
                identity_id TEXT PRIMARY KEY,
                display_name TEXT,
                email TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                disabled_at TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS canva_connections (
                identity_id TEXT PRIMARY KEY REFERENCES auth_identities(identity_id) ON DELETE CASCADE,
                token BLOB NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS auth_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_id TEXT NOT NULL,
                provider TEXT NOT NULL
                    CHECK(provider IN ('discord', 'google')),
                provider_user_id TEXT NOT NULL,
                email TEXT,
                email_verified INTEGER NOT NULL DEFAULT 0,
                display_name TEXT,
                avatar_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, provider_user_id),
                FOREIGN KEY(identity_id)
                    REFERENCES auth_identities(identity_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_auth_accounts_identity
            ON auth_accounts(identity_id)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                token_hash TEXT PRIMARY KEY,
                identity_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT,
                user_agent TEXT,
                FOREIGN KEY(identity_id)
                    REFERENCES auth_identities(identity_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_dashboard_sessions_identity
            ON dashboard_sessions(identity_id, expires_at)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_id TEXT NOT NULL,
                permission TEXT NOT NULL,
                scope_type TEXT NOT NULL DEFAULT 'global'
                    CHECK(scope_type IN ('global', 'guild')),
                scope_id TEXT NOT NULL DEFAULT '',
                granted_by_discord_id TEXT,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(identity_id)
                    REFERENCES auth_identities(identity_id)
                    ON DELETE CASCADE
            )
        """)

        # Upgrade existing databases without losing permission history.
        permission_columns = {
            row["name"]: row
            for row in db.execute(
                "PRAGMA table_info(dashboard_permissions)"
            ).fetchall()
        }

        if (
            "granted_by_discord_id" in permission_columns
            and permission_columns["granted_by_discord_id"]["notnull"]
        ):
            db.execute("""
                CREATE TABLE dashboard_permissions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    scope_type TEXT NOT NULL DEFAULT 'global'
                        CHECK(scope_type IN ('global', 'guild')),
                    scope_id TEXT NOT NULL DEFAULT '',
                    granted_by_discord_id TEXT,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(identity_id)
                        REFERENCES auth_identities(identity_id)
                        ON DELETE CASCADE
                )
            """)

            db.execute("""
                INSERT INTO dashboard_permissions_new (
                    id, identity_id, permission, scope_type, scope_id,
                    granted_by_discord_id, created_at, revoked_at
                )
                SELECT
                    id, identity_id, permission, scope_type, scope_id,
                    granted_by_discord_id, created_at, revoked_at
                FROM dashboard_permissions
            """)

            db.execute("DROP TABLE dashboard_permissions")
            db.execute("""
                ALTER TABLE dashboard_permissions_new
                RENAME TO dashboard_permissions
            """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_dashboard_permissions_identity
            ON dashboard_permissions(identity_id, revoked_at)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state_hash TEXT PRIMARY KEY,
                provider TEXT NOT NULL
                    CHECK(provider IN ('discord', 'google')),
                nonce TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_oauth_states_expiry
            ON oauth_states(expires_at)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_identity_id TEXT,
                actor_discord_id TEXT,
                action TEXT NOT NULL,
                target_identity_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_dashboard_audit_created
            ON dashboard_audit_logs(created_at DESC)
        """)

        # ==========================================
        # NEURAL ENGINE INFERENCE HISTORY
        # Stores diagnostic metadata only.
        # No prompts, completion text, or API keys.
        # ==========================================
        db.execute("""
            CREATE TABLE IF NOT EXISTS neural_inference_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_model TEXT NOT NULL,
                actual_model TEXT,
                request_status TEXT NOT NULL
                    CHECK(request_status IN ('success', 'error')),
                http_status INTEGER,
                latency_ms INTEGER,
                total_tokens INTEGER,
                response_check TEXT NOT NULL,
                error_type TEXT,
                tested_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_neural_history_tested
            ON neural_inference_history(tested_at DESC)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_neural_history_model
            ON neural_inference_history(actual_model, tested_at DESC)
        """)



        db.execute("""
            CREATE TABLE IF NOT EXISTS auth_local_credentials (
                identity_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                username_normalized TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                avatar_url TEXT,
                profile_completed_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(identity_id)
                    REFERENCES auth_identities(identity_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS auth_login_attempts (
                username_normalized TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                failed_count INTEGER NOT NULL DEFAULT 0,
                window_started_at TEXT NOT NULL,
                locked_until TEXT,
                PRIMARY KEY(username_normalized, ip_address)
            )
        """)

# ==============================================
# USER MANAGEMENT
# ==============================================

def register_user(user_id, username=None):
    if not user_id:
        return

    now = utc_now()

    with get_connection() as db:
        db.execute("""
            INSERT INTO users (
                user_id, username, created_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                updated_at = excluded.updated_at
        """, (str(user_id), username, now, now))


# ==============================================
# GUILD MANAGEMENT
# ==============================================

def register_guild(guild_id, guild_name=None, owner_id=None):
    if not guild_id:
        return

    now = utc_now()

    with get_connection() as db:
        db.execute("""
            INSERT INTO guilds (
                guild_id, guild_name, owner_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name = COALESCE(
                    excluded.guild_name, guilds.guild_name
                ),
                owner_id = COALESCE(
                    excluded.owner_id, guilds.owner_id
                ),
                updated_at = excluded.updated_at
        """, (
            str(guild_id),
            guild_name,
            str(owner_id) if owner_id else None,
            now,
            now
        ))


def sync_bot_guild(guild_id, guild_name=None, owner_id=None, is_present=True):
    if not guild_id:
        return

    now = utc_now()

    with get_connection() as db:
        db.execute("""
            INSERT INTO guilds (
                guild_id, guild_name, owner_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name = COALESCE(
                    excluded.guild_name, guilds.guild_name
                ),
                owner_id = COALESCE(
                    excluded.owner_id, guilds.owner_id
                ),
                updated_at = excluded.updated_at
        """, (
            str(guild_id),
            guild_name,
            str(owner_id) if owner_id else None,
            now,
            now
        ))

        db.execute("""
            INSERT INTO bot_guild_presence (
                guild_id, guild_name, owner_id,
                is_present, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name = COALESCE(
                    excluded.guild_name,
                    bot_guild_presence.guild_name
                ),
                owner_id = COALESCE(
                    excluded.owner_id,
                    bot_guild_presence.owner_id
                ),
                is_present = excluded.is_present,
                updated_at = excluded.updated_at
        """, (
            str(guild_id),
            guild_name,
            str(owner_id) if owner_id else None,
            int(bool(is_present)),
            now
        ))


def get_bot_guilds():
    with get_connection() as db:
        rows = db.execute("""
            SELECT guild_id, guild_name, owner_id, is_present, updated_at
            FROM bot_guild_presence
            ORDER BY guild_name COLLATE NOCASE
        """).fetchall()

    return [dict(row) for row in rows]


# ==============================================
# CONVERSATION HISTORY
# ==============================================

def save_message(
    user_id,
    role,
    content,
    keep_last=30,
    guild_id=None,
    channel_id=None,
    context_type=None
):
    if not user_id or role not in ("user", "assistant"):
        return

    content = str(content).strip()
    if not content:
        return

    if context_type is None:
        context_type = "guild" if guild_id else "dm"

    if context_type not in ("dm", "guild"):
        raise ValueError("Context type tidak valid.")

    if context_type == "guild" and not guild_id:
        raise ValueError("Guild ID wajib untuk konteks guild.")

    user_id = str(user_id)
    guild_id = str(guild_id) if guild_id else None
    channel_id = str(channel_id) if channel_id else None
    now = utc_now()

    with get_connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO users (
                user_id, username, created_at, updated_at
            )
            VALUES (?, NULL, ?, ?)
        """, (user_id, now, now))

        db.execute("""
            INSERT INTO conversations (
                user_id, role, content, created_at,
                context_type, guild_id, channel_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            role,
            content,
            now,
            context_type,
            guild_id,
            channel_id
        ))

        db.execute("""
            DELETE FROM conversations
            WHERE user_id = ?
              AND context_type = ?
              AND guild_id IS ?
              AND channel_id IS ?
              AND id NOT IN (
                  SELECT id
                  FROM conversations
                  WHERE user_id = ?
                    AND context_type = ?
                    AND guild_id IS ?
                    AND channel_id IS ?
                  ORDER BY id DESC
                  LIMIT ?
              )
        """, (
            user_id, context_type, guild_id, channel_id,
            user_id, context_type, guild_id, channel_id,
            keep_last
        ))


def get_recent_messages(
    user_id,
    limit=12,
    guild_id=None,
    channel_id=None,
    context_type=None
):
    if not user_id:
        return []

    if context_type is None:
        context_type = "guild" if guild_id else "dm"

    if context_type not in ("dm", "guild"):
        return []

    if context_type == "guild" and not guild_id:
        return []

    guild_id = str(guild_id) if guild_id else None
    channel_id = str(channel_id) if channel_id else None

    with get_connection() as db:
        rows = db.execute("""
            SELECT role, content
            FROM conversations
            WHERE user_id = ?
              AND context_type = ?
              AND guild_id IS ?
              AND channel_id IS ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            str(user_id),
            context_type,
            guild_id,
            channel_id,
            limit
        )).fetchall()

    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]


# ==============================================
# RANKED MEMORY SEARCH
# ==============================================

class ArchivedMemoryError(ValueError):
    """A write would bypass an explicit archive/restore decision."""


def _memory_search_scope(scope, user_id, guild_id, archived=False):
    if type(archived) is not bool:
        raise ValueError("Status arsip tidak valid.")
    if scope == "personal":
        if not user_id:
            return None
        table, where, params = "memories", "user_id = ?", (str(user_id),)
        columns = "id, content, created_at, updated_at, source, revision"
    elif scope == "guild":
        if not guild_id:
            return None
        table, where, params = "guild_memories", "guild_id = ?", (str(guild_id),)
        columns = "id, guild_id, content, created_by_user_id, created_at, updated_at, source, revision"
    elif scope == "global":
        table, where, params = "global_memories", "1 = 1", ()
        columns = "id, category, content, created_by_user_id, created_at, updated_at, source, revision"
    else:
        raise ValueError("Scope Memory tidak valid.")

    where += " AND archived_at IS NOT NULL" if archived else " AND archived_at IS NULL"
    return table, where, params, columns + ", archived_at"


def search_memories(scope, query, *, user_id=None, guild_id=None, limit=5, archived=False):
    """Search one scope; callers must authorize the supplied identity first.

    Rank contiguous token phrases above word overlap, then newest ID.
    Empty queries list newest records (dashboard); punctuation alone matches none.
    """
    if not isinstance(query, str) or len(query.strip()) > 200:
        raise ValueError("Query pencarian harus berupa teks maksimal 200 karakter.")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("Limit pencarian harus berupa bilangan bulat.")
    limit = max(1, min(limit, 100))

    selection = _memory_search_scope(scope, user_id, guild_id, archived=archived)
    if selection is None:
        return []
    table, where, params, columns = selection

    def tokens(text):
        return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())

    query = query.strip()
    words = tokens(query)
    terms = set(words)
    phrase = " " + " ".join(words) + " "
    if query and not words:
        return []

    def score(text):
        content_words = tokens(text)
        hits = len(terms.intersection(content_words))
        if not hits:
            return 0
        # Query length bounds overlap below 1000, so phrase matches always lead.
        return 1000 * (phrase in " " + " ".join(content_words) + " ") + hits

    with get_connection() as db:
        # ponytail: scan the authorized scope; add an FTS index when measured latency warrants it.
        db.create_function("memory_score", 1, score, deterministic=True)
        ranking = "memory_score(content)"
        if scope == "global":
            ranking = "MAX(memory_score(content), memory_score(category))"
        if query:
            rows = db.execute(f"""
                SELECT {columns} FROM {table}
                WHERE {where} AND {ranking} > 0
                ORDER BY {ranking} DESC, id DESC LIMIT ?
            """, (*params, limit)).fetchall()
        else:
            rows = db.execute(f"""
                SELECT {columns} FROM {table}
                WHERE {where} ORDER BY id DESC LIMIT ?
            """, (*params, limit)).fetchall()
    return [dict(row) for row in rows]


def find_similar_memories(scope, content, *, user_id=None, guild_id=None,
                          category="general", exclude_memory_id=None, limit=5, include_unmatched=False):
    """Rank wording candidates across one authorized scope before limiting results."""
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 1000:
        raise ValueError("Isi Memory harus berisi 1 sampai 1000 karakter.")
    if type(limit) is not int or type(include_unmatched) is not bool:
        raise ValueError("Limit atau mode pencarian tidak valid.")
    if exclude_memory_id is not None and (type(exclude_memory_id) is not int or exclude_memory_id < 1):
        raise ValueError("Memory ID tidak valid.")
    selection = _memory_search_scope(scope, user_id, guild_id)
    if selection is None:
        return []
    table, where, params, columns = selection
    if scope == "global":
        where += " AND category = ?"
        params += (str(category).strip() or "general",)
    if exclude_memory_id is not None:
        where += " AND id != ?"
        params += (exclude_memory_id,)

    def similarity(existing):
        result = wording_match(content, existing)
        return round(result['similarity'] * 1000) if result else 0

    if not include_unmatched:
        where += " AND memory_similarity(content) > 0"
    with get_connection() as db:
        # ponytail: scan one scope; consider an index when measured latency warrants it.
        db.create_function("memory_similarity", 1, similarity, deterministic=True)
        rows = db.execute(f"""
            SELECT {columns} FROM {table}
            WHERE {where}
            ORDER BY memory_similarity(content) DESC, id DESC LIMIT ?
        """, (*params, max(1, min(limit, 10)))).fetchall()
    return [{**dict(row), **(wording_match(content, row['content']) or {
        'similarity': 0, 'relation': 'unmatched',
        'reason': 'Tidak ada kemiripan kata; kandidat terbaru untuk tinjauan makna.',
    })} for row in rows]


# ==============================================
# PERSONAL MEMORY
# ==============================================

def _validate_memory_source(source):
    if source not in ("unknown", "direct", "tool", "auto", "dashboard"):
        raise ValueError("Sumber Memory tidak valid.")


def save_memory(user_id, content, *, source="unknown"):
    if not user_id:
        raise ValueError("User ID wajib tersedia.")

    content = str(content).strip()
    if not content:
        raise ValueError("Isi memori tidak boleh kosong.")

    _validate_memory_source(source)
    now = utc_now()
    user_id = str(user_id)

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            INSERT OR IGNORE INTO users (
                user_id, username, created_at, updated_at
            )
            VALUES (?, NULL, ?, ?)
        """, (user_id, now, now))

        existing = db.execute("""
            SELECT id, archived_at FROM memories
            WHERE user_id = ? AND content = ?
            ORDER BY archived_at IS NOT NULL, id DESC LIMIT 1
        """, (user_id, content)).fetchone()

        if existing:
            if existing["archived_at"] is not None:
                raise ArchivedMemoryError("Memory ini diarsipkan. Pulihkan melalui dashboard sebelum menyimpan ulang.")
            db.execute("""
                UPDATE memories
                SET updated_at = ?
                WHERE id = ? AND archived_at IS NULL
            """, (now, existing["id"]))
            return existing["id"]

        cursor = db.execute("""
            INSERT INTO memories (
                user_id, content, created_at, updated_at, source, revision
            )
            VALUES (?, ?, ?, ?, ?, 1)
        """, (user_id, content, now, now, source))

        return cursor.lastrowid


def get_memories(user_id, limit=50):
    if not user_id:
        return []

    with get_connection() as db:
        rows = db.execute("""
            SELECT id, content, created_at, updated_at, source, revision, archived_at
            FROM memories
            WHERE user_id = ? AND archived_at IS NULL
            ORDER BY id DESC
            LIMIT ?
        """, (str(user_id), limit)).fetchall()

    return [dict(row) for row in rows]


def delete_memory(user_id, memory_id):
    if not user_id:
        return False

    with get_connection() as db:
        cursor = db.execute("""
            DELETE FROM memories
            WHERE id = ? AND user_id = ? AND archived_at IS NULL
        """, (int(memory_id), str(user_id)))

    return cursor.rowcount > 0


def update_memory(user_id, memory_id, content):
    if not user_id:
        return False

    content = str(content).strip()
    if not content:
        raise ValueError("Isi memori tidak boleh kosong.")

    now = utc_now()

    with get_connection() as db:
        cursor = db.execute("""
            UPDATE memories
            SET content = ?, updated_at = ?, revision = revision + 1
            WHERE id = ? AND user_id = ? AND archived_at IS NULL
        """, (content, now, int(memory_id), str(user_id)))

    return cursor.rowcount > 0


# ==============================================
# GUILD MEMORY
# ==============================================

def save_guild_memory(guild_id, content, created_by_user_id=None, *, source="unknown"):
    if not guild_id:
        raise ValueError("Guild ID wajib tersedia.")

    content = str(content).strip()
    if not content:
        raise ValueError("Isi guild memory tidak boleh kosong.")

    guild_id = str(guild_id)
    _validate_memory_source(source)
    now = utc_now()

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            INSERT OR IGNORE INTO guilds (
                guild_id, guild_name, owner_id,
                created_at, updated_at
            )
            VALUES (?, NULL, NULL, ?, ?)
        """, (guild_id, now, now))

        existing = db.execute("""
            SELECT id, archived_at FROM guild_memories
            WHERE guild_id = ? AND content = ?
            ORDER BY archived_at IS NOT NULL, id DESC LIMIT 1
        """, (guild_id, content)).fetchone()

        if existing:
            if existing["archived_at"] is not None:
                raise ArchivedMemoryError("Memory ini diarsipkan. Pulihkan melalui dashboard sebelum menyimpan ulang.")
            db.execute("""
                UPDATE guild_memories
                SET updated_at = ?
                WHERE id = ? AND archived_at IS NULL
            """, (now, existing["id"]))
            return existing["id"]

        cursor = db.execute("""
            INSERT INTO guild_memories (
                guild_id, content, created_by_user_id,
                created_at, updated_at, source, revision
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            guild_id,
            content,
            str(created_by_user_id) if created_by_user_id else None,
            now,
            now,
            source
        ))

        return cursor.lastrowid


def get_guild_memories(guild_id, limit=50):
    if not guild_id:
        return []

    with get_connection() as db:
        rows = db.execute("""
            SELECT id, guild_id, content, created_by_user_id,
                   created_at, updated_at, source, revision, archived_at
            FROM guild_memories
            WHERE guild_id = ? AND archived_at IS NULL
            ORDER BY id DESC
            LIMIT ?
        """, (str(guild_id), limit)).fetchall()

    return [dict(row) for row in rows]



def update_guild_memory(guild_id, memory_id, content):
    if not guild_id:
        return False

    content = str(content).strip()
    if not content:
        raise ValueError("Isi guild memory tidak boleh kosong.")

    now = utc_now()

    with get_connection() as db:
        cursor = db.execute("""
            UPDATE guild_memories
            SET content = ?, updated_at = ?, revision = revision + 1
            WHERE id = ? AND guild_id = ? AND archived_at IS NULL
        """, (
            content,
            now,
            int(memory_id),
            str(guild_id)
        ))

    return cursor.rowcount > 0


def delete_guild_memory(guild_id, memory_id):
    if not guild_id:
        return False

    with get_connection() as db:
        cursor = db.execute("""
            DELETE FROM guild_memories
            WHERE id = ? AND guild_id = ? AND archived_at IS NULL
        """, (int(memory_id), str(guild_id)))

    return cursor.rowcount > 0


# ==============================================
# GLOBAL MEMORY
# ==============================================

def save_global_memory(
    content,
    category="general",
    created_by_user_id=None,
    *, source="unknown"
):
    content = str(content).strip()
    category = str(category).strip() or "general"

    if not content:
        raise ValueError("Isi global memory tidak boleh kosong.")

    _validate_memory_source(source)
    now = utc_now()

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("""
            SELECT id, archived_at FROM global_memories
            WHERE category = ? AND content = ?
            ORDER BY archived_at IS NOT NULL, id DESC LIMIT 1
        """, (category, content)).fetchone()

        if existing:
            if existing["archived_at"] is not None:
                raise ArchivedMemoryError("Memory ini diarsipkan. Pulihkan melalui dashboard sebelum menyimpan ulang.")
            db.execute("""
                UPDATE global_memories
                SET updated_at = ?
                WHERE id = ? AND archived_at IS NULL
            """, (now, existing["id"]))
            return existing["id"]

        cursor = db.execute("""
            INSERT INTO global_memories (
                category, content, created_by_user_id,
                created_at, updated_at, source, revision
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            category,
            content,
            str(created_by_user_id) if created_by_user_id else None,
            now,
            now,
            source
        ))

        return cursor.lastrowid


def get_global_memories(category=None, limit=100):
    with get_connection() as db:
        if category:
            rows = db.execute("""
                SELECT id, category, content, created_by_user_id,
                       created_at, updated_at, source, revision, archived_at
                FROM global_memories
                WHERE category = ? AND archived_at IS NULL
                ORDER BY id DESC
                LIMIT ?
            """, (category, limit)).fetchall()
        else:
            rows = db.execute("""
                SELECT id, category, content, created_by_user_id,
                       created_at, updated_at, source, revision, archived_at
                FROM global_memories
                WHERE archived_at IS NULL
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()

    return [dict(row) for row in rows]


def delete_global_memory(memory_id):
    with get_connection() as db:
        cursor = db.execute("""
            DELETE FROM global_memories WHERE id = ? AND archived_at IS NULL
        """, (int(memory_id),))

    return cursor.rowcount > 0


# ==============================================
def update_global_memory(memory_id, content, category=None):
    content = str(content).strip()

    if not content:
        raise ValueError("Isi global memory tidak boleh kosong.")

    now = utc_now()

    with get_connection() as db:
        if category is None:
            cursor = db.execute("""
                UPDATE global_memories
                SET content = ?, updated_at = ?, revision = revision + 1
                WHERE id = ? AND archived_at IS NULL
            """, (content, now, int(memory_id)))
        else:
            cursor = db.execute("""
                UPDATE global_memories
                SET content = ?, category = ?, updated_at = ?, revision = revision + 1
                WHERE id = ? AND archived_at IS NULL
            """, (content, str(category).strip() or "general",
                  now, int(memory_id)))

    return cursor.rowcount > 0


def set_memory_archived(scope, memory_id, archived, *, user_id=None, guild_id=None):
    """Transition exactly one authorized record without changing its content metadata."""
    if type(memory_id) is not int or memory_id < 1 or type(archived) is not bool:
        raise ValueError("Memory ID atau status arsip tidak valid.")
    selection = _memory_search_scope(scope, user_id, guild_id, archived=not archived)
    if selection is None:
        return False
    table, where, params, columns = selection
    with get_connection() as db:
        # Serialize conflict check and restore with other SQLite writers.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(f"SELECT {columns} FROM {table} WHERE {where} AND id = ?", (*params, memory_id)).fetchone()
        if row is None:
            return False
        if not archived:
            _, active_where, active_params, _ = _memory_search_scope(scope, user_id, guild_id)
            active_where += " AND content = ?"
            active_params += (row['content'],)
            if scope == 'global':
                active_where += " AND category = ?"
                active_params += (row['category'],)
            if db.execute(f"SELECT id FROM {table} WHERE {active_where} LIMIT 1", active_params).fetchone():
                raise ArchivedMemoryError("Sudah ada Memory aktif dengan isi yang sama. Arsip tetap disimpan.")
        cursor = db.execute(f"UPDATE {table} SET archived_at = ? WHERE {where} AND id = ?",
                            (utc_now() if archived else None, *params, memory_id))
    return cursor.rowcount > 0


# USER DATA MANAGEMENT
# ==============================================

def clear_user_data(user_id):
    if not user_id:
        return

    with get_connection() as db:
        db.execute("""
            DELETE FROM users WHERE user_id = ?
        """, (str(user_id),))


# ==============================================
# DATABASE STATUS
# ==============================================

def get_database_status():
    with get_connection() as db:
        users = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        conversations = db.execute(
            "SELECT COUNT(*) FROM conversations"
        ).fetchone()[0]

        memories = db.execute(
            "SELECT COUNT(*) FROM memories"
        ).fetchone()[0]

        guilds = db.execute(
            "SELECT COUNT(*) FROM guilds"
        ).fetchone()[0]

        guild_memories = db.execute(
            "SELECT COUNT(*) FROM guild_memories"
        ).fetchone()[0]

        global_memories = db.execute(
            "SELECT COUNT(*) FROM global_memories"
        ).fetchone()[0]

    return {
        "database": str(DATABASE_PATH),
        "users": users,
        "conversations": conversations,
        "personal_memories": memories,
        "guilds": guilds,
        "guild_memories": guild_memories,
        "global_memories": global_memories
    }


# ==============================================
# NEURAL ENGINE INFERENCE HISTORY
# ==============================================

def record_neural_inference(
    requested_model,
    actual_model=None,
    request_status="error",
    http_status=None,
    latency_ms=None,
    total_tokens=None,
    response_check="ERROR",
    error_type=None,
    tested_at=None,
):
    now = tested_at or utc_now()

    with get_connection() as db:
        cursor = db.execute("""
            INSERT INTO neural_inference_history (
                requested_model,
                actual_model,
                request_status,
                http_status,
                latency_ms,
                total_tokens,
                response_check,
                error_type,
                tested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(requested_model or "Unknown")[:200],
            str(actual_model)[:200] if actual_model else None,
            request_status,
            http_status,
            latency_ms,
            total_tokens,
            str(response_check or "ERROR")[:40],
            str(error_type)[:80] if error_type else None,
            now,
        ))

        return cursor.lastrowid



def get_neural_inference_history(limit=50, period="all"):
    from datetime import datetime, timedelta, timezone
    import math

    limit = max(1, min(int(limit), 200))
    period_days = {
        "24h": 1,
        "7d": 7,
        "30d": 30,
        "all": None,
    }

    if period not in period_days:
        raise ValueError("Invalid analytics period")

    days = period_days[period]
    cutoff = (
        (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        if days else None
    )

    where = "WHERE (? IS NULL OR julianday(tested_at) >= julianday(?))"
    params = (cutoff, cutoff)

    def percentile(values, pct):
        if not values:
            return None
        values = sorted(values)
        index = max(0, math.ceil(pct * len(values)) - 1)
        return round(values[index])

    def rate(numerator, denominator):
        return round((numerator or 0) * 100 / denominator, 1) if denominator else 0.0

    with get_connection() as db:
        rows = db.execute(f"""
            SELECT
                id, requested_model, actual_model, request_status,
                http_status, latency_ms, total_tokens,
                response_check, error_type, tested_at
            FROM neural_inference_history
            {where}
            ORDER BY id DESC
            LIMIT ?
        """, (*params, limit)).fetchall()

        summary_row = db.execute(f"""
            SELECT
                COUNT(*) AS total_tests,
                COALESCE(SUM(CASE WHEN request_status='success' THEN 1 ELSE 0 END),0)
                    AS successful_requests,
                COALESCE(SUM(CASE WHEN request_status='error' THEN 1 ELSE 0 END),0)
                    AS failed_requests,
                COALESCE(SUM(CASE WHEN response_check='EXACT_MATCH' THEN 1 ELSE 0 END),0)
                    AS exact_matches,
                COALESCE(SUM(CASE WHEN response_check='EXTRA_TEXT' THEN 1 ELSE 0 END),0)
                    AS extra_text,
                COALESCE(SUM(CASE WHEN response_check='MISMATCH' THEN 1 ELSE 0 END),0)
                    AS mismatches,
                COALESCE(SUM(CASE WHEN response_check='NO_TEXT' THEN 1 ELSE 0 END),0)
                    AS no_text,
                ROUND(AVG(latency_ms)) AS average_latency_ms,
                MAX(latency_ms) AS maximum_latency_ms
            FROM neural_inference_history
            {where}
        """, params).fetchone()

        model_rows = db.execute(f"""
            SELECT
                actual_model,
                COUNT(*) AS total_tests,
                SUM(CASE WHEN request_status='success' THEN 1 ELSE 0 END)
                    AS successful_requests,
                SUM(CASE WHEN request_status='error' THEN 1 ELSE 0 END)
                    AS failed_requests,
                SUM(CASE WHEN response_check='EXACT_MATCH' THEN 1 ELSE 0 END)
                    AS exact_matches,
                SUM(CASE WHEN response_check='EXTRA_TEXT' THEN 1 ELSE 0 END)
                    AS extra_text,
                SUM(CASE WHEN response_check='MISMATCH' THEN 1 ELSE 0 END)
                    AS mismatches,
                SUM(CASE WHEN response_check='NO_TEXT' THEN 1 ELSE 0 END)
                    AS no_text,
                ROUND(AVG(latency_ms)) AS average_latency_ms
            FROM neural_inference_history
            {where}
            AND actual_model IS NOT NULL
            GROUP BY actual_model
            ORDER BY total_tests DESC, actual_model COLLATE NOCASE
        """, params).fetchall()

        latency_rows = db.execute(f"""
            SELECT actual_model, latency_ms
            FROM neural_inference_history
            {where}
            AND latency_ms IS NOT NULL
        """, params).fetchall()

    summary = dict(summary_row)
    all_latencies = [r["latency_ms"] for r in latency_rows]
    total = summary["total_tests"]

    summary["success_rate"] = rate(summary["successful_requests"], total)
    summary["exact_match_rate"] = rate(summary["exact_matches"], total)
    summary["error_rate"] = rate(summary["failed_requests"], total)
    summary["p50_latency_ms"] = percentile(all_latencies, 0.50)
    summary["p95_latency_ms"] = percentile(all_latencies, 0.95)

    model_latencies = {}
    for row in latency_rows:
        name = row["actual_model"]
        if name:
            model_latencies.setdefault(name, []).append(row["latency_ms"])

    models = []
    for row in model_rows:
        model = dict(row)
        count = model["total_tests"]
        values = model_latencies.get(model["actual_model"], [])

        model["success_rate"] = rate(model["successful_requests"], count)
        model["exact_match_rate"] = rate(model["exact_matches"], count)
        model["error_rate"] = rate(model["failed_requests"], count)
        model["p50_latency_ms"] = percentile(values, 0.50)
        model["p95_latency_ms"] = percentile(values, 0.95)
        models.append(model)

    return {
        "period": period,
        "summary": summary,
        "models": models,
        "history": [dict(row) for row in rows],
    }
