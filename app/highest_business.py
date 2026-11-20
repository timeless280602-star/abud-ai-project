"""Fictional in-game business orders and POS. No real payments."""
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.highest import db, origin, clean, fail, audit
from app.highest_ops import privilege, rows, reply, now, change

router=APIRouter(prefix="/highest/api")
STATES={"pending":{"ready"},"ready":{"completed"},"completed":set()}

def document_number(prefix,timestamp,order_id):
    day=datetime.fromtimestamp(int(timestamp),timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{day}-{int(order_id):06d}"

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_price(item INTEGER PRIMARY KEY REFERENCES hq_item(id),buy INTEGER NOT NULL CHECK(buy>=0),sell INTEGER NOT NULL CHECK(sell>=0),updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_order(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),nonce TEXT NOT NULL,group_name TEXT NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),status TEXT NOT NULL CHECK(status IN ('pending','ready','completed')),notes TEXT NOT NULL,vault INTEGER REFERENCES hq_vault(id),treasury INTEGER NOT NULL DEFAULT 0,money_id INTEGER REFERENCES hq_money(id),version INTEGER NOT NULL DEFAULT 1,delivery_note TEXT NOT NULL DEFAULT '',completed_at INTEGER,legacy_hidden INTEGER NOT NULL DEFAULT 0,discount_scope TEXT NOT NULL DEFAULT 'none',discount_type TEXT NOT NULL DEFAULT 'none',discount_value INTEGER NOT NULL DEFAULT 0,discount_amount INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(actor,nonce));
        CREATE TABLE IF NOT EXISTS hq_order_line(order_id INTEGER REFERENCES hq_order(id),item INTEGER REFERENCES hq_item(id),qty INTEGER NOT NULL CHECK(qty>0),buy INTEGER NOT NULL,sell INTEGER NOT NULL,discount_type TEXT NOT NULL DEFAULT 'none',discount_value INTEGER NOT NULL DEFAULT 0,discount_amount INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(order_id,item));
        CREATE TABLE IF NOT EXISTS hq_order_history(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES hq_order(id),actor INTEGER REFERENCES users(id),status TEXT NOT NULL,note TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_order_documents(order_id INTEGER PRIMARY KEY REFERENCES hq_order(id) ON DELETE CASCADE,invoice_no TEXT NOT NULL UNIQUE,invoice_issued_at INTEGER NOT NULL,invoice_creator_name TEXT NOT NULL DEFAULT '',receipt_no TEXT UNIQUE,receipt_issued_at INTEGER,receipt_completed_by TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS hq_discount_policy(rank_id INTEGER PRIMARY KEY REFERENCES ranks(id) ON DELETE CASCADE,scope TEXT NOT NULL DEFAULT 'none' CHECK(scope IN ('none','all','items','both')),max_percent INTEGER NOT NULL DEFAULT 0 CHECK(max_percent BETWEEN 0 AND 100),max_fixed INTEGER NOT NULL DEFAULT 0 CHECK(max_fixed>=0),updated_by INTEGER REFERENCES users(id),updated INTEGER NOT NULL);
        """)
        order_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_order)")}
        if "delivery_note" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN delivery_note TEXT NOT NULL DEFAULT ''")
        if "completed_at" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN completed_at INTEGER")
        if "legacy_hidden" not in order_columns: c.execute("ALTER TABLE hq_order ADD COLUMN legacy_hidden INTEGER NOT NULL DEFAULT 0")
        for name,definition in (("discount_scope","TEXT NOT NULL DEFAULT 'none'"),("discount_type","TEXT NOT NULL DEFAULT 'none'"),("discount_value","INTEGER NOT NULL DEFAULT 0"),("discount_amount","INTEGER NOT NULL DEFAULT 0"),("discount_state","TEXT NOT NULL DEFAULT 'approved'"),("discount_requested_amount","INTEGER NOT NULL DEFAULT 0"),("discount_reason","TEXT NOT NULL DEFAULT ''"),("discount_reviewed_by","INTEGER REFERENCES users(id)"),("discount_review_note","TEXT NOT NULL DEFAULT ''")):
            if name not in order_columns: c.execute(f"ALTER TABLE hq_order ADD COLUMN {name} {definition}")
        line_columns={x["name"] for x in c.execute("PRAGMA table_info(hq_order_line)")}
        for name,definition in (("discount_type","TEXT NOT NULL DEFAULT 'none'"),("discount_value","INTEGER NOT NULL DEFAULT 0"),("discount_amount","INTEGER NOT NULL DEFAULT 0"),("requested_discount_amount","INTEGER NOT NULL DEFAULT 0"),("item_name","TEXT NOT NULL DEFAULT ''")):
            if name not in line_columns: c.execute(f"ALTER TABLE hq_order_line ADD COLUMN {name} {definition}")
        c.execute("UPDATE hq_order_line SET item_name=(SELECT name FROM hq_item WHERE id=hq_order_line.item) WHERE trim(item_name)=''")
        c.execute("UPDATE hq_order SET completed_at=updated WHERE status='completed' AND completed_at IS NULL")
        c.execute("UPDATE hq_order SET discount_requested_amount=discount_amount WHERE discount_requested_amount=0 AND discount_amount>0")
        c.execute("UPDATE hq_order SET discount_state='none' WHERE discount_amount=0 AND discount_requested_amount=0 AND discount_state='approved'")
        c.execute("UPDATE hq_order_line SET requested_discount_amount=discount_amount WHERE requested_discount_amount=0 AND discount_amount>0")
        c.execute("UPDATE hq_order SET legacy_hidden=1,status='pending' WHERE status='cancelled'")
        c.execute("UPDATE hq_order SET status='pending' WHERE status IN ('confirmed','processing')")
        c.execute("UPDATE hq_order SET delivery_note='Butuh pengantaran' WHERE status='ready' AND trim(delivery_note)=''")
        legacy_orders=c.execute("""SELECT o.id,o.created,o.status,o.completed_at,o.updated,u.display_name creator,
            coalesce((SELECT u2.display_name FROM hq_order_history h JOIN users u2 ON u2.id=h.actor
                WHERE h.order_id=o.id AND h.status='completed' ORDER BY h.id DESC LIMIT 1),u.display_name) completed_by
            FROM hq_order o JOIN users u ON u.id=o.actor ORDER BY o.id""").fetchall()
        for legacy in legacy_orders:
            issued=legacy["created"] or legacy["updated"] or now()
            c.execute("""INSERT OR IGNORE INTO hq_order_documents(order_id,invoice_no,invoice_issued_at,invoice_creator_name)
                VALUES(?,?,?,?)""",(legacy["id"],document_number("INV",issued,legacy["id"]),issued,legacy["creator"]))
            if legacy["status"]=="completed":
                receipt_at=legacy["completed_at"] or legacy["updated"] or issued
                c.execute("""UPDATE hq_order_documents SET receipt_no=coalesce(receipt_no,?),
                    receipt_issued_at=coalesce(receipt_issued_at,?),
                    receipt_completed_by=CASE WHEN trim(receipt_completed_by)='' THEN ? ELSE receipt_completed_by END
                    WHERE order_id=?""",(document_number("RCT",receipt_at,legacy["id"]),receipt_at,legacy["completed_by"],legacy["id"]))
class Price(BaseModel):
    item:int
    buy:int=Field(ge=0,le=1000000000)
    sell:int=Field(ge=0,le=1000000000)
class Line(BaseModel):
    item:int
    qty:int=Field(gt=0,le=100000)
    discount_type:str="none"
    discount_value:int=Field(default=0,ge=0,le=1000000000)
class Order(BaseModel):
    nonce:str=Field(min_length=16,max_length=100)
    group_name:str=Field(min_length=1,max_length=100)
    direction:str
    lines:list[Line]=Field(min_length=1,max_length=50)
    notes:str=Field(default="",max_length=1000)
    vault:int|None=None
    treasury:bool=False
    discount_scope:str="none"
    discount_type:str="none"
    discount_value:int=Field(default=0,ge=0,le=1000000000000)
    discount_reason:str=Field(default="",max_length=500)
class Status(BaseModel):
    status:str
    version:int=Field(ge=1)
    note:str=Field(default="",max_length=500)
class DiscountPolicy(BaseModel):
    rank:int
    scope:str="none"
    max_percent:int=Field(default=0,ge=0,le=100)
    max_fixed:int=Field(default=0,ge=0,le=1000000000000)
class DiscountReview(BaseModel):
    approve:bool
    note:str=Field(default="",max_length=500)
def get_order(c,oid):
    r=c.execute("""SELECT o.*,u.display_name creator,d.invoice_no,d.invoice_issued_at,
        d.invoice_creator_name,d.receipt_no,d.receipt_issued_at,d.receipt_completed_by
        FROM hq_order o JOIN users u ON u.id=o.actor
        LEFT JOIN hq_order_documents d ON d.order_id=o.id WHERE o.id=?""",(oid,)).fetchone()
    if not r: fail(404,"Order not found")
    return r
def order_data(c,r):
    out=dict(r)
    out["lines"]=rows(c,"SELECT l.*,coalesce(nullif(l.item_name,''),i.name) name FROM hq_order_line l JOIN hq_item i ON i.id=l.item WHERE order_id=? ORDER BY name",(r["id"],))
    for line in out["lines"]:
        unit=line["buy"] if r["direction"]=="buy" else line["sell"]
        line["subtotal"]=line["qty"]*unit
        line["total"]=line["subtotal"]-line["discount_amount"]
    out["cost"]=sum(x["qty"]*x["buy"] for x in out["lines"])
    out["sales"]=sum(x["qty"]*x["sell"] for x in out["lines"])
    out["subtotal"]=sum(x["subtotal"] for x in out["lines"])
    out["discount_amount"]=sum(x["discount_amount"] for x in out["lines"])
    out["requested_discount_amount"]=r["discount_requested_amount"]
    out["net_sales"]=out["sales"]-out["discount_amount"] if r["direction"]=="sell" else 0
    out["total"]=out["subtotal"]-out["discount_amount"]
    out["estimated_margin"]=out["net_sales"]-out["cost"] if r["direction"]=="sell" else None
    out["money_state"]=None
    if r["money_id"]:
        money=c.execute("SELECT state FROM hq_money WHERE id=?",(r["money_id"],)).fetchone()
        out["money_state"]=money["state"] if money else None
    return out
def history(c,oid,uid,status,note):
    c.execute("INSERT INTO hq_order_history(order_id,actor,status,note,created) VALUES(?,?,?,?,?)",(oid,uid,status,note,now()))
def prices(c):
    return rows(c,"SELECT i.id,i.name,i.category,p.buy,p.sell,p.updated FROM hq_item i LEFT JOIN hq_price p ON i.id=p.item ORDER BY i.name")
def discount_policy(c,rank):
    row=c.execute("SELECT scope,max_percent,max_fixed FROM hq_discount_policy WHERE rank_id=?",(rank,)).fetchone()
    return dict(row) if row else {"scope":"none","max_percent":0,"max_fixed":0}
def discount_scope_allowed(policy,scope):
    return (scope=="all" and policy["scope"] in ("all","both")) or (scope=="items" and policy["scope"] in ("items","both"))
@router.get("/admin/discount-policies")
def get_discount_policies(r:Request):
    with db() as c:
        privilege(c,r,admin=True)
        return reply(rows(c,"""SELECT r.id rank_id,r.name rank_name,coalesce(p.scope,'none') scope,
            coalesce(p.max_percent,0) max_percent,coalesce(p.max_fixed,0) max_fixed,p.updated,p.updated_by
            FROM ranks r LEFT JOIN hq_discount_policy p ON p.rank_id=r.id ORDER BY r.position,r.id"""))
@router.post("/admin/discount-policies")
def save_discount_policy(p:DiscountPolicy,r:Request):
    origin(r)
    if p.scope not in ("none","all","items","both"): fail(400,"Invalid discount scope")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,admin=True)
        if not c.execute("SELECT 1 FROM ranks WHERE id=?",(p.rank,)).fetchone(): fail(404,"Rank not found")
        c.execute("""INSERT INTO hq_discount_policy(rank_id,scope,max_percent,max_fixed,updated_by,updated)
            VALUES(?,?,?,?,?,?) ON CONFLICT(rank_id) DO UPDATE SET scope=excluded.scope,
            max_percent=excluded.max_percent,max_fixed=excluded.max_fixed,updated_by=excluded.updated_by,updated=excluded.updated""",
            (p.rank,p.scope,p.max_percent,p.max_fixed,u["id"],now()))
        audit(c,u["id"],"business.discount_policy",p.rank)
    return {"ok":True}
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
        u=privilege(c,r,"business")
        return reply({"orders":[order_data(c,x) for x in c.execute("""SELECT o.*,u.display_name creator,d.invoice_no,d.invoice_issued_at,
            d.invoice_creator_name,d.receipt_no,d.receipt_issued_at,d.receipt_completed_by
            FROM hq_order o JOIN users u ON u.id=o.actor LEFT JOIN hq_order_documents d ON d.order_id=o.id
            WHERE o.legacy_hidden=0 ORDER BY o.id DESC LIMIT 500""").fetchall()],"prices":[x for x in prices(c) if x["buy"] is not None],"vaults":rows(c,"SELECT id,name FROM hq_vault ORDER BY name"),"discount_policy":discount_policy(c,u["rank"])})
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
    if p.discount_scope not in ("none","all","items"): fail(400,"Invalid discount scope")
    if p.discount_type not in ("none","percent","fixed"): fail(400,"Invalid order discount type")
    if p.discount_scope=="all":
        if p.discount_type not in ("percent","fixed"): fail(400,"Choose a percentage or nominal discount for all items")
        if p.discount_type=="percent" and p.discount_value>100: fail(400,"Percentage discount cannot exceed 100")
        if any(x.discount_type!="none" or x.discount_value for x in p.lines): fail(400,"Choose either an all-items discount or item-specific discounts, not both")
    elif p.discount_scope=="items":
        if p.discount_type!="none" or p.discount_value: fail(400,"Item-specific discounts cannot be combined with an all-items discount")
    else:
        if p.discount_type!="none" or p.discount_value: fail(400,"Discount settings must be empty when discount scope is none")
        if any(x.discount_type!="none" or x.discount_value for x in p.lines): fail(400,"Item discounts require the selected-items discount scope")
    for line in p.lines:
        if line.discount_type not in ("none","percent","fixed"): fail(400,"Invalid item discount type")
        if line.discount_type=="percent" and line.discount_value>100: fail(400,"Item percentage discount cannot exceed 100")
        if line.discount_type=="none" and line.discount_value: fail(400,"A discount value requires a discount type")
        if p.discount_scope!="items" and (line.discount_type!="none" or line.discount_value): fail(400,"Item discounts require the selected-items discount scope")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business","write")
        old=c.execute("SELECT id FROM hq_order WHERE actor=? AND nonce=?",(u["id"],p.nonce)).fetchone()
        if old:return {"id":old["id"],"duplicate":True}
        policy=discount_policy(c,u["rank"])
        if p.discount_scope!="none" and not discount_scope_allowed(policy,p.discount_scope):
            fail(403,"Your rank is not authorized to use this discount scope")
        if p.discount_scope=="none" and p.discount_reason.strip(): fail(400,"Discount reason is only used for discounted orders")
        if p.vault is not None:
            privilege(c,r,"inventory","write")
            if not c.execute("SELECT 1 FROM hq_vault WHERE id=?",(p.vault,)).fetchone():fail(404,"Vault not found")
        if p.treasury:privilege(c,r,"treasury","write")
        items=[]
        for line in p.lines:
            price=c.execute("SELECT p.buy,p.sell,i.name FROM hq_price p JOIN hq_item i ON i.id=p.item WHERE p.item=?",(line.item,)).fetchone()
            if not price:fail(400,"Set item prices before ordering")
            items.append({"item":line.item,"name":price["name"],"qty":line.qty,"buy":price["buy"],"sell":price["sell"],"discount_type":line.discount_type,"discount_value":line.discount_value})
        subtotals=[x["qty"]*(x["buy"] if p.direction=="buy" else x["sell"]) for x in items]
        subtotal=sum(subtotals)
        if subtotal>1000000000000:fail(400,"Order subtotal exceeds ledger limit")
        line_discounts=[0 for _ in items]
        if p.discount_scope=="all":
            if p.discount_type=="percent":
                discount=min(subtotal,(subtotal*p.discount_value+50)//100)
            else:
                discount=min(subtotal,p.discount_value)
            if subtotal:
                shares=[(subtotal_i*discount)//subtotal for subtotal_i in subtotals]
                remainders=[(subtotal_i*discount)%subtotal for subtotal_i in subtotals]
                remainder=discount-sum(shares)
                for index in sorted(range(len(items)),key=lambda i:(-remainders[i],i))[:remainder]:
                    shares[index]+=1
                line_discounts=shares
        elif p.discount_scope=="items":
            for index,item in enumerate(items):
                base=subtotals[index]
                if item["discount_type"]=="percent":
                    line_discounts[index]=min(base,(base*item["discount_value"]+50)//100)
                elif item["discount_type"]=="fixed":
                    line_discounts[index]=min(base,item["discount_value"]*item["qty"])
        for index,item in enumerate(items):
            item["requested_discount_amount"]=line_discounts[index]
        requested_discount=sum(line_discounts)
        needs_approval=False
        if requested_discount:
            if p.discount_scope=="all" and p.discount_type=="percent" and p.discount_value>policy["max_percent"]:
                needs_approval=True
            if p.discount_scope=="items" and any(x["discount_type"]=="percent" and x["discount_value"]>policy["max_percent"] for x in items):
                needs_approval=True
            if requested_discount>policy["max_fixed"]:
                needs_approval=True
        if requested_discount and not p.discount_reason.strip():
            fail(400,"A reason is required for every discounted order")
        if p.discount_reason.strip() and not requested_discount:
            fail(400,"Discount reason is only used for discounted orders")
        state="pending" if needs_approval else ("approved" if requested_discount else "none")
        effective_discount=requested_discount if state=="approved" else 0
        for index,item in enumerate(items):
            item["discount_amount"]=line_discounts[index] if state=="approved" else 0
        total=subtotal-effective_discount
        if total>1000000000000:fail(400,"Order total exceeds ledger limit")
        gid=clean(p.group_name,100)
        created_at=now()
        oid=c.execute("""INSERT INTO hq_order(actor,nonce,group_name,direction,status,notes,vault,treasury,discount_scope,discount_type,discount_value,discount_amount,discount_state,discount_requested_amount,discount_reason,created,updated)
            VALUES(?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,?)""",(u["id"],p.nonce,gid,p.direction,p.notes.strip(),p.vault,int(p.treasury),p.discount_scope,p.discount_type,p.discount_value,effective_discount,state,requested_discount,p.discount_reason.strip(),created_at,created_at)).lastrowid
        c.executemany("""INSERT INTO hq_order_line(order_id,item,item_name,qty,buy,sell,discount_type,discount_value,discount_amount,requested_discount_amount)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",[(oid,x["item"],x["name"],x["qty"],x["buy"],x["sell"],x["discount_type"],x["discount_value"],x["discount_amount"],x["requested_discount_amount"]) for x in items])
        creator_name=c.execute("SELECT display_name FROM users WHERE id=?",(u["id"],)).fetchone()["display_name"]
        c.execute("INSERT INTO hq_order_documents(order_id,invoice_no,invoice_issued_at,invoice_creator_name) VALUES(?,?,?,?)",
            (oid,document_number("INV",created_at,oid),created_at,creator_name))
        history(c,oid,u["id"],"pending","Order created"+(" · Discount approval requested" if needs_approval else ""))
        audit(c,u["id"],"business.order",oid)
        if needs_approval:audit(c,u["id"],"business.discount.request",oid)
        elif requested_discount:audit(c,u["id"],"business.discount.auto_approved",oid)
    return {"id":oid,"discount_state":state,"discount_requested_amount":requested_discount}

@router.get("/business/discount-requests")
def discount_requests(r:Request):
    with db() as c:
        privilege(c,r,"business_discounts")
        pending=rows(c,"""SELECT o.*,u.display_name creator,d.invoice_no,d.invoice_issued_at,d.invoice_creator_name,
            d.receipt_no,d.receipt_issued_at,d.receipt_completed_by FROM hq_order o JOIN users u ON u.id=o.actor
            LEFT JOIN hq_order_documents d ON d.order_id=o.id
            WHERE o.discount_state='pending' AND o.legacy_hidden=0 ORDER BY o.created,o.id LIMIT 200""")
        return reply({"requests":[order_data(c,x) for x in pending]})
@router.post("/business/orders/{oid}/discount-review")
def review_discount(oid:int,p:DiscountReview,r:Request):
    origin(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business_discounts","approve")
        row=get_order(c,oid)
        if row["discount_state"]!="pending": fail(409,"Discount request is no longer pending")
        if row["actor"]==u["id"]: fail(403,"You cannot approve or reject your own discount request")
        if not p.approve and not p.note.strip(): fail(400,"A rejection reason is required")
        if p.approve:
            c.execute("UPDATE hq_order SET discount_state='approved',discount_amount=discount_requested_amount,discount_reviewed_by=?,discount_review_note=?,version=version+1,updated=? WHERE id=?",
                (u["id"],p.note.strip(),now(),oid))
            c.execute("UPDATE hq_order_line SET discount_amount=requested_discount_amount WHERE order_id=?",(oid,))
            history(c,oid,u["id"],"discount_approved",p.note.strip() or "Discount approved")
            audit(c,u["id"],"business.discount.approve",oid)
        else:
            c.execute("UPDATE hq_order SET discount_state='rejected',discount_amount=0,discount_reviewed_by=?,discount_review_note=?,version=version+1,updated=? WHERE id=?",
                (u["id"],p.note.strip(),now(),oid))
            c.execute("UPDATE hq_order_line SET discount_amount=0 WHERE order_id=?",(oid,))
            history(c,oid,u["id"],"discount_rejected",p.note.strip())
            audit(c,u["id"],"business.discount.reject",oid)
    return {"ok":True,"discount_state":"approved" if p.approve else "rejected"}

@router.post("/business/orders/{oid}/status")
def update(oid:int,p:Status,r:Request):
    origin(r)
    if p.status not in ("ready","completed"): fail(400,"Only Pending, Ready and Completed order statuses are supported")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        u=privilege(c,r,"business","approve" if p.status=="completed" else "write")
        row=get_order(c,oid)
        if row["version"]!=p.version: fail(409,"Order changed; reload")
        if row["discount_state"]=="pending": fail(409,"Discount approval is still pending")
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
                    change(c,u["id"],"business_"+row["direction"],row["vault"],line["item"],line["qty"] if row["direction"]=="buy" else -line["qty"],"IC order "+str(oid),"order:"+str(oid),unit_price=unit_price,movement_value=line["total"])
            if row["treasury"] and order["total"]:
                privilege(c,r,"treasury","write")
                amount=order["total"] if row["direction"]=="sell" else -order["total"]
                mid=c.execute("INSERT INTO hq_money(actor,amount,category,note,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],amount,"Business "+row["direction"],"IC order "+str(oid),now())).lastrowid
                audit(c,u["id"],"money.request",mid)
        completed_at=now() if p.status=="completed" else row["completed_at"]
        note=clean(p.note,500) if p.note.strip() else ("Butuh pengantaran" if p.status=="ready" else "Order completed and retained for analytics")
        c.execute("UPDATE hq_order SET status=?,version=version+1,updated=?,delivery_note=?,completed_at=? WHERE id=?",(p.status,now(),delivery_note,completed_at,oid))
        if p.status=="completed":
            completed_by=c.execute("SELECT display_name FROM users WHERE id=?",(u["id"],)).fetchone()["display_name"]
            c.execute("""UPDATE hq_order_documents SET receipt_no=coalesce(receipt_no,?),
                receipt_issued_at=coalesce(receipt_issued_at,?),receipt_completed_by=CASE
                WHEN trim(receipt_completed_by)='' THEN ? ELSE receipt_completed_by END WHERE order_id=?""",
                (document_number("RCT",completed_at,oid),completed_at,completed_by,oid))
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
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy-l.discount_amount ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.discount_amount ELSE 0 END),0) sales_discounts,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.discount_amount ELSE 0 END),0) purchase_discounts,
            coalesce(sum(l.discount_amount),0) total_discounts,
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
        settlements=dict(c.execute("""SELECT
            coalesce(sum(CASE WHEN m.state='pending' THEN 1 ELSE 0 END),0) pending_settlements,
            coalesce(sum(CASE WHEN m.state='pending' THEN m.amount ELSE 0 END),0) pending_settlement_value,
            coalesce(sum(CASE WHEN m.state='posted' THEN m.amount ELSE 0 END),0) posted_settlement_value,
            coalesce(sum(CASE WHEN m.state='rejected' THEN 1 ELSE 0 END),0) rejected_settlements
            FROM hq_order o JOIN hq_money m ON m.id=o.money_id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?""",args).fetchone())
        summary.update(settlements)
        stock_value=dict(c.execute("""SELECT
            coalesce(sum(s.qty*coalesce(p.buy,0)),0) stock_value_estimate,
            coalesce(sum(CASE WHEN p.item IS NULL THEN s.qty ELSE 0 END),0) unpriced_stock_qty
            FROM hq_stock s LEFT JOIN hq_price p ON p.item=s.item""").fetchone())
        summary.update(stock_value)
        groups=rows(c,"""SELECT o.group_name,count(DISTINCT o.id) completed_orders,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy-l.discount_amount ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.discount_amount ELSE 0 END),0) sales_discounts,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.discount_amount ELSE 0 END),0) purchase_discounts,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount-l.qty*l.buy ELSE 0 END),0) estimated_gross_profit
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY o.group_name ORDER BY sales_revenue DESC,purchase_spend DESC LIMIT 50""",args)
        products=rows(c,"""SELECT i.id item_id,i.name item_name,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty ELSE 0 END),0) units_sold,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.discount_amount ELSE 0 END),0) sales_discounts,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.buy ELSE 0 END),0) estimated_cogs,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount-l.qty*l.buy ELSE 0 END),0) estimated_gross_profit,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty ELSE 0 END),0) units_purchased,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.discount_amount ELSE 0 END),0) purchase_discounts,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy-l.discount_amount ELSE 0 END),0) purchase_spend
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id JOIN hq_item i ON i.id=l.item
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY i.id ORDER BY sales_revenue DESC,units_sold DESC LIMIT 100""",args)
        trend=rows(c,"""SELECT strftime('%Y-%m-%d',o.completed_at,'unixepoch') day,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy-l.discount_amount ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount-l.qty*l.buy ELSE 0 END),0) estimated_gross_profit
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
        stock=rows(c,"""SELECT v.name vault_name,i.name item_name,coalesce(s.qty,0) qty,i.min_stock,
            CASE WHEN coalesce(s.qty,0)<i.min_stock THEN 1 ELSE 0 END low_stock
            FROM hq_vault v CROSS JOIN hq_item i
            LEFT JOIN hq_stock s ON s.vault=v.id AND s.item=i.id
            WHERE coalesce(s.qty,0)>0 OR i.min_stock>0
            ORDER BY low_stock DESC,v.name,i.name LIMIT 500""")
        low_stock=rows(c,"""SELECT i.name item_name,coalesce(sum(s.qty),0) total_qty,i.min_stock
            FROM hq_item i LEFT JOIN hq_stock s ON s.item=i.id
            GROUP BY i.id HAVING coalesce(sum(s.qty),0)<i.min_stock
            ORDER BY i.name LIMIT 100""")
        member_activity=rows(c,"""SELECT o.actor,u.display_name,
            count(DISTINCT o.id) transactions_created,
            count(DISTINCT CASE WHEN o.status='pending' THEN o.id END) pending_orders,
            count(DISTINCT CASE WHEN o.status='ready' THEN o.id END) ready_orders,
            count(DISTINCT CASE WHEN o.status='completed' THEN o.id END) completed_orders_created,
            count(DISTINCT CASE WHEN o.direction='sell' THEN o.id END) sales_orders_created,
            count(DISTINCT CASE WHEN o.direction='buy' THEN o.id END) purchase_orders_created
            FROM hq_order o JOIN users u ON u.id=o.actor
            WHERE o.legacy_hidden=0 AND o.created>=? AND o.created<?
            GROUP BY o.actor,u.display_name ORDER BY transactions_created DESC,u.display_name""",args)
        member_finance=rows(c,"""SELECT o.actor,
            count(DISTINCT CASE WHEN o.direction='sell' THEN o.id END) completed_sales_orders,
            count(DISTINCT CASE WHEN o.direction='buy' THEN o.id END) completed_purchase_orders,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount ELSE 0 END),0) sales_revenue,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.qty*l.buy-l.discount_amount ELSE 0 END),0) purchase_spend,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.discount_amount ELSE 0 END),0) sales_discounts,
            coalesce(sum(CASE WHEN o.direction='buy' THEN l.discount_amount ELSE 0 END),0) purchase_discounts,
            coalesce(sum(CASE WHEN o.direction='sell' THEN l.qty*l.sell-l.discount_amount-l.qty*l.buy ELSE 0 END),0) estimated_gross_profit
            FROM hq_order o JOIN hq_order_line l ON l.order_id=o.id
            WHERE o.status='completed' AND o.legacy_hidden=0 AND o.completed_at>=? AND o.completed_at<?
            GROUP BY o.actor""",args)
        finance_by_actor={x["actor"]:x for x in member_finance}
        members=[]
        for member in member_activity:
            member.update(finance_by_actor.get(member["actor"],{"completed_sales_orders":0,"completed_purchase_orders":0,"sales_revenue":0,"purchase_spend":0,"sales_discounts":0,"purchase_discounts":0,"estimated_gross_profit":0}))
            member["completed_order_count"]=member["completed_sales_orders"]+member["completed_purchase_orders"]
            members.append(member)
        finance_actors={x["actor"] for x in member_finance}
        known_actors={x["actor"] for x in members}
        if finance_actors-known_actors:
            for actor in finance_actors-known_actors:
                detail=finance_by_actor[actor]
                user=c.execute("SELECT display_name FROM users WHERE id=?",(actor,)).fetchone()
                members.append({"actor":actor,"display_name":user["display_name"] if user else "Former member",
                    "transactions_created":0,"pending_orders":0,"ready_orders":0,"completed_orders_created":0,
                    "sales_orders_created":0,"purchase_orders_created":0,
                    **detail,"completed_order_count":detail["completed_sales_orders"]+detail["completed_purchase_orders"]})
        members.sort(key=lambda x:(-x["transactions_created"],-x["sales_revenue"],x["display_name"].lower()))
        return reply({"period":{"start":start,"end":end},"summary":summary,
            "groups":groups,"products":products,"trend":trend,"flow":flow,
            "members":members,"stock":stock,"low_stock":low_stock,
            "data_quality":{"unvalued_movement_qty":flow["unvalued_movement_qty"],
            "gross_profit_basis":"Estimated from the buy-price snapshot stored on completed sales orders; not FIFO/weighted-average accounting.",
            "flow_valuation":"Only movements with a recorded unit-price snapshot contribute to valued input/output totals."}})
