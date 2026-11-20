import os,tempfile,unittest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.highest import router,init,bootstrap_admin,db
from app.highest_ops import init as ops_init
from app.highest_social import router as social,init as social_init
from app.highest_live import poll
class SocialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"HIGHEST_DATABASE_PATH":self.tmp.name+"/db.sqlite","HIGHEST_ORIGIN":"https://abud.web.id"});self.env.start();self.addCleanup(self.env.stop)
        init();ops_init();social_init()
        app=FastAPI();app.include_router(router);app.include_router(social)
        self.a,self.u,self.v=[TestClient(app,base_url="https://abud.web.id",headers={"Origin":"https://abud.web.id"}) for _ in range(3)]
        for c,name in ((self.a,"owner"),(self.u,"clipper"),(self.v,"viewer")):
            self.assertEqual(self.post(c,"/register",{"username":name,"display_name":name,"password":"long-test-password"}).status_code,200)
        bootstrap_admin("owner")
    def post(self,c,p,d):return c.post("/highest/api"+p,json=d)
    def get(self,c,p):return c.get("/highest/api"+p)
    def test_moderation_and_pov(self):
        self.assertEqual(self.post(self.u,"/clip",{"title":"Clip","url":"https://youtu.be/example"}).status_code,200)
        cid=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{cid}/published",{}).status_code,200)
        mid=self.post(self.u,"/social/moment",{"title":"Story","summary":"Public RP","spoiler":True}).json()["id"]
        self.assertEqual(self.get(self.v,"/social").json()["moments"],[])
        self.assertEqual(self.post(self.v,f"/social/moment/{mid}/pov",{"clip":cid,"label":"POV"}).status_code,404)
        self.assertEqual(self.post(self.u,f"/social/moment/{mid}/pov",{"clip":cid,"label":"POV"}).status_code,200)
        pid=self.get(self.a,"/admin/social").json()["povs"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{pid}",{"approve":True}).status_code,409)
        self.assertEqual(self.post(self.v,f"/admin/social/moment/{mid}",{"approve":True}).status_code,403)
        self.assertEqual(self.post(self.a,f"/admin/social/moment/{mid}",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.v,"/social").json()["moments"][0]["povs"],[])
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{pid}",{"approve":True}).status_code,200)
        self.assertEqual(len(self.get(self.v,"/social").json()["moments"][0]["povs"]),1)
        second=self.post(self.u,"/social/moment",{"title":"Second story","summary":"More public RP"}).json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/moment/{second}",{"approve":True}).status_code,200)
        self.assertEqual(self.post(self.v,f"/social/moment/{second}/pov",{"clip":cid,"label":"Independent POV"}).status_code,200)
        pending=self.get(self.a,"/admin/social").json()["povs"]
        second_pov=next(x for x in pending if x["moment"]==second)
        self.assertEqual(second_pov["username"],"viewer")
        self.assertEqual(second_pov["clip_owner"],"clipper")
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{second_pov['id']}",{"approve":True}).status_code,200)
        published=next(x for x in self.get(self.v,"/social").json()["moments"] if x["id"]==second)
        self.assertEqual(published["povs"][0]["display_name"],"viewer")
        self.assertEqual(published["povs"][0]["clip_owner"],"clipper")
        for _ in range(2): self.assertEqual(self.post(self.v,f"/social/clip/{cid}/like",{"enabled":True}).status_code,200)
        self.assertEqual(self.get(self.v,"/social").json()["clips"][0]["likes"],1)
        self.assertEqual(self.post(self.v,f"/social/clip/{cid}/bookmark",{"enabled":True}).status_code,200)
        self.assertEqual(len(self.get(self.v,"/social/studio").json()["bookmarks"]),1)
    def test_report_takedown_restore_and_boundaries(self):
        self.assertEqual(self.post(self.u,"/clip",{"title":"Reportable clip","url":"https://youtu.be/reportable"}).status_code,200)
        cid=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{cid}/published",{}).status_code,200)
        report={"content_type":"clip","content_id":cid,"reason":"spam","details":"This looks like a scam link"}
        self.assertEqual(self.post(self.v,"/social/report",report).status_code,200)
        self.assertEqual(self.post(self.v,"/social/report",report).status_code,409)
        self.assertEqual(self.post(self.u,"/social/report",report).status_code,403)
        self.assertEqual(self.post(self.v,"/social/report",{**report,"reason":"unknown"}).status_code,400)
        queue=self.get(self.a,"/admin/social/reports").json()
        self.assertEqual(len(queue["reports"]),1)
        self.assertEqual(queue["reports"][0]["reporter_username"],"viewer")
        self.assertEqual(queue["reports"][0]["content"]["author_username"],"clipper")
        rid=queue["reports"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/report/{rid}",{"action":"remove","note":"Confirmed spam"}).status_code,200)
        self.assertNotIn(cid,[x["id"] for x in self.get(self.v,"/social").json()["clips"]])
        mine=self.get(self.v,"/social/reports").json()["reports"][0]
        self.assertEqual(mine["status"],"actioned")
        self.assertEqual(mine["action"],"removed")
        self.assertEqual(self.post(self.a,f"/admin/social/report/{rid}",{"action":"dismiss"}).status_code,409)
        self.assertEqual(self.post(self.a,f"/admin/social/content/clip/{cid}/restore",{"action":"restore","note":"False positive"}).status_code,200)
        self.assertIn(cid,[x["id"] for x in self.get(self.v,"/social").json()["clips"]])
        self.assertEqual(self.get(self.a,"/admin/social/reports").json()["removed"],[])
        self.assertEqual(self.post(self.v,"/social/report",{"content_type":"clip","content_id":cid,"reason":"other"}).status_code,200)
        self.assertEqual(self.post(self.a,f"/admin/social/report/{self.get(self.a,'/admin/social/reports').json()['reports'][0]['id']}",{"action":"dismiss","note":"No violation"}).status_code,200)
        self.assertEqual(self.get(self.v,"/social/reports").json()["reports"][0]["status"],"dismissed")
        self.assertEqual(self.post(self.u,"/social/wiki",{"kind":"lore","title":"Wiki report target","body":"A public lore entry"}).status_code,200)
        wiki_id=self.get(self.a,"/admin/social").json()["wiki"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/wiki/{wiki_id}",{"approve":True}).status_code,200)
        self.assertEqual(self.post(self.v,"/social/report",{"content_type":"wiki","content_id":wiki_id,"reason":"inappropriate"}).status_code,200)
        wiki_report=self.get(self.a,"/admin/social/reports").json()["reports"][0]
        self.assertEqual(wiki_report["content_type"],"wiki")
        self.assertEqual(self.post(self.a,f"/admin/social/report/{wiki_report['id']}",{"action":"dismiss"}).status_code,200)
        self.assertEqual(self.post(self.a,"/clip",{"title":"Admin-authored clip","url":"https://youtu.be/admin-owned"}).status_code,200)
        admin_clip=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{admin_clip}/published",{}).status_code,200)
        self.assertEqual(self.post(self.v,"/social/report",{"content_type":"clip","content_id":admin_clip,"reason":"spam"}).status_code,200)
        own_report=self.get(self.a,"/admin/social/reports").json()["reports"][0]
        self.assertEqual(self.post(self.a,f"/admin/social/report/{own_report['id']}",{"action":"remove"}).status_code,403)
    def test_comments_replies_likes_and_social_activity(self):
        self.assertEqual(self.post(self.u,"/clip",{"title":"Comment thread clip","url":"https://youtu.be/comments"}).status_code,200)
        cid=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{cid}/published",{}).status_code,200)
        created=self.post(self.v,"/social/comments",{"content_type":"clip","content_id":cid,"body":"Great clip!"})
        self.assertEqual(created.status_code,200)
        comment_id=created.json()["id"]
        owner_activity=self.get(self.u,"/social/activity").json()
        self.assertEqual(owner_activity["unread_count"],2)
        self.assertEqual(owner_activity["items"][0]["kind"],"social_comment")
        self.assertEqual(self.get(self.v,"/social/activity").json()["items"],[])
        reply=self.post(self.u,f"/social/comments/{comment_id}/reply",{"body":"Thanks for watching!"})
        self.assertEqual(reply.status_code,200)
        self.assertEqual(self.get(self.v,"/social/activity").json()["items"][0]["kind"],"social_reply")
        self.assertEqual(self.post(self.u,f"/social/comments/{comment_id}/reply",{"body":"Nested reply is not supported"}).status_code,200)
        self.assertEqual(self.post(self.u,f"/social/comments/{reply.json()['id']}/reply",{"body":"Should not nest"}).status_code,404)
        self.assertEqual(self.post(self.u,f"/social/comments/{comment_id}/like",{"enabled":True}).status_code,200)
        self.assertEqual(self.post(self.u,f"/social/comments/{comment_id}/like",{"enabled":True}).status_code,200)
        self.assertEqual(self.get(self.v,"/social/activity").json()["items"][0]["kind"],"social_comment_like")
        thread=self.get(self.v,f"/social/comments/clip/{cid}").json()
        self.assertEqual(thread["count"],3)
        self.assertEqual(thread["comments"][0]["id"],comment_id)
        self.assertEqual(thread["comments"][0]["likes"],1)
        self.assertEqual(len(thread["comments"][0]["replies"]),2)
        self.assertEqual(thread["comments"][0]["replies"][0]["display_name"],"clipper")
        self.assertEqual(self.post(self.u,f"/social/comments/{comment_id}/delete",{}).status_code,403)
        self.assertEqual(self.post(self.v,f"/social/comments/{comment_id}/delete",{}).status_code,200)
        thread=self.get(self.v,f"/social/comments/clip/{cid}").json()
        self.assertEqual(thread["comments"][0]["body"],"")
        self.assertEqual(thread["comments"][0]["state"],"deleted")
        self.assertEqual(self.post(self.v,"/social/comments",{"content_type":"clip","content_id":999,"body":"Missing target"}).status_code,404)
        self.assertEqual(self.post(self.v,"/social/comments",{"content_type":"clip","content_id":cid,"body":"   "}).status_code,400)
        activity=self.get(self.v,"/social/activity").json()
        self.assertGreaterEqual(activity["unread_count"],2)
        nid=activity["items"][0]["id"]
        self.assertEqual(self.post(self.v,f"/social/activity/{nid}/read",{}).status_code,200)
        self.assertEqual(self.post(self.v,"/social/activity/read-all",{}).status_code,200)
        self.assertEqual(self.get(self.v,"/social/activity").json()["unread_count"],0)
        self.assertEqual(self.get(self.a,f"/social/comments/clip/{cid}").status_code,200)
    def test_pov_discussion_requires_published_parent_and_clip(self):
        self.assertEqual(self.post(self.u,"/clip",{"title":"POV clip","url":"https://youtu.be/pov-comments"}).status_code,200)
        clip_id=self.get(self.a,"/admin").json()["clips"][0]["id"]
        self.assertEqual(self.post(self.a,f"/admin/clip/{clip_id}/published",{}).status_code,200)
        moment_id=self.post(self.u,"/social/moment",{"title":"POV event","summary":"Public RP event"}).json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/moment/{moment_id}",{"approve":True}).status_code,200)
        self.assertEqual(self.post(self.v,f"/social/moment/{moment_id}/pov",{"clip":clip_id,"label":"Viewer POV"}).status_code,200)
        pov_id=self.get(self.a,"/admin/social").json()["povs"][0]["id"]
        self.assertEqual(self.get(self.v,f"/social/comments/pov/{pov_id}").status_code,404)
        self.assertEqual(self.post(self.a,f"/admin/social/pov/{pov_id}",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.v,f"/social/comments/pov/{pov_id}").status_code,200)
        with db() as c:
            c.execute("UPDATE hq_moment SET state='removed' WHERE id=?",(moment_id,))
        self.assertEqual(self.get(self.v,f"/social/comments/pov/{pov_id}").status_code,404)

    def test_youtube_channel_ownership_challenge_auto_verifies(self):
        started=self.post(self.v,"/social/channel-verification",{"kind":"streamer","platform":"youtube","profile_url":"https://www.youtube.com/channel/UC"+"a"*22})
        self.assertEqual(started.status_code,200,started.text)
        verification_id=started.json()["id"]
        challenge=started.json()["challenge"]
        response=MagicMock()
        response.json.return_value={"items":[{"snippet":{"description":"Official channel\\n"+challenge}}]}
        response.raise_for_status.return_value=None
        with patch.dict(os.environ,{"HIGHEST_YOUTUBE_API_KEY":"test-api-key"}):
            with patch("app.highest_social.httpx.Client") as client:
                client.return_value.__enter__.return_value.get.return_value=response
                checked=self.post(self.v,f"/social/channel-verification/{verification_id}/check",{})
        self.assertEqual(checked.status_code,200,checked.text)
        self.assertEqual(checked.json()["status"],"verified")
        self.assertEqual(self.get(self.v,"/social/activity").json()["items"][0]["kind"],"channel_verified")
        studio=self.get(self.v,"/social/studio").json()
        self.assertEqual(studio["verification"][0]["status"],"approved")
        with db() as c:
            self.assertEqual(c.execute("SELECT status FROM hq_channel_verification WHERE id=?",(verification_id,)).fetchone()["status"],"verified")

    def test_streamer_live_transition_notifies_followers_once_per_session(self):
        self.assertEqual(self.post(self.a,"/admin/streamer",{"name":"Live Test","platform":"youtube","channel":"UC"+"b"*22}).status_code,200)
        with db() as c:
            sid=c.execute("SELECT id FROM streamers WHERE channel=?",("UC"+"b"*22,)).fetchone()["id"]
        self.assertEqual(self.post(self.v,f"/social/follow/{sid}",{"enabled":True}).status_code,200)
        with patch("app.highest_live.check",side_effect=[("live","https://youtube.com/watch?v=abcdefghijk"),("live","https://youtube.com/watch?v=abcdefghijk"),("offline",None),("live","https://youtube.com/watch?v=abcdefghijk")]):
            poll();poll();poll();poll()
        with db() as c:
            notices=c.execute("SELECT count(*) FROM hq_notification WHERE uid=? AND kind='streamer_live'",(self.v.get("/highest/api/me").json()["id"],)).fetchone()[0]
        self.assertEqual(notices,2)
        activity=self.get(self.v,"/social/activity").json()
        self.assertEqual(activity["unread_count"],2)
        self.assertTrue(all(x["kind"]=="streamer_live" for x in activity["items"]))

    def test_social_content_approval_notifies_author(self):
        self.assertEqual(self.post(self.v,"/social/post",{"category":"general","body":"Pending community post","spoiler":False}).status_code,200)
        with db() as c:
            post_id=c.execute("SELECT id FROM hq_posts ORDER BY id DESC LIMIT 1").fetchone()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/post/{post_id}",{"approve":True}).status_code,200)
        with db() as c:
            notice=c.execute("SELECT kind,title FROM hq_notification WHERE uid=? AND kind='content_approved'",(self.v.get("/highest/api/me").json()["id"],)).fetchone()
        self.assertIsNotNone(notice)
        self.assertIn("approved",notice["title"].lower())
        activity=self.get(self.v,"/social/activity").json()
        self.assertEqual(activity["items"][0]["kind"],"content_approved")

    def test_creator_wiki_feed(self):
        self.assertEqual(self.post(self.u,"/social/creator",{"kind":"streamer","url":"https://evil.example/a"}).status_code,400)
        self.assertEqual(self.post(self.u,"/social/creator",{"kind":"streamer","url":"https://www.tiktok.com/@test"}).status_code,200)
        uid=self.get(self.u,"/me").json()["id"]
        self.assertEqual(self.post(self.a,f"/admin/social/creator/{uid}/streamer",{"approve":True}).status_code,200)
        self.assertEqual(self.get(self.u,"/internal").status_code,403)
        self.assertEqual(len(self.get(self.v,"/social").json()["creators"]),1)
        self.assertEqual(self.post(self.u,"/social/wiki",{"kind":"lore","title":"Lore","body":"Public IC"}).status_code,200)
        self.assertEqual(self.post(self.u,"/social/post",{"category":"general","body":"Hello"}).status_code,200)
        result=self.get(self.v,"/social").json()
        self.assertEqual(result["wiki"],[]);self.assertEqual(result["posts"],[])
        mod=self.get(self.a,"/admin/social").json()
        for kind,key in (("wiki","wiki"),("post","posts")):
            self.assertEqual(self.post(self.a,f"/admin/social/{kind}/{mod[key][0]['id']}",{"approve":True}).status_code,200)
        result=self.get(self.v,"/social").json()
        self.assertEqual(len(result["wiki"]),1);self.assertEqual(len(result["posts"]),1)
        self.assertEqual(result["wiki"][0]["display_name"],"clipper")
        self.assertEqual(mod["wiki"][0]["username"],"clipper")
        self.assertEqual(mod["posts"][0]["username"],"clipper")
        self.assertEqual(self.post(self.a,"/social/wiki",{"kind":"lore","title":"Admin draft","body":"Self review must be blocked"}).status_code,200)
        own=next(x for x in self.get(self.a,"/admin/social").json()["wiki"] if x["username"]=="owner")
        self.assertEqual(self.post(self.a,f"/admin/social/wiki/{own['id']}",{"approve":True}).status_code,403)
