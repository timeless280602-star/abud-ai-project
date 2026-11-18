export function imageQuotaMessage(event, timeZone = "Asia/Jakarta") {
  let formatter;
  try {
    formatter = new Intl.DateTimeFormat("id-ID", { dateStyle: "long", timeStyle: "long", timeZone });
  } catch {
    formatter = new Intl.DateTimeFormat("id-ID", { dateStyle: "long", timeStyle: "long", timeZone: "Asia/Jakarta" });
  }
  const next = event.reset_at ? `Slot berikutnya tersedia pada ${formatter.format(new Date(event.reset_at))}.`
    : "Waktu tersedia berikutnya menunggu konfirmasi permintaan yang sedang diproses. Hubungi administrator.";
  return `Batas Image Generation Tercapai. Batas 10 gambar dalam jendela 24 jam bergulir telah tercapai${event.pending ? " (termasuk permintaan yang sedang diproses)" : ""}. ${next} Chat biasa tetap bisa digunakan.`;
}
