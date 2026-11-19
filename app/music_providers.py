"""Opt-in catalog routing and conservative recording identity."""
import re
import unicodedata
from urllib.parse import urlsplit

NAMES = {"deezer": "Deezer", "spotify": "Spotify", "applemusic": "Apple Music",
         "tidal": "Tidal", "soundcloud": "SoundCloud", "youtube": "YouTube",
         "bandcamp": "Bandcamp"}
PREFIXES = {"deezer": "dzsearch:", "spotify": "spsearch:", "applemusic": "amsearch:",
            "tidal": "tdsearch:", "soundcloud": "scsearch:", "youtube": "ytsearch:"}
LEGACY = ("soundcloud", "youtube", "bandcamp")
DIRECT = frozenset(("deezer", "soundcloud", "youtube", "bandcamp"))


def provider_order(value):
    items = tuple(dict.fromkeys(x.strip().lower() for x in value.split(",") if x.strip()))
    if not items or any(x not in NAMES for x in items):
        raise ValueError("Invalid ABUD_MUSIC_PROVIDERS")
    return items


def source_for_link(query):
    p = urlsplit(query)
    host = p.hostname or ""
    if host in ("youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be"):
        return "youtube"
    if host in ("soundcloud.com", "www.soundcloud.com", "on.soundcloud.com"):
        return "soundcloud"
    if host == "bandcamp.com" or host.endswith(".bandcamp.com"):
        return "bandcamp"
    if host in ("deezer.com", "www.deezer.com") and re.fullmatch(
        r"/(?:[a-z]{2}/)?(?:track|album|playlist)/[0-9]+/?", p.path
    ):
        return "deezer"
    if host == "open.spotify.com" and re.fullmatch(
        r"/(?:track|album|playlist)/[A-Za-z0-9]{22}/?", p.path
    ):
        return "spotify"
    if host == "music.apple.com" and re.fullmatch(
        r"/[a-z]{2}/(?:album|song|playlist)/[A-Za-z0-9._%~-]+/[A-Za-z0-9.-]+/?", p.path
    ):
        return "applemusic"
    if host in ("tidal.com", "www.tidal.com") and re.fullmatch(
        r"/(?:browse/)?(?:track|album|playlist)/[A-Za-z0-9-]+/?", p.path
    ):
        return "tidal"
    return None


def normalized(text):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text or "").casefold()))


def same_recording(original, candidate):
    if original.is_stream or candidate.is_stream:
        return False
    if not original.length or not candidate.length or abs(original.length - candidate.length) > 3000:
        return False
    first, second = getattr(original, "isrc", None), getattr(candidate, "isrc", None)
    if first and second:
        return first.upper() == second.upper()
    title, artist = normalized(original.title), normalized(original.author)
    return bool(title and artist and title == normalized(candidate.title)
                and artist == normalized(candidate.author))
