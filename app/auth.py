import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
import httpx
from pathlib import Path

from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, Form, File, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app import database


router = APIRouter()
oauth = OAuth()

BASE_URL = os.getenv("ABUD_BASE_URL", "").rstrip("/")
SESSION_COOKIE = "abud_session"
SESSION_LIFETIME_DAYS = 30
SESSION_SHORT_HOURS = 12
PASSWORD_ITERATIONS = 600000
AVATAR_DIR = database.DATABASE_PATH.parent / "profile_avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
CREATOR_DISCORD_ID = "1357798812168618044"

ALLOWED_DASHBOARD_PERMISSIONS = {
    "dashboard.view",
    "overview.view",
    "ai_config.view",
    "ai_config.manage",
    "memory.personal.view",
    "memory.personal.manage",
    "memory.guild.view",
    "memory.guild.manage",
    "server.view",
    "server.manage",
    "activity_logs.view",
    "knowledge_base.view",
    "knowledge_base.manage",
    "automation.view",
    "automation.manage",
    "system_settings.view",
    "permissions.delegate",
}

if not BASE_URL.startswith("https://"):
    raise RuntimeError("ABUD_BASE_URL harus menggunakan HTTPS.")

required_env = (
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "ABUD_SESSION_SECRET",
)

missing_env = [key for key in required_env if not os.getenv(key)]
if missing_env:
    raise RuntimeError(
        "OAuth configuration missing: " + ", ".join(missing_env)
    )


