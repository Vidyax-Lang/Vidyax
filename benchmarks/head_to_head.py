#!/usr/bin/env python3
"""
Reproducible Multi-Workload Head-to-Head Hardware Benchmark:
Vidyax (AOT Native, vxvm C VM, Standalone CLI) vs Lua, Rust, Python 3, Node.js, C (-O2)

Methodology:
  - Uses a minimal C wait4() + CLOCK_MONOTONIC harness so child process Max RSS
    is measured directly in KB without inheriting the Python parent's RSS floor.
  - Median of 5 runs per workload; exact stdout output asserted identical across
    every runtime.
  - Workloads:
      1. Cold-start : boot runtime, print "ok", exit
      2. Recur+Loop : Hanoi(18) [262,143 calls] + 50,000 skyline blocks ("262143 1666691668")
      3. Primes     : Count primes up to 25,000 via trial division ("2762")
      4. Str/Policy : 5,000 iterations of secret-token redaction pipeline ("5000")
"""

import os
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

# ---------------------------------------------------------------------------
# Workload 1: Cold-start ("ok")
# ---------------------------------------------------------------------------
W_HELLO = {
    "expected": "ok",
    "vx": 'print "ok"\n',
    "py": 'print("ok")\n',
    "js": 'console.log("ok");\n',
    "lua": 'print("ok")\n',
    "rs": 'fn main() { println!("ok"); }\n',
    "c": '#include <stdio.h>\nint main(void){puts("ok");return 0;}\n',
}

