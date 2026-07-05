# Vidyax — Roadmap / Catatan Fitur

**Status: v1.1** — error handling lengkap (try/catch, source map, pesan ramah, kategori error) SUDAH masuk.

Catatan fitur yang mau dikerjain nanti. Bukan urutan wajib, tinggal ambil pas siap.

## Prioritas berikutnya

1. **Stdlib lebih lengkap** (paling kepake user)
   - Operasi file: baca/tulis file teks.
   - Math lebih kaya: floor, ceil, round, sqrt, pow, random.
   - String lebih kaya: replace, trim, contains, startswith/endswith.

2. **REPL: blok multi-baris yang lebih mulus**
   - Sekarang aman pakai blok satu baris.
   - Target: ketik `if x:` lalu enter, REPL nunggu isi blok sampai baris kosong.

3. **`ai.ask` live**
   - Uji pakai GROQ_API_KEY beneran, bikin contoh program AI di `contoh/`.

## Ide lain (belum diprioritaskan)

- Ikon file .vx khusus di VS Code.
- Publish extension ke VS Code Marketplace (butuh Node.js + vsce).
- Optimizer lanjutan: inlining, escape analysis untuk alokasi, IR/SSA formal.
- Native backend (sekarang baru VM bytecode).
- Concurrency, package manager, LSP, debugger (target jangka panjang).

## Selesai

### v1.1

- ~~Runtime error nunjuk ke baris .vx asli~~ -> source map baris Python -> baris .vx saat transpile.
- ~~Pesan error lebih ramah pemula~~ -> pesan sintaks membantu, bukan cuma "expected NEWLINE, got NAME".
- ~~Kategori error yang jelas~~ -> dibedakan: sintaks, nama, tipe, runtime.
- VM bytecode (vxc.py + vm/vxvm.c): compiler AST -> bytecode + VM di C.
- Optimizer: constant folding, dead-code elimination, peephole.
- GC mark-sweep di VM (safepoint, --gc-stress, --gc-stats).
- Modul `ai` + member access di VM (libcurl), `get()`/`ai.ask` digate `--allow-net`.
- Test suite VM: 47/47 lulus (tests_vm.py).
- Push ke GitHub: repo `Vidyax` sudah live (github.com/daffa2555/Vidyax).

### v1.0

- ~~try/catch di dalam bahasa Vidyax~~ -> `try:` ... `catch e:` (e = teks error), juga `catch:` tanpa variabel.
- Lexer -> parser -> tree-walker + transpiler ke Python (~32x lebih cepat).
- Perintah `vidyax` (+ alias `vdx`), ekstensi file `.vx`.
- REPL interaktif + blok satu baris.
- 15 fungsi bawaan: len, range, text, num, upper, lower, split, join, push, abs, sum, min, max, type, get.
- Fungsi + rekursi, semua loop (rpt, for, break, continue).
- 25/25 test lulus (tests.py).
- Extension VS Code: syntax highlighting + auto-indent.
