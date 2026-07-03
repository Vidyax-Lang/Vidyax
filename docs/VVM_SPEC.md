# Vidyax Virtual Machine (VVM) — Spesifikasi Arsitektur v1.1

Revisi dari blueprint v1, disesuaikan dengan implementasi nyata di
`vm/vxvm.c` (C) + `vxc.py` (compiler VIR). Bagian yang berubah dari
blueprint v1 ditandai **[revisi]** beserta alasannya. Status: dokumen
hidup — implementasi dan spec harus selalu sinkron.

---

## 1. Posisi VVM di toolchain

```
file.vx ──(vidyax.py: lexer→parser→type_check)──► AST
AST ──(vxc.py)──► VIR (.vxc)  ──(vm/vxvm: verify→execute)──► hasil
```

- Front-end (lexer, parser, analisis scope) **dipakai bersama** dengan
  dua engine Python — VVM mewarisi semantik yang persis sama.
- **[revisi]** Blueprint v1 menyebut "AI Orchestrator" dan kompilasi
  "C/x86" sebagai penentu kapan VVM dipakai. Komponen itu belum ada,
  jadi spec ini berdiri sendiri: VVM dipakai lewat
  `vidyax bytecode file.vx` lalu `vxvm file.vxc`. Orchestrator masuk
  roadmap, bukan prasyarat.
- **[revisi]** Contoh implementasi Python di blueprint v1 dihapus:
  VM di atas Python tetap numpang Python dan lebih lambat dari
  transpiler yang sudah ada. VVM ditulis dalam C.

## 2. Arsitektur inti (sesuai blueprint, kini terimplementasi)

| Komponen | Implementasi |
|---|---|
| Instruction Pointer | `ip` per frame, byte-offset ke dalam code proto |
| Operand Stack | `Value stack[16384]`, dipakai semua opcode komputasi |
| Call Stack | `Frame frames[1024]`: {proto, ip, env} |
| Heap | objek `OStr`/`OList`/`OFunc`/`Env`, semua lewat satu allocator |
| VM Registers | `sp`, `nframes`, `nhandlers`, `instr_count`, `mem_used` — internal, tak tersentuh program |

**[revisi] "Internal AI State" di stack frame dihapus** — belum ada
semantik konkretnya. Ditambahkan kembali jika ada fitur nyata yang
membutuhkannya.

### 2.1 Model nilai (baru — belum ada di blueprint v1)

Tagged union: `null`, `bool`, `number` (double 64-bit), `text`
(immutable, byte-based), `list` (mutable, semantik referensi seperti
Python), `func` (proto + closure env), `builtin`.

### 2.2 Scoping & closure (baru — bagian tersulit, wajib di-spec)

- Variabel diakses lewat **rantai environment**; setiap pemanggilan
  fungsi membuat `Env` baru dengan parent = env tempat fungsi
  **didefinisikan** (closure).
- Aturan sama persis dengan engine Python: nama yang di-assign di mana
  pun dalam sebuah fungsi bersifat lokal; daftar nama itu (`declared`)
  dihitung compiler dan disimpan di proto. Membaca nama `declared` yang
  belum terisi → error `variable 'X' is assigned in this function but
  used before it has a value`.
- Kunci env dibandingkan **per pointer** — sah karena pool konstanta
  di-dedupe oleh compiler.

### 2.3 Error & try/catch (baru)

Stack handler terpisah: `{frame, sp, catch_ip}`. `TRY_PUSH` mendaftar
handler; error runtime melakukan unwind (pulihkan frame + sp, lompat ke
`catch_ip`, push pesan error sebagai teks). Tanpa handler → cetak
`[Vidyax] pesan`, exit 1. `RET` otomatis membuang handler milik frame
yang ditinggalkan.

## 3. VIR — format bytecode (baru)

File `.vxc`, little-endian:

```
"VXC1"  magic
u8      versi (=1)
u32     jumlah konstanta; tiap konstanta:
          tag u8: 1=NUM (f64), 2=STR (u32 panjang + utf-8)
u32     jumlah proto; tiap proto (proto 0 = top level):
          u32 idx-nama, u8 jumlah-param (+u32 idx tiap nama),
          u16 jumlah-declared (+u32 idx tiap nama),
          u32 panjang-code + bytes
```

37 opcode (lihat tabel `OPS` di `vxc.py` — satu-satunya sumber
penomoran; `vm/vxvm.c` wajib sinkron). Operand: u16 (konstanta/nama),
u8 (argc), u32 (target lompatan absolut).

Loop `rpt`/`for..in` di-desugar compiler menjadi counter tersembunyi
(`$n0`, `$i0`, `$it0` — nama ber-`$` tak mungkin bentrok dengan program
karena lexer tidak pernah menghasilkannya).

