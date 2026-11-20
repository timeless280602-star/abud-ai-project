"""Separate authentication and membership for the fictional FiveM HQ."""
import hashlib, hmac, os, re, secrets, sqlite3, time, uuid, mimetypes
from urllib.parse import urlsplit
from contextlib import contextmanager
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
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
        CREATE TABLE IF NOT EXISTS hq_media_audit(id INTEGER PRIMARY KEY,clip_id INTEGER NOT NULL,uid INTEGER NOT NULL,action TEXT NOT NULL,created INTEGER NOT NULL);
        """)
        clip_columns={x["name"] for x in c.execute("PRAGMA table_info(clips)")}
        for name,definition in (("media_path","TEXT"),("media_type","TEXT"),("media_size","INTEGER"),("media_sha256","TEXT"),("views","INTEGER"),("views_checked","INTEGER"),("views_source","TEXT")):
            if name not in clip_columns: c.execute("ALTER TABLE clips ADD COLUMN "+name+" "+definition)

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
        return {"members":[dict(x) for x in c.execute("SELECT m.*,u.username FROM membership m JOIN users u ON m.uid=u.id ORDER BY status,username")],"ranks":[dict(x) for x in c.execute("SELECT * FROM ranks ORDER BY position,id")],"clips":[dict(x) for x in c.execute("SELECT * FROM clips WHERE state='pending'")], "published_clips":[dict(x) for x in c.execute("SELECT id,title,url,views,views_checked,views_source,media_type,media_size FROM clips WHERE state='published' ORDER BY id DESC LIMIT 200")]}
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
def _media_dir():
    base=os.getenv("HIGHEST_DATABASE_PATH",str(Path(os.getenv("ABUD_DATABASE_PATH","/app/data/abud_memory.db")).parent/"highest.db"))
    path=Path(os.getenv("HIGHEST_MEDIA_DIR",str(Path(base).parent/"highest_media")))
    path.mkdir(parents=True,exist_ok=True,mode=0o750)
    return path

@router.post("/api/clip/upload")
async def clip_upload(r:Request,title:str=Form(...),file:UploadFile=File(...)):
    origin(r);u=current(r);throttle(r,"clip-upload:"+str(u["id"]))
    title=clean(title,100)
    allowed={".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp",".gif":"image/gif",".mp4":"video/mp4",".webm":"video/webm"}
    name=(file.filename or "").lower()
    ext=Path(name).suffix
    content_type=allowed.get(ext)
    if not content_type: fail(400,"Supported media: JPG, PNG, WEBP, GIF, MP4 and WEBM")
    if file.content_type and file.content_type not in (content_type,"application/octet-stream"): fail(400,"File type does not match its extension")
    limit=50*1024*1024 if content_type.startswith("video/") else 10*1024*1024
    data=await file.read(limit+1)
    if not data or len(data)>limit: fail(413,"Image limit is 10 MB and video limit is 50 MB")
    valid=(ext in (".jpg",".jpeg") and data.startswith(b"\xff\xd8\xff")) or (ext==".png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or (ext==".gif" and data[:6] in (b"GIF87a",b"GIF89a")) or (ext==".webp" and data[:4]==b"RIFF" and data[8:12]==b"WEBP") or (ext==".mp4" and len(data)>12 and data[4:8]==b"ftyp") or (ext==".webm" and data.startswith(b"\x1a\x45\xdf\xa3"))
    if not valid: fail(400,"File content is not a valid supported media file")
    digest_value=hashlib.sha256(data).hexdigest();filename=uuid.uuid4().hex+ext;target=_media_dir()/filename
    target.write_bytes(data);os.chmod(target,0o640)
    try:
        with db() as c:
            cid=c.execute("INSERT INTO clips(uid,title,url,media_path,media_type,media_size,media_sha256) VALUES(?,?, '',?,?,?,?)",(u["id"],title,filename,content_type,len(data),digest_value)).lastrowid
            c.execute("INSERT INTO hq_media_audit(clip_id,uid,action,created) VALUES(?,?,?,?)",(cid,u["id"],"upload",int(time.time())))
    except Exception:
        target.unlink(missing_ok=True);raise
    return {"ok":True,"id":cid,"state":"pending","media_url":"/highest/api/media/"+str(cid),"sha256":digest_value}

@router.get("/api/media/{cid}")
def clip_media(cid:int,r:Request):
    u=current(r)
    with db() as c:
        item=c.execute("SELECT uid,state,media_path,media_type,media_sha256 FROM clips WHERE id=?",(cid,)).fetchone()
        if not item or not item["media_path"]: fail(404,"Media not found")
        if item["state"]!="published" and int(item["uid"])!=u["id"] and not u["admin"]: fail(404,"Media not found")
        path=_media_dir()/Path(item["media_path"]).name
        if not path.is_file(): fail(404,"Media file is unavailable")
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if not item["media_sha256"] or not hmac.compare_digest(actual,item["media_sha256"]):
            with db() as audit_db:
                audit_db.execute("INSERT INTO hq_media_audit(clip_id,uid,action,created) VALUES(?,?,?,?)",(cid,u["id"],"integrity_failure",int(time.time())))
                audit(audit_db,u["id"],"media.integrity_failure",cid)
            fail(500,"Media integrity verification failed")
        with db() as audit_db:
            audit_db.execute("INSERT INTO hq_media_audit(clip_id,uid,action,created) VALUES(?,?,?,?)",(cid,u["id"],"preview",int(time.time())))
        return FileResponse(path,media_type=item["media_type"],headers={"X-Content-Type-Options":"nosniff","Cache-Control":"private, max-age=300","Content-Security-Policy":"default-src 'none'; sandbox"})

@router.post("/api/admin/clips/stats/refresh")
def refresh_clip_stats(r:Request):
    origin(r)
    current(r,admin=True)
    import httpx
    key=os.getenv("HIGHEST_YOUTUBE_API_KEY","")
    tik_endpoint=os.getenv("HIGHEST_TIKTOK_STATS_URL","");tik_token=os.getenv("HIGHEST_TIKTOK_STATS_TOKEN","")
    with db() as c: clips=[dict(x) for x in c.execute("SELECT id,url,state FROM clips WHERE state='published'")]
    updated=0;unavailable=[];yt_ids=[]
    for clip in clips:
        url=clip["url"] or ""
        match=re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/))([A-Za-z0-9_-]{11})",url)
        if match and key: yt_ids.append((clip["id"],match.group(1)))
        elif "tiktok.com/" in url and urlsplit(tik_endpoint).scheme=="https" and tik_token:
            try:
                with httpx.Client(timeout=12,follow_redirects=False) as client: response=client.get(tik_endpoint,params={"url":url},headers={"Authorization":"Bearer "+tik_token})
                response.raise_for_status();value=response.json().get("views")
                if type(value) is not int or value<0: raise ValueError("Invalid view count")
                with db() as c:c.execute("UPDATE clips SET views=?,views_checked=?,views_source='tiktok_provider' WHERE id=?",(value,int(time.time()),clip["id"]))
                updated+=1
            except Exception: unavailable.append(clip["id"])
        else: unavailable.append(clip["id"])
    for offset in range(0,len(yt_ids),50):
        batch=yt_ids[offset:offset+50]
        try:
            with httpx.Client(timeout=15) as client: response=client.get("https://www.googleapis.com/youtube/v3/videos",params={"part":"statistics","id":",".join(x[1] for x in batch),"key":key})
            response.raise_for_status();items=response.json().get("items")
            if not isinstance(items,list): raise ValueError("Malformed YouTube response")
            values={x.get("id"):int(x["statistics"]["viewCount"]) for x in items if x.get("id") and str(x.get("statistics",{}).get("viewCount","")).isdigit()}
            with db() as c:
                for cid,video_id in batch:
                    if video_id in values:c.execute("UPDATE clips SET views=?,views_checked=?,views_source='youtube_data_api' WHERE id=?",(values[video_id],int(time.time()),cid));updated+=1
                    else: unavailable.append(cid)
        except Exception: unavailable.extend(cid for cid,_ in batch)
    return {"ok":True,"updated":updated,"unavailable":unavailable,"total":len(clips)}

@router.post("/api/admin/clip/{cid}/{decision}")
def moderate(cid:int,decision:str,r:Request):
    origin(r); u=current(r,admin=True)
    if decision not in ("published","rejected"): fail(400,"Invalid decision")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        item=c.execute("SELECT uid,title FROM clips WHERE id=? AND state='pending'",(cid,)).fetchone()
        if not item: fail(409,"Not pending")
        if not c.execute("UPDATE clips SET state=? WHERE id=? AND state='pending'",(decision,cid)).rowcount: fail(409,"Not pending")
        from app.highest_ops import notify
        approved=decision=="published"
        notify(c,int(item["uid"]),"content_approved" if approved else "content_rejected","Clip approved" if approved else "Clip rejected",("Your clip \""+item["title"]+"\" is now published." if approved else "Your clip \""+item["title"]+"\" was rejected."),"/highest/","clip-review:"+str(cid)+":"+decision)
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
