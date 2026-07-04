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

- **Three engines, one behavior.** The tree-walker (Python), the
  transpiler (Python), and the Virtual Machine (C) run the same program
  with **identical** results — guaranteed by differential testing.
- **Its own Virtual Machine.** Written in C, with a mark-sweep garbage
  collector, bytecode verification, and sandbox limits (instructions,
  memory, time).
- **Friendly error messages.** Every error is explained in plain
  language, worded identically across all three engines.
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