## 4. AI Sandboxing (sesuai blueprint, angka direvisi)

Semua **opsional lewat flag**, default tanpa batas — program biasa tak
boleh mati karena limit sandbox:

```
vxvm --max-instr 50000000 --max-mem 268435456 --max-time 5 prog.vxc
```

- **Instruction limit** — dicek tiap instruksi.
  **[revisi]** default blueprint 100.000 terlalu kecil (fib(25) saja
  jutaan instruksi); rekomendasi mode sandbox: ≥ 50 juta.
- **Memory limit** — hitungan **byte** teralokasi (bukan jumlah objek),
  semua jalur alokasi (malloc + realloc) tercatat.
- **Time limit** — CPU time, dicek tiap 4096 instruksi.
- **Permission control** — milestone 1 memenuhi ini secara alami: VVM
  belum punya opcode file system / network / subprocess sama sekali.
  Saat `get`/`ai` masuk (milestone 4), keduanya wajib di belakang flag
  izin eksplisit.
- **Bytecode verification** — sebelum eksekusi: opcode valid, operand
  tidak terpotong, indeks konstanta/proto dalam jangkauan, LOAD/STORE
  menunjuk konstanta teks, semua target lompatan mendarat tepat di awal
  instruksi. VIR rusak ditolak sebelum jalan.

## 5. Garbage Collection — Mark-Sweep (terimplementasi)

Sesuai blueprint Bab 5, dengan satu keputusan desain penting:

- **Koleksi hanya di safepoint** — awal dispatch loop, antar-instruksi.
  Alokasi tidak pernah mengoleksi; ia hanya menaikkan `gc_pending` saat
  heap melewati ambang (`next_gc`, awal 1 MB, lalu 2× ukuran hidup
  pasca-sweep). Dengan ini tidak ada objek temporer C yang bisa
  ter-sweep di tengah sebuah operasi.
- **Roots:** pool konstanta, operand stack `[0..sp)`, dan env tiap
  frame (mark env menjalar ke entri + rantai parent → closure aman).
  `V_BUILTIN` menunjuk tabel statis, bukan heap — dilewati.
- **Akuntansi byte presisi:** setiap jalur alokasi (malloc, realloc,
  buffer string-builder) tercatat dan dikembalikan saat sweep, sehingga
  GC dan sandbox `--max-mem` konsisten satu sama lain.
- **Mode verifikasi:** `--gc-stress` mengoleksi di *setiap* safepoint
  (root yang kelewat langsung merusak hasil), `--gc-stats` mencetak
  jumlah koleksi + puncak memori ke stderr. Seluruh differential suite
  wajib hijau di bawah `--gc-stress` DAN di bawah build
  `-fsanitize=address,undefined` (`make debug`).

Bukti milestone: loop penghasil sampah 300 rb iterasi berjalan tuntas
di bawah `--max-mem 4000000` — 50 koleksi, puncak ~1 MB.

## 6. Status milestone

| # | Isi | Status |
|---|---|---|
| 1 | Core language di VM C, verifikasi VIR, sandbox limits, differential test | **selesai** — 40/40 kasus yang didukung identik dengan kedua engine Python |
| 2 | Mark-sweep GC + gc-stress + ASan verification | **selesai** |
| 3 | Optimizing compiler: constant folding **(selesai)**; slot-based locals, dead-code elim, peephole (berikutnya) | berjalan |
| 4 | `get`/`ai` via libcurl + permission flags | belum |
| 5 | Orchestrator / multi-engine dispatch otomatis | visi |

Benchmark kejujuran (fib(27), mesin sama): walk 4.07s → **vxvm 1.18s**
→ transpiler 0.18s. VVM sudah 3.4× lebih cepat dari tree-walker;
menyalip transpiler menunggu milestone 3 — jangan mengklaim "runtime
utama" sebelum angkanya membuktikan.

## 7. Aturan pengujian (wajib)

Setiap perubahan pada VVM atau vxc.py harus lolos:

```
python3 vidyax.py test                       # 47/47 di kedua engine Python
python3 tests_vm.py                          # VM identik dengan engine
VXVM_FLAGS="--gc-stress" python3 tests_vm.py # VM di bawah tekanan GC
cd vm && make debug && cd .. && \
  VXVM_FLAGS="--gc-stress" python3 tests_vm.py  # + sanitizers
```

Kasus baru ditambahkan di `tests.py` (otomatis terpakai tests_vm.py).
Perilaku benar didefinisikan oleh kesepakatan ketiga engine — bukan
oleh salah satunya.
