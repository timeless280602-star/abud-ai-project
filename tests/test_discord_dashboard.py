import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from app.discord_dashboard import install_dashboard_gateway, snowflake, row_json, toggle, administer

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
        self.client_bot.get_guild.side_effect=lambda ident: self.guild if ident==123 else None
        app=web.Application()
        install_dashboard_gateway(app,self.client_bot,"private",None,None,None,None,None,None)
        return app
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
