# Projects, judul otomatis, dan pengelolaan percakapan

## Dasar integrasi dan dependensi PR

Audit pada 16 November 2026 menemukan `dev` di `f8f2e10`, `main` di
`09d8365`, dan Web Chat di PR #3 yang masih terbuka. Implementasi Web Chat,
keyboard, timestamp, TTS, serta feedback terakhir ada di `6fa71fd` pada
`feature/web-ai-chat`, belum di-merge ke dev. Branch `feature/web-chat-projects`
dibuat dari commit tersebut. Kode yang sama tidak disalin ulang atau di-cherry-pick.

PR Projects menargetkan `dev` dan bergantung pada PR #3. Selama #3 belum
bergabung, diff terhadap dev juga memuat dependensi Web Chat. Urutan integrasi:
review/merge #3 dahulu, kemudian gabungkan dev terbaru ke branch Projects dan
periksa kembali diff serta regression sebelum merge. Jangan otomatis merge salah
satu PR. Main, database production, server production, dan bot Discord tidak diubah.

## Fitur

- Sidebar Projects; buat project, nama/deskripsi, instruksi AI, daftar percakapan,
  chat baru di dalam project, pengaturan, serta penghapusan dengan pilihan riwayat.
- Menu percakapan: Rename, Pin/Unpin, Archive/Unarchive, Move to project, Delete.
  Pin diprioritaskan. Arsip mempunyai tampilan tersendiri dan tetap mempertahankan
  pesan, pin, dan asosiasi project. Arsip harus dipulihkan sebelum melanjutkan chat.
- Penghapusan chat memakai dialog konfirmasi. Memory yang disimpan terpisah tidak
  ikut dihapus. Penghapusan project harus menyebut `keep` atau `delete` secara
  eksplisit; UI juga meminta checkbox konfirmasi.
- Judul pertama memakai fallback deterministik segera dan satu percobaan AI
  semantik di background. Potongan respons pertama tidak menunggu judul.
  Provider menggunakan konfigurasi 9router existing, maksimum 40 token dan pesan
  awal 1000 karakter, timeout total 5 detik (HTTP 4 detik/connect 2 detik).
  Gagal/timeout/restart mempertahankan fallback. Tidak ada retry berulang pada
  pesan berikutnya. Judul manual, termasuk judul yang diberikan saat membuat
  percakapan, tidak dapat ditimpa hasil AI yang terlambat.
- Chat lama tetap tersedia; judul lama diperlakukan sebagai manual. UI melakukan
  satu refresh tertunda setelah respons untuk mengambil judul background.
- Dialog native dengan fokus dan Escape, menu dengan panah/Home/End/Escape,
  serta layout desktop/mobile. Streaming, timestamp lokal, keyboard, copy,
  regenerasi, rating dan TTS existing dipertahankan.

## Mode memory dan batas isolasi

Mode dipilih saat pembuatan dan tidak dapat diubah lewat API settings.

| Mode | Retrieval dan penyimpanan |
| --- | --- |
| Default Memory | Personal web `web:<identity UUID>` dan global aktif read-only, sama dengan Web Chat existing. Instruksi project hanya berlaku di project tersebut. |
| Project-Only Memory | Namespace khusus `web-project:<identity UUID>:<project UUID>`, percakapan saat ini, instruksi project, serta explicit memory/feedback di namespace itu saja. Tidak membaca personal luar, project lain, guild Discord, atau global. |

Tidak ada pembacaan otomatis percakapan lain dalam project pada versi ini.
Instruksi project diberikan sebagai instruksi pengguna, di bawah kebijakan sistem;
instruksi tidak memberi tools, identitas, atau izin scope tambahan. Namespace
memory ditentukan backend dari project yang dimiliki pemilik percakapan, bukan
parameter browser. Ranked search dan active-only/archive behavior memakai helper
Smart Memory existing. Feedback juga dipisahkan dengan namespace tersebut.

## Kebijakan perpindahan dan penghapusan

- Chat biasa dan project Default berbagi batas memory web yang sama. Perpindahan
  di antaranya mempertahankan riwayat; riwayat itu menjadi konteks chat tersebut
  pada tujuan. Tidak ada memory yang disalin atau diganti pemiliknya.
