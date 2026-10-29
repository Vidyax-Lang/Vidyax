#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4-Engine Differential Verification Suite for Vidyax <-> Tokenectomy Sub-Cortex FFI.

Compares stdout (as raw bytes, preserving embedded NULs and UTF-8 sequences),
JSON-serialized map schemas (order-insensitively), and fail-closed security gates
across ALL FOUR Vidyax execution engines:
  1. walk   — Python AST Tree-Walker (`vidyax.py`)
  2. fast   — Python Transpiler (`vidyax.py` -> Python -> exec)
  3. vm     — C99 Bytecode Virtual Machine (`vm/vxvm`)
  4. native — AOT C Compiler (`vxnative.py` -> static ELF binary)
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vidyax
import vxc
import vxnative

VM_BIN = os.path.join(HERE, "vm", "vxvm")
CLI_PY = os.path.join(HERE, "vidyax.py")
PIN_FILE = os.path.join(HERE, "SUBCORTEX_ABI_PIN.json")
DEFAULT_SO = os.path.abspath(
    os.path.join(
        HERE, "..", "..", "tools", "tokenectomy-oss", "target",
        "subcortex", "release",
        "libtokenectomy." + ("dylib" if sys.platform == "darwin" else "so"),
    )
)


def verify_cross_repo_abi_pin():
    assert os.path.isfile(PIN_FILE), f"missing ABI pin manifest: {PIN_FILE}"
    with open(PIN_FILE, "r", encoding="utf-8") as f:
        pin = json.load(f)

    header_path = os.path.abspath(os.path.join(HERE, pin["header_relpath"]))
    cargo_toml = os.path.abspath(os.path.join(HERE, pin["provider_relpath"], "Cargo.toml"))
    assert os.path.isfile(header_path), f"missing C-ABI header at {header_path}"
    assert os.path.isfile(cargo_toml), f"missing provider Cargo.toml at {cargo_toml}"

    with open(header_path, "rb") as f:
        hdr_bytes = f.read()
    actual_sha = hashlib.sha256(hdr_bytes).hexdigest()
    assert actual_sha == pin["header_sha256"], (
        f"cross-repo C-ABI header drift detected!\n"
        f"  SUBCORTEX_ABI_PIN.json expects: {pin['header_sha256']}\n"
        f"  tokenectomy_subcortex.h actual: {actual_sha}"
    )

    hdr_text = hdr_bytes.decode("utf-8")
    expected_ver = int(pin["abi_version"])
    assert f"#define TKMY_ABI_VERSION {expected_ver}" in hdr_text, (
        f"TKMY_ABI_VERSION {expected_ver} not found in {header_path}"
    )
    assert vidyax._RT_NS["_TKMY_ABI_VERSION"] == expected_ver, (
        "vidyax.py _TKMY_ABI_VERSION drifted from SUBCORTEX_ABI_PIN.json"
    )
    for sym in pin["required_symbols"]:
        assert sym in hdr_text, f"required FFI symbol {sym!r} missing from {header_path}"

    limits = pin["limits"]
    assert int(limits["max_input_bytes"]) == 1048576
    assert int(limits["max_ast_bytes"]) == 262144
    assert int(limits["max_path_bytes"]) == 4096
    assert "#define TKMY_MAX_AST_BYTES (256 * 1024)" in hdr_text, (
        f"TKMY_MAX_AST_BYTES (256 * 1024) missing from {header_path}"
    )

    with open(cargo_toml, "r", encoding="utf-8") as f:
        cargo_txt = f.read()
    assert f'name = "{pin["provider_crate"]}"' in cargo_txt, (
        f"provider crate name {pin['provider_crate']!r} not found in {cargo_toml}"
    )
    print(f"  PASS [cross-repo ABI pin] v{expected_ver} sha256={actual_sha[:16]}...")


_SANITIZER_MARKERS = (
    b"AddressSanitizer",
    b"LeakSanitizer",
    b"UndefinedBehaviorSanitizer",
    b"Sanitizer:",
    b"runtime error:",
)


def _strip_vidyax_err(raw_stdout: bytes, raw_stderr: bytes, returncode: int):
    for marker in _SANITIZER_MARKERS:
        if marker in raw_stderr or marker in raw_stdout:
            raise AssertionError(
                "Sanitizer fault/leak detected in engine execution!\n"
                f"  returncode: {returncode}\n"
                f"  stderr:\n{raw_stderr.decode('utf-8', 'replace')}\n"
                f"  stdout:\n{raw_stdout.decode('utf-8', 'replace')}"
            )
    if returncode == 0:
        return raw_stdout, None
    text_out = raw_stdout.decode("utf-8", "replace")
    lines = text_out.rstrip("\n").split("\n")
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if line.startswith("[Vidyax] "):
            msg = line[len("[Vidyax] "):]
            for prefix in ("runtime error, ", "syntax error, ", "type error, ", "name error, "):
                if msg.startswith(prefix):
                    msg = msg[len(prefix):]
            if msg.startswith("line "):
                colon = msg.find(": ")
                if colon != -1:
                    msg = msg[colon + 2:]
            kept = ("\n".join(lines[:idx]) + "\n").encode("utf-8") if idx > 0 else b""
            return kept, msg
    err_fallback = raw_stderr.decode("utf-8", "replace").strip()
    return raw_stdout, err_fallback or f"exited with {returncode}"


