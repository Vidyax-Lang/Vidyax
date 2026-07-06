# -*- coding: utf-8 -*-
"""Vidyax bytecode compiler (.vx -> .vxc) for the C VM (vm/vxvm.c).

Reuses vidyax.py's lexer/parser/type-checker/scope analysis, so the VM
inherits the exact same front-end semantics as the two Python engines.

Format .vxc (little-endian), version 3:
  magic  "VXC1"
  u8     version (=3)
  u32    nconsts, then consts:
           tag u8: 1 = NUM (f64), 2 = STR (u32 len + utf-8 bytes)
  u32    nprotos, then protos (proto 0 = top level):
           u32 name const idx (str)
           u8  nparams, then u32 const idx per param name
           u16 nslots, then u32 const idx per slot name
           u8  n escaping params, then u8 param index each
           u16 ndeclared, then u32 const idx per declared-local name
           u32 codelen, then code bytes
           u32 nlineruns, then (u32 code offset, u32 .vx line) each —
               sorted; a run covers code until the next run's offset

Opcodes: see OPS below (mirrored in vm/vxvm.c — keep in sync!).
`use ai`, member access and get() are supported: the VM ships the same ai
module and routes ai.ask()/get() through libcurl (see vm/vxvm.c). Only
`use <other>` modules are still rejected at compile time.
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
    "AI_NEW": 40,      # push a fresh 'ai' module object
    "GET_MEMBER": 41,  # u16 const idx (member name str); pops obj, pushes member
}



# --- optimizer: inlining (VM pipeline only) ---------------------------
# The Python engines keep the original AST; the differential suite +
# fuzzer prove the inlined program still behaves identically. The rules
# are deliberately conservative — every one of them guards an observable
# behavior (error messages, evaluation order, definedness checks):
#
#   function:  defined once at top level, never reassigned, never used
#              as a value (only ever called directly)
#   body:      exactly `return <expr>` where <expr> uses only literals,
#              its own params, and *builtin* calls; no `and`/`or`
#              (short-circuit could skip an argument read); every param
#              is used, and first uses appear in declaration order
#              (so argument evaluation order is preserved)
#   call site: argc matches, and every argument is a literal or a plain
#              variable (pure — re-reading or reordering them is safe)

import copy as _copy


def _inline_expr_ok(n, params, first_uses):
    t = type(n).__name__
    if t in ("Number", "Str", "Bool", "Null"):
        return True
    if t == "Var":
        if n.name not in params:
            return False
        if n.name not in first_uses:
            first_uses.append(n.name)
        return True
    if t == "BinOp":
        if n.op in ("and", "or"):
            return False
        return (_inline_expr_ok(n.l, params, first_uses)
                and _inline_expr_ok(n.r, params, first_uses))
    if t == "UnaryOp":
        return _inline_expr_ok(n.operand, params, first_uses)
    if t == "Call":
        if type(n.callee).__name__ != "Var":
            return False
        if n.callee.name not in vidyax.BUILTIN_NAMES:
            return False
        return all(_inline_expr_ok(a, params, first_uses) for a in n.args)
    return False


def _pure_arg(n):
    return type(n).__name__ in ("Number", "Str", "Bool", "Null", "Var")


def _subst(n, mapping):
    """Clone `n`, replacing param Vars with (copies of) the arg nodes."""
    t = type(n).__name__
    if t == "Var":
        return _copy.deepcopy(mapping[n.name])
    n = _copy.copy(n)
    if t == "BinOp":
        n.l = _subst(n.l, mapping); n.r = _subst(n.r, mapping)
    elif t == "UnaryOp":
        n.operand = _subst(n.operand, mapping)
    elif t == "Call":
        n.args = [_subst(a, mapping) for a in n.args]
    return n


def _collect_candidates(ast):
    defs, banned = {}, set()
    for s in ast.body:
        if type(s).__name__ == "FuncDef":
            if s.name in defs:
                banned.add(s.name)          # redefined -> unpredictable
            defs[s.name] = s

    def scan_expr(e, callee_of=None):
        t = type(e).__name__
        if t == "Var" and e is not callee_of and e.name in defs:
            banned.add(e.name)              # used as a value
        elif t == "BinOp":
            scan_expr(e.l); scan_expr(e.r)
        elif t == "UnaryOp":
            scan_expr(e.operand)
        elif t == "Call":
            if type(e.callee).__name__ == "Var":
                scan_expr(e.callee, callee_of=e.callee)
            else:
                scan_expr(e.callee)
            for a in e.args:
                scan_expr(a)
        elif t == "ListLit":
            for x in e.items:
                scan_expr(x)
        elif t in ("Member", "Index"):
            scan_expr(e.obj)
            if t == "Index":
                scan_expr(e.idx)
        elif t == "Input":
            scan_expr(e.prompt)

    def scan_stmts(stmts):
        for s in stmts:
            t = type(s).__name__
            if t == "Assign":
                if s.name in defs:
                    banned.add(s.name)      # reassigned
                scan_expr(s.value)
            elif t in ("Print", "ExprStmt"):
                scan_expr(s.expr)
            elif t == "Return" and s.value is not None:
                scan_expr(s.value)
            elif t == "If":
                scan_expr(s.cond); scan_stmts(s.body); scan_stmts(s.orelse)
            elif t == "RepeatN":
                scan_expr(s.count); scan_stmts(s.body)
            elif t == "ForEach":
                scan_expr(s.iterable); scan_stmts(s.body)
            elif t == "FuncDef":
                scan_stmts(s.body)
            elif t == "TryCatch":
                scan_stmts(s.try_body); scan_stmts(s.catch_body)

    scan_stmts(ast.body)

    out = {}
    for name, f in defs.items():
        if name in banned or len(f.body) != 1:
            continue
        ret = f.body[0]
        if type(ret).__name__ != "Return" or ret.value is None:
            continue
        first_uses = []
        if not _inline_expr_ok(ret.value, set(f.params), first_uses):
            continue
        if first_uses != list(f.params):    # every param used, in order
            continue
        out[name] = (f.params, ret.value)
    return out


def _inline_program(ast):
    cand = _collect_candidates(ast)
    if not cand:
        return ast

    def rw(e):
        t = type(e).__name__
        if t == "BinOp":
            e.l = rw(e.l); e.r = rw(e.r)
        elif t == "UnaryOp":
            e.operand = rw(e.operand)
        elif t == "ListLit":
            e.items = [rw(x) for x in e.items]
        elif t == "Member":
            e.obj = rw(e.obj)
        elif t == "Index":
            e.obj = rw(e.obj); e.idx = rw(e.idx)
        elif t == "Input":
            e.prompt = rw(e.prompt)
        elif t == "Call":
            e.args = [rw(a) for a in e.args]
            if type(e.callee).__name__ != "Var":
                e.callee = rw(e.callee)
            elif (e.callee.name in cand
                    and len(e.args) == len(cand[e.callee.name][0])
                    and all(_pure_arg(a) for a in e.args)):
                params, body = cand[e.callee.name]
                return _subst(body, dict(zip(params, e.args)))
        return e

    def rw_stmts(stmts):
        for s in stmts:
            t = type(s).__name__
            if t == "Assign":
                s.value = rw(s.value)
            elif t in ("Print", "ExprStmt"):
                s.expr = rw(s.expr)
            elif t == "Return" and s.value is not None:
                s.value = rw(s.value)
            elif t == "If":
                s.cond = rw(s.cond); rw_stmts(s.body); rw_stmts(s.orelse)
            elif t == "RepeatN":
                s.count = rw(s.count); rw_stmts(s.body)
            elif t == "ForEach":
                s.iterable = rw(s.iterable); rw_stmts(s.body)
            elif t == "FuncDef":
                rw_stmts(s.body)
            elif t == "TryCatch":
                rw_stmts(s.try_body); rw_stmts(s.catch_body)

    rw_stmts(ast.body)
    return ast


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
    OPS["LOAD_SLOT"]: 2, OPS["STORE_SLOT"]: 2, OPS["GET_MEMBER"]: 2,
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
        self.lines = []          # (code offset, .vx line) runs, sorted

    def mark_line(self, line):
        """Record that code emitted from here on comes from .vx `line`."""
        if line and (not self.lines or self.lines[-1][1] != line):
            self.lines.append((len(self.code), line))


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
        # Escape analysis for the top level too: names never read by a
        # nested function live in stack slots (STORE/LOAD_SLOT), not in
        # the global env — top-level loops get the same speed as
        # function-local ones. Escaping names stay env-based so closures
        # keep seeing them.
        main.use_slots = True
        main.slots = list(main.safe)
        main.slot_of = {name: i for i, name in enumerate(main.slots)}
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
        p.mark_line(getattr(n, "line", 0))
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
            if n.name != "ai":
                raise VidyaxError(
                    f"'use {n.name}' is not supported in the VM "
                    "(only 'use ai' is available)")
            # bind the name to a fresh ai-module object
            self.emit(p, "AI_NEW")
            self.name_store(p, n.name)
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
            self.expr(p, n.obj, ctx)
            self.emit(p, "GET_MEMBER", ("H", self.cstr(n.name)))
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
        # remap the line table through the same offset map (dedupe runs
        # that collapsed onto the same new offset: last one wins there,
        # then drop consecutive duplicates of the same line)
        remapped = []
        for off, line in p.lines:
            noff = offset_map.get(off, len(new))
            if remapped and remapped[-1][0] == noff:
                remapped[-1] = (noff, line)
            elif not remapped or remapped[-1][1] != line:
                remapped.append((noff, line))
        p.lines = remapped
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
        out.append(3)  # version 3: v2 (slot layout) + per-proto line table
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
            out += struct.pack("<I", len(p.lines))
            for off, line in p.lines:
                out += struct.pack("<II", off, line)
        return bytes(out)


# --- disassembler: the living documentation of the .vxc format ---
_OPNAME = {code: name for name, code in OPS.items()}


def disassemble(data):
    """Render a .vxc image as readable text. Raises VidyaxError on a
    corrupt file. This is the reference reader for the format described
    in the module docstring — `vidyax disasm <file>` prints it."""
    pos = [0]

    def need(n):
        if pos[0] + n > len(data):
            raise VidyaxError("corrupt .vxc file (truncated)")

    def u8():
        need(1); v = data[pos[0]]; pos[0] += 1; return v

    def u16():
        need(2); v = struct.unpack_from("<H", data, pos[0])[0]; pos[0] += 2; return v

    def u32():
        need(4); v = struct.unpack_from("<I", data, pos[0])[0]; pos[0] += 4; return v

    def f64():
        need(8); v = struct.unpack_from("<d", data, pos[0])[0]; pos[0] += 8; return v

    need(4)
    if bytes(data[:4]) != b"VXC1":
        raise VidyaxError("not a .vxc file (bad magic)")
    pos[0] = 4
    version = u8()

    consts = []
    for _ in range(u32()):
        tag = u8()
        if tag == 1:
            consts.append(f64())
        elif tag == 2:
            n = u32(); need(n)
            consts.append(data[pos[0]:pos[0] + n].decode("utf-8", "replace"))
            pos[0] += n
        else:
            raise VidyaxError("corrupt .vxc file (bad const tag)")

    def cstr(ix):
        if ix >= len(consts) or not isinstance(consts[ix], str):
            raise VidyaxError("corrupt .vxc file (bad name index)")
        return consts[ix]

    def crepr(ix):
        if ix >= len(consts):
            return "?"
        v = consts[ix]
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() else str(v)
        return '"%s"' % v

    protos = []
    for _ in range(u32()):
        name = cstr(u32())
        params = [cstr(u32()) for _ in range(u8())]
        slots = [cstr(u32()) for _ in range(u16())]
        esc = [u8() for _ in range(u8())]
        declared = [cstr(u32()) for _ in range(u16())]
        codelen = u32(); need(codelen)
        code = data[pos[0]:pos[0] + codelen]; pos[0] += codelen
        lines = {}
        if version >= 3:
            for _ in range(u32()):
                off = u32(); lines[off] = u32()
        protos.append((name, params, slots, esc, declared, code, lines))

    lines = ["; Vidyax bytecode VXC1 v%d — %d consts, %d protos"
             % (version, len(consts), len(protos))]
    if len(consts) <= 40:
        lines.append("consts:")
        for i in range(len(consts)):
            lines.append("  [%d] %s" % (i, crepr(i)))

    for pi, (name, params, slots, esc, declared, code, lnruns) in enumerate(protos):
        head = "proto %d <%s>  params=(%s)" % (pi, name, ", ".join(params))
        if slots:
            head += "  slots=(%s)" % ", ".join(slots)
        if esc:
            head += "  esc=%s" % esc
        if declared:
            head += "  declared=(%s)" % ", ".join(declared)
        lines.append("")
        lines.append(head)
        i = 0
        while i < len(code):
            if i in lnruns:
                lines.append("  ; line %d" % lnruns[i])
            op = code[i]
            nm = _OPNAME.get(op)
            if nm is None:
                lines.append("  %04d ???(%d)" % (i, op))
                i += 1
                continue
            w = _OPSIZE.get(op, 0)
            if i + 1 + w > len(code):
                raise VidyaxError("corrupt .vxc file (truncated operand)")
            if w == 0:
                lines.append("  %04d %s" % (i, nm))
            else:
                arg = int.from_bytes(code[i + 1:i + 1 + w], "little")
                note = ""
                if nm == "CONST":
                    note = "  ; %s" % crepr(arg)
                elif nm in ("LOAD", "STORE", "GET_MEMBER"):
                    note = "  ; %s" % cstr(arg)
                elif nm in ("LOAD_SLOT", "STORE_SLOT") and arg < len(slots):
                    note = "  ; %s" % slots[arg]
                elif nm == "MAKE_FUNC" and arg < len(protos):
                    note = "  ; <%s>" % protos[arg][0]
                elif nm in ("JMP", "JMP_IF_FALSE", "JIF_PEEK",
                            "JIT_PEEK", "TRY_PUSH"):
                    note = "  ; -> %04d" % arg
                lines.append("  %04d %-13s %d%s" % (i, nm, arg, note))
            i += 1 + w
    return "\n".join(lines) + "\n"


def disasm_file(path):
    """`vidyax disasm x.vxc` — or x.vx, which is compiled in memory."""
    if path.endswith((".vx", ".vax")):
        with open(path, encoding="utf-8") as f:
            data = compile_source(f.read()).serialize()
    else:
        with open(path, "rb") as f:
            data = f.read()
    return disassemble(data)


def compile_source(source):
    tokens = vidyax.lex(source)
    ast = vidyax.Parser(tokens).parse()
    vidyax.type_check(ast)
    _inline_program(ast)     # VM-only optimization; semantics-preserving
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
    "LOAD_SLOT": (2, "<H"), "STORE_SLOT": (2, "<H"), "GET_MEMBER": (2, "<H"),
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
                if op in ("CONST", "LOAD", "STORE", "GET_MEMBER"):
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
