"""Periodic external view-count synchronization for published creator clips."""
import os, re, time, threading
from urllib.parse import urlsplit
import httpx
from app.highest import db

_started=False
_lock=threading.Lock()

def refresh():
    youtube_key=os.getenv("HIGHEST_YOUTUBE_API_KEY","")
    tiktok_endpoint=os.getenv("HIGHEST_TIKTOK_STATS_URL","")
    tiktok_token=os.getenv("HIGHEST_TIKTOK_STATS_TOKEN","")
    with db() as c:
        clips=[dict(x) for x in c.execute("SELECT id,url FROM clips WHERE state='published' AND url<>''")]
    updated=0
    youtube=[]
    for item in clips:
        url=item["url"] or ""
        match=re.search(r"(?:youtu\\.be/|youtube\\.com/(?:watch\\?(?:.*&)?v=|embed/|shorts/))([A-Za-z0-9_-]{11})",url)
        if match and youtube_key:
            youtube.append((item["id"],match.group(1)))
            continue
        if "tiktok.com/" not in url or urlsplit(tiktok_endpoint).scheme!="https" or not tiktok_token:
            continue
        try:
            with httpx.Client(timeout=12,follow_redirects=False) as client:
                response=client.get(tiktok_endpoint,params={"url":url},headers={"Authorization":"Bearer "+tiktok_token})
            response.raise_for_status()
            value=response.json().get("views")
            if type(value) is not int or value<0: continue
            with db() as c:
                c.execute("UPDATE clips SET views=?,views_checked=?,views_source='tiktok_provider' WHERE id=? AND state='published'",(value,int(time.time()),item["id"]))
            updated+=1
        except Exception:
            continue
    for offset in range(0,len(youtube),50):
        batch=youtube[offset:offset+50]
        try:
            with httpx.Client(timeout=15) as client:
                response=client.get("https://www.googleapis.com/youtube/v3/videos",params={"part":"statistics","id":",".join(x[1] for x in batch),"key":youtube_key})
            response.raise_for_status()
            items=response.json().get("items")
            if not isinstance(items,list): continue
            values={x.get("id"):int(x["statistics"]["viewCount"]) for x in items if x.get("id") and str(x.get("statistics",{}).get("viewCount","")).isdigit()}
            with db() as c:
                for cid,video_id in batch:
                    if video_id in values:
                        c.execute("UPDATE clips SET views=?,views_checked=?,views_source='youtube_data_api' WHERE id=? AND state='published'",(values[video_id],int(time.time()),cid))
                        updated+=1
        except Exception:
            continue
    return {"updated":updated,"total":len(clips)}

def worker():
    interval=max(3600,int(os.getenv("HIGHEST_STATS_INTERVAL","21600")))
    while True:
        try: refresh()
        except Exception: pass
        time.sleep(interval)

def start_stats_worker():
    global _started
    with _lock:
        if _started: return
        _started=True
        threading.Thread(target=worker,daemon=True,name="highest-stats").start()
