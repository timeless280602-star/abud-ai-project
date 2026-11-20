import os,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin
from app.highest_social import router as social,init as social_init
class SocialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"});self.env.start();self.addCleanup(self.env.stop)
        init();social_init()
        app=FastAPI();app.include_router(router);app.include_router(social)
        self.a,self.u,self.v=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(3)]
        for c,name in ((self.a,"owner"),(self.u,"clipper"),(self.v,"viewer")):
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner")
    def post(self,c,p,d):return c.post("/highest/api"+p,json=d)
    def get(self,c,p):return c.get("/highest/api"+p)
    def test_moderation_and_pov(self):
        self.assertEqual(self.post(self.u,"/clip",{"title":"Clip","url":"https://youtu.be/example"}).status_code,200)
        cid=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{cid}/published",{}).status_code,200)
        mid=self.post(self.u,"/social/moment",{"title":"Story","summary":"Public RP","spoiler":True}).json()["id"]
        self.assertEqual(self.get(self.v,"/social").json()["moments"],[])
        self.assertEqual(self.post(self.v,f"/social/moment/{mid}/pov",{"clip":cid,"label":"POV"}).status_code,404)
        self.assertEqual(self.post(self.u,f"/social/moment/{mid}/pov",{"clip":cid,"label":"POV"}).status_code,200)
        pid=self.get(self.a,"/admin/social").json()["povs"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{pid}",{"approve":True}).status_code,409)
        self.assertEqual(self.post(self.v,f"/admin/social/moment/{mid}",{"approve":True}).status_code,403)
        self.assertEqual(self.post(self.a,f"/admin/social/moment/{mid}",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.v,"/social").json()["moments"][0]["povs"],[])
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{pid}",{"approve":True}).status_code,200)
        self.assertEqual(len(self.get(self.v,"/social").json()["moments"][0]["povs"]),1)
        second=self.post(self.u,"/social/moment",{"title":"Second story","summary":"More public RP"}).json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/moment/{second}",{"approve":True}).status_code,200)
        self.assertEqual(self.post(self.v,f"/social/moment/{second}/pov",{"clip":cid,"label":"Independent POV"}).status_code,200)
        pending=self.get(self.a,"/admin/social").json()["povs"]
        second_pov=next(x for x in pending if x["moment"]==second)
        self.assertEqual(second_pov["username"],"viewer")
        self.assertEqual(second_pov["clip_owner"],"clipper")
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{second_pov['id']}",{"approve":True}).status_code,200)
        published=next(x for x in self.get(self.v,"/social").json()["moments"] if x["id"]==second)
        self.assertEqual(published["povs"][0]["display_name"],"viewer")
        self.assertEqual(published["povs"][0]["clip_owner"],"clipper")
        for _ in range(2): self.assertEqual(self.post(self.v,f"/social/clip/{cid}/like",{"enabled":True}).status_code,200)
        self.assertEqual(self.get(self.v,"/social").json()["clips"][0]["likes"],1)
        self.assertEqual(self.post(self.v,f"/social/clip/{cid}/bookmark",{"enabled":True}).status_code,200)
        self.assertEqual(len(self.get(self.v,"/social/studio").json()["bookmarks"]),1)
    def test_creator_wiki_feed(self):
        self.assertEqual(self.post(self.u,"/social/creator",{"kind":"streamer","url":"https://evil.example/a"}).status_code,400)
        self.assertEqual(self.post(self.u,"/social/creator",{"kind":"streamer","url":"https://www.tiktok.com/@test"}).status_code,200)
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/creator/{uid}/streamer",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.u,"/internal").status_code,403)
        self.assertEqual(len(self.get(self.v,"/social").json()["creators"]),1)
        self.assertEqual(self.post(self.u,"/social/wiki",{"kind":"lore","title":"Lore","body":"Public IC"}).status_code,200)
        self.assertEqual(self.post(self.u,"/social/post",{"category":"general","body":"Hello"}).status_code,200)
        result=self.get(self.v,"/social").json()
        self.assertEqual(result["wiki"],[]);self.assertEqual(result["posts"],[])
        mod=self.get(self.a,"/admin/social").json()
        for kind,key in (("wiki","wiki"),("post","posts")):
            self.assertEqual(self.post(self.a,f"/admin/social/{kind}/{mod[key][0]['id']}",{"approve":True}).status_code,200)
        result=self.get(self.v,"/social").json()
        self.assertEqual(len(result["wiki"]),1);self.assertEqual(len(result["posts"]),1)
        self.assertEqual(result["wiki"][0]["display_name"],"clipper")
        self.assertEqual(mod["wiki"][0]["username"],"clipper")
        self.assertEqual(mod["posts"][0]["username"],"clipper")
