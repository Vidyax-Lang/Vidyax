#!/usr/bin/env python3
"""
Reproducible Head-to-Head Hardware Benchmark:
Vidyax (AOT Native, vxvm C VM, Zero-Python CLI) vs Lua, Rust, Python 3, Node.js, C (-O2)

Methodology:
  - Uses a minimal C wait4() + CLOCK_MONOTONIC harness so child process Max RSS
    is measured directly in KB without inheriting the Python parent's RSS floor.
  - Cold-start: median of 5 runs printing "ok".
  - Compute: median of 5 runs computing Hanoi(18) [262,143 recursive calls] +
    50,000 skyline block placements, asserting identical output "262143 1666691668".
"""

import os
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_LINE = "262143 1666691668"

MEAS_C = r"""
#include <stdio.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    pid_t pid = fork();
    if (pid == 0) {
        execvp(argv[1], &argv[1]);
        _exit(127);
    }
    int status = 0;
    struct rusage ru;
    wait4(pid, &status, 0, &ru);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double ms = (t1.tv_sec - t0.tv_sec) * 1000.0 + (t1.tv_nsec - t0.tv_nsec) / 1e6;
    fprintf(stderr, "MEAS %.3f %ld\n", ms, ru.ru_maxrss);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
"""

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
      nh = m + h; h0 = nh; if (w === 2) h1 = nh;
    } else if (col === 1) {
      const m = (w === 2 && h2 > h1) ? h2 : h1;
      nh = m + h; h1 = nh; if (w === 2) h2 = nh;
    } else {
      const m = (w === 2 && h3 > h2) ? h3 : h2;
      nh = m + h; h2 = nh; if (w === 2) h3 = nh;
    }
    total += nh;
  }
  return total;
}
console.log(`${hanoi(18, 1, 3, 2)} ${skyline(50000)}`);
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

