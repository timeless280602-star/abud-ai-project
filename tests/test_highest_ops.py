import os,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin,db
from app.highest_ops import router as ops,init as ops_init,MODULES

class OpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"})
        self.env.start();self.addCleanup(self.env.stop)
        init();ops_init()
        app=FastAPI();app.include_router(router);app.include_router(ops);self.app=app
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
        move={"kind":"deposit","vault":a,"item":item,"qty":10,"unit_cost":10,"note":"Test"}
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
        inventory=self.get(self.u,"/ops/inventory").json()
        stock={(s["vault"],s["item"]):s["qty"] for s in inventory["stock"]}
        self.assertEqual(stock,{(a,item):2,(b,item):2,(a,out):2})
        valuation={(x["vault_id"],x["item_id"]):(x["qty"],x["value"]) for x in inventory["valuation"]}
        self.assertEqual(valuation[(a,item)],(2,20))
        self.assertEqual(valuation[(b,item)],(2,20))
        self.assertEqual(valuation[(a,out)],(2,60))
        transfers=[m for m in inventory["movements"] if m["kind"]=="transfer"]
        self.assertEqual(len(transfers),2)
        self.assertEqual(transfers[0]["ref"],transfers[1]["ref"])
        self.assertEqual({m["counterparty_vault_name"] for m in transfers},{"A","B"})

    def test_fifo_and_weighted_average_costing(self):
        self.grant("inventory")
        for name in ("FIFO Vault","WAC Vault"):
            self.assertEqual(self.post(self.u,"/ops/vault",{"name":name}).status_code,200)
        for name in ("FIFO Item","WAC Item"):
            self.assertEqual(self.post(self.u,"/ops/item",{"name":name,"category":"IC"}).status_code,200)
        data=self.get(self.u,"/ops/inventory").json()
        vaults={x["name"]:x["id"] for x in data["vaults"]}
        items={x["name"]:x["id"] for x in data["items"]}
        fifo_v=vaults["FIFO Vault"];wac_v=vaults["WAC Vault"]
        fifo_i=items["FIFO Item"];wac_i=items["WAC Item"]
        for qty,cost in ((10,10),(10,20)):
            self.assertEqual(self.post(self.u,"/ops/move",{"kind":"deposit","vault":fifo_v,"item":fifo_i,"qty":qty,"unit_cost":cost,"note":"FIFO receipt"}).status_code,200)
            self.assertEqual(self.post(self.u,"/ops/move",{"kind":"deposit","vault":wac_v,"item":wac_i,"qty":qty,"unit_cost":cost,"note":"WAC receipt"}).status_code,200)
        self.assertEqual(self.post(self.u,f"/ops/item/{wac_i}/costing",{"method":"weighted_average"}).status_code,200)
        self.assertEqual(self.post(self.u,"/ops/move",{"kind":"withdraw","vault":fifo_v,"item":fifo_i,"qty":15,"note":"FIFO issue"}).status_code,200)
        self.assertEqual(self.post(self.u,"/ops/move",{"kind":"withdraw","vault":wac_v,"item":wac_i,"qty":15,"note":"WAC issue"}).status_code,200)
        inventory=self.get(self.u,"/ops/inventory").json()
        fifo_issue=next(x for x in inventory["movements"] if x["kind"]=="withdraw" and x["vault"]==fifo_v)
        wac_issue=next(x for x in inventory["movements"] if x["kind"]=="withdraw" and x["vault"]==wac_v)
        self.assertEqual(fifo_issue["value"],200)
        self.assertEqual(wac_issue["value"],225)
        valuation={(x["vault_id"],x["item_id"]):(x["qty"],x["value"]) for x in inventory["valuation"]}
        self.assertEqual(valuation[(fifo_v,fifo_i)],(5,100))
        self.assertEqual(valuation[(wac_v,wac_i)],(5,75))


    def test_legacy_opening_stock_valuation(self):
        self.grant("inventory")
        self.post(self.u,"/ops/vault",{"name":"Legacy Vault"})
        self.post(self.u,"/ops/item",{"name":"Legacy Item","category":"IC"})
        data=self.get(self.u,"/ops/inventory").json()
        vault=data["vaults"][0]["id"];item=data["items"][0]["id"]
        with db() as c:
            c.execute("INSERT INTO hq_stock(vault,item,qty) VALUES(?,?,?)",(vault,item,4))
        inventory=self.get(self.u,"/ops/inventory").json()
        legacy=next(x for x in inventory["valuation"] if x["vault_id"]==vault and x["item_id"]==item)
        self.assertEqual((legacy["qty"],legacy["value"],legacy["unvalued_qty"]),(4,0,4))
        valued=self.post(self.u,"/ops/inventory/opening-valuation",{
            "vault":vault,"item":item,"unit_cost":25,"note":"Opening stock physical valuation"
        })
        self.assertEqual(valued.status_code,200,valued.text)
        self.assertEqual((valued.json()["qty"],valued.json()["value"]),(4,100))
        inventory=self.get(self.u,"/ops/inventory").json()
        row=next(x for x in inventory["valuation"] if x["vault_id"]==vault and x["item_id"]==item)
        self.assertEqual((row["qty"],row["value"],row["unvalued_qty"]),(4,100,0))
        self.assertEqual(self.post(self.u,"/ops/move",{
            "kind":"withdraw","vault":vault,"item":item,"qty":1,"note":"Test opening cost"
        }).status_code,200)
        movement=self.get(self.u,"/ops/inventory").json()["movements"][0]
        self.assertEqual((movement["kind"],movement["value"]),( "withdraw",25))

    def test_cases(self):
        self.grant("cases","view")
        self.assertEqual(self.post(self.u,"/ops/cases",{"name":"Case","summary":"IC"}).status_code,403)
        self.grant("cases","write")
        cid=self.post(self.u,"/ops/cases",{"name":"Case","summary":"IC"}).json()["id"]
        self.assertEqual(self.post(self.u,f"/ops/cases/{cid}",{"note":"Update","status":"closed"}).status_code,200)
        self.assertEqual(self.get(self.u,f"/ops/cases/{cid}").json()["case"]["status"],"closed")

    def test_all_access(self):
        self.grant("treasury","view")
        self.assertEqual(self.post(self.u,"/admin/grants",{"rank":self.rank,"module":"*","level":"approve"}).status_code,403)
        self.assertEqual(self.post(self.a,"/admin/grants",{"rank":self.rank,"module":"*","level":"write"}).status_code,400)
        self.grant("*","approve")
        rights=self.get(self.u,"/ops/access").json()
        self.assertEqual(rights,dict.fromkeys(MODULES,"approve"))
        self.assertEqual(self.get(self.u,"/ops/cases").status_code,200)
        self.assertEqual(self.get(self.u,"/admin/grants").status_code,403)
        self.grant("*","none")
        self.assertEqual(self.get(self.u,"/ops/access").json(),{"treasury":"view"})
        self.assertEqual(self.get(self.u,"/ops/cases").status_code,403)
        self.grant("*","approve")
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/revoke/{uid}",{}).status_code,200)
        self.assertEqual(self.get(self.u,"/ops/treasury").status_code,403)

    def test_operations_calendar_persistence_filters_and_history(self):
        self.assertEqual(self.get(self.u,"/ops/calendar").status_code,403)
        self.grant("operations","view")
        self.assertEqual(self.get(self.u,"/ops/calendar").status_code,200)
        payload={
            "title":"HQ briefing","category":"Briefing","division":"Operations",
            "detail":"Review planned activities","owner":"Officer One","location":"HQ Internal",
            "starts_at":"2026-11-21T09:00","ends_at":"2026-11-21T10:00",
            "status":"planned","reminder_minutes":15
        }
        self.assertEqual(self.post(self.u,"/ops/calendar",payload).status_code,403)
        self.grant("operations","write")
        created=self.post(self.u,"/ops/calendar",payload)
        self.assertEqual(created.status_code,200)
        event_id=created.json()["id"]
        result=self.get(self.u,"/ops/calendar?division=Operations&status=planned")
        self.assertEqual(len(result.json()["events"]),1)
        self.assertTrue(result.json()["events"][0]["starts_at"].endswith("+07:00"))
        invalid={**payload,"ends_at":"2026-11-21T08:00"}
        self.assertEqual(self.u.put(self.path+"/ops/calendar/"+str(event_id),json=invalid).status_code,400)
        changed={**payload,"title":"Updated HQ briefing","status":"in_progress"}
        self.assertEqual(self.u.put(self.path+"/ops/calendar/"+str(event_id),json=changed).status_code,200)
        history=self.get(self.u,"/ops/calendar/"+str(event_id)+"/history").json()
        self.assertEqual([x["version"] for x in history],[2,1])
        self.assertEqual(history[0]["title"],"Updated HQ briefing")
        # Members sharing the same rank inherit the same module grant.
        reviewer_id=self.get(self.v,"/me").json()["id"]
        self.assertEqual(self.get(self.v,"/ops/calendar/"+str(event_id)+"/history").status_code,200)
        self.assertEqual(self.post(self.a,f"/admin/revoke/{reviewer_id}",{}).status_code,200)
        self.assertEqual(self.get(self.v,"/ops/calendar/"+str(event_id)+"/history").status_code,403)

    def test_full_approval_workflow_routes_delegation_and_history(self):
        self.assertEqual(self.post(self.u,"/ops/approvals",{
            "module":"cases","title":"Case review","description":"Approve case brief"
        }).status_code,403)
        self.grant("cases","write")
        self.assertEqual(self.get(self.u,"/ops/approvals").status_code,200)
        self.assertEqual(self.post(self.u,"/ops/approvals",{
            "module":"cases","title":"Case review","description":"Approve case brief"
        }).status_code,200)

        # Configure two distinct approval ranks; both must hold cases:approve.
        self.grant("cases","approve")
        self.assertEqual(self.post(self.a,"/admin/rank",{"name":"Command","position":2}).status_code,200)
        ranks=self.get(self.a,"/admin").json()["ranks"]
        second_rank=next(x["id"] for x in ranks if x["name"]=="Command")
        self.assertEqual(self.post(self.a,"/admin/rank",{"name":"Liaison","position":1}).status_code,200)
        ranks=self.get(self.a,"/admin").json()["ranks"]
        delegate_rank=next(x["id"] for x in ranks if x["name"]=="Liaison")
        self.assertEqual(self.post(self.a,"/admin/grants",{
            "module":"cases","rank":second_rank,"level":"approve"
        }).status_code,200)
        self.assertEqual(self.post(self.a,"/admin/grants",{
            "module":"cases","rank":delegate_rank,"level":"approve"
        }).status_code,200)

        def new_member(name,rank_id):
            client=TestClient(self.app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"})
            self.assertEqual(self.post(client,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
            self.assertEqual(self.post(client,"/apply",{"character":name}).status_code,200)
            uid=self.get(client,"/me").json()["id"]
            self.assertEqual(self.post(self.a,f"/admin/review/{uid}",{
                "approve":True,"rank":rank_id,"position":"Officer"
            }).status_code,200)
            return client,uid

        first_reviewer,first_uid=new_member("firstreviewer",self.rank)
        delegate,delegate_uid=new_member("delegate",delegate_rank)
        second_reviewer,second_uid=new_member("secondreviewer",second_rank)
        self.assertEqual(self.post(self.a,"/admin/approval-policies",{
            "module":"cases","ranks":[self.rank,second_rank]
        }).status_code,200)

        submitted=self.post(self.u,"/ops/approvals",{
            "module":"cases","reference_type":"case","reference_id":"CASE-7",
            "title":"Approve case file","description":"Two-step approval",
            "payload":{"classification":"internal"}
        })
        self.assertEqual(submitted.status_code,200)
        request_id=submitted.json()["id"]
        self.assertEqual(self.post(self.u,f"/ops/approvals/{request_id}/review",{
            "approve":True,"note":"Self approval must fail"
        }).status_code,403)
        self.assertEqual(self.post(second_reviewer,f"/ops/approvals/{request_id}/review",{
            "approve":True,"note":"Wrong step"
        }).status_code,403)

        self.assertEqual(self.post(first_reviewer,"/ops/approvals/delegations",{
            "module":"cases","delegate_user_id":delegate_uid,"active":True
        }).status_code,200)
        self.assertEqual(self.post(delegate,f"/ops/approvals/{request_id}/review",{
            "approve":True,"note":"Delegated first step"
        }).status_code,200)
        mine=self.get(self.u,"/ops/approvals?scope=mine").json()
        self.assertEqual(next(x for x in mine if x["id"]==request_id)["current_step"],2)
        self.assertEqual(self.post(delegate,f"/ops/approvals/{request_id}/review",{
            "approve":True
        }).status_code,403)
        self.assertEqual(self.post(second_reviewer,f"/ops/approvals/{request_id}/review",{
            "approve":True,"note":"Final approval"
        }).status_code,200)
        history=self.get(self.u,f"/ops/approvals/{request_id}/history").json()
        self.assertEqual(history["request"]["status"],"approved")
        self.assertEqual([a["step"] for a in history["actions"]],[1,2])
        self.assertEqual(history["actions"][0]["delegated_from"],first_uid)

        rejected=self.post(self.u,"/ops/approvals",{
            "module":"cases","title":"Reject test","description":"Should be rejected"
        }).json()["id"]
        self.assertEqual(self.post(first_reviewer,f"/ops/approvals/{rejected}/review",{
            "approve":False,"note":"Insufficient evidence"
        }).status_code,200)
        self.assertEqual(self.get(self.u,f"/ops/approvals/{rejected}/history").json()["request"]["status"],"rejected")

        cancelled=self.post(self.u,"/ops/approvals",{
            "module":"cases","title":"Cancel test","description":"Requester may cancel"
        }).json()["id"]
        self.assertEqual(self.post(self.u,f"/ops/approvals/{cancelled}/cancel",{}).status_code,200)
        self.assertEqual(self.get(self.u,f"/ops/approvals/{cancelled}/history").json()["request"]["status"],"cancelled")
