"""Administrative records for fictional FiveM roleplay. Separate from community."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.highest import db, origin, clean, fail, audit
from app.highest_ops import privilege, rows, reply, now

router=APIRouter(prefix="/highest/api")
RECORDS={
    "syndicates": ("active","inactive","archived"),
    "operations": ("planned","in_progress","completed","cancelled","archived"),
    "assets": ("available","assigned","maintenance","retired","archived"),
    "documents": ("draft","active","archived"),
}
def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_record(id INTEGER PRIMARY KEY,module TEXT NOT NULL,title TEXT NOT NULL,category TEXT NOT NULL,detail TEXT NOT NULL,owner TEXT NOT NULL,reference TEXT NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS hq_record_module ON hq_record(module,id);
        CREATE TABLE IF NOT EXISTS hq_revision(record_id INTEGER REFERENCES hq_record(id),version INTEGER,title TEXT NOT NULL,category TEXT NOT NULL,detail TEXT NOT NULL,owner TEXT NOT NULL,reference TEXT NOT NULL,status TEXT NOT NULL,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,PRIMARY KEY(record_id,version));
        CREATE TABLE IF NOT EXISTS hq_ack(record_id INTEGER REFERENCES hq_record(id),version INTEGER,uid INTEGER REFERENCES users(id),created INTEGER,PRIMARY KEY(record_id,version,uid));
        CREATE TABLE IF NOT EXISTS hq_case_evidence(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES hq_case(id),title TEXT NOT NULL,reference TEXT NOT NULL,detail TEXT NOT NULL,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_case_relation(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES hq_case(id),left_name TEXT NOT NULL,right_name TEXT NOT NULL,label TEXT NOT NULL,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL);
        """)
class Record(BaseModel):
    title:str=Field(min_length=1,max_length=120)
    category:str=Field(min_length=1,max_length=60)
    detail:str=Field(min_length=1,max_length=12000)
    owner:str=Field(default="",max_length=120)
    reference:str=Field(default="",max_length=200)
    status:str
    version:int|None=None
class Evidence(BaseModel):
    title:str=Field(min_length=1,max_length=120)
    reference:str=Field(min_length=1,max_length=500)
    detail:str=Field(default="",max_length=2000)
class Relation(BaseModel):
    left_name:str=Field(min_length=1,max_length=100)
    right_name:str=Field(min_length=1,max_length=100)
    label:str=Field(min_length=1,max_length=120)

def check_module(module):
    if module not in RECORDS: fail(404,"Unknown module")
def data(p,module):
    if p.status not in RECORDS[module]: fail(400,"Invalid status")
    return (clean(p.title,120),clean(p.category,60),clean(p.detail,12000),p.owner.strip(),p.reference.strip(),p.status)
def record(c,module,rid):
    row=c.execute("SELECT * FROM hq_record WHERE module=? AND id=?",(module,rid)).fetchone()
    if not row: fail(404,"Record unavailable")
    return row
def revision(c,rid,uid):
    c.execute("""INSERT INTO hq_revision(record_id,version,title,category,detail,owner,reference,status,actor,created)
       SELECT id,version,title,category,detail,owner,reference,status,?,? FROM hq_record WHERE id=?""",(uid,now(),rid))

@router.get("/records/{module}")
def list_records(module:str,r:Request):
    check_module(module)
    with db() as c:
        u=privilege(c,r,module)
        out=rows(c,"SELECT * FROM hq_record WHERE module=? ORDER BY updated DESC,id DESC LIMIT 300",(module,))
        if module=="documents":
            for row in out:
                row["acknowledged"]=bool(c.execute("SELECT 1 FROM hq_ack WHERE record_id=? AND version=? AND uid=?",(row["id"],row["version"],u["id"])).fetchone())
                row["ack_count"]=c.execute("SELECT count(*) FROM hq_ack WHERE record_id=? AND version=?",(row["id"],row["version"])).fetchone()[0]
        return reply(out)

@router.post("/records/{module}")
def create(module:str,p:Record,r:Request):
    check_module(module); origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,module,"write")
        rid=c.execute("INSERT INTO hq_record(module,title,category,detail,owner,reference,status,actor,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",(module,*data(p,module),u["id"],now(),now())).lastrowid
        revision(c,rid,u["id"]);audit(c,u["id"],module+".create",rid)
    return {"id":rid}

