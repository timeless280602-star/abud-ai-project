"""Public-to-authenticated community content; never reads IC internal tables."""
import time
import sqlite3
from urllib.parse import urlsplit
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.highest import db, current, origin, clean, fail, audit, throttle
from app.highest_ops import notify

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
        CREATE TABLE IF NOT EXISTS hq_reports(id INTEGER PRIMARY KEY,reporter INTEGER NOT NULL REFERENCES users(id),content_type TEXT NOT NULL CHECK(content_type IN ('clip','moment','pov','wiki','post')),content_id INTEGER NOT NULL,reason TEXT NOT NULL CHECK(reason IN ('harassment','personal_info','spam','inappropriate','copyright','other')),details TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','actioned','dismissed')),action TEXT NOT NULL DEFAULT '',reviewed_by INTEGER REFERENCES users(id),reviewed_at INTEGER,review_note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS hq_reports_queue ON hq_reports(status,created DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS hq_reports_one_open ON hq_reports(reporter,content_type,content_id) WHERE status='open';
        CREATE TABLE IF NOT EXISTS hq_comment(
            id INTEGER PRIMARY KEY,content_type TEXT NOT NULL CHECK(content_type IN ('clip','moment','pov','wiki','post')),
            content_id INTEGER NOT NULL,parent_id INTEGER REFERENCES hq_comment(id),uid INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'published' CHECK(state IN ('published','deleted')),
            created INTEGER NOT NULL,updated INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS hq_comment_content ON hq_comment(content_type,content_id,state,created);
        CREATE INDEX IF NOT EXISTS hq_comment_parent ON hq_comment(parent_id,created);
        CREATE TABLE IF NOT EXISTS hq_comment_like(
            uid INTEGER NOT NULL REFERENCES users(id),comment_id INTEGER NOT NULL REFERENCES hq_comment(id),
            created INTEGER NOT NULL,PRIMARY KEY(uid,comment_id)
        );
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
class ContentReport(BaseModel):
    content_type:str
    content_id:int=Field(ge=1)
    reason:str
    details:str=Field(default="",max_length=1000)
class ReportDecision(BaseModel):
    action:str
    note:str=Field(default="",max_length=500)
class CommentCreate(BaseModel):
    content_type:str
    content_id:int=Field(ge=1)
    body:str=Field(min_length=1,max_length=1000)
class CommentReply(BaseModel):
    body:str=Field(min_length=1,max_length=1000)
class CommentToggle(BaseModel):
    enabled:bool

@router.get("/social")
def social(r:Request):
    u=current(r)
    with db() as c:
        moments=rows(c,"SELECT m.id,title,summary,spoiler,created,u.display_name FROM hq_moment m JOIN users u ON m.uid=u.id WHERE m.state='published' ORDER BY m.id DESC LIMIT 100")
        for m in moments:
            m["povs"]=rows(c,"SELECT p.id,p.label,cl.title,cl.url,u.display_name,cu.display_name clip_owner FROM hq_pov p JOIN clips cl ON p.clip=cl.id JOIN users u ON p.uid=u.id JOIN users cu ON cl.uid=cu.id WHERE p.moment=? AND p.state='published' AND cl.state='published' ORDER BY p.id",(m["id"],))
        wiki=rows(c,"SELECT w.id,w.kind,w.title,w.body,w.spoiler,w.created,u.display_name FROM hq_wiki w JOIN users u ON w.uid=u.id WHERE w.state='published' ORDER BY w.id DESC LIMIT 100")
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
def _published_owner(c,kind,cid):
    tables={"clip":"clips","moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}
    table=tables.get(kind)
    if not table: fail(400,"Invalid content type")
    if kind=="pov":
        target=c.execute("""SELECT p.uid FROM hq_pov p
            JOIN hq_moment m ON m.id=p.moment
            JOIN clips cl ON cl.id=p.clip
            WHERE p.id=? AND p.state='published' AND m.state='published' AND cl.state='published'""",(cid,)).fetchone()
    else:
        target=c.execute("SELECT uid FROM "+table+" WHERE id=? AND state='published'",(cid,)).fetchone()
    if not target: fail(404,"Published content unavailable")
    return int(target["uid"])

def _comment_payload(c,comment,uid):
    item=dict(comment)
    item["likes"]=c.execute("SELECT count(*) FROM hq_comment_like WHERE comment_id=?",(item["id"],)).fetchone()[0]
    item["liked"]=bool(c.execute("SELECT 1 FROM hq_comment_like WHERE comment_id=? AND uid=?",(item["id"],uid)).fetchone())
    item["mine"]=int(item["uid"])==uid
    item["replies"]=rows(c,"""SELECT x.id,x.parent_id,x.uid,x.body,x.state,x.created,x.updated,u.display_name
        FROM hq_comment x JOIN users u ON u.id=x.uid
        WHERE x.parent_id=? ORDER BY x.created,x.id""",(item["id"],))
    for reply_item in item["replies"]:
        reply_item["mine"]=int(reply_item["uid"])==uid
        reply_item["likes"]=c.execute("SELECT count(*) FROM hq_comment_like WHERE comment_id=?",(reply_item["id"],)).fetchone()[0]
        reply_item["liked"]=bool(c.execute("SELECT 1 FROM hq_comment_like WHERE comment_id=? AND uid=?",(reply_item["id"],uid)).fetchone())
    return item

@router.get("/social/comments/{kind}/{cid}")
def list_comments(kind:str,cid:int,r:Request):
    u=current(r)
    with db() as c:
        _published_owner(c,kind,cid)
        comments=rows(c,"""SELECT x.id,x.parent_id,x.uid,x.body,x.state,x.created,x.updated,u.display_name
            FROM hq_comment x JOIN users u ON u.id=x.uid
            WHERE x.content_type=? AND x.content_id=? AND x.parent_id IS NULL
            ORDER BY x.created DESC,x.id DESC LIMIT 100""",(kind,cid))
        return reply({"comments":[_comment_payload(c,x,u["id"]) for x in comments],
            "count":c.execute("SELECT count(*) FROM hq_comment WHERE content_type=? AND content_id=? AND state='published'",(kind,cid)).fetchone()[0]})

@router.post("/social/comments")
def create_comment(p:CommentCreate,r:Request):
    origin(r);u=current(r);throttle(r,"comment:"+str(u["id"]))
    body=clean(p.body,1000)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        owner=_published_owner(c,p.content_type,p.content_id)
        cid=c.execute("INSERT INTO hq_comment(content_type,content_id,uid,body,created,updated) VALUES(?,?,?,?,?,?)",
            (p.content_type,p.content_id,u["id"],body,now(),now())).lastrowid
        if owner!=u["id"]:
            notify(c,owner,"social_comment","New community comment",u["display_name"]+" commented: "+body[:180],"/highest/","social:comment:"+str(cid))
        audit(c,u["id"],"social.comment.create",cid)
    return {"ok":True,"id":cid}

@router.post("/social/comments/{comment_id}/reply")
def reply_comment(comment_id:int,p:CommentReply,r:Request):
    origin(r);u=current(r);throttle(r,"comment:"+str(u["id"]))
    body=clean(p.body,1000)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        parent=c.execute("SELECT * FROM hq_comment WHERE id=? AND parent_id IS NULL AND state='published'",(comment_id,)).fetchone()
        if not parent: fail(404,"Top-level comment unavailable")
        _published_owner(c,parent["content_type"],parent["content_id"])
        rid=c.execute("INSERT INTO hq_comment(content_type,content_id,parent_id,uid,body,created,updated) VALUES(?,?,?,?,?,?,?)",
            (parent["content_type"],parent["content_id"],comment_id,u["id"],body,now(),now())).lastrowid
        if int(parent["uid"])!=u["id"]:
            notify(c,int(parent["uid"]),"social_reply","New reply to your comment",u["display_name"]+" replied: "+body[:180],"/highest/","social:reply:"+str(rid))
        audit(c,u["id"],"social.comment.reply",rid)
    return {"ok":True,"id":rid}

@router.post("/social/comments/{comment_id}/like")
def toggle_comment_like(comment_id:int,p:CommentToggle,r:Request):
    origin(r);u=current(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        comment=c.execute("SELECT * FROM hq_comment WHERE id=? AND state='published'",(comment_id,)).fetchone()
        if not comment: fail(404,"Comment unavailable")
        _published_owner(c,comment["content_type"],comment["content_id"])
        if p.enabled:
            inserted=c.execute("INSERT OR IGNORE INTO hq_comment_like(uid,comment_id,created) VALUES(?,?,?)",(u["id"],comment_id,now()))
            if inserted.rowcount and int(comment["uid"])!=u["id"]:
                notify(c,int(comment["uid"]),"social_comment_like","Someone liked your comment",u["display_name"]+" liked your comment.","/highest/","social:comment-like:"+str(comment_id)+":"+str(u["id"]))
        else:
            c.execute("DELETE FROM hq_comment_like WHERE uid=? AND comment_id=?",(u["id"],comment_id))
    return {"ok":True}

@router.post("/social/comments/{comment_id}/delete")
def delete_comment(comment_id:int,r:Request):
    origin(r);u=current(r)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        comment=c.execute("SELECT * FROM hq_comment WHERE id=? AND state='published'",(comment_id,)).fetchone()
        if not comment: fail(404,"Comment unavailable")
        if int(comment["uid"])!=u["id"] and not u.get("admin"): fail(403,"You can only delete your own comment")
        c.execute("UPDATE hq_comment SET state='deleted',body='',updated=? WHERE id=?",(now(),comment_id))
        c.execute("DELETE FROM hq_comment_like WHERE comment_id=?",(comment_id,))
        audit(c,u["id"],"social.comment.delete",comment_id)
    return {"ok":True}

@router.get("/social/activity")
def social_activity(r:Request,limit:int=50):
    u=current(r)
    if limit<1 or limit>100: fail(400,"Invalid activity limit")
    with db() as c:
        items=rows(c,"SELECT id,kind,title,body,href,created,read_at FROM hq_notification WHERE uid=? AND kind LIKE 'social_%' ORDER BY created DESC,id DESC LIMIT ?",(u["id"],limit))
        unread=c.execute("SELECT count(*) FROM hq_notification WHERE uid=? AND kind LIKE 'social_%' AND read_at IS NULL",(u["id"],)).fetchone()[0]
        return reply({"items":items,"unread_count":unread})

@router.post("/social/activity/read-all")
def social_activity_read_all(r:Request):
    origin(r);u=current(r)
    with db() as c:
        c.execute("UPDATE hq_notification SET read_at=? WHERE uid=? AND kind LIKE 'social_%' AND read_at IS NULL",(now(),u["id"]))
    return {"ok":True}

@router.post("/social/activity/{notification_id}/read")
def social_activity_read(notification_id:int,r:Request):
    origin(r);u=current(r)
    with db() as c:
        cur=c.execute("UPDATE hq_notification SET read_at=? WHERE id=? AND uid=? AND kind LIKE 'social_%' AND read_at IS NULL",(now(),notification_id,u["id"]))
        if not cur.rowcount and not c.execute("SELECT 1 FROM hq_notification WHERE id=? AND uid=? AND kind LIKE 'social_%'",(notification_id,u["id"])).fetchone(): fail(404,"Activity notification not found")
    return {"ok":True}

@router.post("/social/report")
def create_report(p:ContentReport,r:Request):
    origin(r); u=current(r); throttle(r,"report:"+str(u["id"]))
    if p.reason not in ("harassment","personal_info","spam","inappropriate","copyright","other"): fail(400,"Invalid report reason")
    tables={"clip":"clips","moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}
    table=tables.get(p.content_type)
    if not table: fail(400,"Invalid content type")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        target=c.execute("SELECT uid FROM "+table+" WHERE id=? AND state='published'",(p.content_id,)).fetchone()
        if not target: fail(404,"Published content unavailable")
        if int(target["uid"])==u["id"]: fail(403,"You cannot report your own content")
        if c.execute("SELECT 1 FROM hq_reports WHERE reporter=? AND content_type=? AND content_id=? AND status='open'",(u["id"],p.content_type,p.content_id)).fetchone(): fail(409,"You already have an open report for this content")
        rid=c.execute("INSERT INTO hq_reports(reporter,content_type,content_id,reason,details,created) VALUES(?,?,?,?,?,?)",(u["id"],p.content_type,p.content_id,p.reason,clean(p.details,1000,False),now())).lastrowid
        audit(c,u["id"],"social.report.create",rid)
    return {"ok":True,"id":rid}

@router.get("/social/reports")
def my_reports(r:Request):
    u=current(r)
    with db() as c:
        return reply({"reports":rows(c,"SELECT id,content_type,content_id,reason,details,status,action,review_note,created,reviewed_at FROM hq_reports WHERE reporter=? ORDER BY id DESC LIMIT 100",(u["id"],))})

@router.get("/admin/social/reports")
def report_queue(r:Request):
    current(r,admin=True)
    tables={"clip":"clips","moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}
    with db() as c:
        reports=rows(c,"SELECT r.*,ru.username reporter_username,ru.display_name reporter_name,mu.username moderator_username FROM hq_reports r JOIN users ru ON ru.id=r.reporter LEFT JOIN users mu ON mu.id=r.reviewed_by WHERE r.status='open' ORDER BY r.created ASC LIMIT 300")
        for report in reports:
            table=tables[report["content_type"]]
            report["content"]=c.execute("SELECT x.uid,u.username author_username,u.display_name author_name FROM "+table+" x JOIN users u ON u.id=x.uid WHERE x.id=?",(report["content_id"],)).fetchone()
            if report["content"]:
                report["content"]=dict(report["content"])
                if report["content_type"]=="clip":
                    extra=c.execute("SELECT title,url FROM clips WHERE id=?",(report["content_id"],)).fetchone()
                elif report["content_type"]=="moment":
                    extra=c.execute("SELECT title,summary body FROM hq_moment WHERE id=?",(report["content_id"],)).fetchone()
                elif report["content_type"]=="pov":
                    extra=c.execute("SELECT p.label title,cl.title body,cl.url FROM hq_pov p JOIN clips cl ON cl.id=p.clip WHERE p.id=?",(report["content_id"],)).fetchone()
                elif report["content_type"]=="wiki":
                    extra=c.execute("SELECT title,body FROM hq_wiki WHERE id=?",(report["content_id"],)).fetchone()
                else:
                    extra=c.execute("SELECT category title,body FROM hq_posts WHERE id=?",(report["content_id"],)).fetchone()
                report["content"].update(dict(extra) if extra else {})
        removed=[]
        for kind,table in tables.items():
            items=rows(c,"SELECT x.id,x.uid,u.username,u.display_name FROM "+table+" x JOIN users u ON u.id=x.uid WHERE x.state='removed' ORDER BY x.id DESC LIMIT 100")
            for item in items:
                if kind=="clip": extra=c.execute("SELECT title,url FROM clips WHERE id=?",(item["id"],)).fetchone()
                elif kind=="moment": extra=c.execute("SELECT title,summary body FROM hq_moment WHERE id=?",(item["id"],)).fetchone()
                elif kind=="pov": extra=c.execute("SELECT label title FROM hq_pov WHERE id=?",(item["id"],)).fetchone()
                elif kind=="wiki": extra=c.execute("SELECT title,body FROM hq_wiki WHERE id=?",(item["id"],)).fetchone()
                else: extra=c.execute("SELECT category title,body FROM hq_posts WHERE id=?",(item["id"],)).fetchone()
                removed.append(dict(kind=kind,**item,**(dict(extra) if extra else {})))
        return reply({"reports":reports,"removed":removed})

@router.post("/admin/social/report/{rid}")
def decide_report(rid:int,p:ReportDecision,r:Request):
    origin(r); u=current(r,admin=True)
    if p.action not in ("remove","dismiss"): fail(400,"Choose remove or dismiss")
    tables={"clip":"clips","moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        report=c.execute("SELECT * FROM hq_reports WHERE id=? AND status='open'",(rid,)).fetchone()
        if not report: fail(409,"Report is no longer open")
        table=tables[report["content_type"]]
        target=c.execute("SELECT uid,state FROM "+table+" WHERE id=?",(report["content_id"],)).fetchone()
        if not target: fail(404,"Reported content no longer exists")
        if int(target["uid"])==u["id"]: fail(403,"Cannot moderate your own content")
        if p.action=="remove":
            if target["state"]!="published": fail(409,"Content is no longer published")
            c.execute("UPDATE "+table+" SET state='removed' WHERE id=?",(report["content_id"],))
        action="removed" if p.action=="remove" else "dismissed"
        c.execute("UPDATE hq_reports SET status=?,action=?,reviewed_by=?,reviewed_at=?,review_note=? WHERE id=? AND status='open'",("actioned" if p.action=="remove" else "dismissed",action,u["id"],now(),clean(p.note,500,False),rid))
        audit(c,u["id"],"social.report."+action,report["content_id"])
    return {"ok":True}

@router.post("/admin/social/content/{kind}/{cid}/restore")
def restore_content(kind:str,cid:int,p:ReportDecision,r:Request):
    origin(r); u=current(r,admin=True)
    if p.action!="restore": fail(400,"Restore action required")
    tables={"clip":"clips","moment":"hq_moment","pov":"hq_pov","wiki":"hq_wiki","post":"hq_posts"}
    table=tables.get(kind)
    if not table: fail(400,"Invalid content type")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        target=c.execute("SELECT uid,state FROM "+table+" WHERE id=?",(cid,)).fetchone()
        if not target: fail(404,"Content not found")
        if int(target["uid"])==u["id"]: fail(403,"Cannot restore your own content")
        if target["state"]!="removed": fail(409,"Content is not removed")
        c.execute("UPDATE "+table+" SET state='published' WHERE id=?",(cid,))
        audit(c,u["id"],"social.content.restore",cid)
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
