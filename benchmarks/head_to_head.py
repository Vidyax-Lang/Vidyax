#!/usr/bin/env python3
"""
Reproducible Head-to-Head Hardware Benchmark:
Vidyax (vxvm C VM & AOT Native) vs Python 3 vs Node.js (V8) vs Lua vs C (-O2)

Measures:
  1. Cold-start latency (boot runtime -> print -> exit, median of 5 runs)
  2. Compute workload: Hanoi(18) [262,143 recursive moves] + 50,000 Skyline block placements
     (asserts identical output across every runtime)
  3. Peak Resident Set Size (Max RSS in KB via Linux getrusage / resource)
  4. Runtime binary size on disk
"""

import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import vxc
import vxnative

EXPECTED_LINE = "262143 1666691668"

VIDYAX_HELLO = 'print "ok"\n'
VIDYAX_BENCH = """
func hanoi(n, a, b, c):
    if n <= 1:
        return 1
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)

func skyline(n):
    h0: 0
    h1: 0
    h2: 0
    h3: 0
    total: 0
    i: 0
    rpt n:
        w: (i % 2) + 1
        h: (i % 4) + 1
        col: i % 3
        if col == 0:
            m: h0
            if w == 2 and h1 > m:
                m: h1
            nh: m + h
            h0: nh
            if w == 2:
                h1: nh
        elif col == 1:
            m: h1
            if w == 2 and h2 > m:
                m: h2
            nh: m + h
            h1: nh
            if w == 2:
                h2: nh
        else:
            m: h2
            if w == 2 and h3 > m:
                m: h3
            nh: m + h
            h2: nh
            if w == 2:
                h3: nh
        total: total + nh
        i: i + 1
    return total

print text(hanoi(18, 1, 3, 2)) + " " + text(skyline(50000))
"""

PYTHON_BENCH = """
def hanoi(n, a, b, c):
    if n <= 1:
        return 1
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)

def skyline(n):
    h0 = h1 = h2 = h3 = 0
    total = 0
    for i in range(n):
        w = (i % 2) + 1
        h = (i % 4) + 1
        col = i % 3
        if col == 0:
            m = h1 if (w == 2 and h1 > h0) else h0
            nh = m + h
            h0 = nh
            if w == 2:
                h1 = nh
        elif col == 1:
            m = h2 if (w == 2 and h2 > h1) else h1
            nh = m + h
            h1 = nh
            if w == 2:
                h2 = nh
        else:
            m = h3 if (w == 2 and h3 > h2) else h2
            nh = m + h
            h2 = nh
            if w == 2:
                h3 = nh
        total += nh
    return total

print(f"{hanoi(18, 1, 3, 2)} {skyline(50000)}")
"""

NODE_BENCH = """
function hanoi(n, a, b, c) {
  if (n <= 1) return 1;
  return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a);
}
function skyline(n) {
  let h0 = 0, h1 = 0, h2 = 0, h3 = 0, total = 0;
  for (let i = 0; i < n; i++) {
    const w = (i % 2) + 1;
    const h = (i % 4) + 1;
    const col = i % 3;
    let nh;
    if (col === 0) {
      const m = (w === 2 && h1 > h0) ? h1 : h0;
      nh = m + h;
      h0 = nh;
      if (w === 2) h1 = nh;
    } else if (col === 1) {
      const m = (w === 2 && h2 > h1) ? h2 : h1;
      nh = m + h;
      h1 = nh;
      if (w === 2) h2 = nh;
    } else {
      const m = (w === 2 && h3 > h2) ? h3 : h2;
      nh = m + h;
      h2 = nh;
      if (w === 2) h3 = nh;
    }
    total += nh;
  }
  return total;
}
console.log(`${hanoi(18, 1, 3, 2)} ${skyline(50000)}`);
"""