- Chat kosong boleh dipindah ke/dari mode apa pun.
- Chat berisi pesan tidak boleh melintasi batas Project-Only: keluar ke chat biasa,
  Default, project-only lain, maupun masuk dari luar. API mengembalikan 409 dengan
  penjelasan untuk membuat chat baru di tujuan. Memindahkan ke project yang sama
  tetap diperbolehkan. Pembatasan ini juga berlaku untuk chat yang diarsipkan.
- Project Default dapat dihapus sambil mempertahankan chat sebagai chat biasa,
  termasuk pesan, status arsip dan pin. Personal memory tetap ada.
- Project-Only dengan riwayat tidak boleh dihapus dengan pilihan `keep`, karena
  akan melepas riwayat privat ke scope biasa. Pertahankan project lalu arsipkan
  chat jika ingin menyimpan riwayat. Pilihan `delete` menghapus chat project dan
  memory namespace project tersebut secara eksplisit. Tidak menyentuh memory
  personal/global atau project lain. Project-Only yang seluruh chatnya kosong
  boleh dihapus dengan pilihan keep.
- Delete chat saja tetap mempertahankan memory/feedback project, seperti explicit
  save Web Chat. Delete project Project-Only menghapus seluruh namespace miliknya.
- Move/archive/delete project ditolak selama ada respons terkait yang masih berjalan.

## API

Semua endpoint memerlukan sesi valid, profil lengkap, ownership; setiap mutasi
memerlukan exact Origin existing. Payload menolak field asing, termasuk owner,
permission, dan memory scope. SQL memakai parameter terikat. Maksimum 50 project
serta 200 percakapan total per identitas. Settings: nama 100 karakter, deskripsi
1000, instruksi 4000. Semua batas berada di backend.

| Endpoint | Fungsi |
| --- | --- |
| GET/POST `/web/chat/projects` | Daftar dengan jumlah chat aktif dalam satu query / buat project |
| GET/PATCH `/web/chat/projects/{id}` | Baca/edit nama, deskripsi, instruksi; mode immutable |
| DELETE `/web/chat/projects/{id}` | Body wajib `{"conversations":"keep"}` atau `"delete"` |
| GET `/web/chat/projects/{id}/conversations?archived=false` | Chat milik project |
| GET `/web/chat/conversations?project_id=...&archived=false` | Chat project; tanpa project_id membaca chat biasa |
| GET `/web/chat/conversations?archived=true` | Semua arsip milik pengguna; opsional filter project |
| POST `/web/chat/conversations` | Body opsional `project_id`; title eksplisit dianggap manual |
| PATCH `/web/chat/conversations/{id}/pin` | `{"enabled":true/false}` |
| PATCH `/web/chat/conversations/{id}/archive` | `{"enabled":true/false}` |
| PATCH `/web/chat/conversations/{id}/project` | `{"project_id":"UUID"}` atau null |

Endpoint pesan, feedback, rename, dan delete existing tetap digunakan. Judul AI
merupakan proses internal setelah admission pesan pertama; tidak ada endpoint
publik yang memungkinkan spam regenerasi judul. Query list memakai JOIN dan
indeks, bukan satu query tambahan per percakapan/project.

## Migrasi dan rollback

Startup menambahkan tabel `web_projects`, indeks owner, serta kolom conversation:
`project_id` nullable dengan FK, `pinned` default 0, `archived_at` nullable, dan
`title_state` default manual. Indeks baru mendukung filter grup/arsip/pin.
ID, isi pesan, tanggal, dan tabel Discord tidak ditulis ulang. Pemeriksaan kolom
serta ALTER diserialkan dengan transaksi SQLite; startup ulang/concurrent aman.

Migrasi aditif tidak berarti aplikasi lama memahami isolasi baru. **Jangan rollback
ke API lama yang mengabaikan project scope** setelah memakai Project-Only, karena
API tersebut dapat menyajikan riwayat project sebagai chat biasa dan memakai
memory scope yang salah. Jika rollback diperlukan, batasi akses terlebih dahulu,
simpan database terbaru, lalu gunakan versi yang memahami project atau pulihkan
backup pra-fitur secara terencana dengan menerima hilangnya data setelah backup.
Jangan menghapus tabel/kolom atau mengganti SQLite aktif secara manual.

