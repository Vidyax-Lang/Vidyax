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


def _refs_in(stmts):
    """Every Var name referenced anywhere in these statements, descending
    into nested function bodies too. If a nested function mentions name X
    and X is a local of the enclosing function, then X is captured."""
    out = set()

    def ex(e):
        if e is None:
            return
        t = type(e).__name__
        if t == "Var":
            out.add(e.name)
        elif t == "Input":
            ex(e.prompt)
        elif t == "UnaryOp":
            ex(e.operand)
        elif t == "BinOp":
            ex(e.l); ex(e.r)
        elif t == "Call":
            ex(e.callee)
            for a in e.args:
                ex(a)
        elif t == "Index":
            ex(e.obj); ex(e.idx)
        elif t == "Member":
            ex(e.obj)
        elif t == "ListLit":
            for it in e.items:
                ex(it)

    def st(s):
        t = type(s).__name__
        if t == "Assign":
            ex(s.value); out.add(s.name)
        elif t in ("ExprStmt", "Print"):
            ex(s.expr)
        elif t == "If":
            ex(s.cond)
            for x in s.body: st(x)
            for x in s.orelse: st(x)
        elif t == "RepeatN":
            ex(s.count)
            for x in s.body: st(x)
        elif t == "ForEach":
            ex(s.iterable); out.add(s.var)
            for x in s.body: st(x)
        elif t == "TryCatch":
            for x in s.try_body: st(x)
            if s.err_var:
                out.add(s.err_var)
            for x in s.catch_body: st(x)
        elif t == "FuncDef":
            for x in s.body: st(x)   # descend: nested-nested captures count
        elif t == "Return":
            ex(s.value)
        elif t == "Import":
            out.add(s.name)

    for s in stmts:
        st(s)
    return out


def escaping_names(body):
    """Names referenced by a function nested directly or transitively in
    `body`. A local of this function that appears here escapes: some inner
    function can outlive this one and still needs it, so it must live on
    the heap. Everything else can live in a fast stack slot.

    Conservative: if a nested function has its own local shadowing the same
    name, we still mark it escaping. That only costs a little speed, never
    correctness."""
    caught = set()

    def walk(stmts):
        for s in stmts:
            t = type(s).__name__
            if t == "FuncDef":
                caught.update(_refs_in(s.body))
            elif t == "If":
                walk(s.body); walk(s.orelse)
            elif t == "RepeatN":
                walk(s.body)
            elif t == "ForEach":
                walk(s.body)
            elif t == "TryCatch":
                walk(s.try_body); walk(s.catch_body)

    walk(body)
    return caught

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
    "LOAD_SLOT": 38,   # u16 slot index (direct stack access, no lookup)
    "STORE_SLOT": 39,  # u16 slot index
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



# operand byte-width per opcode (for the peephole pass)
_OPSIZE = {
    OPS["CONST"]: 2, OPS["LOAD"]: 2, OPS["STORE"]: 2,
    OPS["LOAD_SLOT"]: 2, OPS["STORE_SLOT"]: 2,
    OPS["LIST"]: 2, OPS["MAKE_FUNC"]: 2, OPS["CALL"]: 1,
    OPS["JMP"]: 4, OPS["JMP_IF_FALSE"]: 4,
    OPS["JIF_PEEK"]: 4, OPS["JIT_PEEK"]: 4, OPS["TRY_PUSH"]: 4,
}

