# Vidyax — Roadmap / Catatan Fitur

**Status: v1.2** — stdlib lengkap (file, math, string) SUDAH masuk.

Catatan fitur yang mau dikerjain nanti. Bukan urutan wajib, tinggal ambil pas siap.

## Prioritas berikutnya

1. **Concurrency Fase D** — `go`/`wait` sudah hidup di walker + fast + VVM
   (Fase A-C). Tersisa: native backend. Desain: `docs/CONCURRENCY.md`.

## Ide lain (belum diprioritaskan)

- SSA penuh di atas lapisan CFG (phi node, versi variabel) — baru berguna
  saat native backend dikerjakan.
- Native backend (sekarang baru VM bytecode).
- Concurrency, package manager, LSP, debugger (target jangka panjang).

## Selesai

### v1.3

- Concurrency Fase C: VVM ikut menjalankan `go`/`wait` — refactor `VmCtx`
  (state eksekusi per-task, alias makro via thread-local `vx_ctx` ala Lua),
  GIL `vx_gil` dilepas hanya di builtin I/O, GC me-root semua ctx, akuntansi
  byte atomik, opcode `OP_GO` + modul `vm/task.c`. Hijau di gc-stress, ASan,
  DAN ThreadSanitizer; 2 ai.ask live paralel di VM 1,6 dtk (CPU 0,04 dtk).
- Concurrency Fase B: `t: go f(x)` / `wait(t)` hidup di walker + fast —
  task paralel dengan model GIL (interleave hanya saat I/O; data race
  mustahil). Error task muncul ulang di wait (catchable); task gagal tanpa
  wait dilaporkan di akhir program. `contoh/paralel.vx`: 2 ai.ask live
  paralel 0,95 dtk total. VM/native menolak `go` dengan pesan Fase C yang
  jelas. 7 test go/wait baru (subset deterministik).
- Concurrency Fase A: dokumen desain (`docs/CONCURRENCY.md`) + builtin
  `sleep(secs)` & `now()` identik di KEEMPAT engine, guard arity ala VM.
- ~~Native backend~~ -> `vidyax native prog.vx -o prog` (vxnative.py): AOT
  .vx -> C -> binary standalone. Tiap proto jadi fungsi C (tanpa dispatch
  loop), di-link dengan runtime VM yang sama (value/gc/net/builtins) —
  nilai, GC, builtin identik by construction; try/catch via setjmp per try.
  fib(27) 2,6x lebih cepat dari VVM (~36x dari transpiler). Differential
  60/60 program fuzz + test permanen di tests.py.
- ~~Optimizer: lapisan IR/CFG~~ -> `_cfg` di vxc.py: bytecode didecode jadi
  basic block ber-edge eksplisit, lalu jump threading + eliminasi blok tak
  terjangkau (ekor `NULL/RET` mati, rantai JMP), + cabang `if` berkondisi
  konstan di-drop saat emit. Line table ikut diremap. Substrat untuk SSA /
  native backend.
- ~~Optimizer: escape analysis top-level~~ -> `<main>` kini slot-based seperti
  fungsi: nama top-level yang tidak dibaca fungsi manapun tinggal di stack
  slot (O(1)), bukan env global (linear scan). ~1,9x di loop panas dengan 60
  global; pesan "not defined" untuk slot main yang belum diisi tetap sama.
- ~~Optimizer: inlining~~ -> pass inlining di vxc.py (VM saja; engine Python
  tetap referensi — differential test + fuzzer membuktikan perilaku identik).
  Aturan konservatif: body `return <expr>` (param-only + builtin, tanpa
  and/or), arg pure, urutan evaluasi & pesan error terjaga; sinergi dengan
  constant folding (`sq(3)` -> `CONST 9`). ~18% lebih cepat di loop
  padat-panggilan. Bonus fuzzer: bug `-0` di fmt_double VM ketahuan & fix.
- ~~LSP~~ -> `vidyax lsp` (vxlsp.py, tanpa dependensi, JSON-RPC stdio):
  diagnostics live (share front-end `check_source`), completion (keyword +
  35 builtin ber-dokumentasi + nama di dokumen), hover builtin, document
  symbols. Bisa dipakai editor mana pun ber-klien LSP (Neovim, Helix, dst.);
  extension VS Code masih pakai jalur `vidyax check`-nya sendiri (migrasi
  ke klien LSP = ide lanjutan).
- ~~Profiler~~ -> `vidyax profile file.vx` / `vxvm --profile` (modul
  `vm/profile.c`): deterministik (hitung instruksi, bukan sampling) —
  total + instr/detik, panggilan & porsi instruksi per fungsi, top-10
  hot lines via line table v3. Bookkeeping-nya di luar akuntansi GC/--max-mem.
