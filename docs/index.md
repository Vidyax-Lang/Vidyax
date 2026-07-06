# Vidyax

> *Code as simple as writing instructions.*

Vidyax (`.vx`) is a programming language designed to make writing code
feel like writing plain instructions. Its name comes from the Sanskrit
word *vidyā* (विद्या) — "knowledge".

Vidyax is more than a thin wrapper over Python. It has its own toolchain:

```
file.vx → Lexer → Parser → AST → Semantic Analysis
        → Compiler → Bytecode (.vxc) → Virtual Machine (C) → Result
```

## Hello world

```vidyax
print "Hello, world!"
```

```bash
vidyax run hello.vx
```

## What makes Vidyax different

- **Four engines, one behavior.** A tree-walker, a Python transpiler, a
  C bytecode VM, and a native compiler run the same program with
  **identical** results — guaranteed by differential testing and a
  fuzzer.
- **Its own Virtual Machine.** Written in C, with a mark-sweep garbage
  collector, an optimizing compiler, bytecode verification, and sandbox
  limits (instructions, memory, time).
- **Native binaries.** `vidyax native` compiles a program to a
  standalone executable — no runtime needed to run it.
- **Concurrency.** `go` / `wait` overlaps slow work (network, AI) with a
  model that makes data races impossible.
- **Modules & packages.** `use name` splits code across files;
  `vidyax install` fetches shared modules.
- **Friendly error messages.** Every error is explained in plain
  language, worded identically across every engine.
- **Built-in AI.** An `ai` module lets you query language models directly
  from your program.

## Where to start

<div class="grid cards" markdown>

- :material-rocket-launch: **[Guide](GUIDE.md)** — learn Vidyax from
  scratch through examples; ideal for beginners.

- :material-book-open-variant: **[Reference](REFERENCE.md)** — the
  complete list of syntax, built-in functions, and CLI commands.

- :material-chip: **[VVM Specification](VVM_SPEC.md)** — the Virtual
  Machine architecture, bytecode format, and garbage collector.

- :material-arrow-decision: **[Concurrency](CONCURRENCY.md)** — the design
  of `go` / `wait` and how tasks work across all four engines.

</div>

## Running through the Virtual Machine

```bash
# Compile to bytecode
vidyax bytecode program.vx

# Run with the C VM
./vm/vxvm program.vxc
```

The output is identical to `vidyax run program.vx`, but it runs on a
self-built C runtime — not on top of Python.

---

<small>Built by **NaDev** · from a student's hands, for students.</small>
