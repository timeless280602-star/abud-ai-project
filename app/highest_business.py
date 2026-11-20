"""Fictional in-game business orders and POS. No real payments."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.highest import db, origin, clean, fail, audit
from app.highest_ops import privilege, rows, reply, now, change

router=APIRouter(prefix="/highest/api")
STATES={"pending":{"confirmed","cancelled"},"confirmed":{"processing","cancelled"},"processing":{"ready","cancelled"},"ready":{"completed","cancelled"},"completed":set(),"cancelled":set()}
def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_price(item INTEGER PRIMARY KEY REFERENCES hq_item(id),buy INTEGER NOT NULL CHECK(buy>=0),sell INTEGER NOT NULL CHECK(sell>=0),updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_order(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),nonce TEXT NOT NULL,group_name TEXT NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),status TEXT NOT NULL,notes TEXT NOT NULL,vault INTEGER REFERENCES hq_vault(id),treasury INTEGER NOT NULL DEFAULT 0,money_id INTEGER REFERENCES hq_money(id),version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(actor,nonce));
        CREATE TABLE IF NOT EXISTS hq_order_line(order_id INTEGER REFERENCES hq_order(id),item INTEGER REFERENCES hq_item(id),qty INTEGER NOT NULL CHECK(qty>0),buy INTEGER NOT NULL,sell INTEGER NOT NULL,PRIMARY KEY(order_id,item));
        CREATE TABLE IF NOT EXISTS hq_order_history(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES hq_order(id),actor INTEGER REFERENCES users(id),status TEXT NOT NULL,note TEXT NOT NULL,created INTEGER NOT NULL);
        """)
class Price(BaseModel):
    item:int
    buy:int=Field(ge=0,le=1000000000)
    sell:int=Field(ge=0,le=1000000000)
class Line(BaseModel):
    item:int
    qty:int=Field(gt=0,le=100000)
class Order(BaseModel):
    nonce:str=Field(min_length=16,max_length=100)
    group_name:str=Field(min_length=1,max_length=100)
    direction:str
    lines:list[Line]=Field(min_length=1,max_length=50)
    notes:str=Field(default="",max_length=1000)
    vault:int|None=None
    treasury:bool=False
class Status(BaseModel):
    status:str
    version:int=Field(ge=1)
    note:str=Field(default="",max_length=500)
def get_order(c,oid):
    r=c.execute("SELECT * FROM hq_order WHERE id=?",(oid,)).fetchone()
    if not r: fail(404,"Order not found")
    return r
def order_data(c,r):
    out=dict(r)
    out["lines"]=rows(c,"SELECT l.*,i.name FROM hq_order_line l JOIN hq_item i ON i.id=l.item WHERE order_id=? ORDER BY i.name",(r["id"],))
    out["cost"]=sum(x["qty"]*x["buy"] for x in out["lines"])
    out["sales"]=sum(x["qty"]*x["sell"] for x in out["lines"])
    out["total"]=out["cost"] if r["direction"]=="buy" else out["sales"]
    out["estimated_margin"]=out["sales"]-out["cost"] if r["direction"]=="sell" else None
    out["money_state"]=None
    if r["money_id"]:
        money=c.execute("SELECT state FROM hq_money WHERE id=?",(r["money_id"],)).fetchone()
        out["money_state"]=money["state"] if money else None
    return out
def history(c,oid,uid,status,note):
    c.execute("INSERT INTO hq_order_history(order_id,actor,status,note,created) VALUES(?,?,?,?,?)",(oid,uid,status,note,now()))
def prices(c):
    return rows(c,"SELECT i.id,i.name,i.category,p.buy,p.sell,p.updated FROM hq_item i LEFT JOIN hq_price p ON i.id=p.item ORDER BY i.name")
@router.get("/business/prices")
def price_list(r:Request):
    with db() as c:
        privilege(c,r,"business_prices")
        return reply(prices(c))