class Proto:
    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.declared = []
        self.escaping = []   # locals captured by a nested function -> heap
        self.safe = []       # locals used only here -> can be a stack slot
        # --- slot layout (stage 2) ---
        self.use_slots = False   # main stays env-based; functions use slots
        self.slots = []          # ordered slot names; first nparams = params
        self.slot_of = {}        # name -> slot index (SAFE names only)
        self.esc_param_ix = []   # param indexes whose value must be copied
                                 # into the heap env at call entry
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

    # --- name resolution (stage 2): slot if safe, env name otherwise ---
    def name_store(self, p, name):
        ix = p.slot_of.get(name)
        if ix is not None:
            self.emit(p, "STORE_SLOT", ("H", ix))
        else:
            self.emit(p, "STORE", ("H", self.cstr(name)))

    def name_load(self, p, name):
        ix = p.slot_of.get(name)
        if ix is not None:
            self.emit(p, "LOAD_SLOT", ("H", ix))
        else:
            self.emit(p, "LOAD", ("H", self.cstr(name)))

    def hidden(self, p, name):
        """Register a compiler-generated loop variable. Inside functions it
        gets a fresh slot (fast, and it must NOT be a named STORE: a
        function without escaping locals has no env of its own, so a named
        store would pollute the shared closure env)."""
        if p.use_slots and name not in p.slot_of:
            p.slot_of[name] = len(p.slots)
            p.slots.append(name)
        return name

    # --- program ---
    def compile_program(self, ast):
        main = Proto("<main>", [])
        all_locals = sorted(assigned_names(ast.body))
        esc = escaping_names(ast.body)
        main.escaping = [n for n in all_locals if n in esc]
        main.safe = [n for n in all_locals if n not in esc]
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
            self.name_store(p, n.name)
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
            n_name = self.hidden(p, f"$n{hid}")
            i_name = self.hidden(p, f"$i{hid}")
            self.expr(p, n.count, ctx)
            self.emit(p, "CHECK_RPT")
            self.name_store(p, n_name)
            self.emit(p, "CONST", ("H", self.cnum(0)))
            self.name_store(p, i_name)
            loop = len(p.code)
            self.name_load(p, i_name)
            self.name_load(p, n_name)
            self.emit(p, "LT")
            jend = self.emit_jump(p, "JMP_IF_FALSE")
            self.name_load(p, i_name)
            self.emit(p, "CONST", ("H", self.cnum(1)))
            self.emit(p, "ADD")
            self.name_store(p, i_name)
            self.loop_body(p, n.body, ctx, loop, jend)
        elif t == "ForEach":
            # $it: CHECK_ITER(src); $i: 0
            # loop: if not ($i < len($it)) -> end
            #       var: $it[$i]; $i: $i+1; body; jmp loop
            hid = ctx["hidden"]; ctx["hidden"] += 1
            it_name = self.hidden(p, f"$it{hid}")
            i_name = self.hidden(p, f"$i{hid}")
            self.expr(p, n.iterable, ctx)
            self.emit(p, "CHECK_ITER")
            self.name_store(p, it_name)
            self.emit(p, "CONST", ("H", self.cnum(0)))
            self.name_store(p, i_name)
            loop = len(p.code)
            self.name_load(p, i_name)
            self.name_load(p, it_name)
            self.emit(p, "LEN")
            self.emit(p, "LT")
            jend = self.emit_jump(p, "JMP_IF_FALSE")
            self.name_load(p, it_name)
            self.name_load(p, i_name)
            self.emit(p, "INDEX")
            self.name_store(p, n.var)
            self.name_load(p, i_name)
            self.emit(p, "CONST", ("H", self.cnum(1)))
            self.emit(p, "ADD")
            self.name_store(p, i_name)
            self.loop_body(p, n.body, ctx, loop, jend)
        elif t == "FuncDef":
            sub = Proto(n.name, list(n.params))
            local_names = sorted(assigned_names(n.body) | set(n.params))
            esc = escaping_names(n.body)
            sub.escaping = [x for x in local_names if x in esc]
            sub.safe = [x for x in local_names if x not in esc]
            # --- slot layout ---
            # Calling convention puts args at the first nparams stack
            # positions, so EVERY param owns a slot position. But only
            # SAFE params are addressed through it; escaping params are
            # copied into the heap env at entry and accessed by name.
            sub.use_slots = True
            safe_set = set(sub.safe)
            sub.slots = list(n.params) + [x for x in sub.safe
                                          if x not in n.params]
            sub.slot_of = {name: i for i, name in enumerate(sub.slots)
                           if name in safe_set}
            sub.esc_param_ix = [i for i, pn in enumerate(n.params)
                                if pn not in safe_set]
            # env read-before-assign guard now only covers escaping
            # non-param locals (safe ones are guarded by UNSET slots)
            sub.declared = sorted(set(sub.escaping) - set(n.params))
            self.protos.append(sub)
            ix = len(self.protos) - 1
            if ix > 0xFFFF:
                raise VidyaxError("too many functions")
            subctx = {"loops": [], "trydepth": 0, "hidden": 0}
            self.block(sub, n.body, subctx)
            self.emit(sub, "NULL")   # falling off the end returns null
            self.emit(sub, "RET")
            self.emit(p, "MAKE_FUNC", ("H", ix))
            self.name_store(p, n.name)
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
                self.name_store(p, n.err_var)
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
            self.name_load(p, n.name)
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
    def _peephole(self, p):
        """Local bytecode cleanups that preserve semantics. Conservative:
        we only touch instructions that carry no jump target INTO the
        region we remove. Because any code offset can be a jump target,
        we first collect every jump destination and refuse to delete a
        pair if its second instruction is a landing spot."""
        code = p.code
        # collect all absolute jump targets (u32 operand ops)
        targets = set()
        i = 0
        while i < len(code):
            op = code[i]
            sz = _OPSIZE.get(op, 0)
            if sz == 4:
                (t,) = struct.unpack_from("<I", code, i + 1)
                targets.add(t)
            i += 1 + sz
        # pattern: <pure-value op> immediately followed by POP  ->  drop both
        # (loading a value then discarding it has no effect). Only when the
        # POP is not itself a jump target.
        PURE = {OPS["CONST"], OPS["LOAD_SLOT"], OPS["NULL"],
                OPS["TRUE"], OPS["FALSE"]}
        new = bytearray()
        offset_map = {}          # old offset -> new offset
        i = 0
        while i < len(code):
            offset_map[i] = len(new)
            op = code[i]
            sz = _OPSIZE.get(op, 0)
            nxt = i + 1 + sz
            if (op in PURE and nxt < len(code)
                    and code[nxt] == OPS["POP"]
                    and i not in targets and nxt not in targets):
                i = nxt + 1      # skip the value op AND the POP
                continue
            new += code[i:i + 1 + sz]
            i += 1 + sz
        offset_map[len(code)] = len(new)
        # rewrite jump targets through the offset map
        j = 0
        while j < len(new):
            op = new[j]
            sz = _OPSIZE.get(op, 0)
            if sz == 4:
                (t,) = struct.unpack_from("<I", new, j + 1)
                struct.pack_into("<I", new, j + 1, offset_map.get(t, t))
            j += 1 + sz
        p.code = new

    def serialize(self):
        for p in self.protos:
            self._peephole(p)
        # Intern every name FIRST — proto names / params may never appear
        # in code, and adding consts after the count is written corrupts
        # the file.
        for p in self.protos:
            self.cstr(p.name)
            for name in p.params:
                self.cstr(name)
            for name in p.declared:
                self.cstr(name)
            for name in p.slots:
                self.cstr(name)
        out = bytearray(b"VXC1")
        out.append(2)  # version 2: protos carry slot layout
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
            if len(p.slots) > 0xFFFF:
                raise VidyaxError("too many locals in one function")
            out += struct.pack("<H", len(p.slots))
            for name in p.slots:
                out += struct.pack("<I", self.cstr(name))
            out.append(len(p.esc_param_ix))
            for ix in p.esc_param_ix:
                out.append(ix)
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
    "LOAD_SLOT": (2, "<H"), "STORE_SLOT": (2, "<H"),
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
        lines.append(f"    escaping={p.escaping}  safe(stackable)={p.safe}")
        lines.append(f"    slots={p.slots}  esc_params={p.esc_param_ix}")
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
                elif op in ("LOAD_SLOT", "STORE_SLOT"):
                    extra = f"   ; slot '{p.slots[val]}'"
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
