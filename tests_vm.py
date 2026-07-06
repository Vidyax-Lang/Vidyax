# -*- coding: utf-8 -*-
"""Differential tests for the C VM (vxvm) against the Python engines.

Reuses the exact CASES/ERROR_CASES from tests.py: compiles each case to
bytecode, runs ./vm/vxvm, and requires stdout + error text to match the
expected result. `use ai` and member access run on the VM now; the only
skipped cases are ones that would make a live network request.

Run: python3 tests_vm.py
"""
import os
import subprocess
import sys
import tempfile

import vxc
from tests import CASES, ERROR_CASES, GO_CASES

VM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm", "vxvm")
# extra flags, e.g.: VXVM_FLAGS="--gc-stress" python3 tests_vm.py
VM_FLAGS = os.environ.get("VXVM_FLAGS", "").split()
# the shared file-op cases need fs; the sandbox net-deny cases need the
# net baseline granted so the sandbox (not the flag) is what denies it
VM_FLAGS += ["--allow-fs", "--allow-net"]

# The VM runs `use ai` and member access. Only skip cases that would hit
# the network (ai.ask / a reachable get()), which needs credentials.
def supported(src):
    return ".ask" not in src


def run_vm(src):
    """Compile + run on the VM. Returns (stdout, error_msg_or_None)."""
    with tempfile.NamedTemporaryFile(suffix=".vxc", delete=False) as f:
        path = f.name
    try:
        c = vxc.compile_source(src)
    except vxc.VidyaxError as e:
        os.unlink(path)
        return "", e.msg   # parse/compile errors: same front-end as engines
    try:
        with open(path, "wb") as f:
            f.write(c.serialize())
        r = subprocess.run([VM] + VM_FLAGS + [path], capture_output=True, text=True,
                           timeout=30)
        out = r.stdout
        err = None
        if r.returncode != 0:
            # the VM prints "[Vidyax] msg" as its last stdout line on error
            lines = out.rstrip("\n").split("\n")
            if lines and lines[-1].startswith("[Vidyax] "):
                err = lines[-1][len("[Vidyax] "):]
                out = "".join(l + "\n" for l in lines[:-1]) if len(lines) > 1 else ""
            else:
                err = (r.stderr.strip() or "vm crashed "
                       f"(exit {r.returncode})")
        return out, err
    finally:
        os.unlink(path)


def main():
    passed = failed = skipped = 0

    for i, (src, want) in enumerate(CASES, 1):
        if not supported(src):
            skipped += 1
            continue
        out, err = run_vm(src)
        if err is not None:
            failed += 1
            print(f"  FAIL vm-test {i}: errored: {err!r} (stdout={out!r})")
        elif out != want:
            failed += 1
            print(f"  FAIL vm-test {i}: got {out!r}, want {want!r}")
        else:
            passed += 1
            print(f"  PASS vm-test {i}")

    base = len(CASES)
    for i, (src, want_sub) in enumerate(ERROR_CASES, 1):
        if not supported(src):
            skipped += 1
            continue
        out, err = run_vm(src)
        if err is None:
            failed += 1
            print(f"  FAIL vm-err {i} (#{base+i}): did not error "
                  f"(stdout={out!r})")
        elif want_sub not in err:
            failed += 1
            print(f"  FAIL vm-err {i} (#{base+i}): error {err!r} "
                  f"missing {want_sub!r}")
        else:
            passed += 1
            print(f"  PASS vm-err {i} (#{base+i})")

    # go/wait (Phase C): the deterministic task subset must match too
    for i, (src, want, want_err) in enumerate(GO_CASES, 1):
        out, err = run_vm(src)
        problems = []
        if out != want:
            problems.append(f"got {out!r}, want {want!r}")
        if want_err is None and err is not None:
            problems.append(f"errored: {err!r}")
        if want_err is not None and (err is None or want_err not in err):
            problems.append(f"error {err!r} missing {want_err!r}")
        if problems:
            failed += 1
            print(f"  FAIL vm-go {i}: " + " | ".join(problems))
        else:
            passed += 1
            print(f"  PASS vm-go {i}")

    # sandbox: without --allow-fs the VM must refuse file access
    saved = VM_FLAGS[:]
    try:
        VM_FLAGS.remove("--allow-fs")
        out, err = run_vm('print readfile("/tmp/vx_selftest.txt")\n')
    finally:
        VM_FLAGS[:] = saved
    if err is not None and "file access is not allowed" in err:
        passed += 1
        print("  PASS vm-sandbox fs-deny")
    else:
        failed += 1
        print(f"  FAIL vm-sandbox fs-deny: out={out!r} err={err!r}")

    total = len(CASES) + len(ERROR_CASES) + len(GO_CASES) + 1
    print(f"\nVM: {passed} passed, {failed} failed, {skipped} skipped "
          f"(network — ai.ask) of {total}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