@router.post("/business/prices")
def save_price(p:Price,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business_prices","write")
        if not c.execute("SELECT 1 FROM hq_item WHERE id=?",(p.item,)).fetchone():fail(404,"Create inventory item first")
        c.execute("INSERT INTO hq_price VALUES(?,?,?,?) ON CONFLICT(item) DO UPDATE SET buy=excluded.buy,sell=excluded.sell,updated=excluded.updated",(p.item,p.buy,p.sell,now()))
        audit(c,u["id"],"business.price",p.item)
    return {"ok":True}
@router.get("/business/orders")
def orders(r:Request):
    with db() as c:
        privilege(c,r,"business")
        return reply({"orders":[order_data(c,x) for x in c.execute("SELECT * FROM hq_order ORDER BY id DESC LIMIT 150").fetchall()],"prices":[x for x in prices(c) if x["buy"] is not None],"vaults":rows(c,"SELECT id,name FROM hq_vault ORDER BY name")})
@router.get("/business/orders/{oid}")
def order(oid:int,r:Request):
    with db() as c:
        privilege(c,r,"business")
        return reply({"order":order_data(c,get_order(c,oid)),"history":rows(c,"SELECT h.*,u.display_name FROM hq_order_history h JOIN users u ON u.id=h.actor WHERE order_id=? ORDER BY h.id",(oid,))})
@router.post("/business/orders")
def create(p:Order,r:Request):
    origin(r)
    if p.direction not in ("buy","sell"):fail(400,"Invalid transaction direction")
    if len({x.item for x in p.lines})!=len(p.lines):fail(400,"Combine duplicate items")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business","write")
        old=c.execute("SELECT id FROM hq_order WHERE actor=? AND nonce=?",(u["id"],p.nonce)).fetchone()
        if old:return {"id":old["id"],"duplicate":True}
        if p.vault is not None:
            privilege(c,r,"inventory","write")
            if not c.execute("SELECT 1 FROM hq_vault WHERE id=?",(p.vault,)).fetchone():fail(404,"Vault not found")
        if p.treasury:privilege(c,r,"treasury","write")
        items=[]
        for line in p.lines:
            price=c.execute("SELECT buy,sell FROM hq_price WHERE item=?",(line.item,)).fetchone()
            if not price:fail(400,"Set item prices before ordering")
            items.append((line.item,line.qty,price["buy"],price["sell"]))
        total=sum(x[1]*(x[2] if p.direction=="buy" else x[3]) for x in items)
        if total>1000000000000:fail(400,"Order total exceeds ledger limit")
        gid=clean(p.group_name,100)
        oid=c.execute("INSERT INTO hq_order(actor,nonce,group_name,direction,status,notes,vault,treasury,created,updated) VALUES(?,?,?,?,'pending',?,?,?,?,?)",(u["id"],p.nonce,gid,p.direction,p.notes.strip(),p.vault,int(p.treasury),now(),now())).lastrowid
        c.executemany("INSERT INTO hq_order_line VALUES(?,?,?,?,?)",[(oid,*x) for x in items])
        history(c,oid,u["id"],"pending","Order created")
        audit(c,u["id"],"business.order",oid)
    return {"id":oid}
@router.post("/business/orders/{oid}/status")
def update(oid:int,p:Status,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business","approve" if p.status in ("completed","cancelled") else "write")
        row=get_order(c,oid)
        if row["version"]!=p.version:fail(409,"Order changed; reload")
        if p.status not in STATES[row["status"]]:fail(409,"Invalid status transition")
        if p.status=="cancelled" and not p.note.strip():fail(400,"Cancellation reason required")
        mid=None
        if p.status=="completed":
            order=order_data(c,row)
            if row["vault"] is not None:
                privilege(c,r,"inventory","write")
                for line in order["lines"]:
                    change(c,u["id"],"business_"+row["direction"],row["vault"],line["item"],line["qty"] if row["direction"]=="buy" else -line["qty"],"IC order "+str(oid),"order:"+str(oid))
            if row["treasury"] and order["total"]:
                privilege(c,r,"treasury","write")
                amount=order["total"] if row["direction"]=="sell" else -order["total"]
                mid=c.execute("INSERT INTO hq_money(actor,amount,category,note,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],amount,"Business "+row["direction"],"IC order "+str(oid),now())).lastrowid
                audit(c,u["id"],"money.request",mid)
        c.execute("UPDATE hq_order SET status=?,version=version+1,updated=?,money_id=coalesce(?,money_id) WHERE id=?",(p.status,now(),mid,oid))
        history(c,oid,u["id"],p.status,p.note.strip())
        audit(c,u["id"],"business."+p.status,oid)
    return {"ok":True,"money_id":mid}
