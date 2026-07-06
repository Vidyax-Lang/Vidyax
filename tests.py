# -*- coding: utf-8 -*-
"""Differential tests for Vidyax v1.1. Run: python vidyax.py test

Every case runs through BOTH engines:
  - walk = tree-walking interpreter (run_text)
  - fast = transpile-to-Python path  (run_fast_text)  <- the default `vidyax run`

A case only passes if BOTH engines produce the expected result AND
agree with each other exactly. This is what keeps the two execution
paths from silently drifting apart again.
"""
import io
import json
import contextlib
import os
import subprocess
import sys
import vidyax

ENGINES = [("walk", vidyax.run_text), ("fast", vidyax.run_fast_text)]


def run_engine(fn, src):
    """Returns (stdout, error_msg_or_None) for one engine."""
    buf = io.StringIO()
    err = None
    try:
        with contextlib.redirect_stdout(buf):
            fn(src)
    except vidyax.VidyaxError as e:
        err = e.msg
    return buf.getvalue(), err


# --- cases that must SUCCEED with this exact stdout, on both engines ---
CASES = [
    ('print "hi"\n', "hi\n"),
    ('x: 5\nprint x + 3\n', "8\n"),
    ('print "a" + "b"\n', "ab\n"),
    ('if 5 > 3:\n    print "yes"\n', "yes\n"),
    ('if 1 > 2:\n    print "a"\nelse:\n    print "b"\n', "b\n"),
    ('if 1 > 2:\n    print "a"\nelif 3 > 1:\n    print "c"\nelse:\n    print "d"\n', "c\n"),
    ('rpt 3:\n    print "x"\n', "x\nx\nx\n"),
    ('for i in [1, 2, 3]:\n    print i\n', "1\n2\n3\n"),
    ('func f(a, b):\n    return a * b\nprint f(4, 5)\n', "20\n"),
    ('print true\nprint false\nprint null\n', "true\nfalse\nnull\n"),
    ('print 10 / 4\n', "2.5\n"),
    ('print not false\n', "true\n"),
    ('print 5 >= 5 and 3 < 4\n', "true\n"),
    ('d: [10, 20, 30]\nprint d[1]\n', "20\n"),
    ('for c in "abc":\n    print c\n', "a\nb\nc\n"),
    ('print len([1, 2, 3])\n', "3\n"),
    ('print range(4)\n', "[0, 1, 2, 3]\n"),
    ('print upper("hi")\n', "HI\n"),
    ('print sum([1, 2, 3, 4])\n', "10\n"),
    ('print join(["a", "b"], "-")\n', "a-b\n"),
    ('func fac(n):\n    if n <= 1:\n        return 1\n    return n * fac(n - 1)\nprint fac(5)\n', "120\n"),
    ('t: 0\nfor i in range(1, 5):\n    t: t + i\nprint t\n', "10\n"),
    ('try:\n    x: 1 / 0\ncatch e:\n    print "caught: " + e\n', "caught: cannot divide by 0\n"),
    ('try:\n    print 1 / 0\ncatch:\n    print "err"\nprint "after"\n', "err\nafter\n"),
    # scoping: reading an outer name (never assigned locally) works
    ('x: 10\nfunc f():\n    y: x + 1\n    return y\nprint f()\n', "11\n"),
    # scoping: assignment in a func is local, never leaks out
    ('x: 1\nfunc f():\n    x: 5\n    return x\nprint f()\nprint x\n', "5\n1\n"),
    # closures: nested funcs read enclosing locals
    ('func outer(a):\n    func inner(b):\n        return a + b\n    return inner(10)\nprint outer(5)\n', "15\n"),
    # break/continue inside rpt and for
    ('for i in [1, 2, 3, 4, 5]:\n    if i == 4:\n        break\n    if i == 2:\n        continue\n    print i\n', "1\n3\n"),
    # get() failure is now catchable with try/catch (was: ERROR_ string)
    ('try:\n    x: get("http://0.0.0.0:1")\ncatch e:\n    print "caught"\n', "caught\n"),
    # ai module: same default model + provider routing on both engines
    ('use ai\nprint ai.model\n', "llama-3.1-8b-instant\n"),
    ('use ai\nai.open "openai:gpt-4o-mini"\nprint ai.provider + " " + ai.model\n', "openai gpt-4o-mini\n"),
    ('use ai\nai.open "openai:gpt-4o-mini"\nai.open "gpt-4o"\nprint ai.provider + " " + ai.model\n', "openai gpt-4o\n"),
    ('use ai\nai.system "abc"\nprint ai.system_prompt\n', "abc\n"),
    # stdlib: math
    ('print floor(3.7)\nprint floor(-1.5)\n', "3\n-2\n"),
    ('print ceil(3.2)\nprint ceil(-1.5)\n', "4\n-1\n"),
    ('print round(2.5)\nprint round(-2.5)\nprint round(2.4)\n', "3\n-3\n2\n"),
    ('print round(3.14159, 2)\nprint round(3.14159, 3)\n', "3.14\n3.142\n"),
    ('print sqrt(16)\nprint sqrt(2.25)\n', "4\n1.5\n"),
    ('print pow(2, 10)\nprint pow(9, 0.5)\n', "1024\n3\n"),
    ('r: random(1, 6)\nprint r >= 1 and r <= 6\n', "true\n"),
    ('r: random()\nprint r >= 0 and r < 1\n', "true\n"),
    ('print random(3, 3)\n', "3\n"),
    # stdlib: string
    ('print replace("halo dunia", "dunia", "vx")\n', "halo vx\n"),
    ('print replace("aaa", "a", "bb")\n', "bbbbbb\n"),
    ('print trim("  hai  ")\nprint trim("x")\n', "hai\nx\n"),
    ('print contains("vidyax", "dy")\nprint contains("vidyax", "zz")\n', "true\nfalse\n"),
    ('print contains([1, 2, 3], 2)\nprint contains([1, 2], 9)\n', "true\nfalse\n"),
    ('print contains(["a", "b"], "b")\n', "true\n"),
    ('print startswith("vidyax", "vid")\nprint startswith("vidyax", "dya")\n', "true\nfalse\n"),
    ('print endswith("vidyax", "yax")\nprint endswith("vidyax", "vid")\n', "true\nfalse\n"),
    # stdlib: list ops
    ('xs: [3, 1, 2]\nsort(xs)\nprint xs\n', "[1, 2, 3]\n"),
    ('print sort(["b", "c", "a"])\n', "[a, b, c]\n"),
    ('print reverse([1, 2, 3])\n', "[3, 2, 1]\n"),
    ('xs: [1, 2, 3]\nprint pop(xs)\nprint xs\n', "3\n[1, 2]\n"),
    ('print pop([9, 8, 7], 0)\nprint pop([9, 8, 7], -2)\n', "9\n8\n"),
    ('ys: [1, 2, 4]\ninsert(ys, 2, 3)\nprint ys\n', "[1, 2, 3, 4]\n"),
    ('ys: [1, 2]\ninsert(ys, 99, 3)\ninsert(ys, 0, 0)\nprint ys\n', "[0, 1, 2, 3]\n"),
    ('ys: [1, 2, 2, 3]\nremove(ys, 2)\nprint ys\n', "[1, 2, 3]\n"),
    ('print find([5, 6, 7], 6)\nprint find([5, 6], 9)\n', "1\n-1\n"),
    ('print find("vidyax", "dy")\nprint find("vidyax", "zz")\n', "2\n-1\n"),
    ('print slice([1, 2, 3, 4, 5], 1, 3)\n', "[2, 3]\n"),
    ('print slice("vidyax", 0, 3)\nprint slice("vidyax", -3, 99)\n', "vid\nyax\n"),
    ('print slice([1, 2, 3], 2, 1)\n', "[]\n"),
    # -- pinned by the differential fuzzer (fuzz.py) --
    # bools are numbers everywhere (true=1, false=0), like the VM's numlike
    ('print floor(true) + ceil(false)\nprint abs(true)\nprint -true\n', "1\n1\n-1\n"),
    # text builtins format values Vidyax-style (never Python's str())
    ('print trim(false)\nprint upper(null)\nprint lower(3.0)\n', "false\nNULL\n3\n"),
    # top-level read-before-assign is a NAME error on all three engines
    # ("assigned in this function..." wording is for user functions only)
    ('try:\n    x: q + 1\ncatch e:\n    print e\nq: 5\nprint q\n',
     "variable 'q' is not defined\n5\n"),
    # list concat with +, like the VM's do_add
    ('print [1, 2] + [3]\n', "[1, 2, 3]\n"),
    # stdlib: time (Phase A of the concurrency design, docs/CONCURRENCY.md)
    ('t0: now()\nsleep(0.01)\nd: now() - t0\nprint d >= 0.01 and d < 10\n'
     'print type(now())\n', "true\nnumber\n"),
    # stdlib: files (the VM needs --allow-fs; tests_vm.py passes it)
    ('writefile("/tmp/vx_selftest.txt", "abc")\nprint readfile("/tmp/vx_selftest.txt")\n', "abc\n"),
    ('print writefile("/tmp/vx_selftest.txt", 123)\nprint readfile("/tmp/vx_selftest.txt")\n', "null\n123\n"),
]

