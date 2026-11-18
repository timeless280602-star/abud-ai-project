import asyncio
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import discord
from aiohttp import web
from discord import app_commands

from app.creator_notifications import (
    Creator,
    Event,
    NotificationError,
    Store,
    parse_account,
)
from app.creator_providers import YouTube
from app.discord_notifications import Notifications, install_notification_commands

ACCOUNT = "UC" + "a" * 22


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "db.sqlite")
        self.store = Store(self.path)
        self.creator = Creator("youtube", ACCOUNT, "Creator", "uploads")
        self.ident = self.store.add(1, 10, self.creator, "none", "both")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_limit_is_per_guild_and_platform_and_includes_paused(self):
        for i in range(9):
            self.store.add(1, 10, Creator("youtube", str(i), "T"), "none", "both")
        self.store.edit(1, self.ident, 10, "none", "both", False)
        with self.assertRaisesRegex(NotificationError, "10"):
            self.store.add(1, 10, Creator("youtube", "overflow", "T"), "none", "both")
        self.store.add(2, 20, self.creator, "here", "live")
        self.store.add(1, 10, Creator("tiktok", "creator", "T"), "none", "post")

    def test_duplicate_and_cross_guild_mutations_are_rejected(self):
        with self.assertRaises(NotificationError):
            self.store.add(1, 10, self.creator, "none", "live")
        with self.assertRaises(NotificationError):
            self.store.remove(2, self.ident)
        with self.assertRaises(NotificationError):
            self.store.edit(2, self.ident, 20, "everyone", "both", True)
        self.assertEqual(len(self.store.list(1)), 1)

    def test_history_and_delivery_keys_survive_restart(self):
        row = self.store.get(1, self.ident)
        post = Event("youtube", ACCOUNT, "vid", "post", "T", time.time() + 1)
        live = Event("youtube", ACCOUNT, "vid", "live", "T", time.time() + 1)
        self.assertTrue(self.store.wants(row, post))
        self.store.delivered(row, post)
        self.store.close()
        self.store = Store(self.path)
        self.assertFalse(self.store.wants(row, post))
        self.assertTrue(self.store.wants(row, live))

    def test_old_posts_wrong_source_event_filter_pause_and_resume(self):
        row = self.store.get(1, self.ident)
        old = Event("youtube", ACCOUNT, "old", "post", "T", row["since"] - 10)
        self.assertFalse(self.store.wants(row, old))
        self.assertFalse(
            self.store.wants(
                row, Event("youtube", "other", "x", "live", "T", time.time())
            )
        )
        self.store.edit(1, self.ident, 10, "here", "live", False)
        self.assertFalse(
            self.store.wants(
                self.store.get(1, self.ident),
                Event("youtube", ACCOUNT, "x", "live", "T", time.time()),
            )
        )
        with patch(
            "app.creator_notifications.time.time", return_value=row["since"] + 100
        ):
            self.store.edit(1, self.ident, 10, "none", "live", True)
        row = self.store.get(1, self.ident)
        self.assertFalse(
            self.store.wants(
                row, Event("youtube", ACCOUNT, "x", "live", "T", row["since"] - 1)
            )
        )
        self.assertFalse(
            self.store.wants(
                row, Event("youtube", ACCOUNT, "x", "post", "T", row["since"] + 1)
            )
        )

    def test_pending_scheduled_streams_persist_and_expire(self):
        self.store.watch(ACCOUNT, "future", time.time() + 100)
        self.store.watch(ACCOUNT, "expired", time.time() - 1)
        self.assertEqual(self.store.pending(ACCOUNT), ["future"])
        self.store.unwatch(ACCOUNT, "future")
        self.assertEqual(self.store.pending(ACCOUNT), [])

    def test_remove_cleans_dedupe_state(self):
        row = self.store.get(1, self.ident)
        self.store.delivered(
            row, Event("youtube", ACCOUNT, "x", "live", "T", time.time())
        )
        self.store.remove(1, self.ident)
        self.assertEqual(self.store.list(1), [])
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0], 0
        )


