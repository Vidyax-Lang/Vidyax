# Vidyax — Roadmap / Catatan Fitur

**Status: v1.2** — stdlib lengkap (file, math, string) SUDAH masuk.

Catatan fitur yang mau dikerjain nanti. Bukan urutan wajib, tinggal ambil pas siap.

## Prioritas berikutnya

1. **`ai.ask` live**
   - Uji pakai GROQ_API_KEY beneran, bikin contoh program AI di `contoh/`.

## Ide lain (belum diprioritaskan)

- Ikon file .vx khusus di VS Code.
- Publish extension ke VS Code Marketplace (butuh Node.js + vsce).
- Optimizer lanjutan: inlining, escape analysis untuk alokasi, IR/SSA formal.
- Native backend (sekarang baru VM bytecode).
- Concurrency, package manager, LSP, debugger (target jangka panjang).

## Selesai

### v1.2

- ~~REPL: blok multi-baris yang lebih mulus~~ ->
  - Blok (`if:`/`func:`/`try:`) otomatis lanjut di prompt `... `, dieksekusi saat baris kosong.
  - Baris kosong TIDAK mengeksekusi blok yang belum lengkap (`try:` nunggu `catch:`-nya).
  - Ctrl-C batalin blok setengah jadi / hentikan program yang lagi jalan, tanpa keluar REPL.
  - Ctrl-C saat mengetik tidak lagi bikin REPL crash dengan traceback Python.
  - 5 test REPL baru (subprocess, via stdin) di tests.py.
- ~~Stdlib lebih lengkap~~ -> 13 builtin baru (total 28), di KEDUA engine Python + VM C:
  - File: `readfile(path)`, `writefile(path, x)` — di VM digate `--allow-fs` (deny by default).
  - Math: `floor`, `ceil`, `round(x[, digits])` (half away from zero), `sqrt`, `pow`, `random([a, b])`.
  - String: `replace`, `trim`, `contains` (juga untuk list), `startswith`, `endswith`.
- Test: 89/89 differential (walk + fast + REPL), 75/75 VM (termasuk test sandbox fs-deny).

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
