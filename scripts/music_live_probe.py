"""Opt-in staging-only Discord playback; no production application login or storage."""
import asyncio
import logging
import os
from uuid import uuid4

import discord
import wavelink

logging.disable(logging.CRITICAL)


class PlaybackProbe(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.started = False
        self.success = False
        self.player = None
        self.node = None
        self.turn = None
        self.turn_id = None

    async def on_wavelink_track_end(self, payload):
        if (
            self.turn and not self.turn.done()
            and payload.player is self.player
            and getattr(payload.track.extras, "probe_id", None) == self.turn_id
        ):
            self.turn.set_result(("end", str(payload.reason)))

    async def on_wavelink_track_exception(self, payload):
        if (
            self.turn and not self.turn.done()
            and payload.player is self.player
            and getattr(payload.track.extras, "probe_id", None) == self.turn_id
        ):
            self.turn.set_result(("error", "provider exception"))

    async def on_wavelink_track_stuck(self, payload):
        if (
            self.turn and not self.turn.done()
            and payload.player is self.player
            and getattr(payload.track.extras, "probe_id", None) == self.turn_id
        ):
            self.turn.set_result(("error", "track stuck"))

    async def play_probe(self, label, query):
        print(f"=== LIVE {label} ===", flush=True)
        try:
            tracks = await wavelink.Pool.fetch_tracks(query, node=self.node)
            if not tracks or isinstance(tracks, wavelink.Playlist):
                print(f"{label}: no playable single track", flush=True)
                return False
            track = tracks[0]
            self.turn = asyncio.get_running_loop().create_future()
            self.turn_id = uuid4().hex
            track.extras = {"probe_id": self.turn_id}
            await self.player.play(track, volume=25, paused=False, add_history=False)
            async with asyncio.timeout(18):
                while True:
                    if self.turn.done():
                        kind, reason = self.turn.result()
                        if kind == "end" and reason.lower() == "finished":
                            print(f"{label}: track finished; audible confirmation required", flush=True)
                            return True
                        print(f"{label}: {kind} ({reason})", flush=True)
                        return False
                    if self.player.connected and self.player.position >= 5000:
                        print(f"{label}: position advanced >= 5 s; audible confirmation required", flush=True)
                        return True
                    await asyncio.sleep(0.2)
        except (Exception, asyncio.TimeoutError) as error:
            print(f"{label}: {type(error).__name__}", flush=True)
            return False
        finally:
            self.turn = None
            self.turn_id = None
            if self.player:
                await self.player.skip(force=True)

    async def on_ready(self):
        if self.started:
            return
        self.started = True
        try:
            async with asyncio.timeout(100):
                if str(self.user.id) == os.environ["PRODUCTION_BOT_ID"]:
                    raise RuntimeError("Refusing production bot identity")
                channel = self.get_channel(int(os.environ["STAGING_VOICE_CHANNEL_ID"]))
                if not isinstance(channel, discord.VoiceChannel):
                    raise RuntimeError("Staging voice channel not accessible")
                if str(channel.guild.id) != os.environ["STAGING_GUILD_ID"]:
                    raise RuntimeError("Wrong staging guild")
                if not any(not member.bot for member in channel.members):
                    raise RuntimeError("Join the selected test channel first")
                permissions = channel.permissions_for(channel.guild.me)
                if not all((permissions.view_channel, permissions.connect, permissions.speak)):
                    raise RuntimeError("Missing staging voice permissions")
                self.node = wavelink.Node(
                    uri="http://music-provider-staging:2333",
                    password=os.environ["STAGING_PASSWORD"],
                    retries=0,
                    inactive_player_timeout=None,
                )
                async with asyncio.timeout(15):
                    await wavelink.Pool.connect(nodes=[self.node], client=self)
                    while self.node.status == wavelink.NodeStatus.CONNECTING:
                        await asyncio.sleep(0.05)
                    if self.node.status != wavelink.NodeStatus.CONNECTED:
                        raise RuntimeError("Staging node not ready")
                self.player = await channel.connect(
                    cls=wavelink.Player, timeout=20, reconnect=False, self_deaf=True
                )
                self.player.autoplay = wavelink.AutoPlayMode.disabled
                local_ok = await self.play_probe("local-tone", "/diagnostic/tone.wav")
                youtube_ok = await self.play_probe("youtube", "ytsearch:Separuh Aku NOAH")
                print(f"LIVE RESULTS local={local_ok} youtube={youtube_ok}", flush=True)
                self.success = True  # completed probe is not a playback pass
        except Exception as error:
            print("LIVE PROBE FAILED:", type(error).__name__, flush=True)
        finally:
            try:
                if self.player:
                    await self.player.disconnect()
            finally:
                try:
                    if self.node:
                        await self.node.close(eject=True)
                finally:
                    await self.close()


async def main():
    client = PlaybackProbe()
    try:
        async with asyncio.timeout(140):
            async with client:
                await client.start(os.environ["STAGING_DISCORD_TOKEN"])
    except Exception as error:
        print("Staging gateway failure:", type(error).__name__, flush=True)
        raise SystemExit(1) from None
    if not client.success:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
