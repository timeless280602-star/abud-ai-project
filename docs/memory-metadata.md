# Smart Memory 2.0 — metadata tahap pertama

## Perubahan

Ketiga scope memory memperoleh dua kolom secara aditif saat `init_database()`:

| Kolom | Data lama | Data baru |
| --- | --- | --- |
| `source` | `unknown` | Jalur pembuatan record: `direct`, `tool`, `auto`, `dashboard`, atau `unknown` untuk pemanggil yang tidak menyebut sumber |
| `revision` | `0` (riwayat sebelum migrasi tidak diketahui) | `1` saat dibuat, bertambah satu untuk setiap operasi edit yang berhasil |

`source` adalah asal pembuatan **record**, bukan bukti kebenaran konten atau
identitas editor terakhir. Edit tidak mengganti sumber awal. Edit dengan teks
sama tetap dihitung sebagai satu revisi; duplicate save tidak menaikkan revisi.
Untuk record legacy, edit pertama menghasilkan revisi 1: ini tidak merekonstruksi
jumlah edit sebelum migrasi. Belum ada penyimpanan snapshot konten tiap revisi.

Sumber ditentukan server berdasarkan jalur pemanggil: command parser dan fallback
save eksplisit memakai `direct`; function tool dan legacy action fallback memakai
`tool`; extractor memakai `auto`; endpoint pembuatan dashboard memakai `dashboard`.
Argumen tool tidak menerima `source`/`revision`. Field tambahan dari browser atau
hasil ekstraksi model tidak menentukan metadata yang disimpan.

Migrasi memakai pemeriksaan kolom dan `ALTER TABLE ADD COLUMN`, bukan menyalin,
menghapus, atau mereset tabel. ID, owner, category, content, timestamp, foreign key,
dan urutan autoincrement dipertahankan. Startup berulang tidak mengubah metadata
existing. Database lama perlu menjalankan startup versi ini sebelum memakai query
versi baru. Schema tambahan juga membolehkan kode lama membaca kolom lamanya;
write dari kode lama akan mendapat default `unknown`/0 dan tidak melacak revisi.

Getter/list/search database mengembalikan kedua field tambahan. Dashboard
menampilkan label sumber dan revisi yang diketahui. Response tool search dan
validasi izin personal, guild, global tetap seperti sebelumnya. Tidak ada endpoint
baru untuk membaca atau mengubah metadata dengan melewati otorisasi.

## Validasi

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
cd frontend
npm run build
```

- 19 test lulus pada Python 3.11.18 dan 3.12, termasuk 13 regression tahap search.
- Database pre-metadata buatan dengan ID, konten, pemilik, timestamp dan category
  diverifikasi setelah dua kali startup. Foreign key dan autoincrement tetap valid.
- Ketiga scope diuji untuk sumber awal, duplicate save, edit dan revisi.
- Validasi sumber, constraint database, isolasi owner, jalur direct/tool/auto,
  pembuatan dashboard, serta penolakan/pengabaian metadata palsu diuji otomatis.
- Build frontend lulus. `git diff --check` lulus.
- Playwright headless lokal memverifikasi label `Direct request` dan `REVISION 1`,
  lalu mengulang sembilan kelompok pemeriksaan UI: ranking/cap hasil, kontrol
  read-only, penolakan request lintas scope, pergantian server, empty state,
  menu/layout mobile 390px, global/category untuk creator, tanpa exception JS,
  dan akses tanpa sesi ditolak. Menggunakan SQLite terpisah, sesi uji lokal nyata,
  serta mock membership Discord; request browser eksternal diblokir.
- Peringatan deprecation dependency/startup yang sudah ada tetap muncul.

Pengujian tidak mengakses VPS, menjalankan bot, memakai OAuth sungguhan, atau
menjalankan image Docker production. Tidak ada deployment maupun perubahan main.

Confidence, tipe fakta, waktu konfirmasi, expiry, deduplikasi semantik dan
pengarsipan belum ditambahkan. Tahap berikutnya memerlukan kebijakan eksplisit
untuk menghindari penandaan kepastian atau penghapusan berdasarkan dugaan.
