# Smart Memory 2.0 — audit dan tahap pertama

Audit statis terhadap repository pada baseline `dev` commit `09d8365`.
Cakupan: database, seluruh operasi memory pada API/tool/bot, autentikasi dan
permission dashboard, Skill Engine, React Memory Matrix, pengujian, dependency,
Dockerfile dan Compose. Tidak mengakses VPS, database production, layanan OAuth,
9Router, atau koneksi Discord. Ini bukan audit keamanan menyeluruh terhadap
seluruh fitur autentikasi dan infrastruktur yang berjalan.

## Temuan dan keputusan

| Area | Temuan awal | Tindakan tahap pertama |
| --- | --- | --- |
| `app/database.py` | Tiga tabel scope terpisah; deduplikasi `content = ?` (global juga category), timestamp creation/update, indeks owner dan ID. Belum ada query search. | Tambah pencarian pada tabel yang sama, tanpa migrasi, perubahan write path, atau reset data. |
| `app/tools.py` | Search substring casefold dari 100 record terbaru, berhenti setelah 5 hasil; memori lama terlewat dan hasil bergantung urutan ID. | Search seluruh scope terpilih sebelum SQL LIMIT, pertahankan response dan potongan content 500 karakter. |
| `app/main.py` | Dashboard memfilter substring content/category setelah LIMIT 100, bahkan memfilter dua kali; chat menyuntikkan memory terbaru sebagai konteks. | Dashboard memakai search yang sama dengan tool; chat context dan command listing tetap berperilaku seperti sebelumnya. |
| `app/bot.py` | Mengirim identitas/context dan flag admin melalui API internal; gateway memverifikasi membership. `client.run(TOKEN)` dieksekusi saat module diimport. | Tidak mengimport/menjalankan bot; tidak perlu perubahan bot untuk search. |
| `app/auth.py` | Dashboard memakai session, linked Discord ID, permission scope, dan live guild membership. Google-only tidak memperoleh akses personal/guild tanpa Discord. | Pertahankan pemeriksaan di route sebelum search. |
| `app/skills/` | Registry read-only, validasi path/symlink/ukuran, policy default deny, hanya skill testing boleh dibaca. Matcher keyword khusus metadata skill. | Tidak memakai tokenizer skill untuk memory: tokenizer itu ASCII dan membuang stopwords. Tidak membuka akses database/tool melalui skill. |
| `frontend/src/main.jsx` | Memory Matrix mengirim `scope`, `guild_id`, `q` ke backend dan mempertahankan urutan items; respons lama diabaikan setelah effect cleanup. | Tidak memerlukan perubahan UI untuk menampilkan ranking server. |
| `tests/` | Hanya 5 test calculator/tool/permission; belum ada search/database/dashboard regression. | Tambah test database SQLite sementara, tool, dan HTTP dashboard dengan layanan eksternal dimock. |
| Deployment | Compose mengikat `/opt/abud/data`, `/opt/abud/skills`, nama container dan port production. | Jangan gunakan Compose ini untuk development secara langsung. Tidak menjalankan Docker atau deployment. |
| Dependency/CI | Dependency Python sebagian tidak dipin, frontend tanpa lockfile; baseline tidak memiliki workflow CI. | Tidak menambah dependency; sediakan command test yang bisa dijalankan lokal. Lockfile/CI terpisah dari search. |

## Perilaku pencarian

- Normalisasi Unicode NFKC + casefold; token kata menggunakan regex Unicode `\w+`.
- Frasa adalah token query berurutan, mengabaikan variasi spasi dan tanda baca.
- Skor: bonus frasa 1000 + jumlah **kata unik** query yang cocok. Sebagian kata
  boleh cocok; frasa selalu mengungguli overlap karena query maksimal 200 karakter.
- Jika skor sama, ID terbesar lebih dahulu. Pengulangan kata tidak menambah skor.
- Batas helper integer dijepit ke 1–100; bool/non-integer ditolak. Tool selalu 5
  hasil, dashboard 100. Limit diterapkan setelah ranking, tanpa cutoff kandidat 100.
