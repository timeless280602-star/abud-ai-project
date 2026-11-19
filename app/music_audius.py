"""Public Audius catalog adapter; no arbitrary URLs, credentials or downloads.

This is a staging foundation. The returned stream URL is NOT a certificate of
licensing or successful Lavalink playback. Do not expose it as user input.
"""
import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

BASE = "https://api.audius.co/v1"
_ID = re.compile(r"[A-Za-z0-9]{1,32}", re.ASCII)


class AudiusError(Exception):
    """Safe, fixed-text errors at the provider boundary."""


def checked_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AudiusError("Audius track ID tidak valid.")
    return value


@dataclass(frozen=True)
class AudiusTrack:
    id: str
    title: str
    artist: str
    duration: int
    isrc: str | None
    license: str | None

    @property
    def stream_url(self):
        return BASE + "/tracks/" + checked_id(self.id) + "/stream"


def public_track(data):
    if not isinstance(data, dict):
        raise AudiusError("Metadata Audius tidak valid.")
    if (
        data.get("is_available") is not True
        or data.get("is_stream_gated") is not False
        or data.get("is_unlisted") is not False
        or data.get("is_delete") is not False
        or data.get("stream_conditions")
        or data.get("allowed_api_keys")
        or data.get("access_authorities")
    ):
        raise AudiusError("Akses audio Audius tidak terkonfirmasi.")
    user = data.get("user")
    title, artist, duration = data.get("title"), (
        user.get("name") if isinstance(user, dict) else None
    ), data.get("duration")
    if (not isinstance(title, str) or not title.strip()
            or not isinstance(artist, str) or not artist.strip()
            or type(duration) is not int or not 0 < duration <= 7200):
        raise AudiusError("Metadata Audius tidak valid.")
    return AudiusTrack(checked_id(data.get("id")), title[:256], artist[:256],
                       duration, data.get("isrc"), data.get("license"))


class AudiusCatalog:
    def __init__(self, *, request=None):
        self.request = request or self._curl
        self.slots = asyncio.Semaphore(2)

    async def _curl(self, endpoint):
        # wait_for works in both the VPS Python 3.10 and the bot Python 3.11.
        try:
            return await asyncio.wait_for(self._curl_request(endpoint), timeout=15)
        except (OSError, asyncio.TimeoutError, ValueError):
            raise AudiusError("API Audius tidak tersedia.") from None

    async def _curl_request(self, endpoint):
        # Fixed origin, no curl config files, no metadata redirects, no shell.
        async with self.slots:
            proc = await asyncio.create_subprocess_exec(
                "curl", "--disable", "--fail", "--silent", "--show-error",
                "--proto", "=https", "--max-time", "10", "--max-filesize",
                "2097152", "-H", "Accept: application/json", BASE + endpoint,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                raw, _ = await proc.communicate()
            finally:
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
            if proc.returncode or len(raw) > 2097152:
                raise AudiusError("API Audius tidak tersedia.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise AudiusError("Respons Audius tidak valid.")
            return data

    async def track(self, track_id):
        track_id = checked_id(track_id)
        result = public_track((await self.request("/tracks/" + track_id)).get("data"))
        if result.id != track_id:
            raise AudiusError("ID track Audius tidak cocok.")
        return result

    async def search(self, query):
        query = query.strip()
        if not query or len(query) > 300 or any(ord(c) < 32 for c in query):
            raise AudiusError("Judul pencarian Audius tidak valid.")
        params = urlencode({"query": query, "limit": 5})
        data = (await self.request("/tracks/search?" + params)).get("data")
        if not isinstance(data, list):
            raise AudiusError("Respons Audius tidak valid.")
        ids = []
        # Search results are not access grants; only return IDs to be rechecked.
        for item in data[:5]:
            if isinstance(item, dict):
                try:
                    identifier = checked_id(item.get("id"))
                except AudiusError:
                    continue
                if identifier not in ids:
                    ids.append(identifier)
        return ids
