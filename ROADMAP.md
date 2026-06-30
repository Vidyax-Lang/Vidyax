# Vidyax — Roadmap / Catatan Fitur

**Status: v1.0** — error handling try/catch SUDAH masuk.

Catatan fitur yang mau dikerjain nanti. Bukan urutan wajib, tinggal ambil pas siap.

## Error handling (prioritas berikutnya)

1. **Runtime error nunjuk ke baris .vx asli** (paling kepake)
   - Sekarang: error pas jalan (mode cepat/transpile) nunjuk ke file .py hasil compile, bukan baris .vx.
   - Solusi: bikin "source map" — simpan pemetaan baris Python -> baris Vidyax saat transpile,
     lalu terjemahkan balik kalau ada error.

2. **Pesan error lebih ramah pemula**
   - Sekarang masih teknis: "expected NEWLINE, got NAME".
   - Target: lebih membantu, mis. "Sepertinya ada dua perintah di satu baris — coba pisah jadi dua baris."

3. **Kategori error yang jelas**
   - Bedain: error sintaks (salah nulis), error nama (variabel belum ada),
     error tipe (mis. nambah teks dengan daftar), error runtime.
   - Biar user tau ini masalah jenis apa.

4. ~~try/catch di dalam bahasa Vidyax~~ -> SUDAH ADA di v1.0
   - Implementasi: `try:` ... `catch e:` ... (e = teks error). Juga `catch:` tanpa variabel.
   - Built-in `get(url)` untuk HTTP GET juga sudah ada (dengan error handling).

## Ide lain (belum diprioritaskan)

- REPL: blok multi-baris yang lebih mulus (sekarang aman pakai blok satu baris).
- `ai.ask` live: uji pakai GROQ_API_KEY beneran, bikin contoh program AI.
- Stdlib lebih lengkap: operasi file, math, string lebih kaya.
- Source-map (lihat error handling #1) sekaligus buat debugging.
- Ikon file .vx khusus di VS Code.
- Publish extension ke VS Code Marketplace (butuh Node.js + vsce).
- Push ke GitHub: repo `vidyax` dan `vidyax-vscode` (README, LICENSE, .gitignore sudah siap).

## Status sekarang (v1.0)

- Lexer -> parser -> tree-walker + transpiler ke Python (~32x lebih cepat).
- Perintah `vidyax` (+ alias `vdx`), ekstensi file `.vx`.
- REPL interaktif + blok satu baris.
- 15 fungsi bawaan: len, range, text, num, upper, lower, split, join, push, abs, sum, min, max, type, get.
- Fungsi + rekursi, semua loop (rpt, for, break, continue).
- 25/25 test lulus.
- Extension VS Code: syntax highlighting + auto-indent.
