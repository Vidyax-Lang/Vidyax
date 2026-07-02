# Vidyax — v1.1

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

## What works in v1.1

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
| HTTP         | get(url) -> fetches a URL, returns text (raises a catchable error on failure — use try/catch) |
| REPL         | run `vax` with no file to type code live |

## AI Features (BYOK — Bring Your Own Key)

Vidyax uses a **BYOK** model: you use your own API key. Vidyax never stores or uses anyone else's key. Free & secure.

### 1. Get an API Key

**Groq (free, recommended to start):**
- Go to https://console.groq.com/keys
- Log in, click **Create API Key**, and copy it (looks like `gsk_...`)

**OpenAI (optional):**
- Go to https://platform.openai.com/api-keys
- Create a key (looks like `sk-...`)

### 2. Set Your API Key

**Temporary (lost when the terminal closes):**
```bash
export GROQ_API_KEY=gsk_xxxxxxxx
```

**Permanent (recommended):**
```bash
echo 'export GROQ_API_KEY=gsk_xxxxxxxx' >> ~/.bashrc
source ~/.bashrc
```

### 3. Use It in Code

**Groq (default):**
```
use ai
ai.open "llama-3.1-8b-instant"
answer: ai.ask "List 3 benefits of exercise"
print answer
```

**Choose another provider with a `provider:model` prefix:**
```
ai.open "groq:llama-3.1-8b-instant"
ai.open "openai:gpt-4o-mini"
```
Without a prefix, Vidyax defaults to Groq.

> **Note:** Each provider needs its own environment key — `GROQ_API_KEY` for Groq, `OPENAI_API_KEY` for OpenAI. Groq model list: https://console.groq.com/docs/models. If you get a 403 error, the model is usually not available for your account; try `llama-3.1-8b-instant`.

## What changed in v1.1

One runtime, two engines. The tree-walker (`vidyax walk`) and the transpiler
(`vidyax run`) now share the exact same runtime helpers, so programs behave
identically on both — enforced by differential tests (`vidyax test` runs
every case on both engines and requires the outputs to match).

- `ai` module unified: `provider:model` routing now works on the default
  `run` path too, same default model everywhere (`llama-3.1-8b-instant`).
- **Breaking:** `get(url)` now raises a catchable error on failure instead
  of returning an `"ERROR_..."` string. Wrap it in `try/catch`.
- Scoping rule made explicit: a variable assigned anywhere inside a function
  is local to that function. Reading it before it has a value is a clear
  error (same message on both engines) instead of a crash.
- Built-in names (`len`, `get`, ...) are reserved — shadowing them is a
  parse error.
- `break`/`continue`/`return` outside a loop/function fail at parse time.
- Python internals (`__class__`, anything `_`-prefixed) are no longer
  reachable from transpiled programs.

## Roadmap (NOT runnable yet — stubbed on purpose)

agent, go, use web, use database, vidyax fmt, vax install.

## Layout

```
vidyax.py         # interpreter + transpiler + CLI (single file)
install.sh        # installs the `vax` command
tests.py          # differential tests (every case runs on BOTH engines)
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