oauth.register(
    name="discord",
    client_id=os.getenv("DISCORD_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("DISCORD_OAUTH_CLIENT_SECRET"),
    authorize_url="https://discord.com/oauth2/authorize",
    access_token_url="https://discord.com/api/oauth2/token",
    api_base_url="https://discord.com/api/",
    client_kwargs={"scope": "identify email", "code_challenge_method": "S256"},
)

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()



def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(calculated.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def client_ip(request):
    # Jangan percaya X-Forwarded-For dari browser.
    return request.client.host if request.client else "unknown"


def get_or_create_identity(provider, profile):
    provider_user_id = str(profile["id"])
    now = iso_now()

    with database.get_connection() as db:
        account = db.execute(
            """
            SELECT identity_id
            FROM auth_accounts
            WHERE provider = ? AND provider_user_id = ?
            """,
            (provider, provider_user_id),
        ).fetchone()

        if account:
            identity_id = account["identity_id"]
            identity = db.execute(
                """
                SELECT disabled_at
                FROM auth_identities
                WHERE identity_id = ?
                """,
                (identity_id,),
            ).fetchone()

            if not identity or identity["disabled_at"]:
                raise HTTPException(
                    status_code=403,
                    detail="Akun dashboard dinonaktifkan.",
                )

            db.execute(
                """
                UPDATE auth_accounts
                SET email = ?,
                    email_verified = ?,
                    display_name = ?,
                    avatar_url = ?,
                    updated_at = ?
                WHERE provider = ? AND provider_user_id = ?
                """,
                (
                    profile.get("email"),
                    int(bool(profile.get("email_verified"))),
                    profile.get("display_name"),
                    profile.get("avatar_url"),
                    now,
                    provider,
                    provider_user_id,
                ),
            )
            db.execute(
                """
                UPDATE auth_identities
                SET display_name = COALESCE(?, display_name),
                    email = COALESCE(?, email),
                    updated_at = ?
                WHERE identity_id = ?
                """,
                (
                    profile.get("display_name"),
                    profile.get("email"),
                    now,
                    identity_id,
                ),
            )
            return identity_id

        # Akun provider baru selalu mendapatkan identitas terpisah.
        # Email yang sama tidak pernah digunakan untuk auto-link.
        identity_id = str(uuid.uuid4())

        db.execute(
            """
            INSERT INTO auth_identities (
                identity_id, display_name, email,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                identity_id,
                profile.get("display_name"),
                profile.get("email"),
                now,
                now,
            ),
        )

        db.execute(
            """
            INSERT INTO auth_accounts (
                identity_id, provider, provider_user_id,
                email, email_verified, display_name,
                avatar_url, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity_id,
                provider,
                provider_user_id,
                profile.get("email"),
                int(bool(profile.get("email_verified"))),
                profile.get("display_name"),
                profile.get("avatar_url"),
                now,
                now,
            ),
        )

        db.execute(
            """
            INSERT INTO dashboard_audit_logs (
                actor_identity_id, actor_discord_id,
                action, target_identity_id, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                identity_id,
                provider_user_id if provider == "discord" else None,
                "oauth_account_created",
                identity_id,
                provider,
                now,
            ),
        )

    return identity_id


def create_session(identity_id, old_token=None, user_agent=None, remember_me=False, login_method='oauth'):
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)
    now = utc_now()
    now_text = now.isoformat()
    expires = now + (timedelta(days=SESSION_LIFETIME_DAYS) if remember_me else timedelta(hours=SESSION_SHORT_HOURS))

    with database.get_connection() as db:
        if old_token:
            db.execute(
                """
                UPDATE dashboard_sessions
                SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (now_text, hash_token(old_token)),
            )

        db.execute(
            """
            INSERT INTO dashboard_sessions (
                token_hash, identity_id, created_at,
                expires_at, last_seen_at, user_agent
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token_hash,
                identity_id,
                now_text,
                expires.isoformat(),
                now_text,
                (user_agent or "")[:512],
            ),
        )

        discord = db.execute(
            """
            SELECT provider_user_id
            FROM auth_accounts
            WHERE identity_id = ? AND provider = 'discord'
            LIMIT 1
            """,
            (identity_id,),
        ).fetchone()

        db.execute(
            """
            INSERT INTO dashboard_audit_logs (
                actor_identity_id, actor_discord_id,
                action, target_identity_id, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                identity_id,
                discord["provider_user_id"] if discord else None,
                "dashboard_login",
                identity_id,
                f"{login_method} session created; remember_me={bool(remember_me)}",
                now_text,
            ),
        )

    return raw_token


def get_current_identity(request):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return None

    token_hash = hash_token(raw_token)
    now = iso_now()

    with database.get_connection() as db:
        row = db.execute(
            """
            SELECT
                i.identity_id,
                i.display_name,
                i.email,
                i.disabled_at,
                s.expires_at
            FROM dashboard_sessions s
            JOIN auth_identities i
              ON i.identity_id = s.identity_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
            """,
            (token_hash,),
        ).fetchone()

        if not row or row["disabled_at"] or row["expires_at"] <= now:
            return None

        accounts = db.execute(
            """
            SELECT provider, email, email_verified, display_name, avatar_url
            FROM auth_accounts
            WHERE identity_id = ?
            ORDER BY provider
            """,
            (row["identity_id"],),
        ).fetchall()

        discord = db.execute(
            """
            SELECT provider_user_id
            FROM auth_accounts
            WHERE identity_id = ? AND provider = 'discord'
            LIMIT 1
            """,
            (row["identity_id"],),
        ).fetchone()

        permissions = db.execute(
            """
            SELECT permission, scope_type, scope_id
            FROM dashboard_permissions
            WHERE identity_id = ?
              AND revoked_at IS NULL
            ORDER BY permission, scope_type, scope_id
            """,
            (row["identity_id"],),
        ).fetchall()

        local_profile = db.execute(
            """
            SELECT username, avatar_url, profile_completed_at
            FROM auth_local_credentials
            WHERE identity_id = ?
            """,
            (row["identity_id"],),
        ).fetchone()

        db.execute(
            """
            UPDATE dashboard_sessions
            SET last_seen_at = ?
            WHERE token_hash = ?
            """,
            (now, token_hash),
        )

    is_creator = bool(
        discord
        and discord["provider_user_id"] == CREATOR_DISCORD_ID
    )

    provider_avatars = {
        account["provider"]: account["avatar_url"]
        for account in accounts
        if account["avatar_url"]
    }
    effective_avatar = (
        (local_profile["avatar_url"] if local_profile else None)
        or provider_avatars.get("discord")
        or provider_avatars.get("google")
    )

    return {
        "identity_id": row["identity_id"],
        "display_name": row["display_name"],
        "email": row["email"],
        "username": local_profile["username"] if local_profile else None,
        "avatar_url": effective_avatar,
        "profile_completed": bool(local_profile),
        "profile_required": not bool(local_profile),
        "is_creator": is_creator,
        "full_control": is_creator,
        "discord_linked": bool(discord),
        "accounts": [
            {
                "provider": account["provider"],
                "email": account["email"],
                "email_verified": bool(account["email_verified"]),
                "display_name": account["display_name"],
            }
            for account in accounts
        ],
        "permissions": [
            {
                "permission": permission["permission"],
                "scope_type": permission["scope_type"],
                "scope_id": permission["scope_id"],
            }
            for permission in permissions
        ],
        "dashboard_access": (
            is_creator
            or any(
                permission["scope_type"] == "guild"
                or (
                    permission["permission"] == "dashboard.view"
                    and permission["scope_type"] == "global"
                    and permission["scope_id"] == "*"
                )
                for permission in permissions
            )
        ),
    }


def set_session_cookie(response, raw_token, remember_me=False):
    cookie_options = dict(
        key=SESSION_COOKIE,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite='lax',
        path='/',
    )
    if remember_me:
        cookie_options['max_age'] = SESSION_LIFETIME_DAYS * 24 * 60 * 60
    response.set_cookie(**cookie_options)


def _legacy_cookie_marker(response, raw_token):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=SESSION_LIFETIME_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


async def discord_profile(request):
    token = await oauth.discord.authorize_access_token(request)
    response = await oauth.discord.get("users/@me", token=token)
    profile = response.json()

    if not profile.get("id"):
        raise ValueError("Discord identity is missing.")

    discord_user_id = str(profile["id"])
    avatar_hash = profile.get("avatar")

    if avatar_hash:
        extension = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/"
            f"{discord_user_id}/{avatar_hash}.{extension}?size=256"
        )
    else:
        # Discord default avatar:
        # legacy discriminator accounts use discriminator % 5;
        # newer usernames use (user_id >> 22) % 6.
        discriminator = profile.get("discriminator")
        if discriminator and str(discriminator) != "0":
            default_index = int(discriminator) % 5
        else:
            default_index = (int(discord_user_id) >> 22) % 6

        avatar_url = (
            f"https://cdn.discordapp.com/embed/avatars/"
            f"{default_index}.png"
        )

    return {
        "id": discord_user_id,
        "email": profile.get("email"),
        "email_verified": bool(profile.get("verified", False)),
        "display_name": (
            profile.get("global_name")
            or profile.get("username")
            or "Discord User"
        ),
        "avatar_url": avatar_url,
    }


async def google_profile(request):
    token = await oauth.google.authorize_access_token(request)
    profile = token.get("userinfo")

    if not profile:
        raise ValueError("Google ID token was not validated.")

    if not profile or not profile.get("sub"):
        raise ValueError("Google identity is missing.")

    if not profile.get("email_verified"):
        raise ValueError("Google email is not verified.")

    return {
        "id": str(profile["sub"]),
        "email": profile.get("email"),
        "email_verified": True,
        "display_name": profile.get("name") or "Google User",
        "avatar_url": profile.get("picture"),
    }


async def finish_login(request, provider):
    try:
        if provider == "discord":
            profile = await discord_profile(request)
        else:
            profile = await google_profile(request)

        identity_id = get_or_create_identity(provider, profile)

        remember_me = bool(request.session.pop("abud_remember_me", False))
        old_token = request.cookies.get(SESSION_COOKIE)
        raw_token = create_session(
            identity_id,
            old_token,
            request.headers.get("user-agent", ""),
            remember_me=remember_me,
            login_method=provider,
        )

        response = RedirectResponse(url="/", status_code=303)
        set_session_cookie(response, raw_token, remember_me)
        return response

    except HTTPException:
        raise
    except Exception as exc:
        # Jangan pernah mencatat access token, secret, atau callback query.
        print(
            f"OAuth callback failed: provider={provider}, "
            f"error={type(exc).__name__}"
        )
        raise HTTPException(
            status_code=400,
            detail="Login gagal. Silakan ulangi proses login.",
        )


@router.get("/auth/discord/login")
async def discord_login(request: Request):
    request.session["abud_remember_me"] = request.query_params.get("remember") == "1"
    redirect_uri = BASE_URL + "/auth/discord/callback"
    return await oauth.discord.authorize_redirect(request, redirect_uri)


@router.get("/auth/discord/callback")
async def discord_callback(request: Request):
    return await finish_login(request, "discord")


@router.get("/auth/google/login")
async def google_login(request: Request):
    request.session["abud_remember_me"] = request.query_params.get("remember") == "1"
    redirect_uri = BASE_URL + "/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(request: Request):
    return await finish_login(request, "google")


async def verify_guild_membership(guild_id: str, discord_user_id: str):
    """
    Verifikasi live melalui bot.
    User ID selalu berasal dari akun Discord yang tertaut,
    bukan dari input browser.
    """
    verify_url = os.getenv("ABUD_BOT_VERIFY_URL", "").strip()
    internal_key = os.getenv("ABUD_INTERNAL_API_KEY", "")

    if not verify_url or not internal_key:
        raise HTTPException(
            status_code=503,
            detail="Layanan verifikasi Discord belum dikonfigurasi."
        )

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                verify_url,
                json={
                    "guild_id": guild_id,
                    "user_id": discord_user_id,
                },
                headers={
                    "Authorization": f"Bearer {internal_key}",
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail="Verifikasi Discord sementara tidak tersedia."
            )

        result = response.json()

        if (
            result.get("verified") is not True
            or str(result.get("guild_id", "")) != guild_id
            or str(result.get("user_id", "")) != discord_user_id
        ):
            raise HTTPException(
                status_code=503,
                detail="Respons verifikasi Discord tidak valid."
            )

        return result

    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=503,
            detail="Tidak dapat menghubungi layanan verifikasi Discord."
        )


