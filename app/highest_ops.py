"""Transactional IC ledger, warehouse, crafting and case files for FiveM."""
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.highest import db, origin, digest, cookie, fail, clean, audit, current

router=APIRouter(prefix="/highest/api")
MODULES=("treasury","inventory","crafting","cases","syndicates","operations","assets","documents","business","business_prices","business_analytics","business_discounts")

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_grants(rank_id INTEGER REFERENCES ranks(id) ON DELETE CASCADE,module TEXT,level TEXT CHECK(level IN ('view','write','approve')),PRIMARY KEY(rank_id,module));
        CREATE TABLE IF NOT EXISTS hq_money(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),amount INTEGER NOT NULL,category TEXT NOT NULL,note TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','posted','rejected')),reviewer INTEGER REFERENCES users(id),created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_vault(id INTEGER PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_item(id INTEGER PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE NOT NULL,category TEXT NOT NULL,min_stock INTEGER NOT NULL CHECK(min_stock>=0));
        CREATE TABLE IF NOT EXISTS hq_stock(vault INTEGER REFERENCES hq_vault(id),item INTEGER REFERENCES hq_item(id),qty INTEGER NOT NULL CHECK(qty>=0),PRIMARY KEY(vault,item));
        CREATE TABLE IF NOT EXISTS hq_movement(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),kind TEXT NOT NULL,vault INTEGER REFERENCES hq_vault(id),item INTEGER REFERENCES hq_item(id),delta INTEGER NOT NULL,after_qty INTEGER NOT NULL,note TEXT NOT NULL,ref TEXT NOT NULL,unit_price INTEGER,value INTEGER,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_cost_layer(id INTEGER PRIMARY KEY,vault INTEGER NOT NULL REFERENCES hq_vault(id),item INTEGER NOT NULL REFERENCES hq_item(id),qty_remaining INTEGER NOT NULL CHECK(qty_remaining>=0),value_remaining INTEGER NOT NULL CHECK(value_remaining>=0),source TEXT NOT NULL,reference TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS hq_cost_layer_fifo ON hq_cost_layer(vault,item,created,id);

        CREATE TABLE IF NOT EXISTS hq_recipe(id INTEGER PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE NOT NULL,output INTEGER REFERENCES hq_item(id),output_qty INTEGER NOT NULL CHECK(output_qty>0));
        CREATE TABLE IF NOT EXISTS hq_ingredient(recipe INTEGER REFERENCES hq_recipe(id),item INTEGER REFERENCES hq_item(id),qty INTEGER NOT NULL CHECK(qty>0),PRIMARY KEY(recipe,item));
        CREATE TABLE IF NOT EXISTS hq_batch(id INTEGER PRIMARY KEY,recipe INTEGER REFERENCES hq_recipe(id),vault INTEGER REFERENCES hq_vault(id),actor INTEGER REFERENCES users(id),batches INTEGER NOT NULL,created INTEGER NOT NULL,note TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_case(id INTEGER PRIMARY KEY,title TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_case_note(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES hq_case(id),actor INTEGER REFERENCES users(id),note TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_operation_event(
            id INTEGER PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,division TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',owner TEXT NOT NULL DEFAULT '',location TEXT NOT NULL DEFAULT '',
            starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('planned','in_progress','completed','cancelled','archived')),
            reminder_minutes INTEGER NOT NULL DEFAULT 0 CHECK(reminder_minutes IN (0,5,15,30,60,1440)),
            version INTEGER NOT NULL DEFAULT 1,actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,updated INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_operation_event_dates ON hq_operation_event(starts_at,ends_at,status);
        CREATE TABLE IF NOT EXISTS hq_operation_revision(
            event_id INTEGER REFERENCES hq_operation_event(id) ON DELETE CASCADE,version INTEGER,title TEXT NOT NULL,
            category TEXT NOT NULL,division TEXT NOT NULL,detail TEXT NOT NULL,owner TEXT NOT NULL,location TEXT NOT NULL,
            starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,status TEXT NOT NULL,reminder_minutes INTEGER NOT NULL,
            actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,PRIMARY KEY(event_id,version)
        );

        CREATE TABLE IF NOT EXISTS hq_approval_policy(module TEXT NOT NULL,step INTEGER NOT NULL CHECK(step>0),rank_id INTEGER NOT NULL REFERENCES ranks(id) ON DELETE CASCADE,PRIMARY KEY(module,step));
        CREATE TABLE IF NOT EXISTS hq_approval_request(id INTEGER PRIMARY KEY,module TEXT NOT NULL,reference_type TEXT NOT NULL DEFAULT '',reference_id TEXT NOT NULL DEFAULT '',title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',payload TEXT NOT NULL DEFAULT '{}',requester INTEGER NOT NULL REFERENCES users(id),status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),current_step INTEGER NOT NULL DEFAULT 1,total_steps INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS hq_approval_queue ON hq_approval_request(status,module,current_step,created);
        CREATE TABLE IF NOT EXISTS hq_approval_request_step(request_id INTEGER NOT NULL REFERENCES hq_approval_request(id) ON DELETE CASCADE,step INTEGER NOT NULL,rank_id INTEGER NOT NULL REFERENCES ranks(id),PRIMARY KEY(request_id,step));
        CREATE TABLE IF NOT EXISTS hq_approval_action(id INTEGER PRIMARY KEY,request_id INTEGER NOT NULL REFERENCES hq_approval_request(id) ON DELETE CASCADE,step INTEGER NOT NULL,actor INTEGER NOT NULL REFERENCES users(id),delegated_from INTEGER REFERENCES users(id),decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL,UNIQUE(request_id,step));
        CREATE TABLE IF NOT EXISTS hq_approval_delegation(id INTEGER PRIMARY KEY,module TEXT NOT NULL,delegator INTEGER NOT NULL REFERENCES users(id),delegate INTEGER NOT NULL REFERENCES users(id),active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(module,delegator,delegate));
        CREATE TABLE IF NOT EXISTS hq_notification(
            id INTEGER PRIMARY KEY,uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',href TEXT NOT NULL DEFAULT '',
            dedupe_key TEXT NOT NULL,created INTEGER NOT NULL,read_at INTEGER,
            UNIQUE(uid,dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS hq_notification_inbox ON hq_notification(uid,read_at,created DESC);
        CREATE TABLE IF NOT EXISTS hq_notification_dispatch(
            event_id INTEGER NOT NULL REFERENCES hq_operation_event(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            dispatched_at INTEGER NOT NULL,PRIMARY KEY(event_id,version,uid)
        );        """)
        item_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_item)")}
        if "costing_method" not in item_columns: c.execute("ALTER TABLE hq_item ADD COLUMN costing_method TEXT NOT NULL DEFAULT 'fifo'")
        movement_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_movement)")}
        if "unit_price" not in movement_columns: c.execute("ALTER TABLE hq_movement ADD COLUMN unit_price INTEGER")
        if "value" not in movement_columns: c.execute("ALTER TABLE hq_movement ADD COLUMN value INTEGER")
        if "counterparty_vault" not in movement_columns: c.execute("ALTER TABLE hq_movement ADD COLUMN counterparty_vault INTEGER REFERENCES hq_vault(id)")
        if "cost_method" not in movement_columns: c.execute("ALTER TABLE hq_movement ADD COLUMN cost_method TEXT")
        if "cost_source" not in movement_columns: c.execute("ALTER TABLE hq_movement ADD COLUMN cost_source TEXT NOT NULL DEFAULT 'unvalued'")


def notify(c,uid,kind,title,body='',href='',dedupe_key=None):
    if not uid: return False
    key=dedupe_key or f"{kind}:{hashlib.sha256((title+'|'+body+'|'+href).encode()).hexdigest()}"
    cur=c.execute("""INSERT OR IGNORE INTO hq_notification(uid,kind,title,body,href,dedupe_key,created)
        VALUES(?,?,?,?,?,?,?)""",(uid,kind,clean(title,160),clean(body,1000,required=False),clean(href,240,required=False),key,now()))
    return cur.rowcount==1

def _notify_approval_step(c,request_id,step):
    item=c.execute("SELECT module,requester,title FROM hq_approval_request WHERE id=?",(request_id,)).fetchone()
    if not item: return
    configured=c.execute("SELECT rank_id FROM hq_approval_request_step WHERE request_id=? AND step=?",(request_id,step)).fetchone()
    if configured:
        candidates=rows(c,"""SELECT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module=? OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND m.rank=? AND u.id<>?""",(item["module"],configured["rank_id"],item["requester"]))
        delegated=rows(c,"""SELECT DISTINCT du.id FROM hq_approval_delegation d
            JOIN users du ON du.id=d.delegate JOIN membership dm ON dm.uid=du.id
            JOIN users ou ON ou.id=d.delegator JOIN membership om ON om.uid=ou.id
            JOIN hq_grants dg ON dg.rank_id=dm.rank AND (dg.module=d.module OR dg.module='*') AND dg.level='approve'
            JOIN hq_grants og ON og.rank_id=om.rank AND (og.module=d.module OR og.module='*') AND og.level='approve'
            WHERE d.module=? AND d.active=1 AND dm.status='approved' AND om.status='approved'
              AND om.rank=? AND dm.rank=? AND du.id<>?""",(item["module"],configured["rank_id"],configured["rank_id"],item["requester"]))
        candidates.extend(delegated)
    else:
        candidates=rows(c,"""SELECT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module=? OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(item["module"],item["requester"]))
    for target in {x["id"] for x in candidates}:
        notify(c,target,"approval_review","Approval requires your review",
            f"{item['title']} · {item['module']} · step {step}",
            "/highest/internal/","approval:"+str(request_id)+":step:"+str(step)+":user:"+str(target))

def now(): return int(time.time())
def rows(c,sql,args=()): return [dict(x) for x in c.execute(sql,args)]
def reply(data): return JSONResponse(data,headers={"Cache-Control":"no-store"})
def privilege(c,r,module=None,level="view",admin=False):
    token=r.cookies.get(cookie,"")
    u=c.execute("""SELECT u.id,u.admin,m.rank,m.status FROM users u JOIN sessions s ON s.uid=u.id LEFT JOIN membership m ON m.uid=u.id WHERE s.token=? AND s.expires>?""",(digest(token),now())).fetchone()
    if not u: fail(401,"Sign in first")
    if admin:
        if not u["admin"]: fail(403,"Administrator required")
        return u
    if u["status"]!="approved" or u["rank"] is None: fail(403,"Membership approval required")
    if module:
        allowed=c.execute("SELECT level FROM hq_grants WHERE rank_id=? AND (module=? OR module='*') ORDER BY CASE module WHEN '*' THEN 0 ELSE 1 END",(u["rank"],module)).fetchone()
        levels={"view":1,"write":2,"approve":3}
        if not allowed or levels[allowed["level"]]<levels[level]: fail(403,"Module permission required")
    return u

class Grant(BaseModel):
    rank:int
    module:str
    level:str
class Money(BaseModel):
    amount:int=Field(gt=0,le=1000000000000)
    direction:str
    category:str=Field(min_length=1,max_length=60)
    note:str=Field(min_length=1,max_length=500)
class Decision(BaseModel):
    approve:bool
class ApprovalSubmission(BaseModel):
    module:str
    reference_type:str=Field(default='',max_length=80)
    reference_id:str=Field(default='',max_length=120)
    title:str=Field(min_length=3,max_length=160)
    description:str=Field(default='',max_length=4000)
    payload:dict=Field(default_factory=dict)
class ApprovalDecision(BaseModel):
    approve:bool
    note:str=Field(default='',max_length=1000)
class ApprovalPolicy(BaseModel):
    module:str
    ranks:list[int]=Field(min_length=1,max_length=8)
class ApprovalDelegation(BaseModel):
    module:str
    delegate_user_id:int
    active:bool=True
class Name(BaseModel):
    name:str=Field(min_length=1,max_length=80)
class Item(Name):
    category:str=Field(min_length=1,max_length=60)
    min_stock:int=Field(default=0,ge=0,le=1000000000)
class Movement(BaseModel):
    kind:str
    vault:int
    item:int
    qty:int=Field(gt=0,le=1000000000)
    destination:int|None=None
    unit_cost:int|None=Field(default=None,ge=0,le=1000000000)
    note:str=Field(min_length=1,max_length=500)
class CostingMethod(BaseModel):
    method:str
class StockAdjustment(BaseModel):
    vault:int
    item:int
    counted_qty:int=Field(ge=0,le=1000000000000)
    unit_cost:int|None=Field(default=None,ge=0,le=1000000000)
    note:str=Field(min_length=1,max_length=500)
class OpeningValuation(BaseModel):
    vault:int
    item:int
    unit_cost:int=Field(ge=0,le=1000000000)
    note:str=Field(min_length=1,max_length=500)
class Ingredient(BaseModel):
    item:int
    qty:int=Field(gt=0,le=1000000)
class Recipe(Name):
    output:int
    output_qty:int=Field(gt=0,le=1000000)
    ingredients:list[Ingredient]=Field(min_length=1,max_length=30)
class Batch(BaseModel):
    recipe:int
    vault:int
    batches:int=Field(gt=0,le=1000)
    note:str=Field(min_length=1,max_length=500)
class Case(Name):
    summary:str=Field(min_length=1,max_length=4000)
class CaseNote(BaseModel):
    note:str=Field(min_length=1,max_length=4000)
    status:str|None=None

@router.get("/notifications")
def notification_inbox(r:Request,limit:int=50):
    if limit<1 or limit>100: fail(400,"Invalid notification limit")
    with db() as c:
        u=privilege(c,r)
        unread=c.execute("SELECT count(*) FROM hq_notification WHERE uid=? AND read_at IS NULL",(u["id"],)).fetchone()[0]
        items=rows(c,"SELECT id,kind,title,body,href,created,read_at FROM hq_notification WHERE uid=? ORDER BY created DESC,id DESC LIMIT ?",(u["id"],limit))
        return reply({"items":items,"unread_count":unread})

@router.post("/notifications/{notification_id}/read")
def notification_read(notification_id:int,r:Request):
    origin(r)
    with db() as c:
        u=privilege(c,r)
        cur=c.execute("UPDATE hq_notification SET read_at=? WHERE id=? AND uid=? AND read_at IS NULL",(now(),notification_id,u["id"]))
        if cur.rowcount==0 and not c.execute("SELECT 1 FROM hq_notification WHERE id=? AND uid=?",(notification_id,u["id"])).fetchone(): fail(404,"Notification not found")
    return {"ok":True}

@router.post("/notifications/read-all")
def notification_read_all(r:Request):
    origin(r)
    with db() as c:
        u=privilege(c,r)
        c.execute("UPDATE hq_notification SET read_at=? WHERE uid=? AND read_at IS NULL",(now(),u["id"]))
    return {"ok":True}

@router.get("/ops/access")
def access(r:Request):
    with db() as c:
        u=privilege(c,r)
        configured={x["module"]:x["level"] for x in c.execute("SELECT module,level FROM hq_grants WHERE rank_id=?",(u["rank"],))}
        if configured.get("*")=="approve": return reply(dict.fromkeys(MODULES,"approve"))
        return reply({k:v for k,v in configured.items() if k in MODULES})

@router.get("/admin/grants")
def grants(r:Request):
    with db() as c:
        privilege(c,r,admin=True)
        return reply(rows(c,"SELECT * FROM hq_grants ORDER BY rank_id,module"))

@router.post("/admin/grants")
def grant(p:Grant,r:Request):
    origin(r)
    if p.module=="*":
        if p.level not in ("none","approve"): fail(400,"All Access must be enabled or disabled")
    elif p.module not in MODULES or p.level not in ("none","view","write","approve"): fail(400,"Invalid grant")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,admin=True)
        if not c.execute("SELECT 1 FROM ranks WHERE id=?",(p.rank,)).fetchone(): fail(404,"Rank not found")
        if p.level=="none": c.execute("DELETE FROM hq_grants WHERE rank_id=? AND module=?",(p.rank,p.module))
        else: c.execute("INSERT INTO hq_grants VALUES(?,?,?) ON CONFLICT(rank_id,module) DO UPDATE SET level=excluded.level",(p.rank,p.module,p.level))
        audit(c,u["id"],"grant."+p.module+"."+p.level,p.rank)
    return {"ok":True}

def balance(c): return c.execute("SELECT coalesce(sum(amount),0) FROM hq_money WHERE state='posted'").fetchone()[0]

@router.get("/ops/treasury")
def treasury(r:Request):
    with db() as c:
        privilege(c,r,"treasury")
        return reply({"balance":balance(c),"entries":rows(c,"SELECT m.*,u.username FROM hq_money m JOIN users u ON u.id=m.actor ORDER BY m.id DESC LIMIT 300")})

@router.post("/ops/treasury")
def money(p:Money,r:Request):
    origin(r)
    if p.direction not in ("income","expense"): fail(400,"Invalid direction")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","write")
        amount=p.amount if p.direction=="income" else -p.amount
        mid=c.execute("INSERT INTO hq_money(actor,amount,category,note,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],amount,clean(p.category,60),clean(p.note,500),now())).lastrowid
        reviewers=rows(c,"""SELECT DISTINCT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module='treasury' OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(u["id"],))
        for target in reviewers:
            notify(c,target["id"],"treasury_review","Treasury transaction awaits review",
                clean(p.category,60)+" · "+str(abs(amount))+" · "+clean(p.note,500),
                "/highest/internal/","treasury:"+str(mid)+":review:"+str(target["id"]))
        audit(c,u["id"],"money.request",mid)
    return {"ok":True,"id":mid}

@router.post("/ops/treasury/{mid}/review")
def money_review(mid:int,p:Decision,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","approve")
        row=c.execute("SELECT * FROM hq_money WHERE id=? AND state='pending'",(mid,)).fetchone()
        if not row: fail(409,"No pending transaction")
        if row["actor"]==u["id"]: fail(403,"Cannot approve or reject own submission")
        if p.approve and balance(c)+row["amount"]<0: fail(409,"Insufficient treasury balance")
        state="posted" if p.approve else "rejected"
        c.execute("UPDATE hq_money SET state=?,reviewer=? WHERE id=?",(state,u["id"],mid))
        notify(c,row["actor"],"treasury_decision","Treasury transaction "+state,
            row["category"]+" · "+str(abs(row["amount"])),"/highest/internal/","treasury:"+str(mid)+":decision:"+state)
        audit(c,u["id"],"money."+state,mid)
    return {"ok":True}

def catalog(c):
    return {"vaults":rows(c,"SELECT * FROM hq_vault ORDER BY name"),"items":rows(c,"SELECT * FROM hq_item ORDER BY name")}

@router.post("/ops/vault")
def vault(p:Name,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"inventory","write")
        if c.execute("SELECT 1 FROM hq_vault WHERE name=?",(p.name.strip(),)).fetchone(): fail(409,"Vault exists")
        vid=c.execute("INSERT INTO hq_vault(name) VALUES(?)",(clean(p.name,80),)).lastrowid
        audit(c,u["id"],"vault.create",vid)
    return {"ok":True}

@router.post("/ops/item")
def item(p:Item,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"inventory","write")
        if c.execute("SELECT 1 FROM hq_item WHERE name=?",(p.name.strip(),)).fetchone(): fail(409,"Item exists")
        iid=c.execute("INSERT INTO hq_item(name,category,min_stock) VALUES(?,?,?)",(clean(p.name,80),clean(p.category,60),p.min_stock)).lastrowid
        audit(c,u["id"],"item.create",iid)
    return {"ok":True}

def _item_method(c,item):
    row=c.execute("SELECT costing_method FROM hq_item WHERE id=?",(item,)).fetchone()
    if not row: fail(404,"Item not found")
    return row["costing_method"] if row["costing_method"] in ("fifo","weighted_average") else "fifo"

def _ensure_cost_layers(c,vault=None,item=None):
    sql="""SELECT s.vault,s.item,s.qty-coalesce(l.layer_qty,0) missing
        FROM hq_stock s LEFT JOIN (
            SELECT vault,item,sum(qty_remaining) layer_qty FROM hq_cost_layer GROUP BY vault,item
        ) l ON l.vault=s.vault AND l.item=s.item
        WHERE s.qty>coalesce(l.layer_qty,0)"""
    args=()
    if vault is not None: sql+=" AND s.vault=?";args+=(vault,)
    if item is not None: sql+=" AND s.item=?";args+=(item,)
    for row in c.execute(sql,args).fetchall():
        c.execute("""INSERT INTO hq_cost_layer(vault,item,qty_remaining,value_remaining,source,reference,created)
            VALUES(?,?,?,0,'legacy_unvalued','opening-migration',?)""",(row["vault"],row["item"],row["missing"],now()))

def _active_layers(c,vault,item):
    return rows(c,"SELECT * FROM hq_cost_layer WHERE vault=? AND item=? AND qty_remaining>0 ORDER BY created,id",(vault,item))

def _layer_cost_source(slices):
    sources={x["source"] for x in slices if x["qty"]>0}
    unknown={"legacy_unvalued","unvalued","mixed_unvalued"}
    if sources & unknown: return "mixed_unvalued" if len(sources)>1 or "mixed_unvalued" in sources else next(iter(sources))
    return next(iter(sources)) if len(sources)==1 else ("mixed" if sources else "unvalued")

def _receive_cost(c,vault,item,qty,total_value,source,ref,method=None):
    method=method or _item_method(c,item)
    if method=="weighted_average":
        active=_active_layers(c,vault,item)
        total_qty=sum(x["qty_remaining"] for x in active)+qty
        value=sum(x["value_remaining"] for x in active)+total_value
        unknown_sources=("legacy_unvalued","unvalued","mixed_unvalued")
        active_unknown=any(x["source"] in unknown_sources for x in active)
        incoming_unknown=source in unknown_sources
        if active and active_unknown!=incoming_unknown:
            fail(409,"Revalue legacy opening stock before mixing it with costed weighted-average stock")
        layer_source=source if not active else ("mixed_unvalued" if incoming_unknown else ("weighted_average_pool" if any(x["source"]!=source for x in active) else source))
        if active:
            keep=active[0]["id"]
            c.execute("UPDATE hq_cost_layer SET qty_remaining=?,value_remaining=?,source=?,reference=?,created=? WHERE id=?",
                (total_qty,value,layer_source,ref,now(),keep))
            for old in active[1:]:
                c.execute("UPDATE hq_cost_layer SET qty_remaining=0,value_remaining=0 WHERE id=?",(old["id"],))
        else:
            c.execute("INSERT INTO hq_cost_layer(vault,item,qty_remaining,value_remaining,source,reference,created) VALUES(?,?,?,?,?,?,?)",
                (vault,item,total_qty,value,layer_source,ref,now()))
    else:
        c.execute("INSERT INTO hq_cost_layer(vault,item,qty_remaining,value_remaining,source,reference,created) VALUES(?,?,?,?,?,?,?)",
            (vault,item,qty,total_value,source,ref,now()))

def _consume_cost(c,vault,item,qty,ref):
    _ensure_cost_layers(c,vault,item)
    layers=_active_layers(c,vault,item)
    available=sum(x["qty_remaining"] for x in layers)
    if available<qty: fail(409,"Stock costing layers are incomplete; reconcile opening stock before withdrawal")
    method=_item_method(c,item)
    if method=="weighted_average":
        total_qty=sum(x["qty_remaining"] for x in layers)
        total_value=sum(x["value_remaining"] for x in layers)
        unit_value=(total_value+total_qty//2)//total_qty if total_qty else 0
        take_value=total_value if qty==total_qty else (total_value*qty+total_qty//2)//total_qty
        source=_layer_cost_source([{"source":x["source"],"qty":x["qty_remaining"]} for x in layers])
        keep=layers[0]["id"]
        c.execute("UPDATE hq_cost_layer SET qty_remaining=?,value_remaining=? WHERE id=?",(total_qty-qty,total_value-take_value,keep))
        for old in layers[1:]: c.execute("UPDATE hq_cost_layer SET qty_remaining=0,value_remaining=0 WHERE id=?",(old["id"],))
        return take_value,[{"qty":qty,"value":take_value,"source":source,"unit_cost":unit_value}]
    remaining=qty;total=0;slices=[]
    for layer in layers:
        if remaining<=0: break
        take=min(remaining,layer["qty_remaining"])
        take_value=layer["value_remaining"] if take==layer["qty_remaining"] else (layer["value_remaining"]*take+layer["qty_remaining"]//2)//layer["qty_remaining"]
        c.execute("UPDATE hq_cost_layer SET qty_remaining=?,value_remaining=? WHERE id=?",
            (layer["qty_remaining"]-take,layer["value_remaining"]-take_value,layer["id"]))
        slices.append({"qty":take,"value":take_value,"source":layer["source"],"unit_cost":(take_value+take//2)//take})
        total+=take_value;remaining-=take
    return total,slices

def _cost_summary(c):
    _ensure_cost_layers(c)
    return rows(c,"""SELECT v.id vault_id,v.name vault_name,i.id item_id,i.name item_name,i.costing_method,
        coalesce(sum(l.qty_remaining),0) qty,coalesce(sum(l.value_remaining),0) value,
        CASE WHEN coalesce(sum(l.qty_remaining),0)>0 THEN round(sum(l.value_remaining)*1.0/sum(l.qty_remaining),2) ELSE 0 END average_unit_cost,
        coalesce(sum(CASE WHEN l.source IN ('legacy_unvalued','unvalued','mixed_unvalued') THEN l.qty_remaining ELSE 0 END),0) unvalued_qty
        FROM hq_vault v CROSS JOIN hq_item i LEFT JOIN hq_cost_layer l ON l.vault=v.id AND l.item=i.id AND l.qty_remaining>0
        LEFT JOIN hq_stock st ON st.vault=v.id AND st.item=i.id
        WHERE coalesce(st.qty,0)>0 OR coalesce(i.min_stock,0)>0
        GROUP BY v.id,i.id ORDER BY v.name,i.name""")

def change(c,uid,kind,vault,item,delta,note,ref,unit_price=None,movement_value=None,counterparty_vault=None,cost_slices=None):
    if not c.execute("SELECT 1 FROM hq_vault WHERE id=?",(vault,)).fetchone() or not c.execute("SELECT 1 FROM hq_item WHERE id=?",(item,)).fetchone(): fail(404,"Vault or item not found")
    row=c.execute("SELECT qty FROM hq_stock WHERE vault=? AND item=?",(vault,item)).fetchone()
    qty=(row["qty"] if row else 0)+delta
    if qty<0: fail(409,"Insufficient stock")
    if qty>1000000000000: fail(409,"Stock limit exceeded")
    method=_item_method(c,item);total_value=0;slices=[]
    if delta<0:
        total_value,slices=_consume_cost(c,vault,item,-delta,ref)
        unit_price=(total_value+(-delta)//2)//(-delta)
        cost_source=_layer_cost_source(slices)
    elif delta>0:
        if cost_slices is not None:
            slices=cost_slices
            total_value=sum(x["value"] for x in slices)
            for part in slices: _receive_cost(c,vault,item,part["qty"],part["value"],part["source"],ref,method)
            cost_source=_layer_cost_source(slices)
        else:
            if movement_value is not None: total_value=movement_value
            elif unit_price is not None: total_value=delta*unit_price
            else: total_value=0
            cost_source="unvalued" if unit_price is None and movement_value is None else ("business_purchase_snapshot" if kind=="business_buy" else ("production_conversion" if kind=="craft_output" else "recorded_unit_cost"))
            _receive_cost(c,vault,item,delta,total_value,cost_source,ref,method)
        unit_price=(total_value+delta//2)//delta
    else:
        cost_source="no_quantity_change"
    c.execute("INSERT INTO hq_stock VALUES(?,?,?) ON CONFLICT(vault,item) DO UPDATE SET qty=excluded.qty",(vault,item,qty))
    c.execute("""INSERT INTO hq_movement(actor,kind,vault,item,delta,after_qty,note,ref,unit_price,value,created,counterparty_vault,cost_method,cost_source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid,kind,vault,item,delta,qty,note,ref,unit_price,total_value,now(),counterparty_vault,method,cost_source))
    return {"value":total_value,"unit_cost":unit_price,"cost_source":cost_source,"slices":slices}

@router.get("/ops/inventory")
def inventory(r:Request):
    with db() as c:
        privilege(c,r,"inventory")
        _ensure_cost_layers(c)
        return reply({**catalog(c),
            "stock":rows(c,"SELECT s.*,v.name vault_name,i.name item_name,i.costing_method FROM hq_stock s JOIN hq_vault v ON v.id=s.vault JOIN hq_item i ON i.id=s.item ORDER BY v.name,i.name"),
            "movements":rows(c,"""SELECT m.*,v.name vault_name,i.name item_name,u.username,cv.name counterparty_vault_name
                FROM hq_movement m JOIN hq_vault v ON v.id=m.vault JOIN hq_item i ON i.id=m.item
                JOIN users u ON u.id=m.actor LEFT JOIN hq_vault cv ON cv.id=m.counterparty_vault
                ORDER BY m.id DESC LIMIT 500"""),
            "low":rows(c,"SELECT i.id,i.name,i.min_stock,coalesce(sum(s.qty),0) total FROM hq_item i LEFT JOIN hq_stock s ON s.item=i.id GROUP BY i.id HAVING total<i.min_stock"),
            "valuation":_cost_summary(c),
            "cost_layers":rows(c,"""SELECT l.*,v.name vault_name,i.name item_name FROM hq_cost_layer l
                JOIN hq_vault v ON v.id=l.vault JOIN hq_item i ON i.id=l.item
                WHERE l.qty_remaining>0 ORDER BY l.created DESC,l.id DESC LIMIT 500""")})

@router.post("/ops/item/{iid}/costing")
def item_costing(iid:int,p:CostingMethod,r:Request):
    origin(r)
    if p.method not in ("fifo","weighted_average"): fail(400,"Use fifo or weighted_average")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"inventory","write")
        if not c.execute("SELECT 1 FROM hq_item WHERE id=?",(iid,)).fetchone(): fail(404,"Item not found")
        _ensure_cost_layers(c,item=iid)
        if p.method=="weighted_average":
            for vault_row in c.execute("SELECT id FROM hq_vault").fetchall():
                layers=_active_layers(c,vault_row["id"],iid)
                if len(layers)>1:
                    qty=sum(x["qty_remaining"] for x in layers);value=sum(x["value_remaining"] for x in layers)
                    source=_layer_cost_source([{"source":x["source"],"qty":x["qty_remaining"]} for x in layers])
                    keep=layers[0]["id"]
                    c.execute("UPDATE hq_cost_layer SET qty_remaining=?,value_remaining=?,source=?,created=? WHERE id=?",(qty,value,source,now(),keep))
                    for old in layers[1:]: c.execute("UPDATE hq_cost_layer SET qty_remaining=0,value_remaining=0 WHERE id=?",(old["id"],))
        c.execute("UPDATE hq_item SET costing_method=? WHERE id=?",(p.method,iid))
        audit(c,u["id"],"inventory.costing_method",iid)
    return {"ok":True,"method":p.method}

@router.post("/ops/inventory/opening-valuation")
def opening_valuation(p:OpeningValuation,r:Request):
    import secrets
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"inventory","write")
        _ensure_cost_layers(c,p.vault,p.item)
        stock=c.execute("SELECT qty FROM hq_stock WHERE vault=? AND item=?",(p.vault,p.item)).fetchone()
        if not stock: fail(404,"No stock balance found for this stash and item")
        layers=c.execute("SELECT * FROM hq_cost_layer WHERE vault=? AND item=? AND qty_remaining>0 AND source IN ('legacy_unvalued','unvalued','mixed_unvalued') ORDER BY created,id",(p.vault,p.item)).fetchall()
        if not layers: fail(409,"There is no unvalued opening stock to revalue")
        total_qty=sum(x["qty_remaining"] for x in layers);total_value=total_qty*p.unit_cost
        for layer in layers:
            c.execute("UPDATE hq_cost_layer SET value_remaining=?,source='opening_valuation',reference=?,created=? WHERE id=?",
                (layer["qty_remaining"]*p.unit_cost,"opening:"+secrets.token_hex(8),now(),layer["id"]))
        ref=secrets.token_hex(12);method=_item_method(c,p.item)
        c.execute("""INSERT INTO hq_movement(actor,kind,vault,item,delta,after_qty,note,ref,unit_price,value,created,cost_method,cost_source)
            VALUES(?,'opening_valuation',?,?,0,?,?,?,?,?,?,?,'opening_valuation')""",
            (u["id"],p.vault,p.item,stock["qty"],clean(p.note,500),ref,p.unit_cost,total_value,now(),method))
        audit(c,u["id"],"stock.opening_valuation",p.item)
    return {"ok":True,"reference":ref,"qty":total_qty,"value":total_value}

@router.post("/ops/inventory/adjust")
def stock_adjust(p:StockAdjustment,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"inventory","write")
        _ensure_cost_layers(c,p.vault,p.item)
        row=c.execute("SELECT qty FROM hq_stock WHERE vault=? AND item=?",(p.vault,p.item)).fetchone()
        if not c.execute("SELECT 1 FROM hq_vault WHERE id=?",(p.vault,)).fetchone() or not c.execute("SELECT 1 FROM hq_item WHERE id=?",(p.item,)).fetchone(): fail(404,"Vault or item not found")
        current_qty=row["qty"] if row else 0
        delta=p.counted_qty-current_qty
        if delta>0 and p.unit_cost is None: fail(400,"Unit cost is required for a positive stock adjustment")
        if delta==0: return {"ok":True,"delta":0}
        import secrets
        ref=secrets.token_hex(12)
        result=change(c,u["id"],"stock_adjustment",p.vault,p.item,delta,clean(p.note,500),ref,unit_price=p.unit_cost if delta>0 else None)
        audit(c,u["id"],"stock.adjust",p.item)
    return {"ok":True,"reference":ref,"delta":delta,"value":result["value"]}

@router.post("/ops/move")
def move(p:Movement,r:Request):
    import secrets
    origin(r)
    if p.kind not in ("deposit","withdraw","transfer"): fail(400,"Invalid movement")
    if p.kind=="transfer" and (p.destination is None or p.destination==p.vault): fail(400,"Different destination required")
    if p.kind=="deposit" and p.unit_cost is None: fail(400,"Unit cost is required for deposits")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"inventory","write")
        ref=secrets.token_hex(12);note=clean(p.note,500)
        if p.kind=="transfer":
            src=c.execute("SELECT name FROM hq_vault WHERE id=?",(p.vault,)).fetchone()
            dst=c.execute("SELECT name FROM hq_vault WHERE id=?",(p.destination,)).fetchone()
            if not src or not dst: fail(404,"Vault not found")
            result=change(c,u["id"],"transfer",p.vault,p.item,-p.qty,note,ref,counterparty_vault=p.destination)
            change(c,u["id"],"transfer",p.destination,p.item,p.qty,note,ref,counterparty_vault=p.vault,cost_slices=result["slices"])
        else:
            change(c,u["id"],p.kind,p.vault,p.item,p.qty if p.kind=="deposit" else -p.qty,note,ref,
                unit_price=p.unit_cost if p.kind=="deposit" else None)
        audit(c,u["id"],"stock."+p.kind,p.item)
    return {"ok":True,"reference":ref}

@router.get("/ops/crafting")
def crafting(r:Request):
    with db() as c:
        privilege(c,r,"crafting")
        recipes=rows(c,"SELECT r.*,i.name output_name FROM hq_recipe r JOIN hq_item i ON i.id=r.output")
        for recipe in recipes: recipe["ingredients"]=rows(c,"SELECT g.item,g.qty,i.name FROM hq_ingredient g JOIN hq_item i ON g.item=i.id WHERE recipe=?",(recipe["id"],))
        return reply({**catalog(c),"recipes":recipes,"batches":rows(c,"SELECT b.*,r.name recipe_name,v.name vault_name,u.username FROM hq_batch b JOIN hq_recipe r ON r.id=b.recipe JOIN hq_vault v ON v.id=b.vault JOIN users u ON u.id=b.actor ORDER BY b.id DESC LIMIT 300")})

@router.post("/ops/recipe")
def recipe(p:Recipe,r:Request):
    origin(r)
    ids=[i.item for i in p.ingredients]
    if len(set(ids))!=len(ids) or p.output in ids: fail(400,"Distinct inputs and output required")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"crafting","write")
        if c.execute("SELECT 1 FROM hq_recipe WHERE name=?",(p.name.strip(),)).fetchone(): fail(409,"Recipe exists")
        for iid in ids+[p.output]:
            if not c.execute("SELECT 1 FROM hq_item WHERE id=?",(iid,)).fetchone(): fail(404,"Item not found")
        rid=c.execute("INSERT INTO hq_recipe(name,output,output_qty) VALUES(?,?,?)",(clean(p.name,80),p.output,p.output_qty)).lastrowid
        c.executemany("INSERT INTO hq_ingredient VALUES(?,?,?)",[(rid,i.item,i.qty) for i in p.ingredients])
        audit(c,u["id"],"recipe.create",rid)
    return {"ok":True}

@router.post("/ops/craft")
def craft(p:Batch,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"crafting","write")
        rec=c.execute("SELECT * FROM hq_recipe WHERE id=?",(p.recipe,)).fetchone()
        if not rec: fail(404,"Recipe not found")
        note=clean(p.note,500)
        bid=c.execute("INSERT INTO hq_batch(recipe,vault,actor,batches,created,note) VALUES(?,?,?,?,?,?)",(p.recipe,p.vault,u["id"],p.batches,now(),note)).lastrowid
        production_cost=0
        for ing in c.execute("SELECT * FROM hq_ingredient WHERE recipe=?",(p.recipe,)).fetchall():
            consumed=change(c,u["id"],"craft_input",p.vault,ing["item"],-ing["qty"]*p.batches,note,"batch:"+str(bid))
            production_cost+=consumed["value"]
        change(c,u["id"],"craft_output",p.vault,rec["output"],rec["output_qty"]*p.batches,note,"batch:"+str(bid),movement_value=production_cost)
        audit(c,u["id"],"craft.complete",bid)
    return {"ok":True,"id":bid}

@router.get("/ops/cases")
def cases(r:Request):
    with db() as c:
        privilege(c,r,"cases")
        return reply(rows(c,"SELECT * FROM hq_case ORDER BY updated DESC,id DESC LIMIT 300"))

@router.post("/ops/cases")
def create_case(p:Case,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"cases","write")
        cid=c.execute("INSERT INTO hq_case(title,summary,status,actor,created,updated) VALUES(?,?,'open',?,?,?)",(clean(p.name,80),clean(p.summary,4000),u["id"],now(),now())).lastrowid
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hq_case_entity'").fetchone():
            case_ref="TH-"+str(int(cid)).zfill(4)
            c.execute("""INSERT OR IGNORE INTO hq_case_entity(case_id,entity_type,name,description,reference,x,y,actor,created,updated)
                VALUES(?,'case',?,?,?,500,60,?,?,?)""",(cid,case_ref+" · "+clean(p.name,80),clean(p.summary,2000),case_ref,u["id"],now(),now()))
        audit(c,u["id"],"case.create",cid)
    return {"ok":True,"id":cid}

@router.get("/ops/cases/{cid}")
def case_details(cid:int,r:Request):
    with db() as c:
        privilege(c,r,"cases")
        case=c.execute("SELECT * FROM hq_case WHERE id=?",(cid,)).fetchone()
        if not case: fail(404,"Case not found")
        return reply({"case":dict(case),"notes":rows(c,"SELECT n.*,u.username FROM hq_case_note n JOIN users u ON u.id=n.actor WHERE case_id=? ORDER BY n.id",(cid,))})

@router.post("/ops/cases/{cid}")
def case_note(cid:int,p:CaseNote,r:Request):
    origin(r)
    if p.status not in (None,"open","review","closed"): fail(400,"Invalid case status")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"cases","write")
        if not c.execute("UPDATE hq_case SET status=coalesce(?,status),updated=? WHERE id=?",(p.status,now(),cid)).rowcount: fail(404,"Case not found")
        c.execute("INSERT INTO hq_case_note(case_id,actor,note,created) VALUES(?,?,?,?)",(cid,u["id"],clean(p.note,4000),now()))
        audit(c,u["id"],"case.note",cid)
    return {"ok":True}

@router.get("/admin/ops-audit")
def logs(r:Request):
    with db() as c:
        privilege(c,r,admin=True)
        return reply(rows(c,"SELECT a.*,u.username FROM audit a LEFT JOIN users u ON a.actor=u.id ORDER BY a.id DESC LIMIT 500"))


# Visual Operations Calendar — normalized, persistent WIB schedule records.
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
HQ_TZ=ZoneInfo("Asia/Jakarta")
OP_EVENT_STATUSES=("planned","in_progress","completed","cancelled","archived")
OP_REMINDERS=(0,5,15,30,60,1440)

def _calendar_time(value):
    try: parsed=datetime.fromisoformat(value)
    except (TypeError,ValueError): fail(400,"Use a valid ISO date/time")
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=HQ_TZ)
    return parsed.astimezone(HQ_TZ)

class OperationEvent(BaseModel):
    title:str=Field(min_length=1,max_length=140)
    category:str=Field(min_length=1,max_length=80)
    division:str=Field(default="",max_length=100)
    detail:str=Field(default="",max_length=4000)
    owner:str=Field(default="",max_length=120)
    location:str=Field(default="",max_length=240)
    starts_at:str=Field(min_length=16,max_length=40)
    ends_at:str=Field(min_length=16,max_length=40)
    status:str="planned"
    reminder_minutes:int=Field(default=0,ge=0,le=1440)

def _event_values(p):
    if p.status not in OP_EVENT_STATUSES: fail(400,"Invalid operation status")
    if p.reminder_minutes not in OP_REMINDERS: fail(400,"Unsupported reminder interval")
    start=_calendar_time(p.starts_at);end=_calendar_time(p.ends_at)
    if end<=start: fail(400,"End time must be after start time")
    if end-start>timedelta(days=30): fail(400,"An event cannot exceed 30 days")
    return (clean(p.title,140),clean(p.category,80),clean(p.division,100,required=False),
        clean(p.detail,4000,required=False),clean(p.owner,120,required=False),
        clean(p.location,240,required=False),start.isoformat(),end.isoformat(),
        p.status,p.reminder_minutes)

def _event_snapshot(c,event_id,version,uid):
    c.execute("""INSERT INTO hq_operation_revision(event_id,version,title,category,division,detail,owner,location,
        starts_at,ends_at,status,reminder_minutes,actor,created)
        SELECT id,?,title,category,division,detail,owner,location,starts_at,ends_at,status,reminder_minutes,?,?
        FROM hq_operation_event WHERE id=?""",(version,uid,now(),event_id))

@router.get("/ops/calendar")
def operation_calendar(r:Request,start:str|None=None,end:str|None=None,division:str|None=None,
    category:str|None=None,status:str|None=None):
    with db() as c:
        privilege(c,r,"operations")
        sql="""SELECT e.*,coalesce(u.display_name,u.username) creator_name
            FROM hq_operation_event e LEFT JOIN users u ON u.id=e.actor WHERE 1=1"""
        args=[]
        if start: sql+=" AND e.ends_at>=?";args.append(_calendar_time(start).isoformat())
        if end: sql+=" AND e.starts_at<=?";args.append(_calendar_time(end).isoformat())
        if division: sql+=" AND e.division=?";args.append(clean(division,100))
        if category: sql+=" AND e.category=?";args.append(clean(category,80))
        if status:
            if status not in OP_EVENT_STATUSES: fail(400,"Invalid operation status filter")
            sql+=" AND e.status=?";args.append(status)
        sql+=" ORDER BY e.starts_at,e.id LIMIT 500"
        return reply({"events":rows(c,sql,args),
            "divisions":[x["division"] for x in rows(c,"SELECT DISTINCT division FROM hq_operation_event WHERE division<>'' ORDER BY division")],
            "categories":[x["category"] for x in rows(c,"SELECT DISTINCT category FROM hq_operation_event ORDER BY category")],
            "organizational_units":[x["name"] for x in rows(c,"SELECT name FROM ranks ORDER BY position DESC,name")]})

@router.post("/ops/calendar")
def create_operation_event(p:OperationEvent,r:Request):
    origin(r);values=_event_values(p)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"operations","write")
        event_id=c.execute("""INSERT INTO hq_operation_event(title,category,division,detail,owner,location,starts_at,ends_at,status,
            reminder_minutes,version,actor,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
            (*values,u["id"],now(),now())).lastrowid
        _event_snapshot(c,event_id,1,u["id"]);audit(c,u["id"],"operations.event.create",event_id)
    return {"ok":True,"id":event_id}

@router.put("/ops/calendar/{event_id}")
def update_operation_event(event_id:int,p:OperationEvent,r:Request):
    origin(r);values=_event_values(p)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"operations","write")
        old=c.execute("SELECT * FROM hq_operation_event WHERE id=?",(event_id,)).fetchone()
        if not old: fail(404,"Operation event not found")
        if p.status=="archived" or old["status"]=="archived": privilege(c,r,"operations","approve")
        version=old["version"]+1
        c.execute("""UPDATE hq_operation_event SET title=?,category=?,division=?,detail=?,owner=?,location=?,starts_at=?,ends_at=?,
            status=?,reminder_minutes=?,version=?,actor=?,updated=? WHERE id=?""",
            (*values,version,u["id"],now(),event_id))
        _event_snapshot(c,event_id,version,u["id"]);audit(c,u["id"],"operations.event.update",event_id)
    return {"ok":True,"version":version}

@router.get("/ops/calendar/{event_id}/history")
def operation_event_history(event_id:int,r:Request):
    with db() as c:
        privilege(c,r,"operations")
        if not c.execute("SELECT 1 FROM hq_operation_event WHERE id=?",(event_id,)).fetchone(): fail(404,"Operation event not found")
        return reply(rows(c,"""SELECT h.*,coalesce(u.display_name,u.username) actor_name FROM hq_operation_revision h
            LEFT JOIN users u ON u.id=h.actor WHERE h.event_id=? ORDER BY h.version DESC""",(event_id,)))


def _approval_reviewer(c,uid,module,step,request_id=None):
    configured=(c.execute("SELECT rank_id FROM hq_approval_request_step WHERE request_id=? AND step=?",(request_id,step)).fetchone() if request_id is not None else c.execute("SELECT rank_id FROM hq_approval_policy WHERE module=? AND step=?",(module,step)).fetchone())
    user=c.execute("SELECT m.rank,m.status FROM users u JOIN membership m ON m.uid=u.id WHERE u.id=?",(uid,)).fetchone()
    if not user or user["status"]!="approved" or user["rank"] is None: return False,None
    grant=c.execute("SELECT level FROM hq_grants WHERE rank_id=? AND (module=? OR module='*') ORDER BY CASE module WHEN '*' THEN 0 ELSE 1 END",(user["rank"],module)).fetchone()
    if not grant or grant["level"]!="approve": return False,None
    if configured:
        if user["rank"]==configured["rank_id"]: return True,None
        delegated=c.execute("""SELECT d.delegator FROM hq_approval_delegation d JOIN users du ON du.id=d.delegator JOIN membership dm ON dm.uid=du.id JOIN hq_grants g ON g.rank_id=dm.rank AND (g.module=d.module OR g.module='*') AND g.level='approve' WHERE d.module=? AND d.delegate=? AND d.active=1 AND dm.status='approved' AND dm.rank=? ORDER BY d.updated DESC LIMIT 1""",(module,uid,configured["rank_id"])).fetchone()
        return (True,delegated["delegator"]) if delegated else (False,None)
    if grant["level"]=="approve": return True,None
    delegated=c.execute("""SELECT d.delegator FROM hq_approval_delegation d JOIN users du ON du.id=d.delegator JOIN membership dm ON dm.uid=du.id JOIN hq_grants g ON g.rank_id=dm.rank AND (g.module=d.module OR g.module='*') AND g.level='approve' WHERE d.module=? AND d.delegate=? AND d.active=1 AND dm.status='approved' ORDER BY d.updated DESC LIMIT 1""",(module,uid)).fetchone()
    if delegated:
        grant=c.execute("SELECT level FROM hq_grants WHERE rank_id=(SELECT rank FROM membership WHERE uid=?) AND (module=? OR module='*') ORDER BY CASE module WHEN '*' THEN 0 ELSE 1 END",(delegated["delegator"],module)).fetchone()
        if grant and grant["level"]=="approve": return True,delegated["delegator"]
    return False,None

@router.get("/ops/approvals")
def approval_list(r:Request,scope:str="all"):
    if scope not in ("all","mine","inbox"): fail(400,"Invalid approval scope")
    with db() as c:
        u=privilege(c,r)
        candidates=rows(c,"SELECT a.*,u.username requester_name FROM hq_approval_request a JOIN users u ON u.id=a.requester ORDER BY a.created DESC LIMIT 300")
        if scope=="mine": result=[a for a in candidates if a["requester"]==u["id"]]
        elif scope=="inbox": result=[a for a in candidates if a["status"]=="pending" and a["requester"]!=u["id"] and _approval_reviewer(c,u["id"],a["module"],a["current_step"],a["id"])[0]]
        else: result=[a for a in candidates if a["requester"]==u["id"] or _approval_reviewer(c,u["id"],a["module"],a["current_step"],a["id"])[0]]
        return reply(result)

@router.post("/ops/approvals")
def approval_submit(p:ApprovalSubmission,r:Request):
    origin(r)
    if p.module not in MODULES: fail(400,"Unknown approval module")
    import json
    payload=json.dumps(p.payload,ensure_ascii=False,separators=(",",":"))
    if len(payload)>12000: fail(400,"Approval payload is too large")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,p.module,"write")
        policy=rows(c,"SELECT step FROM hq_approval_policy WHERE module=? ORDER BY step",(p.module,))
        if policy and [x["step"] for x in policy]!=list(range(1,len(policy)+1)): fail(409,"Approval route is misconfigured")
        total=len(policy) or 1
        rid=c.execute("INSERT INTO hq_approval_request(module,reference_type,reference_id,title,description,payload,requester,status,current_step,total_steps,created,updated) VALUES(?,?,?,?,?,?,?,'pending',1,?,?,?)",(p.module,clean(p.reference_type,80,required=False),clean(p.reference_id,120,required=False),clean(p.title,160),clean(p.description,4000,required=False),payload,u["id"],total,now(),now())).lastrowid
        if policy:
            route=rows(c,"SELECT rank_id FROM hq_approval_policy WHERE module=? ORDER BY step",(p.module,))
            c.executemany("INSERT INTO hq_approval_request_step(request_id,step,rank_id) VALUES(?,?,?)",[(rid,index,x["rank_id"]) for index,x in enumerate(route,1)])
        _notify_approval_step(c,rid,1)
        audit(c,u["id"],"approval.submit",rid)
    return {"ok":True,"id":rid,"steps":total}

@router.post("/ops/approvals/{request_id}/review")
def approval_review(request_id:int,p:ApprovalDecision,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r)
        item=c.execute("SELECT * FROM hq_approval_request WHERE id=?",(request_id,)).fetchone()
        if not item: fail(404,"Approval request not found")
        if item["status"]!="pending": fail(409,"Approval request is no longer pending")
        if item["requester"]==u["id"]: fail(403,"Cannot review your own request")
        eligible,delegator=_approval_reviewer(c,u["id"],item["module"],item["current_step"],request_id)
        if not eligible: fail(403,"You are not assigned to the current approval step")
        decision="approved" if p.approve else "rejected"
        c.execute("INSERT INTO hq_approval_action(request_id,step,actor,delegated_from,decision,note,created) VALUES(?,?,?,?,?,?,?)",(request_id,item["current_step"],u["id"],delegator,decision,clean(p.note,1000,required=False),now()))
        if not p.approve: state="rejected";step=item["current_step"]
        elif item["current_step"]<item["total_steps"]: state="pending";step=item["current_step"]+1
        else: state="approved";step=item["current_step"]
        c.execute("UPDATE hq_approval_request SET status=?,current_step=?,updated=? WHERE id=?",(state,step,now(),request_id))
        if state=="pending":
            _notify_approval_step(c,request_id,step)
        else:
            notify(c,item["requester"],"approval_decision","Approval request "+state,
                item["title"]+" · reviewed by "+str(u["id"]),
                "/highest/internal/","approval:"+str(request_id)+":final:"+state)
        audit(c,u["id"],"approval."+decision,request_id)
    return {"ok":True,"status":state,"next_step":step}

@router.post("/ops/approvals/{request_id}/cancel")
def approval_cancel(request_id:int,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r)
        item=c.execute("SELECT * FROM hq_approval_request WHERE id=?",(request_id,)).fetchone()
        if not item: fail(404,"Approval request not found")
        if item["requester"]!=u["id"]: fail(403,"Only the requester can cancel")
        if item["status"]!="pending": fail(409,"Only pending requests can be cancelled")
        c.execute("UPDATE hq_approval_request SET status='cancelled',updated=? WHERE id=?",(now(),request_id))
        audit(c,u["id"],"approval.cancel",request_id)
    return {"ok":True}

@router.get("/ops/approvals/{request_id}/history")
def approval_history(request_id:int,r:Request):
    with db() as c:
        u=privilege(c,r);item=c.execute("SELECT * FROM hq_approval_request WHERE id=?",(request_id,)).fetchone()
        if not item: fail(404,"Approval request not found")
        previous=c.execute("SELECT 1 FROM hq_approval_action WHERE request_id=? AND actor=?",(request_id,u["id"])).fetchone()
        if item["requester"]!=u["id"] and not previous and not _approval_reviewer(c,u["id"],item["module"],item["current_step"],request_id)[0]: fail(403,"Approval history access denied")
        return reply({"request":dict(item),"actions":rows(c,"SELECT a.*,u.username actor_name,du.username delegated_from_name FROM hq_approval_action a JOIN users u ON u.id=a.actor LEFT JOIN users du ON du.id=a.delegated_from WHERE a.request_id=? ORDER BY a.step",(request_id,))})

@router.post("/ops/approvals/delegations")
def approval_delegation(p:ApprovalDelegation,r:Request):
    origin(r)
    if p.module not in MODULES: fail(400,"Unknown approval module")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,p.module,"approve")
        if p.delegate_user_id==u["id"]: fail(400,"Cannot delegate to yourself")
        target=c.execute("SELECT u.id,m.rank,m.status FROM users u JOIN membership m ON m.uid=u.id WHERE u.id=?",(p.delegate_user_id,)).fetchone()
        if not target or target["status"]!="approved": fail(404,"Delegate must be an approved member")
        grant=c.execute("SELECT level FROM hq_grants WHERE rank_id=? AND (module=? OR module='*') ORDER BY CASE module WHEN '*' THEN 0 ELSE 1 END",(target["rank"],p.module)).fetchone()
        if not grant or grant["level"]!="approve": fail(403,"Delegate must hold approve permission for this module")
        c.execute("INSERT INTO hq_approval_delegation(module,delegator,delegate,active,created,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(module,delegator,delegate) DO UPDATE SET active=excluded.active,updated=excluded.updated",(p.module,u["id"],p.delegate_user_id,int(p.active),now(),now()))
        audit(c,u["id"],"approval.delegation."+("activate" if p.active else "revoke"),p.delegate_user_id)
    return {"ok":True}

@router.get("/ops/approvals/delegations")
def approval_delegations(r:Request,module:str|None=None):
    with db() as c:
        u=privilege(c,r)
        return reply(rows(c,"SELECT d.*,du.username delegator_name,eu.username delegate_name FROM hq_approval_delegation d JOIN users du ON du.id=d.delegator JOIN users eu ON eu.id=d.delegate WHERE d.delegator=? AND (? IS NULL OR d.module=?) ORDER BY d.module,d.id DESC",(u["id"],module,module)))

@router.get("/admin/approval-policies")
def approval_policies(r:Request):
    with db() as c:
        privilege(c,r,admin=True)
        return reply({"ranks":rows(c,"SELECT id,name,position FROM ranks ORDER BY position DESC,name"),"policies":rows(c,"SELECT p.module,p.step,p.rank_id,r.name rank_name FROM hq_approval_policy p JOIN ranks r ON r.id=p.rank_id ORDER BY p.module,p.step")})

@router.post("/admin/approval-policies")
def approval_policy_save(p:ApprovalPolicy,r:Request):
    origin(r)
    if p.module not in MODULES or len(set(p.ranks))!=len(p.ranks): fail(400,"Invalid module or duplicate approval rank")
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,admin=True)
        for rank_id in p.ranks:
            if not c.execute("SELECT 1 FROM ranks WHERE id=?",(rank_id,)).fetchone(): fail(404,"Approval rank not found")
            grant=c.execute("SELECT level FROM hq_grants WHERE rank_id=? AND (module=? OR module='*') ORDER BY CASE module WHEN '*' THEN 0 ELSE 1 END",(rank_id,p.module)).fetchone()
            if not grant or grant["level"]!="approve": fail(409,"Every approval rank must have approve permission for this module")
        c.execute("DELETE FROM hq_approval_policy WHERE module=?",(p.module,))
        c.executemany("INSERT INTO hq_approval_policy(module,step,rank_id) VALUES(?,?,?)",[(p.module,i,rank_id) for i,rank_id in enumerate(p.ranks,1)])
        audit(c,u["id"],"approval.policy.update."+p.module,len(p.ranks))
    return {"ok":True,"steps":len(p.ranks)}

@router.delete("/admin/approval-policies/{module}")
def approval_policy_clear(module:str,r:Request):
    origin(r)
    if module not in MODULES: fail(400,"Unknown approval module")
    with db() as c:
        u=privilege(c,r,admin=True);c.execute("DELETE FROM hq_approval_policy WHERE module=?",(module,))
        audit(c,u["id"],"approval.policy.clear."+module,0)
    return {"ok":True}
