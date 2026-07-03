# -*- coding: utf-8 -*-
"""Vidyax bytecode compiler (.vx -> .vxc) for the C VM (vm/vxvm.c).

Reuses vidyax.py's lexer/parser/type-checker/scope analysis, so the VM
inherits the exact same front-end semantics as the two Python engines.

Format .vxc (little-endian):
  magic  "VXC1"
  u8     version (=1)
  u32    nconsts, then consts:
           tag u8: 1 = NUM (f64), 2 = STR (u32 len + utf-8 bytes)
  u32    nprotos, then protos (proto 0 = top level):
           u32 name const idx (str)
           u8  nparams, then u32 const idx per param name
           u16 ndeclared, then u32 const idx per declared-local name
           u32 codelen, then code bytes

Opcodes: see OPS below (mirrored in vm/vxvm.c — keep in sync!).
Not supported in the VM yet (rejected at compile time): use ai / member
access. get() compiles but raises at runtime in the VM.
"""
import struct
import sys

import vidyax
from vidyax import VidyaxError, assigned_names

# --- opcodes (keep numbering in sync with vm/vxvm.c) ---
OPS = {
    "CONST": 1,        # u16 const idx
    "NULL": 2, "TRUE": 3, "FALSE": 4,
    "POP": 5,
    "LOAD": 6,         # u16 const idx (name str)
    "STORE": 7,        # u16 const idx (name str)
    "ADD": 8, "SUB": 9, "MUL": 10, "DIV": 11, "MOD": 12, "NEG": 13,
    "EQ": 14, "NE": 15, "LT": 16, "LE": 17, "GT": 18, "GE": 19,
    "NOT": 20,
    "JMP": 21,             # u32 absolute
    "JMP_IF_FALSE": 22,    # u32, pops
    "JIF_PEEK": 23,        # u32, peeks (for 'and')
    "JIT_PEEK": 24,        # u32, peeks (for 'or')
    "LIST": 25,        # u16 item count
    "INDEX": 26,
    "CALL": 27,        # u8 argc
    "MAKE_FUNC": 28,   # u16 proto idx
    "RET": 29,
    "PRINT": 30,
    "ASK": 31,
    "CHECK_RPT": 32,   # validate TOS is a number -> trunc int (as num)
    "CHECK_ITER": 33,  # validate TOS is list/text
    "LEN": 34,         # internal fast len (loop desugaring)
    "TRY_PUSH": 35,    # u32 catch addr
    "TRY_POP": 36,
    "HALT": 37,
}



# --- optimizer: constant folding (behavior-preserving by design) ---
def _fold(n):
    """Recursively fold literal arithmetic/comparisons. Returns a
    replacement node or the original. Never folds anything that would
    change behavior: / and % by zero stay for runtime, and floats use
    the same f64 arithmetic the VM uses."""
    t = type(n).__name__
    if t == "BinOp":
        n.l = _fold(n.l); n.r = _fold(n.r)
        lt, rt = type(n.l).__name__, type(n.r).__name__
        if lt == "Number" and rt == "Number":
            a, b = float(n.l.v), float(n.r.v)
            if n.op == "+": return vidyax.Number(a + b)
            if n.op == "-": return vidyax.Number(a - b)
            if n.op == "*": return vidyax.Number(a * b)
            if n.op == "/" and b != 0: return vidyax.Number(a / b)
            if n.op == "%" and b != 0:
                import math
                r = math.fmod(a, b)
                if r != 0 and ((r < 0) != (b < 0)):
                    r += b
                return vidyax.Number(r)
            if n.op in ("==", "!=", "<", "<=", ">", ">="):
                res = {"==": a == b, "!=": a != b, "<": a < b,
                       "<=": a <= b, ">": a > b, ">=": a >= b}[n.op]
                return vidyax.Bool(res)
        if lt == "Str" and rt == "Str" and n.op == "+":
            return vidyax.Str(n.l.v + n.r.v)
    elif t == "UnaryOp":
        n.operand = _fold(n.operand)
        ot = type(n.operand).__name__
        if n.op == "-" and ot == "Number":
            return vidyax.Number(-float(n.operand.v))
        if n.op == "not" and ot in ("Bool", "Number", "Str", "Null"):
            v = n.operand
            if ot == "Bool": return vidyax.Bool(not v.v)
            if ot == "Number": return vidyax.Bool(float(v.v) == 0)
            if ot == "Str": return vidyax.Bool(len(v.v) == 0)
            return vidyax.Bool(True)
    return n


class Proto:
    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.declared = []
        self.code = bytearray()


