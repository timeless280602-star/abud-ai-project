"""Opt-in catalog routing and conservative recording identity."""
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

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


YOUTUBE_HOSTS = frozenset(("youtube.com", "www.youtube.com", "m.youtube.com",
                           "music.youtube.com", "youtu.be"))


def youtube_target(query):
    """Return a canonical video/playlist URL and a video ID, if applicable."""
    p = urlsplit(query)
    if (p.scheme != "https" or p.hostname not in YOUTUBE_HOSTS
            or p.username is not None or p.password is not None or p.port not in (None, 443)):
        raise ValueError("Invalid YouTube URL")
    params = parse_qs(p.query, keep_blank_values=True, max_num_fields=30)
    path = p.path.rstrip("/")
    video = None
    if p.hostname == "youtu.be":
        video = path.removeprefix("/")
    elif path == "/watch" and len(params.get("v", [])) == 1:
        video = params["v"][0]
    elif re.fullmatch(r"/(?:shorts|live|embed)/[A-Za-z0-9_-]{11}", path):
        video = path.rsplit("/", 1)[1]
    elif path == "/playlist" and len(params.get("list", [])) == 1:
        playlist = params["list"][0]
        if re.fullmatch(r"[A-Za-z0-9_-]{2,100}", playlist):
            return "https://www.youtube.com/playlist?list=" + playlist, None
    if video and re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        # A shared watch URL always means the selected video, not its mix/playlist.
        return "https://www.youtube.com/watch?v=" + video, video
    raise ValueError("Invalid YouTube video or playlist ID")


def source_for_link(query):
    p = urlsplit(query)
    host = p.hostname or ""
    if host in YOUTUBE_HOSTS:
        try:
            youtube_target(query)
        except ValueError:
            return None
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