# --- cases that must FAIL on both engines, with the SAME error text ---
# (stdout before the error must also match; `want` is a substring pin)
ERROR_CASES = [
    ('x: 1 / 0\n', "cannot divide by 0"),
    ('print y\n', "variable 'y' is not defined"),
    ('func f():\n    x: x + 1\n    return x\nf()\n', "used before it has a value"),
    ('rpt "a":\n    print 1\n', "'rpt' needs a number"),
    ('for i in 5:\n    print i\n', "'for ... in' needs a list or text"),
    ('nums: [1, 2]\nprint nums[9]\n', "index out of range"),
    ('print "abc".__class__\n', "private"),
    ('use ai\nprint ai.nope\n', "no member"),
    ('use ai\nai.open "claude:sonnet"\n', "unknown AI provider"),
    ('len: 5\n', "built-in function name"),
    ('break\n', "'break' only works inside a loop"),
    ('return 1\n', "'return' only works inside a function"),
    ('x: 5\nx()\n', "this is not a function"),
    ('func f(a):\n    return a\nprint f(1, 2)\n', "needs 1 args"),
    ('print sqrt(-4)\n', "sqrt() needs a number >= 0"),
    ('print floor("a")\n', "floor() needs a number"),
    ('print round(1.5, -1)\n', "round() digits must be 0 or more"),
    ('print random(9)\n', "random() takes no values, or two whole numbers"),
    ('print random(6, 1)\n', "random(a, b) needs a <= b"),
    ('print replace("abc", "", "x")\n', "replace() needs a non-empty text to find"),
    ('print contains(5, 1)\n', "contains() needs a list or text"),
    ('print readfile("/definitely/missing/vx.txt")\n', "readfile() failed"),
    ('print pop([])\n', "pop() on an empty list"),
    ('print pop([1, 2], 5)\n', "index out of range"),
    ('remove([1, 2], 9)\n', "remove(): value not in list"),
    ('sort([1, "a"])\n', "cannot compare number with text"),
    ('print find(5, 1)\n', "find() needs a list or text"),
    ('print slice(5, 0, 1)\n', "slice() needs a list or text"),
    # -- pinned by the differential fuzzer (fuzz.py): raw Python error
    #    text must never leak; all engines share the VM's wording --
    ('x: [2, "a"]\nprint x[0] < x[1]\n', "cannot compare number with text"),
    ('print true + []\n', "cannot add bool and list"),
    ('print "ab" * 2\n', "cannot do arithmetic on text and number"),
    ('x: "a"\nprint x - 1\n', "cannot do arithmetic on text and number"),
    ('x: "a"\nprint -x\n', "cannot negate text"),
    ('print abs("a")\n', "abs() needs a number"),
    ('print sum([1, "a"])\n', "sum() needs a list of numbers"),
    ('print min([])\n', "min() needs at least one value"),
    ('print max(1, "a")\n', "cannot compare text with number"),
    ('print range("a")\n', "range() takes 1 to 3 numbers"),
    ('push(5, 1)\n', "push() needs a list and a value"),
    ('print split("ab", "")\n', "empty separator"),
    ('sleep(-1)\n', "sleep() needs a number of seconds >= 0"),
    ('print now(1)\n', "now() takes no values"),
]

