import os,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
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
        self.grant_rank(self.manager_rank,"business","approve")
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
        self.post(self.u,"/ops/move",{"kind":"deposit","vault":self.vault,"item":self.item,"qty":5,"unit_cost":20,"note":"Test"})
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
        self.assertEqual(analytics["flow"]["valued_output"],60)
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
        payload={"nonce":"all-percent-discount-12345","group_name":"Discount Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"treasury":True,"discount_scope":"all","discount_type":"percent","discount_value":10,"discount_reason":"IC promotional pricing"}
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
        payload={"nonce":"selected-fixed-discount-12345","group_name":"Mixed Basket","direction":"sell","lines":[{"item":self.item,"qty":2,"discount_type":"fixed","discount_value":3},{"item":second,"qty":2}],"discount_scope":"items","discount_reason":"IC customer loyalty discount"}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((order["subtotal"],order["discount_amount"],order["total"]),(110,6,104))
        discounted=next(x for x in order["lines"] if x["item"]==self.item)
        untouched=next(x for x in order["lines"] if x["item"]==second)
        self.assertEqual((discounted["discount_type"],discounted["discount_value"],discounted["discount_amount"],discounted["total"]),("fixed",3,6,64))
        self.assertEqual((untouched["discount_amount"],untouched["total"]),(0,40))

    def test_all_items_nominal_discount_applies_to_purchase_total(self):
        payload={"nonce":"all-fixed-discount-12345","group_name":"Supplier Group","direction":"buy","lines":[{"item":self.item,"qty":3}],"treasury":True,"discount_scope":"all","discount_type":"fixed","discount_value":5,"discount_reason":"IC supplier volume discount"}
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
        direct={"nonce":"direct-discount-12345678","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"percent","discount_value":5,"discount_reason":"IC direct promotion"}
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


    def test_direct_discount_requires_reason_and_logs_actor(self):
        payload={"nonce":"direct-reason-required-123456","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":3}],"discount_scope":"all","discount_type":"percent","discount_value":5}
        self.assertEqual(self.post(self.u,"/business/orders",payload).status_code,400)
        payload["discount_reason"]="IC loyalty promotion"
        response=self.post(self.u,"/business/orders",payload)
        self.assertEqual(response.status_code,200,response.text)
        order=self.get(self.u,f"/business/orders/{response.json()['id']}").json()["order"]
        self.assertEqual(order["creator"],"cashier")
        self.assertEqual(order["discount_reason"],"IC loyalty promotion")


    def test_member_analytics_attributes_orders_to_creator_not_status_editor(self):
        self.post(self.u,"/business/orders",{"nonce":"member-created-sale-12345","group_name":"Member A Group","direction":"sell","lines":[{"item":self.item,"qty":2}]})
        self.post(self.m,"/business/orders",{"nonce":"member-created-buy-12345","group_name":"Member B Group","direction":"buy","lines":[{"item":self.item,"qty":1}]})
        cashier_id=self.get(self.u,"/me").json()["id"]
        oid=next(x["id"] for x in self.get(self.u,"/business/orders").json()["orders"] if x["actor"]==cashier_id and x["nonce"]=="member-created-sale-12345")
        self.advance(oid)
        self.assertEqual(self.post(self.m,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        analytics=self.get(self.u,"/business/analytics").json()
        member_u=next(x for x in analytics["members"] if x["actor"]==self.get(self.u,"/me").json()["id"])
        member_m=next(x for x in analytics["members"] if x["actor"]==self.get(self.m,"/me").json()["id"])
        self.assertEqual((member_u["transactions_created"],member_u["completed_orders_created"],member_u["sales_revenue"]),(1,1,70))
        self.assertEqual((member_m["transactions_created"],member_m["purchase_orders_created"],member_m["sales_revenue"]),(1,1,0))
        detail=self.get(self.u,f"/business/orders/{oid}").json()
        self.assertEqual(detail["order"]["creator"],"cashier")
        self.assertEqual(detail["history"][-1]["display_name"],"manager")

    def test_order_creator_cannot_be_overridden_by_request_payload(self):
        payload={"nonce":"immutable-creator-12345","group_name":"Member A Group","direction":"sell","lines":[{"item":self.item,"qty":1}],"actor":99999,"creator":"Forged User"}
        oid=self.post(self.u,"/business/orders",payload).json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual(order["actor"],self.get(self.u,"/me").json()["id"])
        self.assertEqual(order["creator"],"cashier")

    def test_invoice_is_issued_at_order_creation_and_receipt_at_completion(self):
        response=self.post(self.u,"/business/orders",{"nonce":"invoice-document-test-12345","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":2}]})
        self.assertEqual(response.status_code,200,response.text)
        oid=response.json()["id"]
        created=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertRegex(created["invoice_no"],r"^INV-\d{8}-\d{6}$")
        stylesheet=self.u.get("/highest/document.css")
        self.assertEqual(stylesheet.status_code,200)
        self.assertIn("size:A4",stylesheet.text)
        self.assertEqual(created["invoice_creator_name"],"cashier")
        self.assertIsNotNone(created["invoice_issued_at"])
        self.assertIsNone(created["receipt_no"])
        self.assertIsNone(created["receipt_issued_at"])
        second=self.post(self.u,"/business/orders",{"nonce":"invoice-document-test-67890","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":1}]}).json()["id"]
        second_order=self.get(self.u,f"/business/orders/{second}").json()["order"]
        self.assertNotEqual(created["invoice_no"],second_order["invoice_no"])
        self.advance(oid)
        self.assertEqual(self.post(self.m,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        completed=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertRegex(completed["receipt_no"],r"^RCT-\d{8}-\d{6}$")
        self.assertIsNotNone(completed["receipt_issued_at"])
        self.assertEqual(completed["receipt_completed_by"],"manager")
        self.assertEqual(completed["invoice_no"],created["invoice_no"])
        self.assertEqual(completed["invoice_creator_name"],"cashier")
        listed=next(x for x in self.get(self.u,"/business/orders").json()["orders"] if x["id"]==oid)
        self.assertEqual((listed["invoice_no"],listed["receipt_no"]),(completed["invoice_no"],completed["receipt_no"]))

    def test_completed_legacy_order_documents_are_backfilled(self):
        oid=self.post(self.u,"/business/orders",{"nonce":"legacy-document-backfill-12345","group_name":"IC Group","direction":"sell","lines":[{"item":self.item,"qty":1}]}).json()["id"]
        self.advance(oid)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        with sqlite3.connect(self.tmp.name+"/db.sqlite") as conn:
            conn.execute("DELETE FROM hq_order_documents WHERE order_id=?",(oid,))
        with patch("app.highest_business.now",return_value=1900000000):
            business_init()
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertTrue(order["invoice_no"].startswith("INV-"))
        self.assertTrue(order["receipt_no"].startswith("RCT-"))
        self.assertEqual(order["invoice_creator_name"],"cashier")
        self.assertEqual(order["receipt_completed_by"],"cashier")

    def test_business_profiles_are_admin_managed_and_snapshotted_per_order(self):
        self.assertEqual(self.get(self.u,"/admin/business-profiles").status_code,403)
        default=self.get(self.a,"/admin/business-profiles").json()["profiles"]
        self.assertEqual(len(default),1)
        self.assertEqual((default[0]["code"],default[0]["invoice_prefix"],default[0]["receipt_prefix"]),("HIGHEST","INV","RCT"))
        payload={
            "code":"NORTH","name":"North Division","description":"Northern business operations",
            "organization_name":"THE HIGHEST NORTH","contact_name":"North Desk",
            "contact_details":"IC Radio 01","logo_url":"https://cdn.example.com/north.png",
            "invoice_prefix":"NTH","receipt_prefix":"NRC","template":"executive",
            "accent_color":"#123456","footer":"North Division · Internal IC record",
            "active":True,"is_default":False
        }
        self.assertEqual(self.post(self.u,"/admin/business-profiles",payload).status_code,403)
        created=self.post(self.a,"/admin/business-profiles",payload)
        self.assertEqual(created.status_code,200,created.text)
        profile_id=created.json()["id"]
        available=self.get(self.u,"/business/orders").json()["profiles"]
        self.assertTrue(any(x["id"]==profile_id and x["name"]=="North Division" for x in available))
        order_payload={"nonce":"north-profile-order-123456","group_name":"North IC Group","direction":"sell",
            "lines":[{"item":self.item,"qty":2}],"business_profile_id":profile_id}
        created_order=self.post(self.u,"/business/orders",order_payload)
        self.assertEqual(created_order.status_code,200,created_order.text)
        oid=created_order.json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertTrue(order["invoice_no"].startswith("NTH-"))
        self.assertEqual((order["business_profile"]["name"],order["business_profile"]["organization_name"],
            order["business_profile"]["template"],order["business_profile"]["accent_color"]),
            ("North Division","THE HIGHEST NORTH","executive","#123456"))
        changed={**payload,"id":profile_id,"name":"North Division Renamed","invoice_prefix":"REN","receipt_prefix":"RCP",
            "accent_color":"#654321","footer":"Updated footer"}
        self.assertEqual(self.post(self.a,"/admin/business-profiles",changed).status_code,200)
        unchanged=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual((unchanged["business_profile"]["name"],unchanged["business_profile"]["invoice_prefix"],
            unchanged["business_profile"]["accent_color"]),("North Division","NTH","#123456"))
        self.assertTrue(unchanged["invoice_no"].startswith("NTH-"))
        self.advance(oid)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed"}).status_code,200)
        completed=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertTrue(completed["receipt_no"].startswith("NRC-"))
        self.assertEqual(completed["business_profile"]["name"],"North Division")

    def test_business_profile_validation_default_protection_and_inactive_selection(self):
        base={"code":"BAD","name":"Bad Profile","invoice_prefix":"BAD","receipt_prefix":"BAD",
            "template":"classic","accent_color":"#b58b4a","active":True,"is_default":False}
        for change in ({"logo_url":"http://example.com/logo.png"},{"accent_color":"red"},
            {"invoice_prefix":"BAD-1"},{"template":"unknown"}):
            self.assertIn(self.post(self.a,"/admin/business-profiles",{**base,**change}).status_code,(400,422))
        default=self.get(self.a,"/admin/business-profiles").json()["profiles"][0]
        deactivate={**default,"active":False,"is_default":False}
        self.assertEqual(self.post(self.a,"/admin/business-profiles",deactivate).status_code,409)
        inactive=self.post(self.a,"/admin/business-profiles",{**base,"code":"ARCHIVE","name":"Archived Unit","active":False})
        self.assertEqual(inactive.status_code,200,inactive.text)
        bad_order={"nonce":"inactive-profile-order-12345","group_name":"Test","direction":"sell",
            "lines":[{"item":self.item,"qty":1}],"business_profile_id":inactive.json()["id"]}
        self.assertEqual(self.post(self.u,"/business/orders",bad_order).status_code,400)

    def test_legacy_orders_receive_default_business_snapshot(self):
        oid=self.post(self.u,"/business/orders",{"nonce":"legacy-brand-snapshot-12345","group_name":"Legacy Group",
            "direction":"sell","lines":[{"item":self.item,"qty":1}]}).json()["id"]
        with sqlite3.connect(self.tmp.name+"/db.sqlite") as conn:
            conn.execute("DELETE FROM hq_order_business_snapshot WHERE order_id=?",(oid,))
            conn.execute("UPDATE hq_order SET business_profile_id=NULL WHERE id=?",(oid,))
        business_init()
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        self.assertEqual(order["business_profile"]["code"],"HIGHEST")
        self.assertEqual(order["business_profile"]["name"],"THE HIGHEST HQ")
        self.assertTrue(order["invoice_no"].startswith("INV-"))

    def test_document_center_search_archive_filters_and_pdf_download(self):
        created=self.create()
        self.assertEqual(created.status_code,200,created.text)
        oid=created.json()["id"]
        order=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        invoice=order["invoice_no"]
        issued=datetime.fromtimestamp(order["invoice_issued_at"],timezone(timedelta(hours=7)))
        period=issued.strftime("%Y-%m")
        day=issued.strftime("%Y-%m-%d")
        creator_id=self.get(self.u,"/me").json()["id"]
        profile_id=order["business_profile"]["profile_id"]
        center=self.get(self.u,"/business/documents")
        self.assertEqual(center.status_code,200,center.text)
        data=center.json()
        self.assertEqual((data["summary"]["document_count"],data["summary"]["invoice_count"],data["summary"]["receipt_count"]),(1,1,0))
        self.assertEqual(data["documents"][0]["document_number"],invoice)
        self.assertEqual(data["archive_periods"][0]["period"],period)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"q":invoice}).json()["total"],1)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"profile_id":profile_id}).json()["total"],1)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"creator_id":creator_id}).json()["total"],1)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"period":period}).json()["total"],1)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"from_date":day,"to_date":day}).json()["total"],1)
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"kind":"receipt"}).json()["total"],0)
        self.assertEqual(self.get(self.v,"/business/documents").status_code,403)
        invoice_pdf=self.u.get(f"/highest/api/business/documents/{oid}/invoice/pdf")
        self.assertEqual(invoice_pdf.status_code,200,invoice_pdf.content[:200])
        self.assertEqual(invoice_pdf.headers["content-type"],"application/pdf")
        self.assertTrue(invoice_pdf.content.startswith(b"%PDF-"))
        self.assertIn(invoice+".pdf",invoice_pdf.headers.get("content-disposition",""))
        self.advance(oid)
        self.assertEqual(self.post(self.u,"/ops/move",{"kind":"deposit","vault":self.vault,"item":self.item,"qty":3,"unit_cost":20,"note":"Document Center receipt test"}).status_code,200)
        self.assertEqual(self.post(self.u,f"/business/orders/{oid}/status",{"version":2,"status":"completed","note":"Completed for document archive test"}).status_code,200)
        completed=self.get(self.u,f"/business/orders/{oid}").json()["order"]
        receipt=completed["receipt_no"]
        self.assertTrue(receipt)
        archived=self.get(self.u,"/business/documents").json()
        self.assertEqual((archived["summary"]["document_count"],archived["summary"]["invoice_count"],archived["summary"]["receipt_count"]),(2,1,1))
        self.assertEqual(self.u.get("/highest/api/business/documents",params={"q":receipt,"kind":"receipt"}).json()["documents"][0]["document_number"],receipt)
        receipt_pdf=self.u.get(f"/highest/api/business/documents/{oid}/receipt/pdf")
        self.assertEqual(receipt_pdf.status_code,200,receipt_pdf.content[:200])
        self.assertTrue(receipt_pdf.content.startswith(b"%PDF-"))
        self.assertIn(receipt+".pdf",receipt_pdf.headers.get("content-disposition",""))

    def test_document_center_validates_filters_and_receipt_requires_completion(self):
        oid=self.create().json()["id"]
        self.assertEqual(self.get(self.u,"/business/documents?kind=unknown").status_code,400)
        self.assertEqual(self.get(self.u,"/business/documents?period=2026-13").status_code,400)
        self.assertEqual(self.get(self.u,"/business/documents?from_date=20-11-2026").status_code,400)
        self.assertEqual(self.get(self.u,"/business/documents?from_date=2026-11-21&to_date=2026-11-20").status_code,400)
        self.assertEqual(self.u.get(f"/highest/api/business/documents/{oid}/receipt/pdf").status_code,404)
        self.assertEqual(self.u.get(f"/highest/api/business/documents/{oid}/unknown/pdf").status_code,400)
