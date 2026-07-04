<div align="center">

# Vidyax

**A lightweight, secure, AI-native programming language with its own C-based bytecode virtual machine.**

*"Code as simple as writing instructions."*

[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/daffa2555.vidyax?label=VS%20Marketplace&color=8A2BE2&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=daffa2555.vidyax)
[![License](https://img.shields.io/github/license/daffa2555/Vidyax?color=blue)](https://github.com/daffa2555/Vidyax/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/daffa2555/Vidyax?style=social)](https://github.com/daffa2555/Vidyax/stargazers)
[![Docs](https://img.shields.io/badge/docs-online-8A2BE2)](https://daffa2555.github.io/Vidyax/)

[Documentation](https://daffa2555.github.io/Vidyax/) · [Report a Bug](https://github.com/daffa2555/Vidyax/issues) · [Request a Feature](https://github.com/daffa2555/Vidyax/issues)

</div>

---

## Introduction

**Vidyax** is a programming language designed around a single idea: writing code should feel as natural as writing plain instructions. It began as a humble tree-walking interpreter in Python and has since evolved into a genuinely independent language, powered by its own bytecode compiler and a high-performance virtual machine written from scratch in C.

Vidyax is built to be three things at once:

- **Lightweight** — the entire runtime is a single, dependency-free C binary that compiles and runs comfortably even on modest hardware.
- **Secure** — every program is verified before execution and runs inside a sandbox with configurable resource limits, making Vidyax safe for untrusted or educational environments.
- **AI-native** — a first-class `ai` module lets programs query language models directly, treating AI as a built-in capability rather than an afterthought.

Above all, Vidyax is an **educational** language: readable enough for a beginner's first program, yet architecturally complete enough to demonstrate how real languages work — from lexing and parsing all the way down to garbage collection and bytecode execution.

## Key Features

- 🚀 **Custom C Virtual Machine (VVM)** — a stack-based bytecode interpreter written entirely in C, delivering performance that outpaces the original Python transpiler by a wide margin.
- 🧹 **Mark-Sweep Garbage Collector** — automatic memory management built from scratch, with safepoint-based collection and precise byte-level accounting. No manual memory handling required.
- ⚡ **Slot-Based Local Variables** — a compile-time escape analysis pass places non-captured locals into fast stack slots, eliminating per-call heap allocation on hot paths.
- 🛡️ **Bytecode Verifier** — every compiled program is validated before it runs: opcodes, operand ranges, and jump targets are all checked, so malformed bytecode is rejected rather than executed.
- 🔒 **Strict Sandboxing** — optional instruction, memory, and time limits let you run untrusted code safely and predictably.
- 🔁 **Three Verified Engines** — a tree-walker, a Python transpiler, and the C VM all run the same programs through a shared differential test suite, guaranteeing identical behavior across every execution path.
- 🤖 **Built-in AI Module** — query language models directly from your code with a clean, minimal API.
- 🧰 **Official Editor Tooling** — a Visual Studio Code extension provides syntax highlighting and language support out of the box.

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

The Python-based front end (lexer, parser, and semantic analysis) is shared across all three engines, ensuring the language behaves identically whether interpreted directly or compiled to bytecode. The C virtual machine handles the final stage: verifying the bytecode, then executing it with garbage collection and sandbox enforcement active.

## Syntax & Usage Examples

> Replace the snippets below with your exact Vidyax syntax.

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

For the complete language reference, see the [official documentation](https://daffa2555.github.io/Vidyax/).

## Installation & Setup

Vidyax requires **GCC** (or any C99-compatible compiler), **Make**, and **Python 3** for the compiler front end.

**1. Clone the repository**

```bash
git clone https://github.com/daffa2555/Vidyax.git
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
gcc -O2 -Wall -Wextra -o vm/vxvm vm/vxvm.c -lm
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

**4. Verify your build (optional)**

Run the full test suite to confirm all three engines agree:

```bash
python3 vidyax.py test      # tree-walker + transpiler
python3 tests_vm.py         # C virtual machine
```

## VS Code Tooling

Vidyax ships with an official **Visual Studio Code extension** that provides syntax highlighting and editor support for `.vx` files.

**To install:**

1. Open **Visual Studio Code**.
2. Go to the **Extensions** panel (`Ctrl+Shift+X`).
3. Search for **Vidyax**.
4. Click **Install** on the official extension by `daffa2555`.

You can also install it directly from the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=daffa2555.vidyax).

## Contributing

Contributions, bug reports, and feature requests are welcome. Feel free to open an [issue](https://github.com/daffa2555/Vidyax/issues) or submit a pull request. Every new language feature is expected to pass the differential test suite, ensuring all engines remain consistent.

## License

This project is licensed under the terms specified in the [LICENSE](https://github.com/daffa2555/Vidyax/blob/main/LICENSE) file.

---

<div align="center">

**Built by [NaDev](https://github.com/daffa2555)** · from a student's hands, for students.

</div>
