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
import contextlib
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

    total = len(CASES) + len(ERROR_CASES)
    print(f"\n{passed}/{total} tests passed (each on BOTH engines)")
    if failed:
        raise SystemExit(1)
