"""Cached livestream polling. Never mark a failed provider query offline."""
import os, re, time, threading
from urllib.parse import urlsplit
import httpx
from app.highest import db

def check(s):
    if s["platform"]=="youtube":
        key=os.getenv("HIGHEST_YOUTUBE_API_KEY")
        if not key: return "unknown",None
        with httpx.Client(timeout=12) as client:
            r=client.get("https://www.googleapis.com/youtube/v3/search",params={"part":"id","channelId":s["channel"],"eventType":"live","type":"video","maxResults":1,"key":key})
            r.raise_for_status()
            data=r.json()
            if not isinstance(data.get("items"),list): raise ValueError("Malformed YouTube response")
            if not data["items"]: return "offline",None
            video=data["items"][0]["id"]["videoId"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}",video): raise ValueError("Invalid video")
            return "live","https://www.youtube.com/watch?v="+video
    endpoint=os.getenv("HIGHEST_TIKTOK_STATUS_URL","")
    token=os.getenv("HIGHEST_TIKTOK_STATUS_TOKEN","")
    if urlsplit(endpoint).scheme!="https" or not token: return "unknown",None
    # Operator-configured provider contract: GET ?username=... -> {"live": true|false}.
    with httpx.Client(timeout=12,follow_redirects=False) as client:
        r=client.get(endpoint,params={"username":s["channel"]},headers={"Authorization":"Bearer "+token})
        r.raise_for_status()
        status=r.json().get("live")
        if type(status) is not bool: raise ValueError("Invalid status")
        return ("live","https://www.tiktok.com/@"+s["channel"]+"/live") if status else ("offline",None)

def poll():
    with db() as c: streams=[dict(x) for x in c.execute("SELECT * FROM streamers")]
    for s in streams:
        try: status,url=check(s)
        except Exception: status,url="unknown",None
        with db() as c:
            c.execute("UPDATE streamers SET status=?,checked=?,live_url=? WHERE id=?",(status,int(time.time()),url,s["id"]))
def worker():
    while True:
        try: poll()
        except Exception: pass
        try: interval=max(300,int(os.getenv("HIGHEST_LIVE_INTERVAL","3600")))
        except ValueError: interval=3600
        time.sleep(interval)
def start_live_worker():
    threading.Thread(target=worker,daemon=True,name="highest-live").start()