C_BENCH = """
#include <stdio.h>
static long long hanoi(int n, int a, int b, int c) {
    if (n <= 1) return 1;
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a);
}
static long long skyline(int n) {
    long long h0 = 0, h1 = 0, h2 = 0, h3 = 0, total = 0;
    for (int i = 0; i < n; i++) {
        int w = (i % 2) + 1;
        int h = (i % 4) + 1;
        int col = i % 3;
        long long m, nh;
        if (col == 0) {
            m = (w == 2 && h1 > h0) ? h1 : h0;
            nh = m + h; h0 = nh; if (w == 2) h1 = nh;
        } else if (col == 1) {
            m = (w == 2 && h2 > h1) ? h2 : h1;
            nh = m + h; h1 = nh; if (w == 2) h2 = nh;
        } else {
            m = (w == 2 && h3 > h2) ? h3 : h2;
            nh = m + h; h2 = nh; if (w == 2) h3 = nh;
        }
        total += nh;
    }
    return total;
}
int main(void) {
    printf("%lld %lld\\n", hanoi(18, 1, 3, 2), skyline(50000));
    return 0;
}
"""

LUA_BENCH = """
local function hanoi(n, a, b, c)
    if n <= 1 then return 1 end
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)
end
local function skyline(n)
    local h0, h1, h2, h3, total = 0, 0, 0, 0, 0
    for i = 0, n - 1 do
        local w = (i % 2) + 1
        local h = (i % 4) + 1
        local col = i % 3
        local m, nh
        if col == 0 then
            m = (w == 2 and h1 > h0) and h1 or h0
            nh = m + h; h0 = nh; if w == 2 then h1 = nh end
        elseif col == 1 then
            m = (w == 2 and h2 > h1) and h2 or h1
            nh = m + h; h1 = nh; if w == 2 then h2 = nh end
        else
            m = (w == 2 and h3 > h2) and h3 or h2
            nh = m + h; h2 = nh; if w == 2 then h3 = nh end
        end
        total = total + nh
    end
    return total
end
print(string.format("%d %d", hanoi(18, 1, 3, 2), skyline(50000)))
"""


