# Vidyax Concurrency — Design Document (v1 draft)

Status: **all phases shipped (A-E)** — `go`/`wait` and `agent` run on
all FOUR engines (walker, fast, VVM, native).

## 1. Goals and hard constraints

1. **Four-engine parity.** Everything observable must behave the same on
   the tree-walker, the transpiler, the VVM, and the native backend —
   the differential suite and the fuzzer are the project's backbone and
   concurrency must not break them.
2. **Beginner-first.** One new concept, not five. No locks, no channels,
   no `async`-colored functions in v1.
3. **AI-native payoff.** The killer use case is overlapping slow I/O:
   several `ai.ask` / `get()` calls at once. Pure-compute parallelism is
   NOT a goal (it would demand a thread-safe GC and buy a beginner
   language little).

## 2. Models considered

| Model | Verdict | Why |
|---|---|---|
| Free-running OS threads | **rejected** | data races reach the user; GC and both Python engines can't match C semantics — parity impossible |
| async/await event loop | **rejected** | colors every function; two dialects of the language; hardest to teach |
| actor/message passing | **rejected (v1)** | strongest model, but needs channels + serialization — too much surface for v1 |
| **tasks + one interpreter lock, I/O releases it** | **chosen** | exactly Python's GIL model, so the Python engines get it for free; C engines replicate it with one mutex |

## 3. The chosen design: `go` / `wait`

```vidyax
func tanya(topik):
    return ai.ask "jelaskan " + topik

t1: go tanya("gravitasi")     # starts a task, returns immediately
t2: go tanya("fotosintesis")  # runs concurrently with t1
print wait(t1)                # result of t1 (blocks until done)
print wait(t2)
```

- **`go f(args)`** — prefix keyword, valid only in front of a call.
  Arguments are evaluated eagerly in the caller (same order as a normal
  call), then the call itself runs as a **task**. `go` yields a value of
  the new type `"task"`.
- **`wait(t)`** — a builtin, not a keyword (no new grammar). Returns the
  task's result; if the task raised, **the same error re-raises at the
  `wait` site** and is catchable with try/catch there.
- **Execution model:** one global interpreter lock. A task only runs
  while holding it; the lock is **released only inside blocking
  builtins** — `get`, `ai.ask`, `readfile`, `writefile`, `sleep`, `ask`.
  Consequences, in beginner terms:
  - pure computation never interleaves → **no data races, ever**;
  - overlap happens exactly where it pays: waiting on the network/disk;
  - a program with no `go` behaves byte-for-byte as today.
- **Program exit:** the main task implicitly `wait`s every still-running
  task; an error in a never-waited task is reported like an uncaught
  top-level error (nothing is silently lost).
- `type(t)` is `"task"`; printing a task shows `<task f>`. Tasks are not
  lists/text — passing one to other builtins is a type error.

## 4. Per-engine implementation sketch

| Engine | Mechanism |
|---|---|
| walker + fast | `threading.Thread` — CPython's GIL **is** the model; `wait` = `join` + re-raise |
| VVM | the big refactor: today the VM state (stack/frames/handlers) is global; it must move into a `VmCtx` struct so each task owns one. One global `pthread_mutex`; blocking builtins wrap their syscall in unlock/lock. GC: stop-the-world while holding the lock; roots = every ctx's stack+frames |
| native | same `VmCtx` + mutex; `go` at a call site spawns a pthread running the callee's `np_K` with a fresh ctx |

Honest cost estimate: the Python engines are days; the `VmCtx`
refactor is the single biggest change the VM has seen — it touches
gc.c, vm.c, debug.c, profile.c and the generated native code, and it is
the reason this document exists before any code.

## 5. Testing strategy

- Deterministic subset for the suite: tasks that don't overlap I/O
  (compute-only, or a single task) must produce identical output on all
  engines — these go into tests.py as usual.
- Ordering-free assertions for real overlap: run N tasks appending to a
  list, assert on the SORTED result.
- The fuzzer keeps excluding `go` (nondeterministic interleaving can't
  be diffed byte-for-byte); a separate `fuzz_tasks.py` can fuzz the
  deterministic subset.

## 6. Phases

- **A (done):** `sleep(secs)` + `now()` builtins on every engine.
- **B (done):** `go`/`wait` on walker + fast, differential tests for the
  deterministic subset.
- **C (done):** the `VmCtx` refactor — execution state moved into a
  per-task context (macro-aliased through the thread-local `vx_ctx`, so
  the dispatch loop reads unchanged); one `vx_gil` mutex, released only
  inside blocking builtins; GC roots iterate every live context; byte
  accounting is atomic; `OP_GO` + `vm/task.c`. Verified with the full
  suite under --gc-stress, ASan, AND ThreadSanitizer.
- **D (done):** native backend — task.c became engine-agnostic via a
  `vx_task_runner` hook (VM: bytecode loop; native: the compiled NFN[]
  call); `ntry` went thread-local. Verified under ThreadSanitizer.
- **E (done):** the `agent` keyword — `agent name:` declares a stateful
  AI persona (`model`/`system` fixed at declaration, conversation history
  per agent). Lives in the shared runtime (`_Agent`) for the Python
  engines and as `OAgent` + `OP_AGENT` in the C engines; callable like a
  function and compatible with `go`/`wait`. Rule of thumb documented:
  one agent = one conversation; parallelize with several agents.

## 7. Decisions (signed off by the language owner, 6 Jul 2026)

1. **`wait(t)` is a builtin** — zero new grammar.
2. **`go` accepts builtin calls too** (`go get(url)`) — that IS the main
   use case.
3. **No timeout in v1** — `wait(t, max_secs)` and task cancellation are
   v2 questions.

Status: design APPROVED; **all phases (A-E) shipped**.