@router.get("/auth/guilds")
async def auth_guilds(request: Request):
    identity = get_current_identity(request)

    if not identity:
        raise HTTPException(status_code=401, detail="Belum login.")
    if not identity.get("profile_completed"):
        raise HTTPException(status_code=403, detail="Selesaikan pembuatan akun terlebih dahulu.")

    # Google-only tetap dapat menggunakan permission global,
    # tetapi tidak memperoleh akses server Discord.
    with database.get_connection() as db:
        discord_account = db.execute(
            """
            SELECT provider_user_id
            FROM auth_accounts
            WHERE identity_id = ?
              AND provider = 'discord'
            LIMIT 1
            """,
            (identity["identity_id"],),
        ).fetchone()

        guilds = db.execute(
            """
            SELECT guild_id, guild_name
            FROM bot_guild_presence
            WHERE is_present = 1
            ORDER BY guild_name COLLATE NOCASE
            """
        ).fetchall()

        permission_rows = db.execute(
            """
            SELECT permission, scope_type, scope_id
            FROM dashboard_permissions
            WHERE identity_id = ?
              AND revoked_at IS NULL
            """,
            (identity["identity_id"],),
        ).fetchall()

    global_permissions = {
        row["permission"]
        for row in permission_rows
        if row["scope_type"] == "global"
        and row["scope_id"] == "*"
    }

    guild_permissions = {}
    for row in permission_rows:
        if row["scope_type"] == "guild":
            guild_permissions.setdefault(row["scope_id"], set()).add(
                row["permission"]
            )

    result = []

    if discord_account:
        discord_user_id = str(discord_account["provider_user_id"])

        for guild in guilds:
            guild_id = str(guild["guild_id"])

            try:
                verification = await verify_guild_membership(
                    guild_id,
                    discord_user_id,
                )
            except HTTPException as error:
                # Gangguan verifikasi tidak boleh berubah menjadi akses.
                if error.status_code == 503:
                    continue
                raise

            if not verification.get("is_member"):
                continue

            is_owner = bool(verification.get("is_owner"))
            is_admin = bool(verification.get("is_admin"))

            assigned = guild_permissions.get(guild_id, set())

            # Server Owner / Administrator status is informational only.
            # Access comes exclusively from explicit guild-scoped grants.
            effective = set(assigned)

            result.append({
                "guild_id": guild_id,
                "guild_name": guild["guild_name"],
                "is_owner": is_owner,
                "is_admin": is_admin,
                "is_member": True,
                "has_access": bool(effective),
                "permissions": sorted(effective),
            })

    has_guild_access = any(
        item["has_access"] for item in result
    )

    return {
        "guilds": result,
        "discord_linked": bool(discord_account),
        "global_permissions": sorted(global_permissions),
        "dashboard_access": (
            identity["is_creator"]
            or "dashboard.view" in global_permissions
            or has_guild_access
        ),
    }