@router.get("/records/{module}/{rid}")
def details(module:str,rid:int,r:Request):
    check_module(module)
    with db() as c:
        privilege(c,r,module)
        row=record(c,module,rid)
        return reply({"record":dict(row),"revisions":rows(c,"SELECT version,title,category,detail,owner,reference,status,created FROM hq_revision WHERE record_id=? ORDER BY version DESC",(rid,))})

@router.post("/records/{module}/{rid}")
def update(module:str,rid:int,p:Record,r:Request):
    check_module(module);origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,module,"write")
        row=record(c,module,rid)
        if p.version!=row["version"]: fail(409,"Record changed; reload before editing")
        if p.status=="archived" or row["status"]=="archived": privilege(c,r,module,"approve")
        c.execute("UPDATE hq_record SET title=?,category=?,detail=?,owner=?,reference=?,status=?,version=version+1,actor=?,updated=? WHERE id=?",(*data(p,module),u["id"],now(),rid))
        revision(c,rid,u["id"]);audit(c,u["id"],module+".update",rid)
    return {"ok":True}

@router.post("/records/documents/{rid}/ack")
def acknowledge(rid:int,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"documents")
        row=record(c,"documents",rid)
        if row["status"]!="active": fail(409,"Document is not active")
        c.execute("INSERT OR IGNORE INTO hq_ack VALUES(?,?,?,?)",(rid,row["version"],u["id"],now()))
        audit(c,u["id"],"documents.ack",rid)
    return {"ok":True}

def check_case(c,cid):
    if not c.execute("SELECT 1 FROM hq_case WHERE id=?",(cid,)).fetchone():fail(404,"Case unavailable")
@router.get("/case-extras/{cid}")
def extras(cid:int,r:Request):
    with db() as c:
        privilege(c,r,"cases");check_case(c,cid)
        return reply({"evidence":rows(c,"SELECT * FROM hq_case_evidence WHERE case_id=? ORDER BY id",(cid,)),"relations":rows(c,"SELECT * FROM hq_case_relation WHERE case_id=? ORDER BY id",(cid,))})
@router.post("/case-extras/{cid}/evidence")
def evidence(cid:int,p:Evidence,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
        eid=c.execute("INSERT INTO hq_case_evidence(case_id,title,reference,detail,actor,created) VALUES(?,?,?,?,?,?)",(cid,clean(p.title,120),clean(p.reference,500),p.detail.strip(),u["id"],now())).lastrowid
        audit(c,u["id"],"case.evidence",eid)
    return {"ok":True}
@router.post("/case-extras/{cid}/relation")
def relation(cid:int,p:Relation,r:Request):
    origin(r)
    left=clean(p.left_name,100);right=clean(p.right_name,100)
    if left.casefold()==right.casefold():fail(400,"Use distinct fictional characters")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
        rid=c.execute("INSERT INTO hq_case_relation(case_id,left_name,right_name,label,actor,created) VALUES(?,?,?,?,?,?)",(cid,left,right,clean(p.label,120),u["id"],now())).lastrowid
        audit(c,u["id"],"case.relationship",rid)
    return {"ok":True}

@router.get("/approval-center")
def approval(r:Request):
    with db() as c:
        u=privilege(c,r)
        grants={x["module"]:x["level"] for x in c.execute("SELECT module,level FROM hq_grants WHERE rank_id=?",(u["rank"],))}
        result={"treasury":[],"membership":[],"clips":[],"community":{}}
        if grants.get("*")=="approve" or grants.get("treasury")=="approve":
            result["treasury"]=rows(c,"SELECT id,amount,category,note,actor,created FROM hq_money WHERE state='pending' AND actor<>? ORDER BY id",(u["id"],))
        if u["admin"]:
            result["membership"]=rows(c,"SELECT uid,character,requested FROM membership WHERE status='pending' ORDER BY uid")
            result["clips"]=rows(c,"SELECT id,title FROM clips WHERE state='pending' ORDER BY id")
            for kind,table,state in [("creators","hq_creator","status"),("moments","hq_moment","state"),("povs","hq_pov","state"),("wiki","hq_wiki","state"),("posts","hq_posts","state")]:
                result["community"][kind]=c.execute("SELECT count(*) FROM "+table+" WHERE "+state+"='pending'").fetchone()[0]
        return reply(result)
