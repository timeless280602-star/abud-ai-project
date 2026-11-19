"""Explicit music requests in Abud chat, using the same player as slash commands."""

import re
from dataclasses import dataclass

import discord

from app.music_session import MusicChoiceRequired, MusicError
from app.music_commands import SongSelection

# Anchored imperative grammar: ordinary chat, quoted instructions and explanations
# are not treated as actions. Song titles and artist names are passed through intact.
REQUEST = re.compile(
    r"^(?:(?:tolong|coba|mohon|bantuin|bantu|bisa(?:kah)?|boleh(?:kah)?)\s+){0,3}"
    r"(?:putar(?:kan|in)?|puter(?:in)?|mainkan|play)"
    r"(?:\s+(?:(?:lagu|musik|playlist)\b\s*)?(?P<query>.*))?$",
    re.IGNORECASE,
)


def music_request(content, bot_id=None):
    text = content.strip()
    original = text
    if "\n" in text or "\r" in text:
        return None
    if bot_id is not None:
        text = re.sub(rf"<@!?{re.escape(str(bot_id))}>", "", text).strip()
    text = re.sub(
        r"^(?:(?:hey|hai|halo|oi|yo)\s+)?(?:abud|bud)\b[\s,:!]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r",\s*(?:abud|bud)[.!]?$", "", text, flags=re.IGNORECASE).strip()
    addressed = text != original
    if not addressed and not re.match(
        r"^(?:coba\s+(?:putar|puter|mainkan)\w*\b|"
        r"(?:(?:tolong|coba|mohon)\s+)*(?:putar\w*|puter\w*|mainkan|play)\s+(?:lagu\b|musik\b|playlist\b|<?https://))",
        text,
        re.IGNORECASE,
    ):
        return None
    match = REQUEST.fullmatch(text)
    if not match:
        return None
    query = (match.group("query") or "").strip()
    if re.fullmatch(r"(?:gak|ga|nggak|enggak|tidak|bisa)\?", query, re.IGNORECASE):
        return None
    if len(query) >= 2 and (
        (query[0], query[-1]) in [('"', '"'), ("'", "'"), ("(", ")"), ("<", ">")]
    ):
        query = query[1:-1].strip()
    # Accept a pasted Markdown link only when its visible URL and target agree.
    # Never interpret an arbitrary hyperlink label as a different requested URL.
    linked = re.fullmatch(r"\[(https://[^\s\[\]()]+)\]\((https://[^\s\[\]()]+)\)", query)
    if linked:
        if linked.group(1) != linked.group(2):
            return None
        query = linked.group(2)
    return query


@dataclass(frozen=True)
class ChatMusicContext:
    guild: object
    user: object
    channel: object

    @property
    def guild_id(self):
        return self.guild.id if self.guild else None


async def handle_music_message(message, manager, *, bot_id=None):
    query = music_request(message.content, bot_id)
    if query is None:
        return False
    try:
        if message.guild is None:
            raise MusicError(
                "Musik hanya bisa diputar di server Discord. Masuk voice channel lalu kirim permintaannya di server."
            )
        if not query:
            raise MusicError(
                "Mau putar lagu apa? Tulis: Abud, coba putar judul lagu - nama band, atau gunakan /play dengan link YouTube."
            )
        context = ChatMusicContext(message.guild, message.author, message.channel)
        async with message.channel.typing():
            tracks = await manager.play_query(context, query)
        if len(tracks) == 1:
            title = discord.utils.escape_markdown(
                discord.utils.escape_mentions(tracks[0].title)
            )[:180]
            text = f"🎶 **{title}** masuk antrean musik, Bos. Lihat panel Abud Music untuk status pemutarannya."
        else:
            text = f"🎶 {len(tracks)} lagu masuk antrean musik. Lihat panel Abud Music untuk status pemutarannya."
    except MusicChoiceRequired as choice:
        view = SongSelection(manager, message.author.id, choice.tracks)
        view.message = await message.reply(
            "Pilih lagu yang kamu maksud (berlaku 60 detik; hanya peminta yang bisa memilih).",
            view=view, mention_author=False, allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except Exception as error:  # noqa: BLE001 - do not expose provider responses or credentials in chat
        text = (
            str(error)
            if isinstance(error, MusicError)
            else "Sumber musik belum bisa diputar. Coba judul/link atau sumber lain melalui /play."
        )
    await message.reply(
        text, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
    )
    return True
