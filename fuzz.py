# -*- coding: utf-8 -*-
"""Differential fuzzer for Vidyax.

Generates random (but always-terminating) Vidyax programs and runs each
one through all three engines:

    walk  = tree-walking interpreter   (vidyax.run_text)
    fast  = transpile-to-Python path   (vidyax.run_fast_text)
    vm    = bytecode compiler + C VM   (vxc + vm/vxvm)

A program passes only if all three agree on stdout AND on the error
message (if any). Any disagreement is written to fuzz_failures/ for
replay. This is the stability net behind the differential test suite:
tests.py pins known behaviours, fuzz.py hunts for unknown ones.

Usage:
    python fuzz.py                 # quick run (default 300 programs)
    python fuzz.py -n 2000         # longer run
    python fuzz.py --seed 12345    # reproduce a specific run
    python fuzz.py --gc-stress     # VM collects at every safepoint

Determinism rules for generated programs: no random(), ask, get, ai,
readfile/writefile — every run of a generated program must produce
identical output everywhere.
"""
import argparse
import contextlib
import io
import os
import random
import re
import subprocess
import sys
import tempfile

import vidyax
import vxc

HERE = os.path.dirname(os.path.abspath(__file__))
VM = os.path.join(HERE, "vm", "vxvm")

# builtins that are safe (deterministic, no I/O) for generated programs
STR_FUNCS = ["upper", "lower", "trim", "text"]
NUM1_FUNCS = ["abs", "floor", "ceil", "round", "sqrt", "text"]


