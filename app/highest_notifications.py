"""In-app HQ notification delivery for approval events and operational reminders."""
import threading
import time
from datetime import datetime, timezone
from app.highest_ops import db, notify

_started = False
_start_lock = threading.Lock()

def _as_aware(value):
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def dispatch_due_reminders():
    current = datetime.now(timezone.utc)
    delivered = 0
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        events = c.execute("""SELECT id,version,title,category,division,owner,location,
            starts_at,ends_at,reminder_minutes,actor
            FROM hq_operation_event
            WHERE reminder_minutes>0 AND status IN ('planned','in_progress')
            ORDER BY starts_at,id""").fetchall()
        for event in events:
            if not event["actor"]:
                continue
            try:
                start = _as_aware(event["starts_at"])
                end = _as_aware(event["ends_at"])
            except (TypeError, ValueError):
                continue
            due = start.timestamp() - int(event["reminder_minutes"]) * 60
            if current.timestamp() < due or current > end:
                continue
            recipients = {int(event["actor"])}
            owner = (event["owner"] or "").strip()
            if owner:
                matched = c.execute("""SELECT u.id FROM users u JOIN membership m ON m.uid=u.id
                    WHERE m.status='approved' AND
                    (u.username=? COLLATE NOCASE OR u.display_name=? COLLATE NOCASE)
                    LIMIT 1""", (owner, owner)).fetchone()
                if matched:
                    recipients.add(int(matched["id"]))
            for uid in recipients:
                inserted = c.execute("""INSERT OR IGNORE INTO hq_notification_dispatch
                    (event_id,version,uid,dispatched_at) VALUES(?,?,?,?)""",
                    (event["id"],event["version"],uid,int(current.timestamp())))
                if inserted.rowcount:
                    body = event["category"] + " · " + start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    if event["location"]:
                        body += " · " + event["location"]
                    if event["division"]:
                        body += " · " + event["division"]
                    notify(c,uid,"operations_reminder","Upcoming: " + event["title"],
                        body,"/highest/internal/",
                        "calendar:"+str(event["id"])+":v"+str(event["version"])+":reminder:"+str(uid))
                    delivered += 1
    return delivered

def worker():
    while True:
        try:
            dispatch_due_reminders()
        except Exception:
            # Keep the worker alive; failures are retried on the next interval.
            pass
        time.sleep(30)

def start_notification_worker():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=worker,daemon=True,name="highest-notifications").start()