def run_walk(src: str, env=None):
    with tempfile.NamedTemporaryFile("w", suffix=".vx", encoding="utf-8", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, "-B", CLI_PY, "walk", path],
            capture_output=True,
            env=env,
            timeout=30,
        )
        return _strip_vidyax_err(r.stdout, r.stderr, r.returncode)
    finally:
        os.unlink(path)


def run_fast(src: str, env=None):
    with tempfile.NamedTemporaryFile("w", suffix=".vx", encoding="utf-8", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, "-B", CLI_PY, "run", path],
            capture_output=True,
            env=env,
            timeout=30,
        )
        return _strip_vidyax_err(r.stdout, r.stderr, r.returncode)
    finally:
        os.unlink(path)


def run_vm(src: str, allow_fs=False, extra_flags=(), env=None):
    with tempfile.NamedTemporaryFile(suffix=".vxc", delete=False) as f:
        vxc_path = f.name
    try:
        c = vxc.compile_source(src)
    except vidyax.VidyaxError as e:
        os.unlink(vxc_path)
        return b"", e.msg
    try:
        with open(vxc_path, "wb") as f:
            f.write(c.serialize())
        flags = list(extra_flags)
        if allow_fs:
            flags.append("--allow-fs")
        r = subprocess.run(
            [VM_BIN, *flags, vxc_path],
            capture_output=True,
            env=env,
            timeout=30,
        )
        return _strip_vidyax_err(r.stdout, r.stderr, r.returncode)
    finally:
        if os.path.exists(vxc_path):
            os.unlink(vxc_path)


def run_native(src: str, allow_fs=False, extra_flags=(), env=None):
    with tempfile.TemporaryDirectory() as td:
        vx_path = os.path.join(td, "prog.vx")
        bin_path = os.path.join(td, "prog_bin")
        with open(vx_path, "w", encoding="utf-8") as f:
            f.write(src)
        try:
            if env is not None:
                code = (
                    "import sys; sys.path.insert(0, %r); import vxnative; "
                    "vxnative.native_file(%r, out=%r)" % (HERE, vx_path, bin_path)
                )
                cr = subprocess.run(
                    [sys.executable, "-B", "-c", code],
                    capture_output=True,
                    env=env,
                    timeout=60,
                )
                if cr.returncode != 0:
                    return b"", cr.stderr.decode("utf-8", "replace").strip()
            else:
                vxnative.native_file(vx_path, out=bin_path)
        except vidyax.VidyaxError as e:
            return b"", e.msg
        flags = list(extra_flags)
        if allow_fs:
            flags.append("--allow-fs")
        r = subprocess.run(
            [bin_path, *flags],
            capture_output=True,
            env=env,
            timeout=30,
        )
        return _strip_vidyax_err(r.stdout, r.stderr, r.returncode)


def assert_all_4_engines(name: str, src: str, allow_fs=False, expected_out: bytes = None, expected_err: str = None):
    results = {
        "walk": run_walk(src),
        "fast": run_fast(src),
        "vm": run_vm(src, allow_fs=allow_fs, extra_flags=("--gc-stress",)),
        "native": run_native(src, allow_fs=allow_fs, extra_flags=("--gc-stress",)),
    }
    if expected_err is not None:
        for eng, (out, err) in results.items():
            assert err is not None, f"[{name}] engine '{eng}' succeeded unexpectedly (out={out!r})"
            assert expected_err in err, (
                f"[{name}] engine '{eng}' error {err!r} did not contain {expected_err!r}"
            )
        print(f"  PASS [4-engines err] {name}")
        return

    ref_out, ref_err = results["vm"]
    for eng, (out, err) in results.items():
        assert err is None, f"[{name}] engine '{eng}' failed with error: {err!r}"
        assert out == ref_out, (
            f"[{name}] engine '{eng}' stdout mismatch vs 'vm':\n"
            f"  {eng}: {out!r}\n  vm  : {ref_out!r}"
        )
    if expected_out is not None:
        assert ref_out == expected_out, (
            f"[{name}] stdout did not match expected:\n"
            f"  got : {ref_out!r}\n  want: {expected_out!r}"
        )
    print(f"  PASS [4-engines out] {name}")