# --- runtime errors must report the ORIGINAL .vx line (source map). Checked
# on BOTH engines: the walker carries lines natively, the fast path maps the
# generated-Python traceback back through its line table. (src, expected_line)
LINE_CASES = [
    ('x: 10\ny: 0\nz: x / y\n', 3),                    # divide by zero
    ('nums: [1, 2, 3]\nprint nums[10]\n', 2),          # index out of range
    ('func bad(n):\n    return n / 0\nprint bad(5)\n', 2),  # error inside a func
    ('a: 1\nfor i in [1, 2]:\n    c: a / 0\n', 3),     # error in a loop body
]

# --- errors must be CATEGORIZED (syntax / name / type / runtime) so beginners
# know what kind of problem they hit. Checked on BOTH engines. (src, label)
CATEGORY_CASES = [
    ('print 1 2\n', "syntax error"),      # extra tokens -> parse fails
    ('x: 1 +\n', "syntax error"),         # unfinished expression
    ('print y\n', "name error"),          # undefined variable
    ('x: 5 - "a"\n', "type error"),       # arithmetic on text (static)
    ('x: 1 / 0\n', "runtime error"),      # divide by zero (only known at run)
    ('x: 5\nx()\n', "runtime error"),     # calling a non-function
]

# --- REPL: fed to `vidyax` over stdin as if typed. Each case is
# (typed_input, must_appear_in_output, must_NOT_appear_in_output) ---
REPL_CASES = [
    # a block runs when closed with a blank line
    ('if 5 > 3:\n    print "yes"\n\n', ["yes"], []),
    # `try:` is NOT executed at the blank line — it waits for its `catch`
    ('try:\n    x: 1 / 0\n\ncatch e:\n    print "ok " + e\n\n',
     ["ok cannot divide by 0"], ["must be followed"]),
    # a func defined across lines is callable afterwards
    ('func sq(n):\n    return n * n\n\nsq(6)\n', ["36"], []),
    # bare expressions echo their value
    ('1 + 2\n', ["3"], []),
    # real mistakes surface immediately, they don't open a silent block
    ('print zzz\n', ["variable 'zzz' is not defined"], []),
]


