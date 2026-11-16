# Smart Memory 2.0 — arsip manual yang dapat dipulihkan

## Perilaku

Ketiga tabel memory mendapat kolom nullable `archived_at` melalui migrasi aditif
pada startup. Default NULL menjaga semua record lama tetap aktif. Migrasi tidak
menghapus, menyalin ulang, atau mereset data; startup berulang mempertahankan
status arsip existing.

Memory Matrix memiliki pilihan **Show archived memories**. Tampilan default
hanya menampilkan record aktif; pilihan tersebut menampilkan hanya arsip dengan
pencarian/ranking dan batas 100 hasil yang sama. Pengguna dengan izin view dapat
membaca arsip milik scope yang diizinkan. Hanya pemegang izin manage pada scope
itu yang mendapat tombol Archive atau Restore.

- Archive memerlukan konfirmasi, lalu mengisi `archived_at` dengan waktu UTC.
- Restore mengembalikan `archived_at` ke NULL. ID, pemilik, content, category,
  source, revision, created_at dan updated_at dipertahankan pada kedua operasi.
- Editor, kandidat duplikat, dan tombol edit/delete tidak ditampilkan di tampilan
  arsip. Handler update/delete existing juga menolak record yang masih diarsipkan,
  termasuk request dari editor/tab lama. Penghapusan eksplisit record aktif tetap
  tersedia dengan perilaku lama.
- Tidak ada expiry, arsip berdasarkan umur, pemulihan otomatis, atau penghapusan
  arsip otomatis. Arsip tetap disimpan sampai keputusan eksplisit berikutnya.
- Operasi penghapusan seluruh data pengguna existing tetap menghapus data pengguna
  tersebut, termasuk arsip melalui foreign key cascade; arsip bukan backup di luar
  kontrol penghapusan data pengguna.

## Pencarian, konteks AI, dan penyimpanan ulang

Getter personal/guild/global, tool list/search, command listing, serta kandidat
duplikat (termasuk pool AI tanpa overlap kata) hanya membaca record aktif.
Blok persistent memory untuk chat juga memakai getter ini, sehingga arsip tidak
disuntikkan sebagai referensi memori aktif. Ini tidak menghapus pesan percakapan
lama atau membuat model melupakan fakta yang sudah terdapat dalam pesan tersebut.
Statistik database existing tetap menghitung seluruh record tersimpan termasuk arsip.

Save dengan teks identik (serta category sama untuk global) memeriksa status
record existing. Jika hanya ada kecocokan di arsip, save ditolak dengan pesan
pemulihan; dashboard menerima HTTP 409. Auto-save tidak melaporkan event tersimpan
dan tidak mengaktifkan atau menduplikasi record tersebut. Jika database legacy
memiliki salinan identik aktif dan arsip sekaligus, kecocokan aktif diprioritaskan.
Arsip berlaku per record, bukan larangan semantik terhadap fakta: parafrasa baru
masih dapat disimpan melalui jalur existing, dan salinan aktif lain tetap aktif.

Restore ditolak dengan HTTP 409 jika ada record aktif identik pada owner/scope
(dan category global) yang sama. Pemeriksaan dan transisi memakai transaksi
SQLite BEGIN IMMEDIATE, sebagaimana operasi save, untuk menserialkan keputusan
terhadap writer lain. Dua restore serentak terhadap salinan identik hanya dapat
mengaktifkan salah satunya. Ini bukan unique constraint baru terhadap seluruh
jalur edit atau pembersihan duplikat legacy.

## API dan izin

- `GET /dashboard/memory?archived=true` membaca arsip; default `false` membaca aktif.
- `POST /dashboard/memory/archive` menerima scope, guild_id opsional, memory_id
  positif, dan archived boolean strict (`true` untuk archive, `false` untuk restore).
- Pemeriksaan origin dan sesi tetap berlaku. Personal memakai linked Discord ID
  pengguna dan `memory.personal.manage`; guild memakai `memory.guild.manage`
  untuk server yang sama ditambah verifikasi membership live; global hanya linked
  Discord ID pencipta. UI/status creator saja tidak memberi akses global.
- Guard scope yang sebelumnya dipakai list/review juga melayani mode write pada
  archive/restore. Permission view tidak naik menjadi manage.
- Query database membatasi owner/guild dan status asal yang diharapkan. Record
  yang tidak ada, bukan milik scope itu, atau sudah berganti status menghasilkan
  HTTP 404 tanpa mutasi. Transisi berulang tidak mengganti timestamp arsip.
- Transisi sukses dicatat sebagai `memory.archive` atau `memory.restore` di audit
  dashboard dengan actor, scope, guild dan ID record; konten tidak dimasukkan log.

Tidak ada dependency baru, perubahan bot, atau deployment. Startup API versi ini
harus berjalan sebelum memakai schema baru. Kode aplikasi lama masih dapat membaca
kolom lamanya, tetapi tidak memahami arsip; menjalankan/rollback ke API lama dapat
menampilkan arsip sebagai aktif. Karena itu semua jalur API harus memakai versi
ini saat fitur arsip digunakan. Tidak ada instance lama/baru yang dijalankan untuk
pengujian terhadap data VPS.

## Validasi

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
cd frontend
npm run build
```

37 test lulus pada Python 3.11.18 dan 3.12, termasuk 28 regression sebelumnya.
Test baru mencakup ketiga scope, metadata utuh setelah archive/restore, arsip
bertahan setelah startup berulang, owner dan izin view/manage, origin/sesi,
verifikasi guild gagal tertutup, akses global, audit, duplicate save/auto-save,
edit/delete dari tab lama, dua restore bersamaan, serta blok memori chat yang
tidak mengandung arsip. Test migrasi pre-metadata existing diperbarui untuk
memastikan archived_at NULL tanpa mengubah kolom/data lama.

Build frontend dan `git diff --check` lulus. Playwright headless lokal memverifikasi
10 kelompok alur: profil baca tanpa kontrol mutasi, pembatalan konfirmasi,
archive/metadata/tombol Restore, duplicate save 409, pencarian arsip, pemulihan
personal, isolasi server guild, pemulihan global/category, mobile 390px tanpa
overflow, dan tanpa exception JavaScript. Fixture memakai database/sesi terpisah,
grant manage guild eksplisit, mock membership Discord dan blok request browser
ke layanan eksternal. AI sungguhan, OAuth, image Docker, dan VPS tidak diuji.
Peringatan deprecation dependency/startup existing tetap muncul.

Production dan main tidak diubah. PR ditujukan ke dev untuk review, tanpa merge
atau deployment pada tahap ini.
