import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import ChatOrganization from "./ChatOrganization";
import ChatChoices from "./ChatChoices";
import { eligibleChoices } from "./chatChoices";
import ChatImages from "./ChatImages";
import { imageQuotaMessage } from "./imageQuota";
import { chatApi } from "./chatApi";
const root = "/web/chat/conversations";
const messageTime = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "short", day: "numeric",
  hour: "2-digit", minute: "2-digit", timeZoneName: "short",
});
function speechLanguage(text) {
  if (/[\u3040-\u30ff]/u.test(text)) return "ja-JP";
  if (/[\uac00-\ud7af]/u.test(text)) return "ko-KR";
  if (/[\u4e00-\u9fff]/u.test(text)) return "zh-CN";
  if (/[\u0600-\u06ff]/u.test(text)) return "ar-SA";
  const words = text.toLowerCase().match(/[a-z]+/g) || [];
  const count = (vocabulary) => words.filter((word) => vocabulary.includes(word)).length;
  const indonesian = count(["yang", "dan", "di", "ini", "itu", "untuk", "dengan", "kamu", "saya", "bisa", "tidak", "adalah", "aku", "anda", "halo", "terima", "kasih"]);
  const english = count(["the", "and", "is", "are", "this", "that", "for", "with", "you", "your", "can", "not", "hello", "thanks"]);
  return indonesian > english ? "id-ID" : english > indonesian ? "en-US" : navigator.language;
}
async function api(path = "", method = "GET", body) {
  return chatApi("/conversations" + path, method, body);
}
export default function WebChat({ onOpenIntegrations } = {}) {
  const [projects, setProjects] = useState([]),
    [projectId, setProjectId] = useState(null),
    [archived, setArchived] = useState(false),
    [archivedChat, setArchivedChat] = useState(false);
  const listVersion = useRef(0), titleRefresh = useRef(null);
  const [list, setList] = useState([]),
    [id, setId] = useState(null),
    [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState(""),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [ratingId, setRatingId] = useState(null),
    [badRating, setBadRating] = useState(false),
    [reason, setReason] = useState(""),
    [feedbackCategory, setFeedbackCategory] = useState(""),
    [ratingBusy, setRatingBusy] = useState(false),
    [speakingId, setSpeakingId] = useState(null);
  const shareCategory = !projectId || projects.some((project) => project.id === projectId && project.memory_mode === "default");
  const sending = useRef(false);
  const [attachment, setAttachment] = useState(null);
  const attachmentInput = useRef(null);
  function clearAttachment() {
    setAttachment(null);
    if (attachmentInput.current) attachmentInput.current.value = "";
  }
  const [imageLoading, setImageLoading] = useState(false);
  const invalidatedChoices = useRef(new Set());
  const [choicesBlocked, setChoicesBlocked] = useState(false);
  const version = useRef(0),
    abort = useRef(null),
    bottom = useRef(null),
    speech = useRef(null);
  const renderedVersion = version.current;
  const choiceKey = `${id}:${messages.at(-1)?.id}`;
  let choiceInvalidated = invalidatedChoices.current.has(choiceKey);
  try {
    choiceInvalidated ||= sessionStorage.getItem(`abud:invalidated-choice:${choiceKey}`) === "1";
  } catch { /* Storage may be unavailable; in-memory invalidation still applies. */ }
  const choices = !choiceInvalidated && eligibleChoices(messages.at(-1), messages.at(-1));
  function stopSpeech() {
    if (speech.current) {
      speech.current = null;
      window.speechSynthesis?.cancel();
    }
    setSpeakingId(null);
  }
  async function refresh() {
    const v = ++listVersion.current;
    const query = new URLSearchParams({ archived: String(archived) });
    if (projectId) query.set("project_id", projectId);
    const [chats, groups] = await Promise.all([api("?" + query), chatApi("/projects")]);
    const [chatData, groupData] = await Promise.all([chats.json(), groups.json()]);
    if (v === listVersion.current) { setList(chatData); setProjects(groupData); }
  }
  useEffect(() => {
    return () => {
      abort.current?.abort();
      clearTimeout(titleRefresh.current);
      if (speech.current) {
        speech.current = null;
        window.speechSynthesis?.cancel();
      }
    };
  }, []);
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [projectId, archived]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);
  async function open(cid) {
    if (sending.current) return;
    const v = ++version.current;
    stopSpeech();
    setRatingId(null);
    setNotice("");
    setLoading(true);
    setId(cid);
    clearAttachment();
    setMessages([]);
    setError("");
    try {
      const d = await (await api("/" + cid)).json();
      if (v === version.current) { setMessages(d.messages); setChoicesBlocked(false); setArchivedChat(Boolean(d.archived_at)); }
    } catch (e) {
      if (v === version.current) setError(e.message);
    } finally {
      if (v === version.current) setLoading(false);
    }
  }
  async function create() {
    if (sending.current) return;
    try {
      const d = await (await api("", "POST", { project_id: projectId })).json();
      await refresh();
      await open(d.id);
    } catch (e) {
      setError(e.message);
    }
  }
  function view(pid, showArchived) {
    if (sending.current) return;
    ++version.current;
    ++listVersion.current;
    stopSpeech();
    clearAttachment();
    setId(null); setMessages([]); setList([]); setRatingId(null); setError(""); setNotice("");
    clearTimeout(titleRefresh.current);
    setArchivedChat(false); setProjectId(pid); setArchived(showArchived);
    if (pid === projectId && showArchived === archived) refresh().catch((e) => setError(e.message));
  }
  function organizationChanged(change) {
    if (change.project === projectId) view(null, false);
    else if (change.clear && change.conversation === id) {
      ++version.current;
      clearAttachment();
      stopSpeech(); setId(null); setMessages([]); setRatingId(null); setArchivedChat(false);
    }
  }
  async function send(regenerate = false, choiceText, sourceId) {
    const text = (choiceText ?? draft).trim();
    const file = !regenerate && choiceText === undefined ? attachment : null;
    if (sourceId !== undefined && (choicesBlocked || invalidatedChoices.current.has(`${id}:${sourceId}`) || sourceId !== messages.at(-1)?.id)) return;
    if (renderedVersion !== version.current || sending.current || busy || loading || ratingBusy || archivedChat || !id || (file && text.length > 1000) || (!regenerate && ((!text && !file) || (messages.at(-1)?.role === "user" || messages.at(-1)?.incomplete)))) return;
    sending.current = true;
    setChoicesBlocked(true);
    const currentVersion = version.current;
    if (regenerate && messages.at(-1)?.role === "assistant" && messages.at(-1)?.id) {
      // Invalidate before the request: a failed regenerate can restore this exact ID.
      invalidatedChoices.current.add(choiceKey);
      try {
        sessionStorage.setItem(`abud:invalidated-choice:${choiceKey}`, "1");
      } catch { /* Keep the in-memory tombstone even if tab storage is unavailable. */ }
    }
    stopSpeech();
    setRatingId(null);
    setBusy(true);
    setError("");
    setNotice("");
    abort.current = new AbortController();
    let reader;
    try {
      const requestId = regenerate ? null : crypto.randomUUID();
      let body;
      if (file) {
        body = new FormData();
        body.append("attachment", file);
        body.append("message", text);
        body.append("request_id", requestId);
      } else {
        body = JSON.stringify(regenerate
          ? { regenerate: true }
          : { message: text, request_id: requestId });
      }
      const r = await fetch(root + "/" + id + (file ? "/attachment-messages" : "/messages"), {
        method: "POST",
        credentials: "same-origin",
        signal: abort.current.signal,
        headers: file ? undefined : { "Content-Type": "application/json" },
        body,
      });
      if (!r.ok) {
        const d = await r.json();
        throw Error(
          typeof d.detail === "string" ? d.detail : "Message rejected.",
        );
      }
      const base = regenerate
        ? messages.at(-1)?.role === "assistant"
          ? messages.slice(0, -1)
          : messages
        : [...messages, { role: "user", content: file ? [text, `Lampiran: ${file.name}`].filter(Boolean).join("\n\n") : text, created_at: new Date().toISOString() }];
      const created_at = new Date().toISOString();
      setDraft("");
      if (file) clearAttachment();
      setMessages([...base, { role: "assistant", content: "", created_at }]);
      reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "",
        answer = "",
        complete = false, images = [];
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop();
        for (const f of frames) {
          if (!f.startsWith("data: ")) continue;
          const e = JSON.parse(f.slice(6));
          if (e.type === "error") throw Error(e.message);
          if (e.type === "done") complete = true;
          if (e.type === "image_loading") setImageLoading(true);
          if (e.type === "image_quota") setNotice(imageQuotaMessage(e));
          if (e.type === "images") {
            images = e.images;
            setMessages([...base, { role: "assistant", content: answer, images, created_at }]);
          }
          if (e.type === "memory_saved") setNotice("Personal memory saved.");
          if (e.type === "memory_not_saved") setNotice(e.message);
          if (e.type === "delta") {
            answer += e.text;
            setMessages([...base, { role: "assistant", content: answer, images, created_at }]);
          }
        }
        if (chunk.done) break;
      }
      if (!complete) throw Error("Connection interrupted. Please regenerate.");
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
      setMessages((items) => items.map((item) =>
        item.role === "assistant" && !item.id ? { ...item, incomplete: true } : item));
    } finally {
      // Release the HTTP stream promptly on parsing errors or server error events.
      if (reader) {
        try { await reader.cancel(); } catch { /* The connection may already be closed. */ }
        reader.releaseLock();
      }
      if (!abort.current?.signal.aborted && currentVersion === version.current) {
        try {
          setMessages((await (await api("/" + id)).json()).messages);
          setChoicesBlocked(false);
          await refresh();
          clearTimeout(titleRefresh.current);
          titleRefresh.current = setTimeout(() => refresh().catch(() => {}), 5500);
        } catch (e) {
          setError(e.message);
        }
      }
      sending.current = false;
      setBusy(false);
      setImageLoading(false);
    }
  }
  async function rate(message, rating) {
    if (ratingBusy || busy) return;
    setRatingBusy(true);
    setError("");
    const currentVersion = version.current;
    try {
      const category = rating === "bad" && shareCategory ? feedbackCategory || null : null;
      const result = await (await api(`/${id}/messages/${message.id}/feedback`, "POST", {
        rating, reason: rating === "bad" ? reason.trim() : "", improvement_category: category,
      })).json();
      if (currentVersion !== version.current) return;
      setMessages((items) => items.map((item) => item.id === message.id
        ? { ...item, rating: result.rating, feedback_reason: result.reason, feedback_category: category } : item));
      setRatingId(null);
      setReason("");
      setNotice("Feedback saved to personal memory for future responses.");
    } catch (e) {
      if (currentVersion === version.current) setError(e.message);
    } finally {
      setRatingBusy(false);
    }
  }
  function readAloud(message, element) {
    if (speakingId === message.id) { stopSpeech(); return; }
    stopSpeech();
    if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
      setError("Read aloud is not supported by this browser.");
      return;
    }
    const text = element.closest("article").querySelector(".chat-message-body").innerText;
    const lang = speechLanguage(text);
    const voices = window.speechSynthesis.getVoices();
    const voice = voices.find((v) => v.lang.toLowerCase() === lang.toLowerCase())
      || voices.find((v) => v.lang.split("-")[0] === lang.split("-")[0]);
    const chunks = text.match(/[\s\S]{1,180}(?:\s|$)|[\s\S]{1,180}/g) || [];
    const session = {};
    speech.current = session;
    setSpeakingId(message.id);
    function next() {
      if (speech.current !== session) return;
      const chunk = chunks.shift();
      if (!chunk) { speech.current = null; setSpeakingId(null); return; }
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = lang;
      if (voice) utterance.voice = voice;
      utterance.onend = next;
      utterance.onerror = () => {
        if (speech.current !== session) return;
        stopSpeech();
        setError("Could not read this message. Check your device's available voices.");
      };
      session.utterance = utterance;
      try {
        window.speechSynthesis.speak(utterance);
      } catch {
        utterance.onerror();
      }
    }
    next();
  }
  return (
    <section className="web-chat" aria-label="AI Chat">
      <ChatOrganization list={list} projects={projects} projectId={projectId} archived={archived}
        busy={busy || ratingBusy} id={id} onOpen={open} onCreate={create} onView={view}
        onRefresh={refresh} onChanged={organizationChanged} />
      <div className="chat-main">
        <div className="chat-messages" aria-busy={busy}>
          {!id && (
            <div className="chat-empty">
              <h2>Talk with Abud</h2>
              <p>Create a conversation to begin. No Discord account needed.</p>
            </div>
          )}
          {id && !messages.length && <p>How can I help you today?</p>}
          {messages.map((m, i) => (
            <article className={"chat-message " + m.role} key={m.id || i}>
              <strong>{m.role === "user" ? "You" : "Abud"}</strong>
              {m.created_at && <time className="chat-time" dateTime={m.created_at}
                title={new Date(m.created_at).toLocaleString()}>{messageTime.format(new Date(m.created_at))}</time>}
              <div className="chat-message-body">
                <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
                  {m.content || (m.incomplete ? "No response received." : "Thinking…")}
                </ReactMarkdown>
                {m.images?.length > 0 && <ChatImages images={m.images} />}
                {m.incomplete && <small>Incomplete response · Regenerate to retry.</small>}
              </div>
              {m === messages.at(-1) && choices && !archivedChat && !loading &&
                <ChatChoices key={`${projectId}:${id}:${m.id}`}
                  group={choices}
                  disabled={busy || ratingBusy || choicesBlocked}
                  onSend={(text) => send(false, text, m.id)} />}
              <div className="chat-message-actions">
                <button type="button" onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(m.content);
                    setNotice("Message copied.");
                  } catch {
                    setError("Clipboard unavailable. Select and copy the message.");
                  }
                }}>Copy</button>
                {m.role === "assistant" && onOpenIntegrations && /^\s*buat paket konten\s*:/i.test(messages[i - 1]?.content ?? "") &&
                  <button type="button" disabled={busy} onClick={onOpenIntegrations}>Buat desain di Canva</button>}
                {m.role === "assistant" && m.id && <>
                  <button type="button" disabled={busy || ratingBusy}
                    aria-expanded={ratingId === m.id} aria-label="Rate response"
                    onClick={() => {
                      setRatingId(ratingId === m.id ? null : m.id);
                      setBadRating(false);
                      setReason(m.feedback_reason || "");
                      setFeedbackCategory(m.feedback_category || "");
                    }}>Rate response{m.rating ? ` · ${m.rating === "good" ? "Good" : "Bad"}` : ""}</button>
                  <button type="button" aria-pressed={speakingId === m.id}
                    onClick={(e) => readAloud(m, e.currentTarget)}>
                    {speakingId === m.id ? "Stop reading" : "Read aloud"}
                  </button>
                </>}
              </div>
              {ratingId === m.id && <div className="chat-feedback" aria-label="Response feedback">
                <div className="chat-message-actions">
                  <button type="button" disabled={ratingBusy || busy} onClick={() => rate(m, "good")}>Good response</button>
                  <button type="button" disabled={ratingBusy || busy} aria-expanded={badRating}
                    onClick={() => setBadRating(true)}>Bad response</button>
                  <button type="button" disabled={ratingBusy} onClick={() => setRatingId(null)}>Cancel</button>
                </div>
                {badRating && <form onSubmit={(e) => { e.preventDefault(); rate(m, "bad"); }}>
                  <label htmlFor={`feedback-${m.id}`}>What was wrong or should be improved?</label>
                  <textarea id={`feedback-${m.id}`} value={reason} required maxLength={500}
                    disabled={ratingBusy} onChange={(e) => setReason(e.target.value)} />
                  {shareCategory && <label>
                    Share an issue category with the creator (optional)
                    <select value={feedbackCategory} disabled={ratingBusy} onChange={(e) => setFeedbackCategory(e.target.value)}>
                      <option value="">Keep feedback private</option>
                      <option value="accuracy">Accuracy</option>
                      <option value="missing_context">Missing context</option>
                      <option value="instructions">Did not follow instructions</option>
                      <option value="clarity">Clarity</option>
                    </select>
                    <small>Only the category is included in aggregate counts.</small>
                  </label>}
                  <button disabled={ratingBusy || busy || !reason.trim()}>Submit feedback</button>
                </form>}
                <small>Saved as your personal response preference, used to guide future replies.</small>
              </div>}
            </article>
          ))}
          <div ref={bottom} />
        </div>
        <div role="status">{busy ? (imageLoading ? "Generating image…" : "Abud is responding…") : notice}</div>
        {error && (
          <p className="chat-error" role="alert">
            {error}
          </p>
        )}
        {id && archivedChat && <p className="chat-archive-notice">Archived chat · Restore it from the conversation menu to continue.</p>}
        {id && !archivedChat && (
          <form
            className="chat-composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <label htmlFor="chat-draft">Message Abud</label>
            <textarea
              id="chat-draft"
              value={draft}
              disabled={busy}
              maxLength={attachment ? 1000 : 6000}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask anything…"
            />
            <div>
              <label htmlFor="chat-attachment">Lampiran PDF, Word, atau PowerPoint</label>
              <input
                id="chat-attachment"
                ref={attachmentInput}
                type="file"
                accept=".pdf,.docx,.pptx"
                disabled={busy || loading}
                onChange={(event) => {
                  const selected = event.target.files[0];
                  if (selected && selected.size > 5 * 1024 * 1024) {
                    clearAttachment();
                    setError("Ukuran lampiran maksimal 5 MB.");
                    return;
                  }
                  setError("");
                  setAttachment(selected ?? null);
                }}
              />
              {attachment && <button type="button" disabled={busy} onClick={clearAttachment}>Hapus lampiran</button>}
              {attachment && <small>Cuplikan teks lampiran akan disimpan dalam riwayat chat.</small>}
            </div>
            <div>
              <button
                disabled={
                  busy || loading || ratingBusy || (!draft.trim() && !attachment) || (attachment && draft.trim().length > 1000) || (messages.at(-1)?.role === "user" || messages.at(-1)?.incomplete)
                }
              >
                Send
              </button>
              <button
                type="button"
                disabled={busy || loading || ratingBusy || !messages.length}
                onClick={() => send(true)}
              >
                Regenerate response
              </button>
            </div>
            <small>
              Enter to send · Shift+Enter for a new line. Times use your device's time zone.
            </small>
            <small>
              AI can make mistakes. Explicit remember requests save personal
              memory separately from Discord. In Project-Only mode, saved memories and feedback stay inside that project.
            </small>
          </form>
        )}
      </div>
    </section>
  );
}
