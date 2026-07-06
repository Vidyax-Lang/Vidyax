# Vidyax Language Reference (v1.1)

This document lists all of Vidyax's syntax, types, built-in functions,
CLI commands, and error messages. To learn from scratch, see
[GUIDE.md](./GUIDE.md).

---

## Execution model

Vidyax has **two execution engines that share one runtime**:

| Command       | Engine               | Notes |
|---------------|----------------------|-------|
| `vidyax run`  | transpiler → Python  | the main path; translates `.vx` to Python, then runs it |
| `vidyax walk` | tree-walker          | interprets the syntax tree directly; useful for debugging/comparison |

Both call the same runtime helpers, so their results are identical by
construction. This is tested automatically: `vidyax test` runs every case
on **both** engines and requires the output to match exactly.

There is also a third engine — the **C Virtual Machine** (see
[VVM_SPEC.md](./VVM_SPEC.md)) — validated against these two with the same
test suite.

---

## Basic syntax

- One statement per line. No semicolons.
- Blocks are marked by **indentation** (spaces), like Python.
- Comments start with `#` and run to the end of the line.

```vidyax
# this is a comment
print "hello"
```

---

## Value types

| Type    | Example literal         | Notes |
|---------|-------------------------|-------|
| number  | `42`, `3.14`, `-7`      | integers & decimals used together |
| text    | `"hello"`               | double quotes |
| boolean | `true`, `false`         |       |
| empty   | `null`                  | absence of a value |
| list    | `[1, 2, 3]`, `["a","b"]`| may mix types |

`type(x)` returns the type name as text: `"number"`, `"text"`, `"bool"`,
`"null"`, or `"list"`.

---

## Variables

```vidyax
name: value
```

- Assignment uses `:` (not `=`).
- Built-in function names are **forbidden** as variable names, function
  names, parameters, loop variables, or `catch` variables. This avoids
  cross-engine mismatches and is caught early by `vidyax check`.
- **Scoping rule:** a name assigned inside a function is **local** to
  that function. Reading a local variable before it has a value is an
  error. Reading a name never assigned locally falls through to the outer
  scope (so you can read globals).

---

## Operators

**Arithmetic:** `+`  `-`  `*`  `/`  `%`

- `+` concatenates text as well as adding numbers. If one side is text,
  the other is converted to text automatically.
- `+` also joins two lists.
- `/` always produces a decimal; division by zero raises
  `cannot divide by 0`.

**Comparison:** `==`  `!=`  `<`  `<=`  `>`  `>=` → produce booleans.

**Logic:** `and`  `or`  `not`.

**Index:** `list[i]` or `text[i]`, counting from 0. Out-of-range index
raises `index out of range`.

**Member access:** `object.member`. Only Vidyax runtime modules (namely
`ai`) have members. Underscore-prefixed members (`_`) cannot be accessed
(this prevents leaking Python internals).

---

## Conditionals

```vidyax
if condition:
    ...
elif other_condition:
    ...
else:
    ...
```

`elif` and `else` are optional. A value is considered "true" when: the
boolean `true`, a non-zero number, or a non-empty text/list.

---

## Loops

**Repeat N times** — `N` must be a number (otherwise →
`'rpt' needs a number`):

```vidyax
rpt N:
    ...
```

**Iterate a list or text** — the source must be a list/text (otherwise →
`'for ... in' needs a list or text`):

```vidyax
for item in source:
    ...
```

**Loop control:**

- `break` — exit the loop.
- `continue` — skip to the next iteration.

`break`/`continue` outside a loop is a *parse-time* error
(`'break' only works inside a loop`). A `break` inside a function cannot
target a loop outside that function.

---

## Functions

```vidyax
func name(p1, p2):
    ...
    return value
```

- `return` may omit a value (returning `null`), or return a value.
- `return` outside a function is a parse-time error
  (`'return' only works inside a function`).
- The number of arguments must match the number of parameters; otherwise
  → `function 'name' needs N args, got M`.
- Recursive functions are supported.

---

## Error handling

```vidyax
try:
    ...
catch e:      # 'e' holds the error message as text
    ...
```

The `catch` variable is optional:

```vidyax
try:
    ...
catch:
    ...
```

All runtime errors (division by zero, out-of-range index, `get` failure,
etc.) can be caught. Error messages are identical across both execution
engines.