# ---------------------------------------------------------------------------
# Workload 2: Hanoi(18) + 50,000 Skyline blocks ("262143 1666691668")
# ---------------------------------------------------------------------------
W_RECUR = {
    "expected": "262143 1666691668",
    "vx": """
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
""",
    "py": """
def hanoi(n, a, b, c):
    if n <= 1: return 1
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)
def skyline(n):
    h0 = h1 = h2 = h3 = 0
    total = 0
    for i in range(n):
        w = (i % 2) + 1; h = (i % 4) + 1; col = i % 3
        if col == 0:
            m = h1 if (w == 2 and h1 > h0) else h0
            nh = m + h; h0 = nh
            if w == 2: h1 = nh
        elif col == 1:
            m = h2 if (w == 2 and h2 > h1) else h1
            nh = m + h; h1 = nh
            if w == 2: h2 = nh
        else:
            m = h3 if (w == 2 and h3 > h2) else h2
            nh = m + h; h2 = nh
            if w == 2: h3 = nh
        total += nh
    return total
print(f"{hanoi(18, 1, 3, 2)} {skyline(50000)}")
""",
    "js": """
function hanoi(n, a, b, c) {
  if (n <= 1) return 1;
  return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a);
}
function skyline(n) {
  let h0 = 0, h1 = 0, h2 = 0, h3 = 0, total = 0;
  for (let i = 0; i < n; i++) {
    const w = (i % 2) + 1, h = (i % 4) + 1, col = i % 3;
    let nh;
    if (col === 0) { const m = (w === 2 && h1 > h0) ? h1 : h0; nh = m + h; h0 = nh; if (w === 2) h1 = nh; }
    else if (col === 1) { const m = (w === 2 && h2 > h1) ? h2 : h1; nh = m + h; h1 = nh; if (w === 2) h2 = nh; }
    else { const m = (w === 2 && h3 > h2) ? h3 : h2; nh = m + h; h2 = nh; if (w === 2) h3 = nh; }
    total += nh;
  }
  return total;
}
console.log(`${hanoi(18, 1, 3, 2)} ${skyline(50000)}`);
""",
    "lua": """
local function hanoi(n, a, b, c)
    if n <= 1 then return 1 end
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)
end
local function skyline(n)
    local h0, h1, h2, h3, total = 0, 0, 0, 0, 0
    for i = 0, n - 1 do
        local w, h, col = (i % 2) + 1, (i % 4) + 1, i % 3
        local m, nh
        if col == 0 then m = (w == 2 and h1 > h0) and h1 or h0; nh = m + h; h0 = nh; if w == 2 then h1 = nh end
        elseif col == 1 then m = (w == 2 and h2 > h1) and h2 or h1; nh = m + h; h1 = nh; if w == 2 then h2 = nh end
        else m = (w == 2 and h3 > h2) and h3 or h2; nh = m + h; h2 = nh; if w == 2 then h3 = nh end end
        total = total + nh
    end
    return total
end
print(string.format("%d %d", hanoi(18, 1, 3, 2), skyline(50000)))
""",
    "rs": """
fn hanoi(n: i64, a: i64, b: i64, c: i64) -> i64 {
    if n <= 1 { return 1; }
    hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a)
}
fn skyline(n: i64) -> i64 {
    let (mut h0, mut h1, mut h2, mut h3, mut total) = (0i64, 0, 0, 0, 0);
    for i in 0..n {
        let w = (i % 2) + 1; let h = (i % 4) + 1; let col = i % 3;
        let nh = if col == 0 { let m = if w == 2 && h1 > h0 { h1 } else { h0 }; let v = m + h; h0 = v; if w == 2 { h1 = v; } v }
        else if col == 1 { let m = if w == 2 && h2 > h1 { h2 } else { h1 }; let v = m + h; h1 = v; if w == 2 { h2 = v; } v }
        else { let m = if w == 2 && h3 > h2 { h3 } else { h2 }; let v = m + h; h2 = v; if w == 2 { h3 = v; } v };
        total += nh;
    }
    total
}
fn main() { println!("{} {}", hanoi(18, 1, 3, 2), skyline(50000)); }
""",
    "c": """
#include <stdio.h>
static long long hanoi(int n, int a, int b, int c) {
    if (n <= 1) return 1;
    return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a);
}
static long long skyline(int n) {
    long long h0 = 0, h1 = 0, h2 = 0, h3 = 0, total = 0;
    for (int i = 0; i < n; i++) {
        int w = (i % 2) + 1, h = (i % 4) + 1, col = i % 3;
        long long m, nh;
        if (col == 0) { m = (w == 2 && h1 > h0) ? h1 : h0; nh = m + h; h0 = nh; if (w == 2) h1 = nh; }
        else if (col == 1) { m = (w == 2 && h2 > h1) ? h2 : h1; nh = m + h; h1 = nh; if (w == 2) h2 = nh; }
        else { m = (w == 2 && h3 > h2) ? h3 : h2; nh = m + h; h2 = nh; if (w == 2) h3 = nh; }
        total += nh;
    }
    return total;
}
int main(void) { printf("%lld %lld\\n", hanoi(18, 1, 3, 2), skyline(50000)); return 0; }
""",
}

# ---------------------------------------------------------------------------
# Workload 3: Prime Counting up to 25,000 ("2762")
# ---------------------------------------------------------------------------
W_PRIMES = {
    "expected": "2762",
    "vx": """
func is_prime(n):
    if n < 2:
        return false
    if n == 2:
        return true
    if n % 2 == 0:
        return false
    d: 3
    rpt n:
        if d * d > n:
            break
        if n % d == 0:
            return false
        d: d + 2
    return true

count: 0
n: 2
rpt 24999:
    if is_prime(n):
        count: count + 1
    n: n + 1
print text(count)
""",
    "py": """
def is_prime(n):
    if n < 2: return False
    if n == 2: return True
    if n % 2 == 0: return False
    d = 3
    while d * d <= n:
        if n % d == 0: return False
        d += 2
    return True
print(sum(1 for n in range(2, 25001) if is_prime(n)))
""",
    "js": """
function isPrime(n) {
  if (n < 2) return false;
  if (n === 2) return true;
  if (n % 2 === 0) return false;
  for (let d = 3; d * d <= n; d += 2) if (n % d === 0) return false;
  return true;
}
let c = 0; for (let n = 2; n <= 25000; n++) if (isPrime(n)) c++;
console.log(c);
""",
    "lua": """
local function is_prime(n)
    if n < 2 then return false end
    if n == 2 then return true end
    if n % 2 == 0 then return false end
    local d = 3
    while d * d <= n do
        if n % d == 0 then return false end
        d = d + 2
    end
    return true
end
local c = 0
for n = 2, 25000 do if is_prime(n) then c = c + 1 end end
print(c)
""",
    "rs": """
fn is_prime(n: i64) -> bool {
    if n < 2 { return false; }
    if n == 2 { return true; }
    if n % 2 == 0 { return false; }
    let mut d = 3;
    while d * d <= n {
        if n % d == 0 { return false; }
        d += 2;
    }
    true
}
fn main() {
    let mut c = 0;
    for n in 2..=25000 { if is_prime(n) { c += 1; } }
    println!("{}", c);
}
""",
    "c": """
#include <stdio.h>
static int is_prime(int n) {
    if (n < 2) return 0;
    if (n == 2) return 1;
    if (n % 2 == 0) return 0;
    for (int d = 3; d * d <= n; d += 2) if (n % d == 0) return 0;
    return 1;
}
int main(void) {
    int c = 0; for (int n = 2; n <= 25000; n++) if (is_prime(n)) c++;
    printf("%d\\n", c); return 0;
}
""",
}

