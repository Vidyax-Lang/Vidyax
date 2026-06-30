# Vidyax — v1.3se 

> Named after the Sanskrit word *vidyā* (विद्या) — "knowledge".

> "Code as simple as writing instructions."

A programming language with English keywords, designed AI-first.
Working core: lexer -> parser -> (tree-walker **and** a Python transpiler for speed).

## Install (make `vax` a real command)

```bash
bash install.sh
vidyax contoh/main.vx     # run with the command
./contoh/main.vx       # run directly (shebang + chmod +x)
```

Without installing: `python vidyax.py contoh/main.vx`

## Usage

```bash
vax                    # start the interactive REPL (type code live)
vidyax <file.vx>          # run (FAST: compiles to Python, then runs)
vidyax run <file.vx>      # same
vidyax build <file.vx>    # compile to a standalone <file>.py you can ship
vidyax walk <file.vx>     # run with the tree-walker (slower; for debugging)
vidyax test               # run built-in tests
```

## Speed

Vidyax runs by transpiling to Python and executing natively, instead of walking
the syntax tree. On a recursive `fib(27)` + a 300k-iteration loop:

| Mode         | Time     |
|--------------|----------|
| Tree-walker  | ~5100 ms |
| Transpiled   | ~158 ms  |
| **Speedup**  | **~32x** |

`vidyax build file.vx` emits a clean, portable `file.py` that runs with plain
`python3` anywhere — no Vidyax needed on the target machine.

## What works in v0.1

| Feature      | Example                              |
|--------------|--------------------------------------|
| Print        | print "Hello"                        |
| Variables    | name: "Daffa"                        |
| Input        | name: ask "Who are you?"             |
| Operators    | + - * / %  == != < > <= >=           |
| Logic        | and  or  not                         |
| Conditionals | if / elif / else                     |
| Loops        | rpt 3:  and  for x in list:          |
| Loop control | break, continue                      |
| Error handling | try: ... catch e: ... (e = teks error)    |
| Functions    | func add(a, b): + return             |
| Types        | number, text, true/false, null, list [...] |
| Built-in AI  | use ai -> ai.ask "..."               |
| Built-ins    | len, range, text, num, upper, lower, split, join, push, abs, sum, min, max, type, get |
| HTTP         | get(url) -> fetches a URL, returns text (or an ERROR_ string on failure) |
| REPL         | run `vax` with no file to type code live |

### Enabling AI (ai.ask)

```bash
export GROQ_API_KEY=gsk_xxx
export VIDYAX_MODEL=llama-3.3-70b-versatile   # optional
vidyax contoh/ai.vx
```

## Roadmap (NOT runnable yet — stubbed on purpose)

agent, go, use web, use database, vidyax fmt, vax install.

## Layout

```
vidyax.py         # interpreter + transpiler + CLI (single file)
install.sh        # installs the `vax` command
tests.py          # built-in tests
contoh/
  main.vx         # full demo
  interactive.vx  # input + recursion
  ai.vx           # AI demo
  fungsi.vx       # functions + recursion
  builtin.vx      # built-in functions
  web.vx          # HTTP get(url) demo
```

## Design notes

- Blocks use space indentation (Python-style). No TAB.
- ':' is used for assignment (x: 5) and to open a block (if ...:); the parser tells them apart by context.
- Method calls may omit parentheses for a single argument: ai.ask "...".
- One-line blocks are allowed: `if x > 0: print "yes"` and `func sq(n): return n * n`. Great for the REPL.
- The transpiler reuses the same lexer/parser; the tree-walker stays for debugging and reference.
