"""Public-to-authenticated community content; never reads IC internal tables."""
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.highest import db, current, origin, clean, fail, audit, throttle

router=APIRouter(prefix="/highest/api")
def now(): return int(time.time())
def rows(c,q,args=()): return [dict(x) for x in c.execute(q,args)]
def reply(data): return JSONResponse(data,headers={"Cache-Control":"no-store"})
def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS hq_creator(uid INTEGER REFERENCES users(id),kind TEXT CHECK(kind IN ('streamer','clipper')),url TEXT NOT NULL,note TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(uid,kind));
        CREATE TABLE IF NOT EXISTS hq_moment(id INTEGER PRIMARY KEY,uid INTEGER REFERENCES users(id),title TEXT NOT NULL,summary TEXT NOT NULL,spoiler INTEGER NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_pov(id INTEGER PRIMARY KEY,moment INTEGER REFERENCES hq_moment(id),clip INTEGER REFERENCES clips(id),label TEXT NOT NULL,uid INTEGER REFERENCES users(id),state TEXT NOT NULL,UNIQUE(moment,clip));
        CREATE TABLE IF NOT EXISTS hq_wiki(id INTEGER PRIMARY KEY,uid INTEGER REFERENCES users(id),kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,spoiler INTEGER NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hq_clip_likes(uid INTEGER REFERENCES users(id),clip INTEGER REFERENCES clips(id),PRIMARY KEY(uid,clip));
        CREATE TABLE IF NOT EXISTS hq_clip_bookmarks(uid INTEGER REFERENCES users(id),clip INTEGER REFERENCES clips(id),PRIMARY KEY(uid,clip));
        CREATE TABLE IF NOT EXISTS hq_follows(uid INTEGER REFERENCES users(id),streamer INTEGER REFERENCES streamers(id),PRIMARY KEY(uid,streamer));
        CREATE TABLE IF NOT EXISTS hq_posts(id INTEGER PRIMARY KEY,uid INTEGER REFERENCES users(id),body TEXT NOT NULL,category TEXT NOT NULL,spoiler INTEGER NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL);
        """)
def valid_link(value):
    try: p=urlsplit(value)
    except ValueError: fail(400,"Invalid link")
    if p.scheme!="https" or p.netloc.lower() not in {"youtube.com","www.youtube.com","youtu.be","m.youtube.com","tiktok.com","www.tiktok.com","vm.tiktok.com","vt.tiktok.com"} or not p.path.strip("/"): fail(400,"Use a YouTube or TikTok link")
    return value
class Creator(BaseModel):
    kind:str
    url:str=Field(max_length=500)
    note:str=Field(default="",max_length=500)
class Moment(BaseModel):
    title:str=Field(min_length=1,max_length=100)
    summary:str=Field(min_length=1,max_length=1000)
    spoiler:bool=False
class Pov(BaseModel):
    clip:int
    label:str=Field(min_length=1,max_length=80)
class Wiki(BaseModel):
    kind:str
    title:str=Field(min_length=1,max_length=100)
    body:str=Field(min_length=1,max_length=10000)
    spoiler:bool=False
class Toggle(BaseModel):
    enabled:bool
class Post(BaseModel):
    body:str=Field(min_length=1,max_length=2000)
    category:str
    spoiler:bool=False
class Review(BaseModel):
    approve:bool

@router.get("/social")
def social(r:Request):
    u=current(r)
    with db() as c:
        moments=rows(c,"SELECT m.id,title,summary,spoiler,created,u.display_name FROM hq_moment m JOIN users u ON m.uid=u.id WHERE m.state='published' ORDER BY m.id DESC LIMIT 100")
        for m in moments:
            m["povs"]=rows(c,"SELECT p.id,p.label,cl.title,cl.url,u.display_name,cu.display_name clip_owner FROM hq_pov p JOIN clips cl ON p.clip=cl.id JOIN users u ON p.uid=u.id JOIN users cu ON cl.uid=cu.id WHERE p.moment=? AND p.state='published' AND cl.state='published' ORDER BY p.id",(m["id"],))
        wiki=rows(c,"SELECT w.id,w.kind,w.title,w.body,w.spoiler,w.created,u.display_name FROM hq_wiki w JOIN users u ON w.uid=u.id WHERE w.state='published' ORDER BY id DESC LIMIT 100")
        posts=rows(c,"SELECT p.id,p.body,p.category,p.spoiler,p.created,u.display_name FROM hq_posts p JOIN users u ON p.uid=u.id WHERE p.state='published' ORDER BY p.id DESC LIMIT 100")
        clips=rows(c,"""SELECT cl.id,cl.title,cl.url,u.display_name,
        (SELECT count(*) FROM hq_clip_likes l WHERE l.clip=cl.id) likes,
        EXISTS(SELECT 1 FROM hq_clip_likes l WHERE l.clip=cl.id AND l.uid=?) liked,
        EXISTS(SELECT 1 FROM hq_clip_bookmarks b WHERE b.clip=cl.id AND b.uid=?) bookmarked
        FROM clips cl JOIN users u ON cl.uid=u.id WHERE cl.state='published' ORDER BY likes DESC,cl.id DESC LIMIT 100""",(u["id"],u["id"]))
        creators=rows(c,"SELECT u.display_name,h.kind,h.url FROM hq_creator h JOIN users u ON h.uid=u.id WHERE h.status='approved'")
        follows=[x["streamer"] for x in c.execute("SELECT streamer FROM hq_follows WHERE uid=?",(u["id"],))]
        leaderboard=rows(c,"""SELECT u.display_name,count(*) clips,(SELECT count(*) FROM hq_clip_likes l JOIN clips cl ON cl.id=l.clip WHERE cl.uid=u.id AND cl.state='published') likes FROM clips c JOIN users u ON c.uid=u.id WHERE c.state='published' GROUP BY u.id ORDER BY likes DESC,clips DESC LIMIT 20""")
        return reply(dict(moments=moments,wiki=wiki,posts=posts,clips=clips,creators=creators,follows=follows,leaderboard=leaderboard))

@router.get("/social/studio")
def studio(r:Request):
    u=current(r)
    with db() as c:
        clips=rows(c,"SELECT c.id,c.title,c.url,c.state,(SELECT count(*) FROM hq_clip_likes l WHERE l.clip=c.id) likes FROM clips c WHERE uid=? ORDER BY c.id DESC LIMIT 300",(u["id"],))
        return reply(dict(clips=clips,verification=rows(c,"SELECT kind,url,status,note FROM hq_creator WHERE uid=?",(u["id"],)),moments=rows(c,"SELECT id,title,state FROM hq_moment WHERE uid=? ORDER BY id DESC",(u["id"],)),wiki=rows(c,"SELECT id,kind,title,state FROM hq_wiki WHERE uid=? ORDER BY id DESC",(u["id"],)),posts=rows(c,"SELECT id,category,state FROM hq_posts WHERE uid=? ORDER BY id DESC",(u["id"],)),bookmarks=rows(c,"SELECT c.id,c.title,c.url FROM hq_clip_bookmarks b JOIN clips c ON c.id=b.clip WHERE b.uid=? AND c.state='published' ORDER BY c.id DESC",(u["id"],))))

@router.post("/social/creator")
def creator(p:Creator,r:Request):
    origin(r); u=current(r); throttle(r,"creator:"+str(u["id"]))
    if p.kind not in ("streamer","clipper"): fail(400,"Invalid creator type")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        prev=c.execute("SELECT status FROM hq_creator WHERE uid=? AND kind=?",(u["id"],p.kind)).fetchone()
        if prev and prev["status"] in ("pending","approved"): fail(409,"Already pending or verified")
        c.execute("INSERT INTO hq_creator VALUES(?,?,?,?,'pending') ON CONFLICT(uid,kind) DO UPDATE SET url=excluded.url,note=excluded.note,status='pending'",(u["id"],p.kind,valid_link(p.url),p.note.strip()))
    return {"ok":True}
@router.post("/social/moment")
def moment(p:Moment,r:Request):
    origin(r); u=current(r); throttle(r,"moment:"+str(u["id"]))
    with db() as c:
        mid=c.execute("INSERT INTO hq_moment(uid,title,summary,spoiler,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],clean(p.title,100),clean(p.summary,1000),int(p.spoiler),now())).lastrowid
    return {"id":mid}
@router.post("/social/moment/{mid}/pov")
def pov(mid:int,p:Pov,r:Request):
    origin(r); u=current(r); throttle(r,"pov:"+str(u["id"]))
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        m=c.execute("SELECT uid,state FROM hq_moment WHERE id=?",(mid,)).fetchone()
        if not m or (m["state"]!="published" and not (m["state"]=="pending" and m["uid"]==u["id"])): fail(404,"Moment unavailable")
        if not c.execute("SELECT 1 FROM clips WHERE id=? AND state='published'",(p.clip,)).fetchone(): fail(404,"Published clip required")
        if c.execute("SELECT 1 FROM hq_pov WHERE moment=? AND clip=?",(mid,p.clip)).fetchone(): fail(409,"Clip already submitted for this moment")
        c.execute("INSERT INTO hq_pov(moment,clip,label,uid,state) VALUES(?,?,?,?,'pending')",(mid,p.clip,clean(p.label,80),u["id"]))
    return {"ok":True}
@router.post("/social/wiki")
def wiki(p:Wiki,r:Request):
    origin(r); u=current(r); throttle(r,"wiki:"+str(u["id"]))
    if p.kind not in ("lore","character","recap"): fail(400,"Invalid wiki type")
    with db() as c:
        c.execute("INSERT INTO hq_wiki(uid,kind,title,body,spoiler,state,created) VALUES(?,?,?,?,?,'pending',?)",(u["id"],p.kind,clean(p.title,100),clean(p.body,10000),int(p.spoiler),now()))
    return {"ok":True}
@router.post("/social/post")
def post(p:Post,r:Request):
    origin(r); u=current(r); throttle(r,"post:"+str(u["id"]))
    if p.category not in ("general","storyline","fan_art","clips","memes"): fail(400,"Invalid category")
    with db() as c:
        c.execute("INSERT INTO hq_posts(uid,body,category,spoiler,state,created) VALUES(?,?,?,?,'pending',?)",(u["id"],clean(p.body,2000),p.category,int(p.spoiler),now()))
    return {"ok":True}
@router.post("/social/clip/{cid}/{action}")
def clip_action(cid:int,action:str,p:Toggle,r:Request):
    origin(r); u=current(r)
    table={"like":"hq_clip_likes","bookmark":"hq_clip_bookmarks"}.get(action)
    if not table: fail(400,"Invalid action")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM clips WHERE id=? AND state='published'",(cid,)).fetchone(): fail(404,"Clip unavailable")
        if p.enabled: c.execute("INSERT OR IGNORE INTO "+table+" VALUES(?,?)",(u["id"],cid))
        else: c.execute("DELETE FROM "+table+" WHERE uid=? AND clip=?",(u["id"],cid))
    return {"ok":True}
@router.post("/social/follow/{sid}")
def follow(sid:int,p:Toggle,r:Request):
    origin(r); u=current(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM streamers WHERE id=?",(sid,)).fetchone(): fail(404,"Streamer unavailable")
        if p.enabled: c.execute("INSERT OR IGNORE INTO hq_follows VALUES(?,?)",(u["id"],sid))
        else: c.execute("DELETE FROM hq_follows WHERE uid=? AND streamer=?",(u["id"],sid))
    return {"ok":True}
@router.get("/admin/social")
def moderation(r:Request):
    current(r,admin=True)
    with db() as c:
        return reply(dict(creators=rows(c,"SELECT h.*,u.username,u.display_name FROM hq_creator h JOIN users u ON h.uid=u.id WHERE h.status='pending'"),moments=rows(c,"SELECT m.*,u.username,u.display_name FROM hq_moment m JOIN users u ON m.uid=u.id WHERE m.state='pending'"),povs=rows(c,"SELECT p.*,m.title moment_title,cl.title clip_title,cl.url,pu.username,pu.display_name,cu.display_name clip_owner FROM hq_pov p JOIN hq_moment m ON p.moment=m.id JOIN clips cl ON p.clip=cl.id JOIN users pu ON p.uid=pu.id JOIN users cu ON cl.uid=cu.id WHERE p.state='pending'"),wiki=rows(c,"SELECT w.*,u.username,u.display_name FROM hq_wiki w JOIN users u ON w.uid=u.id WHERE w.state='pending'"),posts=rows(c,"SELECT p.*,u.username,u.display_name FROM hq_posts p JOIN users u ON p.uid=u.id WHERE p.state='pending'")))
@router.post("/admin/social/creator/{uid}/{kind}")
def review_creator(uid:int,kind:str,p:Review,r:Request):
    origin(r); u=current(r,admin=True)
    if uid==u["id"]: fail(403,"Cannot review own verification")
    with db() as c:
        if not c.execute("UPDATE hq_creator SET status=? WHERE uid=? AND kind=? AND status='pending'",("approved" if p.approve else "rejected",uid,kind)).rowcount: fail(409,"Not pending")
        audit(c,u["id"],"creator."+kind+(".approve" if p.approve else ".reject"),uid)
    return {"ok":True}
@router.post("/admin/social/{kind}/{cid}")
def review(kind:str,cid:int,p:Review,r:Request):
    origin(r); u=current(r,admin=True)
    table={"moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}.get(kind)
    if not table: fail(400,"Invalid type")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        submission=c.execute("SELECT uid FROM "+table+" WHERE id=? AND state='pending'",(cid,)).fetchone()
        if not submission: fail(409,"Not pending")
        if int(submission["uid"])==u["id"]: fail(403,"Cannot review your own community submission")
        if p.approve and kind=="pov" and not c.execute("SELECT 1 FROM hq_pov p JOIN hq_moment m ON p.moment=m.id JOIN clips cl ON p.clip=cl.id WHERE p.id=? AND m.state='published' AND cl.state='published'",(cid,)).fetchone(): fail(409,"Approve moment and clip first")
        if not c.execute("UPDATE "+table+" SET state=? WHERE id=? AND state='pending'",("published" if p.approve else "rejected",cid)).rowcount: fail(409,"Not pending")
        audit(c,u["id"],"social."+kind+(".publish" if p.approve else ".reject"),cid)
    return {"ok":True}