def assert_all_4_engines_json_lines(name: str, src: str, expected_objs: list):
    """Compares line-delimited JSON objects order-insensitively across all 4 engines,
    decoupling map schema verification from C OMap FNV-1a hash-bucket slot order."""
    results = {
        "walk": run_walk(src),
        "fast": run_fast(src),
        "vm": run_vm(src, extra_flags=("--gc-stress",)),
        "native": run_native(src, extra_flags=("--gc-stress",)),
    }
    for eng, (out, err) in results.items():
        assert err is None, f"[{name}] engine '{eng}' failed: {err!r}"
        lines = [ln for ln in out.decode("utf-8").splitlines() if ln.strip()]
        parsed = [json.loads(ln) for ln in lines]
        assert parsed == expected_objs, (
            f"[{name}] engine '{eng}' JSON objects mismatch:\n"
            f"  got : {parsed!r}\n  want: {expected_objs!r}"
        )
    print(f"  PASS [4-engines json] {name}")


def test_noop_stub_fails_closed():
    """Compiles a native binary referencing all 3 subcortex builtins FORCED with
    -DVX_SUBCORTEX_NOOP (no libtokenectomy.a) and verifies every stub raises an
    explicit runtime error rather than returning empty strings or {valid: true}."""
    src = r'''
errs: []
try:
    subcortex_redact("token=abc1234567890")
catch e1:
    push(errs, e1)
try:
    subcortex_prune("trace")
catch e2:
    push(errs, e2)
try:
    subcortex_audit_ast("a.py", "x = 1\n")
catch e3:
    push(errs, e3)
print len(errs)
for m in errs:
    print m
# Finally invoke uncaught to prove non-zero process exit
subcortex_audit_ast("a.py", "x = 1\n")
'''
    c = vxc.compile_source(src)
    c.serialize()
    csrc = vxnative.emit_c(c)
    vmdir = os.path.join(HERE, "vm")
    mods = [
        os.path.join(vmdir, m)
        for m in ("value.c", "gc.c", "net.c", "builtins.c", "task.c",
                  "vx_model_bridge.c", "vx_subcortex_bridge.c")
    ]
    cc = os.environ.get("CC", "cc")
    curl = shutil.which("pkg-config") and subprocess.run(
        ["pkg-config", "--exists", "libcurl"]).returncode == 0
    with tempfile.TemporaryDirectory() as td:
        cfile = os.path.join(td, "noop_probe.c")
        bin_path = os.path.join(td, "noop_probe")
        with open(cfile, "w", encoding="utf-8") as f:
            f.write(csrc)
        cmd = [cc, "-O2", "-DVXVM_RUNTIME", "-DVX_SUBCORTEX_NOOP", "-I", vmdir]
        if curl:
            curl_cflags = subprocess.run(
                ["pkg-config", "--cflags", "libcurl"], capture_output=True, text=True
            ).stdout.split()
            curl_libs = subprocess.run(
                ["pkg-config", "--libs", "libcurl"], capture_output=True, text=True
            ).stdout.split()
            cmd += ["-DVX_HAVE_CURL", *curl_cflags, cfile, *mods, "-o", bin_path, "-lm", "-lpthread", *curl_libs]
        else:
            cmd += [cfile, *mods, "-o", bin_path, "-lm", "-lpthread"]
        cr = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert cr.returncode == 0, f"VX_SUBCORTEX_NOOP compile failed: {cr.stderr}"

        rr = subprocess.run([bin_path], capture_output=True, text=True, timeout=15)
        assert rr.returncode != 0, "VX_SUBCORTEX_NOOP binary exited 0 on uncaught stub call!"
        expected_lines = [
            "3",
            "subcortex: static library was not linked at compile time",
            "subcortex: static library was not linked at compile time",
            "subcortex: static library was not linked at compile time",
            "[Vidyax] subcortex: static library was not linked at compile time",
        ]
        assert rr.stdout.strip().splitlines() == expected_lines, (
            f"unexpected VX_SUBCORTEX_NOOP output: {rr.stdout!r}"
        )
    print("  PASS [VX_SUBCORTEX_NOOP] all 3 stubs fail closed with explicit error & non-zero exit")


