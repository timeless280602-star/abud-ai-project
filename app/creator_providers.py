"""Official YouTube Data API adapter; all outbound URLs are fixed."""

import time
from datetime import datetime

import aiohttp

from app.creator_notifications import Creator, Event, NotificationError, parse_account


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


class YouTube:
    def __init__(self, http, key, store):
        self.http, self.key, self.store = http, key, store
        self.blocked_until = 0

    async def request(self, resource, **params):
        if not self.key:
            raise NotificationError(
                "YOUTUBE_API_KEY belum dikonfigurasi oleh pengelola bot."
            )
        if time.time() < self.blocked_until:
            raise NotificationError(
                "YouTube sedang membatasi API. Pemantauan akan mencoba lagi otomatis."
            )
        async with self.http.get(
            "https://www.googleapis.com/youtube/v3/" + resource,
            params={**params, "key": self.key},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                if response.status in (403, 429):
                    self.blocked_until = time.time() + 3600
                raise NotificationError(
                    f"YouTube API gagal (HTTP {response.status}). Periksa API key/kuota."
                )
            raw = await response.content.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise NotificationError("Respons YouTube terlalu besar.")
            import json

            return json.loads(raw)

    async def resolve(self, value):
        field, account = parse_account("youtube", value)
        data = await self.request(
            "channels", part="snippet,contentDetails", **{field: account}
        )
        items = data.get("items", [])
        if not items:
            raise NotificationError("Channel YouTube tidak ditemukan.")
        item = items[0]
        return Creator(
            "youtube",
            item["id"],
            item["snippet"]["title"],
            item["contentDetails"]["relatedPlaylists"]["uploads"],
        )

    async def poll(self, creator):
        # No search.list: uploads discovery plus batched video status is cheaper.
        data = await self.request(
            "playlistItems",
            part="contentDetails",
            playlistId=creator.uploads,
            maxResults=50,
        )
        ids = {x["contentDetails"]["videoId"] for x in data.get("items", [])}
        ids.update(self.store.pending(creator.account))
        events = []
        ids = sorted(ids)
        for start in range(0, len(ids), 50):
            data = await self.request(
                "videos",
                part="snippet,liveStreamingDetails",
                id=",".join(ids[start : start + 50]),
            )
            for item in data.get("items", []):
                snippet = item["snippet"]
                if snippet["channelId"] != creator.account:
                    continue
                live = item.get("liveStreamingDetails", {})
                state = snippet.get("liveBroadcastContent", "none")
                video, title = item["id"], snippet["title"]
                if state == "upcoming" or (
                    live.get("actualStartTime") and not live.get("actualEndTime")
                ):
                    # Retain scheduled/live IDs even after they leave the uploads window.
                    self.store.watch(creator.account, video, time.time() + 90 * 86400)
                else:
                    self.store.unwatch(creator.account, video)
                if (
                    state == "live"
                    and live.get("actualStartTime")
                    and not live.get("actualEndTime")
                ):
                    events.append(
                        Event(
                            "youtube",
                            creator.account,
                            video,
                            "live",
                            title,
                            timestamp(live["actualStartTime"]),
                        )
                    )
                elif not live and state == "none":
                    events.append(
                        Event(
                            "youtube",
                            creator.account,
                            video,
                            "post",
                            title,
                            timestamp(snippet["publishedAt"]),
                        )
                    )
        return sorted(events, key=lambda event: event.occurred)


def session():
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25, connect=5), trust_env=False
    )