- Tool tetap membutuhkan 2–100 karakter. Dashboard menerima sampai 200 karakter;
  query kosong mengembalikan record terbaru. Query hanya tanda baca tanpa token
  mengembalikan kosong. `%` bukan wildcard dan teks query tidak menjadi SQL.
- Global dashboard tetap mencocokkan category. Category dan content dinilai
  terpisah, memakai skor tertinggi; tidak membentuk frasa lintas field.
- `total_found` dan `count` tetap jumlah hasil yang dikembalikan, bukan total
  kecocokan sebelum limit. Bentuk record dan timestamp tetap dipertahankan.
- Bukan semantic search: belum ada sinonim, stemming, typo tolerance, atau embedding.

## Batas izin yang dipertahankan

Tool search hanya personal pengguna aktif dan guild konteks aktif; global search
belum diekspos ke tool. Dashboard personal membutuhkan linked Discord dan grant;
guild membutuhkan grant untuk guild yang sama dan membership live; global hanya
linked Discord ID pencipta. Database helper adalah lapisan internal, bukan endpoint
autorisasi: caller wajib mengotorisasi ID sebelum memanggilnya. SQL personal/guild
selalu menyertakan owner ID. Tidak ada fallback ke scope lain.

## Validasi

Di virtualenv dengan dependency `requirements.txt`:

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
```

Variabel path wajib diarahkan ke area sementara, karena module database yang ada
membuat direktori parent saat diimport. Setiap test baru mengganti path dengan
database TemporaryDirectory sendiri dan membersihkannya. Dashboard memakai
konfigurasi OAuth dummy, TestClient tanpa lifespan, serta mock identitas/gateway;
tidak ada server, bot, atau koneksi OAuth/Discord/AI yang dijalankan.

Hasil lokal: 13 test lulus di Python 3.12 dan Python 3.11.18; termasuk 5 test baseline. Peringatan
deprecation Authlib/httpx dan FastAPI startup berasal dari dependency/pola yang
sudah ada. Image production memakai Python 3.11; kompatibilitas interpreter 3.11 sudah diuji
di virtualenv terpisah, tetapi image Docker belum dijalankan.
Build frontend `npm run build` lulus pada Node 24.22.1 (Vite 6.4.6).
`git diff --check` juga lulus. Tidak ada pengujian browser atau deployment.

Review lanjutan terhadap diff tidak menemukan perubahan yang melewati kontrol izin:
search tetap dipanggil setelah guard route, tabel dipilih dari whitelist scope,
owner ID diikat sebagai parameter SQL, serta LIMIT diterapkan setelah ranking.
Tidak ada perubahan kode tambahan yang diperlukan dari review ini.

## Tahap lanjutan

1. Ukur waktu search dan jumlah memory per scope. Implementasi saat ini memindai
   seluruh scope dengan SQLite UDF (dapat menghitung skor lagi untuk sorting),
   sehingga biaya naik seiring data. Tambahkan FTS hanya jika pengukuran memerlukan,
   dengan indeks/backfill aditif, pengujian Unicode, serta filter scope yang sama.
2. Tambahkan metadata secara aditif: sumber, tipe fakta, confidence, waktu terakhir
   dikonfirmasi, dan expiry opsional. Tetapkan kebijakan data lama sebelum migrasi;
   jangan menebak confidence untuk record existing.
3. Deduplikasi semantik harus mencari kandidat **di scope/owner yang sama**, lalu
   menawarkan merge/update yang dapat ditinjau. Jangan menghapus fakta berbeda
   berdasarkan kemiripan saja; pertahankan provenance dan riwayat perubahan.
4. Lifecycle jangka panjang: review ingatan usang/kontradiktif, arsip yang dapat
   dipulihkan, dan retensi eksplisit. Jangan menerapkan penghapusan otomatis pada
   database existing tanpa kebijakan serta persetujuan terpisah.

Perubahan tahap pertama ditujukan untuk PR ke `dev`, bukan merge ke `main`.
Tidak ada deployment atau modifikasi `/opt/abud` maupun `/opt/abud-dev`.