class Compiler:
    def __init__(self):
        self.consts = []          # list of ("num", f) / ("str", s)
        self.const_ix = {}        # key -> idx (dedupe)
        self.protos = []

    # --- const pool ---
    def const(self, kind, v):
        key = (kind, v)
        if key in self.const_ix:
            return self.const_ix[key]
        self.consts.append((kind, v))
        ix = len(self.consts) - 1
        if ix > 0xFFFF:
            raise VidyaxError("too many constants (max 65536)")
        self.const_ix[key] = ix
        return ix

    def cnum(self, x): return self.const("num", float(x))
    def cstr(self, s): return self.const("str", str(s))

    # --- emit helpers ---
    def emit(self, p, op, *operands_spec):
        p.code.append(OPS[op])
        for fmt, val in operands_spec:
            p.code += struct.pack("<" + fmt, val)

    def emit_jump(self, p, op):
        """Emit a jump with a placeholder target; returns patch position."""
        p.code.append(OPS[op])
        pos = len(p.code)
        p.code += b"\x00\x00\x00\x00"
        return pos

    def patch(self, p, pos, target=None):
        t = len(p.code) if target is None else target
        p.code[pos:pos + 4] = struct.pack("<I", t)

    # --- program ---
    def compile_program(self, ast):
        main = Proto("<main>", [])
        self.protos.append(main)
        ctx = {"loops": [], "trydepth": 0, "hidden": 0}
        self.block(main, ast.body, ctx)
        self.emit(main, "HALT")
        return self

    def block(self, p, stmts, ctx):
        for s in stmts:
            self.stmt(p, s, ctx)

    # --- statements ---
    def stmt(self, p, n, ctx):
        t = type(n).__name__
        if t == "Assign":
            self.expr(p, n.value, ctx)
            self.emit(p, "STORE", ("H", self.cstr(n.name)))
        elif t == "ExprStmt":
            self.expr(p, n.expr, ctx)
            self.emit(p, "POP")
        elif t == "Print":
            self.expr(p, n.expr, ctx)
            self.emit(p, "PRINT")
        elif t == "If":
            self.expr(p, n.cond, ctx)
            jfalse = self.emit_jump(p, "JMP_IF_FALSE")
            self.block(p, n.body, ctx)
            if n.orelse:
                jend = self.emit_jump(p, "JMP")
                self.patch(p, jfalse)
                self.block(p, n.orelse, ctx)
                self.patch(p, jend)
            else:
                self.patch(p, jfalse)
        elif t == "RepeatN":
            # $n: CHECK_RPT(count); $i: 0
            # loop: if not ($i < $n) -> end; $i: $i+1; body; jmp loop
            hid = ctx["hidden"]; ctx["hidden"] += 1
            n_name, i_name = self.cstr(f"$n{hid}"), self.cstr(f"$i{hid}")
            self.expr(p, n.count, ctx)
            self.emit(p, "CHECK_RPT")
            self.emit(p, "STORE", ("H", n_name))
            self.emit(p, "CONST", ("H", self.cnum(0)))
            self.emit(p, "STORE", ("H", i_name))
            loop = len(p.code)
            self.emit(p, "LOAD", ("H", i_name))
            self.emit(p, "LOAD", ("H", n_name))
            self.emit(p, "LT")
            jend = self.emit_jump(p, "JMP_IF_FALSE")
            self.emit(p, "LOAD", ("H", i_name))
            self.emit(p, "CONST", ("H", self.cnum(1)))
            self.emit(p, "ADD")
            self.emit(p, "STORE", ("H", i_name))
            self.loop_body(p, n.body, ctx, loop, jend)
        elif t == "ForEach":
            # $it: CHECK_ITER(src); $i: 0
            # loop: if not ($i < len($it)) -> end
            #       var: $it[$i]; $i: $i+1; body; jmp loop
            hid = ctx["hidden"]; ctx["hidden"] += 1
            it_name, i_name = self.cstr(f"$it{hid}"), self.cstr(f"$i{hid}")
            var_name = self.cstr(n.var)
            self.expr(p, n.iterable, ctx)
            self.emit(p, "CHECK_ITER")
            self.emit(p, "STORE", ("H", it_name))
            self.emit(p, "CONST", ("H", self.cnum(0)))
            self.emit(p, "STORE", ("H", i_name))
            loop = len(p.code)
            self.emit(p, "LOAD", ("H", i_name))
            self.emit(p, "LOAD", ("H", it_name))
            self.emit(p, "LEN")
            self.emit(p, "LT")
            jend = self.emit_jump(p, "JMP_IF_FALSE")
            self.emit(p, "LOAD", ("H", it_name))
            self.emit(p, "LOAD", ("H", i_name))
            self.emit(p, "INDEX")
            self.emit(p, "STORE", ("H", var_name))
            self.emit(p, "LOAD", ("H", i_name))
            self.emit(p, "CONST", ("H", self.cnum(1)))
            self.emit(p, "ADD")
            self.emit(p, "STORE", ("H", i_name))
            self.loop_body(p, n.body, ctx, loop, jend)
        elif t == "FuncDef":
            sub = Proto(n.name, list(n.params))
            sub.declared = sorted(assigned_names(n.body) - set(n.params))
            self.protos.append(sub)
            ix = len(self.protos) - 1
            if ix > 0xFFFF:
                raise VidyaxError("too many functions")
            subctx = {"loops": [], "trydepth": 0, "hidden": 0}
            self.block(sub, n.body, subctx)
            self.emit(sub, "NULL")   # falling off the end returns null
            self.emit(sub, "RET")
            self.emit(p, "MAKE_FUNC", ("H", ix))
            self.emit(p, "STORE", ("H", self.cstr(n.name)))
        elif t == "Return":
            if n.value is None:
                self.emit(p, "NULL")
            else:
                self.expr(p, n.value, ctx)
            self.emit(p, "RET")   # the VM pops this frame's try handlers
        elif t == "Break":
            self.pop_tries_to_loop(p, ctx)
            ctx["loops"][-1]["breaks"].append(self.emit_jump(p, "JMP"))
        elif t == "Continue":
            self.pop_tries_to_loop(p, ctx)
            self.emit(p, "JMP")
            p.code += struct.pack("<I", ctx["loops"][-1]["start"])
        elif t == "TryCatch":
            jtry = self.emit_jump(p, "TRY_PUSH")
            ctx["trydepth"] += 1
            self.block(p, n.try_body, ctx)
            ctx["trydepth"] -= 1
            self.emit(p, "TRY_POP")
            jend = self.emit_jump(p, "JMP")
            self.patch(p, jtry)   # catch lands here; VM pushed the error msg
            if n.err_var:
                self.emit(p, "STORE", ("H", self.cstr(n.err_var)))
            else:
                self.emit(p, "POP")
            self.block(p, n.catch_body, ctx)
            self.patch(p, jend)
        elif t == "Import":
            raise VidyaxError(
                f"'use {n.name}' is not supported in the VM yet "
                "(run it with `vidyax run` instead)")
        else:
            raise VidyaxError(f"cannot compile statement {t}")

    def loop_body(self, p, body, ctx, loop_start, jend_patch):
        ctx["loops"].append({"start": loop_start, "breaks": [],
                             "trydepth": ctx["trydepth"]})
        self.block(p, body, ctx)
        self.emit(p, "JMP")
        p.code += struct.pack("<I", loop_start)
        info = ctx["loops"].pop()
        self.patch(p, jend_patch)
        for b in info["breaks"]:
            self.patch(p, b)

    def pop_tries_to_loop(self, p, ctx):
        """break/continue that jump out of try blocks must pop handlers."""
        depth_here = ctx["trydepth"]
        depth_loop = ctx["loops"][-1]["trydepth"]
        for _ in range(depth_here - depth_loop):
            self.emit(p, "TRY_POP")

    # --- expressions ---
    def expr(self, p, n, ctx):
        n = _fold(n)
        t = type(n).__name__
        if t == "Number":
            self.emit(p, "CONST", ("H", self.cnum(n.v)))
        elif t == "Str":
            self.emit(p, "CONST", ("H", self.cstr(n.v)))
        elif t == "Bool":
            self.emit(p, "TRUE" if n.v else "FALSE")
        elif t == "Null":
            self.emit(p, "NULL")
        elif t == "ListLit":
            for item in n.items:
                self.expr(p, item, ctx)
            if len(n.items) > 0xFFFF:
                raise VidyaxError("list literal too long")
            self.emit(p, "LIST", ("H", len(n.items)))
        elif t == "Var":
            self.emit(p, "LOAD", ("H", self.cstr(n.name)))
        elif t == "Input":
            self.expr(p, n.prompt, ctx)
            self.emit(p, "ASK")
        elif t == "UnaryOp":
            self.expr(p, n.operand, ctx)
            self.emit(p, "NOT" if n.op == "not" else "NEG")
        elif t == "BinOp":
            if n.op == "and":
                self.expr(p, n.l, ctx)
                j = self.emit_jump(p, "JIF_PEEK")
                self.emit(p, "POP")
                self.expr(p, n.r, ctx)
                self.patch(p, j)
            elif n.op == "or":
                self.expr(p, n.l, ctx)
                j = self.emit_jump(p, "JIT_PEEK")
                self.emit(p, "POP")
                self.expr(p, n.r, ctx)
                self.patch(p, j)
            else:
                self.expr(p, n.l, ctx)
                self.expr(p, n.r, ctx)
                op = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV",
                      "%": "MOD", "==": "EQ", "!=": "NE", "<": "LT",
                      "<=": "LE", ">": "GT", ">=": "GE"}[n.op]
                self.emit(p, op)
        elif t == "Call":
            self.expr(p, n.callee, ctx)
            for a in n.args:
                self.expr(p, a, ctx)
            if len(n.args) > 255:
                raise VidyaxError("too many arguments")
            self.emit(p, "CALL", ("B", len(n.args)))
        elif t == "Index":
            self.expr(p, n.obj, ctx)
            self.expr(p, n.idx, ctx)
            self.emit(p, "INDEX")
        elif t == "Member":
            raise VidyaxError(
                "member access is not supported in the VM yet "
                "(run it with `vidyax run` instead)")
        else:
            raise VidyaxError(f"cannot compile expression {t}")

    # --- serialization ---
    def serialize(self):
        # Intern every name FIRST — proto names / params may never appear
        # in code, and adding consts after the count is written corrupts
        # the file.
        for p in self.protos:
            self.cstr(p.name)
            for name in p.params:
                self.cstr(name)
            for name in p.declared:
                self.cstr(name)
        out = bytearray(b"VXC1")
        out.append(1)  # version
        out += struct.pack("<I", len(self.consts))
        for kind, v in self.consts:
            if kind == "num":
                out.append(1); out += struct.pack("<d", v)
            else:
                b = v.encode("utf-8")
                out.append(2); out += struct.pack("<I", len(b)); out += b
        out += struct.pack("<I", len(self.protos))
        for p in self.protos:
            out += struct.pack("<I", self.cstr(p.name))
            out.append(len(p.params))
            for name in p.params:
                out += struct.pack("<I", self.cstr(name))
            out += struct.pack("<H", len(p.declared))
            for name in p.declared:
                out += struct.pack("<I", self.cstr(name))
            out += struct.pack("<I", len(p.code))
            out += p.code
        return bytes(out)


