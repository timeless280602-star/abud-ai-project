"""Administrative records for fictional FiveM roleplay. Separate from community."""
import hashlib, json, os, re, uuid
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import Response
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

        CREATE TABLE IF NOT EXISTS hq_case_entity(
            id INTEGER PRIMARY KEY,
            case_id INTEGER NOT NULL REFERENCES hq_case(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('case','character','vehicle','organization','evidence')),
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            reference TEXT NOT NULL DEFAULT '',
            x REAL NOT NULL DEFAULT 500,
            y REAL NOT NULL DEFAULT 260,
            actor INTEGER REFERENCES users(id),
            created INTEGER NOT NULL,
            updated INTEGER NOT NULL,
            UNIQUE(case_id,entity_type,name)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS hq_case_root_entity ON hq_case_entity(case_id) WHERE entity_type='case';
        CREATE INDEX IF NOT EXISTS hq_case_entity_case ON hq_case_entity(case_id,entity_type,id);
        CREATE TABLE IF NOT EXISTS hq_case_entity_link(
            id INTEGER PRIMARY KEY,
            case_id INTEGER NOT NULL REFERENCES hq_case(id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES hq_case_entity(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES hq_case_entity(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            actor INTEGER REFERENCES users(id),
            created INTEGER NOT NULL,
            UNIQUE(case_id,source_id,target_id,label)
        );
        CREATE INDEX IF NOT EXISTS hq_case_entity_link_case ON hq_case_entity_link(case_id,id);
        CREATE TABLE IF NOT EXISTS hq_evidence_file(
            id INTEGER PRIMARY KEY,
            case_id INTEGER NOT NULL REFERENCES hq_case(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES hq_case_entity(id) ON DELETE RESTRICT,
            related_entity_id INTEGER REFERENCES hq_case_entity(id) ON DELETE RESTRICT,
            title TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('document','photo','other')),
            detail TEXT NOT NULL DEFAULT '',
            original_filename TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            content_type TEXT NOT NULL,
            size INTEGER NOT NULL CHECK(size>0),
            sha256 TEXT NOT NULL,
            actor INTEGER REFERENCES users(id),
            created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_evidence_case ON hq_evidence_file(case_id,id DESC);
        CREATE TABLE IF NOT EXISTS hq_evidence_event(
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES hq_evidence_file(id) ON DELETE RESTRICT,
            case_id INTEGER NOT NULL REFERENCES hq_case(id) ON DELETE RESTRICT,
            actor INTEGER REFERENCES users(id),
            action TEXT NOT NULL CHECK(action IN ('uploaded','previewed','downloaded','integrity_failed')),
            file_sha256 TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_evidence_event_file ON hq_evidence_event(file_id,id);
        """)
        for case in c.execute("SELECT * FROM hq_case").fetchall():
            case_name="TH-"+str(int(case["id"])).zfill(4)+" · "+case["title"]
            case_ref="TH-"+str(int(case["id"])).zfill(4)
            c.execute("""INSERT OR IGNORE INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                VALUES(?,'case',?,?,?,500,60,?,?,?)""",(case["id"],case_name,case["summary"],case_ref,case["actor"],case["created"],case["updated"]))
        for old in c.execute("SELECT * FROM hq_case_relation").fetchall():
            ids=[]
            for index,name in enumerate((old["left_name"],old["right_name"])):
                c.execute("""INSERT OR IGNORE INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                    VALUES(?,'character',?,'Migrated from an existing case relationship','',?,?,?, ?,?)""",
                    (old["case_id"],name,260+index*480,270,old["actor"],old["created"],old["created"]))
                node=c.execute("SELECT id FROM hq_case_entity WHERE case_id=? AND entity_type='character' AND name=?",(old["case_id"],name)).fetchone()
                ids.append(node["id"])
            c.execute("INSERT OR IGNORE INTO hq_case_entity_link(case_id,source_id,target_id,label,actor,created) VALUES(?,?,?,?,?,?)",
                (old["case_id"],ids[0],ids[1],old["label"],old["actor"],old["created"]))
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

class EntityNode(BaseModel):
    entity_type:str
    name:str=Field(min_length=1,max_length=100)
    description:str=Field(default="",max_length=2000)
    reference:str=Field(default="",max_length=200)
    x:float|None=Field(default=None,ge=0,le=1000)
    y:float|None=Field(default=None,ge=0,le=520)
class EntityLink(BaseModel):
    source_id:int
    target_id:int
    label:str=Field(min_length=1,max_length=120)
class NodePosition(BaseModel):
    x:float=Field(ge=0,le=1000)
    y:float=Field(ge=0,le=520)

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
        if p.status=="archived": privilege(c,r,module,"approve")
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

MAX_EVIDENCE_BYTES=15*1024*1024
EVIDENCE_TYPES={".pdf":"application/pdf",".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp"}
def evidence_root():
    default_db=os.getenv("HIGHEST_DATABASE_PATH",str(Path(os.getenv("ABUD_DATABASE_PATH","/app/data/abud_memory.db")).parent/"highest.db"))
    root=Path(os.getenv("HIGHEST_EVIDENCE_PATH",str(Path(default_db).parent/"highest_evidence"))).resolve()
    public_root=(Path(__file__).parent/"highest_web").resolve()
    if root==public_root or public_root in root.parents:
        fail(500,"Evidence storage must be outside public web assets")
    return root
def detect_evidence_type(data):
    if data.startswith(b"%PDF-"): return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if data.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if len(data)>=12 and data[:4]==b"RIFF" and data[8:12]==b"WEBP": return "image/webp"
    return None
def _event_hash(event_id,file_id,case_id,actor,action,file_sha256,previous_hash,created):
    payload=[event_id,file_id,case_id,actor,action,file_sha256,previous_hash,created]
    return hashlib.sha256(json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
def append_evidence_event(c,file_id,case_id,actor,action,file_sha256):
    last=c.execute("SELECT event_hash FROM hq_evidence_event WHERE file_id=? ORDER BY id DESC LIMIT 1",(file_id,)).fetchone()
    previous=last["event_hash"] if last else ""
    created=now()
    event_id=c.execute("""INSERT INTO hq_evidence_event(file_id,case_id,actor,action,file_sha256,previous_hash,event_hash,created)
        VALUES(?,?,?,?,?,?,?,?)""",(file_id,case_id,actor,action,file_sha256,previous,"",created)).lastrowid
    digest=_event_hash(event_id,file_id,case_id,actor,action,file_sha256,previous,created)
    c.execute("UPDATE hq_evidence_event SET event_hash=? WHERE id=?",(digest,event_id))
    return event_id
def verify_evidence_chain(events):
    previous=""
    for event in events:
        if event["previous_hash"]!=previous:
            return False
        expected=_event_hash(event["id"],event["file_id"],event["case_id"],event["actor"],event["action"],event["file_sha256"],event["previous_hash"],event["created"])
        if event["event_hash"]!=expected:
            return False
        previous=event["event_hash"]
    return True
def safe_original_filename(value,extension):
    value=(value or "evidence").replace("\\","/").split("/")[-1]
    value=re.sub(r"[\x00-\x1f\x7f]","",value).strip()
    return value[:180] or "evidence"+extension
def evidence_node_position(c,cid):
    count=c.execute("SELECT count(*) FROM hq_case_entity WHERE case_id=? AND entity_type<>'case'",(cid,)).fetchone()[0]
    return 130+(count%4)*240,190+min(count//4,2)*140
@router.get("/case-extras/{cid}")
def extras(cid:int,r:Request):
    with db() as c:
        privilege(c,r,"cases");check_case(c,cid)
        return reply({
            "evidence":rows(c,"SELECT * FROM hq_case_evidence WHERE case_id=? ORDER BY id",(cid,)),
            "relations":rows(c,"SELECT * FROM hq_case_relation WHERE case_id=? ORDER BY id",(cid,)),
            "files":rows(c,"""SELECT f.id,f.case_id,f.entity_id,f.related_entity_id,f.title,f.category,f.detail,
                f.original_filename,f.content_type,f.size,f.sha256,f.actor,f.created,
                coalesce(u.display_name,u.username) uploader,e.name entity_name,related.name related_name,
                (SELECT count(*) FROM hq_evidence_event ev WHERE ev.file_id=f.id) event_count
                FROM hq_evidence_file f LEFT JOIN users u ON u.id=f.actor
                JOIN hq_case_entity e ON e.id=f.entity_id
                LEFT JOIN hq_case_entity related ON related.id=f.related_entity_id
                WHERE f.case_id=? ORDER BY f.id DESC""",(cid,)),
            "nodes":rows(c,"SELECT * FROM hq_case_entity WHERE case_id=? ORDER BY CASE entity_type WHEN 'case' THEN 0 ELSE 1 END,id",(cid,)),
            "links":rows(c,"""SELECT l.*,s.name source_name,s.entity_type source_type,t.name target_name,t.entity_type target_type
                FROM hq_case_entity_link l JOIN hq_case_entity s ON s.id=l.source_id
                JOIN hq_case_entity t ON t.id=l.target_id WHERE l.case_id=? ORDER BY l.id""",(cid,))
        })

@router.post("/case-extras/{cid}/nodes")
def create_entity(cid:int,p:EntityNode,r:Request):
    origin(r)
    if p.entity_type not in ("character","vehicle","organization"): fail(400,"Choose a character, vehicle or organization node")
    name=clean(p.name,100)
    description=clean(p.description,2000,required=False)
    reference=clean(p.reference,200,required=False)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
        x,y=evidence_node_position(c,cid)
        if p.x is not None:x=p.x
        if p.y is not None:y=p.y
        try:
            node_id=c.execute("""INSERT INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(cid,p.entity_type,name,description,reference,x,y,u["id"],now(),now())).lastrowid
        except Exception as e:
            if "UNIQUE constraint failed" in str(e): fail(409,"This entity already exists in the case")
            raise
        audit(c,u["id"],"case.entity.create",node_id)
    return {"ok":True,"id":node_id}

@router.post("/case-extras/{cid}/links")
def create_entity_link(cid:int,p:EntityLink,r:Request):
    origin(r)
    label=clean(p.label,120)
    if p.source_id==p.target_id: fail(400,"An entity cannot be linked to itself")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
        source=c.execute("SELECT id FROM hq_case_entity WHERE id=? AND case_id=?",(p.source_id,cid)).fetchone()
        target=c.execute("SELECT id FROM hq_case_entity WHERE id=? AND case_id=?",(p.target_id,cid)).fetchone()
        if not source or not target: fail(404,"Both entities must belong to this case")
        if c.execute("SELECT 1 FROM hq_case_entity_link WHERE case_id=? AND source_id=? AND target_id=? AND label=?",(cid,p.source_id,p.target_id,label)).fetchone():
            fail(409,"This relationship already exists")
        link_id=c.execute("INSERT INTO hq_case_entity_link(case_id,source_id,target_id,label,actor,created) VALUES(?,?,?,?,?,?)",(cid,p.source_id,p.target_id,label,u["id"],now())).lastrowid
        audit(c,u["id"],"case.entity.link",link_id)
    return {"ok":True,"id":link_id}

@router.post("/case-extras/{cid}/nodes/{node_id}/position")
def move_entity(cid:int,node_id:int,p:NodePosition,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
        if not c.execute("UPDATE hq_case_entity SET x=?,y=?,updated=? WHERE id=? AND case_id=?",(p.x,p.y,now(),node_id,cid)).rowcount:
            fail(404,"Entity not found in this case")
        audit(c,u["id"],"case.entity.position",node_id)
    return {"ok":True}

@router.post("/case-extras/{cid}/files")
async def upload_case_evidence(cid:int,r:Request,file:UploadFile=File(...),title:str=Form(...),
    category:str=Form("document"),detail:str=Form(""),related_entity_id:str=Form("")):
    origin(r)
    title=clean(title,120)
    if category not in ("document","photo","other"): fail(400,"Invalid evidence category")
    detail=clean(detail,2000,required=False)
    related_id=None
    if related_entity_id.strip():
        try: related_id=int(related_entity_id)
        except ValueError: fail(400,"Invalid related entity")
    with db() as c:
        privilege(c,r,"cases","write");check_case(c,cid)
        if related_id is not None and not c.execute("SELECT 1 FROM hq_case_entity WHERE id=? AND case_id=? AND entity_type<>'case'",(related_id,cid)).fetchone():
            fail(404,"Related entity not found in this case")
    raw_name=(file.filename or "evidence").replace("\\","/").split("/")[-1]
    extension=Path(raw_name).suffix.lower()
    expected=EVIDENCE_TYPES.get(extension)
    if not expected: fail(400,"Only PDF, PNG, JPG and WEBP evidence files are accepted")
    if file.size is not None and file.size>MAX_EVIDENCE_BYTES:
        await file.close()
        fail(413,"Evidence files are limited to 15 MB")
    content=await file.read(MAX_EVIDENCE_BYTES+1)
    await file.close()
    if not content: fail(400,"Evidence file is empty")
    if len(content)>MAX_EVIDENCE_BYTES: fail(413,"Evidence files are limited to 15 MB")
    actual=detect_evidence_type(content)
    if actual!=expected: fail(400,"File extension does not match its actual content")
    original=safe_original_filename(raw_name,extension)
    sha=hashlib.sha256(content).hexdigest()
    stored=uuid.uuid4().hex+extension
    root=evidence_root()
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(root,0o700)
    target=(root/stored).resolve()
    if target.parent!=root.resolve(): fail(400,"Invalid evidence storage path")
    try:
        with target.open("xb") as output: output.write(content)
        os.chmod(target,0o600)
        with db() as c:
            c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"cases","write");check_case(c,cid)
            if related_id is not None and not c.execute("SELECT 1 FROM hq_case_entity WHERE id=? AND case_id=? AND entity_type<>'case'",(related_id,cid)).fetchone():
                fail(404,"Related entity not found in this case")
            x,y=evidence_node_position(c,cid)
            node_name=title
            if c.execute("SELECT 1 FROM hq_case_entity WHERE case_id=? AND entity_type='evidence' AND name=?",(cid,node_name)).fetchone():
                node_name=title[:86]+" · "+stored[:8]
            entity_id=c.execute("""INSERT INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                VALUES(?,'evidence',?,?,?,?,?,?,?,?)""",(cid,node_name,detail,"SHA-256 "+sha[:16],x,y,u["id"],now(),now())).lastrowid
            file_id=c.execute("""INSERT INTO hq_evidence_file(case_id,entity_id,related_entity_id,title,category,detail,original_filename,
                stored_name,content_type,size,sha256,actor,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid,entity_id,related_id,title,category,detail,original,stored,actual,len(content),sha,u["id"],now())).lastrowid
            if related_id is not None:
                c.execute("INSERT INTO hq_case_entity_link(case_id,source_id,target_id,label,actor,created) VALUES(?,?,?,'Evidence relates to',?,?)",
                    (cid,entity_id,related_id,u["id"],now()))
            append_evidence_event(c,file_id,cid,u["id"],"uploaded",sha)
            audit(c,u["id"],"case.evidence.upload",file_id)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"ok":True,"id":file_id,"entity_id":entity_id,"sha256":sha,"size":len(content)}

@router.get("/case-extras/evidence/{eid}/custody")
def evidence_custody(eid:int,r:Request):
    with db() as c:
        privilege(c,r,"cases")
        item=c.execute("SELECT id,case_id FROM hq_evidence_file WHERE id=?",(eid,)).fetchone()
        if not item: fail(404,"Evidence file not found")
        events=rows(c,"""SELECT e.*,coalesce(u.display_name,u.username,'Unknown account') actor_name
            FROM hq_evidence_event e LEFT JOIN users u ON u.id=e.actor WHERE e.file_id=? ORDER BY e.id""",(eid,))
        return reply({"events":events,"chain_valid":verify_evidence_chain(events)})

@router.get("/case-extras/evidence/{eid}/file")
def evidence_file(eid:int,r:Request,download:bool=False):
    issue=None;content=None;item=None;disposition="attachment"
    with db() as c:
        u=privilege(c,r,"cases")
        item=c.execute("SELECT * FROM hq_evidence_file WHERE id=?",(eid,)).fetchone()
        if not item: fail(404,"Evidence file not found")
        root=evidence_root().resolve()
        path=(root/item["stored_name"]).resolve()
        if path.parent!=root:
            issue="Evidence storage path is invalid"
        elif not path.is_file():
            issue="Evidence file is missing; access has been blocked"
        else:
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=item["sha256"]:
                issue="Evidence integrity check failed; access has been blocked"
        if issue:
            c.execute("BEGIN IMMEDIATE")
            append_evidence_event(c,eid,item["case_id"],u["id"],"integrity_failed",item["sha256"])
            audit(c,u["id"],"case.evidence.integrity_failed",eid)
        else:
            action="downloaded" if download or item["content_type"]=="application/pdf" else "previewed"
            c.execute("BEGIN IMMEDIATE")
            append_evidence_event(c,eid,item["case_id"],u["id"],action,item["sha256"])
            audit(c,u["id"],"case.evidence."+action,eid)
            disposition="attachment" if download or item["content_type"]=="application/pdf" else "inline"
    if issue: fail(409,issue)
    filename="evidence-"+str(eid)+Path(item["original_filename"]).suffix.lower()
    content_disposition=disposition+'; filename="'+filename+'"; filename*=UTF-8\'\''+quote(item["original_filename"])
    headers={
        "Content-Disposition":content_disposition,
        "X-Content-Type-Options":"nosniff","Cache-Control":"private, no-store",
        "Cross-Origin-Resource-Policy":"same-origin","Content-Security-Policy":"default-src 'none'; sandbox"
    }
    return Response(content=content,media_type=item["content_type"],headers=headers)

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
        created=now()
        rid=c.execute("INSERT INTO hq_case_relation(case_id,left_name,right_name,label,actor,created) VALUES(?,?,?,?,?,?)",(cid,left,right,clean(p.label,120),u["id"],created)).lastrowid
        node_ids=[]
        for index,name in enumerate((left,right)):
            c.execute("""INSERT OR IGNORE INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                VALUES(?,'character',?,'Migrated from a case relationship','',?,?,?, ?,?)""",(cid,name,260+index*480,270,u["id"],created,created))
            node=c.execute("SELECT id FROM hq_case_entity WHERE case_id=? AND entity_type='character' AND name=?",(cid,name)).fetchone()
            node_ids.append(node["id"])
        c.execute("INSERT OR IGNORE INTO hq_case_entity_link(case_id,source_id,target_id,label,actor,created) VALUES(?,?,?,?,?,?)",
            (cid,node_ids[0],node_ids[1],clean(p.label,120),u["id"],created))
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


@router.get("/case-intelligence/analytics")
def case_intelligence_analytics(r:Request):
    """Read-only aggregate intelligence across fictional IC case files."""
    with db() as c:
        privilege(c,r,"cases")
        case_totals=dict(c.execute("""SELECT count(*) total,
            coalesce(sum(status='open'),0) open,
            coalesce(sum(status='review'),0) review,
            coalesce(sum(status='closed'),0) closed
            FROM hq_case""").fetchone())
        graph=dict(c.execute("""SELECT
            count(*) total_nodes,
            coalesce(sum(entity_type='character'),0) characters,
            coalesce(sum(entity_type='vehicle'),0) vehicles,
            coalesce(sum(entity_type='organization'),0) organizations,
            coalesce(sum(entity_type='evidence'),0) evidence_nodes
            FROM hq_case_entity WHERE entity_type<>'case'""").fetchone())
        graph["relationships"]=c.execute("SELECT count(*) FROM hq_case_entity_link").fetchone()[0]
        graph["evidence_files"]=c.execute("SELECT count(*) FROM hq_evidence_file").fetchone()[0]
        graph["custody_events"]=c.execute("SELECT count(*) FROM hq_evidence_event").fetchone()[0]
        graph["integrity_failures"]=c.execute("SELECT count(*) FROM hq_evidence_event WHERE action='integrity_failed'").fetchone()[0]
        graph["case_linked_assets"]=c.execute("SELECT count(*) FROM hq_asset WHERE case_id IS NOT NULL").fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hq_asset'").fetchone() else 0

        recurring=rows(c,"""SELECT entity_type,lower(trim(name)) match_key,min(name) entity_name,
            count(DISTINCT case_id) case_count,count(*) node_count,
            group_concat(DISTINCT case_id) case_ids
            FROM hq_case_entity
            WHERE entity_type IN ('character','vehicle','organization')
                AND trim(name)<>''
            GROUP BY entity_type,lower(trim(name))
            HAVING count(DISTINCT case_id)>1
            ORDER BY case_count DESC,node_count DESC,entity_type,entity_name LIMIT 100""")
        for item in recurring:
            ids=[int(x) for x in (item.pop("case_ids") or "").split(",") if x]
            item["cases"]=rows(c,"SELECT id,title,status FROM hq_case WHERE id IN ("+",".join("?" for _ in ids)+") ORDER BY id",ids) if ids else []
            item["interpretation"]="Exact normalized name match across cases; this is a review lead, not proof of shared identity."

        central=rows(c,"""SELECT e.id entity_id,e.case_id,c.title case_title,e.entity_type,e.name,
            count(l.id) degree
            FROM hq_case_entity e JOIN hq_case c ON c.id=e.case_id
            LEFT JOIN hq_case_entity_link l ON l.case_id=e.case_id AND (l.source_id=e.id OR l.target_id=e.id)
            WHERE e.entity_type<>'case'
            GROUP BY e.id ORDER BY degree DESC,e.name LIMIT 30""")
        rel_labels=rows(c,"""SELECT label,count(*) relationship_count,
            count(DISTINCT case_id) case_count
            FROM hq_case_entity_link GROUP BY label
            ORDER BY relationship_count DESC,label LIMIT 30""")
        clusters=rows(c,"""SELECT a.case_id left_case_id,ca.title left_case,
            b.case_id right_case_id,cb.title right_case,
            a.entity_type,a.name matched_name
            FROM hq_case_entity a JOIN hq_case_entity b
              ON a.entity_type=b.entity_type AND lower(trim(a.name))=lower(trim(b.name))
             AND a.case_id<b.case_id
            JOIN hq_case ca ON ca.id=a.case_id
            JOIN hq_case cb ON cb.id=b.case_id
            WHERE a.entity_type IN ('character','vehicle','organization') AND trim(a.name)<>''
            GROUP BY a.case_id,b.case_id,a.entity_type,lower(trim(a.name))
            ORDER BY a.name LIMIT 100""")
        timeline=rows(c,"""SELECT day, sum(cases_opened) cases_opened,
            sum(case_updates) case_updates,sum(nodes_added) nodes_added,
            sum(relationships_added) relationships_added,sum(evidence_uploaded) evidence_uploaded,
            sum(custody_events) custody_events
            FROM (
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours') day,1 cases_opened,
                    0 case_updates,0 nodes_added,0 relationships_added,0 evidence_uploaded,0 custody_events
                    FROM hq_case
                UNION ALL
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours'),0,1,0,0,0,0 FROM hq_case_note
                UNION ALL
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours'),0,0,1,0,0,0
                    FROM hq_case_entity WHERE entity_type<>'case'
                UNION ALL
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours'),0,0,0,1,0,0 FROM hq_case_entity_link
                UNION ALL
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours'),0,0,0,0,1,0 FROM hq_evidence_file
                UNION ALL
                SELECT strftime('%Y-%m-%d',created,'unixepoch','+7 hours'),0,0,0,0,0,1 FROM hq_evidence_event
            ) activity GROUP BY day ORDER BY day DESC LIMIT 180""")
        busiest=rows(c,"""SELECT c.id case_id,c.title,c.status,c.created,c.updated,
            (SELECT count(*) FROM hq_case_entity e WHERE e.case_id=c.id AND e.entity_type<>'case') entity_count,
            (SELECT count(*) FROM hq_case_entity_link l WHERE l.case_id=c.id) relationship_count,
            (SELECT count(*) FROM hq_evidence_file f WHERE f.case_id=c.id) evidence_count,
            (SELECT count(*) FROM hq_case_note n WHERE n.case_id=c.id) update_count
            FROM hq_case c ORDER BY (entity_count+relationship_count+evidence_count+update_count) DESC,c.updated DESC LIMIT 20""")
        integrity_by_case=rows(c,"""SELECT c.id case_id,c.title,count(ev.id) integrity_failures
            FROM hq_case c JOIN hq_evidence_event ev ON ev.case_id=c.id AND ev.action='integrity_failed'
            GROUP BY c.id ORDER BY integrity_failures DESC,c.id""")
        return reply({
            "scope":"Fictional IC roleplay records only. Exact name matches are candidate overlaps and must be manually verified.",
            "cases":case_totals,"graph":graph,"recurring_entities":recurring,
            "most_connected_entities":central,"relationship_patterns":rel_labels,
            "candidate_case_overlaps":clusters,"activity_timeline":timeline,
            "most_active_cases":busiest,"recorded_integrity_failures_by_case":integrity_by_case,
            "generated_at":now()
        })