class Gen:
    """Grammar-driven random program generator (seeded => reproducible)."""

    def __init__(self, rng):
        self.r = rng
        self.vars = []          # variable names known to exist
        self.funcs = []         # (name, nparams)
        self.n = 0

    def fresh(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    # ---- expressions ----
    def num(self):
        return str(self.r.choice([0, 1, 2, 3, 5, 7, 10, 42, -3, -1]))

    def string(self):
        s = "".join(self.r.choice("abcxyz ,") for _ in range(self.r.randint(0, 5)))
        return '"%s"' % s

    def list_lit(self, depth):
        items = [self.expr(depth - 1) for _ in range(self.r.randint(0, 4))]
        return "[" + ", ".join(items) + "]"

    def expr(self, depth):
        r = self.r
        if depth <= 0 or r.random() < 0.3:
            leaves = [self.num, self.string,
                      lambda: r.choice(["true", "false"])]
            if self.vars and r.random() < 0.6:
                return r.choice(self.vars)
            return r.choice(leaves)()
        k = r.randint(0, 9)
        if k <= 3:   # arithmetic / comparison / logic
            op = r.choice(["+", "-", "*", "%", "/", "==", "!=", "<", "<=",
                           ">", ">=", "and", "or"])
            return "(%s %s %s)" % (self.expr(depth - 1), op,
                                   self.expr(depth - 1))
        if k == 4:
            return "(not %s)" % self.expr(depth - 1)
        if k == 5:
            return self.list_lit(depth)
        if k == 6:   # builtin over a string-ish value
            return "%s(%s)" % (r.choice(STR_FUNCS), self.expr(depth - 1))
        if k == 7:   # builtin over a number-ish value
            return "%s(%s)" % (r.choice(NUM1_FUNCS), self.expr(depth - 1))
        if k == 8:   # list/text probes (may error: that's fine, errors are
                     # compared too — they just must be IDENTICAL everywhere)
            e = self.expr(depth - 1)
            return r.choice([
                "len(%s)" % e,
                "contains(%s, %s)" % (e, self.expr(depth - 1)),
                "find(%s, %s)" % (e, self.expr(depth - 1)),
                "slice(%s, %s, %s)" % (e, self.num(), self.num()),
            ])
        if self.funcs and r.random() < 0.7:
            name, np = r.choice(self.funcs)
            args = ", ".join(self.expr(depth - 1) for _ in range(np))
            return "%s(%s)" % (name, args)
        return "sum([1, 2, 3])"

    # ---- statements ----
    def assign(self, ind):
        if self.vars and self.r.random() < 0.4:
            name = self.r.choice(self.vars)
        else:
            name = self.fresh("v")
        line = "%s%s: %s" % (ind, name, self.expr(2))
        self.vars.append(name)
        return [line]

    def block(self, ind, depth, in_loop):
        out = []
        for _ in range(self.r.randint(1, 3)):
            out += self.stmt(ind, depth - 1, in_loop)
        return out or [ind + "print 0"]

    def stmt(self, ind, depth, in_loop=False):
        r = self.r
        k = r.randint(0, 11)
        if depth <= 0 or k <= 3:
            return self.assign(ind)
        if k <= 5:
            return ["%sprint %s" % (ind, self.expr(2))]
        if k == 6:
            out = ["%sif %s:" % (ind, self.expr(1))]
            out += self.block(ind + "    ", depth, in_loop)
            if r.random() < 0.5:
                out.append("%selse:" % ind)
                out += self.block(ind + "    ", depth, in_loop)
            return out
        if k == 7:
            out = ["%srpt %d:" % (ind, r.randint(0, 3))]
            out += self.block(ind + "    ", depth, True)
            return out
        if k == 8:
            v = self.fresh("i")
            self.vars.append(v)
            out = ["%sfor %s in %s:" % (ind, v, self.list_lit(2))]
            out += self.block(ind + "    ", depth, True)
            return out
        if k == 9:
            out = ["%stry:" % ind]
            out += self.block(ind + "    ", depth, in_loop)
            e = self.fresh("e")
            self.vars.append(e)
            out.append("%scatch %s:" % (ind, e))
            out.append('%s    print "err: " + %s' % (ind, e))
            return out
        if k == 10 and in_loop:
            return [ind + self.r.choice(["break", "continue"])]
        return ["%sprint %s" % (ind, self.expr(2))]

    def func_def(self):
        name = self.fresh("f")
        np = self.r.randint(1, 2)
        params = [self.fresh("p") for _ in range(np)]
        saved = self.vars
        self.vars = list(params)            # body sees params only
        out = ["func %s(%s):" % (name, ", ".join(params))]
        for _ in range(self.r.randint(1, 2)):
            out += self.stmt("    ", 1)
        out.append("    return %s" % self.expr(2))
        self.vars = saved
        self.funcs.append((name, np))       # callable from here on
        return out

    def program(self):
        lines = []
        for _ in range(self.r.randint(0, 2)):
            lines += self.func_def()
        for _ in range(self.r.randint(3, 8)):
            lines += self.stmt("", 2)
        return "\n".join(lines) + "\n"


# ---- the three engines ----
def run_py(fn, src):
    buf = io.StringIO()
    err = None
    try:
        with contextlib.redirect_stdout(buf):
            fn(src)
    except vidyax.VidyaxError as e:
        err = e.msg
    except RecursionError:
        err = "RECURSION"
    return buf.getvalue(), err


def run_vm(src, gc_stress):
    try:
        c = vxc.compile_source(src)
    except vxc.VidyaxError as e:
        return "", e.msg
    with tempfile.NamedTemporaryFile(suffix=".vxc", delete=False) as f:
        path = f.name
        f.write(c.serialize())
    flags = ["--max-instr", "20000000", "--max-time", "10"]
    if gc_stress:
        flags.append("--gc-stress")
    try:
        r = subprocess.run([VM] + flags + [path], capture_output=True,
                           text=True, timeout=30)
    finally:
        os.unlink(path)
    out, err = r.stdout, None
    if r.returncode != 0:
        lines = out.rstrip("\n").split("\n")
        if lines and lines[-1].startswith("[Vidyax] "):
            err = lines[-1][len("[Vidyax] "):]
            out = "".join(l + "\n" for l in lines[:-1]) if len(lines) > 1 else ""
        else:
            err = r.stderr.strip() or f"vm crashed (exit {r.returncode})"
    return out, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=300, help="programs to generate")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--gc-stress", action="store_true")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(10 ** 9)
    print(f"fuzz: n={args.n} seed={seed} gc_stress={args.gc_stress}")
    rng = random.Random(seed)

    faildir = os.path.join(HERE, "fuzz_failures")
    failures = 0
    for i in range(1, args.n + 1):
        src = Gen(random.Random(rng.randrange(10 ** 9))).program()
        results = {
            "walk": run_py(vidyax.run_text, src),
            "fast": run_py(vidyax.run_fast_text, src),
            "vm":   run_vm(src, args.gc_stress),
        }
        vals = set(results.values())
        if len(vals) != 1:
            failures += 1
            os.makedirs(faildir, exist_ok=True)
            p = os.path.join(faildir, f"seed{seed}_case{i}.vx")
            with open(p, "w") as f:
                f.write(src)
            print(f"\nDIVERGENCE at case {i} (saved to {p}):")
            for name, (out, err) in results.items():
                print(f"  {name}: out={out!r} err={err!r}")
        if i % 50 == 0:
            print(f"  ...{i}/{args.n} ok so far: {i - failures}")

    print(f"\nfuzz done: {args.n - failures}/{args.n} agree "
          f"(seed {seed})")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
