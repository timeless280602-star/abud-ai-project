import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { chatApi } from "./chatApi";

function Dialog({ title, children, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    const dialog = ref.current;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="chat-dialog" aria-labelledby="chat-dialog-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
    <header><h2 id="chat-dialog-title">{title}</h2><button type="button" aria-label="Close dialog" onClick={onClose}>×</button></header>
    {children}
  </dialog>;
}

export default function ChatOrganization({ list, projects, projectId, archived, busy, id, onOpen, onCreate, onView, onRefresh, onChanged, navigationTarget }) {
  const [menu, setMenu] = useState(null), [editor, setEditor] = useState(null),
    [saving, setSaving] = useState(false), [error, setError] = useState("");
  const menuRef = useRef(null), menuButton = useRef(null);
  const selected = projects.find((p) => p.id === projectId);
  useEffect(() => {
    if (!menu) return;
    menuRef.current?.querySelector("button")?.focus();
    const outside = (e) => { if (!menuRef.current?.contains(e.target) && !menuButton.current?.contains(e.target)) setMenu(null); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [menu]);
  function closeMenu() { setMenu(null); menuButton.current?.focus(); }
  function show(value) { setEditor(value); setError(""); closeMenu(); }
  async function run(action, changed) {
    setSaving(true); setError(""); closeMenu();
    try {
      await action();
      if (changed) onChanged(changed);
      if (!changed?.project) await onRefresh();
      setEditor(null);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }
  function projectEditor(project = null) {
    show({ type: "project", project, name: project?.name || "", description: project?.description || "",
      instructions: project?.instructions || "", memory_mode: project?.memory_mode || "default" });
  }
  const update = (field, value) => setEditor((old) => ({ ...old, [field]: value }));
  const navigation = <div className="chat-sidebar" role="region" aria-label="Chat navigation">
      <h2 className="chat-section-label">PROJECTS</h2>
      <button disabled={busy || saving} onClick={() => projectEditor()}>＋ New project</button>
      <nav aria-label="Projects">
        {projects.map((p) => <button className="chat-project-link" key={p.id} disabled={busy || saving}
          aria-current={projectId === p.id && !archived ? "page" : undefined} onClick={() => onView(p.id, false)}>
          <span>{p.name}</span><small>{p.conversation_count || 0} · {p.memory_mode === "project_only" ? "Project-only" : "Default"}</small>
        </button>)}
      </nav>
      <h2 className="chat-section-label">CHATS</h2>
      <div className="chat-view-actions">
        <button disabled={busy || saving} aria-pressed={!projectId && !archived} onClick={() => onView(null, false)}>Recent chats</button>
        <button disabled={busy || saving} aria-pressed={archived} onClick={() => onView(null, true)}>Archived chats</button>
      </div>
      <button disabled={busy || saving || archived} onClick={onCreate}>＋ New conversation</button>
      <nav aria-label="Conversations">
        {!list.length && <p className="chat-sidebar-hint">{archived ? "No archived chats." : "No conversations yet."}</p>}
        {list.map((c, index) => <React.Fragment key={c.id}>
          {(index === 0 || Boolean(list[index - 1].pinned) !== Boolean(c.pinned)) && <h3 className="chat-section-label">{c.pinned ? "Pinned" : "Recent"}</h3>}
          <div className="chat-conversation">
            <button disabled={busy || saving} aria-current={id === c.id ? "page" : undefined} onClick={() => onOpen(c.id)}>
              {c.pinned ? "📌 " : ""}{c.title}
              {archived && c.project_name && <small className="chat-project-caption">{c.project_name}</small>}
            </button>
            <button disabled={busy || saving} aria-label={`Options for ${c.title}`} aria-haspopup="menu" aria-expanded={menu === c.id}
              onClick={(e) => { menuButton.current = e.currentTarget; setMenu(menu === c.id ? null : c.id); }}>⋯</button>
            {menu === c.id && <div className="chat-context-menu" role="menu" ref={menuRef} onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); closeMenu(); }
              if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
                e.preventDefault();
                const buttons = [...menuRef.current.querySelectorAll("button")];
                let at = buttons.indexOf(document.activeElement);
                at = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : (at + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
                buttons[at].focus();
              }
            }}>
              <button role="menuitem" onClick={() => show({ type: "rename", conversation: c, name: c.title })}>Rename</button>
              <button role="menuitem" onClick={() => run(() => chatApi(`/conversations/${c.id}/pin`, "PATCH", { enabled: !c.pinned }))}>{c.pinned ? "Unpin" : "Pin"}</button>
              <button role="menuitem" onClick={() => run(() => chatApi(`/conversations/${c.id}/archive`, "PATCH", { enabled: !c.archived_at }), { conversation: c.id, clear: true })}>{c.archived_at ? "Unarchive" : "Archive"}</button>
              <button role="menuitem" onClick={() => show({ type: "move", conversation: c, project_id: c.project_id || "" })}>Move to project</button>
              <button role="menuitem" onClick={() => show({ type: "delete-chat", conversation: c })}>Delete</button>
            </div>}
          </div>
        </React.Fragment>)}
      </nav>
      {error && !editor && <p role="alert" className="chat-error">{error}</p>}
    </div>;
  return <>
    {navigationTarget && createPortal(navigation, navigationTarget)}
    {selected && !archived && <div className="chat-project-panel">
      <div><h2>{selected.name}</h2><span className="chat-memory-mode">{selected.memory_mode === "project_only" ? "Project-only memory" : "Default memory"}</span></div>
      {selected.description && <p>{selected.description}</p>}
      <details><summary>Project instructions</summary><p>{selected.instructions || "No custom instructions."}</p></details>
      <div className="chat-view-actions"><button disabled={busy || saving} onClick={onCreate}>New chat in project</button>
        <button disabled={busy || saving} onClick={() => projectEditor(selected)}>Project settings</button>
        <button disabled={busy || saving} onClick={() => show({ type: "delete-project", project: selected, disposition: "keep", confirm: false })}>Delete project</button></div>
    </div>}
    {editor && <Dialog title={{ project: editor.project ? "Project settings" : "New project", rename: "Rename conversation", move: "Move conversation", "delete-chat": "Delete conversation", "delete-project": "Delete project" }[editor.type]}
      onClose={() => { if (!saving) setEditor(null); }}>
      {error && <p role="alert" className="chat-error">{error}</p>}
      <form onSubmit={(e) => {
        e.preventDefault();
        if (saving) return;
        if (editor.type === "project") {
          const body = { name: editor.name.trim(), description: editor.description, instructions: editor.instructions };
          if (!editor.project) body.memory_mode = editor.memory_mode;
          run(() => chatApi(editor.project ? `/projects/${editor.project.id}` : "/projects", editor.project ? "PATCH" : "POST", body));
        } else if (editor.type === "rename") {
          run(() => chatApi(`/conversations/${editor.conversation.id}`, "PATCH", { title: editor.name.trim() }));
        } else if (editor.type === "move") {
          run(() => chatApi(`/conversations/${editor.conversation.id}/project`, "PATCH", { project_id: editor.project_id || null }), { conversation: editor.conversation.id, clear: true });
        } else if (editor.type === "delete-chat") {
          run(() => chatApi(`/conversations/${editor.conversation.id}`, "DELETE"), { conversation: editor.conversation.id, clear: true });
        } else if (editor.type === "delete-project" && editor.confirm) {
          run(() => chatApi(`/projects/${editor.project.id}`, "DELETE", { conversations: editor.disposition }), { project: editor.project.id });
        }
      }}>
        {["project", "rename"].includes(editor.type) && <label>Name<input aria-label="Name" required autoFocus maxLength={100} value={editor.name} disabled={saving} onChange={(e) => update("name", e.target.value)} /></label>}
        {editor.type === "project" && <>
          <label>Description (optional)<textarea aria-label="Description (optional)" maxLength={1000} value={editor.description} disabled={saving} onChange={(e) => update("description", e.target.value)} /></label>
          <label>AI instructions (optional)<textarea aria-label="AI instructions (optional)" maxLength={4000} value={editor.instructions} disabled={saving} onChange={(e) => update("instructions", e.target.value)} /></label>
          <label>Memory mode<select aria-label="Memory mode" value={editor.memory_mode} disabled={Boolean(editor.project) || saving} onChange={(e) => update("memory_mode", e.target.value)}>
            <option value="default">Default Memory</option><option value="project_only">Project-Only Memory</option>
          </select></label>
          <p>Default Memory uses your authorized web personal memories and shared global knowledge. Project-Only uses only this chat, project instructions and memories saved inside this project. Other chats are not read automatically.</p>
          <p>Memory mode cannot be changed after creation. Project instructions cannot override security policies.</p>
        </>}
        {editor.type === "move" && <>
          <label>Destination project<select aria-label="Destination project" value={editor.project_id} disabled={saving} onChange={(e) => update("project_id", e.target.value)}>
            <option value="">Ordinary chats (no project)</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.memory_mode === "project_only" ? "Project-only" : "Default"}</option>)}
          </select></label>
          <p>Messages are preserved. Memories are never transferred. Only empty chats can cross a Project-Only memory boundary.</p>
        </>}
        {editor.type === "delete-chat" && <p>Delete “{editor.conversation.title}” and all its messages? Separately saved personal or project memories remain. This cannot be undone.</p>}
        {editor.type === "delete-project" && <>
          <p>Delete “{editor.project.name}”? Choose explicitly what happens to its conversations.</p>
          <label>Conversation history<select aria-label="Conversation history" value={editor.disposition} disabled={saving} onChange={(e) => { update("disposition", e.target.value); update("confirm", false); }}>
            <option value="keep">Keep conversations as ordinary chats</option><option value="delete">Delete conversations and their messages</option>
          </select></label>
          <p>Project-Only chats with messages cannot be detached into ordinary chats. Keep the project and archive its chats to preserve their isolation. Deleting a Project-Only project removes its dedicated project memories. Default personal memories remain.</p>
          <label><input type="checkbox" checked={editor.confirm} disabled={saving} onChange={(e) => update("confirm", e.target.checked)} /> I confirm this project deletion and the selected history action.</label>
        </>}
        <footer><button type="button" disabled={saving} onClick={() => setEditor(null)}>Cancel</button>
          <button disabled={saving || (["project", "rename"].includes(editor.type) && !editor.name.trim()) || (editor.type === "delete-project" && !editor.confirm)}>{saving ? "Saving…" : editor.type.startsWith("delete") ? "Delete permanently" : "Save"}</button></footer>
      </form>
    </Dialog>}
  </>;
}
