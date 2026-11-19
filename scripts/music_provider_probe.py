"""Read-only Lavalink source smoke probe. Never logs provider URLs or credentials."""
import asyncio
import os
import aiohttp

async def main():
    password = os.environ["STAGING_PASSWORD"]
    url = "http://music-provider-staging:2333"
    headers = {"Authorization": password}
    async with aiohttp.ClientSession(
        headers=headers, timeout=aiohttp.ClientTimeout(total=35)
    ) as session:
        for attempt in range(60):
            try:
                async with session.get(url + "/v4/info", timeout=3) as res:
                    res.raise_for_status()
                    info = await res.json()
                    print("Lavalink:", info["version"]["semver"], flush=True)
                    print("Sources:", info["sourceManagers"], flush=True)
                    break
            except (aiohttp.ClientError, TimeoutError):
                await asyncio.sleep(2)
        else:
            raise RuntimeError("Staging REST did not become ready")
        queries = [
            ("local-generated-wav", "/diagnostic/tone.wav"),
            ("youtube-search", "ytsearch:Separuh Aku NOAH"),
            ("soundcloud-search", "scsearch:Separuh Aku NOAH"),
        ]
        bandcamp = os.getenv("BANDCAMP_TEST_URL", "")
        if bandcamp:
            from app.music_session import music_query
            from urllib.parse import urlsplit
            music_query(bandcamp)
            if not urlsplit(bandcamp).hostname.endswith(".bandcamp.com"):
                raise ValueError("Expected artist Bandcamp URL")
            queries.append(("bandcamp", bandcamp))
        for label, query in queries:
            try:
                async with session.get(url + "/v4/loadtracks", params={"identifier": query}) as res:
                    res.raise_for_status()
                    result = await res.json()
                kind = result.get("loadType", "unknown")
                data = result.get("data")
                count = len(data) if kind == "search" else (
                    len(data.get("tracks", [])) if kind == "playlist" else
                    int(kind == "track")
                )
                print(f"{label}: {kind}, tracks={count}", flush=True)
                if label == "local-generated-wav" and kind != "track":
                    raise RuntimeError("Local test fixture failed to load")
            except (aiohttp.ClientError, TimeoutError) as error:
                print(f"{label}: {type(error).__name__}", flush=True)
                if label == "local-generated-wav":
                    raise
        print("SOURCE PROBE COMPLETE (metadata only, not Discord playback)", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