- ~~Debugger~~ -> `vidyax debug file.vx` / `vxvm --debug` (modul `vm/debug.c`):
  breakpoint per baris .vx (`b`/`d`), `c`/`s` (step into)/`n` (step over),
  `bt` backtrace, `locals` (tanpa nama internal `$`), `stack`. Ditenagai
  format .vxc v3: line table per proto (offset -> baris .vx), ikut diremap
  peephole; `vidyax disasm` kini menampilkan marker `; line N`.
- ~~Pecah vxvm.c jadi modular~~ -> `vm/` kini 6 modul + 1 header:
  `vx.h` (tipe + API bersama), `value.c` (konstruktor, env, format angka,
  semantik eq/cmp/add/index), `gc.c` (alokasi + mark-sweep), `net.c`
  (JSON + libcurl + modul ai), `builtins.c` (35 builtin), `loader.c`
  (loader .vxc + verifier), `vm.c` (state global, dispatch loop, main).
  Perilaku identik (110/110 + fuzz), `vm_error` kini beranotasi noreturn.
- Disassembler `vidyax disasm <file.vxc|file.vx>` — listing lengkap: pool
  konstanta, layout slot per proto, instruksi terdecode (nama & target jump
  ter-resolve). `vxc.disassemble()` = pembaca rujukan format .vxc, sekaligus
  dokumentasi bytecode yang hidup.
- Stabilitas: fuzzer differential (`fuzz.py`) — program acak diuji identik di
  ketiga engine (`python fuzz.py -n 1000`, `--gc-stress`, `--seed` untuk replay).
  6 kelas bug parity ditemukan & diperbaiki (semua di engine Python, VM-nya benar):
  - Perbandingan `< > <= >=` tipe campuran membocorkan TypeError mentah Python
    -> helper `_cmp` bersama, pesan sama dengan VM ("cannot compare X with Y").
  - Operator `- * %` dan minus unary membocorkan error mentah / semantik Python
    (`"ab" * 2` jalan di Python!) -> `_arith`/`_neg` ala VM ("cannot do
    arithmetic on X and Y", "cannot negate X"); `+` kini persis do_add
    ("cannot add X and Y", list + list didukung).
  - Builtin teks pakai `str()` Python (trim(false) -> "False") -> `_vstr` semua.
  - `floor/ceil/round/...` menolak bool padahal bool = angka di seluruh bahasa.
  - `abs/sum/min/max/range/push/split/join` bocor error mentah (mis. `min([])`).
  - Read-before-assign di top level: fast path bilang "assigned in this
    function", walker/VM bilang "not defined" -> seragam "not defined".
- 16 test regresi baru di-pin dari temuan fuzzer; fuzz bersih 2400+ program
  (termasuk 400 di bawah --gc-stress).
- Stdlib operasi list (7 builtin baru, total 35, di ketiga engine):
  `pop(lst[, i])`, `remove`, `insert` (clamp ala Python), `sort` (in-place,
  stabil, tolak tipe campuran dengan pesan sama persis Python/VM), `reverse`,
  `find` (list + teks, -1 kalau tidak ada), `slice` (aturan `x[a:b]` Python,
  indeks negatif + clamp).
- Test: 108/108 differential, 94/94 VM — hijau juga di `--gc-stress` dan ASan.

### v1.2

- ~~Ikon file .vx khusus di VS Code~~ -> ikon SVG terang/gelap di `vidyax-vscode`
  (contributes.languages[].icon, engine ^1.63), + `.vscodeignore`; terbundel di
  `vidyax-1.1.0.vsix`.
- ~~Publish extension ke VS Code Marketplace~~ -> v1.1.0 LIVE di Marketplace
  (publisher `nadev`).
- ~~`ai.ask` live~~ -> diuji dengan GROQ_API_KEY asli di KETIGA engine (walk, fast,
  VM `--allow-net`); contoh baru `contoh/chatbot.vx` (chat loop + simpan transkrip
  pakai stdlib file).
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
- Push ke GitHub: repo `Vidyax` sudah live (github.com/Vidyax-Lang/Vidyax).

### v1.0

- ~~try/catch di dalam bahasa Vidyax~~ -> `try:` ... `catch e:` (e = teks error), juga `catch:` tanpa variabel.
- Lexer -> parser -> tree-walker + transpiler ke Python (~32x lebih cepat).
- Perintah `vidyax` (+ alias `vdx`), ekstensi file `.vx`.
- REPL interaktif + blok satu baris.
- 15 fungsi bawaan: len, range, text, num, upper, lower, split, join, push, abs, sum, min, max, type, get.
- Fungsi + rekursi, semua loop (rpt, for, break, continue).
- 25/25 test lulus (tests.py).
- Extension VS Code: syntax highlighting + auto-indent.