def test_library_loading_security_gates():
    assert os.path.isfile(DEFAULT_SO), f"missing staged library at {DEFAULT_SO}"
    with open(DEFAULT_SO, "rb") as f:
        good_sha256 = hashlib.sha256(f.read()).hexdigest()

    probe_src = 'print subcortex_redact("token=abc1234567890")\n'

    # 1. Missing library -> fail closed (zero Python fallback)
    env_missing = dict(os.environ)
    env_missing["VX_SUBCORTEX_LIB"] = "/nonexistent_dir_7f9a/libtokenectomy.so"
    for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
        _, err = runner(probe_src, env=env_missing)
        assert err is not None and "subcortex: failed to load library" in err, (
            f"engine '{eng_name}' did NOT fail closed on missing .so: {err!r}"
        )

    # 2. Relative path in VX_SUBCORTEX_LIB -> rejected (blocks LD_LIBRARY_PATH / CWD hijack)
    env_rel = dict(os.environ)
    env_rel["VX_SUBCORTEX_LIB"] = "libtokenectomy.so"
    for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
        _, err = runner(probe_src, env=env_rel)
        assert err is not None and "must be an absolute path" in err, (
            f"engine '{eng_name}' did NOT reject relative VX_SUBCORTEX_LIB: {err!r}"
        )

    with tempfile.TemporaryDirectory() as td:
        # 3. Trusted 0700 parent dir + 0755 .so + valid VX_SUBCORTEX_SHA256 -> succeeds
        trusted_dir = os.path.join(td, "trusted_dir")
        os.mkdir(trusted_dir, 0o700)
        os.chmod(trusted_dir, 0o700)
        trusted_so = os.path.join(trusted_dir, "libtokenectomy.so")
        shutil.copyfile(DEFAULT_SO, trusted_so)
        os.chmod(trusted_so, 0o755)

        env_good_sha = dict(os.environ)
        env_good_sha["VX_SUBCORTEX_LIB"] = trusted_so
        env_good_sha["VX_SUBCORTEX_SHA256"] = good_sha256
        for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
            out, err = runner(probe_src, env=env_good_sha)
            assert err is None and out == b"token=[REDACTED]\n", (
                f"engine '{eng_name}' failed with valid pinned path + SHA-256: err={err!r} out={out!r}"
            )

        # 4. Mismatched VX_SUBCORTEX_SHA256 -> rejected fail-closed
        env_bad_sha = dict(env_good_sha)
        env_bad_sha["VX_SUBCORTEX_SHA256"] = "0" * 64
        for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
            _, err = runner(probe_src, env=env_bad_sha)
            assert err is not None and "SHA-256" in err, (
                f"engine '{eng_name}' did NOT reject mismatched SHA-256: {err!r}"
            )

        # 5. World-writable library file (0777) inside trusted 0700 parent -> rejected fail-closed
        writable_so = os.path.join(trusted_dir, "writable.so")
        shutil.copyfile(DEFAULT_SO, writable_so)
        os.chmod(writable_so, 0o777)
        env_writable_file = dict(os.environ)
        env_writable_file["VX_SUBCORTEX_LIB"] = writable_so
        for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
            _, err = runner(probe_src, env=env_writable_file)
            assert err is not None and "group/world-writable" in err, (
                f"engine '{eng_name}' did NOT reject world-writable .so: {err!r}"
            )

        # 6. Library inside world-writable parent directory (0777, e.g. /tmp staging) -> rejected fail-closed
        world_dir = os.path.join(td, "world_writable_dir")
        os.mkdir(world_dir, 0o777)
        os.chmod(world_dir, 0o777)
        staged_in_world = os.path.join(world_dir, "libtokenectomy.so")
        shutil.copyfile(DEFAULT_SO, staged_in_world)
        os.chmod(staged_in_world, 0o755)
        env_world_dir = dict(os.environ)
        env_world_dir["VX_SUBCORTEX_LIB"] = staged_in_world
        for eng_name, runner in (("walk", run_walk), ("fast", run_fast), ("vm", run_vm)):
            _, err = runner(probe_src, env=env_world_dir)
            assert err is not None and "group/world-writable" in err, (
                f"engine '{eng_name}' did NOT reject world-writable parent dir: {err!r}"
            )

    # 7. Native static library path checks (missing + relative)
    bad_stat_env = dict(os.environ)
    bad_stat_env["VX_SUBCORTEX_STATIC_LIB"] = "/nonexistent_dir_7f9a/libtokenectomy.a"
    _, nat_err1 = run_native(probe_src, env=bad_stat_env)
    assert nat_err1 is not None and "subcortex static library not found" in nat_err1

    rel_stat_env = dict(os.environ)
    rel_stat_env["VX_SUBCORTEX_STATIC_LIB"] = "relative/libtokenectomy.a"
    _, nat_err2 = run_native(probe_src, env=rel_stat_env)
    assert nat_err2 is not None and "must be an absolute path" in nat_err2

    print("  PASS [library security gates] abs-path, owner/0022 mode, parent dir, SHA-256 pin")


