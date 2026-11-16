// Deliberately conservative: numeric/bulleted lists need an explicit decision cue.
const decision = /(?:\b(?:choose|select|pick)\b.{0,55}\b(?:action|option|path|one|two)\b|\b(?:your choice|what (?:do|will) you do)\b|\b(?:pilih|pilihanmu|pilihan kamu|apa yang (?:kamu|akan)|mau pilih)\b)/i;
const technical = /\b(?:tutorial|instructions|installation|install|dependencies|deploy|documentation|configuration|command output|references|citations|konfigurasi|instalasi|panduan|langkah-langkah|referensi)\b/i;
const action = /^(?:\*\*)?(?:open|investigate|call|wait|hide|run|leave|enter|ask|talk|follow|take|use|keep|choose|try|buy|accept|decline|stay|search|listen|go|membuka|buka|menyelidiki|selidiki|memanggil|panggil|menunggu|tunggu|pergi|masuk|bertanya|ikuti|mengambil|ambil|gunakan|memilih|pilih|mencoba|coba|membeli|beli|terima|tolak|diam|cari|mencari|dengarkan)\b/i;
const story = /\b(?:story|scene|narrative|cerita|adegan|kisah)\b/i;

export function parseChoices(text) {
  if (typeof text !== "string" || text.length > 60000) return null;
  const lines = text.trim().split(/\r?\n/);
  // Exclude formatted examples and technical payloads rather than guessing their scope.
  if (lines.some((line) => /^\s*(?:```|~~~|>|\||\{|\[|\}|\])/.test(line)) || technical.test(text)) return null;
  const options = [];
  let start = -1, end = -1, style;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const match = line.match(/^ {0,3}(?:([-*+])\s+)?(?:\*\*)?([A-Ha-h]|[1-9])([.)])(?:\*\*)?\s+(.+?)\s*$/);
    const bullet = !match && line.match(/^ {0,3}([-*+])\s+(.+?)\s*$/);
    if (match || bullet) {
      if (end >= 0 && lines.slice(end + 1, i).some((s) => s.trim())) return null;
      const label = match ? match[2].toUpperCase() : String(options.length + 1);
      const currentStyle = match ? `${/\d/.test(label) ? "number" : "letter"}${match[3]}${match[1] || ""}` : `bullet${bullet[1]}`;
      const description = match ? match[4] : bullet[2];
      const expected = /\d/.test(label) ? String(options.length + 1) : String.fromCharCode(65 + options.length);
      if ((style && style !== currentStyle) || label !== expected || options.length === 8 || !/[\p{L}]/u.test(description) || description.length > 600) return null;
      if (start < 0) start = i;
      style = currentStyle;
      options.push({ label, text: description });
      end = i;
    } else if (options.length && /^ {2,3}\S/.test(line) && !/^\s*[-*+#\d]/.test(line)) {
      // Only indented, adjacent continuation lines belong to an option.
      if (i !== end + 1 || options.at(-1).text.length + line.length > 600) return null;
      options.at(-1).text += "\n" + line.trim();
      end = i;
    }
  }
  if (options.length < 2) return null;
  const before = lines.slice(0, start).join("\n");
  const after = lines.slice(end + 1).join("\n").trim();
  if (after && (after.length > 140 || after.split("\n").length > 2 || !decision.test(after))) return null;
  const context = before + "\n" + after;
  if (/\b(?:example|contoh)\b/i.test(context)) return null;
  if (!decision.test(context) && !(style.startsWith("letter") && !before.trim() && !after && options.every((option) => action.test(option.text)))) return null;
  return { options, storytelling: story.test(context) };
}

export function choicePrompt(group, selected) {
  if (!group || selected.length < 1 || selected.length > 2 || new Set(selected).size !== selected.length) throw Error("Select one or two choices.");
  const options = selected.map((label) => group.options.find((option) => option.label === label));
  if (options.some((option) => !option)) throw Error("Unknown choice.");
  const descriptions = options.map((option) => `opsi ${option.label}: ${option.text}`).join("; lalu ");
  return `Saya memilih ${descriptions}. ${group.storytelling ? "Lanjutkan cerita" : "Lanjutkan"} berdasarkan ${options.length === 2 ? "gabungan kedua pilihan ini secara masuk akal" : "pilihan ini"}.`;
}

export function eligibleChoices(message, latest) {
  return message === latest && message?.role === "assistant" && message.id && !message.incomplete
    ? parseChoices(message.content) : null;
}
