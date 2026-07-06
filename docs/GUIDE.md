# Vidyax Guide

> Learn Vidyax from scratch through examples. For the complete details of
> every feature, see [REFERENCE.md](./REFERENCE.md).

Vidyax (`.vx`) is a programming language built so that writing code feels
like writing plain instructions. Its philosophy: *"Code as simple as
writing instructions."*

---

## 0. Running a program

Save your code to a `.vx` file, then:

```bash
vidyax run hello.vx      # the main way to run a program
```

If you haven't installed the `vidyax` command yet, run it directly
through Python:

```bash
python3 vidyax.py run hello.vx
```

---

## 1. Hello world

```vidyax
print "Hello, world!"
```

`print` displays something on the screen. Text is written between double
quotes.

---

## 2. Variables

A colon (`:`) is used to assign a value to a variable — not an equals
sign.

```vidyax
name: "Daf"
age: 21
print "Hello " + name
```

Built-in names (like `len`, `get`, `print`) cannot be used as variable
names — Vidyax rejects that to avoid confusion.

---

## 3. Numbers and text

```vidyax
print 10 + 5         # 15
print 10 / 4         # 2.5
print "a" + "b"      # ab
print "age: " + 21   # age: 21  (numbers become text when joined)
```

`+` concatenates text **and** adds numbers. If one side is text, the
other side becomes text too.

---

## 4. Conditionals (if / elif / else)

Blocks are marked with indentation, similar to Python.

```vidyax
score: 75

if score >= 90:
    print "A"
elif score >= 70:
    print "B"
else:
    print "C"
```

Logical operators: `and`, `or`, `not`.

```vidyax
if age >= 17 and not false:
    print "allowed"
```

---

## 5. Loops

**`rpt N`** — repeat N times:

```vidyax
rpt 3:
    print "repeat"
```

**`for x in ...`** — iterate over each item in a list or each character
in text:

```vidyax
fruits: ["apple", "mango", "orange"]
for f in fruits:
    print f

for letter in "abc":
    print letter
```

**`break`** exits the loop, **`continue`** jumps to the next iteration:

```vidyax
for i in [1, 2, 3, 4, 5]:
    if i == 4:
        break
    if i == 2:
        continue
    print i
# output: 1, then 3
```

---

## 6. Functions

```vidyax
func add(a, b):
    return a + b

print add(10, 20)   # 30
```

Functions can call themselves (recursion):

```vidyax
func factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print factorial(5)   # 120
```

### Variable rules inside functions (important)

A variable you **assign inside a function is local** — it only lives in
that function and does not leak outside. This is the same as most other
languages.

```vidyax
x: 1

func change():
    x: 5       # this is a LOCAL x, not the outer x
    return x

print change()   # 5
print x          # 1  (the outer x is unchanged)
```

You can still **read** an outer variable as long as you don't overwrite
it:

```vidyax
factor: 10

func multiply(n):
    return n * factor   # reading 'factor' from outside — allowed

print multiply(3)   # 30
```

If you need to change a value for use outside, return it with `return` —
don't rely on globals.

---

## 7. Handling errors (try / catch)

If an operation might fail, wrap it in `try` / `catch` so the program
doesn't stop abruptly.

```vidyax
try:
    result: 10 / 0
catch e:
    print "caught: " + e   # caught: cannot divide by 0
```

`catch` can omit the variable if you don't need the message:

```vidyax
try:
    print ghostThing
catch:
    print "something went wrong, but the program continues"
```

---

## 8. Input from the user

`ask` reads one line of input from the user:

```vidyax
name: ask "What is your name?"
print "Hello, " + name
```

---

## 9. Fetching data from the internet: `get`

`get(url)` fetches the contents of a URL as text. If it fails (no
connection, wrong URL, server error), `get` **raises a catchable
error** — so always wrap it in `try` / `catch`.

```vidyax
try:
    quote: get("https://api.github.com/zen")
    print quote
catch e:
    print "failed to fetch: " + e
```

> Change in v1.1: `get` used to return text starting with `"ERROR_..."`
> on failure. It now raises an error like any other operation. Old
> programs that checked for `"ERROR_"` need to switch to `try`/`catch`.

---

## 10. Built-in AI

Vidyax has a built-in `ai` module. Enable it with `use ai`, then ask
questions with `ai.ask`.

```vidyax
use ai
ai.system "answer briefly and casually"
answer: ai.ask "What is a computer?"
print answer
```

Default model: `llama-3.1-8b-instant` (via Groq). You can change the
model or provider:

```vidyax
ai.open "llama-3.1-8b-instant"       # change model (still Groq)
ai.open "openai:gpt-4o-mini"         # change provider + model
```

Each provider needs its own API key in the environment:

```bash
export GROQ_API_KEY=gsk_xxxxx
export OPENAI_API_KEY=sk_xxxxx
```

### Agents: AI with a persona and a memory

For anything conversational, declare an **agent** — a named AI persona
that remembers its conversation:

```vidyax
agent guru:
    system "kamu guru fisika, jawab singkat"

print guru("apa itu gravitasi?")
print guru("jelaskan lebih sederhana")  # it remembers the topic!
```

Each agent keeps its own history, so two agents can even talk to each
other (see `contoh/agen.vx`). Agents work with `go`/`wait` too — but
remember: one agent is one conversation, so run *different* agents in
parallel, not the same one.

### Sandboxing an agent's work zone

Agent replies are just text — but if *your code* acts on a bad reply
(hallucination, prompt injection), damage happens where the code has
authority. Wrap each agent's work zone in a `sandbox` so it can't:

```vidyax
sandbox deny fs:              # this zone can use AI, but never files
    karya: penulis("...")
    ...process karya...
writefile("hasil.txt", hasil) # only the main scope writes
```

Denied things raise a normal catchable error; permissions come back the
moment the block ends. See `contoh/sekat.vx` for a full example.

---

## 11. Working with lists and text

Lists hold a series of values. Vidyax gives you a full set of tools to
build and reshape them:

```vidyax
nums: [3, 1, 2]
push(nums, 4)          # [3, 1, 2, 4] — add to the end
sort(nums)             # [1, 2, 3, 4] — sort in place
print reverse(nums)    # [4, 3, 2, 1]
print pop(nums)        # 4  (removes and returns the last item)
print find(nums, 2)    # 1  (index of the value, or -1 if absent)
print slice(nums, 0, 2)# [1, 2]  (a copy of items 0..1)
print contains(nums, 3)# true
```

Text has matching tools:

```vidyax
print upper("halo")               # HALO
print replace("a-b-c", "-", " ")  # a b c
print split("a,b,c", ",")         # [a, b, c]
print join(["x", "y"], "-")       # x-y
print trim("  spasi  ")           # spasi
print startswith("vidyax", "vid") # true
```

And numbers:

```vidyax
print round(3.14159, 2)   # 3.14
print sqrt(16)            # 4
print floor(3.7)         # 3
print random(1, 6)       # a dice roll
```

See [REFERENCE.md](./REFERENCE.md) for the complete list.

---

## 12. Splitting code into files (`use`)

When a program grows, move reusable code into its own `.vx` file and
pull it in with `use`. Say you have `mathx.vx`:

```vidyax
# mathx.vx
func kuadrat(n):
    return n * n
```

Then any program in the same folder (or in a `vx_modules/` subfolder)
can use it:

```vidyax
use mathx
print kuadrat(9)   # 81
```

A module is loaded once even if several files `use` it, and Vidyax
catches circular `use`. To grab a module someone published on GitHub:

```bash
vidyax install user/repo        # downloads it into vx_modules/
```

---

## 13. Doing things at the same time (`go` / `wait`)

Normally each line waits for the one before it. But when you're waiting
on something slow — the network, an AI model — you can run several at
once with `go`:

```vidyax
use ai

t1: go ai.ask "Explain gravity in one sentence"
t2: go ai.ask "Explain photosynthesis in one sentence"

print wait(t1)   # both questions were sent at the SAME time,
print wait(t2)   # so this finishes in ~1 answer's worth of time
```

`go f(x)` starts a **task** and returns immediately; `wait(t)` gives you
its result (and re-raises its error, catchable with try/catch). Pure
calculation never overlaps, so you never get tangled results — tasks
only interleave while waiting on input/output. A program without `go`
behaves exactly as before.

---

## 14. Going faster: bytecode and native

`vidyax run` is plenty fast for most things. When you need more speed,
Vidyax can compile your program down two more steps:

```bash
vidyax bytecode program.vx      # -> program.vxc, run with ./vm/vxvm
vidyax native   program.vx      # -> a standalone binary, no Python needed
```

The native binary is the fastest option and needs no runtime installed —
handy for sharing a finished tool. All of these run your program with
identical results; that sameness is enforced by the test suite.

Other handy commands while developing:

```bash
vidyax debug   program.vx       # step through line by line
vidyax profile program.vx       # see which lines are hot
```

---

## Next

- [REFERENCE.md](./REFERENCE.md) — the complete list of all syntax,
  built-in functions, CLI commands, and error messages.
- The `contoh/` folder in the repo — example programs you can run
  directly (a guessing game, a word counter, a note keeper, and more).

If you write the same program, every engine — `vidyax run`, `vidyax
walk`, the bytecode VM, and a native binary — produces identical
results. This is guaranteed by the built-in tests (`vidyax test`).