@router.get("/auth/me")
async def auth_me(request: Request):
    identity = get_current_identity(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Belum login.")

    if not identity.get("profile_completed"):
        identity["dashboard_access"] = False
        return {"authenticated": True, **identity}

    # Periksa akses guild melalui verifikasi live bot.
    # Jika bot tidak dapat memverifikasi, akses tidak diberikan.
    guild_access = await auth_guilds(request)

    global_dashboard_access = any(
        permission["permission"] == "dashboard.view"
        and permission["scope_type"] == "global"
        and permission["scope_id"] == "*"
        for permission in identity["permissions"]
    )

    identity["dashboard_access"] = bool(
        identity["is_creator"]
        or global_dashboard_access
        or guild_access["dashboard_access"]
    )

    return {
        "authenticated": True,
        **identity,
    }


@router.post("/auth/logout")
async def auth_logout(request: Request):
    origin = request.headers.get("origin")
    if origin != BASE_URL:
        raise HTTPException(status_code=403, detail="Origin tidak diizinkan.")

    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        with database.get_connection() as db:
            now_text = iso_now()
            token_hash = hash_token(raw_token)

            session = db.execute(
                """
                SELECT identity_id
                FROM dashboard_sessions
                WHERE token_hash = ? AND revoked_at IS NULL
                LIMIT 1
                """,
                (token_hash,),
            ).fetchone()

            if session:
                identity_id = session["identity_id"]

                discord = db.execute(
                    """
                    SELECT provider_user_id
                    FROM auth_accounts
                    WHERE identity_id = ? AND provider = 'discord'
                    LIMIT 1
                    """,
                    (identity_id,),
                ).fetchone()

                db.execute(
                    """
                    INSERT INTO dashboard_audit_logs (
                        actor_identity_id, actor_discord_id,
                        action, target_identity_id, details, created_at
                    )
                    VALUES (?, ?, 'dashboard_logout', ?, ?, ?)
                    """,
                    (
                        identity_id,
                        discord["provider_user_id"] if discord else None,
                        identity_id,
                        "session revoked by user",
                        now_text,
                    ),
                )

                db.execute(
                    """
                    UPDATE dashboard_sessions
                    SET revoked_at = ?
                    WHERE token_hash = ? AND revoked_at IS NULL
                    """,
                    (now_text, token_hash),
                )

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


class PasswordLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False


@router.post("/auth/password/login")
async def password_login(request: Request, payload: PasswordLoginRequest):
    require_same_origin(request)
    username = payload.username.strip()
    normalized = username.casefold()
    ip = client_ip(request)
    now = utc_now()
    now_text = now.isoformat()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    with database.get_connection() as db:
        attempt = db.execute(
            """
            SELECT failed_count, window_started_at, locked_until
            FROM auth_login_attempts
            WHERE username_normalized = ? AND ip_address = ?
            """,
            (normalized, ip),
        ).fetchone()

        if attempt and attempt["locked_until"] and attempt["locked_until"] > now_text:
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi 15 menit.")

        credential = db.execute(
            """
            SELECT c.identity_id, c.password_hash, i.disabled_at
            FROM auth_local_credentials c
            JOIN auth_identities i ON i.identity_id = c.identity_id
            WHERE c.username_normalized = ?
            """,
            (normalized,),
        ).fetchone()

    valid = False
    if credential and not credential["disabled_at"]:
        valid = verify_password(payload.password, credential["password_hash"])
    else:
        # Perhitungan dummy mengurangi perbedaan waktu untuk username yang tidak ada.
        verify_password(payload.password, hash_password("dummy-password-value"))

    if not valid:
        with database.get_connection() as db:
            if attempt and attempt["window_started_at"] > (now - timedelta(minutes=15)).isoformat():
                count = int(attempt["failed_count"]) + 1
                window = attempt["window_started_at"]
            else:
                count = 1
                window = now_text

            locked = (now + timedelta(minutes=15)).isoformat() if count >= 10 else None
            db.execute(
                """
                INSERT INTO auth_login_attempts
                    (username_normalized, ip_address, failed_count, window_started_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username_normalized, ip_address) DO UPDATE SET
                    failed_count=excluded.failed_count,
                    window_started_at=excluded.window_started_at,
                    locked_until=excluded.locked_until
                """,
                (normalized, ip, count, window, locked),
            )
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    with database.get_connection() as db:
        db.execute(
            "DELETE FROM auth_login_attempts WHERE username_normalized = ? AND ip_address = ?",
            (normalized, ip),
        )

    old_token = request.cookies.get(SESSION_COOKIE)
    raw_token = create_session(
        credential["identity_id"],
        old_token,
        request.headers.get("user-agent", ""),
        remember_me=payload.remember_me,
        login_method="username_password",
    )
    response = JSONResponse({"authenticated": True})
    set_session_cookie(response, raw_token, payload.remember_me)
    return response


@router.post("/auth/profile/setup")
async def profile_setup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    avatar: UploadFile | None = File(default=None),
):
    require_same_origin(request)
    identity = get_current_identity(request)

    if not identity:
        raise HTTPException(status_code=401, detail="Sesi login tidak ditemukan.")
    if identity.get("profile_completed"):
        raise HTTPException(status_code=409, detail="Profil akun sudah dibuat.")

    username = username.strip()
    normalized = username.casefold()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,23}", username):
        raise HTTPException(status_code=400, detail="Username harus 3–24 karakter: huruf, angka, titik, garis bawah, atau strip.")
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(status_code=400, detail="Password harus 12–128 karakter.")

    avatar_url = None
    saved_path = None

    if avatar and avatar.filename:
        data = await avatar.read(1024 * 1024 + 1)
        await avatar.close()

        if len(data) > 1024 * 1024:
            raise HTTPException(status_code=413, detail="Foto profil maksimal 1 MB.")

        mime = avatar.content_type or ""
        if data.startswith(b"\x89PNG\r\n\x1a\n") and mime == "image/png":
            extension = "png"
        elif data.startswith(b"\xff\xd8\xff") and mime == "image/jpeg":
            extension = "jpg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and mime == "image/webp":
            extension = "webp"
        else:
            raise HTTPException(status_code=400, detail="Format foto harus PNG, JPG, atau WebP.")

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.{extension}"
        saved_path = AVATAR_DIR / filename
        saved_path.write_bytes(data)
        avatar_url = f"/profile-avatars/{filename}"

    now = iso_now()
    password_hash = hash_password(password)

    try:
        with database.get_connection() as db:
            existing = db.execute(
                "SELECT identity_id FROM auth_local_credentials WHERE username_normalized = ?",
                (normalized,),
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Username sudah digunakan.")

            db.execute(
                """
                INSERT INTO auth_local_credentials
                    (identity_id, username, username_normalized, password_hash,
                     avatar_url, profile_completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity["identity_id"], username, normalized, password_hash,
                    avatar_url, now, now, now,
                ),
            )
            db.execute(
                "UPDATE auth_identities SET display_name = ?, updated_at = ? WHERE identity_id = ?",
                (username, now, identity["identity_id"]),
            )
            discord = db.execute(
                "SELECT provider_user_id FROM auth_accounts WHERE identity_id = ? AND provider = 'discord'",
                (identity["identity_id"],),
            ).fetchone()
            db.execute(
                """
                INSERT INTO dashboard_audit_logs
                    (actor_identity_id, actor_discord_id, action, target_identity_id, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    identity["identity_id"],
                    discord["provider_user_id"] if discord else None,
                    "profile_created",
                    identity["identity_id"],
                    "Local username and password configured",
                    now,
                ),
            )
    except sqlite3.IntegrityError:
        if saved_path and saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=409, detail="Username sudah digunakan.")

    return {"success": True, "profile_completed": True}


