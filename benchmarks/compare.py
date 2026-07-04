#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare the last two benchmark batches in results.json."""
import argparse
import json
import os
import sys

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(BENCH_DIR, "results.json")
DEFAULT_ORDER = [
    "fibonacci.vx",
    "matrix.vx",
    "quicksort.vx",
    "recursive_function.vx",
    "string_manipulations.vx",
]


def load_results(path):
    if not os.path.exists(path):
        print(f"Missing results file: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def completed_records(records):
    return [
        r for r in records
        if isinstance(r, dict)
        and r.get("file")
        and isinstance(r.get("run"), dict)
        and isinstance(r.get("walk"), dict)
    ]


def latest_batches(records, order):
    wanted = set(order)
    batches = []
    current = []
    seen = set()

    for rec in reversed(records):
        name = rec.get("file")
        if name not in wanted or name in seen:
            continue
        current.append(rec)
        seen.add(name)
        if len(seen) == len(wanted):
            batches.append({r["file"]: r for r in current})
            current = []
            seen = set()
            if len(batches) == 2:
                return batches[1], batches[0]

    return None, None


def value(record, engine, metric):
    data = record.get(engine) or {}
    if metric in data:
        return data[metric]
    return data.get("elapsed_s")


def pct(old, new):
    if old is None or new is None or old == 0:
        return None
    return ((new - old) / old) * 100


def verdict(change, threshold):
    if change is None:
        return "n/a"
    if change > threshold:
        return "slower"
    if change < -threshold:
        return "faster"
    return "same"


def fmt_time(v):
    if v is None:
        return "n/a"
    return f"{v:.6f}s"


def fmt_pct(v):
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def print_table(old_batch, new_batch, order, engine, metric, threshold):
    print(f"Comparing latest batch vs previous batch")
    print(f"engine={engine} metric={metric} threshold={threshold}%")
    print()
    print(f"{'file':28} {'old':>12} {'new':>12} {'change':>10} status")
    print("-" * 72)

    changes = []
    for name in order:
        old = old_batch.get(name)
        new = new_batch.get(name)
        old_v = value(old, engine, metric) if old else None
        new_v = value(new, engine, metric) if new else None
        change = pct(old_v, new_v)
        changes.append(change)
        print(
            f"{name:28} {fmt_time(old_v):>12} {fmt_time(new_v):>12} "
            f"{fmt_pct(change):>10} {verdict(change, threshold)}"
        )

    usable = [c for c in changes if c is not None]
    if usable:
        avg = sum(usable) / len(usable)
        print("-" * 72)
        print(f"{'average':28} {'':>12} {'':>12} {fmt_pct(avg):>10} {verdict(avg, threshold)}")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Compare the last two benchmark batches."
    )
    parser.add_argument(
        "--results", default=RESULTS_PATH,
        help="Path to results.json"
    )
    parser.add_argument(
        "--engine", choices=("run", "walk"), default="run",
        help="Engine to compare"
    )
    parser.add_argument(
        "--metric", choices=("avg_s", "elapsed_s"), default="avg_s",
        help="Metric to compare; avg_s is best when --repeat was used"
    )
    parser.add_argument(
        "--threshold", type=float, default=3.0,
        help="Percent change considered meaningful"
    )
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    records = completed_records(load_results(args.results))
    old_batch, new_batch = latest_batches(records, DEFAULT_ORDER)
    if old_batch is None or new_batch is None:
        print("Need at least two complete benchmark batches to compare.")
        print("Run: python3 benchmarks/record.py --repeat 3")
        sys.exit(1)
    print_table(
        old_batch,
        new_batch,
        DEFAULT_ORDER,
        args.engine,
        args.metric,
        args.threshold,
    )


if __name__ == "__main__":
    main()
