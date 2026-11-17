# Voice chat Abud

Voice chat menambahkan alur rekam, edit transkrip, kirim, lalu dengarkan. Browser
mengirim rekaman ke API Abud. Worker Whisper mengubah rekaman menjadi teks.
Setelah pengguna menekan **Kirim ke Ollama**, Abud memakai riwayat percakapan
dan mengalirkan jawaban dari Ollama. Jawaban disimpan, lalu Piper membuat WAV
untuk dibacakan. Jika browser memblokir putar otomatis, gunakan **Read aloud**.

Mikrofon membutuhkan HTTPS atau localhost. Rekaman dibatasi sekitar 30 detik
dan 3 MB. Rekaman dan WAV diproses untuk tiap permintaan tanpa disimpan sebagai
file. Teks transkrip yang dikirim dan jawaban masuk ke riwayat chat. Jika pengguna
mengirim pesan teks biasa di percakapan yang sama, riwayatnya dapat masuk ke
provider teks reguler sebagai konteks. Kiriman suara dan regenerasinya memakai
Ollama. Perintah riset dan gambar tetap tersedia melalui alur chat teks.

## Menjalankan di host Docker

Siapkan file `id_ID-news_tts-medium.onnx` dan `id_ID-news_tts-medium.onnx.json`
dari [Piper Voices](https://huggingface.co/rhasspy/piper-voices/tree/main/id/id_ID/news_tts/medium)
di direktori `voice-models/`. Direktori harus dapat dilalui dan kedua file harus
dapat dibaca oleh UID 10001, pengguna worker di container. Gunakan `ABUD_PIPER_VOICES_DIR` dan
`ABUD_PIPER_MODEL` untuk memilih direktori atau model lain. Periksa ketentuan
model suara yang dipilih sebelum dipakai dalam deployment.

Dari checkout dengan konfigurasi Compose Abud yang sudah berfungsi:

```sh
docker compose -f compose.yaml -f compose.voice.yaml up -d --build abud-voice ollama
docker compose -f compose.yaml -f compose.voice.yaml exec ollama ollama pull qwen2.5:1.5b
docker compose -f compose.yaml -f compose.voice.yaml up -d --no-deps --build abud-api
```

Compose membangun image Ollama khusus CPU untuk host Linux x86-64, memakai
binary resmi versi 0.40.16 dengan pemeriksaan SHA-256. Image akhir berisi
runtime CPU dan lisensi yang disertakan paket. Build pertama mengunduh arsip
rilis sekitar 1,55 GB, mengekstrak komponen CPU, lalu menghapus arsip pada langkah
yang sama. Model Ollama diunduh terpisah ke volume.

Unduhan pertama mengisi volume cache Whisper dan Ollama. Model default adalah
Whisper `base`, Ollama `qwen2.5:1.5b`, dan suara Piper bahasa Indonesia. Gunakan
`ABUD_WHISPER_MODEL` atau `ABUD_VOICE_OLLAMA_MODEL` untuk mengganti model.
Jika memilih model Ollama lain, gunakan nama itu juga pada perintah `ollama pull`.

Setelah worker selesai memuat model, buka percakapan dari browser dan uji tombol
**Rekam suara** dengan satu kalimat pendek. Pastikan transkrip dapat diedit,
jawaban muncul di riwayat setelah halaman dimuat ulang, dan **Read aloud**
dapat memainkan suara Piper.

Jalankan Compose dengan overlay yang sama untuk pembaruan API jika voice chat
perlu tetap aktif. Deployment yang hanya menggunakan `compose.yaml` memakai
konfigurasi chat biasa. Untuk staging atau layanan model yang sudah tersedia,
tetapkan `ABUD_VOICE_WORKER_URL`, `ABUD_VOICE_OLLAMA_URL`, dan
`ABUD_VOICE_OLLAMA_MODEL` pada API. Gunakan alamat jaringan privat yang dapat
dijangkau dari container API.

## Staging terisolasi

Gunakan checkout terpisah dan ikuti [konfigurasi staging](../staging/README.md)
untuk `.env.staging`, HTTPS, dan akses penguji. Siapkan dua file model suara
Piper seperti di atas. Jalankan perintah ini dari checkout staging.

```sh
docker compose -f compose.staging.yaml -f compose.staging.voice.yaml config --quiet
docker compose -f compose.staging.yaml -f compose.staging.voice.yaml up -d --build abud-voice ollama
docker compose -f compose.staging.yaml -f compose.staging.voice.yaml exec ollama ollama pull qwen2.5:1.5b
docker compose -f compose.staging.yaml -f compose.staging.voice.yaml up -d --build api
curl --fail http://127.0.0.1:18000/health
```

Overlay staging memakai volume dan jaringan milik proyek staging. API
mendengarkan pada port loopback 18000. Whisper, Piper, dan Ollama tetap
dijangkau melalui jaringan Compose. Workflow **Abud Voice Staging Smoke**
menjalankan stack yang sama dengan database sementara, akun fixture, audio
sintetis, dan model asli. Uji OAuth, proxy HTTPS serta mikrofon pengguna
dilakukan saat staging telah tersedia pada server tujuan.

## Rilis produksi dari PR #18

Setelah menyiapkan kedua file Piper di `/opt/abud/voice-models/`, gunakan SHA
rilis yang sudah lulus CI dengan skrip `scripts/deploy-web-release.sh SHA --voice`.
Skrip lama bisa dijalankan tanpa argumen kedua untuk rilis web tanpa konfigurasi
voice. Untuk mempertahankan voice ketika memperbarui API, gunakan `--voice`
pada setiap rilis. Opsi ini mengunduh model Ollama yang dikonfigurasi, menunggu
worker siap, membuat salinan database SQLite, lalu mengganti container API.
