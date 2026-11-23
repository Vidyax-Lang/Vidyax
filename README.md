<div align="center">

# Vidyax

**A lightweight, secure, AI-native programming language with its own C-based bytecode virtual machine.**

*"Code as simple as writing instructions."*

[![Rating](https://img.shields.io/visual-studio-marketplace/stars/nadev.vidyax?color=gold)](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax)
[![GitHub Stars](https://img.shields.io/github/stars/Vidyax-Lang/Vidyax?style=social)](https://github.com/Vidyax-Lang/Vidyax/stargazers)
[![Docs](https://img.shields.io/badge/docs-online-8A2BE2)](https://vidyax-lang.github.io/Vidyax/)

[Documentation](https://vidyax-lang.github.io/Vidyax/) · [Report a Bug](https://github.com/Vidyax-Lang/Vidyax/issues) · [Request a Feature](https://github.com/Vidyax-Lang/Vidyax/issues)

</div>

---

## Introduction

**Vidyax** is a programming language designed around a single idea: writing code should feel as natural as writing plain instructions. It began as a humble tree-walking interpreter in Python and grew into a complete ecosystem of compilers, bytecode tooling, and AI-assisted execution.

Vidyax is built to be three things at once:

- **Lightweight** — the entire runtime is a single, dependency-free C binary that compiles and runs comfortably even on modest hardware.
- **Secure** — every program is verified before execution and runs inside a sandbox with configurable resource limits, making Vidyax safe for untrusted or educational environments.
- **AI-native** — a first-class `ai` module lets programs query language models directly, treating AI as a built-in capability rather than an afterthought.

Above all, Vidyax is an **educational** language: readable enough for a beginner's first program, yet architecturally complete enough to demonstrate how real languages work — from lexing and parsing to bytecode verification and execution.

## Kronumos Ecosystem

Vidyax is part of the broader **Kronumos ecosystem** — a vision of autonomous, AI-native software engineering built around verifiable tools, high-performance runtimes, and intelligent developer workflows.

The Kronumos ecosystem combines:

- **Vidyax** — an AI-native programming language with its own compiler and virtual machine.
- **Kronumos AI tools** — autonomous systems for software repair, debugging, and code understanding.
- **Developer-first automation** — workflows designed to make building, validating, and shipping software more reliable and more intelligent.

Together, these projects aim to create a connected environment where language design, compiler engineering, and AI-assisted software development reinforce one another.

- [Hugging Face](https://huggingface.co/Kronumos)
- [Kronomus](https://kronumos.com/)
- [Vidyax](https://github.com/Vidyax-Lang/Vidyax)

## Key Features

- 🔁 **Four Verified Engines** — a tree-walker, a Python transpiler, a C bytecode VM, and an **ahead-of-time native compiler** all run the same programs through a shared differential test suite.
- 🚀 **Custom C Virtual Machine (VVM)** — a stack-based bytecode interpreter written entirely in C, outpacing the Python transpiler by a wide margin.
- 🏎️ **Native Backend** — `vidyax native` compiles a program to a standalone C binary (no runtime needed) that runs ~2.6× faster than the VM and ~36× faster than the transpiler.
- ⚙️ **Optimizing Compiler** — constant folding, dead-code elimination, peephole, function inlining, escape analysis, and a basic-block CFG layer, all behavior-preserving.
- 🧹 **Mark-Sweep Garbage Collector** — safepoint-based collection with precise byte-level accounting. No manual memory handling.
- 🧵 **Concurrency** — `go f(x)` / `wait(t)` runs slow I/O (network, AI) in parallel on all four engines, with a GIL-style model that makes data races impossible.
- 📦 **Modules & Packages** — `use name` splits code across files; `vidyax install user/repo` fetches shared modules.
- 🛡️ **Sandbox & Verifier** — every compiled program is validated (opcodes, operands, jump targets) before it runs, with optional instruction/memory/time limits for untrusted code.
- 🤖 **Built-in AI Module** — query language models directly from your code with a clean, minimal API.
- 🤖 **Official AI Assistant** — `vidyax-coder-7b` fine-tuned on Hugging Face for generating and explaining Vidyax code.
- 🧰 **Full Toolchain** — an interactive REPL, a line debugger (`vidyax debug`), a profiler (`vidyax profile`), a disassembler (`vidyax disasm`), a Language Server (`vidyax lsp`), and a publication pipeline for packages and docs.

## Architecture Overview

Vidyax follows a classic, staged compilation pipeline. Source code is transformed step by step into a compact bytecode format, which is then executed by the virtual machine:

```
  source.vx
      │
      ▼
   Lexer  ──►  Parser  ──►  AST  ──►  Semantic Analysis
                                            │
                                            ▼
                                       Compiler
                                            │
                                            ▼
                                   Bytecode (.vxc)
                                            │
                                            ▼
                              Bytecode Verifier ──► Vidyax VM (C)
                                                          │
                                                          ▼
                                                       Result
```

The Python-based front end (lexer, parser, and semantic analysis) is shared across every engine, ensuring the language behaves identically whether interpreted directly, compiled to bytecode, or converted to native code.

## Syntax & Usage Examples

**Hello World**

```vidyax
print "Hello, World!"
```

**Variables**

```vidyax
name: "NaDev"
print "Hello " + name

age: 19
if age >= 17:
    print "Adult"
else:
    print "Minor"
```

**Loops**

```vidyax
# Repeat N times
rpt 3:
    print "loop"

# Iterate over a list
fruits: ["apple", "mango", "orange"]
for f in fruits:
    print "fruit: " + f
```

**Functions & Recursion**

```vidyax
func factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print "5! = " + factorial(5)
```

**AI, in parallel**

```vidyax
use ai

# both questions are sent at the same time
a: go ai.ask "Explain gravity in one sentence"
b: go ai.ask "Explain photosynthesis in one sentence"
print wait(a)
print wait(b)
```

More runnable programs — a guessing game, a word counter, a note keeper,
a chatbot — live in the [`contoh/`](./contoh) folder. For the complete
language reference, see the [official documentation](https://vidyax-lang.github.io/Vidyax/).

## Installation & Setup

Vidyax requires **GCC** (or any C99-compatible compiler), **Make**, and **Python 3** for the compiler front end.

**1. Clone the repository**

```bash
git clone https://github.com/Vidyax-Lang/Vidyax.git
cd Vidyax
```

**2. Build the virtual machine**

```bash
cd vm
make
cd ..
```

This compiles the C source into the `vxvm` binary. Alternatively, you can invoke the compiler directly:

```bash
make -C vm        # or: cc -O2 -o vm/vxvm vm/*.c -lm -lcurl
```

**3. Run a Vidyax program**

The quickest way to run a `.vx` file:

```bash
python3 vidyax.py run program.vx
```

To run it through the C virtual machine, compile to bytecode first, then execute:

```bash
python3 vidyax.py bytecode program.vx
./vm/vxvm program.vxc
```

To compile a program to a **standalone native binary** (no Python needed
to run it):

```bash
python3 vidyax.py native program.vx -o program
./program
```

**4. Verify your build (optional)**

Run the full test suite to confirm every engine agrees:

```bash
python3 vidyax.py test      # tree-walker + transpiler (+ VM/native smoke tests)
python3 tests_vm.py         # C virtual machine
python3 fuzz.py             # differential fuzzer across engines
```

## 🤖 AI Coding Assistant

Vidyax ships with an official AI coding assistant fine-tuned specifically for the language.

**Vidyax Coder 7B** is a Qwen 7B-based model trained on curated Vidyax code, capable of generating code, explaining errors, and refactoring programs with full understanding of Vidyax's unique syntax and runtime model.

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained("NadevA23/Viydax-Coder-7b-v1")
tokenizer = AutoTokenizer.from_pretrained("NadevA23/Viydax-Coder-7b-v1")
```

Available on [Hugging Face](https://huggingface.co/NadevA23/Viydax-Coder-7b-v1).

## VS Code Tooling

Vidyax ships with an official **Visual Studio Code extension** that provides syntax highlighting and editor support for `.vx` files.

**To install:**

1. Open **Visual Studio Code**.
2. Go to the **Extensions** panel (`Ctrl+Shift+X`).
3. Search for **Vidyax**.
4. Click **Install** on the official extension by `NaDev`.

You can also install it directly from the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax).

## Self-Hosting Bootstrap & Zero-Python Standalone CLI (`vxc.vx`)

Vidyax compiles itself to `VXC1 v3` bytecode on the native C VM (`vm/vxvm`) with a verified 3-stage bit-exact fixed point (`34,274 bytes`, `135/135` VM tests, `300/300` differential fuzzer parity):

```bash
./bootstrap.sh
make -C vm vxvm vidyax
```

`make -C vm vidyax` embeds the self-hosted `vxc.vxc` compiler directly inside the C VM to produce a single **`141 KB` standalone native binary (`./vidyax`)** with **zero Python runtime dependency**:

```bash
./vidyax program.vx                  # compile (.vx -> .vxc) via embedded vxc + execute in sandbox
./vidyax compile program.vx -o a.vxc # compile to bytecode without Python
./vidyax --allow-fs program.vx       # opt-in capability flags (net & fs denied by default)
```

## Technical Benchmark Report (Head-to-Head)

All numbers below are measured on Linux x86_64 via [benchmarks/head_to_head.py](benchmarks/head_to_head.py) using a minimal C `wait4()` + `CLOCK_MONOTONIC` harness (median of 5 runs; per-process `ru_maxrss` measured directly without Python fork RSS inflation).

- **Cold-start:** Boot runtime, print `"ok"`, exit.
- **Compute:** Identical algorithm across all runtimes — recursive `Hanoi(18)` (`262,143` calls) + `50,000` skyline block-placement iterations (output asserted identical: `262143 1666691668`).
- **Networking:** `libcurl` is lazy-loaded via `dlopen("libcurl.so.4")` only on the first HTTP/`ai.ask()` call, so offline/sandboxed programs pay zero OpenSSL/libcurl startup cost.

| Runtime | Cold-Start | Compute (`Hanoi(18) + 50k`) | Peak RAM (`Max RSS`) | Binary Size | Built-in Sandbox |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Vidyax AOT Native** | `2.54 ms` | `39.27 ms` | `2.29 MB` (`2,348 KB`) | `94 KB` | Built-in (`deny net, fs`) |
| **Vidyax C VM (`vxvm .vxc`)** | `2.68 ms` | `174.60 ms` | `3.45 MB` (`3,528 KB`) | `104 KB` | Built-in (`deny net, fs`) |
| **Vidyax Zero-Python CLI (`.vx`)** | `6.25 ms` | `187.12 ms` | `3.35 MB` (`3,432 KB`) | `141 KB` | Built-in + self-hosted |
| **Lua** | `3.01 ms` | `26.61 ms` | `2.56 MB` (`2,620 KB`) | `322 KB` | Manual env strip |
| **Rust (`rustc -O`)** | `3.58 ms` | `5.06 ms` | `2.25 MB` (`2,300 KB`) | `4.3 MB` | None (OS-level) |
| **Python 3 (CPython)** | `36.44 ms` | `74.64 ms` | `10.84 MB` (`11,096 KB`) | `14 KB + libpython` | None |
| **Node.js (V8 JIT)** | `57.83 ms` | `67.77 ms` | `72.04 MB` (`73,768 KB`) | `119 MB` | Experimental flag |
| **C (`gcc -O2`)** | `2.11 ms` | `2.54 ms` | `1.62 MB` (`1,664 KB`) | `16 KB` | None (raw OS) |

### Honest Trade-offs & Architectural Notes

1. **Where Vidyax wins:** Cold-start (`2.54–2.68 ms`), binary footprint (`94–141 KB`), and memory footprint (`2.29–3.45 MB`) beat CPython (`36.44 ms`, `10.84 MB`) and Node.js V8 (`57.83 ms`, `72.04 MB`) by an order of magnitude while enforcing deny-by-default capability sandboxing (`sandbox deny net, fs:`) without Docker or microVM overhead. End-to-end, `Vidyax AOT Native` (`39.27 ms`) outperforms both CPython (`74.64 ms`) and Node.js (`67.77 ms`) on this short-lived compute workload.
2. **Where C, Rust, and Lua remain faster:**
   - **C (`2.54 ms`) & Rust (`5.06 ms`)** operate on unboxed machine integers with zero GC safepoint checks. Vidyax values are dynamically tagged (`Value` structs) with runtime type checks and GC safepoints on loops/calls.
   - **Lua (`26.61 ms`)** uses a register-based VM, whereas `vxvm` (`174.60 ms`) is currently a stack-based bytecode interpreter without a JIT.
   - **Next optimization target:** Unboxed `int64`/`double` local specialization in `vxnative` to close the gap toward C/Rust for numeric loops.

Reproduce on your own hardware:

```bash
python3 benchmarks/head_to_head.py
```

## Contributing

Contributions, bug reports, and feature requests are welcome. Feel free to open an [issue](https://github.com/Vidyax-Lang/Vidyax/issues) or submit a pull request. Every new language feature is expected to be verified against the shared test suite before merging.

Copyright © 2026 Tokenectomy Labs.
---

<div align="center">

**Built by [Tokenectomy Labs](https://github.com/Tokenectomy-Labs)**

</div>
