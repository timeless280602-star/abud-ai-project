import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router, init, bootstrap_admin, db
from app.highest_ops import router as ops_router, init as ops_init
from app.highest_live import check

class HighestTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.temp.name+"/hq.db","HIGHEST_ORIGIN":"https://abud.web.id"})
        self.env.start()
        self.addCleanup(self.env.stop)
        init()
        ops_init()
        app=FastAPI()
        app.include_router(router)
        app.include_router(ops_router)
        self.admin=TestClient(app,base_url="https://abud.web.id")
        self.user=TestClient(app,base_url="https://abud.web.id")
        for client,name in [(self.admin,"owner"),(self.user,"viewer")]:
            client.headers["Origin"]="https://abud.web.id"
            self.assertEqual(client.post("/highest/api/register",json={"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner")

    def test_native_clip_upload_is_private_until_published(self):
        path="/highest/api"
        png=b"\x89PNG\r\n\x1a\n"+b"\x00"*16
        response=self.user.post(path+"/clip/upload",data={"title":"Native upload"},files={"file":("native.png",png,"image/png")})
        self.assertEqual(response.status_code,200,response.text)
        clip_id=response.json()["id"]
        self.assertEqual(self.user.get(path+"/media/"+str(clip_id)).status_code,200)
        outsider=TestClient(self.admin.app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"})
        self.assertEqual(outsider.post(path+"/register",json={"username":"outsider","display_name":"outsider","password":"long-test-password"}).status_code,200)
        self.assertEqual(outsider.get(path+"/media/"+str(clip_id)).status_code,404)
        pending=self.admin.get(path+"/admin").json()["clips"]
        self.assertEqual(pending[0]["media_type"],"image/png")
        self.assertEqual(self.admin.post(path+f"/admin/clip/{clip_id}/published").status_code,200)
        public=self.admin.get(path+"/media/"+str(clip_id))
        self.assertEqual(public.status_code,200)
        self.assertEqual(public.content,png)

    def test_native_clip_tampering_is_blocked_and_audited(self):
        path="/highest/api"
        png=b"\x89PNG\r\n\x1a\n"+b"\x00"*16
        uploaded=self.user.post(path+"/clip/upload",data={"title":"Tamper test"},files={"file":("tamper.png",png,"image/png")})
        self.assertEqual(uploaded.status_code,200,uploaded.text)
        clip_id=uploaded.json()["id"]
        with db() as c:
            media_path=c.execute("SELECT media_path FROM clips WHERE id=?",(clip_id,)).fetchone()["media_path"]
        target=os.path.join(self.temp.name,"highest_media",media_path)
        with open(target,"wb") as f:
            f.write(png+b"tampered")
        response=self.user.get(path+"/media/"+str(clip_id))
        self.assertEqual(response.status_code,500)
        with db() as c:
            actions=[x["action"] for x in c.execute("SELECT action FROM hq_media_audit WHERE clip_id=?",(clip_id,))]
            audit_event=c.execute("SELECT 1 FROM audit WHERE action='media.integrity_failure' AND target=?",(str(clip_id),)).fetchone()
        self.assertIn("integrity_failure",actions)
        self.assertIsNotNone(audit_event)

    def test_clip_approval_sends_private_notification(self):
        path="/highest/api"
        self.assertEqual(self.user.post(path+"/clip",json={"title":"Approval notice","url":"https://youtu.be/abcdefghijk"}).status_code,200)
        clip_id=self.admin.get(path+"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.admin.post(path+f"/admin/clip/{clip_id}/published").status_code,200)
        with db() as c:
            notice=c.execute("SELECT kind FROM hq_notification WHERE uid=? AND kind='content_approved'",(self.user.get(path+"/me").json()["id"],)).fetchone()
        self.assertIsNotNone(notice)

    def test_external_view_stats_do_not_invent_unavailable_values(self):
        path="/highest/api"
        self.assertEqual(self.user.post(path+"/clip",json={"title":"No API stats","url":"https://youtu.be/abcdefghijk"}).status_code,200)
        clip_id=self.admin.get(path+"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.admin.post(path+f"/admin/clip/{clip_id}/published").status_code,200)
        with patch.dict(os.environ,{"HIGHEST_YOUTUBE_API_KEY":""}):
            result=self.admin.post(path+"/admin/clips/stats/refresh").json()
        self.assertEqual(result["updated"],0)
        self.assertIn(clip_id,result["unavailable"])
        with db() as c:
            self.assertIsNone(c.execute("SELECT views FROM clips WHERE id=?",(clip_id,)).fetchone()["views"])

    def test_scheduled_youtube_stats_refresh_updates_only_published_clips(self):
        path="/highest/api"
        self.assertEqual(self.user.post(path+"/clip",json={"title":"YouTube stats","url":"https://youtu.be/abcdefghijk"}).status_code,200)
        clip_id=self.admin.get(path+"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.admin.post(path+f"/admin/clip/{clip_id}/published").status_code,200)
        response=type("Response",(),{"json":lambda self:{"items":[{"id":"abcdefghijk","statistics":{"viewCount":"1234"}}]},"raise_for_status":lambda self:None})()
        with patch.dict(os.environ,{"HIGHEST_YOUTUBE_API_KEY":"test-key"}):
            with patch("app.highest_stats.httpx.Client") as client:
                client.return_value.__enter__.return_value.get.return_value=response
                from app.highest_stats import refresh
                result=refresh()
        self.assertEqual(result["updated"],1)
        with db() as c:
            row=c.execute("SELECT views,views_source FROM clips WHERE id=?",(clip_id,)).fetchone()
        self.assertEqual(row["views"],1234)
        self.assertEqual(row["views_source"],"youtube_data_api")

    def test_scheduled_tiktok_stats_requires_https_provider(self):
        path="/highest/api"
        self.assertEqual(self.user.post(path+"/clip",json={"title":"TikTok stats","url":"https://www.tiktok.com/@creator/video/123456"}).status_code,200)
        clip_id=self.admin.get(path+"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.admin.post(path+f"/admin/clip/{clip_id}/published").status_code,200)
        response=type("Response",(),{"json":lambda self:{"views":987},"raise_for_status":lambda self:None})()
        with patch.dict(os.environ,{"HIGHEST_TIKTOK_STATS_URL":"https://provider.example/stats","HIGHEST_TIKTOK_STATS_TOKEN":"test-token"}):
            with patch("app.highest_stats.httpx.Client") as client:
                client.return_value.__enter__.return_value.get.return_value=response
                from app.highest_stats import refresh
                result=refresh()
        self.assertEqual(result["updated"],1)
        with db() as c:
            row=c.execute("SELECT views,views_source FROM clips WHERE id=?",(clip_id,)).fetchone()
        self.assertEqual(row["views"],987)
        self.assertEqual(row["views_source"],"tiktok_provider")

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
        no_origin=TestClient(self.admin.app,base_url="https://abud.web.id")
        no_origin.cookies.update(self.admin.cookies)
        self.assertEqual(no_origin.post("/highest/api/admin/clips/stats/refresh").status_code,403)
        with patch.dict(os.environ,{"HIGHEST_YOUTUBE_API_KEY":"","HIGHEST_TIKTOK_STATUS_URL":"","HIGHEST_TIKTOK_STATUS_TOKEN":""}):
            self.assertEqual(check({"platform":"youtube","channel":"UCtest"}),("unknown",None))
            self.assertEqual(check({"platform":"tiktok","channel":"test"}),("unknown",None))
