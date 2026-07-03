# Vidyax Virtual Machine (VVM) — Architecture Specification v1.1

A revision of the v1 blueprint, aligned with the actual implementation in
`vm/vxvm.c` (C) + `vxc.py` (VIR compiler). Changes from blueprint v1 are
marked **[revised]** along with the reason. Status: a living document —
the implementation and spec must always stay in sync.

---

## 1. VVM's place in the toolchain

```
file.vx ──(vidyax.py: lexer→parser→type_check)──► AST
AST ──(vxc.py)──► VIR (.vxc)  ──(vm/vxvm: verify→execute)──► result
```

- The front-end (lexer, parser, scope analysis) is **shared** with the
  two Python engines — the VVM inherits the exact same semantics.
- **[revised]** Blueprint v1 named an "AI Orchestrator" and "C/x86"
  compilation as the deciders of when the VVM is used. Those components
  don't exist yet, so this spec stands on its own: the VVM is used via
  `vidyax bytecode file.vx` then `vxvm file.vxc`. The orchestrator is on
  the roadmap, not a prerequisite.
- **[revised]** The Python example implementation in blueprint v1 has
  been removed: a VM on top of Python still rides on Python and is slower
  than the existing transpiler. The VVM is written in C.

## 2. Core architecture (per blueprint, now implemented)

| Component | Implementation |
|-----------|----------------|
| Instruction Pointer | `ip` per frame, a byte offset into the proto's code |
| Operand Stack | `Value stack[16384]`, used by all computation opcodes |
| Call Stack | `Frame frames[1024]`: {proto, ip, env} |
| Heap | `OStr`/`OList`/`OFunc`/`Env` objects, all through one allocator |
| VM Registers | `sp`, `nframes`, `nhandlers`, `instr_count`, `mem_used` — internal, untouchable by the program |

**[revised] The "Internal AI State" in the stack frame was removed** — it
had no concrete semantics. It will be added back if a real feature needs
it.

### 2.1 Value model (new — absent in blueprint v1)

A tagged union: `null`, `bool`, `number` (64-bit double), `text`
(immutable, byte-based), `list` (mutable, reference semantics like
Python), `func` (proto + closure env), `builtin`.

### 2.2 Scoping & closures (new — the hardest part, must be specified)

- Variables are accessed via an **environment chain**; each function call
  creates a new `Env` whose parent is the environment where the function
  was **defined** (closure).
- The rule is exactly the Python engines': a name assigned anywhere in a
  function is local; that list of names (`declared`) is computed by the
  compiler and stored in the proto. Reading a `declared` name before it
  has a value → `variable 'X' is assigned in this function but used
  before it has a value`.
- Environment keys are compared **by pointer** — valid because the
  constant pool is deduplicated by the compiler.

### 2.3 Errors & try/catch (new)

A separate handler stack: `{frame, sp, catch_ip}`. `TRY_PUSH` registers a
handler; a runtime error unwinds (restores frame + sp, jumps to
`catch_ip`, pushes the error message as text). With no handler → print
`[Vidyax] message`, exit 1. `RET` automatically drops handlers belonging
to the frame it leaves.

## 3. VIR — the bytecode format (new)

A `.vxc` file, little-endian:

```
"VXC1"  magic
u8      version (=1)
u32     constant count; each constant:
          tag u8: 1=NUM (f64), 2=STR (u32 length + utf-8)
u32     proto count; each proto (proto 0 = top level):
          u32 name-idx, u8 param-count (+u32 idx per name),
          u16 declared-count (+u32 idx per name),
          u32 code-length + bytes
```

37 opcodes (see the `OPS` table in `vxc.py` — the single source of
numbering; `vm/vxvm.c` must stay in sync). Operands: u16 (constant/name),
u8 (argc), u32 (absolute jump target).

`rpt`/`for..in` loops are desugared by the compiler into hidden counters
(`$n0`, `$i0`, `$it0` — `$`-prefixed names can never collide with program
names because the lexer never produces them).

## 4. AI Sandboxing (per blueprint, numbers revised)