def main():
    if "--check-pin" in sys.argv[1:]:
        verify_cross_repo_abi_pin()
        return

    assert os.path.isfile(VM_BIN), f"vxvm binary missing at {VM_BIN}; run `make -C engines/vidyax/vm`"
    print("Running 4-engine Sub-Cortex FFI differential suite (walk, fast, vm, native)...")

    # 0. Cross-repo ABI & header SHA-256 pin verification
    verify_cross_repo_abi_pin()

    # 1. Empty inputs across all 3 FFI functions
    assert_all_4_engines(
        "empty_inputs",
        r'''
r1: subcortex_redact("")
r2: subcortex_prune("")
a1: subcortex_audit_ast("ok.py", "")
a2: subcortex_audit_ast("", "x = 1")
print [len(r1), len(r2), a1["valid"], a1["code"], a1["status"], a2["valid"], a2["code"], a2["status"]]
''',
        expected_out=b"[0, 0, true, 0, OK, false, 1, INVALID_INPUT]\n",
    )

    # 2. Outer NUL preservation + mid-secret NUL injection defense + invalid UTF-8 binary payloads
    with tempfile.TemporaryDirectory() as td:
        nul_secret_file = os.path.join(td, "nul_secret.bin")
        with open(nul_secret_file, "wb") as f:
            f.write(
                b"head\x00"
                b"tok=sk-proj-12345\x00abcdef12345678901234 "
                b"token=abc\x00def "
                b"\xff\xfe "
                b"url=postgres://admin:hun\x00ter2@10.0.0.1:5432/prod\x00attached "
                b"\x00tail"
            )

        nul_trace_file = os.path.join(td, "nul_trace.bin")
        with open(nul_trace_file, "wb") as f:
            f.write(
                b"Error: crash\x00tag99 \xff\n"
                b"    at internal (/srv/node_modules/express/lib/router.js:12:4)\n"
                b"    at checkout (/srv/src/checkout.ts:77:9)\n"
            )

        nul_code_file = os.path.join(td, "nul_code.py")
        with open(nul_code_file, "wb") as f:
            f.write(b"x = 1\x00y = 2\n")

        nul_path_file = os.path.join(td, "nul_path.bin")
        with open(nul_path_file, "wb") as f:
            f.write(b"bad\x00path.py")

        assert_all_4_engines(
            "mid_secret_nul_injection_and_outer_nul_preservation",
            f'''
raw: readfile({json.dumps(nul_secret_file)})
clean: subcortex_redact(raw)
print clean
''',
            allow_fs=True,
            expected_out=(
                b"head\x00"
                b"tok=[OPENAI_KEY_REDACTED] "
                b"token=[REDACTED] "
                b"\xef\xbf\xbd\xef\xbf\xbd "
                b"url=[CONNECTION_STRING_REDACTED] "
                b"\x00tail\n"
            ),
        )

        nul_proc_env_file = os.path.join(td, "proc_environ.bin")
        with open(nul_proc_env_file, "wb") as f:
            f.write(
                b"PATH=/usr/bin\x00TOKEN=abc12345\x00HOME=/root\x00USER=nans\n"
                b"APP_ENV=prod\x00DATABASE_URL=postgres://svc:hunter2@db:5432/app\x00HOME=/root\x00LANG=C\n"
                b"worker\x00--api_key=sec99\x00--port\x008080"
            )
        assert_all_4_engines(
            "nul_delimited_environ_and_cmdline_over_redact_tradeoff",
            f'''
raw: readfile({json.dumps(nul_proc_env_file)})
print subcortex_redact(raw)
''',
            allow_fs=True,
            expected_out=(
                b"PATH=/usr/bin\x00TOKEN=[REDACTED]=/root\x00USER=nans\n"
                b"APP_ENV=prod\x00DATABASE_URL=[CONNECTION_STRING_REDACTED]\n"
                b"worker\x00--api_key=[REDACTED]\n"
            ),
        )

        assert_all_4_engines(
            "embedded_nul_and_invalid_utf8_prune",
            f'''
raw: readfile({json.dumps(nul_trace_file)})
pruned: subcortex_prune(raw)
print pruned
''',
            allow_fs=True,
            expected_out=(
                b"Error: crash\x00tag99 \xef\xbf\xbd\n"
                b"    at checkout (/srv/src/checkout.ts:77:9)\n"
            ),
        )

        assert_all_4_engines(
            "embedded_nul_in_audit_ast_code_and_path",
            f'''
bad_code: readfile({json.dumps(nul_code_file)})
bad_path: readfile({json.dumps(nul_path_file)})
r_code: subcortex_audit_ast("mod.py", bad_code)
r_path: subcortex_audit_ast(bad_path, "x = 1\\n")
print [r_code["valid"], r_code["code"], r_code["status"], r_path["valid"], r_path["code"], r_path["status"]]
''',
            allow_fs=True,
            expected_out=b"[false, 1, INVALID_INPUT, false, 1, INVALID_INPUT]\n",
        )

        bad_utf8_py = os.path.join(td, "bad_utf8.py")
        with open(bad_utf8_py, "wb") as f:
            f.write(b"x = 1 # \xff\xfe\n")
        raw_utf8_src = f'''
raw: readfile({json.dumps(bad_utf8_py)})
r: subcortex_audit_ast("mod.py", raw)
print [r["valid"], r["code"], r["status"]]
'''
        vm_out, vm_err = run_vm(raw_utf8_src, allow_fs=True)
        nat_out, nat_err = run_native(raw_utf8_src, allow_fs=True)
        assert vm_err is None and nat_err is None
        assert vm_out == nat_out == b"[false, 1, INVALID_INPUT]\n"

        surrogate_raw = b"x = 1 # \xff\xfe\n".decode("utf-8", "surrogateescape")
        py_res = vidyax.BUILTINS["subcortex_audit_ast"]("mod.py", surrogate_raw)
        assert (py_res["valid"], py_res["code"], py_res["status"]) == (False, 1, "INVALID_INPUT")
        print("  PASS [raw invalid UTF-8 audit_ast] vm + native + Python ctypes surrogateescape")

    # 3. Multi-byte Unicode (Emoji, CJK, Accents) — order-insensitive map check
    assert_all_4_engines(
        "multibyte_unicode_parity",
        r'''
msg: "🔐 Kunci 東京 café: sk-proj-1234567890abcdefghijklmnop 🚀"
print subcortex_redact(msg)
py_u: "def hitung_gaji(nama):\n    pesan = 'Halo 東京 🚀 café'\n    return pesan\n"
r_u: subcortex_audit_ast("gaji.py", py_u)
print [r_u["valid"], r_u["code"], r_u["status"], r_u["error"]]
''',
        expected_out=(
            "🔐 Kunci 東京 café: [OPENAI_KEY_REDACTED] 🚀\n"
            "[true, 0, OK, ]\n"
        ).encode("utf-8"),
    )

    # 4. Order-insensitive JSON schema & polyglot grammar checks under `sandbox deny fs, net`
    assert_all_4_engines_json_lines(
        "audit_ast_explicit_4_field_schema_order_insensitive",
        r'''
sandbox deny fs, net:
    print json_string(subcortex_audit_ast("/no/such/dir/app.rs", "pub fn f(x: i32) -> i32 { x + 1 }\n"))
    print json_string(subcortex_audit_ast("lazy.py", "def f():\n    # ... rest of code\n    pass\n"))
    print json_string(subcortex_audit_ast("mod.zig", "const x = 1;"))
''',
        expected_objs=[
            {"valid": True, "code": 0, "status": "OK", "error": ""},
            {
                "valid": False,
                "code": 4,
                "status": "LAZY_PLACEHOLDER",
                "error": "anti-hallucination violation: lazy placeholder comment detected",
            },
            {
                "valid": False,
                "code": 2,
                "status": "UNKNOWN_LANG",
                "error": "unsupported or disabled language extension",
            },
        ],
    )

    assert_all_4_engines(
        "polyglot_statuses_sorted_keys_and_sandbox_deny_fs",
        r'''
sandbox deny fs, net:
    r_py: subcortex_audit_ast("/no/such/dir/app.py", "def f(x):\n    return x * 2\n")
    r_js: subcortex_audit_ast("/no/such/dir/app.js", "function f(x) { return x + 1; }\n")
    r_ts: subcortex_audit_ast("/no/such/dir/app.ts", "export const f = (x: number): number => x;\n")
    r_tsx: subcortex_audit_ast("/no/such/dir/app.tsx", "export const View = () => <div>ok</div>;\n")
    r_rs: subcortex_audit_ast("/no/such/dir/app.rs", "pub fn f(x: i32) -> i32 { x + 1 }\n")
    print [r_py["code"], r_js["code"], r_ts["code"], r_tsx["code"], r_rs["code"]]
    print sort(keys(r_rs))

    r_syn: subcortex_audit_ast("broken.py", "def broken(:\n    return 1\n")
    print [r_syn["valid"], r_syn["code"], r_syn["status"], contains(r_syn["error"], "line 1")]

    r_lazy1: subcortex_audit_ast("lazy.py", "def f():\n    # ... rest of code\n    pass\n")
    r_lazy2: subcortex_audit_ast("lazy.ts", "function f() {\n  // ... existing code\n}\n")
    r_lazy3: subcortex_audit_ast("lazy.rs", "pub fn f() {\n  /* ... unchanged */\n}\n")
    print [r_lazy1["status"], r_lazy2["status"], r_lazy3["status"]]

    r_unk1: subcortex_audit_ast("mod.zig", "const x = 1;")
    r_unk2: subcortex_audit_ast("Makefile", "all:\n\techo hi\n")
    print [r_unk1["code"], r_unk1["status"], r_unk2["code"], r_unk2["status"]]
''',
        allow_fs=False,
        expected_out=(
            "[0, 0, 0, 0, 0]\n"
            "[code, error, status, valid]\n"
            "[false, 3, SYNTAX_ERROR, true]\n"
            "[LAZY_PLACEHOLDER, LAZY_PLACEHOLDER, LAZY_PLACEHOLDER]\n"
            "[2, UNKNOWN_LANG, 2, UNKNOWN_LANG]\n"
        ).encode("utf-8"),
    )

    # 5. Exact size cap boundaries:
    #    - redact / prune_log: 1 MiB (1,048,576 B) OK, 1,048,577 B TOO_LARGE
    #    - audit_ast code:     256 KiB (262,144 B) OK (both comments & dense functions), 262,145 B & 1 MiB TOO_LARGE
    #    - audit_ast path:     4 KiB (4,096 B) OK, 4,097 B TOO_LARGE
    assert_all_4_engines(
        "exact_size_cap_boundaries_1mib_256kib_and_4kib",
        r'''
blk_256k: "#"
rpt 18:
    blk_256k: blk_256k + blk_256k

blk_1m: blk_256k + blk_256k + blk_256k + blk_256k

unit: "def f(a, b):\n    return a + b\n"
dense: unit
rpt 13:
    dense: dense + dense
pad_len: 262144 - len(dense)
dense_256k: dense + slice(blk_256k, 0, pad_len - 1) + "\n"

ok_red: subcortex_redact(blk_1m)
ok_ast_comment: subcortex_audit_ast("cap.py", blk_256k)
ok_ast_dense: subcortex_audit_ast("dense.py", dense_256k)

over_1m: blk_1m + "#"
err_red: ""
try:
    subcortex_redact(over_1m)
catch e1:
    err_red: e1

err_prn: ""
try:
    subcortex_prune(over_1m)
catch e2:
    err_prn: e2

over_ast_256k: subcortex_audit_ast("cap.py", blk_256k + "#")
over_ast_1m: subcortex_audit_ast("cap.py", blk_1m)

p: "a"
rpt 12:
    p: p + p
p_exact: slice(p, 0, 4093) + ".py"
p_over: slice(p, 0, 4094) + ".py"
pa_ok: subcortex_audit_ast(p_exact, "x = 1\n")
pa_over: subcortex_audit_ast(p_over, "x = 1\n")

print [len(ok_red), len(dense_256k), ok_ast_comment["code"], ok_ast_comment["status"], ok_ast_dense["code"], ok_ast_dense["status"]]
print err_red
print err_prn
print [over_ast_256k["valid"], over_ast_256k["code"], over_ast_256k["status"], over_ast_1m["code"], over_ast_1m["status"]]
print [pa_ok["code"], pa_ok["status"], pa_over["code"], pa_over["status"]]
''',
        expected_out=(
            "[1048576, 262144, 0, OK, 0, OK]\n"
            "subcortex_redact() failed: TOO_LARGE\n"
            "subcortex_prune() failed: TOO_LARGE\n"
            "[false, 5, TOO_LARGE, 5, TOO_LARGE]\n"
            "[0, OK, 5, TOO_LARGE]\n"
        ).encode("utf-8"),
    )

    # 6. Arity & argument type error parity across all 4 engines
    assert_all_4_engines(
        "arity_and_type_error_parity",
        r'''
errs: []
try:
    subcortex_redact()
catch e:
    push(errs, e)
try:
    subcortex_redact(123)
catch e:
    push(errs, e)
try:
    subcortex_prune("a", "b")
catch e:
    push(errs, e)
try:
    subcortex_audit_ast("a.py")
catch e:
    push(errs, e)
try:
    subcortex_audit_ast("a.py", null)
catch e:
    push(errs, e)
for msg in errs:
    print msg
''',
        expected_out=(
            "subcortex_redact() needs 1 text value\n"
            "subcortex_redact() needs 1 text value\n"
            "subcortex_prune() needs 1 text value\n"
            "subcortex_audit_ast() needs 2 text values (path, code)\n"
            "subcortex_audit_ast() needs 2 text values (path, code)\n"
        ).encode("utf-8"),
    )

    # 7. Reserved builtin name cannot be shadowed
    assert_all_4_engines(
        "reserved_builtin_shadowing_rejected",
        r'''
func subcortex_redact(x):
    return x
''',
        expected_err="'subcortex_redact' is a built-in function name",
    )

    # 8. First-class indirect / dynamic dispatch via dict & higher-order function across all 4 engines
    assert_all_4_engines(
        "first_class_dynamic_dispatch_parity",
        r'''
func invoke1(fn, arg):
    return fn(arg)

func invoke2(fn, a, b):
    return fn(a, b)

table: {"r": subcortex_redact, "p": subcortex_prune, "a": subcortex_audit_ast}
out_r: invoke1(table["r"], "token=abc1234567890")
out_p: invoke1(table["p"], "Error: boom\n    at x (/app/node_modules/pkg/i.js:1:1)\n    at y (/app/src/m.ts:2:3)\n")
out_a: invoke2(table["a"], "m.py", "def ok():\n    return 7\n")
print [out_r, contains(out_p, "node_modules"), contains(out_p, "src/m.ts"), out_a["valid"], out_a["status"]]
''',
        expected_out=b"[token=[REDACTED], false, true, true, OK]\n",
    )

    # 9. Concurrent `go` / `wait` tasks across all 4 engines
    assert_all_4_engines(
        "concurrent_go_tasks_subcortex",
        r'''
func worker_py(n):
    r: subcortex_audit_ast("job.py", "def f(x):\n    return x + 1\n")
    s: subcortex_redact("k=sk-proj-1234567890abcdefghijklmnop")
    return [n, r["code"], s]

func worker_rs(n):
    r: subcortex_audit_ast("job.rs", "pub fn f(x: i32) -> i32 { x }\n")
    return [n, r["code"], r["status"]]

t1: go worker_py(1)
t2: go worker_rs(2)
t3: go worker_py(3)
t4: go worker_rs(4)
print [wait(t1), wait(t2), wait(t3), wait(t4)]
''',
        expected_out=(
            "[[1, 0, k=[OPENAI_KEY_REDACTED]], [2, 0, OK], "
            "[3, 0, k=[OPENAI_KEY_REDACTED]], [4, 0, OK]]\n"
        ).encode("utf-8"),
    )

    # 10. Library loading security gates (Item #3) & VX_SUBCORTEX_NOOP fail-closed stub (Item #6)
    test_library_loading_security_gates()
    test_noop_stub_fails_closed()

    # 11. Calibrated VM fuel budget (--max-instr) and memory cap (--max-mem) defenses on Engine 3 (vxvm)
    # Even a small 156 B audit_ast call (~47 us, ~4,200 equivalent VM instructions) must trip a tight 2,000-instr budget!
    small_fuel_src = r'''
r: subcortex_audit_ast("fuel.py", "def f(x):\n    return x + 1\n")
print r["status"]
'''
    _, small_fuel_err = run_vm(small_fuel_src, extra_flags=("--max-instr", "2000"))
    assert small_fuel_err is not None and "instruction limit exceeded" in small_fuel_err, (
        f"expected calibrated VM instruction limit error on small AST call, got {small_fuel_err!r}"
    )

    large_fuel_src = r'''
s: "#"
rpt 16:
    s: s + s
r: subcortex_audit_ast("fuel.py", s)
print r["status"]
'''
    _, large_fuel_err = run_vm(large_fuel_src, extra_flags=("--max-instr", "500000"))
    assert large_fuel_err is not None and "instruction limit exceeded" in large_fuel_err, (
        f"expected calibrated VM instruction limit error on 64 KiB AST payload, got {large_fuel_err!r}"
    )

    payload_16k = "x" * 16384
    mem_src = f'''
s: "{payload_16k}"
print "REACHED_FFI"
out: subcortex_redact(s)
print len(out)
'''
    mem_out, mem_err = run_vm(mem_src, extra_flags=("--max-mem", "45000"))
    assert mem_out == b"REACHED_FFI\n" and mem_err is not None and "memory limit exceeded" in mem_err, (
        f"expected VM memory limit error strictly inside subcortex_buf_into_ostr, got out={mem_out!r} err={mem_err!r}"
    )

    # Caught --max-mem inside try/catch must also free the Rust-allocated tkmy_buf before longjmp
    # and leave GC state consistent under --gc-stress.
    caught_mem_src = f'''
s: "{payload_16k}"
caught: ""
try:
    out: subcortex_redact(s)
    print len(out)
catch e:
    caught: e
print contains(caught, "memory limit exceeded")
'''
    cm_out, cm_err = run_vm(caught_mem_src, extra_flags=("--max-mem", "45000", "--gc-stress"))
    assert cm_err is None and cm_out == b"true\n", (
        f"expected clean caught --max-mem longjmp with zero leak, got out={cm_out!r} err={cm_err!r}"
    )
    print("  PASS [vm resource budgets] calibrated --max-instr fuel, --max-mem & longjmp buffer cleanup")

    print("\nALL 4-ENGINE SUB-CORTEX DIFFERENTIAL TESTS PASSED (walk, fast, vm, native)!")


if __name__ == "__main__":
    main()