RUST_BENCH = """
fn hanoi(n: i64, a: i64, b: i64, c: i64) -> i64 {
    if n <= 1 { return 1; }
    hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)
}
fn skyline(n: i64) -> i64 {
    let (mut h0, mut h1, mut h2, mut h3, mut total) = (0i64, 0, 0, 0, 0);
    for i in 0..n {
        let w = (i % 2) + 1;
        let h = (i % 4) + 1;
        let col = i % 3;
        let nh = if col == 0 {
            let m = if w == 2 && h1 > h0 { h1 } else { h0 };
            let v = m + h; h0 = v; if w == 2 { h1 = v; } v
        } else if col == 1 {
            let m = if w == 2 && h2 > h1 { h2 } else { h1 };
            let v = m + h; h1 = v; if w == 2 { h2 = v; } v
        } else {
            let m = if w == 2 && h3 > h2 { h3 } else { h2 };
            let v = m + h; h2 = v; if w == 2 { h3 = v; } v
        };
        total += nh;
    }
    total
}
fn main() {
    println!("{} {}", hanoi(18, 1, 3, 2), skyline(50000));
}
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


def measure(meas_bin, cmd, expected, runs=5):
    times_ms, rsses = [], []
    for _ in range(runs):
        p = subprocess.run([meas_bin, *cmd], capture_output=True, text=True, check=True)
        if p.stdout.strip() != expected:
            raise RuntimeError(f"Output mismatch for {cmd}: got {p.stdout.strip()!r}, expected {expected!r}")
        line = [l for l in p.stderr.splitlines() if l.startswith("MEAS ")][-1]
        _, ms, rss = line.split()
        times_ms.append(float(ms))
        rsses.append(int(rss))
    return statistics.median(times_ms), max(rsses)


def bin_size(path):
    if not path or not os.path.exists(path):
        return "-"
    kb = os.path.getsize(os.path.realpath(path)) / 1024.0
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"


def main():
    tmp = tempfile.mkdtemp(prefix="vidyax_h2h_")
    try:
        meas_c = os.path.join(tmp, "meas.c")
        meas_bin = os.path.join(tmp, "meas")
        with open(meas_c, "w") as f:
            f.write(MEAS_C)
        subprocess.run(["gcc", "-O2", meas_c, "-o", meas_bin], check=True)

        vx_cli = os.path.join(ROOT, "vidyax")
        vxvm = os.path.join(ROOT, "vm", "vxvm")
        if not os.path.exists(vx_cli) or not os.path.exists(vxvm):
            subprocess.run(["make", "-C", os.path.join(ROOT, "vm"), "vxvm", "vidyax"], check=True)

        vx_h, vx_b = os.path.join(tmp, "h.vx"), os.path.join(tmp, "b.vx")
        vx_h_vxc, vx_b_vxc = os.path.join(tmp, "h.vxc"), os.path.join(tmp, "b.vxc")
        vx_h_nat, vx_b_nat = os.path.join(tmp, "h_nat"), os.path.join(tmp, "b_nat")
        open(vx_h, "w").write(VIDYAX_HELLO)
        open(vx_b, "w").write(VIDYAX_BENCH)
        subprocess.run([vx_cli, "compile", vx_h, "-o", vx_h_vxc], stdout=subprocess.DEVNULL, check=True)
        subprocess.run([vx_cli, "compile", vx_b, "-o", vx_b_vxc], stdout=subprocess.DEVNULL, check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "vidyax.py"), "native", vx_h, "-o", vx_h_nat], stdout=subprocess.DEVNULL, check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "vidyax.py"), "native", vx_b, "-o", vx_b_nat], stdout=subprocess.DEVNULL, check=True)

        py_h, py_b = os.path.join(tmp, "h.py"), os.path.join(tmp, "b.py")
        open(py_h, "w").write('print("ok")\n')
        open(py_b, "w").write(PYTHON_BENCH)

        c_h, c_b = os.path.join(tmp, "h.c"), os.path.join(tmp, "b.c")
        c_h_bin, c_b_bin = os.path.join(tmp, "h_c"), os.path.join(tmp, "b_c")
        open(c_h, "w").write('#include <stdio.h>\nint main(void){puts("ok");return 0;}\n')
        open(c_b, "w").write(C_BENCH)
        subprocess.run(["gcc", "-O2", c_h, "-o", c_h_bin], check=True)
        subprocess.run(["gcc", "-O2", c_b, "-o", c_b_bin], check=True)

        targets = [
            ("Vidyax AOT Native", [vx_h_nat], [vx_b_nat], bin_size(vx_b_nat), "Built-in (deny net, fs)"),
            ("Vidyax C VM (vxvm .vxc)", [vxvm, vx_h_vxc], [vxvm, vx_b_vxc], bin_size(vxvm), "Built-in (deny net, fs)"),
            ("Vidyax Zero-Python CLI (.vx)", [vx_cli, vx_h], [vx_cli, vx_b], bin_size(vx_cli), "Built-in + self-hosted"),
            ("Python 3 (CPython)", [sys.executable, py_h], [sys.executable, py_b], "14 KB + libpython", "None"),
        ]

        node_bin = shutil.which("node")
        if node_bin:
            js_h, js_b = os.path.join(tmp, "h.js"), os.path.join(tmp, "b.js")
            open(js_h, "w").write('console.log("ok");\n')
            open(js_b, "w").write(NODE_BENCH)
            targets.append(("Node.js (V8 JIT)", [node_bin, js_h], [node_bin, js_b], bin_size(node_bin), "Experimental flag"))

        lua_bin = shutil.which("lua") or shutil.which("luajit")
        if lua_bin:
            lua_h, lua_b = os.path.join(tmp, "h.lua"), os.path.join(tmp, "b.lua")
            open(lua_h, "w").write('print("ok")\n')
            open(lua_b, "w").write(LUA_BENCH)
            targets.append((os.path.basename(lua_bin), [lua_bin, lua_h], [lua_bin, lua_b], bin_size(lua_bin), "Manual env strip"))

        if shutil.which("rustc"):
            rs_h, rs_b = os.path.join(tmp, "h.rs"), os.path.join(tmp, "b.rs")
            rs_h_bin, rs_b_bin = os.path.join(tmp, "h_rs"), os.path.join(tmp, "b_rs")
            open(rs_h, "w").write('fn main() { println!("ok"); }\n')
            open(rs_b, "w").write(RUST_BENCH)
            subprocess.run(["rustc", "-O", rs_h, "-o", rs_h_bin], check=True)
            subprocess.run(["rustc", "-O", rs_b, "-o", rs_b_bin], check=True)
            targets.append(("Rust (rustc -O)", [rs_h_bin], [rs_b_bin], bin_size(rs_b_bin), "None (OS-level)"))

        targets.append(("C (gcc -O2)", [c_h_bin], [c_b_bin], bin_size(c_b_bin), "None (raw OS)"))

        print("| Runtime | Cold-Start | Compute (`Hanoi(18) + 50k`) | Peak RAM (`Max RSS`) | Binary Size | Built-in Sandbox |")
        print("| :--- | :---: | :---: | :---: | :---: | :--- |")
        for name, hc, bc, sz, sb in targets:
            cm, _ = measure(meas_bin, hc, "ok")
            bm, rss = measure(meas_bin, bc, EXPECTED_LINE)
            print(f"| **{name}** | `{cm:.2f} ms` | `{bm:.2f} ms` | `{rss / 1024:.2f} MB ({rss} KB)` | `{sz}` | {sb} |")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
