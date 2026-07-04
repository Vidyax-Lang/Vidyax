#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record benchmark results for Vidyax .vx files.

Runs each benchmark on all three engines and records timings:
  run   - transpiler -> CPython
  walk  - tree-walking interpreter
  vxvm  - the C virtual machine (compile to .vxc, then execute)

A case only PASSes if all three engines produce identical output.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDYAX = sys.executable if sys.executable else "python3"
VIDYAX_SCRIPT = os.path.join(REPO_ROOT, "vidyax.py")
VXC_SCRIPT = os.path.join(REPO_ROOT, "vxc.py")
VXVM_BIN = os.path.join(REPO_ROOT, "vm", "vxvm")
BENCH_DIR = os.path.join(REPO_ROOT, "benchmarks")
OUT_PATH = os.path.join(BENCH_DIR, "results.json")
DEFAULT_TIMEOUT = 120


def _clean_timeout_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _run(pattern, file_path, timeout):
    cmd = [VIDYAX, VIDYAX_SCRIPT, pattern, file_path]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {
            "elapsed_s": round(time.perf_counter() - t0, 6),
            "stdout": _clean_timeout_output(e.stdout),
            "stderr": _clean_timeout_output(e.stderr),
            "returncode": None,
            "timeout": True,
        }
    return {
        "elapsed_s": round(time.perf_counter() - t0, 6),
        "stdout": p.stdout,
        "stderr": p.stderr,
        "returncode": p.returncode,
        "timeout": False,
    }


