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
        self.a,self.u,self.v,self.m=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(4)]
        for c,name in ((self.a,"owner"),(self.u,"cashier"),(self.v,"viewer"),(self.m,"manager")):
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner");self.post(self.a,"/admin/rank",{"name":"Cashier"})
        self.post(self.a,"/admin/rank",{"name":"Manager","position":1})
        ranks=self.get(self.a,"/admin").json()["ranks"]
        self.rank=next(x["id"] for x in ranks if x["name"]=="Cashier")
        self.manager_rank=next(x["id"] for x in ranks if x["name"]=="Manager")
        self.post(self.u,"/apply",{"character":"Cashier IC"})
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/review/{uid}",{"approve":True,"rank":self.rank,"position":"Cashier"}).status_code,200)
        self.post(self.m,"/apply",{"character":"Manager IC"})
        manager_uid=self.get(self.m,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/review/{manager_uid}",{"approve":True,"rank":self.manager_rank,"position":"Manager"}).status_code,200)
        self.grant("*","approve")
        self.grant_rank(self.manager_rank,"business_discounts","approve")
        self.set_discount_policy("both",100,1000000000000)
        self.post(self.u,"/ops/item",{"name":"RP Item","category":"IC"})
        self.post(self.u,"/ops/vault",{"name":"Store"})
        data=self.get(self.u,"/ops/inventory").json();self.item=data["items"][0]["id"];self.vault=data["vaults"][0]["id"]
        self.assertEqual(self.post(self.u,"/business/prices",{"item":self.item,"buy":20,"sell":35}).status_code,200)
    def post(self,c,p,d):return c.post("/highest/api"+p,json=d)
    def get(self,c,p):return c.get("/highest/api"+p)
    def grant(self,m,l):
        self.grant_rank(self.rank,m,l)
    def grant_rank(self,rank,m,l):
        self.assertEqual(self.post(self.a,"/admin/grants",{"rank":rank,"module":m,"level":l}).status_code,200)
    def set_discount_policy(self,scope="both",max_percent=100,max_fixed=1000000000000,rank=None):
        self.assertEqual(self.post(self.a,"/admin/discount-policies",{"rank":rank or self.rank,"scope":scope,"max_percent":max_percent,"max_fixed":max_fixed}).status_code,200)
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
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,200)
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,409)
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
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,403)
        self.assertEqual(self.post(self.u,"/business/prices",{"item":self.item,"buy":1,"sell":2}).status_code,403)
        self.grant("business","approve")
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,403)
        self.grant("inventory","write");self.grant("treasury","write")
        self.assertEqual(self.post(self.u,path,{"version":2,"status":"completed"}).status_code,200)
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


    def test_all_items_percentage_discount_flows_into_revenue_and_treasury(self):
        payload={"nonce":"all-percent-discount-12345","group_name":"Discount Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"treasury":True,"discount_scope":"all","discount_type":"percent","discount_value":10}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["subtotal"],order["discount_amount"],order["total"]),(105,11,94))
        self.assertEqual(order["lines"][0]["discount_amount"],11)
        self.assertEqual(order["estimated_margin"],34)
        self.advance(oid)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        ledger=self.get(self.u,"/ops/treasury").json()
        self.assertEqual(ledger["entries"][0]["amount"],94)
        analytics=self.get(self.u,"/business/analytics").json()["summary"]
        self.assertEqual((analytics["sales_revenue"],analytics["sales_discounts"],analytics["estimated_gross_profit"]),(94,11,34))

    def test_selected_item_fixed_discount_is_per_unit_and_snapshotted(self):
        self.post(self.u,"/ops/item",{"name":"Second RP Item","category":"IC"})
        items=self.get(self.u,"/ops/inventory").json()["items"]
        second=next(x["id"] for x in items if x["name"]=="Second RP Item")
        self.assertEqual(self.post(self.u,"/business/prices",{"item":second,"buy":10,"sell":20}).status_code,200)
        payload={"nonce":"selected-fixed-discount-12345","group_name":"Mixed Basket","direction":"sell","lines":[{"item":self.item,"qty":2,"discount_type":"fixed","discount_value":3},{"item":second,"qty":2}],"discount_scope":"items"}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["subtotal"],order["discount_amount"],order["total"]),(110,6,104))
        discounted=next(x for x in order["lines"] if x["item"]==self.item)
        untouched=next(x for x in order["lines"] if x["item"]==second)
        self.assertEqual((discounted["discount_type"],discounted["discount_value"],discounted["discount_amount"],discounted["total"]),("fixed",3,6,64))
        self.assertEqual((untouched["discount_amount"],untouched["total"]),(0,40))

    def test_all_items_nominal_discount_applies_to_purchase_total(self):
        payload={"nonce":"all-fixed-discount-12345","group_name":"Supplier Group","direction":"buy","lines":[{"item":self.item,"qty":3}],"treasury":True,"discount_scope":"all","discount_type":"fixed","discount_value":5}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["subtotal"],order["discount_amount"],order["total"]),(60,5,55))
        self.advance(oid)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        self.assertEqual(self.get(self.u,"/ops/treasury").json()["entries"][0]["amount"],-55)
        analytics=self.get(self.u,"/business/analytics").json()["summary"]
        self.assertEqual((analytics["purchase_spend"],analytics["purchase_discounts"]),(55,5))

    def test_discount_cannot_be_stacked_between_cart_and_item(self):
        payload={"nonce":"invalid-stack-discount-12345","group_name":"Bad Discount","direction":"sell","lines":[{"item":self.item,"qty":1,"discount_type":"fixed","discount_value":2}],"discount_scope":"all","discount_type":"percent","discount_value":10}
        self.assertEqual(self.post(self.u,"/business/orders",payload).status_code,400)
        payload["discount_scope"]="items"
        payload["discount_type"]="none"
        payload["discount_value"]=0
        payload["lines"][0]["discount_value"]=101
        payload["lines"][0]["discount_type"]="percent"
        self.assertEqual(self.post(self.u,"/business/orders",payload).status_code,400)


    def test_rank_discount_policy_direct_limit_and_manager_approval(self):
        self.set_discount_policy("all",10,1000)
        denied_scope={"nonce":"scope-denied-123456789","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":1,"discount_type":"percent","discount_value":5}],"discount_scope":"items"}
        self.assertEqual(self.post(self.u,"/business/orders",denied_scope).status_code,403)
        direct={"nonce":"direct-discount-12345678","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"percent","discount_value":5}
        direct_id=self.post(self.u,"/business/orders",direct).json()["id"]
        direct_order=self.get(self.u,f"/business/orders/{direct_id}").json()["order"]
        self.assertEqual((direct_order["discount_state"],direct_order["discount_amount"],direct_order["total"]),("approved",5,100))
        request={"nonce":"approval-discount-12345","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"percent","discount_value":20,"discount_reason":"Promotional price approved by business manager"}
        request_id=self.post(self.u,"/business/orders",request).json()["id"]
        pending=self.get(self.u,f"/business/orders/{request_id}").json()["order"]
        self.assertEqual((pending["discount_state"],pending["discount_amount"],pending["requested_discount_amount"],pending["total"]),("pending",0,21,105))
        self.assertEqual(self.post(self.u,f"/business/orders/{request_id}/status",{"version":1,"status":"ready"}).status_code,409)
        self.assertEqual(self.post(self.u,f"/business/orders/{request_id}/discount-review",{"approve":True,"note":"Approved for this order"}).status_code,403)
        queue=self.get(self.m,"/business/discount-requests").json()["requests"]
        self.assertTrue(any(x["id"]==request_id for x in queue))
        self.assertEqual(self.post(self.m,f"/business/orders/{request_id}/discount-review",{"approve":True,"note":"Approved for this order"}).status_code,200)
        approved=self.get(self.u,f"/business/orders/{request_id}").json()["order"]
        self.assertEqual((approved["discount_state"],approved["discount_amount"],approved["total"]),("approved",21,84))
        self.assertEqual(self.post(self.u,f"/business/orders/{request_id}/status",{"version":2,"status":"ready"}).status_code,200)

    def test_discount_rejection_removes_discount_but_keeps_order_usable(self):
        self.set_discount_policy("both",5,5)
        request={"nonce":"rejected-discount-123456","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"fixed","discount_value":20,"discount_reason":"Request a one-time promotion"}
        oid=self.post(self.u,"/business/orders",request).json()["id"]
        self.assertEqual(self.post(self.m,f"/business/orders/{oid}/discount-review",{"approve":False,"note":"Exceeds approved promotion budget"}).status_code,200)
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["discount_state"],order["discount_amount"],order["requested_discount_amount"],order["total"]),("rejected",0,20,105))
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"ready"}).status_code,200)

    def test_discount_requires_reason_and_policy_admin_is_protected(self):
        self.assertEqual(self.get(self.u,"/admin/discount-policies").status_code,403)
        self.set_discount_policy("all",5,5)
        payload={"nonce":"reason-required-123456","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"percent","discount_value":20}
        self.assertEqual(self.post(self.u,"/business/orders",payload).status_code,400)
        policies=self.get(self.a,"/admin/discount-policies").json()
        cashier=next(x for x in policies if x["rank_id"]==self.rank)
        self.assertEqual((cashier["scope"],cashier["max_percent"],cashier["max_fixed"]),("all",5,5))