class URLTests(unittest.TestCase):
    def test_supported_links(self):
        for value in ["@creator", "https://www.youtube.com/@creator/streams?x=1"]:
            self.assertEqual(parse_account("youtube", value), ("forHandle", "@creator"))
        self.assertEqual(
            parse_account("youtube", "https://youtube.com/channel/" + ACCOUNT),
            ("id", ACCOUNT),
        )
        self.assertEqual(
            parse_account("youtube", "https://youtube.com/user/legacy"),
            ("forUsername", "legacy"),
        )
        self.assertEqual(
            parse_account("tiktok", "https://www.tiktok.com/@Creator"),
            ("forHandle", "creator"),
        )

    def test_untrusted_and_invalid_links(self):
        for value in [
            "https://youtube.com.evil/@x",
            "http://youtube.com/@x",
            "https://localhost/@x",
            "https://user@youtube.com/@x",
            "https://youtube.com:123/@x",
            "https://youtube.com:bad/@x",
            "https://youtube.com/watch?v=x",
            "https://youtube.com/c/legacy",
        ]:
            with self.subTest(value=value), self.assertRaises(NotificationError):
                parse_account("youtube", value)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "db"))
        self.provider = YouTube(None, "secret", self.store)
        self.creator = Creator("youtube", ACCOUNT, "T", "UUxxx")

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    def item(self, ident, state="none", live=None, account=ACCOUNT):
        item = {
            "id": ident,
            "snippet": {
                "channelId": account,
                "title": ident,
                "liveBroadcastContent": state,
                "publishedAt": "2026-11-18T12:00:00Z",
                "thumbnails": {
                    "default": {"url": f"https://i.ytimg.com/vi/{ident}/default.jpg"},
                    "high": {"url": f"https://i.ytimg.com/vi/{ident}/hqdefault.jpg"},
                },
            },
        }
        if live is not None:
            item["liveStreamingDetails"] = live
        return item

    async def test_upcoming_to_live_no_archive_as_new_post(self):
        items = [
            self.item("post"),
            self.item(
                "scheduled", "upcoming", {"scheduledStartTime": "2026-11-19T00:00:00Z"}
            ),
            self.item(
                "archive",
                "none",
                {
                    "actualStartTime": "2026-11-17T12:00:00Z",
                    "actualEndTime": "2026-11-17T13:00:00Z",
                },
            ),
            self.item("wrong", account="wrong"),
        ]
        self.provider.request = AsyncMock(
            side_effect=[
                {"items": [{"contentDetails": {"videoId": x["id"]}} for x in items]},
                {"items": items},
            ]
        )
        events = await self.provider.poll(self.creator)
        self.assertEqual([(e.video, e.kind) for e in events], [("post", "post")])
        self.assertEqual(self.store.pending(ACCOUNT), ["scheduled"])
        # Stream left uploads window, but retained upcoming ID is queried.
        self.provider.request = AsyncMock(
            side_effect=[
                {"items": []},
                {
                    "items": [
                        self.item(
                            "scheduled",
                            "live",
                            {"actualStartTime": "2026-11-19T00:00:00Z"},
                        )
                    ]
                },
            ]
        )
        events = await self.provider.poll(self.creator)
        self.assertEqual(events[0].kind, "live")
        self.assertEqual(
            events[0].thumbnail, "https://i.ytimg.com/vi/scheduled/hqdefault.jpg"
        )
        self.assertEqual(self.provider.request.call_args.kwargs["id"], "scheduled")

    async def test_batches_video_ids_and_uses_fixed_resolution(self):
        self.provider.request = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": ACCOUNT,
                        "snippet": {"title": "T"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UUxxx"}},
                    }
                ]
            }
        )
        self.assertEqual(await self.provider.resolve("@creator"), self.creator)
        self.assertEqual(
            self.provider.request.call_args.kwargs["forHandle"], "@creator"
        )
        for i in range(80):
            self.store.watch(ACCOUNT, str(i), time.time() + 100)
        self.provider.request = AsyncMock(return_value={"items": []})
        await self.provider.poll(self.creator)
        calls = self.provider.request.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(len(c.kwargs["id"].split(",")) <= 50 for c in calls[1:]))

    async def test_missing_key_and_quota_cooldown(self):
        self.provider.key = ""
        with self.assertRaises(NotificationError):
            await self.provider.request("channels")
        self.provider.key = "secret"
        response = AsyncMock()
        response.status = 403
        http = Mock()
        http.get.return_value.__aenter__ = AsyncMock(return_value=response)
        http.get.return_value.__aexit__ = AsyncMock(return_value=False)
        self.provider.http = http
        with self.assertRaises(NotificationError):
            await self.provider.request("videos")
        with self.assertRaises(NotificationError):
            await self.provider.request("videos")
        self.assertEqual(http.get.call_count, 1)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Notifications(Mock())
        self.manager.enabled = True
        self.manager.store = Store(str(Path(self.temp.name) / "db"))
        self.manager.webhook_secret = "s" * 32
        self.ident = self.manager.store.add(
            1, 10, Creator("tiktok", "creator", "Creator"), "everyone", "both"
        )

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_concurrent_events_retry_only_failed_delivery(self):
        manager = self.manager
        event = Event("tiktok", "creator", "123", "live", "T", time.time())
        manager.send = AsyncMock(side_effect=[NotificationError("offline"), None])
        with self.assertRaises(NotificationError):
            await manager.dispatch(event)
        await asyncio.gather(manager.dispatch(event), manager.dispatch(event))
        self.assertEqual(manager.send.await_count, 2)

    def request(self, data, stamp=None, secret=None):
        raw = json.dumps(data).encode()
        stamp = str(int(time.time())) if stamp is None else stamp
        sig = hmac.new(
            (secret or self.manager.webhook_secret).encode(),
            stamp.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        return Mock(
            headers={"X-Abud-Timestamp": stamp, "X-Abud-Signature": sig},
            read=AsyncMock(return_value=raw),
        )

    def payload(self):
        return {
            "account": "@Creator",
            "id": "12345",
            "kind": "post",
            "title": "@everyone new",
            "occurred_at": time.time(),
        }

    async def test_webhook_signature_expiry_validation_and_replay(self):
        self.manager.send = AsyncMock()
        payload = self.payload()
        for request in [
            self.request(payload, secret="wrong"),
            self.request(payload, stamp="0"),
        ]:
            with self.assertRaises(web.HTTPUnauthorized):
                await self.manager.webhook(request)
        with self.assertRaises(web.HTTPBadRequest):
            await self.manager.webhook(self.request({**payload, "id": "https://evil"}))
        for _ in range(2):
            result = await self.manager.webhook(self.request(payload))
            self.assertEqual(result.status, 200)
        self.assertEqual(self.manager.send.await_count, 1)

    async def test_webhook_failure_requests_provider_retry(self):
        self.manager.send = AsyncMock(side_effect=NotificationError("offline"))
        with self.assertRaises(web.HTTPServiceUnavailable):
            await self.manager.webhook(self.request(self.payload()))

    async def test_only_intended_literal_ping_allowed_and_test_never_pings(self):
        channel = Mock(send=AsyncMock())
        self.manager.destination = Mock(return_value=channel)
        row = self.manager.store.get(1, self.ident)
        event = Event(
            "tiktok", "creator", "123", "post", "@everyone <@123> title", time.time()
        )
        await self.manager.send(row, event)
        kwargs = channel.send.call_args.kwargs
        self.assertEqual(kwargs["content"], "@everyone")
        self.assertFalse(kwargs["allowed_mentions"].users)
        self.assertFalse(kwargs["allowed_mentions"].roles)
        self.assertEqual(kwargs["view"].children[0].label, "Watch Video")
        self.assertEqual(kwargs["view"].children[0].url, event.url)
        await self.manager.send(row, event, test=True)
        kwargs = channel.send.call_args.kwargs
        self.assertIsNone(kwargs["content"])
        self.assertFalse(kwargs["allowed_mentions"].everyone)
        self.manager.destination.assert_called_with(1, 10, "none")
        self.assertEqual(kwargs["embed"].url, "https://www.tiktok.com/@creator")

    async def test_live_embed_uses_actual_title_large_thumbnail_and_watch_button(self):
        channel = Mock(send=AsyncMock())
        self.manager.destination = Mock(return_value=channel)
        event = Event(
            "youtube",
            ACCOUNT,
            "abcDEF123_-",
            "live",
            "Live Main Bareng Bos Bara",
            time.time(),
            "https://i.ytimg.com/vi/abcDEF123_-/maxresdefault.jpg",
        )
        row = self.manager.store.get(1, self.ident)
        await self.manager.send(row, event)
        message = channel.send.call_args.kwargs
        embed = message["embed"].to_dict()
        self.assertEqual(embed["title"], event.title)
        self.assertEqual(embed["url"], event.url)
        self.assertEqual(embed["image"]["url"], event.thumbnail)
        button = message["view"].to_components()[0]["components"][0]
        self.assertEqual(button["label"], "Watch Live")
        self.assertEqual(button["url"], event.url)
        self.assertEqual(button["style"], discord.ButtonStyle.link.value)
        self.assertNotIn("custom_id", button)
        self.assertIsNone(message["view"].timeout)

    async def test_youtube_thumbnail_fallback_and_tiktok_provider_thumbnail(self):
        channel = Mock(send=AsyncMock())
        self.manager.destination = Mock(return_value=channel)
        row = self.manager.store.get(1, self.ident)
        youtube = Event("youtube", ACCOUNT, "abcDEF123_-", "live", "Live", time.time())
        await self.manager.send(row, youtube)
        self.assertEqual(
            channel.send.call_args.kwargs["embed"].image.url,
            "https://i.ytimg.com/vi/abcDEF123_-/hqdefault.jpg",
        )
        self.manager.send = AsyncMock()
        payload = {
            **self.payload(),
            "kind": "live",
            "thumbnail": "https://cdn.example.com/actual-cover.jpg",
        }
        await self.manager.webhook(self.request(payload))
        self.assertEqual(
            self.manager.send.call_args.args[1].thumbnail, payload["thumbnail"]
        )

    def test_target_permissions_and_cross_guild(self):
        guild = Mock()
        channel = Mock(spec=discord.TextChannel)
        guild.get_channel.return_value = channel
        perms = Mock(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            mention_everyone=False,
        )
        channel.permissions_for.return_value = perms
        self.manager.client.get_guild.return_value = guild
        self.assertIs(self.manager.destination(1, 10, "none"), channel)
        with self.assertRaises(NotificationError):
            self.manager.destination(1, 10, "here")
        perms.embed_links = False
        with self.assertRaises(NotificationError):
            self.manager.destination(1, 10, "none")
        guild.get_channel.return_value = None
        with self.assertRaises(NotificationError):
            self.manager.destination(1, 20, "none")

    async def test_reconnect_start_is_idempotent_and_close_cancels(self):
        await self.manager.close()
        self.manager.path = str(Path(self.temp.name) / "newdb")
        self.manager.client.wait_until_ready = AsyncMock(
            side_effect=lambda: asyncio.sleep(100)
        )
        await self.manager.start()
        task = self.manager.task
        await self.manager.start()
        self.assertIs(self.manager.task, task)
        await self.manager.close()
        self.assertTrue(task.cancelled())

    async def test_commands_register_with_admin_defaults_and_runtime_guard(self):
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        install_notification_commands(tree, self.manager)
        group = tree.get_command("notify")
        self.assertEqual(
            {c.name for c in group.commands}, {"add", "edit", "remove", "list", "test"}
        )
        self.assertTrue(group.default_permissions.administrator)
        interaction = Mock(guild=Mock(), permissions=Mock(administrator=False))
        with self.assertRaises(NotificationError):
            await group.get_command("remove").callback(interaction, self.ident)
        await client.close()