# ---------------------------------------------------------------------------
# Workload 4: String / Policy Secret Redaction (5,000 iterations -> "5000")
# ---------------------------------------------------------------------------
W_POLICY = {
    "expected": "5000",
    "vx": """
func scrub(s):
    v: trim(s)
    if contains(v, "sk-"):
        parts: split(v, "sk-")
        v: parts[0] + "[REDACTED]"
    return v

ok: 0
rpt 5000:
    res: scrub("  deploy key sk-live99887766  ")
    if contains(res, "[REDACTED]"):
        ok: ok + 1
print text(ok)
""",
    "py": """
def scrub(s):
    v = s.strip()
    if "sk-" in v:
        v = v.split("sk-")[0] + "[REDACTED]"
    return v
ok = 0
for _ in range(5000):
    if "[REDACTED]" in scrub("  deploy key sk-live99887766  "):
        ok += 1
print(ok)
""",
    "js": """
function scrub(s) {
  let v = s.trim();
  if (v.includes("sk-")) v = v.split("sk-")[0] + "[REDACTED]";
  return v;
}
let ok = 0;
for (let i = 0; i < 5000; i++) if (scrub("  deploy key sk-live99887766  ").includes("[REDACTED]")) ok++;
console.log(ok);
""",
    "lua": """
local function scrub(s)
    local v = s:match("^%s*(.-)%s*$")
    local idx = v:find("sk%-")
    if idx then v = v:sub(1, idx - 1) .. "[REDACTED]" end
    return v
end
local ok = 0
for i = 1, 5000 do
    if scrub("  deploy key sk-live99887766  "):find("%[REDACTED%]") then ok = ok + 1 end
end
print(ok)
""",
    "rs": """
fn scrub(s: &str) -> String {
    let v = s.trim();
    if let Some(idx) = v.find("sk-") {
        format!("{}[REDACTED]", &v[..idx])
    } else {
        v.to_string()
    }
}
fn main() {
    let mut ok = 0;
    for _ in 0..5000 {
        if scrub("  deploy key sk-live99887766  ").contains("[REDACTED]") { ok += 1; }
    }
    println!("{}", ok);
}
""",
    "c": """
#include <stdio.h>
#include <string.h>
int main(void) {
    int ok = 0;
    const char *raw = "  deploy key sk-live99887766  ";
    char buf[128];
    for (int i = 0; i < 5000; i++) {
        const char *s = raw;
        while (*s == ' ') s++;
        const char *p = strstr(s, "sk-");
        if (p) {
            size_t n = (size_t)(p - s);
            memcpy(buf, s, n);
            strcpy(buf + n, "[REDACTED]");
        }
        if (strstr(buf, "[REDACTED]")) ok++;
    }
    printf("%d\\n", ok);
    return 0;
}
""",
}


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


