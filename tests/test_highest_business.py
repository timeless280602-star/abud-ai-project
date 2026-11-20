import os,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin
from app.highest_ops import router as ops,init as ops_init
from app.highest_business import router as business,init as business_init

class BusinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"});self.env.start();self.addCleanup(self.env.stop)
        init();ops_init();business_init()
        app=FastAPI();app.include_router(router);app.include_router(ops);app.include_router(business)
        self.a,self.u,self.v=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(3)]
        for c,name in ((self.a,"owner"),(self.u,"cashier"),(self.v,"viewer")):
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner");self.post(self.a,"/admin/rank",{"name":"Cashier"})
        self.rank=self.get(self.a,"/admin").json()["ranks"][0]["id"]
        self.post(self.u,"/apply",{"character":"Cashier IC"})
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/review/{uid}",{"approve":True,"rank":self.rank,"position":"Cashier"}).status_code,200)
        self.grant("*","approve")
        self.post(self.u,"/ops/item",{"name":"RP Item","category":"IC"})
        self.post(self.u,"/ops/vault",{"name":"Store"})
        data=self.get(self.u,"/ops/inventory").json();self.item=data["items"][0]["id"];self.vault=data["vaults"][0]["id"]
        self.assertEqual(self.post(self.u,"/business/prices",{"item":self.item,"buy":20,"sell":35}).status_code,200)
    def post(self,c,p,d):return c.post("/highest/api"+p,json=d)
    def get(self,c,p):return c.get("/highest/api"+p)
    def grant(self,m,l):
        self.assertEqual(self.post(self.a,"/admin/grants",{"rank":self.rank,"module":m,"level":l}).status_code,200)
    def create(self,direction="sell",nonce="test-nonce-123456789"):
        data={"nonce":nonce,"group_name":"IC Group","direction":direction,"lines":[{"item":self.item,"qty":3}],"vault":self.vault,"treasury":True}
        return self.post(self.u,"/business/orders",data)
    def advance(self,oid):
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":1,"status":"ready"}).status_code,200)
    def test_sale_snapshot_and_atomic_completion(self):
        self.assertEqual(self.get(self.v,"/business/orders").status_code,403)
        oid=self.create().json()["id"]
        self.assertTrue(self.create().json()["duplicate"])
        self.post(self.u,"/business/prices",{"item":self.item,"buy":30,"sell":50})
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["total"],order["estimated_margin"]),(105,45))
        self.advance(oid)
        path=f"/business/orders/{oid}/status"
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,409)
        self.assertEqual(self.get(self.u,"/ops/treasury").json()["entries"],[])
        self.post(self.u,"/ops/move",{"kind":"deposit","vault":self.vault,"item":self.item,"qty":5,"note":"Test"})
        self.assertEqual(self.post(self.u,path,{"version":4,"status":"completed"}).status_code,200)
        self.assertEqual(self.post(self.u,path,{"version":4,"status":"completed"}).status_code,409)
        self.assertEqual(self.get(self.u,"/ops/inventory").json()["stock"][0]["qty"],2)
        ledger=self.get(self.u,"/ops/treasury").json()
        self.assertEqual((ledger["balance"],len(ledger["entries"]),ledger["entries"][0]["amount"]),(0,1,105))
        self.assertEqual(ledger["entries"][0]["state"],"pending")
        analytics=self.get(self.u,"/business/analytics").json()
        self.assertEqual(analytics["summary"]["sales_revenue"],105)
        self.assertEqual(analytics["summary"]["estimated_cogs"],60)
        self.assertEqual(analytics["summary"]["estimated_gross_profit"],45)
        self.assertEqual(analytics["flow"]["output_qty"],3)
        self.assertEqual(analytics["flow"]["valued_output"],105)
    def test_purchase_and_permissions(self):
        oid=self.create("buy").json()["id"];self.advance(oid)
        self.grant("*","none");self.grant("business","write")
        path=f"/business/orders/{oid}/status"
        self.assertEqual(self.post(self.u,path,{"version":4,"status":"completed"}).status_code,403)
        self.assertEqual(self.post(self.u,"/business/prices",{"item":self.item,"buy":1,"sell":2}).status_code,403)
        self.grant("business","approve")
        self.assertEqual(self.post(self.u,path,{"version":4,"status":"completed"}).status_code,403)
        self.grant("inventory","write");self.grant("treasury","write")
        self.assertEqual(self.post(self.u,path,{"version":4,"status":"completed"}).status_code,200)
        self.assertEqual(self.get(self.u,"/ops/inventory").json()["stock"][0]["qty"],3)
        self.assertEqual(self.get(self.u,"/ops/treasury").json()["entries"][0]["amount"],-60)

    def test_three_status_workflow_and_completed_archive(self):
        payload={"nonce":"workflow-test-nonce-12345","group_name":"Test Group","direction":"sell","lines":[{"item":self.item,"qty":2}]}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual(order["status"],"pending")
        for status in ("confirmed","processing","cancelled"):
            self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":1,"status":status}).status_code,400)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":1,"status":"ready"}).status_code,200)
        ready=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual(ready["status"],"ready")
        self.assertEqual(ready["delivery_note"],"Butuh pengantaran")
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        done=self.get(self.u,f"/business/orders/{oid}").json()
        self.assertEqual(done["order"]["status"],"completed")
        self.assertIsNotNone(done["order"]["completed_at"])
        self.assertEqual([x["status"] for x in done["history"]],["pending","ready","completed"])
        self.assertTrue(any(x["id"]==oid and x["status"]=="completed" for x in self.get(self.u,"/business/orders").json()["orders"]))
        self.assertEqual(self.get(self.u,"/business/analytics").json()["summary"]["sales_revenue"],70)

    def test_analytics_requires_own_permission(self):
        self.grant("*","none")
        self.grant("business","view")
        self.assertEqual(self.get(self.u,"/business/analytics").status_code,403)
        self.grant("business_analytics","view")
        result=self.get(self.u,"/business/analytics").json()
        self.assertIn("flow",result)
        self.assertIn("products",result)