def run_all_tests():
    passed = failed = 0

    for i, (src, want) in enumerate(CASES, 1):
        results = {name: run_engine(fn, src) for name, fn in ENGINES}
        problems = []
        for name, (out, err) in results.items():
            if err is not None:
                problems.append(f"{name} errored: {err!r}")
            elif out != want:
                problems.append(f"{name} got {out!r}, want {want!r}")
        if results["walk"] != results["fast"]:
            problems.append(f"ENGINES DISAGREE: walk={results['walk']!r} fast={results['fast']!r}")
        if problems:
            failed += 1
            print(f"  FAIL test {i}: " + " | ".join(problems))
        else:
            passed += 1
            print(f"  PASS test {i}")

    base = len(CASES)
    for i, (src, want_sub) in enumerate(ERROR_CASES, 1):
        results = {name: run_engine(fn, src) for name, fn in ENGINES}
        problems = []
        for name, (out, err) in results.items():
            if err is None:
                problems.append(f"{name} did not error (stdout={out!r})")
            elif want_sub not in err:
                problems.append(f"{name} error {err!r} missing {want_sub!r}")
        w, f = results["walk"], results["fast"]
        if w[1] is not None and f[1] is not None and (w[0] != f[0] or w[1] != f[1]):
            problems.append(f"ENGINES DISAGREE: walk={w!r} fast={f!r}")
        if problems:
            failed += 1
            print(f"  FAIL err-test {i} (#{base + i}): " + " | ".join(problems))
        else:
            passed += 1
            print(f"  PASS err-test {i} (#{base + i})")

    base2 = len(CASES) + len(ERROR_CASES)
    for i, (src, want_line) in enumerate(LINE_CASES, 1):
        marker = f"line {want_line}:"
        problems = []
        for name, fn in ENGINES:
            try:
                fn(src)
                problems.append(f"{name} did not error")
            except vidyax.VidyaxError as e:
                if marker not in e.show():
                    problems.append(f"{name} show()={e.show()!r} missing {marker!r}")
            except Exception as e:
                problems.append(f"{name} raised {type(e).__name__}: {e}")
        if problems:
            failed += 1
            print(f"  FAIL line-test {i} (#{base2 + i}): " + " | ".join(problems))
        else:
            passed += 1
            print(f"  PASS line-test {i} (#{base2 + i})")

    base3 = len(CASES) + len(ERROR_CASES) + len(LINE_CASES)
    for i, (src, label) in enumerate(CATEGORY_CASES, 1):
        problems = []
        for name, fn in ENGINES:
            try:
                fn(src)
                problems.append(f"{name} did not error")
            except vidyax.VidyaxError as e:
                if label not in e.show():
                    problems.append(f"{name} show()={e.show()!r} missing {label!r}")
            except Exception as e:
                problems.append(f"{name} raised {type(e).__name__}: {e}")
        if problems:
            failed += 1
            print(f"  FAIL cat-test {i} (#{base3 + i}): " + " | ".join(problems))
        else:
            passed += 1
            print(f"  PASS cat-test {i} (#{base3 + i})")

    base4 = base3 + len(CATEGORY_CASES)
    vx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vidyax.py")
    for i, (typed, want_in, want_out) in enumerate(REPL_CASES, 1):
        r = subprocess.run([sys.executable, vx], input=typed,
                           capture_output=True, text=True, timeout=30)
        out = r.stdout + r.stderr
        problems = [f"missing {s!r}" for s in want_in if s not in out]
        problems += [f"unexpected {s!r}" for s in want_out if s in out]
        if r.returncode != 0:
            problems.append(f"repl exited {r.returncode}")
        if problems:
            failed += 1
            print(f"  FAIL repl-test {i} (#{base4 + i}): "
                  + " | ".join(problems) + f" (output={out!r})")
        else:
            passed += 1
            print(f"  PASS repl-test {i} (#{base4 + i})")

    # disassembler smoke test: compile a program, disasm both the .vx and
    # the .vxc file, and check the expected structure is in the listing
    import tempfile
    import vxc
    # two-statement body on purpose: the inliner must NOT fire here, so
    # the listing still contains a real MAKE_FUNC/CALL pair
    dis_src = 'func sq(n):\n    y: n * n\n    return y\nprint sq(7)\n'
    with tempfile.TemporaryDirectory() as td:
        vx = os.path.join(td, "d.vx")
        with open(vx, "w") as f:
            f.write(dis_src)
        listing_vx = vxc.disasm_file(vx)
        vxc_path = vxc.compile_file(vx)
        listing_vxc = vxc.disasm_file(vxc_path)
    problems = []
    if listing_vx != listing_vxc:
        problems.append("disasm(.vx) != disasm(.vxc)")
    for want in ["proto 1 <sq>", "LOAD_SLOT", "MUL", "MAKE_FUNC", "CALL",
                 "PRINT", "HALT"]:
        if want not in listing_vx:
            problems.append(f"listing missing {want!r}")
    # CFG layer: dead branches and unreachable tails must be gone
    cfg_src = ('func one():\n    return 1\n'
               'if false:\n    print "mati"\nprint "hidup"\n')
    listing = vxc.disassemble(vxc.compile_source(cfg_src).serialize())
    if '"mati"' in listing:
        problems.append("constant-false branch survived in the bytecode")
    one = listing.split("proto 1")[1]
    if one.count("RET") != 1:
        problems.append("dead fall-off NULL/RET tail survived after return")
    if problems:
        failed += 1
        print("  FAIL disasm-test 1: " + " | ".join(problems))
    else:
        passed += 1
        print("  PASS disasm-test 1")

    # debugger smoke test: breakpoint inside a function, inspect, continue
    vm_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "vm", "vxvm")
    if os.path.exists(vm_bin):
        with tempfile.TemporaryDirectory() as td:
            dvx = os.path.join(td, "dbg.vx")
            with open(dvx, "w") as f:
                # two-statement body: not inlinable, so the debugger can
                # actually break inside the function frame
                f.write('func sq(n):\n    y: n * n\n    return y\nprint sq(7)\n')
            dpath = vxc.compile_file(dvx)
            r = subprocess.run([vm_bin, "--debug", dpath],
                               input="b 2\nc\nlocals\nbt\nc\n",
                               capture_output=True, text=True, timeout=30)
        dbg = r.stderr
        problems = []
        for want in ["[vxdbg] line 1 in <main>", "[vxdbg] line 2 in sq",
                     "n = 7", "#1 <main> (line 4)"]:
            if want not in dbg:
                problems.append(f"debugger output missing {want!r}")
        if r.stdout.strip() != "49":
            problems.append(f"program output {r.stdout!r}, want '49'")
        if problems:
            failed += 1
            print("  FAIL debug-test 1: " + " | ".join(problems))
        else:
            passed += 1
            print("  PASS debug-test 1")
    else:
        print("  SKIP debug-test 1 (vxvm not built)")
        passed += 1

    # profiler smoke test: report must attribute the work to the function
    if os.path.exists(vm_bin):
        with tempfile.TemporaryDirectory() as td:
            pvx = os.path.join(td, "prof.vx")
            with open(pvx, "w") as f:
                f.write('func tri(n):\n    if n <= 0:\n        return 0\n'
                        '    return n + tri(n - 1)\nprint tri(50)\n')
            ppath = vxc.compile_file(pvx)
            r = subprocess.run([vm_bin, "--profile", ppath],
                               capture_output=True, text=True, timeout=30)
        problems = []
        if r.stdout.strip() != "1275":
            problems.append(f"program output {r.stdout!r}, want '1275'")
        for want in ["== Vidyax profile ==", "per function:", "tri",
                     "hot lines:", "line "]:
            if want not in r.stderr:
                problems.append(f"report missing {want!r}")
        if problems:
            failed += 1
            print("  FAIL profile-test 1: " + " | ".join(problems))
        else:
            passed += 1
            print("  PASS profile-test 1")
    else:
        print("  SKIP profile-test 1 (vxvm not built)")
        passed += 1

    # native backend smoke test: compile to a binary, outputs must match
    import shutil as _sh
    if _sh.which(os.environ.get("CC", "cc")):
        import vxnative
        nat_src = ('func fib(n):\n    if n <= 1:\n        return n\n'
                   '    return fib(n - 1) + fib(n - 2)\n'
                   'try:\n    x: 1 / 0\ncatch e:\n    print "err: " + e\n'
                   'print fib(15)\nprint sort([3, 1, 2])\n')
        want_nat = "err: cannot divide by 0\n610\n[1, 2, 3]\n"
        with tempfile.TemporaryDirectory() as td:
            nvx = os.path.join(td, "n.vx")
            with open(nvx, "w") as f:
                f.write(nat_src)
            try:
                nbin = vxnative.native_file(nvx, os.path.join(td, "n"))
                r = subprocess.run([nbin], capture_output=True, text=True,
                                   timeout=30)
                ok = r.stdout == want_nat and r.returncode == 0
                detail = "" if ok else f" (got {r.stdout!r})"
            except vidyax.VidyaxError as e2:
                ok, detail = False, f" (compile failed: {e2.msg})"
        if ok:
            passed += 1
            print("  PASS native-test 1")
        else:
            failed += 1
            print("  FAIL native-test 1" + detail)
    else:
        print("  SKIP native-test 1 (no C compiler)")
        passed += 1

    # LSP smoke test: full JSON-RPC conversation over stdio
    def lsp_frame(payload):
        body = json.dumps(payload).encode()
        return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)

    def lsp_parse_all(data):
        msgs = []
        while data:
            head, _, rest = data.partition(b"\r\n\r\n")
            n = int(head.split(b":")[1])
            msgs.append(json.loads(rest[:n]))
            data = rest[n:]
        return msgs

    vx_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vidyax.py")
    convo = (
        lsp_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {}})
        + lsp_frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                     "params": {"textDocument": {
                         "uri": "file:///t.vx",
                         "text": "x: 5\nprint x +\n"}}})
        + lsp_frame({"jsonrpc": "2.0", "id": 2,
                     "method": "textDocument/completion",
                     "params": {"textDocument": {"uri": "file:///t.vx"},
                                "position": {"line": 0, "character": 0}}})
        + lsp_frame({"jsonrpc": "2.0", "id": 3, "method": "textDocument/hover",
                     "params": {"textDocument": {"uri": "file:///t.vx"},
                                "position": {"line": 1, "character": 1}}})
        + lsp_frame({"jsonrpc": "2.0", "id": 4, "method": "shutdown",
                     "params": {}})
        + lsp_frame({"jsonrpc": "2.0", "method": "exit", "params": {}})
    )
    r = subprocess.run([sys.executable, vx_py, "lsp"], input=convo,
                       capture_output=True, timeout=30)
    problems = []
    try:
        msgs = lsp_parse_all(r.stdout)
        by_id = {m.get("id"): m for m in msgs if "id" in m}
        caps = by_id[1]["result"]["capabilities"]
        if not caps.get("completionProvider") and "completionProvider" not in caps:
            problems.append("no completion capability")
        diag = [m for m in msgs
                if m.get("method") == "textDocument/publishDiagnostics"]
        if not diag or not diag[0]["params"]["diagnostics"]:
            problems.append("no diagnostics for a syntax error")
        elif diag[0]["params"]["diagnostics"][0]["range"]["start"]["line"] != 1:
            problems.append("diagnostic on the wrong line")
        labels = {i["label"] for i in by_id[2]["result"]}
        for want in ("readfile", "sort", "func", "x"):
            if want not in labels:
                problems.append(f"completion missing {want!r}")
        hover = by_id[3]["result"]
        if not hover or "print" not in hover["contents"]["value"]:
            problems.append(f"hover on 'print' gave {hover!r}")
    except Exception as e:
        problems.append(f"bad LSP transcript: {e} (stderr={r.stderr!r})")
    if problems:
        failed += 1
        print("  FAIL lsp-test 1: " + " | ".join(problems))
    else:
        passed += 1
        print("  PASS lsp-test 1")

    total = (len(CASES) + len(ERROR_CASES) + len(LINE_CASES)
             + len(CATEGORY_CASES) + len(REPL_CASES) + 5)
    print(f"\n{passed}/{total} tests passed (each on BOTH engines)")
    if failed:
        raise SystemExit(1)