class PermissionGrantRequest(BaseModel):
    identity_id: str = Field(min_length=1, max_length=64)
    permission: str = Field(min_length=1, max_length=100)
    scope_type: str = Field(min_length=1, max_length=20)
    scope_id: str = Field(min_length=1, max_length=128)


class PermissionRevokeRequest(BaseModel):
    identity_id: str = Field(min_length=1, max_length=64)
    permission: str = Field(min_length=1, max_length=100)
    scope_type: str = Field(min_length=1, max_length=20)
    scope_id: str = Field(min_length=1, max_length=128)



def require_same_origin(request):
    origin = request.headers.get("origin")
    if origin != BASE_URL:
        raise HTTPException(status_code=403, detail="Origin tidak diizinkan.")


def _permission_has(identity, permission, scope_type, scope_id):
    if identity.get("is_creator"):
        return True

    grants = identity.get("permissions", [])
    candidates = {permission}

    # Manage implies view, but never the reverse.
    view_implications = {
        "memory.personal.view": "memory.personal.manage",
        "memory.guild.view": "memory.guild.manage",
        "ai_config.view": "ai_config.manage",
        "server.view": "server.manage",
        "knowledge_base.view": "knowledge_base.manage",
        "automation.view": "automation.manage",
    }
    if permission in view_implications:
        candidates.add(view_implications[permission])

    return any(
        item.get("permission") in candidates
        and item.get("scope_type") == scope_type
        and item.get("scope_id") == scope_id
        for item in grants
    )


