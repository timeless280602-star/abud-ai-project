import os,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin
from app.highest_ops import router as ops,init as ops_init

class OpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"})
        self.env.start();self.addCleanup(self.env.stop)
        init();ops_init()
        app=FastAPI();app.include_router(router);app.include_router(ops)
        self.path="/highest/api"
        self.a,self.u,self.v=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(3)]
        for c,name in [(self.a,"admin"),(self.u,"member"),(self.v,"reviewer")]:
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("admin")
        self.post(self.a,"/admin/rank",{"name":"Operations"})
        self.rank=self.get(self.a,"/admin").json()["ranks"][0]["id"]
        for c in (self.u,self.v):
            self.post(c,"/apply",{"character":"Test"})
            uid=self.get(c,"/me").json()["id"]
            self.assertEqual(self.post(self.a,f"/admin/review/{uid}",{"approve":True,"rank":self.rank,"position":"Officer"}).status_code,200)
    def post(self,c,path,data):return c.post(self.path+path,json=data)
    def get(self,c,path):return c.get(self.path+path)
    def grant(self,module,level="approve"):
        self.assertEqual(self.post(self.a,"/admin/grants",{"module":module,"rank":self.rank,"level":level}).status_code,200)
    def test_money(self):
        self.assertEqual(self.get(self.u,"/ops/treasury").status_code,403)
        self.grant("treasury")
        data={"amount":100,"direction":"income","category":"RP","note":"Test"}
        mid=self.post(self.u,"/ops/treasury",data).json()["id"]
        self.assertEqual(self.get(self.u,"/ops/treasury").json()["balance"],0)
        self.assertEqual(self.post(self.u,f"/ops/treasury/{mid}/review",{"approve":True}).status_code,403)
        self.assertEqual(self.post(self.v,f"/ops/treasury/{mid}/review",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.u,"/ops/treasury").json()["balance"],100)
        mid=self.post(self.u,"/ops/treasury",{**data,"amount":101,"direction":"expense"}).json()["id"]
        self.assertEqual(self.post(self.v,f"/ops/treasury/{mid}/review",{"approve":True}).status_code,409)
        self.grant("treasury","none")
        self.assertEqual(self.get(self.u,"/ops/treasury").status_code,403)
    def test_stock_rollback_and_crafting(self):
        self.grant("inventory");self.grant("crafting")
        for name in ("A","B"):
            self.assertEqual(self.post(self.u,"/ops/vault",{"name":name}).status_code,200)
        for name in ("Material","Output"):
            self.assertEqual(self.post(self.u,"/ops/item",{"name":name,"category":"IC"}).status_code,200)
        d=self.get(self.u,"/ops/inventory").json()
        a,b=[r["id"] for r in d["vaults"]]; item,out=[r["id"] for r in d["items"]]
        move={"kind":"deposit","vault":a,"item":item,"qty":10,"note":"Test"}
        self.assertEqual(self.post(self.u,"/ops/move",move).status_code,200)
        self.assertEqual(self.post(self.u,"/ops/move",{**move,"kind":"transfer","destination":9999,"qty":2}).status_code,404)
        self.assertEqual(self.get(self.u,"/ops/inventory").json()["stock"][0]["qty"],10)
        self.assertEqual(self.post(self.u,"/ops/move",{**move,"kind":"transfer","destination":b,"qty":2}).status_code,200)
        self.assertEqual(self.post(self.u,"/ops/recipe",{"name":"RP recipe","output":out,"output_qty":1,"ingredients":[{"item":item,"qty":3}]}).status_code,200)
        recipe=self.get(self.u,"/ops/crafting").json()["recipes"][0]["id"]
        craft={"recipe":recipe,"vault":a,"batches":3,"note":"Test"}
        self.assertEqual(self.post(self.u,"/ops/craft",craft).status_code,409)
        self.assertEqual(self.get(self.u,"/ops/crafting").json()["batches"],[])
        self.assertEqual(self.post(self.u,"/ops/craft",{**craft,"batches":2}).status_code,200)
        stock={(s["vault"],s["item"]):s["qty"] for s in self.get(self.u,"/ops/inventory").json()["stock"]}
        self.assertEqual(stock,{(a,item):2,(b,item):2,(a,out):2})
    def test_cases(self):
        self.grant("cases","view")
        self.assertEqual(self.post(self.u,"/ops/cases",{"name":"Case","summary":"IC"}).status_code,403)
        self.grant("cases","write")
        cid=self.post(self.u,"/ops/cases",{"name":"Case","summary":"IC"}).json()["id"]
        self.assertEqual(self.post(self.u,f"/ops/cases/{cid}",{"note":"Update","status":"closed"}).status_code,200)
        self.assertEqual(self.get(self.u,f"/ops/cases/{cid}").json()["case"]["status"],"closed")
