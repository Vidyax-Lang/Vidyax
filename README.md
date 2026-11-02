<div align="center">

# Vidyax

**A lightweight, secure, AI-native programming language with its own C-based bytecode virtual machine.**

*"Code as simple as writing instructions."*

[![Rating](https://img.shields.io/visual-studio-marketplace/stars/nadev.vidyax?color=gold)](https://marketplace.visualstudio.com/items?itemName=nadev.vidyax)
[![License](https://img.shields.io/github/license/Vidyax-Lang/Vidyax?color=blue)](https://github.com/Vidyax-Lang/Vidyax/blob/main/LICENSE)
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

- [Kronumos](https://huggingface.co/Kronumos)
- [Kronomus](https://github.com/Tokenectomy-Labs/Kronomus)
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

## Contributing

Contributions, bug reports, and feature requests are welcome. Feel free to open an [issue](https://github.com/Vidyax-Lang/Vidyax/issues) or submit a pull request. Every new language feature is expected to be verified against the shared test suite before merging.

## License

Copyright © 2026 Tokenectomy Labs.

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](https://github.com/Vidyax-Lang/Vidyax/blob/main/LICENSE).

---

<div align="center">

**Built by [Tokenectomy Labs](https://github.com/Tokenectomy-Labs)**

</div>