---

## Input

```vidyax
ask "prompt"
```

Displays the prompt and reads one line of user input as text.

```vidyax
age: ask "How old are you?"
```

---

## Built-in functions

| Function            | Result |
|---------------------|--------|
| `len(x)`            | length of a text or list |
| `range(n)`          | list `[0, 1, ..., n-1]` |
| `range(a, b)`       | list `[a, ..., b-1]` |
| `text(x)`           | convert a value to text |
| `num(x)`            | convert text/value to a number |
| `upper(s)`          | text to UPPERCASE |
| `lower(s)`          | text to lowercase |
| `split(s, sep=" ")` | split text into a list by a separator |
| `join(lst, sep="")` | join a list into text with a separator |
| `push(lst, x)`      | append `x` to the end of a list |
| `abs(x)`            | absolute value |
| `sum(x)`            | sum of all items in a list |
| `min(...)`          | smallest value |
| `max(...)`          | largest value |
| `type(x)`           | type name as text |
| `get(url)`          | fetch a URL's contents as text (raises on failure) |
| `readfile(path)`    | read a text file's contents (raises on failure) |
| `writefile(path, x)`| write `x` (as text) to a file, replacing it |
| `floor(x)`          | round down to a whole number |
| `ceil(x)`           | round up to a whole number |
| `round(x)`          | round to the nearest whole number (half away from zero) |
| `round(x, digits)`  | round to `digits` decimal places |
| `sqrt(x)`           | square root (`x` must be ≥ 0) |
| `pow(x, y)`         | `x` raised to the power `y` |
| `random()`          | random number ≥ 0 and < 1 |
| `random(a, b)`      | random whole number from `a` to `b` (inclusive) |
| `replace(s, old, new)` | replace every `old` in `s` with `new` |
| `trim(s)`           | remove spaces/tabs/newlines from both ends |
| `contains(x, item)` | true if list `x` has `item`, or text `x` has that substring |
| `startswith(s, p)`  | true if text `s` starts with `p` |
| `endswith(s, p)`    | true if text `s` ends with `p` |
| `pop(lst)` / `pop(lst, i)` | remove & return the last item (or item `i`) |
| `remove(lst, x)`    | remove the first `x` from the list (raises if absent) |
| `insert(lst, i, x)` | insert `x` at position `i` (out-of-range goes to an end) |
| `sort(lst)`         | sort the list in place (items must be the same type) |
| `reverse(lst)`      | reverse the list in place |
| `find(x, item)`     | first index of `item` in a list/text, `-1` if absent |
| `slice(x, a, b)`    | copy of items `a..b-1` of a list/text (negatives count from the end) |
| `sleep(secs)`       | pause for that many seconds |
| `now()`             | current time in epoch seconds (for measuring durations) |
| `wait(t)`           | result of a task made with `go` (re-raises its error here) |

### Tasks (`go` / `wait`)

```vidyax
t1: go ai.ask "jelaskan gravitasi"     # starts a task, returns immediately
t2: go get("https://example.com")      # runs concurrently with t1
print wait(t1)                         # blocks until t1 finishes
print wait(t2)
```

`go f(args)` runs a call as a concurrent **task** (a value of type
`"task"`). Arguments are evaluated eagerly in the caller. Tasks
interleave **only while waiting on I/O** (`get`, `ai.ask`, files,
`sleep`) — pure computation never interleaves, so data races are
impossible. An error inside a task re-raises at its `wait(t)` (catchable
with try/catch); a failed task nobody waited for is reported when the
program ends. Design + roadmap: `docs/CONCURRENCY.md`. Runs on ALL four
engines: the default engine, the walker, the VVM, and native binaries.

The names above are *reserved* — they cannot be overwritten.

> On the VVM (`vidyax bytecode` + `vxvm`), `get()` needs `--allow-net`
> and `readfile()`/`writefile()` need `--allow-fs` — both are denied by
> default in the sandbox.

---

## The `ai` module

Enable it with `use ai`. The `ai` object appears in the program's scope.

| Member             | Function |
|--------------------|----------|
| `ai.ask "..."`     | send a prompt, return the answer as text |
| `ai.system "..."`  | set a system instruction (persona/rules) |
| `ai.open "..."`    | change the model or provider |
| `ai.model`         | the active model name |
| `ai.provider`      | the active provider name (`groq` / `openai`) |
| `ai.system_prompt` | the active system instruction |

