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

Measured on Linux x86_64 using [benchmarks/head_to_head.py](benchmarks/head_to_head.py) with a minimal C `wait4()` + `CLOCK_MONOTONIC` harness (median of 5 runs; per-process `ru_maxrss` measured directly without parent-process RSS inflation; identical stdout output asserted on every workload).

- **Cold-Start:** Boot runtime, print `"ok"`, exit.
- **Hanoi(18) + 50k:** Recursive `Hanoi(18)` (`262,143` calls) + `50,000` skyline block placements (`262143 1666691668`).
- **Primes (25k):** Trial-division prime counting up to `25,000` (`2762`).
- **Policy Scrub (5k):** `5,000` iterations of string trim + secret-token (`sk-`) redaction (`5000`).

| Runtime | Cold-Start | Hanoi18 + 50k | Primes (25k) | Policy Scrub (5k) | Peak RAM (`Max RSS`) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Vidyax AOT Native** | `2.35 ms` | `41.24 ms` | `72.88 ms` | `16.04 ms` | `3.80 MB` |
| **Vidyax C VM (`vxvm .vxc`)** | `2.87 ms` | `177.30 ms` | `97.20 ms` | `22.98 ms` | `3.64 MB` |
| **Vidyax Standalone CLI (`.vx`)** | `5.89 ms` | `196.29 ms` | `113.25 ms` | `22.93 ms` | `3.61 MB` |
| **Lua** | `3.24 ms` | `28.08 ms` | `13.30 ms` | `21.63 ms` | `2.59 MB` |
| **Rust (`rustc -O`)** | `2.86 ms` | `4.67 ms` | `4.52 ms` | `4.61 ms` | `2.23 MB` |
| **Python 3 (CPython)** | `46.20 ms` | `82.08 ms` | `67.78 ms` | `39.25 ms` | `10.71 MB` |
| **Node.js (V8 JIT)** | `59.68 ms` | `70.83 ms` | `71.07 ms` | `66.53 ms` | `72.91 MB` |
| **C (`gcc -O2`)** | `2.18 ms` | `2.68 ms` | `4.19 ms` | `2.21 ms` | `1.69 MB` |

### Honest Trade-offs & Limitations

1. **Where Vidyax wins:** On short-lived sandboxed scripts and string/policy pipelines (`Policy Scrub 5k`), `Vidyax AOT Native` (`16.04 ms`) beats **Lua (`21.63 ms`)**, **CPython (`39.25 ms`)**, and **Node.js V8 (`66.53 ms`)**, with cold-start (`2.35–2.87 ms`) and peak RSS (`3.61–3.80 MB`) an order of magnitude below CPython and Node.js while enforcing deny-by-default capability sandboxing (`sandbox deny net, fs:`) in-process.
2. **Where C, Rust, and Lua remain faster:**
   - **C (`2.68–4.19 ms`) & Rust (`4.52–4.67 ms`)** run unboxed machine integers with zero GC safepoint overhead. Vidyax values are dynamically tagged (`Value` structs) with runtime type checks and GC safepoints on loops/calls — most visible in tight integer division (`Primes 25k`: `72.88 ms` AOT vs `4.52 ms` Rust).
   - **Lua (`13.30–28.08 ms`)** uses a register-based VM, whereas `vxvm` is a stack-based bytecode interpreter without a JIT.
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
