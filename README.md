<div align="center">

# Vidyax

**An experimental, capability-sandboxed programming language with a self-hosting bytecode compiler and C virtual machine.**

[![VS Code Rating](https://img.shields.io/visual-studio-marketplace/stars/nadev.vidyax?color=gold)](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax)
[![GitHub Stars](https://img.shields.io/github/stars/Vidyax-Lang/Vidyax?style=social)](https://github.com/Vidyax-Lang/Vidyax/stargazers)
[![Docs](https://img.shields.io/badge/docs-online-1f7a4c)](https://vidyax-lang.github.io/Vidyax/)

[Documentation](https://vidyax-lang.github.io/Vidyax/) · [Benchmarks](benchmarks/head_to_head.py) · [Issues](https://github.com/Vidyax-Lang/Vidyax/issues)

</div>

---

> **Status: Experimental (Not Yet Stable).** Vidyax is under active development and is not recommended for production use. Language syntax, bytecode encoding, standard library APIs, and runtime internals are subject to breaking changes.

Vidyax is a small, statically verified bytecode language designed for running untrusted or AI-generated scripts in-process without spinning up containers or heavy runtimes.

- **Deny-by-default capability sandbox:** Network and filesystem access are disabled by default and can be further restricted per lexical scope (`sandbox deny net, fs:`), inherited across spawned concurrent tasks (`go` / `wait`).
- **Self-hosted standalone CLI (`./vidyax`):** `make -C vm vidyax` embeds the 3-stage self-hosted compiler (`vxc.vxc`) into the C VM (`vxvm`), allowing `./vidyax program.vx` to compile and execute without requiring Python at runtime.
- **Lazy `libcurl` loading:** `libcurl.so.4` is loaded via `dlopen` only on the first HTTP or `ai.ask()` call, keeping offline startup low (`2.5–2.8 ms`) and peak RSS around `2.3–3.5 MB`.
- **Four parity-verified engines:** Tree-walker, Python transpiler, C bytecode VM (`vxvm`), and AOT native C backend (`vidyax native`), verified against `135/135` VM tests and `300/300` differential fuzzer runs.

---

## Quick Start

Requires a C99 compiler (`gcc` / `cc`) and `make`.

```bash
git clone https://github.com/Vidyax-Lang/Vidyax.git
cd Vidyax
make -C vm vxvm vidyax

./vidyax benchmarks/head_to_head.vx
./vidyax compile program.vx -o program.vxc
./vm/vxvm program.vxc
```

Capabilities are denied by default; opt in explicitly when needed:

```bash
./vidyax --allow-fs program.vx
./vidyax --allow-net --max-instr 5000000 --max-mem 16777216 program.vx
```

---

## Technical Benchmark Report (Head-to-Head)

Measured on Linux x86_64 using [benchmarks/head_to_head.py](benchmarks/head_to_head.py) with a minimal C `wait4()` + `CLOCK_MONOTONIC` harness (median of 5 runs; per-process `ru_maxrss` measured directly without parent-process RSS inflation).

- **Cold-start:** Boot runtime, print `"ok"`, exit.
- **Compute:** Identical algorithm across every runtime — recursive `Hanoi(18)` (`262,143` calls) + `50,000` skyline block-placement iterations ([benchmarks/head_to_head.vx](benchmarks/head_to_head.vx)), asserting exact output `262143 1666691668`.

| Runtime | Cold-Start | Compute (`Hanoi(18) + 50k`) | Peak RAM (`Max RSS`) | Binary Size | Built-in Sandbox |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Vidyax AOT Native** | `2.48 ms` | `39.97 ms` | `2.35 MB` (`2,408 KB`) | `93 KB` | Built-in (`deny net, fs`) |
| **Vidyax C VM (`vxvm .vxc`)** | `2.83 ms` | `175.56 ms` | `3.41 MB` (`3,488 KB`) | `104 KB` | Built-in (`deny net, fs`) |
| **Vidyax Zero-Python CLI (`.vx`)** | `5.55 ms` | `186.78 ms` | `3.50 MB` (`3,580 KB`) | `144 KB` | Built-in + self-hosted |
| **Lua** | `3.09 ms` | `27.96 ms` | `2.57 MB` (`2,628 KB`) | `322 KB` | Manual env strip |
| **Rust (`rustc -O`)** | `3.02 ms` | `5.30 ms` | `2.15 MB` (`2,200 KB`) | `4.3 MB` | None (OS-level) |
| **Python 3 (CPython)** | `38.97 ms` | `74.05 ms` | `10.86 MB` (`11,120 KB`) | `14 KB + libpython` | None |
| **Node.js (V8 JIT)** | `56.77 ms` | `68.11 ms` | `72.05 MB` (`73,780 KB`) | `119.1 MB` | Experimental flag |
| **C (`gcc -O2`)** | `2.25 ms` | `2.85 ms` | `1.62 MB` (`1,664 KB`) | `16 KB` | None (raw OS) |

### Honest Trade-offs & Limitations

1. **Where Vidyax wins:** Cold-start (`2.48–2.83 ms`), binary size (`93–144 KB`), and peak RSS (`2.35–3.50 MB`) are an order of magnitude smaller/faster than CPython (`38.97 ms`, `10.86 MB`) and Node.js V8 (`56.77 ms`, `72.05 MB`), while enforcing capability sandboxing (`--max-instr`, `--max-mem`, `--max-time`, `sandbox deny net, fs:`) in-process without containers. End-to-end, `Vidyax AOT Native` (`39.97 ms`) outperforms both CPython (`74.05 ms`) and Node.js (`68.11 ms`) on short-lived compute workloads.
2. **Where C, Rust, and Lua remain faster:**
   - **C (`2.85 ms`) & Rust (`5.30 ms`)** run unboxed machine integers with zero GC safepoint overhead. Vidyax values are dynamically tagged (`Value` structs) with runtime type checks and GC safepoints on loops/calls.
   - **Lua (`27.96 ms`)** uses a register-based VM, whereas `vxvm` (`175.56 ms`) is a stack-based bytecode interpreter without a JIT.
   - **AOT native compiler (`vxnative.py`)** still uses Python for `.vx -> .c` codegen; porting it to `.vx` and adding unboxed numeric local specialization are the next open engineering milestones.

Reproduce on your own hardware:

```bash
python3 benchmarks/head_to_head.py
```

---

## Architecture

```
  source.vx
      │
      ▼
  vxc.vx (self-hosted compiler, embedded in ./vidyax)
      │
      ▼
  VXC1 v3 Bytecode (.vxc)
      │
      ▼
  Bytecode Verifier ──► Vidyax C VM (vxvm)   [104 KB, mark-sweep GC, capability sandbox]
                    └──► WASM (vidyax.wasm)  [112 KB, browser/edge execution]
```

Optional Python toolchain commands (AOT native codegen, disassembler, LSP, differential fuzzer):

```bash
python3 vidyax.py native program.vx -o program   # AOT compile to standalone C binary
python3 vidyax.py disasm program.vx              # inspect bytecode + line table
python3 vidyax.py lsp                            # JSON-RPC stdio Language Server
```

---

## Language Overview

**Lexical capability sandboxing**

```vidyax
sandbox deny net, fs:
    # Network and filesystem builtins fail deterministically inside this block
    # and inside any task spawned with `go` from here.
    clean: trim(lower("REPORT.TXT"))
    print clean
```

**Functions & recursion**

```vidyax
func factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print "5! = " + text(factorial(5))
```

**Concurrent I/O & stateful AI agents**

```vidyax
use ai

a: go ai.ask("Explain gravity in one sentence")
b: go ai.ask("Explain photosynthesis in one sentence")
print wait(a)
print wait(b)
```

More runnable examples live in [`contoh/`](./contoh). Full syntax and VM bytecode reference: [vidyax-lang.github.io/Vidyax](https://vidyax-lang.github.io/Vidyax/).

---

## Self-Hosting Verification & Test Suite

Verify the 3-stage bit-exact self-hosting fixed point (`vxc.vx` compiling itself twice on `vxvm` with identical output bytes) and cross-engine parity:

```bash
./bootstrap.sh       # 3-stage fixed-point bootstrap (34,274 bytes)
python3 tests.py     # tree-walker + transpiler + native parity suite
python3 tests_vm.py  # 135/135 C VM + sandbox + concurrency tests
python3 fuzz.py      # 300/300 differential fuzzer across walk/fast/vm
```

---

## Ecosystem & Tooling

- **Kronumos Ecosystem:** Vidyax serves as the sandboxed execution runtime for [Kronumos](https://kronumos.com/) and [Tokenectomy Labs](https://github.com/Tokenectomy-Labs).
- **VS Code Extension:** Syntax highlighting + LSP integration via [Visual Studio Marketplace (`nadev.vidyax`)](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax).
- **Fine-Tuned Model:** `NadevA23/Viydax-Coder-7b-v1` on [Hugging Face](https://huggingface.co/NadevA23/Viydax-Coder-7b-v1).

## Contributing & License

Bug reports, reproducible benchmarks, and PRs are welcome via [GitHub Issues](https://github.com/Vidyax-Lang/Vidyax/issues). Every language change must pass `tests.py`, `tests_vm.py`, `fuzz.py`, and `./bootstrap.sh`.

Licensed under the Apache-2.0 License. Copyright © 2026 Tokenectomy Labs.
