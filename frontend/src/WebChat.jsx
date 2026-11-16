import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
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
  const r = await fetch(root + path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!r.ok) {
    const d = await r.json();
    throw Error(typeof d.detail === "string" ? d.detail : "Request rejected.");
  }
  return r;
}
export default function WebChat() {
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
    [ratingBusy, setRatingBusy] = useState(false),
    [speakingId, setSpeakingId] = useState(null);
  const version = useRef(0),
    abort = useRef(null),
    bottom = useRef(null),
    speech = useRef(null);
  function stopSpeech() {
    if (speech.current) {
      speech.current = null;
      window.speechSynthesis?.cancel();
    }
    setSpeakingId(null);
  }
  async function refresh() {
    setList(await (await api()).json());
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    return () => {
      abort.current?.abort();
      if (speech.current) {
        speech.current = null;
        window.speechSynthesis?.cancel();
      }
    };
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);
  async function open(cid) {
    const v = ++version.current;
    stopSpeech();
    setRatingId(null);
    setNotice("");
    setLoading(true);
    setId(cid);
    setMessages([]);
    setError("");
    try {
      const d = await (await api("/" + cid)).json();
      if (v === version.current) setMessages(d.messages);
    } catch (e) {
      if (v === version.current) setError(e.message);
    } finally {
      if (v === version.current) setLoading(false);
    }
  }
  async function create() {
    try {
      const d = await (await api("", "POST", {})).json();
      await refresh();
      await open(d.id);
    } catch (e) {
      setError(e.message);
    }
  }
  async function edit(item, remove = false) {
    const title = remove
      ? null
      : window.prompt("Conversation name", item.title);
    if (remove ? !window.confirm("Delete this conversation?") : !title?.trim())
      return;
    try {
      await api(
        "/" + item.id,
        remove ? "DELETE" : "PATCH",
        remove ? undefined : { title: title.trim() },
      );
      if (remove && id === item.id) {
        stopSpeech();
        ++version.current;
        setId(null);
        setMessages([]);
      }
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  async function send(regenerate = false) {
    if (busy || loading || ratingBusy || !id || (!regenerate && (!draft.trim() || messages.at(-1)?.role === "user"))) return;
    stopSpeech();
    setRatingId(null);
    setBusy(true);
    setError("");
    setNotice("");
    abort.current = new AbortController();
    try {
      const r = await fetch(root + "/" + id + "/messages", {
        method: "POST",
        credentials: "same-origin",
        signal: abort.current.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          regenerate ? { regenerate: true } : { message: draft.trim() },
        ),
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
        : [...messages, { role: "user", content: draft.trim(), created_at: new Date().toISOString() }];
      const created_at = new Date().toISOString();
      setDraft("");
      setMessages([...base, { role: "assistant", content: "", created_at }]);
      const reader = r.body.getReader(),
        decoder = new TextDecoder();
      let buffer = "",
        answer = "",
        complete = false;
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
          if (e.type === "memory_saved") setNotice("Personal memory saved.");
          if (e.type === "memory_not_saved") setNotice(e.message);
          if (e.type === "delta") {
            answer += e.text;
            setMessages([...base, { role: "assistant", content: answer, created_at }]);
          }
        }
        if (chunk.done) break;
      }
      if (!complete) throw Error("Connection interrupted. Please regenerate.");
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    } finally {
      if (!abort.current?.signal.aborted) {
        try {
          setMessages((await (await api("/" + id)).json()).messages);
          await refresh();
        } catch (e) {
          setError(e.message);
        }
        setBusy(false);
      }
    }
  }
  async function rate(message, rating) {
    if (ratingBusy || busy) return;
    setRatingBusy(true);
    setError("");
    const currentVersion = version.current;
    try {
      const result = await (await api(`/${id}/messages/${message.id}/feedback`, "POST", {
        rating, reason: rating === "bad" ? reason.trim() : "",
      })).json();
      if (currentVersion !== version.current) return;
      setMessages((items) => items.map((item) => item.id === message.id
        ? { ...item, rating: result.rating, feedback_reason: result.reason } : item));
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
      <aside className="chat-sidebar">
        <h1>AI Chat</h1>
        <button disabled={busy} onClick={create}>
          ＋ New conversation
        </button>
        <nav aria-label="Conversations">
          {list.map((c) => (
            <div className="chat-conversation" key={c.id}>
              <button
                disabled={busy}
                aria-current={id === c.id ? "page" : undefined}
                onClick={() => open(c.id)}
              >
                {c.title}
              </button>
              <button
                disabled={busy}
                aria-label={"Rename " + c.title}
                onClick={() => edit(c)}
              >
                ✎
              </button>
              <button
                disabled={busy}
                aria-label={"Delete " + c.title}
                onClick={() => edit(c, true)}
              >
                ×
              </button>
            </div>
          ))}
        </nav>
      </aside>
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
                  {m.content || "Thinking…"}
                </ReactMarkdown>
              </div>
              <div className="chat-message-actions">
                <button type="button" onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(m.content);
                    setNotice("Message copied.");
                  } catch {
                    setError("Clipboard unavailable. Select and copy the message.");
                  }
                }}>Copy</button>
                {m.role === "assistant" && m.id && <>
                  <button type="button" disabled={busy || ratingBusy}
                    aria-expanded={ratingId === m.id} aria-label="Rate response"
                    onClick={() => {
                      setRatingId(ratingId === m.id ? null : m.id);
                      setBadRating(false);
                      setReason(m.feedback_reason || "");
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
                  <button disabled={ratingBusy || busy || !reason.trim()}>Submit feedback</button>
                </form>}
                <small>Saved as your personal response preference, used to guide future replies.</small>
              </div>}
            </article>
          ))}
          <div ref={bottom} />
        </div>
        <div role="status">{busy ? "Abud is responding…" : notice}</div>
        {error && (
          <p className="chat-error" role="alert">
            {error}
          </p>
        )}
        {id && (
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
              maxLength={6000}
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
              <button
                disabled={
                  busy || loading || ratingBusy || !draft.trim() || messages.at(-1)?.role === "user"
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
              memory separately from Discord.
            </small>
          </form>
        )}
      </div>
    </section>
  );
}