## Verifikasi dan staging

Gunakan database disposable:

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
python tests/run_web_chat_e2e.py
python tests/run_web_chat_e2e.py web_projects_e2e.cjs
```

Harness HTTPS memakai FastAPI asli, session Secure asli, SQLite terpisah, frontend
production, dan Chromium. OAuth dan AI dimock. Browser memblokir request eksternal.
Test meliputi CRUD/ownership, mode immutable, pin/arsip, delete, move batas scope,
retrieval/writes/feedback project-only, instruksi, migrasi legacy/concurrent,
timeout/fallback/manual title race, potongan stream pertama tanpa menunggu title,
regression Smart Memory/Web Chat, menu keyboard dan viewport 320/390/768/1280.

Gunakan `compose.staging.yaml` standalone dengan env/volume/domain staging sendiri.
Jangan digabung dengan compose production. Buat backup staging sebelum upgrade,
jalankan hanya API, lalu cek login, judul AI dengan key staging, dua akun, dua
project-only dan satu Default, feedback/explicit memory, arsip/restore serta
perpindahan terlarang. Uji juga bahwa percakapan/chat Discord tetap normal.
Verifikasi OAuth, 9router dan SSE melalui proxy sungguhan tetap diperlukan.

Hasil aktual pengujian dicatat di deskripsi PR. Fitur ini disiapkan untuk review
dan staging, tidak otomatis di-deploy atau di-merge.

### Hasil pengujian implementasi

- 66 unittest lulus pada Python 3.12 dan Python 3.11 di image non-root dengan
  networking dimatikan. Termasuk 54 regression sebelumnya dan 12 tes Projects.
- Build frontend production dan image Docker lulus. Build Docker menggunakan
  Dockerfile sementara di luar repo dengan proxy CA sebagai BuildKit secret;
  verifikasi TLS tetap aktif dan tidak ada CA/secret dimasukkan ke source/layer.
- Harness HTTPS Web Chat existing lulus: keyboard, timestamp dua zona waktu,
  feedback, streaming/regeneration, isolasi, error recovery, dan mobile.
- Harness HTTPS Projects lulus: CRUD/settings, mode immutable, judul fallback,
  stream, menu keyboard, pin, arsip/restore, move terlarang/diizinkan, konfirmasi
  delete, pilihan riwayat, serta dialog 320/390/768/1280px. Screenshot desktop/
  mobile juga diperiksa; pengukuran lebar mencakup elemen konten, bukan hanya body.
- Browser mock-HTTP existing lulus setelah menyesuaikan rename/delete ke menu dan
  dialog baru. `npm audit` melaporkan 0 kerentanan; dependency tidak ditambah.
- `git diff --check` lulus. Tidak ada deployment, merge, startup bot, atau akses
  SQLite production dalam pengerjaan ini. Google/9router sungguhan masih menjadi
  acceptance check staging, termasuk kualitas judul semantik dari model asli.

### Lanjutan verifikasi staging lokal

Endpoint rename project sekarang mempertahankan deskripsi dan instruksi existing
jika field itu tidak dikirim. Nilai kosong yang dikirim eksplisit tetap menghapus
field yang dipilih. Regression test dan acceptance Compose memastikan perilaku ini.

Uji `python tests/check_projects_staging.py --image abud-web-chat-projects:local`
lulus terhadap image API asli dengan named volume baru dan sesi disposable,
termasuk restart API serta provider yang sengaja tidak tersedia. Database lulus
`integrity_check` dan `foreign_key_check`; memory tersimpan di namespace project
milik identitas yang benar. Seluruh stack uji dibersihkan setelah selesai.
66 unittest lulus ulang di Python 3.12 dan image Python 3.11 non-root/offline.
Lihat staging/README.md untuk mekanisme isolasi dan cara menjalankannya kembali.
