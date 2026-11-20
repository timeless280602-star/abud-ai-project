"""Separate authentication and membership for the fictional FiveM HQ."""
import hashlib, hmac, os, re, secrets, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/highest")
assets = Path(__file__).parent / "highest_web"
cookie = "highest_session"
ttl = 7*86400

@contextmanager
def db():
    path = Path(os.getenv("HIGHEST_DATABASE_PATH",str(Path(os.getenv("ABUD_DATABASE_PATH","/app/data/abud_memory.db")).parent/"highest.db")))
    path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=10)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        with c: yield c
    finally: c.close()

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, display_name TEXT NOT NULL, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, uid INTEGER REFERENCES users(id), expires INTEGER);
        CREATE TABLE IF NOT EXISTS ranks(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL, position INTEGER NOT NULL, parent INTEGER REFERENCES ranks(id) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS membership(uid INTEGER PRIMARY KEY REFERENCES users(id), character TEXT NOT NULL, callsign TEXT NOT NULL, requested TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','revoked')), rank INTEGER REFERENCES ranks(id) ON DELETE RESTRICT, position TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor INTEGER, action TEXT, target INTEGER, created INTEGER);
        CREATE TABLE IF NOT EXISTS attempts(bucket TEXT, ts INTEGER);
        CREATE INDEX IF NOT EXISTS attempt_idx ON attempts(bucket,ts);
        CREATE TABLE IF NOT EXISTS clips(id INTEGER PRIMARY KEY, uid INTEGER REFERENCES users(id), title TEXT, url TEXT, state TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS streamers(id INTEGER PRIMARY KEY, name TEXT, platform TEXT CHECK(platform IN ('youtube','tiktok')), channel TEXT, status TEXT DEFAULT 'unknown', checked INTEGER DEFAULT 0, live_url TEXT, UNIQUE(platform,channel));
        """)

def fail(status,detail): raise HTTPException(status,detail)
def origin(r):
    if r.headers.get("origin") != os.getenv("HIGHEST_ORIGIN",os.getenv("ABUD_BASE_URL","https://abud.web.id")).rstrip("/"):
        fail(403,"Invalid origin")
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+":"+hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),600000).hex()
def clean(s,limit,required=True):
    s=s.strip()
    if len(s)>limit or (required and not s): fail(400,"Invalid input")
    return s
def audit(c,actor,action,target=None):
    c.execute("INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)",(actor,action,target,int(time.time())))
def throttle(r,name):
    now=int(time.time())
    ip=r.client.host if r.client else "unknown"
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM attempts WHERE ts<?",(now-900,))
        for bucket,limit in [(name,12),("ip:"+ip,120)]:
            if c.execute("SELECT count(*) FROM attempts WHERE bucket=?",(bucket,)).fetchone()[0]>=limit: fail(429,"Try again later")
        c.executemany("INSERT INTO attempts VALUES(?,?)",[(name,now),("ip:"+ip,now)])
def current(r,admin=False,internal=False):
    token=r.cookies.get(cookie,"")
    with db() as c:
        row=c.execute("""SELECT u.id,u.username,u.display_name,u.admin,coalesce(m.status,'community') status,m.rank,m.position
          FROM users u JOIN sessions s ON u.id=s.uid LEFT JOIN membership m ON u.id=m.uid WHERE s.token=? AND s.expires>?""",(digest(token),int(time.time()))).fetchone()
    if not row: fail(401,"Sign in first")
    if admin and not row["admin"]: fail(403,"Administrator required")
    if internal and (row["status"]!="approved" or row["rank"] is None): fail(403,"Membership approval required")
    return dict(row)
def session(uid):
    token=secrets.token_urlsafe(48)
    with db() as c:
        c.execute("DELETE FROM sessions WHERE expires<?",(int(time.time()),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)",(digest(token),uid,int(time.time())+ttl))
    resp=JSONResponse({"ok":True},headers={"Cache-Control":"no-store"})
    resp.set_cookie(cookie,token,max_age=ttl,path="/highest",secure=True,httponly=True,samesite="strict")
    return resp

class Login(BaseModel):
    username:str=Field(min_length=3,max_length=24)
    password:str=Field(min_length=12,max_length=128)
class Register(Login):
    display_name:str=Field(min_length=1,max_length=60)
class Apply(BaseModel):
    character:str=Field(min_length=1,max_length=80)
    callsign:str=Field(default="",max_length=40)
    requested:str=Field(default="",max_length=80)
class Rank(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    position:int=Field(default=0,ge=0,le=10000)
    parent:int|None=None
    id:int|None=None
class Review(BaseModel):
    approve:bool
    rank:int|None=None
    position:str=Field(default="",max_length=80)
    reason:str=Field(default="",max_length=500)
class Assignment(BaseModel):
    rank:int
    position:str=Field(min_length=1,max_length=80)
class Clip(BaseModel):
    title:str=Field(min_length=1,max_length=100)
    url:str=Field(max_length=500)
class Streamer(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    platform:str
    channel:str=Field(min_length=1,max_length=80)

@router.get("")
def redirect(): return RedirectResponse("/highest/",307)
@router.get("/")
@router.get("/community/")
@router.get("/internal/")
@router.get("/admin/")
def page():
    return FileResponse(assets/"index.html",headers={"Cache-Control":"no-store","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'","X-Content-Type-Options":"nosniff"})
@router.get("/ui.js")
def js(): return FileResponse(assets/"ui.js",media_type="application/javascript")
@router.get("/ui.css")
def css(): return FileResponse(assets/"ui.css",media_type="text/css")
@router.get("/document.css")
def document_css(): return FileResponse(assets/"document.css",media_type="text/css")
@router.get("/logo.png")
def logo():
    p=assets/"logo.png"
    if not p.is_file(): fail(404,"Logo not installed")
    return FileResponse(p,media_type="image/png")
@router.post("/api/register")
def register(p:Register,r:Request):
    origin(r); throttle(r,"register:"+p.username.lower())
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,23}",p.username): fail(400,"Invalid username")
    name=clean(p.display_name,60)
    hashed=password_hash(p.password)
    try:
        with db() as c:
            uid=c.execute("INSERT INTO users(username,display_name,password) VALUES(?,?,?)",(p.username.lower(),name,hashed)).lastrowid
            audit(c,uid,"register")
    except sqlite3.IntegrityError: fail(409,"Username already taken")
    return session(uid)
@router.post("/api/login")
def login(p:Login,r:Request):
    origin(r); throttle(r,"login:"+p.username.lower())
    with db() as c: row=c.execute("SELECT * FROM users WHERE username=?",(p.username,)).fetchone()
    stored=row["password"] if row else "0"*32+":"+"0"*64
    if not hmac.compare_digest(password_hash(p.password,stored.split(":")[0]),stored) or not row: fail(401,"Invalid credentials")
    return session(row["id"])
@router.post("/api/logout")
def logout(r:Request):
    origin(r)
    with db() as c: c.execute("DELETE FROM sessions WHERE token=?",(digest(r.cookies.get(cookie,"")),))
    resp=JSONResponse({"ok":True})
    resp.delete_cookie(cookie,path="/highest",secure=True,httponly=True,samesite="strict")
    return resp
@router.get("/api/me")
def me(r:Request): return JSONResponse(current(r),headers={"Cache-Control":"no-store"})
@router.post("/api/apply")
def apply(p:Apply,r:Request):
    origin(r); u=current(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT status FROM membership WHERE uid=?",(u["id"],)).fetchone()
        if row and row["status"] in ("pending","approved"): fail(409,"Already pending or approved")
        c.execute("""INSERT INTO membership(uid,character,callsign,requested,status) VALUES(?,?,?,?,'pending')
        ON CONFLICT(uid) DO UPDATE SET character=excluded.character,callsign=excluded.callsign,requested=excluded.requested,status='pending',rank=NULL,position='',reason=''""",(u["id"],clean(p.character,80),p.callsign.strip(),p.requested.strip()))
        audit(c,u["id"],"apply")
    return {"ok":True}
@router.get("/api/admin")
def admin(r:Request):
    current(r,admin=True)
    with db() as c:
        return {"members":[dict(x) for x in c.execute("SELECT m.*,u.username FROM membership m JOIN users u ON m.uid=u.id ORDER BY status,username")],"ranks":[dict(x) for x in c.execute("SELECT * FROM ranks ORDER BY position,id")],"clips":[dict(x) for x in c.execute("SELECT * FROM clips WHERE state='pending'")]}
@router.post("/api/admin/rank")
def rank(p:Rank,r:Request):
    origin(r); u=current(r,admin=True)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        parent=p.parent; seen=set()
        while parent is not None:
            if parent==p.id or parent in seen: fail(400,"Hierarchy cycle")
            seen.add(parent)
            row=c.execute("SELECT parent FROM ranks WHERE id=?",(parent,)).fetchone()
            if not row: fail(400,"Parent not found")
            parent=row["parent"]
        try:
            if p.id is None: target=c.execute("INSERT INTO ranks(name,position,parent) VALUES(?,?,?)",(clean(p.name,60),p.position,p.parent)).lastrowid
            else:
                target=p.id
                if not c.execute("UPDATE ranks SET name=?,position=?,parent=? WHERE id=?",(clean(p.name,60),p.position,p.parent,target)).rowcount: fail(404,"Rank not found")
        except sqlite3.IntegrityError: fail(409,"Rank name already exists")
        audit(c,u["id"],"rank.save",target)
    return {"ok":True}
@router.post("/api/admin/review/{uid}")
def review(uid:int,p:Review,r:Request):
    origin(r); u=current(r,admin=True)
    if uid==u["id"]: fail(403,"Cannot review own application")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if p.approve and (not p.position.strip() or not c.execute("SELECT 1 FROM ranks WHERE id=?",(p.rank,)).fetchone()): fail(400,"Rank and position required")
        if not p.approve and not p.reason.strip(): fail(400,"Reason required")
        if not c.execute("UPDATE membership SET status=?,rank=?,position=?,reason=? WHERE uid=? AND status='pending'",("approved" if p.approve else "rejected",p.rank if p.approve else None,p.position.strip() if p.approve else "",p.reason.strip(),uid)).rowcount: fail(409,"No pending application")
        audit(c,u["id"],"approve" if p.approve else "reject",uid)
    return {"ok":True}
@router.post("/api/admin/assign/{uid}")
def assign(uid:int,p:Assignment,r:Request):
    origin(r); u=current(r,admin=True)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM ranks WHERE id=?",(p.rank,)).fetchone(): fail(400,"Rank not found")
        if not c.execute("UPDATE membership SET rank=?,position=? WHERE uid=? AND status='approved'",(p.rank,clean(p.position,80),uid)).rowcount: fail(409,"Not approved")
        audit(c,u["id"],"assign",uid)
    return {"ok":True}
@router.post("/api/admin/revoke/{uid}")
def revoke(uid:int,r:Request):
    origin(r); u=current(r,admin=True)
    with db() as c:
        if not c.execute("UPDATE membership SET status='revoked',rank=NULL,position='' WHERE uid=? AND status='approved'",(uid,)).rowcount: fail(409,"Not approved")
        audit(c,u["id"],"revoke",uid)
    return {"ok":True}
@router.get("/api/internal")
def internal(r:Request):
    current(r,internal=True)
    with db() as c:
        return JSONResponse({"ranks":[dict(x) for x in c.execute("SELECT * FROM ranks ORDER BY position,id")],"members":[dict(x) for x in c.execute("SELECT character,callsign,rank,position FROM membership WHERE status='approved'")]},headers={"Cache-Control":"no-store"})
@router.get("/api/community")
def community(r:Request):
    current(r)
    from urllib.parse import quote
    with db() as c:
        streams=[dict(x) for x in c.execute("SELECT * FROM streamers ORDER BY name")]
        clips=[dict(x) for x in c.execute("SELECT clips.id,title,url,display_name FROM clips JOIN users ON clips.uid=users.id WHERE state='published' ORDER BY clips.id DESC LIMIT 100")]
    for s in streams:
        if s["checked"]<time.time()-max(900,int(os.getenv("HIGHEST_LIVE_INTERVAL","3600"))*2): s["status"]="unknown"; s["live_url"]=None
        s["url"]=s["live_url"] or ("https://www.youtube.com/channel/"+quote(s["channel"])+"/live" if s["platform"]=="youtube" else "https://www.tiktok.com/@"+quote(s["channel"])+"/live")
    return JSONResponse({"streamers":streams,"clips":clips},headers={"Cache-Control":"no-store"})
@router.post("/api/clip")
def clip(p:Clip,r:Request):
    from urllib.parse import urlsplit
    origin(r); u=current(r); throttle(r,"clip:"+str(u["id"]))
    url=urlsplit(p.url)
    if url.scheme!="https" or url.netloc.lower() not in {"www.youtube.com","youtube.com","youtu.be","www.tiktok.com","tiktok.com","vm.tiktok.com","vt.tiktok.com"} or not url.path.strip("/"): fail(400,"YouTube or TikTok link required")
    with db() as c: c.execute("INSERT INTO clips(uid,title,url) VALUES(?,?,?)",(u["id"],clean(p.title,100),p.url))
    return {"ok":True}
@router.post("/api/admin/clip/{cid}/{decision}")
def moderate(cid:int,decision:str,r:Request):
    origin(r); u=current(r,admin=True)
    if decision not in ("published","rejected"): fail(400,"Invalid decision")
    with db() as c:
        if not c.execute("UPDATE clips SET state=? WHERE id=? AND state='pending'",(decision,cid)).rowcount: fail(409,"Not pending")
        audit(c,u["id"],"clip."+decision,cid)
    return {"ok":True}
@router.post("/api/admin/streamer")
def streamer(p:Streamer,r:Request):
    origin(r); u=current(r,admin=True)
    if p.platform=="youtube": valid=re.fullmatch(r"UC[A-Za-z0-9_-]{22}",p.channel)
    elif p.platform=="tiktok": valid=re.fullmatch(r"[A-Za-z0-9_.]{1,24}",p.channel)
    else: valid=False
    if not valid: fail(400,"Use a YouTube channel ID or TikTok username")
    with db() as c:
        c.execute("INSERT INTO streamers(name,platform,channel) VALUES(?,?,?) ON CONFLICT(platform,channel) DO UPDATE SET name=excluded.name",(clean(p.name,60),p.platform,p.channel))
        audit(c,u["id"],"streamer.save")
    return {"ok":True}

def bootstrap_admin(username):
    """Operator only: run inside VPS container after the named user registers."""
    init()
    with db() as c:
        if not c.execute("UPDATE users SET admin=1 WHERE username=?",(username,)).rowcount: raise ValueError("Account not found")

@router.post("/api/admin/rank/delete/{rank_id}")
def delete_rank(rank_id:int,r:Request):
    origin(r); u=current(r,admin=True)
    try:
        with db() as c:
            if not c.execute("DELETE FROM ranks WHERE id=?",(rank_id,)).rowcount: fail(404,"Rank not found")
            audit(c,u["id"],"rank.delete",rank_id)
    except sqlite3.IntegrityError: fail(409,"Move members and child ranks first")
    return {"ok":True}
