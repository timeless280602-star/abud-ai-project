import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
const root = "/web/chat/conversations";
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
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const version = useRef(0),
    abort = useRef(null),
    bottom = useRef(null);
  async function refresh() {
    setList(await (await api()).json());
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);
  async function open(cid) {
    const v = ++version.current;
    setId(cid);
    setMessages([]);
    setError("");
    try {
      const d = await (await api("/" + cid)).json();
      if (v === version.current) setMessages(d.messages);
    } catch (e) {
      setError(e.message);
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
    if (busy || !id || (!regenerate && !draft.trim())) return;
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
        : [...messages, { role: "user", content: draft.trim() }];
      setDraft("");
      setMessages([...base, { role: "assistant", content: "" }]);
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
          if (e.type === "delta") {
            answer += e.text;
            setMessages([...base, { role: "assistant", content: answer }]);
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
              <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
                {m.content || "Thinking…"}
              </ReactMarkdown>
              <button
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(m.content);
                    setNotice("Message copied.");
                  } catch {
                    setError(
                      "Clipboard unavailable. Select and copy the message.",
                    );
                  }
                }}
              >
                Copy
              </button>
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
              placeholder="Ask anything…"
            />
            <div>
              <button
                disabled={
                  busy || !draft.trim() || messages.at(-1)?.role === "user"
                }
              >
                Send
              </button>
              <button
                type="button"
                disabled={busy || !messages.length}
                onClick={() => send(true)}
              >
                Regenerate response
              </button>
            </div>
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