def compile_source(source):
    tokens = vidyax.lex(source)
    ast = vidyax.Parser(tokens).parse()
    vidyax.type_check(ast)
    return Compiler().compile_program(ast)


def compile_file(path, out_path=None):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    c = compile_source(source)
    if out_path is None:
        out_path = path.rsplit(".", 1)[0] + ".vxc"
    with open(out_path, "wb") as f:
        f.write(c.serialize())
    return out_path


# --- disassembler (debugging aid) ---
OP_NAMES = {v: k for k, v in OPS.items()}
OPERANDS = {  # op -> (size, fmt)
    "CONST": (2, "<H"), "LOAD": (2, "<H"), "STORE": (2, "<H"),
    "LIST": (2, "<H"), "MAKE_FUNC": (2, "<H"), "CALL": (1, "<B"),
    "JMP": (4, "<I"), "JMP_IF_FALSE": (4, "<I"),
    "JIF_PEEK": (4, "<I"), "JIT_PEEK": (4, "<I"), "TRY_PUSH": (4, "<I"),
}


def dis(c):
    lines = []
    for kind, v in enumerate(c.consts):
        lines.append(f"const {kind}: {v!r}")
    for pi, p in enumerate(c.protos):
        lines.append(f"\nproto {pi} '{p.name}' params={p.params} "
                     f"declared={p.declared}")
        i = 0
        while i < len(p.code):
            op = OP_NAMES.get(p.code[i], f"?{p.code[i]}")
            spec = OPERANDS.get(op)
            if spec:
                size, fmt = spec
                val = struct.unpack_from(fmt, p.code, i + 1)[0]
                extra = ""
                if op in ("CONST", "LOAD", "STORE"):
                    extra = f"   ; {c.consts[val]!r}"
                lines.append(f"  {i:5d}  {op} {val}{extra}")
                i += 1 + size
            else:
                lines.append(f"  {i:5d}  {op}")
                i += 1
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: python3 vxc.py <file.vx> [-o out.vxc] | --dis <file.vx>")
        sys.exit(1)
    try:
        if args[0] == "--dis":
            with open(args[1], encoding="utf-8") as f:
                print(dis(compile_source(f.read())))
        else:
            out = args[args.index("-o") + 1] if "-o" in args else None
            print("[Vidyax] bytecode ->", compile_file(args[0], out))
    except VidyaxError as e:
        print(e.show()); sys.exit(1)
