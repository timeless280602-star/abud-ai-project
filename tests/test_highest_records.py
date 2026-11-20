import os,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin
from app.highest_ops import router as ops,init as ops_init
from app.highest_social import init as social_init
from app.highest_records import router as records,init as records_init

class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"});self.env.start();self.addCleanup(self.env.stop)
        init();ops_init();social_init();records_init()
        app=FastAPI();app.include_router(router);app.include_router(ops);app.include_router(records)
        self.a,self.u,self.v=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(3)]
        for c,name in ((self.a,"owner"),(self.u,"member"),(self.v,"viewer")):
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner")
        self.post(self.a,"/admin/rank",{"name":"Director"})
        rank=self.get(self.a,"/admin").json()["ranks"][0]["id"]
        self.post(self.u,"/apply",{"character":"Fictional Character"})
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/review/{uid}",{"approve":True,"rank":rank,"position":"Director"}).status_code,200)
        self.rank=rank
    def post(self,c,p,d):return c.post("/highest/api"+p,json=d)
    def get(self,c,p):return c.get("/highest/api"+p)
    def grant(self,m,l):
        self.assertEqual(self.post(self.a,"/admin/grants",{"rank":self.rank,"module":m,"level":l}).status_code,200)
    def test_records_permissions_version_and_ack(self):
        self.assertEqual(self.get(self.u,"/records/documents").status_code,403)
        self.grant("*","approve")
        self.assertEqual(self.get(self.v,"/records/documents").status_code,403)
        payload={"title":"SOP","category":"RP","detail":"Test","status":"active"}
        rid=self.post(self.u,"/records/documents",payload).json()["id"]
        self.assertEqual(self.get(self.u,f"/records/assets/{rid}").status_code,404)
        self.assertEqual(self.post(self.u,f"/records/documents/{rid}/ack",{}).status_code,200)
        self.assertTrue(self.get(self.u,"/records/documents").json()[0]["acknowledged"])
        self.assertEqual(self.post(self.u,f"/records/documents/{rid}",{**payload,"version":1,"detail":"Updated"}).status_code,200)
        self.assertFalse(self.get(self.u,"/records/documents").json()[0]["acknowledged"])
        self.assertEqual(self.post(self.u,f"/records/documents/{rid}",{**payload,"version":1}).status_code,409)
        self.assertEqual(len(self.get(self.u,f"/records/documents/{rid}").json()["revisions"]),2)
        self.grant("*","none")
        self.grant("documents","write")
        self.assertEqual(self.post(self.u,f"/records/documents/{rid}",{**payload,"version":2,"status":"archived"}).status_code,403)
    def test_case_extras_and_approval_scope(self):
        self.grant("cases","write")
        cid=self.post(self.u,"/ops/cases",{"name":"IC Case","summary":"Fictional"}).json()["id"]
        self.assertEqual(self.post(self.u,f"/case-extras/{cid}/evidence",{"title":"RP screenshot","reference":"Screenshot 1"}).status_code,200)
        self.assertEqual(self.post(self.u,f"/case-extras/{cid}/relation",{"left_name":"Character A","right_name":"Character B","label":"Fictional relation"}).status_code,200)
        self.assertEqual(self.get(self.v,f"/case-extras/{cid}").status_code,403)
        self.assertEqual(len(self.get(self.u,f"/case-extras/{cid}").json()["relations"]),1)
        self.assertEqual(self.get(self.u,"/approval-center").json(),{"treasury":[],"membership":[],"clips":[],"community":{}})
        self.assertEqual(self.get(self.v,"/approval-center").status_code,403)
