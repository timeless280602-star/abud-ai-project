import os,tempfile,unittest,hashlib
from pathlib import Path
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
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_EVIDENCE_PATH":self.tmp.name+"/evidence","HIGHEST_ORIGIN":"https://abud.web.id"});self.env.start();self.addCleanup(self.env.stop)
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

    def test_evidence_upload_hash_custody_integrity_and_access(self):
        self.grant("cases","write")
        cid=self.post(self.u,"/ops/cases",{"name":"Evidence Case","summary":"Fictional investigation"}).json()["id"]
        graph=self.get(self.u,f"/case-extras/{cid}").json()
        root=next(n for n in graph["nodes"] if n["entity_type"]=="case")
        self.assertIn("TH-",root["name"])
        person=self.post(self.u,f"/case-extras/{cid}/nodes",{"entity_type":"character","name":"Alex Morgan","description":"Fictional character","reference":"CID-01"}).json()["id"]
        vehicle=self.post(self.u,f"/case-extras/{cid}/nodes",{"entity_type":"vehicle","name":"Black Sultan","description":"Fictional vehicle"}).json()["id"]
        link=self.post(self.u,f"/case-extras/{cid}/links",{"source_id":person,"target_id":vehicle,"label":"Frequently seen driving"})
        self.assertEqual(link.status_code,200,link.text)
        self.assertEqual(self.post(self.u,f"/case-extras/{cid}/links",{"source_id":person,"target_id":person,"label":"Self link"}).status_code,400)
        self.assertEqual(self.post(self.u,f"/case-extras/{cid}/nodes/{person}/position",{"x":420,"y":310}).status_code,200)
        moved=self.get(self.u,f"/case-extras/{cid}").json()
        self.assertEqual(next(n for n in moved["nodes"] if n["id"]==person)["x"],420)
        self.assertEqual(len(moved["links"]),1)
        self.assertEqual(self.get(self.v,f"/case-extras/{cid}").status_code,403)
        pdf=b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
        upload=self.u.post(f"/highest/api/case-extras/{cid}/files",
            data={"title":"Interview record","category":"document","detail":"Fictional interview evidence","related_entity_id":str(person)},
            files={"file":("interview.pdf",pdf,"application/pdf")})
        self.assertEqual(upload.status_code,200,upload.text)
        evidence=upload.json()
        self.assertEqual(evidence["sha256"],hashlib.sha256(pdf).hexdigest())
        self.assertEqual(self.v.get(f"/highest/api/case-extras/evidence/{evidence['id']}/file").status_code,403)
        data=self.get(self.u,f"/case-extras/{cid}").json()
        self.assertEqual(len(data["files"]),1)
        self.assertEqual(data["files"][0]["related_name"],"Alex Morgan")
        self.assertEqual(next(n for n in data["nodes"] if n["id"]==evidence["entity_id"])["entity_type"],"evidence")
        self.assertTrue(any(x["source_id"]==evidence["entity_id"] and x["target_id"]==person for x in data["links"]))
        download=self.u.get(f"/highest/api/case-extras/evidence/{evidence['id']}/file?download=true")
        self.assertEqual(download.status_code,200)
        self.assertEqual(download.content,pdf)
        self.assertIn("attachment",download.headers["content-disposition"])
        self.assertEqual(download.headers["x-content-type-options"],"nosniff")
        custody=self.get(self.u,f"/case-extras/evidence/{evidence['id']}/custody").json()
        self.assertTrue(custody["chain_valid"])
        self.assertEqual([x["action"] for x in custody["events"]],["uploaded","downloaded"])
        self.assertTrue(all(len(x["event_hash"])==64 for x in custody["events"]))
        self.assertEqual(self.u.post(f"/highest/api/case-extras/{cid}/files",
            data={"title":"Bad extension","category":"document"},
            files={"file":("not-a-pdf.pdf",b"not a PDF","application/pdf")}).status_code,400)
        from app.highest import db
        with db() as c:
            stored=c.execute("SELECT stored_name FROM hq_evidence_file WHERE id=?",(evidence["id"],)).fetchone()["stored_name"]
        (Path(self.tmp.name)/"evidence"/stored).write_bytes(b"tampered")
        blocked=self.u.get(f"/highest/api/case-extras/evidence/{evidence['id']}/file")
        self.assertEqual(blocked.status_code,409)
        final_custody=self.get(self.u,f"/case-extras/evidence/{evidence['id']}/custody").json()
        self.assertTrue(final_custody["chain_valid"])
        self.assertEqual(final_custody["events"][-1]["action"],"integrity_failed")

    def test_graph_rejects_cross_case_links_and_preserves_legacy_relations(self):
        self.grant("cases","write")
        first=self.post(self.u,"/ops/cases",{"name":"First case","summary":"IC"}).json()["id"]
        second=self.post(self.u,"/ops/cases",{"name":"Second case","summary":"IC"}).json()["id"]
        a=self.post(self.u,f"/case-extras/{first}/nodes",{"entity_type":"character","name":"Character One"}).json()["id"]
        b=self.post(self.u,f"/case-extras/{second}/nodes",{"entity_type":"character","name":"Character Two"}).json()["id"]
        self.assertEqual(self.post(self.u,f"/case-extras/{first}/links",{"source_id":a,"target_id":b,"label":"Cross case"}).status_code,404)
        self.assertEqual(self.post(self.u,f"/case-extras/{first}/links",{"source_id":a,"target_id":a,"label":"Self"}).status_code,400)
        self.assertEqual(self.post(self.u,f"/case-extras/{first}/relation",{"left_name":"Old Character A","right_name":"Old Character B","label":"Legacy alliance"}).status_code,200)
        graph=self.get(self.u,f"/case-extras/{first}").json()
        self.assertTrue(any(x["label"]=="Legacy alliance" for x in graph["links"]))
        self.assertEqual(self.post(self.u,f"/case-extras/{first}/nodes",{"entity_type":"case","name":"Forged case root"}).status_code,400)