**`ai.open` format:**

- `ai.open "model-name"` — change model, keep provider.
- `ai.open "provider:model"` — change both, e.g. `"openai:gpt-4o-mini"`.

Default: provider `groq`, model `llama-3.1-8b-instant`. Can be overridden
via the `VIDYAX_MODEL` environment variable.

**API keys** (per provider):

| Provider | Environment      | URL |
|----------|------------------|-----|
| groq     | `GROQ_API_KEY`   | api.groq.com |
| openai   | `OPENAI_API_KEY` | api.openai.com |

Unknown provider → `unknown AI provider`. Key not set → a message naming
the required environment variable.

---

## CLI commands

| Command                  | Function |
|--------------------------|----------|
| `vidyax run <file.vx>`   | run a program (transpiler path; default) |
| `vidyax walk <file.vx>`  | run through the tree-walker |
| `vidyax build <file.vx>` | translate to a standalone Python `.py` file |
| `vidyax bytecode <file.vx>` | compile to VVM bytecode `.vxc` |
| `vidyax disasm <file.vxc>` | disassemble VVM bytecode (also accepts a `.vx`) |
| `vidyax debug <file.vx>`  | run under the VVM line debugger (`b`/`c`/`s`/`n`/`bt`/`locals`) |
| `vidyax profile <file.vx>` | run on the VVM + per-function/per-line instruction profile |
| `vidyax native <file.vx> [-o out]` | compile to a standalone native binary (needs a C compiler) |
| `vidyax check <file.vx>` | static check only, output errors as JSON (`-` = stdin) |
| `vidyax lsp`             | start the Language Server Protocol server (stdio) |
| `vidyax test`            | run the built-in tests (both engines) |
| `vidyax <file.vx>`       | same as `run` |

Running with no arguments opens the interactive REPL:

- A line that opens a block (`if x:`, `func f():`, `try:`, …) switches to
  the `... ` continuation prompt; keep typing the block's lines.
- A **blank line** runs the block — unless it is still unfinished (a
  `try:` waits for its `catch:` before running).
- A bare expression echoes its value, like a calculator.
- **Ctrl-C** cancels a half-typed block or stops a running program
  without leaving the REPL; **Ctrl-D** exits.

Roadmap commands (recognized but not yet runnable): `fmt`, `install`, and
the keywords `agent`, `go`, `use web`, `use database`.

### Language Server (`vidyax lsp`)

A dependency-free LSP server over stdio for any LSP-capable editor:
live **diagnostics** (same errors as `vidyax check`), **completion**
(keywords, all builtins with docs, names defined in the file), **hover**
docs for builtins, and **document symbols** (outline). Example client
config for Neovim 0.11+:

```lua
vim.lsp.config['vidyax'] = { cmd = { 'vidyax', 'lsp' }, filetypes = { 'vidyax' } }
vim.lsp.enable('vidyax')
```

---

## Error message catalog

| Message | Cause |
|---------|-------|
| `variable 'X' is not defined` | reading a variable that doesn't exist |
| `variable 'X' is assigned in this function but used before it has a value` | reading a local before it's assigned |
| `'X' is a built-in function name — pick a different name` | overwriting a built-in name |
| `cannot divide by 0` | division by zero |
| `index out of range` | list/text index out of bounds |
| `'rpt' needs a number` | `rpt` with a non-number value |
| `'for ... in' needs a list or text` | iterating a non-list/text source |
| `this is not a function` | calling a value that isn't a function |
| `function 'X' needs N args, got M` | wrong number of arguments |
| `member 'X' is private` | accessing an underscore-prefixed member |
| `object has no member 'X'` | accessing a member on a value with no members |
| `'ai' has no member 'X'` | unknown `ai` member |
| `unknown AI provider 'X'` | unknown AI provider |
| `'break' only works inside a loop` | `break`/`continue` outside a loop |
| `'return' only works inside a function` | `return` outside a function |
| `get() failed: ...` | `get(url)` failed (connection/HTTP) |

All messages are consistent between `run` and `walk`.

---

## Keywords (reserved words)

```
print  if  elif  else  rpt  for  in  func  return
ask  use  and  or  not  true  false  null
break  continue  try  catch
agent  go        # roadmap, not runnable yet
```