def _run_vxvm(file_path, timeout):
    """VM path: compile to .vxc first, then run vxvm. Compile time is NOT
    counted -- we measure execution, the same way run/walk are measured."""
    if not os.path.exists(VXVM_BIN):
        return {"elapsed_s": 0.0, "stdout": "", "stderr": "vxvm not built "
                "(run: cd vm && make)", "returncode": 127, "timeout": False}
    vxc_path = file_path.rsplit(".", 1)[0] + ".vxc"
    try:
        comp = subprocess.run([VIDYAX, VXC_SCRIPT, file_path, "-o", vxc_path],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {"elapsed_s": 0.0, "stdout": "",
                "stderr": _clean_timeout_output(e.stderr),
                "returncode": None, "timeout": True}
    if comp.returncode != 0:
        return {"elapsed_s": 0.0, "stdout": "", "stderr": comp.stderr,
                "returncode": comp.returncode, "timeout": False}
    t0 = time.perf_counter()
    try:
        p = subprocess.run([VXVM_BIN, vxc_path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        if os.path.exists(vxc_path):
            os.remove(vxc_path)
        return {"elapsed_s": round(time.perf_counter() - t0, 6),
                "stdout": _clean_timeout_output(e.stdout),
                "stderr": _clean_timeout_output(e.stderr),
                "returncode": None, "timeout": True}
    if os.path.exists(vxc_path):
        os.remove(vxc_path)
    return {"elapsed_s": round(time.perf_counter() - t0, 6),
            "stdout": p.stdout, "stderr": p.stderr,
            "returncode": p.returncode, "timeout": False}


def _summarize_trials(trials):
    elapsed = [t["elapsed_s"] for t in trials]
    first = trials[0]
    summary = {
        "elapsed_s": round(min(elapsed), 6),
        "avg_s": round(sum(elapsed) / len(elapsed), 6),
        "trials": elapsed,
        "stdout": first["stdout"],
        "stderr": first["stderr"],
        "returncode": first["returncode"],
        "timeout": first["timeout"],
        "repeat_consistent": True,
    }
    for trial in trials[1:]:
        if (
            trial["stdout"] != first["stdout"]
            or trial["stderr"] != first["stderr"]
            or trial["returncode"] != first["returncode"]
            or trial["timeout"] != first["timeout"]
        ):
            summary["repeat_consistent"] = False
            break
    return summary


def _run_engine(pattern, path, repeat, timeout):
    trials = []
    for _ in range(repeat):
        if pattern == "vxvm":
            trial = _run_vxvm(path, timeout)
        else:
            trial = _run(pattern, path, timeout)
        trials.append(trial)
        if trial["timeout"]:
            break
    return _summarize_trials(trials)


def classify(result):
    run = result["run"]
    walk = result["walk"]
    vxvm = result.get("vxvm")

    engines = [run, walk] + ([vxvm] if vxvm else [])
    if any(e["timeout"] for e in engines):
        return "TIMEOUT"
    if any(e["returncode"] != 0 for e in engines):
        return "FAIL"
    if any(not e["repeat_consistent"] for e in engines):
        return "FLAKY"

    if run["stdout"] != walk["stdout"]:
        return "MISMATCH"
    if vxvm and vxvm["stdout"] != run["stdout"]:
        return "MISMATCH-VM"
    return "PASS"


def run_case(path, repeat, timeout):
    file_name = os.path.basename(path)
    result = {
        "file": file_name,
        "path": path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repeat": repeat,
        "run": None,
        "walk": None,
        "vxvm": None,
    }
    result["run"] = _run_engine("run", path, repeat, timeout)
    result["walk"] = _run_engine("walk", path, repeat, timeout)
    result["vxvm"] = _run_engine("vxvm", path, repeat, timeout)
    result["status"] = classify(result)
    if result["run"]["elapsed_s"] > 0 and result["walk"]["elapsed_s"] > 0:
        result["speedup"] = round(
            result["walk"]["elapsed_s"] / result["run"]["elapsed_s"], 2)
    if result["vxvm"]["elapsed_s"] > 0 and result["run"]["elapsed_s"] > 0:
        result["vxvm_vs_run"] = round(
            result["run"]["elapsed_s"] / result["vxvm"]["elapsed_s"], 2)
    if result["vxvm"]["elapsed_s"] > 0 and result["walk"]["elapsed_s"] > 0:
        result["vxvm_vs_walk"] = round(
            result["walk"]["elapsed_s"] / result["vxvm"]["elapsed_s"], 2)
    return result


def load_results():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(records):
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
        f.write("\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Record benchmark results for Vidyax .vx files."
    )
    parser.add_argument("targets", nargs="*", help="Benchmark .vx files to run")
    parser.add_argument(
        "-r", "--repeat", type=int, default=1,
        help="Run each engine N times and record min/average time"
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help="Timeout in seconds for each engine trial"
    )
    return parser.parse_args(argv)


def resolve_targets(target_args):
    if target_args:
        targets = []
        for t in target_args:
            if os.path.isabs(t) or os.path.exists(t):
                targets.append(t)
            else:
                targets.append(os.path.join(REPO_ROOT, t))
        return targets
    return sorted(
        os.path.join(BENCH_DIR, name)
        for name in os.listdir(BENCH_DIR)
        if name.endswith(".vx")
    )


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    if args.repeat < 1:
        print("--repeat must be at least 1")
        sys.exit(1)
    if args.timeout <= 0:
        print("--timeout must be greater than 0")
        sys.exit(1)

    targets = resolve_targets(args.targets)
    if not targets:
        print("No .vx benchmarks found.")
        sys.exit(1)

    records = load_results()
    for target in targets:
        if not os.path.exists(target):
            print(f"Missing: {target}")
            continue
        print(f"Benchmarking: {os.path.basename(target)}")
        rec = run_case(target, args.repeat, args.timeout)
        records.append(rec)
        speedup = rec.get("speedup")
        speed = f" speedup={speedup}x" if speedup is not None else ""
        vs_run = rec.get("vxvm_vs_run")
        vm_str = ""
        if vs_run is not None:
            vm_str = (f"\n    vxvm={rec['vxvm']['elapsed_s']}s "
                      f"({vs_run}x vs run, {rec.get('vxvm_vs_walk')}x vs walk)")
        print(
            f"  {rec['status']}: run={rec['run']['elapsed_s']}s "
            f"walk={rec['walk']['elapsed_s']}s{speed}{vm_str}"
        )

    save_results(records)
    print(f"\nSaved {len(records)} record(s) to {OUT_PATH}")


if __name__ == "__main__":
    main()