All **optional via flags**, unlimited by default — a normal program must
never die from a sandbox limit:

```
vxvm --max-instr 50000000 --max-mem 268435456 --max-time 5 prog.vxc
```

- **Instruction limit** — checked each instruction.
  **[revised]** The blueprint default of 100,000 is too small (fib(25)
  alone is millions of instructions); recommended sandbox mode: ≥ 50
  million.
- **Memory limit** — a count of **bytes** allocated (not object count),
  with every allocation path (malloc + realloc) tracked.
- **Time limit** — CPU time, checked every 4096 instructions.
- **Permission control** — milestone 1 satisfies this naturally: the VVM
  has no file system / network / subprocess opcodes at all. When
  `get`/`ai` arrive (milestone 4), both must sit behind an explicit
  permission flag.
- **Bytecode verification** — before execution: valid opcodes,
  non-truncated operands, in-range constant/proto indices, LOAD/STORE
  pointing at text constants, and every jump target landing exactly on an
  instruction boundary. Corrupt VIR is rejected before it runs.

## 5. Garbage Collection — Mark-Sweep (implemented)

Per blueprint chapter 5, with one important design decision:

- **Collection only at safepoints** — the top of the dispatch loop,
  between instructions. Allocation never collects; it merely raises
  `gc_pending` when the heap crosses a threshold (`next_gc`, starting at
  1 MB, then 2× the live size after a sweep). This ensures no C temporary
  can be swept mid-operation.
- **Roots:** the constant pool, the operand stack `[0..sp)`, and each
  frame's env (marking an env cascades to its entries + parent chain → a
  closure stays safe). `V_BUILTIN` points at a static table, not the heap
  — it is skipped.
- **Precise byte accounting:** every allocation path (malloc, realloc,
  string-builder buffers) is tracked and returned on sweep, so the GC and
  the `--max-mem` sandbox stay consistent with each other.
- **Verification modes:** `--gc-stress` collects at *every* safepoint (a
  missed root instantly breaks the result), `--gc-stats` prints the
  collection count + peak memory to stderr. The entire differential suite
  must be green under `--gc-stress` AND under a
  `-fsanitize=address,undefined` build (`make debug`).

Milestone proof: a garbage-heavy loop of 300k iterations runs to
completion under `--max-mem 4000000` — 50 collections, peak ~1 MB.

## 6. Milestone status

| # | Contents | Status |
|---|----------|--------|
| 1 | Core language on the C VM, VIR verification, sandbox limits, differential tests | **done** — 40/40 supported cases identical to both Python engines |
| 2 | Mark-sweep GC + gc-stress + ASan verification | **done** |
| 3 | Optimizing compiler: constant folding **(done)**; slot-based locals, dead-code elimination, peephole (next) | in progress |
| 4 | `get`/`ai` via libcurl + permission flags | pending |
| 5 | Orchestrator / automatic multi-engine dispatch | vision |

Honesty benchmark (fib(27), same machine): walk 4.07s → **vxvm 1.18s**
→ transpiler 0.18s. The VVM is already 3.4× faster than the tree-walker;
overtaking the transpiler awaits milestone 3 — don't claim "primary
runtime" before the numbers prove it.

## 7. Testing rules (mandatory)

Every change to the VVM or vxc.py must pass:

```
python3 vidyax.py test                       # 47/47 on both Python engines
python3 tests_vm.py                          # VM identical to the engines
VXVM_FLAGS="--gc-stress" python3 tests_vm.py # VM under GC pressure
cd vm && make debug && cd .. && \
  VXVM_FLAGS="--gc-stress" python3 tests_vm.py  # + sanitizers
```

New cases are added in `tests.py` (automatically used by tests_vm.py).
Correct behavior is defined by the agreement of all three engines — not
by any single one.

## 8. Prerequisites for self-hosting

The long-term goal is a compiler written in Vidyax itself. That requires
the **language** to grow first — at minimum: file I/O, a dictionary/map
type, and bitwise operators, none of which exist yet. Self-hosting is
therefore not merely rewriting the compiler; the language must mature
before the toolchain can be rebuilt in it.
