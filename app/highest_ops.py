"""Transactional IC ledger, warehouse, crafting and case files for FiveM."""
import time, hashlib, secrets, json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.highest import db, origin, digest, cookie, fail, clean, audit, current

router=APIRouter(prefix="/highest/api")
MODULES=("treasury","inventory","crafting","cases","syndicates","operations","assets","documents","business","business_prices","business_analytics","business_discounts","financial_reports")

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_grants(rank_id INTEGER REFERENCES ranks(id) ON DELETE CASCADE,module TEXT,level TEXT CHECK(level IN ('view','write','approve')),PRIMARY KEY(rank_id,module));
        CREATE TABLE IF NOT EXISTS hq_financial_budget(
            id INTEGER PRIMARY KEY,period TEXT NOT NULL,division TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '',
            amount INTEGER NOT NULL CHECK(amount>=0),actor INTEGER REFERENCES users(id),updated INTEGER NOT NULL,
            UNIQUE(period,division,category)
        );
                CREATE TABLE IF NOT EXISTS hq_treasury_account(
            id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created INTEGER NOT NULL,actor INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS hq_money(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),amount INTEGER NOT NULL,category TEXT NOT NULL,note TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','posted','rejected')),reviewer INTEGER REFERENCES users(id),created INTEGER NOT NULL,account_id INTEGER REFERENCES hq_treasury_account(id),transfer_ref TEXT);
        CREATE TABLE IF NOT EXISTS hq_treasury_transfer(
            id INTEGER PRIMARY KEY,actor INTEGER NOT NULL REFERENCES users(id),source_account INTEGER NOT NULL REFERENCES hq_treasury_account(id),
            destination_account INTEGER NOT NULL REFERENCES hq_treasury_account(id),amount INTEGER NOT NULL CHECK(amount>0),
            note TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','posted','rejected')),
            reviewer INTEGER REFERENCES users(id),created INTEGER NOT NULL,transfer_ref TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS hq_treasury_reconciliation(
            id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES hq_treasury_account(id),
            expected_balance INTEGER NOT NULL,counted_balance INTEGER NOT NULL,difference INTEGER NOT NULL,
            note TEXT NOT NULL,actor INTEGER NOT NULL REFERENCES users(id),status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            reviewer INTEGER REFERENCES users(id),created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_treasury_recon_account ON hq_treasury_reconciliation(account_id,created DESC);
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
        CREATE TABLE IF NOT EXISTS hq_asset(
            id INTEGER PRIMARY KEY,asset_tag TEXT NOT NULL UNIQUE COLLATE NOCASE,
            asset_type TEXT NOT NULL CHECK(asset_type IN ('vehicle','property','equipment','other')),
            name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',make_model TEXT NOT NULL DEFAULT '',
            serial_number TEXT NOT NULL DEFAULT '',plate_number TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',condition TEXT NOT NULL DEFAULT 'good',
            status TEXT NOT NULL CHECK(status IN ('available','assigned','maintenance','retired')),
            purchase_cost INTEGER NOT NULL DEFAULT 0 CHECK(purchase_cost>=0),purchase_date TEXT NOT NULL DEFAULT '',
            assigned_to TEXT NOT NULL DEFAULT '',inventory_item_id INTEGER REFERENCES hq_item(id),
            case_id INTEGER REFERENCES hq_case(id),actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,updated INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_asset_status_type ON hq_asset(status,asset_type,name);
        CREATE TABLE IF NOT EXISTS hq_asset_request(
            id INTEGER PRIMARY KEY,request_type TEXT NOT NULL CHECK(request_type IN ('acquisition','disposal')),
            asset_id INTEGER REFERENCES hq_asset(id),payload TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            actor INTEGER NOT NULL REFERENCES users(id),reviewer INTEGER REFERENCES users(id),
            created INTEGER NOT NULL,reviewed INTEGER
        );
        CREATE INDEX IF NOT EXISTS hq_asset_request_queue ON hq_asset_request(status,created);
        CREATE TABLE IF NOT EXISTS hq_asset_history(
            id INTEGER PRIMARY KEY,asset_id INTEGER NOT NULL REFERENCES hq_asset(id),
            event TEXT NOT NULL,from_value TEXT NOT NULL DEFAULT '',to_value TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',actor INTEGER REFERENCES users(id),created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_asset_history_asset ON hq_asset_history(asset_id,created DESC);
        CREATE TABLE IF NOT EXISTS hq_asset_maintenance(
            id INTEGER PRIMARY KEY,asset_id INTEGER NOT NULL REFERENCES hq_asset(id),
            title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',vendor TEXT NOT NULL DEFAULT '',
            cost INTEGER NOT NULL DEFAULT 0 CHECK(cost>=0),status TEXT NOT NULL CHECK(status IN ('open','completed')),
            actor INTEGER REFERENCES users(id),created INTEGER NOT NULL,completed INTEGER
        );
        CREATE INDEX IF NOT EXISTS hq_asset_maintenance_asset ON hq_asset_maintenance(asset_id,created DESC);
\n        CREATE TABLE IF NOT EXISTS hq_operation_event(
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
        money_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_money)")}
        if "account_id" not in money_columns: c.execute("ALTER TABLE hq_money ADD COLUMN account_id INTEGER REFERENCES hq_treasury_account(id)")
        if "transfer_ref" not in money_columns: c.execute("ALTER TABLE hq_money ADD COLUMN transfer_ref TEXT")
        default_account=c.execute("SELECT id FROM hq_treasury_account WHERE name='General Treasury' COLLATE NOCASE").fetchone()
        if not default_account:
            default_id=c.execute("INSERT INTO hq_treasury_account(name,description,active,created) VALUES('General Treasury','Migrated default treasury account',1,?)",(now(),)).lastrowid
        else: default_id=default_account["id"]
        c.execute("UPDATE hq_money SET account_id=? WHERE account_id IS NULL",(default_id,))
        c.execute("CREATE INDEX IF NOT EXISTS hq_money_account_state ON hq_money(account_id,state,created DESC)")
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
              AND om.rank=? AND du.id<>?""",(item["module"],configured["rank_id"],item["requester"]))
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
    account_id:int|None=None
    direction:str
    category:str=Field(min_length=1,max_length=60)
    note:str=Field(min_length=1,max_length=500)
class TreasuryAccount(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    description:str=Field(default='',max_length=300)
class TreasuryTransfer(BaseModel):
    source_account:int
    destination_account:int
    amount:int=Field(gt=0,le=1000000000000)
    note:str=Field(min_length=1,max_length=500)
class TreasuryReconciliation(BaseModel):
    account_id:int
    counted_balance:int=Field(ge=0,le=1000000000000000)
    note:str=Field(min_length=1,max_length=500)
class AssetAcquisition(BaseModel):
    asset_tag:str=Field(min_length=2,max_length=40)
    asset_type:str
    name:str=Field(min_length=2,max_length=100)
    description:str=Field(default='',max_length=2000)
    make_model:str=Field(default='',max_length=120)
    serial_number:str=Field(default='',max_length=100)
    plate_number:str=Field(default='',max_length=30)
    location:str=Field(default='',max_length=120)
    condition:str=Field(default='good',max_length=40)
    purchase_cost:int=Field(default=0,ge=0,le=1000000000000)
    purchase_date:str=Field(default='',max_length=30)
    inventory_item_id:int|None=None
    case_id:int|None=None
    account_id:int|None=None
    note:str=Field(min_length=1,max_length=500)
class AssetDisposal(BaseModel):
    asset_id:int
    note:str=Field(min_length=1,max_length=500)
class AssetRequest(BaseModel):
    request_type:str
    acquisition:AssetAcquisition|None=None
    disposal:AssetDisposal|None=None
class AssetAssignment(BaseModel):
    assigned_to:str=Field(default='',max_length=120)
    location:str=Field(default='',max_length=120)
    note:str=Field(min_length=1,max_length=500)
class AssetMaintenance(BaseModel):
    title:str=Field(min_length=2,max_length=120)
    description:str=Field(default='',max_length=1500)
    vendor:str=Field(default='',max_length=120)
    cost:int=Field(default=0,ge=0,le=1000000000000)
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

def balance(c,account_id=None):
    if account_id is None:
        return c.execute("SELECT coalesce(sum(amount),0) FROM hq_money WHERE state='posted'").fetchone()[0]
    return c.execute("SELECT coalesce(sum(amount),0) FROM hq_money WHERE state='posted' AND account_id=?",(account_id,)).fetchone()[0]

@router.get("/ops/treasury")
def treasury(r:Request):
    with db() as c:
        privilege(c,r,"treasury")
        accounts=rows(c,"""SELECT a.*,coalesce(sum(CASE WHEN m.state='posted' THEN m.amount ELSE 0 END),0) balance
            FROM hq_treasury_account a LEFT JOIN hq_money m ON m.account_id=a.id
            WHERE a.active=1 GROUP BY a.id ORDER BY a.name""")
        return reply({"balance":balance(c),"accounts":accounts,
            "entries":rows(c,"""SELECT m.*,u.username,a.name account_name FROM hq_money m
                JOIN users u ON u.id=m.actor LEFT JOIN hq_treasury_account a ON a.id=m.account_id
                ORDER BY m.id DESC LIMIT 300"""),
            "transfers":rows(c,"""SELECT t.*,s.name source_name,d.name destination_name,u.username
                FROM hq_treasury_transfer t JOIN hq_treasury_account s ON s.id=t.source_account
                JOIN hq_treasury_account d ON d.id=t.destination_account JOIN users u ON u.id=t.actor
                ORDER BY t.id DESC LIMIT 100"""),
            "reconciliations":rows(c,"""SELECT x.*,a.name account_name,u.username FROM hq_treasury_reconciliation x
                JOIN hq_treasury_account a ON a.id=x.account_id JOIN users u ON u.id=x.actor
                ORDER BY x.id DESC LIMIT 100""")})

@router.post("/ops/treasury/accounts")
def treasury_account_create(p:TreasuryAccount,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","write")
        try:
            aid=c.execute("INSERT INTO hq_treasury_account(name,description,active,created,actor) VALUES(?,?,1,?,?)",
                (clean(p.name,80),clean(p.description,300,required=False),now(),u["id"])).lastrowid
        except Exception as e:
            if "UNIQUE" in str(e): fail(409,"Treasury account name already exists")
            raise
        audit(c,u["id"],"treasury.account.create",aid)
    return {"ok":True,"id":aid}

@router.post("/ops/treasury")
def money(p:Money,r:Request):
    origin(r)
    if p.direction not in ("income","expense"): fail(400,"Invalid direction")
    account_id=getattr(p,"account_id",None)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","write")
        if account_id is None:
            account=c.execute("SELECT id FROM hq_treasury_account WHERE name='General Treasury' COLLATE NOCASE AND active=1").fetchone()
            account_id=account["id"] if account else None
        account=c.execute("SELECT id FROM hq_treasury_account WHERE id=? AND active=1",(account_id,)).fetchone()
        if not account: fail(404,"Active treasury account not found")
        amount=p.amount if p.direction=="income" else -p.amount
        mid=c.execute("INSERT INTO hq_money(actor,amount,category,note,state,created,account_id) VALUES(?,?,?,?,'pending',?,?)",
            (u["id"],amount,clean(p.category,60),clean(p.note,500),now(),account_id)).lastrowid
        reviewers=rows(c,"""SELECT DISTINCT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module='treasury' OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(u["id"],))
        for target in reviewers:
            notify(c,target["id"],"treasury_review","Treasury transaction awaits review",
                account["id"].__str__()+" · "+clean(p.category,60)+" · "+str(abs(amount)),
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
        if p.approve and balance(c,row["account_id"])+row["amount"]<0:
            fail(409,"Insufficient treasury account balance")
        state="posted" if p.approve else "rejected"
        c.execute("UPDATE hq_money SET state=?,reviewer=? WHERE id=?",(state,u["id"],mid))
        notify(c,row["actor"],"treasury_decision","Treasury transaction "+state,
            row["category"]+" · "+str(abs(row["amount"])),"/highest/internal/",
            "treasury:"+str(mid)+":decision:"+state)
        audit(c,u["id"],"money."+state,mid)
    return {"ok":True}

@router.post("/ops/treasury/transfers")
def treasury_transfer_create(p:TreasuryTransfer,r:Request):
    origin(r)
    if p.source_account==p.destination_account: fail(400,"Source and destination accounts must differ")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","write")
        source=c.execute("SELECT * FROM hq_treasury_account WHERE id=? AND active=1",(p.source_account,)).fetchone()
        dest=c.execute("SELECT * FROM hq_treasury_account WHERE id=? AND active=1",(p.destination_account,)).fetchone()
        if not source or not dest: fail(404,"Active treasury account not found")
        if balance(c,p.source_account)<p.amount: fail(409,"Insufficient source account balance")
        ref=secrets.token_hex(12)
        tid=c.execute("""INSERT INTO hq_treasury_transfer(actor,source_account,destination_account,amount,note,status,created,transfer_ref)
            VALUES(?,?,?,?,?,'pending',?,?)""",(u["id"],p.source_account,p.destination_account,p.amount,clean(p.note,500),now(),ref)).lastrowid
        reviewers=rows(c,"""SELECT DISTINCT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module='treasury' OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(u["id"],))
        for target in reviewers:
            notify(c,target["id"],"treasury_transfer_review","Treasury transfer awaits review",
                source["name"]+" → "+dest["name"]+" · "+str(p.amount),"/highest/internal/",
                "treasury-transfer:"+str(tid)+":review:"+str(target["id"]))
        audit(c,u["id"],"treasury.transfer.request",tid)
    return {"ok":True,"id":tid,"reference":ref}

@router.post("/ops/treasury/transfers/{transfer_id}/review")
def treasury_transfer_review(transfer_id:int,p:Decision,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","approve")
        transfer=c.execute("SELECT * FROM hq_treasury_transfer WHERE id=? AND status='pending'",(transfer_id,)).fetchone()
        if not transfer: fail(409,"No pending treasury transfer")
        if transfer["actor"]==u["id"]: fail(403,"Cannot review own transfer")
        state="rejected"
        if p.approve:
            if balance(c,transfer["source_account"])<transfer["amount"]: fail(409,"Insufficient source account balance")
            source=c.execute("SELECT name FROM hq_treasury_account WHERE id=?",(transfer["source_account"],)).fetchone()
            dest=c.execute("SELECT name FROM hq_treasury_account WHERE id=?",(transfer["destination_account"],)).fetchone()
            ref=transfer["transfer_ref"]
            c.execute("""INSERT INTO hq_money(actor,amount,category,note,state,reviewer,created,account_id,transfer_ref)
                VALUES(?,?,'Internal transfer',?,'posted',?,?,?,?)""",
                (transfer["actor"],-transfer["amount"],"Transfer to "+dest["name"]+" · "+transfer["note"],u["id"],now(),transfer["source_account"],ref))
            c.execute("""INSERT INTO hq_money(actor,amount,category,note,state,reviewer,created,account_id,transfer_ref)
                VALUES(?,?,'Internal transfer',?,'posted',?,?,?,?)""",
                (transfer["actor"],transfer["amount"],"Transfer from "+source["name"]+" · "+transfer["note"],u["id"],now(),transfer["destination_account"],ref))
            state="posted"
        c.execute("UPDATE hq_treasury_transfer SET status=?,reviewer=? WHERE id=?",(state,u["id"],transfer_id))
        notify(c,transfer["actor"],"treasury_transfer_decision","Treasury transfer "+state,
            "Transfer #"+str(transfer_id),"/highest/internal/","treasury-transfer:"+str(transfer_id)+":decision:"+state)
        audit(c,u["id"],"treasury.transfer."+state,transfer_id)
    return {"ok":True,"status":state}

@router.post("/ops/treasury/reconciliations")
def treasury_reconciliation_create(p:TreasuryReconciliation,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","write")
        account=c.execute("SELECT * FROM hq_treasury_account WHERE id=? AND active=1",(p.account_id,)).fetchone()
        if not account: fail(404,"Active treasury account not found")
        expected=balance(c,p.account_id);difference=p.counted_balance-expected
        rid=c.execute("""INSERT INTO hq_treasury_reconciliation(account_id,expected_balance,counted_balance,difference,note,actor,status,created)
            VALUES(?,?,?,?,?,?,'pending',?)""",(p.account_id,expected,p.counted_balance,difference,clean(p.note,500),u["id"],now())).lastrowid
        reviewers=rows(c,"""SELECT DISTINCT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module='treasury' OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(u["id"],))
        for target in reviewers:
            notify(c,target["id"],"treasury_reconciliation_review","Treasury reconciliation awaits review",
                account["name"]+" · variance "+str(difference),"/highest/internal/",
                "treasury-reconciliation:"+str(rid)+":review:"+str(target["id"]))
        audit(c,u["id"],"treasury.reconciliation.submit",rid)
    return {"ok":True,"id":rid,"expected_balance":expected,"difference":difference}

@router.post("/ops/treasury/reconciliations/{reconciliation_id}/review")
def treasury_reconciliation_review(reconciliation_id:int,p:Decision,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"treasury","approve")
        record=c.execute("SELECT * FROM hq_treasury_reconciliation WHERE id=? AND status='pending'",(reconciliation_id,)).fetchone()
        if not record: fail(409,"No pending reconciliation")
        if record["actor"]==u["id"]: fail(403,"Cannot review own reconciliation")
        state="approved" if p.approve else "rejected"
        c.execute("UPDATE hq_treasury_reconciliation SET status=?,reviewer=? WHERE id=?",(state,u["id"],reconciliation_id))
        notify(c,record["actor"],"treasury_reconciliation_decision","Treasury reconciliation "+state,
            "Reconciliation #"+str(reconciliation_id)+" · variance "+str(record["difference"]),
            "/highest/internal/","treasury-reconciliation:"+str(reconciliation_id)+":decision:"+state)
        audit(c,u["id"],"treasury.reconciliation."+state,reconciliation_id)
    return {"ok":True,"status":state}

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
        if p.active:
            pending=rows(c,"""SELECT q.id,q.title,q.current_step FROM hq_approval_request q
                JOIN hq_approval_request_step st ON st.request_id=q.id AND st.step=q.current_step
                WHERE q.module=? AND q.status='pending' AND st.rank_id=? AND q.requester<>?""",
                (p.module,u["rank"],u["id"]))
            for request in pending:
                notify(c,p.delegate_user_id,"approval_review","Approval requires your review",
                    request["title"]+" · "+p.module+" · step "+str(request["current_step"]),
                    "/highest/internal/","approval:"+str(request["id"])+":step:"+str(request["current_step"])+":user:"+str(p.delegate_user_id))
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


@router.get("/ops/assets")
def assets(r:Request):
    with db() as c:
        privilege(c,r,"assets")
        return reply({
            "assets":rows(c,"""SELECT a.*,i.name inventory_item_name,cs.title case_title
                FROM hq_asset a LEFT JOIN hq_item i ON i.id=a.inventory_item_id
                LEFT JOIN hq_case cs ON cs.id=a.case_id ORDER BY a.updated DESC,a.id DESC LIMIT 500"""),
            "requests":rows(c,"""SELECT q.*,u.username,rv.username reviewer_name,a.asset_tag,a.name asset_name
                FROM hq_asset_request q JOIN users u ON u.id=q.actor
                LEFT JOIN users rv ON rv.id=q.reviewer LEFT JOIN hq_asset a ON a.id=q.asset_id
                ORDER BY q.created DESC,q.id DESC LIMIT 200"""),
            "maintenance":rows(c,"""SELECT m.*,a.asset_tag,a.name asset_name,u.username
                FROM hq_asset_maintenance m JOIN hq_asset a ON a.id=m.asset_id
                LEFT JOIN users u ON u.id=m.actor ORDER BY m.created DESC,m.id DESC LIMIT 200"""),
            "history":rows(c,"""SELECT h.*,a.asset_tag,a.name asset_name,u.username
                FROM hq_asset_history h JOIN hq_asset a ON a.id=h.asset_id
                LEFT JOIN users u ON u.id=h.actor ORDER BY h.created DESC,h.id DESC LIMIT 300"""),
            "inventory_items":rows(c,"SELECT id,name FROM hq_item ORDER BY name"),
            "cases":rows(c,"SELECT id,title FROM hq_case ORDER BY id DESC LIMIT 300"),
            "accounts":rows(c,"SELECT id,name FROM hq_treasury_account WHERE active=1 ORDER BY name")
        })

@router.post("/ops/assets/requests")
def asset_request(p:AssetRequest,r:Request):
    origin(r)
    if p.request_type not in ("acquisition","disposal"): fail(400,"Invalid asset request type")
    if (p.request_type=="acquisition") != (p.acquisition is not None) or (p.request_type=="disposal") != (p.disposal is not None):
        fail(400,"Provide exactly one matching acquisition or disposal payload")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"assets","write")
        asset_id=None;payload={}
        if p.request_type=="acquisition":
            a=p.acquisition
            if a.asset_type not in ("vehicle","property","equipment","other"): fail(400,"Invalid asset type")
            if a.condition not in ("new","excellent","good","fair","poor"): fail(400,"Invalid asset condition")
            if c.execute("SELECT 1 FROM hq_asset WHERE asset_tag=?",(a.asset_tag.strip(),)).fetchone(): fail(409,"Asset tag already exists")
            if a.inventory_item_id is not None and not c.execute("SELECT 1 FROM hq_item WHERE id=?",(a.inventory_item_id,)).fetchone(): fail(404,"Linked inventory item not found")
            if a.case_id is not None and not c.execute("SELECT 1 FROM hq_case WHERE id=?",(a.case_id,)).fetchone(): fail(404,"Linked case not found")
            if a.purchase_cost>0:
                account=c.execute("SELECT id FROM hq_treasury_account WHERE id=? AND active=1",(a.account_id,)).fetchone()
                if not account: fail(400,"Select an active treasury account for a paid acquisition")
            payload=a.model_dump()
            note=clean(a.note,500)
        else:
            d=p.disposal
            asset=c.execute("SELECT * FROM hq_asset WHERE id=? AND status<>'retired'",(d.asset_id,)).fetchone()
            if not asset: fail(404,"Active asset not found")
            asset_id=d.asset_id;payload={"asset_tag":asset["asset_tag"],"name":asset["name"]}
            note=clean(d.note,500)
        rid=c.execute("""INSERT INTO hq_asset_request(request_type,asset_id,payload,note,status,actor,created)
            VALUES(?,?,?,?, 'pending',?,?)""",(p.request_type,asset_id,json.dumps(payload,separators=(",",":")),note,u["id"],now())).lastrowid
        reviewers=rows(c,"""SELECT DISTINCT u.id FROM users u JOIN membership m ON m.uid=u.id
            JOIN hq_grants g ON g.rank_id=m.rank AND (g.module='assets' OR g.module='*') AND g.level='approve'
            WHERE m.status='approved' AND u.id<>?""",(u["id"],))
        for target in reviewers:
            notify(c,target["id"],"asset_review","Asset request awaits approval",
                p.request_type.title()+" · "+(payload.get("name") or payload.get("asset_tag",""))+" · "+note,
                "/highest/internal/","asset-request:"+str(rid)+":review:"+str(target["id"]))
        audit(c,u["id"],"asset.request."+p.request_type,rid)
    return {"ok":True,"id":rid}

@router.post("/ops/assets/requests/{request_id}/review")
def asset_request_review(request_id:int,p:Decision,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"assets","approve")
        request=c.execute("SELECT * FROM hq_asset_request WHERE id=? AND status='pending'",(request_id,)).fetchone()
        if not request: fail(409,"No pending asset request")
        if request["actor"]==u["id"]: fail(403,"Cannot review your own asset request")
        payload=json.loads(request["payload"]);status="rejected"
        if p.approve and request["request_type"]=="acquisition":
            if c.execute("SELECT 1 FROM hq_asset WHERE asset_tag=?",(payload["asset_tag"],)).fetchone(): fail(409,"Asset tag was registered by another request")
            aid=c.execute("""INSERT INTO hq_asset(asset_tag,asset_type,name,description,make_model,serial_number,plate_number,
                location,condition,status,purchase_cost,purchase_date,inventory_item_id,case_id,actor,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,'available',?,?,?,?,?,?,?)""",
                (payload["asset_tag"].strip(),payload["asset_type"],clean(payload["name"],100),clean(payload["description"],2000,required=False),
                 clean(payload["make_model"],120,required=False),clean(payload["serial_number"],100,required=False),
                 clean(payload["plate_number"],30,required=False),clean(payload["location"],120,required=False),payload["condition"],
                 payload["purchase_cost"],payload["purchase_date"],payload["inventory_item_id"],payload["case_id"],request["actor"],now(),now())).lastrowid
            c.execute("INSERT INTO hq_asset_history(asset_id,event,to_value,note,actor,created) VALUES(?,'acquired','available',?,?,?)",
                (aid,request["note"],u["id"],now()))
            if payload["purchase_cost"]>0:
                c.execute("""INSERT INTO hq_money(actor,amount,category,note,state,created,account_id)
                    VALUES(?,?,'Asset acquisition',?,'pending',?,?)""",
                    (request["actor"],-payload["purchase_cost"],"Asset "+payload["asset_tag"]+" · "+request["note"],now(),payload["account_id"]))
                money_id=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                audit(c,u["id"],"money.request.asset_acquisition",money_id)
            audit(c,u["id"],"asset.acquire",aid)
            payload["created_asset_id"]=aid
            status="approved"
        elif p.approve and request["request_type"]=="disposal":
            asset=c.execute("SELECT * FROM hq_asset WHERE id=? AND status<>'retired'",(request["asset_id"],)).fetchone()
            if not asset: fail(409,"Asset is already retired or unavailable")
            c.execute("UPDATE hq_asset SET status='retired',updated=? WHERE id=?",(now(),asset["id"]))
            c.execute("INSERT INTO hq_asset_history(asset_id,event,from_value,to_value,note,actor,created) VALUES(?,'disposed',?,'retired',?,?,?)",
                (asset["id"],asset["status"],request["note"],u["id"],now()))
            audit(c,u["id"],"asset.dispose",asset["id"])
            status="approved"
        c.execute("UPDATE hq_asset_request SET status=?,reviewer=?,reviewed=? WHERE id=?",(status,u["id"],now(),request_id))
        notify(c,request["actor"],"asset_decision","Asset request "+status,
            request["request_type"].title()+" · "+str(request_id),"/highest/internal/",
            "asset-request:"+str(request_id)+":decision:"+status)
        audit(c,u["id"],"asset.request."+status,request_id)
    return {"ok":True,"status":status}

@router.post("/ops/assets/{asset_id}/assignment")
def asset_assignment(asset_id:int,p:AssetAssignment,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"assets","write")
        asset=c.execute("SELECT * FROM hq_asset WHERE id=?",(asset_id,)).fetchone()
        if not asset: fail(404,"Asset not found")
        if asset["status"] in ("retired","maintenance"): fail(409,"Retired or maintained assets cannot be assigned")
        assigned=clean(p.assigned_to,120,required=False)
        status="assigned" if assigned else "available"
        c.execute("UPDATE hq_asset SET assigned_to=?,location=?,status=?,updated=? WHERE id=?",
            (assigned,clean(p.location,120,required=False) or asset["location"],status,now(),asset_id))
        c.execute("""INSERT INTO hq_asset_history(asset_id,event,from_value,to_value,note,actor,created)
            VALUES(?,'assignment',?,?,?, ?,?)""",(asset_id,asset["assigned_to"],assigned,clean(p.note,500),u["id"],now()))
        audit(c,u["id"],"asset.assignment",asset_id)
    return {"ok":True,"status":status}

@router.post("/ops/assets/{asset_id}/maintenance")
def asset_maintenance(asset_id:int,p:AssetMaintenance,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"assets","write")
        asset=c.execute("SELECT * FROM hq_asset WHERE id=?",(asset_id,)).fetchone()
        if not asset: fail(404,"Asset not found")
        if asset["status"]=="retired": fail(409,"Retired asset cannot enter maintenance")
        mid=c.execute("""INSERT INTO hq_asset_maintenance(asset_id,title,description,vendor,cost,status,actor,created)
            VALUES(?,?,?,?,?,'open',?,?)""",
            (asset_id,clean(p.title,120),clean(p.description,1500,required=False),clean(p.vendor,120,required=False),p.cost,u["id"],now())).lastrowid
        c.execute("UPDATE hq_asset SET status='maintenance',updated=? WHERE id=?",(now(),asset_id))
        c.execute("""INSERT INTO hq_asset_history(asset_id,event,from_value,to_value,note,actor,created)
            VALUES(?,'maintenance',?,'maintenance',?,?,?)""",(asset_id,asset["status"],clean(p.title,120)+" · "+clean(p.description,1500,required=False),u["id"],now()))
        audit(c,u["id"],"asset.maintenance.open",mid)
    return {"ok":True,"id":mid}

@router.post("/ops/assets/{asset_id}/maintenance/{maintenance_id}/complete")
def asset_maintenance_complete(asset_id:int,maintenance_id:int,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"assets","write")
        asset=c.execute("SELECT * FROM hq_asset WHERE id=?",(asset_id,)).fetchone()
        record=c.execute("SELECT * FROM hq_asset_maintenance WHERE id=? AND asset_id=? AND status='open'",(maintenance_id,asset_id)).fetchone()
        if not asset or not record: fail(404,"Open maintenance record not found")
        status="assigned" if asset["assigned_to"] else "available"
        c.execute("UPDATE hq_asset_maintenance SET status='completed',completed=? WHERE id=?",(now(),maintenance_id))
        c.execute("UPDATE hq_asset SET status=?,updated=? WHERE id=?",(status,now(),asset_id))
        c.execute("""INSERT INTO hq_asset_history(asset_id,event,from_value,to_value,note,actor,created)
            VALUES(?,'maintenance_completed','maintenance',?,?,?,?)""",(asset_id,status,record["title"],u["id"],now()))
        audit(c,u["id"],"asset.maintenance.complete",maintenance_id)
    return {"ok":True,"status":status}

@router.get("/ops/executive")
def executive_dashboard(r:Request):
    with db() as c:
        u=privilege(c,r)
        grants={x["module"]:x["level"] for x in c.execute(
            "SELECT module,level FROM hq_grants WHERE rank_id=?",(u["rank"],)).fetchall()}
        if grants.get("*")=="approve":
            allowed=set(MODULES)
        else:
            allowed={module for module in MODULES if module in grants}
        data={"generated_at":now(),"membership":{
            "active":c.execute("SELECT count(*) FROM membership WHERE status='approved'").fetchone()[0],
            "pending":c.execute("SELECT count(*) FROM membership WHERE status='pending'").fetchone()[0],
            "ranks":c.execute("SELECT count(DISTINCT rank) FROM membership WHERE status='approved' AND rank IS NOT NULL").fetchone()[0]
        },"permissions":sorted(allowed),"sections":{}}
        if allowed & {"treasury","inventory","assets","operations","cases","business","business_analytics"}:
            visible_modules=sorted(allowed)
            placeholders=",".join("?" for _ in visible_modules)
            data["sections"]["approvals"]={
                "pending":c.execute("SELECT count(*) FROM hq_approval_request WHERE status='pending' AND module IN ("+placeholders+")",visible_modules).fetchone()[0]
            } if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hq_approval_request'").fetchone() else {"pending":0}
        if "treasury" in allowed:
            posted=c.execute("SELECT coalesce(sum(amount),0) FROM hq_money WHERE state='posted'").fetchone()[0]
            pending=c.execute("SELECT count(*) FROM hq_money WHERE state='pending'").fetchone()[0]
            flow=c.execute("SELECT coalesce(sum(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,coalesce(sum(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense FROM hq_money WHERE state='posted' AND created>=?",(now()-30*86400,)).fetchone()
            data["sections"]["treasury"]={"balance":posted,"pending_transactions":pending,
                "accounts":c.execute("SELECT count(*) FROM hq_treasury_account WHERE active=1").fetchone()[0],
                "income_30d":flow["income"],"expense_30d":flow["expense"]}
        if "inventory" in allowed:
            valuation=_cost_summary(c)
            data["sections"]["inventory"]={"items":c.execute("SELECT count(*) FROM hq_item").fetchone()[0],
                "vaults":c.execute("SELECT count(*) FROM hq_vault").fetchone()[0],
                "stock_units":c.execute("SELECT coalesce(sum(qty),0) FROM hq_stock").fetchone()[0],
                "low_stock":c.execute("SELECT count(*) FROM (SELECT i.id,coalesce(sum(s.qty),0) total FROM hq_item i LEFT JOIN hq_stock s ON s.item=i.id GROUP BY i.id HAVING total<i.min_stock)").fetchone()[0],
                "stock_value":sum(x["value"] for x in valuation),
                "unvalued_units":sum(x["unvalued_qty"] for x in valuation)}
        if "assets" in allowed:
            data["sections"]["assets"]={"total":c.execute("SELECT count(*) FROM hq_asset").fetchone()[0],
                "available":c.execute("SELECT count(*) FROM hq_asset WHERE status='available'").fetchone()[0],
                "assigned":c.execute("SELECT count(*) FROM hq_asset WHERE status='assigned'").fetchone()[0],
                "maintenance":c.execute("SELECT count(*) FROM hq_asset WHERE status='maintenance'").fetchone()[0],
                "retired":c.execute("SELECT count(*) FROM hq_asset WHERE status='retired'").fetchone()[0],
                "acquisition_cost":c.execute("SELECT coalesce(sum(purchase_cost),0) FROM hq_asset WHERE status<>'retired'").fetchone()[0]}
        if "operations" in allowed:
            data["sections"]["operations"]={"upcoming":c.execute("SELECT count(*) FROM hq_operation_event WHERE status IN ('planned','in_progress') AND datetime(ends_at)>=datetime('now')").fetchone()[0],
                "in_progress":c.execute("SELECT count(*) FROM hq_operation_event WHERE status='in_progress'").fetchone()[0],
                "completed":c.execute("SELECT count(*) FROM hq_operation_event WHERE status='completed'").fetchone()[0],
                "recent":rows(c,"SELECT id,title,category,division,owner,starts_at,ends_at,status FROM hq_operation_event WHERE status NOT IN ('cancelled','archived') ORDER BY starts_at DESC LIMIT 5")}
        if "cases" in allowed:
            evidence_ready=all(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                for table in ("hq_evidence_file","hq_evidence_event"))
            data["sections"]["cases"]={"total":c.execute("SELECT count(*) FROM hq_case").fetchone()[0],
                "open":c.execute("SELECT count(*) FROM hq_case WHERE status='open'").fetchone()[0],
                "review":c.execute("SELECT count(*) FROM hq_case WHERE status='review'").fetchone()[0],
                "closed":c.execute("SELECT count(*) FROM hq_case WHERE status='closed'").fetchone()[0],
                "evidence_files":c.execute("SELECT count(*) FROM hq_evidence_file").fetchone()[0] if evidence_ready else 0,
                "evidence_events":c.execute("SELECT count(*) FROM hq_evidence_event").fetchone()[0] if evidence_ready else 0,
                "integrity_failures":c.execute("SELECT count(*) FROM hq_evidence_event WHERE action='integrity_failed'").fetchone()[0] if evidence_ready else 0}
        if "business_analytics" in allowed:
            data["sections"]["business_analytics"]={"available":True}
        if u["admin"]:
            data["sections"]["security"]={
                "audit_events_7d":c.execute("SELECT count(*) FROM audit WHERE created>=?",(now()-7*86400,)).fetchone()[0],
                "flagged_events_7d":c.execute("SELECT count(*) FROM audit WHERE created>=? AND (lower(action) LIKE '%integrity%' OR lower(action) LIKE '%denied%' OR lower(action) LIKE '%failed%')",(now()-7*86400,)).fetchone()[0],
                "recent":rows(c,"SELECT a.id,a.action,a.target,a.created,u.username FROM audit a LEFT JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 8")}
        return reply(data)


# Advanced Financial Reporting — posted-ledger reporting and monthly budgets.
from datetime import date, datetime, timedelta, timezone
from fastapi.responses import Response
import csv, io

class FinancialBudget(BaseModel):
    period:str=Field(min_length=7,max_length=7)
    division:str=Field(default="",max_length=100)
    category:str=Field(default="",max_length=60)
    amount:int=Field(ge=0,le=1000000000000000)

def _financial_period(value):
    try: parsed=datetime.strptime(value,"%Y-%m").date().replace(day=1)
    except (TypeError,ValueError): fail(400,"Periods must use YYYY-MM")
    if parsed.strftime("%Y-%m")!=value: fail(400,"Periods must use YYYY-MM")
    return parsed

def _financial_bounds(start,end):
    first=_financial_period(start);last=_financial_period(end)
    if last<first: fail(400,"End period must not precede start period")
    count=(last.year-first.year)*12+last.month-first.month+1
    if count>36: fail(400,"A report can cover at most 36 months")
    next_month=date(last.year+(last.month==12),1 if last.month==12 else last.month+1,1)
    tz=timezone(timedelta(hours=7))
    return int(datetime(first.year,first.month,1,tzinfo=tz).timestamp()),int(datetime(next_month.year,next_month.month,1,tzinfo=tz).timestamp()),count

def _financial_report_data(c,start,end):
    first=_financial_period(start);last=_financial_period(end)
    begin,finish,count=_financial_bounds(start,end)
    previous_last=first-timedelta(days=1)
    previous_index=first.year*12+first.month-1-count
    previous_first=date(previous_index//12,previous_index%12+1,1)
    previous_start=int(datetime(previous_first.year,previous_first.month,1,tzinfo=timezone(timedelta(hours=7))).timestamp())
    previous_finish=begin
    opening=c.execute("SELECT coalesce(sum(amount),0) FROM hq_money WHERE state='posted' AND created<?",(begin,)).fetchone()[0]
    monthly=rows(c,"""SELECT strftime('%Y-%m',datetime(created,'unixepoch','+7 hours')) period,
        coalesce(sum(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,
        coalesce(sum(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense,count(*) transactions
        FROM hq_money WHERE state='posted' AND created>=? AND created<?
        GROUP BY period ORDER BY period""",(begin,finish))
    monthly_map={x["period"]:x for x in monthly};periods=[];cursor=first
    while cursor<=last:
        x=monthly_map.get(cursor.strftime("%Y-%m"),{})
        periods.append({"period":cursor.strftime("%Y-%m"),"income":x.get("income",0),"expense":x.get("expense",0),
            "net":x.get("income",0)-x.get("expense",0),"transactions":x.get("transactions",0)})
        cursor=date(cursor.year+(cursor.month==12),1 if cursor.month==12 else cursor.month+1,1)
    summary=c.execute("""SELECT coalesce(sum(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,
        coalesce(sum(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense,count(*) transactions
        FROM hq_money WHERE state='posted' AND created>=? AND created<?""",(begin,finish)).fetchone()
    prior=c.execute("""SELECT coalesce(sum(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,
        coalesce(sum(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense,count(*) transactions
        FROM hq_money WHERE state='posted' AND created>=? AND created<?""",(previous_start,previous_finish)).fetchone()
    by_division=rows(c,"""SELECT coalesce(r.name,'Unassigned') division,
        coalesce(sum(CASE WHEN m.amount>0 THEN m.amount ELSE 0 END),0) income,
        coalesce(sum(CASE WHEN m.amount<0 THEN -m.amount ELSE 0 END),0) expense,count(*) transactions
        FROM hq_money m LEFT JOIN membership mb ON mb.uid=m.actor LEFT JOIN ranks r ON r.id=mb.rank
        WHERE m.state='posted' AND m.created>=? AND m.created<?
        GROUP BY division ORDER BY division""",(begin,finish))
    by_category=rows(c,"""SELECT category,coalesce(sum(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,
        coalesce(sum(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense,count(*) transactions
        FROM hq_money WHERE state='posted' AND created>=? AND created<?
        GROUP BY category ORDER BY category""",(begin,finish))
    budgets=rows(c,"""SELECT period,division,category,amount FROM hq_financial_budget
        WHERE period>=? AND period<=? ORDER BY period,division,category""",(start,end))
    for budget in budgets:
        budget_start,budget_finish,_=_financial_bounds(budget["period"],budget["period"])
        clauses=["m.state='posted'","m.amount<0","m.created>=?","m.created<?"];params=[budget_start,budget_finish]
        if budget["division"]:
            clauses.append("coalesce(r.name,'Unassigned')=?");params.append(budget["division"])
        if budget["category"]:
            clauses.append("m.category=?");params.append(budget["category"])
        budget["actual_expense"]=c.execute("SELECT coalesce(sum(-m.amount),0) FROM hq_money m LEFT JOIN membership mb ON mb.uid=m.actor LEFT JOIN ranks r ON r.id=mb.rank WHERE "+" AND ".join(clauses),params).fetchone()[0]
        budget["variance"]=budget["amount"]-budget["actual_expense"]
        budget["utilization_pct"]=round(budget["actual_expense"]*100/budget["amount"],2) if budget["amount"] else None
    budget_total=sum(x["amount"] for x in budgets);expense_total=summary["expense"]
    return {"period":{"start":start,"end":end,"months":count},
        "summary":{"opening_balance":opening,"income":summary["income"],"expense":expense_total,
            "net_cash_flow":summary["income"]-expense_total,"closing_balance":opening+summary["income"]-expense_total,
            "transactions":summary["transactions"],"budget_total":budget_total,
            "budget_remaining":budget_total-expense_total if budgets else None,
            "budget_utilization_pct":round(expense_total*100/budget_total,2) if budget_total else None},
        "comparison":{"previous_start":previous_first.strftime("%Y-%m"),"previous_end":previous_last.strftime("%Y-%m"),
            "income":prior["income"],"expense":prior["expense"],"net_cash_flow":prior["income"]-prior["expense"],
            "income_change":summary["income"]-prior["income"],"expense_change":expense_total-prior["expense"],
            "net_change":(summary["income"]-expense_total)-(prior["income"]-prior["expense"])},
        "monthly":periods,"divisions":by_division,"categories":by_category,"budgets":budgets,
        "budget_note":"Expenses are attributed to the member's current approved rank, not a historical rank snapshot. Internal account transfers are excluded. Only posted Treasury ledger entries are included.",
        "generated_at":now()}

@router.get("/ops/financial-reports")
def financial_reports(r:Request,start:str,end:str):
    with db() as c:
        privilege(c,r,"financial_reports")
        return reply(_financial_report_data(c,start,end))

@router.post("/ops/financial-reports/budgets")
def financial_budget_save(p:FinancialBudget,r:Request):
    origin(r);_financial_period(p.period)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"financial_reports","write")
        division=clean(p.division,100,required=False);category=clean(p.category,60,required=False)
        c.execute("""INSERT INTO hq_financial_budget(period,division,category,amount,actor,updated)
            VALUES(?,?,?,?,?,?) ON CONFLICT(period,division,category)
            DO UPDATE SET amount=excluded.amount,actor=excluded.actor,updated=excluded.updated""",
            (p.period,division,category,p.amount,u["id"],now()))
        audit(c,u["id"],"financial.budget.save",None)
    return {"ok":True}

@router.delete("/ops/financial-reports/budgets")
def financial_budget_delete(r:Request,period:str,division:str="",category:str=""):
    origin(r);_financial_period(period)
    with db() as c:
        c.execute("BEGIN IMMEDIATE");u=privilege(c,r,"financial_reports","write")
        result=c.execute("DELETE FROM hq_financial_budget WHERE period=? AND division=? AND category=?",
            (period,clean(division,100,required=False),clean(category,60,required=False)))
        if not result.rowcount: fail(404,"Budget not found")
        audit(c,u["id"],"financial.budget.delete",None)
    return {"ok":True}

@router.get("/ops/financial-reports/export")
def financial_report_export(r:Request,start:str,end:str,format:str="csv"):
    with db() as c:
        privilege(c,r,"financial_reports");data=_financial_report_data(c,start,end)
    filename=f"highest-financial-report-{start.replace('-','')}-{end.replace('-','')}"
    if format=="csv":
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(["THE HIGHEST HQ — FINANCIAL REPORT",start,end]);writer.writerow(["Metric","Amount"])
        for key,value in data["summary"].items(): writer.writerow([key,value])
        writer.writerow([]);writer.writerow(["Monthly cash flow"]);writer.writerow(["Period","Income","Expense","Net cash flow","Transactions"])
        for x in data["monthly"]: writer.writerow([x["period"],x["income"],x["expense"],x["net"],x["transactions"]])
        writer.writerow([]);writer.writerow(["Division performance"]);writer.writerow(["Division","Income","Expense","Net","Transactions"])
        for x in data["divisions"]: writer.writerow([x["division"],x["income"],x["expense"],x["income"]-x["expense"],x["transactions"]])
        writer.writerow([]);writer.writerow(["Category performance"]);writer.writerow(["Category","Income","Expense","Net","Transactions"])
        for x in data["categories"]: writer.writerow([x["category"],x["income"],x["expense"],x["income"]-x["expense"],x["transactions"]])
        writer.writerow([]);writer.writerow(["Monthly budgets"]);writer.writerow(["Period","Division","Category","Budget"])
        for x in data["budgets"]: writer.writerow([x["period"],x["division"],x["category"],x["amount"]])
        writer.writerow([]);writer.writerow(["Data basis",data["budget_note"]])
        return Response("\ufeff"+stream.getvalue(),media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":f'attachment; filename="{filename}.csv"'})
    if format=="xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill
        from openpyxl.utils import get_column_letter
        wb=Workbook();ws=wb.active;ws.title="Executive Summary"
        ws.append(["THE HIGHEST HQ — FINANCIAL REPORT"]);ws.append(["Period",start,end]);ws.append([])
        ws.append(["Metric","Amount"])
        for key,value in data["summary"].items(): ws.append([key,value])
        def sheet(name,headers,items,keys):
            sh=wb.create_sheet(name);sh.append(headers)
            for item in items: sh.append([item.get(k) for k in keys])
            return sh
        sheet("Monthly Cash Flow",["Period","Income","Expense","Net Cash Flow","Transactions"],data["monthly"],["period","income","expense","net","transactions"])
        divs=[{**x,"net":x["income"]-x["expense"]} for x in data["divisions"]]
        sheet("Division Performance",["Division","Income","Expense","Net","Transactions"],divs,["division","income","expense","net","transactions"])
        cats=[{**x,"net":x["income"]-x["expense"]} for x in data["categories"]]
        sheet("Category Performance",["Category","Income","Expense","Net","Transactions"],cats,["category","income","expense","net","transactions"])
        sheet("Monthly Budgets",["Period","Division","Category","Budget"],data["budgets"],["period","division","category","amount"])
        for sh in wb.worksheets:
            sh.freeze_panes="A2";sh.auto_filter.ref=sh.dimensions
            for cell in sh[1]:
                cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="292929")
            for col in sh.columns:
                width=min(42,max(12,max((len(str(cell.value or "")) for cell in col),default=0)+2))
                sh.column_dimensions[get_column_letter(col[0].column)].width=width
        output=io.BytesIO();wb.save(output);output.seek(0)
        return Response(output.getvalue(),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":f'attachment; filename="{filename}.xlsx"'})
    if format=="pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4,landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        output=io.BytesIO();doc=SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm)
        styles=getSampleStyleSheet();story=[Paragraph("THE HIGHEST HQ — FINANCIAL REPORT",styles["Title"]),
            Paragraph(f"Reporting period: {start} to {end} · Generated from posted Treasury entries",styles["Normal"]),Spacer(1,6*mm)]
        def table(title,headers,values):
            story.append(Paragraph(title,styles["Heading2"]));t=Table([headers]+values,repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#292929")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#cccccc")),
                ("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),5)]))
            story.extend([t,Spacer(1,4*mm)])
        table("Executive Summary",["Metric","Amount"],[[k,str(v)] for k,v in data["summary"].items()])
        table("Monthly Cash Flow",["Period","Income","Expense","Net","Transactions"],[[x["period"],str(x["income"]),str(x["expense"]),str(x["net"]),str(x["transactions"])] for x in data["monthly"]])
        table("Division Performance",["Division","Income","Expense","Net","Transactions"],[[x["division"],str(x["income"]),str(x["expense"]),str(x["income"]-x["expense"]),str(x["transactions"])] for x in data["divisions"]])
        table("Category Performance",["Category","Income","Expense","Net","Transactions"],[[x["category"],str(x["income"]),str(x["expense"]),str(x["income"]-x["expense"]),str(x["transactions"])] for x in data["categories"]])
        table("Monthly Budgets",["Period","Division","Category","Budget"],[[x["period"],x["division"] or "All divisions",x["category"] or "All categories",str(x["amount"])] for x in data["budgets"]])
        story.append(Paragraph(data["budget_note"],styles["Italic"]));doc.build(story);output.seek(0)
        return Response(output.getvalue(),media_type="application/pdf",
            headers={"Content-Disposition":f'attachment; filename="{filename}.pdf"'})
    fail(400,"Supported export formats are csv, xlsx and pdf")