def build_workload_cmds(tmp, tag, w, vx_cli, vxvm):
    cmds = {}
    vx_src = os.path.join(tmp, f"{tag}.vx")
    vx_vxc = os.path.join(tmp, f"{tag}.vxc")
    vx_nat = os.path.join(tmp, f"{tag}_vx_nat")
    open(vx_src, "w").write(w["vx"])
    subprocess.run([vx_cli, "compile", vx_src, "-o", vx_vxc], stdout=subprocess.DEVNULL, check=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "vidyax.py"), "native", vx_src, "-o", vx_nat], stdout=subprocess.DEVNULL, check=True)

    cmds["Vidyax AOT Native"] = [vx_nat]
    cmds["Vidyax C VM (vxvm .vxc)"] = [vxvm, vx_vxc]
    cmds["Vidyax Standalone CLI (.vx)"] = [vx_cli, vx_src]

    py_src = os.path.join(tmp, f"{tag}.py")
    open(py_src, "w").write(w["py"])
    cmds["Python 3 (CPython)"] = [sys.executable, py_src]

    node_bin = shutil.which("node")
    if node_bin:
        js_src = os.path.join(tmp, f"{tag}.js")
        open(js_src, "w").write(w["js"])
        cmds["Node.js (V8 JIT)"] = [node_bin, js_src]

    lua_bin = shutil.which("lua")
    if lua_bin:
        lua_src = os.path.join(tmp, f"{tag}.lua")
        open(lua_src, "w").write(w["lua"])
        cmds["Lua"] = [lua_bin, lua_src]

    if shutil.which("rustc"):
        rs_src = os.path.join(tmp, f"{tag}.rs")
        rs_bin = os.path.join(tmp, f"{tag}_rs")
        open(rs_src, "w").write(w["rs"])
        subprocess.run(["rustc", "-O", rs_src, "-o", rs_bin], check=True)
        cmds["Rust (rustc -O)"] = [rs_bin]

    c_src = os.path.join(tmp, f"{tag}.c")
    c_bin = os.path.join(tmp, f"{tag}_c")
    open(c_src, "w").write(w["c"])
    subprocess.run(["gcc", "-O2", c_src, "-o", c_bin], check=True)
    cmds["C (gcc -O2)"] = [c_bin]
    return cmds


def main():
    tmp = tempfile.mkdtemp(prefix="vidyax_h2h_multi_")
    try:
        meas_c = os.path.join(tmp, "meas.c")
        meas_bin = os.path.join(tmp, "meas")
        open(meas_c, "w").write(MEAS_C)
        subprocess.run(["gcc", "-O2", meas_c, "-o", meas_bin], check=True)

        vx_cli = os.path.join(ROOT, "vidyax")
        vxvm = os.path.join(ROOT, "vm", "vxvm")
        if not os.path.exists(vx_cli) or not os.path.exists(vxvm):
            subprocess.run(["make", "-C", os.path.join(ROOT, "vm"), "vxvm", "vidyax"], check=True)

        workloads = [
            ("hello", W_HELLO),
            ("recur", W_RECUR),
            ("primes", W_PRIMES),
            ("policy", W_POLICY),
        ]
        built = {tag: build_workload_cmds(tmp, tag, w, vx_cli, vxvm) for tag, w in workloads}
        runtimes = list(built["hello"].keys())

        print("| Runtime | Cold-Start | Hanoi18 + 50k | Primes (25k) | Policy Scrub (5k) | Peak RAM (Max RSS) |")
        print("| :--- | :---: | :---: | :---: | :---: | :---: |")
        for rt in runtimes:
            c_ms, _ = measure(meas_bin, built["hello"][rt], W_HELLO["expected"])
            r_ms, r_rss = measure(meas_bin, built["recur"][rt], W_RECUR["expected"])
            p_ms, p_rss = measure(meas_bin, built["primes"][rt], W_PRIMES["expected"])
            s_ms, s_rss = measure(meas_bin, built["policy"][rt], W_POLICY["expected"])
            peak_kb = max(r_rss, p_rss, s_rss)
            print(f"| **{rt}** | `{c_ms:.2f} ms` | `{r_ms:.2f} ms` | `{p_ms:.2f} ms` | `{s_ms:.2f} ms` | `{peak_kb/1024:.2f} MB` |")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
