import unittest
import discord
from urllib.parse import urlsplit, parse_qs
from app.discord_invite import invite_url, INSTALL_PERMISSIONS
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from app.discord_dashboard import install_dashboard_gateway, snowflake, row_json, toggle, administer

class InviteTests(unittest.TestCase):
    def test_fixed_guild_install_and_minimal_permissions(self):
        url = urlsplit(invite_url("123456789012345678"))
        q = parse_qs(url.query)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https","discord.com","/oauth2/authorize"))
        self.assertEqual(q["client_id"], ["123456789012345678"])
        self.assertEqual(q["scope"], ["bot applications.commands"])
        self.assertEqual(q["integration_type"], ["0"])
        self.assertEqual(set(q), {"client_id","scope","integration_type","permissions"})
        perms = discord.Permissions(INSTALL_PERMISSIONS)
        for name in ("manage_channels","add_reactions","view_channel","send_messages","manage_messages","embed_links","attach_files","read_message_history","connect","speak","manage_roles","create_public_threads","create_private_threads","send_messages_in_threads"):
            self.assertTrue(getattr(perms,name), name)
        for name in ("administrator","manage_guild","mention_everyone","ban_members","kick_members"):
            self.assertFalse(getattr(perms,name), name)
    def test_invalid_app_id(self):
        for bad in ("", "123&redirect_uri=evil", "0", 123, "9"*20):
            with self.assertRaises(ValueError):
                invite_url(bad)

class Serialization(unittest.TestCase):
    def test_discord_ids_not_js_numbers(self):
        self.assertEqual(row_json({"channel": 1357798812168618044, "enabled":1})["channel"],"1357798812168618044")
        with self.assertRaises(ValueError): snowflake(1357798812168618044)
        with self.assertRaises(ValueError): snowflake("0")
        with self.assertRaises(ValueError): toggle({"enabled":"false"},"enabled")

class GatewayAuth(AioHTTPTestCase):
    async def get_application(self):
        self.guild = Mock()
        self.guild.id = 123
        self.guild.fetch_member = AsyncMock(return_value=SimpleNamespace(id=456,guild_permissions=SimpleNamespace(administrator=False)))
        self.client_bot=Mock()
        self.client_bot.is_ready.return_value=True
        self.client_bot.application_id=123456789012345678
        self.client_bot.get_guild.side_effect=lambda ident: self.guild if ident==123 else None
        app=web.Application()
        install_dashboard_gateway(app,self.client_bot,"private",None,None,None,None,None,None)
        return app
    async def test_invite_gateway_requires_key_and_returns_live_app_id(self):
        path="/internal/dashboard/discord/install"
        r=await self.client.get(path)
        self.assertEqual(r.status,401)
        r=await self.client.get(path,headers={"Authorization":"Bearer private"})
        self.assertEqual(r.status,200)
        self.assertEqual(await r.json(),{"application_id":"123456789012345678"})
        self.guild.fetch_member.assert_not_called()
    async def test_missing_internal_key(self):
        r=await self.client.post("/internal/dashboard/discord",json={})
        self.assertEqual(r.status,401)
        self.guild.fetch_member.assert_not_called()
    async def test_non_admin_and_nonmember_server(self):
        headers={"Authorization":"Bearer private"}
        for guild in ("123","999"):
            r=await self.client.post("/internal/dashboard/discord",headers=headers,json={"guild_id":guild,"user_id":"456","action":"read"})
            self.assertEqual(r.status,403)
        self.guild.fetch_member.assert_awaited_once_with(456)
    async def test_browser_cannot_supply_admin(self):
        r=await self.client.post("/internal/dashboard/discord",headers={"Authorization":"Bearer private"},json={"guild_id":"123","user_id":"456","action":"ticket.save","data":{"admin":True}})
        self.assertEqual(r.status,403)

class Actions(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            await administer(SimpleNamespace(id=123),None,"something",{},None,None,None,None)
    async def test_leveling_save_uses_original_store(self):
        manager=Mock()
        guild=SimpleNamespace(id=123)
        await administer(guild,None,"leveling.save",{"enabled":True,"chat":True,"voice":False,"announcement":None},manager,None,None,None)
        manager.store.configure.assert_called_once_with(123,True,True,False,None)
        manager.sync_voice.assert_called_once_with(guild)