def measure_cmd(cmd, runs=5, expected=None):
    times_ms = []
    max_rss_kb = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate()
        t1 = time.perf_counter()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}\n{err}")
        if expected is not None and out.strip() != expected:
            raise RuntimeError(f"Output mismatch for {cmd}: got {out.strip()!r}, expected {expected!r}")
        times_ms.append((t1 - t0) * 1000.0)

    # Measure Max RSS in isolated child via /usr/bin/time -f %M if available
    if os.path.exists("/usr/bin/time"):
        r = subprocess.run(
            ["/usr/bin/time", "-f", "%M", *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            max_rss_kb = int(r.stderr.strip().splitlines()[-1])
        except Exception:
            max_rss_kb = 0
    else:
        # Fallback: Python child wrapper measuring wait4 ru_maxrss
        helper = (
            "import os, subprocess, sys; "
            "p = subprocess.Popen(sys.argv[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            "_, _, ru = os.wait4(p.pid, 0); "
            "print(ru.ru_maxrss)"
        )
        r = subprocess.run([sys.executable, "-c", helper, *cmd], capture_output=True, text=True)
        try:
            max_rss_kb = int(r.stdout.strip())
        except Exception:
            max_rss_kb = 0

    return statistics.median(times_ms), max_rss_kb


def bin_size_kb(path):
    if not path or not os.path.exists(path):
        return "-"
    real = os.path.realpath(path)
    return f"{os.path.getsize(real) / 1024:.0f} KB"


def main():
    tmp = tempfile.mkdtemp(prefix="vidyax_h2h_")
    try:
        vx_hello = os.path.join(tmp, "hello.vx")
        vx_hello_vxc = os.path.join(tmp, "hello.vxc")
        vx_bench = os.path.join(tmp, "bench.vx")
        vx_bench_vxc = os.path.join(tmp, "bench.vxc")
        vx_bench_bin = os.path.join(tmp, "bench_vx_native")
        vx_hello_bin = os.path.join(tmp, "hello_vx_native")

        with open(vx_hello, "w") as f:
            f.write(VIDYAX_HELLO)
        with open(vx_bench, "w") as f:
            f.write(VIDYAX_BENCH)

        vxc.compile_file(vx_hello, vx_hello_vxc)
        vxc.compile_file(vx_bench, vx_bench_vxc)
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "vidyax.py"), "native", vx_hello, "-o", vx_hello_bin],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "vidyax.py"), "native", vx_bench, "-o", vx_bench_bin],
            stdout=subprocess.DEVNULL,
            check=True,
        )

        py_hello = os.path.join(tmp, "hello.py")
        py_bench = os.path.join(tmp, "bench.py")
        with open(py_hello, "w") as f:
            f.write('print("ok")\n')
        with open(py_bench, "w") as f:
            f.write(PYTHON_BENCH)

        js_hello = os.path.join(tmp, "hello.js")
        js_bench = os.path.join(tmp, "bench.js")
        with open(js_hello, "w") as f:
            f.write('console.log("ok");\n')
        with open(js_bench, "w") as f:
            f.write(NODE_BENCH)

        c_hello = os.path.join(tmp, "hello.c")
        c_hello_bin = os.path.join(tmp, "hello_c")
        c_bench = os.path.join(tmp, "bench.c")
        c_bench_bin = os.path.join(tmp, "bench_c")
        with open(c_hello, "w") as f:
            f.write('#include <stdio.h>\nint main(void){puts("ok");return 0;}\n')
        with open(c_bench, "w") as f:
            f.write(C_BENCH)
        subprocess.run(["gcc", "-O2", c_hello, "-o", c_hello_bin], check=True)
        subprocess.run(["gcc", "-O2", c_bench, "-o", c_bench_bin], check=True)

        vxvm = os.path.join(ROOT, "vm", "vxvm")
        targets = [
            ("Vidyax AOT Native", [vx_hello_bin], [vx_bench_bin], bin_size_kb(vx_bench_bin), "Built-in (deny net,fs)"),
            ("Vidyax C VM (vxvm)", [vxvm, vx_hello_vxc], [vxvm, vx_bench_vxc], bin_size_kb(vxvm), "Built-in (deny net,fs)"),
            ("Python 3 (CPython)", [sys.executable, py_hello], [sys.executable, py_bench], bin_size_kb(shutil.which("python3")), "None (needs container)"),
        ]

        node_bin = shutil.which("node")
        if node_bin:
            targets.append(("Node.js (V8 JIT)", [node_bin, js_hello], [node_bin, js_bench], bin_size_kb(node_bin), "Experimental flag"))

        lua_bin = shutil.which("lua") or shutil.which("luajit")
        if lua_bin:
            lua_h = os.path.join(tmp, "hello.lua")
            lua_b = os.path.join(tmp, "bench.lua")
            with open(lua_h, "w") as f:
                f.write('print("ok")\n')
            with open(lua_b, "w") as f:
                f.write(LUA_BENCH)
            targets.append((os.path.basename(lua_bin), [lua_bin, lua_h], [lua_bin, lua_b], bin_size_kb(lua_bin), "Manual env strip"))

        targets.append(("C (gcc -O2 baseline)", [c_hello_bin], [c_bench_bin], bin_size_kb(c_bench_bin), "None (unsafe raw OS)"))

        print("| Runtime | Cold-Start (ms) | Compute (ms) | Peak RAM (Max RSS) | Binary Size | Built-in Sandbox |")
        print("| :--- | :---: | :---: | :---: | :---: | :--- |")
        for name, h_cmd, b_cmd, bsize, sbox in targets:
            cold_ms, _ = measure_cmd(h_cmd, runs=5, expected="ok")
            comp_ms, rss_kb = measure_cmd(b_cmd, runs=5, expected=EXPECTED_LINE)
            rss_str = f"{rss_kb / 1024:.2f} MB ({rss_kb} KB)" if rss_kb else "n/a"
            print(f"| **{name}** | `{cold_ms:.2f} ms` | `{comp_ms:.2f} ms` | `{rss_str}` | `{bsize}` | {sbox} |")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
