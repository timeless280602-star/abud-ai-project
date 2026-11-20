import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router, init, bootstrap_admin
from app.highest_live import check

class HighestTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.temp.name+"/hq.db","HIGHEST_ORIGIN":"https://abud.web.id"})
        self.env.start()
        self.addCleanup(self.env.stop)
        init()
        app=FastAPI()
        app.include_router(router)
        self.admin=TestClient(app,base_url="https://abud.web.id")
        self.user=TestClient(app,base_url="https://abud.web.id")
        for client,name in [(self.admin,"owner"),(self.user,"viewer")]:
            client.headers["Origin"]="https://abud.web.id"
            self.assertEqual(client.post("/highest/api/register",json={"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner")

    def test_approval_and_revocation(self):
        u=self.user; a=self.admin; path="/highest/api"
        self.assertEqual(u.get(path+"/internal").status_code,403)
        self.assertEqual(u.get(path+"/admin").status_code,403)
        self.assertEqual(u.post(path+"/apply",json={"character":"Test Character"}).status_code,200)
        self.assertEqual(u.get(path+"/internal").status_code,403)
        self.assertEqual(u.post(path+"/admin/rank",json={"name":"Unauthorized"}).status_code,403)
        self.assertEqual(a.post(path+"/admin/rank",json={"name":"Leader","position":0}).status_code,200)
        data=a.get(path+"/admin").json()
        rank=data["ranks"][0]["id"]; uid=data["members"][0]["uid"]
        self.assertEqual(a.post(path+"/admin/review/"+str(uid),json={"approve":True,"rank":rank,"position":"Officer"}).status_code,200)
        self.assertEqual(u.get(path+"/internal").status_code,200)
        self.assertEqual(a.post(path+"/admin/rank",json={"id":rank,"name":"Leader","parent":rank}).status_code,400)
        self.assertEqual(a.post(path+"/admin/rank/delete/"+str(rank),json={}).status_code,409)
        self.assertEqual(a.post(path+"/admin/revoke/"+str(uid),json={}).status_code,200)
        self.assertEqual(u.get(path+"/internal").status_code,403)

    def test_origin_and_unconfigured_live(self):
        self.assertEqual(self.user.post("/highest/api/logout",json={},headers={"Origin":"https://other.example"}).status_code,403)
        with patch.dict(os.environ,{"HIGHEST_YOUTUBE_API_KEY":"","HIGHEST_TIKTOK_STATUS_URL":"","HIGHEST_TIKTOK_STATUS_TOKEN":""}):
            self.assertEqual(check({"platform":"youtube","channel":"UCtest"}),("unknown",None))
            self.assertEqual(check({"platform":"tiktok","channel":"test"}),("unknown",None))
