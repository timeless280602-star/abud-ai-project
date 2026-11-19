"""Browser-facing Discord bot settings, isolated from existing dashboard grants."""
import os
import re
import json
import logging
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.discord_invite import invite_url
from app import auth, database

router = APIRouter()
log = logging.getLogger(__name__)

def identify(request):
    identity = auth.get_current_identity(request)
    if not identity:
        raise HTTPException(401, "Silakan login terlebih dahulu.")
    if not identity.get("profile_completed"):
        raise HTTPException(403, "Selesaikan profil terlebih dahulu.")
    with database.get_connection() as db:
        account = db.execute("SELECT provider_user_id FROM auth_accounts WHERE identity_id=? AND provider='discord' LIMIT 1",
                             (identity["identity_id"],)).fetchone()
    if not account:
        raise HTTPException(403, "Hubungkan akun Discord terlebih dahulu.")
    return identity, str(account["provider_user_id"])

@router.get("/discord/invite")
async def invite():
    """Public invite. Resolve the running bot application, not the OAuth login app."""
    verify_url = os.getenv("ABUD_BOT_VERIFY_URL", "")
    key = os.getenv("ABUD_INTERNAL_API_KEY", "")
    suffix = "/internal/verify/guild-member"
    if not verify_url.endswith(suffix) or not key:
        raise HTTPException(503, "Undangan ABUD sementara tidak tersedia.")
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(verify_url[:-len(suffix)] + "/internal/dashboard/discord/install",
                                        headers={"Authorization": "Bearer " + key})
            response.raise_for_status()
            url = invite_url(response.json()["application_id"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Undangan ABUD sementara tidak tersedia. Coba lagi dari website.") from None
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})

@router.get("/dashboard/discord/servers")
async def servers(request: Request):
    identify(request)
    result = await auth.auth_guilds(request)
    return {"servers": [{"id": g["guild_id"], "name": g["guild_name"]}
                        for g in result["guilds"] if g["is_member"] and (g["is_owner"] or g["is_admin"])]}

@router.post("/dashboard/discord/action")
async def action(request: Request):
    if request.headers.get("origin") != auth.BASE_URL:
        raise HTTPException(403, "Origin tidak diizinkan.")
    identity, actor = identify(request)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Gunakan JSON.")
    # Bound streamed body even if Content-Length is absent.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 12000:
            raise HTTPException(413, "Permintaan terlalu besar.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Permintaan tidak valid.") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Permintaan tidak valid.")
    guild = data.get("guild_id")
    op = data.get("action")
    args = data.get("data", {})
    if not isinstance(guild, str) or not re.fullmatch(r"[0-9]{1,20}", guild) or not isinstance(op, str) or not isinstance(args, dict):
        raise HTTPException(400, "Permintaan tidak valid.")
    allowed = {"read", "leveling.save", "leveling.exclude", "welcome.save", "welcome.test",
               "reaction.create", "reaction.bind", "reaction.unbind", "reaction.publish", "reaction.disable", "reaction.delete",
               "ticket.save", "ticket.publish", "notify.add", "notify.edit", "notify.remove", "notify.test"}
    if op not in allowed:
        raise HTTPException(400, "Aksi tidak tersedia.")
    verify_url = os.getenv("ABUD_BOT_VERIFY_URL", "")
    key = os.getenv("ABUD_INTERNAL_API_KEY", "")
    suffix = "/internal/verify/guild-member"
    if not verify_url.endswith(suffix) or not key:
        raise HTTPException(503, "Gateway bot belum dikonfigurasi.")
    try:
        async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
            resp = await client.post(verify_url[:-len(suffix)] + "/internal/dashboard/discord",
                json={"guild_id": guild, "user_id": actor, "action": op, "data": args},
                headers={"Authorization": "Bearer " + key})
        result = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Gateway bot tidak tersedia. Muat ulang sebelum mengulangi aksi.") from None
    if resp.status_code != 200:
        raise HTTPException(resp.status_code if resp.status_code in (400,403,503) else 503,
                            result.get("detail", "Operasi gagal.") if isinstance(result,dict) else "Operasi gagal.")
    if op != "read":
        try:
            with database.get_connection() as db:
                db.execute("INSERT INTO dashboard_audit_logs (actor_identity_id,actor_discord_id,action,target_identity_id,details,created_at) VALUES (?,?,?,NULL,?,?)",
                           (identity["identity_id"], actor, "discord." + op, json.dumps({"guild_id":guild}), datetime.now(timezone.utc).isoformat()))
        except Exception:
            log.exception("Discord dashboard audit insert failed")
    return result
