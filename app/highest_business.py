"""Fictional in-game business orders and POS. No real payments."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.highest import db, origin, clean, fail, audit
from app.highest_ops import privilege, rows, reply, now, change

router=APIRouter(prefix="/highest/api")
STATES={"pending":{"ready"},"ready":{"completed"},"completed":set()}
def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_price(item INTEGER PRIMARY KEY REFERENCES hq_item(id),buy INTEGER NOT NULL CHECK(buy>=0),sell INTEGER NOT NULL CHECK(sell>=0),updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_order(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),nonce TEXT NOT NULL,group_name TEXT NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),status TEXT NOT NULL CHECK(status IN ('pending','ready','completed')),notes TEXT NOT NULL,vault INTEGER REFERENCES hq_vault(id),treasury INTEGER NOT NULL DEFAULT 0,money_id INTEGER REFERENCES hq_money(id),version INTEGER NOT NULL DEFAULT 1,delivery_note TEXT NOT NULL DEFAULT '',completed_at INTEGER,legacy_hidden INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(actor,nonce));
        CREATE TABLE IF NOT EXISTS hq_order_line(order_id INTEGER REFERENCES hq_order(id),item INTEGER REFERENCES hq_item(id),qty INTEGER NOT NULL CHECK(qty>0),buy INTEGER NOT NULL,sell INTEGER NOT NULL,PRIMARY KEY(order_id,item));
        CREATE TABLE IF NOT EXISTS hq_order_history(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES hq_order(id),actor INTEGER REFERENCES users(id),status TEXT NOT NULL,note TEXT NOT NULL,created INTEGER NOT NULL);
        """)
        order_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_order)")}
        if "delivery_note" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN delivery_note TEXT NOT NULL DEFAULT ''")
        if "completed_at" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN completed_at INTEGER")
        if "legacy_hidden" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN legacy_hidden INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE hq_order SET completed_at=updated WHERE status='completed' AND completed_at IS NULL")
        c.execute("UPDATE hq_order SET legacy_hidden=1,status='pending' WHERE status='cancelled'")
        c.execute("UPDATE hq_order SET status='pending' WHERE status IN ('confirmed','processing')")
        c.execute("UPDATE hq_order SET delivery_note='Butuh pengantaran' WHERE status='ready' AND trim(delivery_note)=''")
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
        return reply({"orders":[order_data(c,x) for x in c.execute("SELECT * FROM hq_order WHERE legacy_hidden=0 ORDER BY id DESC LIMIT 500").fetchall()],"prices":[x for x in prices(c) if x["buy"] is not None],"vaults":rows(c,"SELECT id,name FROM hq_vault ORDER BY name")})
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
    if p.status not in ("ready","completed"): fail(400,"Only Pending, Ready and Completed order statuses are supported")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business","approve" if p.status=="completed" else "write")
        row=get_order(c,oid)
        if row["version"]!=p.version: fail(409,"Order changed; reload")
        if p.status not in STATES.get(row["status"],set()): fail(409,"Invalid status transition")
        mid=None
        delivery_note=row["delivery_note"]
        if p.status=="ready":
            delivery_note=clean(p.note,500) if p.note.strip() else "Butuh pengantaran"
        if p.status=="completed":
            order=order_data(c,row)
            if row["vault"] is not None:
                privilege(c,r,"inventory","write")
                for line in order["lines"]:
                    unit_price=line["buy"] if row["direction"]=="buy" else line["sell"]
                    change(c,u["id"],"business_"+row["direction"],row["vault"],line["item"],line["qty"] if row["direction"]=="buy" else -line["qty"],"IC order "+str(oid),"order:"+str(oid),unit_price=unit_price)
            if row["treasury"] and order["total"]:
                privilege(c,r,"treasury","write")
                amount=order["total"] if row["direction"]=="sell" else -order["total"]
                mid=c.execute("INSERT INTO hq_money(actor,amount,category,note,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],amount,"Business "+row["direction"],"IC order "+str(oid),now())).lastrowid
                audit(c,u["id"],"money.request",mid)
        completed_at=now() if p.status=="completed" else row["completed_at"]
        note=clean(p.note,500) if p.note.strip() else ("Butuh pengantaran" if p.status=="ready" else "Order completed and retained for analytics")
        c.execute("UPDATE hq_order SET status=?,version=version+1,updated=?,delivery_note=?,completed_at=? WHERE id=?",(p.status,now(),delivery_note,completed_at,oid))
        history(c,oid,u["id"],p.status,note)
        audit(c,u["id"],"business."+p.status,oid)
    return {"ok":True,"money_id":mid}

@router.get("/business/analytics")
def analytics(r:Request,start:int|None=None,end:int|None=None):
    with db() as c:
        privilege(c,r,"business_analytics")
        end=now()+1 if end is None else end
        start=end-30*86400 if start is None else start
        if start<0 or end<=start or end-start>5*366*86400: fail(400,"Invalid analytics date range (maximum five years)")
        args=(start,end)
        summary=dict(c.execute("""SELECT
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.buy ELSE 0 END),0) estimated_cogs,
            count(DISTINCT CASE WHEN o.direction='sell' THEN o.id END) sales_orders,
            count(DISTINCT CASE WHEN o.direction='buy' THEN o.id END) purchase_orders,
            count(DISTINCT o.id) completed_orders,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty ELSE 0 END),0) units_sold,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty ELSE 0 END),0) units_purchased
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?""",args).fetchone())
        summary["estimated_gross_profit"]=summary["sales_revenue"]-summary["estimated_cogs"]
        summary["gross_margin_pct"]=round(summary["estimated_gross_profit"]/summary["sales_revenue"]*100,2) if summary["sales_revenue"] else 0
        summary["net_order_value"]=summary["sales_revenue"]-summary["purchase_spend"]
        summary["average_sales_order"]=round(summary["sales_revenue"]/summary["sales_orders"]) if summary["sales_orders"] else 0
        summary["pending_orders"]=c.execute("SELECT count(*) FROM hq_order WHERE status='pending' AND legacy_hidden=0").fetchone()[0]
        summary["ready_orders"]=c.execute("SELECT count(*) FROM hq_order WHERE status='ready' AND legacy_hidden=0").fetchone()[0]
        summary["delivery_backlog"]=summary["ready_orders"]
        groups=rows(c,"""SELECT o.group_name,count(DISTINCT o.id) completed_orders,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*(l.sell-l.buy) ELSE 0 END),0) estimated_gross_profit
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY o.group_name ORDER BY sales_revenue DESC,purchase_spend DESC LIMIT 50""",args)
        products=rows(c,"""SELECT i.id item_id,i.name item_name,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty ELSE 0 END),0) units_sold,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.buy ELSE 0 END),0) estimated_cogs,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*(l.sell-l.buy) ELSE 0 END),0) estimated_gross_profit,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty ELSE 0 END),0) units_purchased,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy ELSE 0 END),0) purchase_spend
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id JOIN hq_item i ON i.id=l.item
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY i.id ORDER BY sales_revenue DESC,units_sold DESC LIMIT 100""",args)
        trend=rows(c,"""SELECT strftime('%Y-%m-%d',o.completed_at,'unixepoch') day,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*(l.sell-l.buy) ELSE 0 END),0) estimated_gross_profit
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY day ORDER BY day""",args)
        flow=dict(c.execute("""SELECT
            coalesce(sum(CASE WHEN delta>0 AND kind<>'transfer' THEN delta ELSE 0 END),0) input_qty,
            coalesce(sum(CASE WHEN delta<0 AND kind<>'transfer' THEN -delta ELSE 0 END),0) output_qty,
            coalesce(sum(CASE WHEN kind='transfer' AND delta>0 THEN delta ELSE 0 END),0) transfer_in_qty,
            coalesce(sum(CASE WHEN kind='transfer' AND delta<0 THEN -delta ELSE 0 END),0) transfer_out_qty,
            coalesce(sum(CASE WHEN delta>0 AND kind<>'transfer' THEN coalesce(value,0) ELSE 0 END),0) valued_input,
            coalesce(sum(CASE WHEN delta<0 AND kind<>'transfer' THEN coalesce(value,0) ELSE 0 END),0) valued_output,
            coalesce(sum(CASE WHEN value IS NULL THEN abs(delta) ELSE 0 END),0) unvalued_movement_qty,
            count(*) movement_count
            FROM hq_movement WHERE created>=? AND created<?""",args).fetchone())
        flow["by_type"]=rows(c,"""SELECT kind,count(*) movements,
            coalesce(sum(CASE WHEN delta>0 AND kind<>'transfer' THEN delta ELSE 0 END),0) input_qty,
            coalesce(sum(CASE WHEN delta<0 AND kind<>'transfer' THEN -delta ELSE 0 END),0) output_qty,
            coalesce(sum(CASE WHEN kind='transfer' AND delta>0 THEN delta ELSE 0 END),0) transfer_in_qty,
            coalesce(sum(CASE WHEN kind='transfer' AND delta<0 THEN -delta ELSE 0 END),0) transfer_out_qty,
            coalesce(sum(CASE WHEN delta>0 THEN coalesce(value,0) ELSE 0 END),0) input_value,
            coalesce(sum(CASE WHEN delta<0 THEN coalesce(value,0) ELSE 0 END),0) output_value,
            coalesce(sum(CASE WHEN value IS NULL THEN abs(delta) ELSE 0 END),0) unvalued_qty
            FROM hq_movement WHERE created>=? AND created<? GROUP BY kind ORDER BY movements DESC""",args)
        flow["by_item"]=rows(c,"""SELECT i.id item_id,i.name item_name,
            coalesce(sum(CASE WHEN m.delta>0 AND m.kind<>'transfer' THEN m.delta ELSE 0 END),0) input_qty,
            coalesce(sum(CASE WHEN m.delta<0 AND m.kind<>'transfer' THEN -m.delta ELSE 0 END),0) output_qty,
            coalesce(sum(CASE WHEN m.kind='transfer' AND m.delta>0 THEN m.delta ELSE 0 END),0) transfer_in_qty,
            coalesce(sum(CASE WHEN m.kind='transfer' AND m.delta<0 THEN -m.delta ELSE 0 END),0) transfer_out_qty,
            coalesce(sum(CASE WHEN m.delta>0 THEN coalesce(m.value,0) ELSE 0 END),0) input_value,
            coalesce(sum(CASE WHEN m.delta<0 THEN coalesce(m.value,0) ELSE 0 END),0) output_value
            FROM hq_movement m JOIN hq_item i ON i.id=m.item WHERE m.created>=? AND m.created<?
            GROUP BY i.id ORDER BY input_qty+output_qty DESC LIMIT 100""",args)
        stock=rows(c,"""SELECT v.name vault_name,i.name item_name,s.qty,i.min_stock,
            CASE WHEN s.qty<i.min_stock THEN 1 ELSE 0 END low_stock
            FROM hq_stock s JOIN hq_vault v ON v.id=s.vault JOIN hq_item i ON i.id=s.item
            ORDER BY low_stock DESC,v.name,i.name LIMIT 300""")
        low_stock=[x for x in stock if x["low_stock"]]
        return reply({"period":{"start":start,"end":end},"summary":summary,
            "groups":groups,"products":products,"trend":trend,"flow":flow,
            "stock":stock,"low_stock":low_stock,
            "data_quality":{"unvalued_movement_qty":flow["unvalued_movement_qty"],
            "gross_profit_basis":"Estimated from the buy-price snapshot stored on completed sales orders; not FIFO/weighted-average accounting.",
            "flow_valuation":"Only movements with a recorded unit-price snapshot contribute to valued input/output totals."}})
