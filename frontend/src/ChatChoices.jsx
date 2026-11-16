import React, { useState } from "react";
import { choicePrompt } from "./chatChoices";

export default function ChatChoices({ group, disabled, onSend }) {
  const [selected, setSelected] = useState([]);
  return <section className="chat-choices" aria-label="Pilihan respons">
    <p>Pilih maksimal dua opsi.</p>
    <div className="chat-choice-options">
      {group.options.map((option) => <button type="button" key={option.label}
        aria-pressed={selected.includes(option.label)}
        disabled={disabled || (selected.length === 2 && !selected.includes(option.label))}
        onClick={() => setSelected((items) => items.includes(option.label)
          ? items.filter((label) => label !== option.label) : items.length < 2 ? [...items, option.label] : items)}>
        {option.label}. {option.text}
      </button>)}
    </div>
    <p role="status">{selected.length} of 2 selected</p>
    <button type="button" disabled={disabled || !selected.length}
      onClick={() => onSend(choicePrompt(group, selected))}>Lanjutkan dengan pilihan</button>
  </section>;
}
