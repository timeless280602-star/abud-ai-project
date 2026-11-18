# Smart Memory 2.0 — tinjauan kandidat duplikat

PR metadata #2 direview, 19 test diulang pada Python 3.11.18, lalu di-merge ke
`dev` (`2360e09`). Tahap ini menambahkan tinjauan draf, bukan pembersihan otomatis
seluruh database atau penghapusan record yang dianggap duplikat.

## Alur pengguna

Di editor Memory Matrix:

1. **Check similar wording** membandingkan draf dengan record pada scope yang
   diizinkan. Maksimal lima kandidat ditampilkan beserta alasan kemiripannya.
2. **Review meaning with AI** bersifat opsional. Draf dan maksimal lima kandidat
   dikirim ke router/model AI yang sudah dikonfigurasi, hanya saat tombol dipilih.
   AI memberi anotasi `duplicate`, `related`, `conflict`, atau `distinct` dan alasan.
   Ini saran, bukan kepastian atau izin menulis.
3. Pengguna memilih **Keep as separate draft**, **Update this record**, atau
   **Combine into draft**. Ketiganya hanya mengubah editor. Save tetap diperlukan
   untuk membuat/memperbarui record lewat endpoint existing beserta izin manage.
4. Combine menyusun konten lama dan draf dengan newline untuk diedit pengguna;
   tidak memakai teks gabungan buatan model dan tidak menghapus record lain.
   Draf di atas 1000 karakter diblokir untuk disimpan sampai pengguna memendekkannya,
   tanpa pemotongan otomatis. Exact duplicate save tetap memakai deduplikasi lama.

Update terhadap record mempertahankan sumber pembuatannya dan menaikkan revisi
sesuai tahap metadata. Jika draf berasal dari edit record lain, record asal tidak
dihapus ketika pengguna memilih kandidat berbeda. Pembersihan pasangan record
existing tetap keputusan manual terpisah; tidak ada bulk merge atau delete.
Hasil tinjauan dengan scope/server/kategori/draf/ID edit yang sudah berubah tidak
ditampilkan. UI review hanya tersedia pada editor yang memiliki izin manage;
endpoint tinjauan sendiri adalah operasi baca dan membutuhkan izin view.

## Kandidat lokal dan batas cakupan semantik

- Normalisasi NFKC/casefold, overlap kata Jaccard, dan Dice trigram karakter.
  Ambang kandidat lokal 0.55; skor bukan probabilitas fakta yang sama.
- Pencarian menilai seluruh scope sebelum LIMIT, sehingga kandidat dengan wording
  relevan di luar 100 record terbaru tetap dapat ditemukan. Tidak ada scan pasangan
  seluruh database secara kuadratik. Biaya tetap linear terhadap jumlah record scope.
- Perbedaan keberadaan negasi atau angka ditandai sebagai kemungkinan konflik;
  heuristic ini tidak dapat memahami semua bentuk negasi, nama, tanggal, atau makna.
- Mode AI memprioritaskan kandidat wording dan mengisi slot kosong dengan record
  terbaru dari scope yang sama. Ini memungkinkan parafrasa tanpa overlap kata
  ditinjau pada kumpulan kecil, tetapi **tidak menjamin semua parafrasa lama ditemukan**
  jika lima kandidat lain lebih dahulu terpilih. Belum ada indeks embedding.
- Untuk record legacy yang lebih dari 1000 karakter, penilaian lokal/prompt AI
  hanya menggunakan 1000 karakter awal; konten record asli tidak diubah.
- Ketika AI tidak dikonfigurasi, timeout, HTTP gagal, atau respons tidak valid,
  kandidat wording tetap tersedia dan UI menyatakan tinjauan AI tidak tersedia.
  Kandidat tanpa overlap yang hanya ditambahkan untuk AI tidak ditampilkan saat fallback.

## Batas keamanan dan kompatibilitas

`POST /dashboard/memory/similar` menerima scope, guild_id, content, category,
exclude_memory_id dan use_ai. Konten berada di body, bukan URL. Pemeriksaan origin,
sesi dan izin dijalankan sebelum pembacaan kandidat atau pemanggilan AI.
Route list dan review memakai fungsi izin baca yang sama: personal berdasarkan
linked Discord pengguna; guild berdasarkan grant guild dan verifikasi membership;
global hanya linked Discord pencipta. Global juga dibatasi category yang sama.
Pemilihan tabel menggunakan whitelist dan ID/kategori diikat sebagai parameter SQL.

Tidak ada data dari scope/owner lain yang menjadi kandidat atau masuk prompt.
Prompt memperlakukan isi memori sebagai data tidak tepercaya, tanpa tools. Respons
AI harus berupa satu anotasi per ID kandidat yang diizinkan, ID integer unik,
relation yang dikenal, dan reason teks maksimal 500 karakter. Respons tidak boleh
mengganti isi/source/revisi record atau memperkenalkan ID baru. Alasan dirender
sebagai teks React, bukan HTML atau perintah.

Tidak ada migrasi/schema baru, dependency baru, atau perubahan auto-save/tool AI
bot. Router menggunakan NINE_ROUTER_BASE_URL, NINE_ROUTER_MODEL dan
NINE_ROUTER_API_KEY existing; timeout 20 detik, maksimal 1500 token keluaran.
Tinjauan tidak mengubah tabel memori. Pembaruan sesi autentikasi existing tetap
berjalan. Tidak ada aktivitas Discord, deploy, atau perubahan `main`/VPS.

## Validasi

```sh
ABUD_DATABASE_PATH="$(mktemp -d)/abud.db" python -m unittest discover -s tests -v
cd frontend
npm run build
```

- 28 test lulus pada Python 3.11.18 dan 3.12, termasuk 19 regression sebelumnya.
  Tambahan mencakup Unicode, reorder/typo, negasi/angka, isolasi scope/category,
  pengecualian record sendiri, kandidat lama, batas hasil/input, tidak ada mutasi,
  origin/permission, dan larangan pemanggilan AI sebelum akses diberikan.
- Kontrak AI diuji dengan mock: anotasi valid tidak mengganti konten, ID halusinasi
  dan output rusak ditolak, timeout/key kosong mempertahankan fallback. Akurasi
  model/router sungguhan belum diukur; pengujian tidak mengirim memory ke layanan AI.
- Build frontend dan `git diff --check` lulus.
- Playwright headless pada server lokal dengan SQLite terpisah dan sesi autentikasi
  uji nyata memverifikasi 10 kelompok alur: read-only tanpa editor review, kandidat
  tanpa mutasi, staging update lalu Save, keep separate lalu Save, combine lalu Save
  tanpa delete, fallback AI, respons stale tersembunyi, mobile 390px, pergantian scope,
  dan tanpa exception JavaScript. Membership Discord dimock dan request browser
  eksternal diblokir. Pemeriksaan tambahan memastikan draf gabungan >1000 karakter
  tidak dapat disimpan dan tidak memotong/mengubah konten existing.

Arsip, pemulihan dan retensi tetap tahap berikutnya. Tidak ada penghapusan otomatis.
