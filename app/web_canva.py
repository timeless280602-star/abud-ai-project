"""Per-account Canva Connect authorization and design creation."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app import auth, database
from app.web_chat import identity

PATH = "/web/chat/integrations/canva"
API = "https://api.canva.com/rest/v1"
router = APIRouter(prefix=PATH)


def _credentials():
    return os.getenv("CANVA_CLIENT_ID", ""), os.getenv("CANVA_CLIENT_SECRET", "")


def _configured():
    credentials = _credentials()
    if not all(credentials):
        raise HTTPException(503, "Integrasi Canva belum dikonfigurasi.")
    return credentials


def _cipher(owner):
    key = hmac.digest(
        os.environ["ABUD_SESSION_SECRET"].encode(),
        f"abud:canva:token:v1:{owner}".encode(),
        "sha256",
    )
    return Fernet(base64.urlsafe_b64encode(key))


def _redirect_uri():
    return auth.BASE_URL.rstrip("/") + PATH + "/callback"


def _saved_token(owner):
    with database.get_connection() as db:
        row = db.execute(
            "SELECT token FROM canva_connections WHERE identity_id=?", (owner,)
        ).fetchone()
    if not row:
        return None, None
    value = row["token"]
    try:
        return value, json.loads(_cipher(owner).decrypt(value))
    except InvalidToken:
        return value, None


def _exchange(**form):
    try:
        response = httpx.post(
            API + "/oauth/token", auth=_configured(), data=form, timeout=10
        )
        if response.status_code in {400, 401, 403}:
            raise HTTPException(409, "Otorisasi Canva gagal. Hubungkan kembali akun Canva.")
        response.raise_for_status()
        data = response.json()
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        expires_in = int(data["expires_in"])
        if not isinstance(access_token, str) or not access_token or not isinstance(refresh_token, str) or not refresh_token or expires_in <= 0:
            raise ValueError("Invalid Canva token")
        return {
            "access": access_token,
            "refresh": refresh_token,
            "expires": time.time() + expires_in,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "Canva sedang tidak dapat dihubungi.") from None


@router.get("")
def status(request: Request):
    owner = identity(request)
    _, token = _saved_token(owner)
    return {"available": all(_credentials()), "connected": token is not None}


@router.post("/connect")
def connect(request: Request):
    owner = identity(request)
    client_id, _ = _configured()
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    request.session["canva_connect"] = {
        "owner": owner, "state": state, "verifier": verifier, "expires": time.time() + 600,
    }
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = urlencode({
        "client_id": client_id, "response_type": "code", "scope": "design:content:write",
        "state": state, "code_challenge": challenge.decode().rstrip("="),
        "code_challenge_method": "s256", "redirect_uri": _redirect_uri(),
    })
    return {"url": "https://www.canva.com/api/oauth/authorize?" + query}


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = ""):
    owner = identity(request)
    pending = request.session.pop("canva_connect", {})
    valid = (
        pending.get("owner") == owner and pending.get("expires", 0) > time.time()
        and hmac.compare_digest(pending.get("state", "").encode(), state.encode())
    )
    if not valid or not code:
        return RedirectResponse("/?canva=failed", status_code=303)
    try:
        token = _exchange(
            grant_type="authorization_code", code=code,
            code_verifier=pending["verifier"], redirect_uri=_redirect_uri(),
        )
    except HTTPException:
        return RedirectResponse("/?canva=failed", status_code=303)
    encrypted = _cipher(owner).encrypt(json.dumps(token).encode())
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO canva_connections(identity_id,token) VALUES (?,?) "
            "ON CONFLICT(identity_id) DO UPDATE SET token=excluded.token",
            (owner, encrypted),
        )
    return RedirectResponse("/?canva=connected", status_code=303)


@router.delete("")
def disconnect(request: Request):
    owner = identity(request)
    request.session.pop("canva_connect", None)
    previous, token = _saved_token(owner)
    if token and all(_credentials()):
        try:
            response = httpx.post(
                API + "/oauth/revoke", auth=_configured(),
                data={"token": token["refresh"]}, timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, "Canva belum bisa mencabut akses. Coba lagi.") from None
    with database.get_connection() as db:
        db.execute("DELETE FROM canva_connections WHERE identity_id=? AND token=?", (owner, previous))
    return {"connected": False}


class Design(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)


@router.post("/designs")
def create_design(request: Request, design: Design):
    owner = identity(request)
    _configured()
    previous, token = _saved_token(owner)
    if not token:
        raise HTTPException(409, "Hubungkan akun Canva terlebih dahulu.")
    if token["expires"] <= time.time() + 60:
        token = _exchange(grant_type="refresh_token", refresh_token=token["refresh"])
        encrypted = _cipher(owner).encrypt(json.dumps(token).encode())
        with database.get_connection() as db:
            result = db.execute(
                "UPDATE canva_connections SET token=? WHERE identity_id=? AND token=?",
                (encrypted, owner, previous),
            )
            if result.rowcount != 1:
                raise HTTPException(409, "Koneksi Canva berubah. Coba lagi.")
    try:
        response = httpx.post(
            API + "/designs", headers={"Authorization": "Bearer " + token["access"]},
            json={
                "type": "type_and_asset",
                "design_type": {"type": "custom", "width": 1080, "height": 1080},
                "title": design.title,
            },
            timeout=10,
        )
        if response.status_code in {401, 403}:
            raise HTTPException(409, "Akses desain Canva ditolak. Hubungkan kembali akun Canva.")
        response.raise_for_status()
        url = response.json()["design"]["urls"]["edit_url"]
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != "www.canva.com":
            raise ValueError("Unexpected Canva URL")
        return {"url": url}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "Canva tidak dapat membuat desain saat ini.") from None