def _admin_actor(request):
    identity = get_current_identity(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Belum login.")
    if not identity.get("profile_completed"):
        raise HTTPException(status_code=403, detail="Profil belum diselesaikan.")
    if not identity.get("is_creator") and not any(
        item.get("permission") == "permissions.delegate"
        for item in identity.get("permissions", [])
    ):
        raise HTTPException(
            status_code=403,
            detail="Tidak memiliki izin untuk mengelola otorisasi.",
        )
    return identity


def _actor_discord_id(db, identity_id):
    row = db.execute(
        """
        SELECT provider_user_id
        FROM auth_accounts
        WHERE identity_id = ? AND provider = 'discord'
        LIMIT 1
        """,
        (identity_id,),
    ).fetchone()
    return str(row["provider_user_id"]) if row else None


def _is_creator_identity(db, identity_id):
    row = db.execute(
        """
        SELECT 1
        FROM auth_accounts
        WHERE identity_id = ?
          AND provider = 'discord'
          AND provider_user_id = ?
        LIMIT 1
        """,
        (identity_id, CREATOR_DISCORD_ID),
    ).fetchone()
    return bool(row)


def _validate_admin_scope(scope_type, scope_id):
    if scope_type not in ("global", "guild"):
        raise HTTPException(status_code=400, detail="Scope harus global atau guild.")

    if scope_type == "global" and scope_id != "*":
        raise HTTPException(
            status_code=400,
            detail="Global scope harus menggunakan scope_id '*'.",
        )

    if scope_type == "guild" and (
        scope_id == "*" or not str(scope_id).isdigit()
    ):
        raise HTTPException(
            status_code=400,
            detail="Guild scope memerlukan Discord Guild ID yang valid.",
        )


def _require_scope_delegation(actor, permission, scope_type, scope_id):
    if actor.get("is_creator"):
        return

    # Delegation and the permission being changed must both be held
    # in precisely the same scope.
    if not _permission_has(
        actor, "permissions.delegate", scope_type, scope_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Tidak memiliki izin delegasi pada scope ini.",
        )

    if not _permission_has(actor, permission, scope_type, scope_id):
        raise HTTPException(
            status_code=403,
            detail="Tidak dapat memberikan atau mencabut permission yang tidak dimiliki pada scope ini.",
        )


@router.get("/auth/admin/identities")
async def admin_list_identities(request: Request):
    actor = _admin_actor(request)

    if actor.get("is_creator"):
        managed_scopes = None
    else:
        managed_scopes = {
            (item["scope_type"], item["scope_id"])
            for item in actor.get("permissions", [])
            if item.get("permission") == "permissions.delegate"
        }

    with database.get_connection() as db:
        identities = db.execute(
            """
            SELECT identity_id, display_name, email, created_at
            FROM auth_identities
            WHERE disabled_at IS NULL
            ORDER BY created_at DESC
            LIMIT 200
            """
        ).fetchall()

        result = []
        for item in identities:
            target_id = item["identity_id"]
            accounts = db.execute(
                """
                SELECT provider, email, email_verified, display_name,
                       provider_user_id
                FROM auth_accounts
                WHERE identity_id = ?
                ORDER BY provider
                """,
                (target_id,),
            ).fetchall()

            is_creator_target = any(
                account["provider"] == "discord"
                and str(account["provider_user_id"]) == CREATOR_DISCORD_ID
                for account in accounts
            )

            permissions = db.execute(
                """
                SELECT permission, scope_type, scope_id
                FROM dashboard_permissions
                WHERE identity_id = ? AND revoked_at IS NULL
                ORDER BY permission
                """,
                (target_id,),
            ).fetchall()

            visible_permissions = [
                {
                    "permission": grant["permission"],
                    "scope_type": grant["scope_type"],
                    "scope_id": grant["scope_id"],
                }
                for grant in permissions
                if managed_scopes is None
                or (grant["scope_type"], grant["scope_id"]) in managed_scopes
            ]

            result.append({
                "identity_id": target_id,
                "display_name": item["display_name"],
                "email": item["email"] if actor.get("is_creator") else None,
                "created_at": item["created_at"],
                "is_creator": is_creator_target,
                "accounts": [
                    {
                        "provider": account["provider"],
                        "email": (
                            account["email"]
                            if actor.get("is_creator") else None
                        ),
                        "email_verified": bool(account["email_verified"]),
                        "display_name": account["display_name"],
                    }
                    for account in accounts
                ],
                "permissions": visible_permissions,
            })

        if actor.get("is_creator"):
            guild_rows = db.execute(
                """
                SELECT guild_id, guild_name
                FROM bot_guild_presence
                WHERE is_present = 1
                ORDER BY guild_name COLLATE NOCASE
                """
            ).fetchall()
            scopes = [{"scope_type": "global", "scope_id": "*", "label": "Global"}]
            scopes.extend({
                "scope_type": "guild",
                "scope_id": str(row["guild_id"]),
                "label": row["guild_name"] or str(row["guild_id"]),
            } for row in guild_rows)
        else:
            scopes = []
            for scope_type, scope_id in sorted(managed_scopes):
                if scope_type == "global":
                    label = "Global"
                else:
                    guild_row = db.execute(
                        """
                        SELECT guild_name
                        FROM bot_guild_presence
                        WHERE guild_id = ?
                        """,
                        (scope_id,),
                    ).fetchone()
                    label = (
                        guild_row["guild_name"]
                        if guild_row and guild_row["guild_name"]
                        else scope_id
                    )
                scopes.append({
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "label": label,
                })

    return {
        "identities": result,
        "managed_scopes": scopes,
        "permissions_catalog": sorted(ALLOWED_DASHBOARD_PERMISSIONS),
        "is_creator": bool(actor.get("is_creator")),
    }


@router.post("/auth/admin/permissions/grant")
async def admin_grant_permission(
    request: Request,
    payload: PermissionGrantRequest,
):
    require_same_origin(request)
    actor = _admin_actor(request)

    if payload.permission not in ALLOWED_DASHBOARD_PERMISSIONS:
        raise HTTPException(
            status_code=400,
            detail="Permission tidak termasuk daftar yang diizinkan.",
        )

    _validate_admin_scope(payload.scope_type, payload.scope_id)
    _require_scope_delegation(
        actor, payload.permission, payload.scope_type, payload.scope_id
    )

    if payload.identity_id == actor["identity_id"]:
        raise HTTPException(
            status_code=403,
            detail="Tidak dapat mengubah permission milik sendiri.",
        )

    now = iso_now()

    with database.get_connection() as db:
        target = db.execute(
            """
            SELECT identity_id
            FROM auth_identities
            WHERE identity_id = ? AND disabled_at IS NULL
            """,
            (payload.identity_id,),
        ).fetchone()

        if not target:
            raise HTTPException(
                status_code=404,
                detail="Identitas target tidak ditemukan atau dinonaktifkan.",
            )

        if _is_creator_identity(db, payload.identity_id):
            raise HTTPException(
                status_code=403,
                detail="Akses Bos Bara tidak dapat diubah.",
            )

        if payload.scope_type == "guild":
            known_guild = db.execute(
                """
                SELECT guild_id
                FROM bot_guild_presence
                WHERE guild_id = ? AND is_present = 1
                """,
                (payload.scope_id,),
            ).fetchone()
            if not known_guild:
                raise HTTPException(
                    status_code=404,
                    detail="Server tidak ditemukan atau bot tidak berada di server tersebut.",
                )

        existing = db.execute(
            """
            SELECT id
            FROM dashboard_permissions
            WHERE identity_id = ?
              AND permission = ?
              AND scope_type = ?
              AND scope_id = ?
              AND revoked_at IS NULL
            LIMIT 1
            """,
            (
                payload.identity_id,
                payload.permission,
                payload.scope_type,
                payload.scope_id,
            ),
        ).fetchone()

        if existing:
            return {"success": True, "status": "already_granted"}

        actor_discord_id = _actor_discord_id(db, actor["identity_id"])

        db.execute(
            """
            INSERT INTO dashboard_permissions (
                identity_id, permission, scope_type, scope_id,
                granted_by_discord_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.identity_id,
                payload.permission,
                payload.scope_type,
                payload.scope_id,
                actor_discord_id,
                now,
            ),
        )

        db.execute(
            """
            INSERT INTO dashboard_audit_logs (
                actor_identity_id, actor_discord_id,
                action, target_identity_id, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor["identity_id"],
                actor_discord_id,
                "dashboard_permission_granted",
                payload.identity_id,
                f"{payload.permission}|{payload.scope_type}|{payload.scope_id}",
                now,
            ),
        )

    return {"success": True, "status": "granted"}


@router.post("/auth/admin/permissions/revoke")
async def admin_revoke_permission(
    request: Request,
    payload: PermissionRevokeRequest,
):
    require_same_origin(request)
    actor = _admin_actor(request)

    if payload.permission not in ALLOWED_DASHBOARD_PERMISSIONS:
        raise HTTPException(
            status_code=400,
            detail="Permission tidak termasuk daftar yang diizinkan.",
        )

    _validate_admin_scope(payload.scope_type, payload.scope_id)
    _require_scope_delegation(
        actor, payload.permission, payload.scope_type, payload.scope_id
    )

    if payload.identity_id == actor["identity_id"]:
        raise HTTPException(
            status_code=403,
            detail="Tidak dapat mengubah permission milik sendiri.",
        )

    now = iso_now()

    with database.get_connection() as db:
        target = db.execute(
            """
            SELECT identity_id
            FROM auth_identities
            WHERE identity_id = ?
            """,
            (payload.identity_id,),
        ).fetchone()

        if not target:
            raise HTTPException(
                status_code=404,
                detail="Identitas target tidak ditemukan.",
            )

        if _is_creator_identity(db, payload.identity_id):
            raise HTTPException(
                status_code=403,
                detail="Akses Bos Bara tidak dapat diubah.",
            )

        actor_discord_id = _actor_discord_id(db, actor["identity_id"])

        cursor = db.execute(
            """
            UPDATE dashboard_permissions
            SET revoked_at = ?
            WHERE identity_id = ?
              AND permission = ?
              AND scope_type = ?
              AND scope_id = ?
              AND revoked_at IS NULL
            """,
            (
                now,
                payload.identity_id,
                payload.permission,
                payload.scope_type,
                payload.scope_id,
            ),
        )

        revoked_count = cursor.rowcount

        if revoked_count:
            db.execute(
                """
                INSERT INTO dashboard_audit_logs (
                    actor_identity_id, actor_discord_id,
                    action, target_identity_id, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    actor["identity_id"],
                    actor_discord_id,
                    "dashboard_permission_revoked",
                    payload.identity_id,
                    f"{payload.permission}|{payload.scope_type}|{payload.scope_id}",
                    now,
                ),
            )

    return {
        "success": True,
        "status": "revoked" if revoked_count else "not_found",
        "revoked_count": revoked_count,
    }
