#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vidyax - interpreter v1.1
"Code as simple as writing instructions."

Single file: lexer -> parser -> evaluator + CLI.
Two engines, ONE runtime: the tree-walker and the transpiler both call the
same helpers defined in the RUNTIME string, so behaviour stays identical
by construction (and is enforced by the differential tests).
Usage:
    python vidyax.py run main.vx
    python vidyax.py test
"""

import sys
import os
import json
import urllib.request
import urllib.error

# When executed as `python vidyax.py`, this module is loaded as __main__;
# vxc.py's `import vidyax` would then load a SECOND copy, whose VidyaxError
# is a different class — and `except VidyaxError` in the CLI would miss it.
# Alias the module so every importer shares this one instance.
if __name__ == "__main__":
    sys.modules.setdefault("vidyax", sys.modules["__main__"])

VERSION = "1.3"

# =====================================================================
# 1. TOKEN & LEXER
# =====================================================================

KEYWORDS = {
    "print", "if", "elif", "else", "rpt", "for", "in", "func", "return",
    "ask", "use", "and", "or", "not",
    "true", "false", "null",
    "break", "continue",
    "try", "catch",
    # roadmap (recognized but not yet runnable):
    "agent", "go",
}

TWO_CHAR_OPS = {"==", "!=", "<=", ">="}
ONE_CHAR_OPS = {
    ":", "(", ")", "[", "]", ",", ".",
    "+", "-", "*", "/", "%", "<", ">", "=",
}


class Token:
    def __init__(self, kind, value, line):
        self.kind = kind   # NEWLINE, INDENT, DEDENT, NUMBER, STRING, NAME, KEYWORD, OP, EOF
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, line {self.line})"


class VidyaxError(Exception):
    """User-friendly error for Vidyax programs.

    kind categorizes the problem so beginners know what to look for:
      "syntax"  — the code is written wrong (typo, missing/extra token)
      "name"    — a variable or name that isn't defined (yet)
      "type"    — using a value the wrong way (e.g. math on text)
      "runtime" — something went wrong while running (e.g. divide by 0)
    """
    _LABELS = {"syntax": "syntax error", "name": "name error",
               "type": "type error", "runtime": "runtime error"}

    def __init__(self, msg, line=None, kind=None):
        self.msg = msg
        self.line = line
        self.kind = kind
        super().__init__(msg)

    def show(self):
        label = self._LABELS.get(self.kind)
        head = f"{label}, " if label else ""
        if self.line:
            return f"[Vidyax] {head}line {self.line}: {self.msg}"
        return f"[Vidyax] {head}{self.msg}"


# Beginner-friendly names for token categories, used in syntax messages.
_KIND_WORDS = {
    "NEWLINE": "a new line", "NAME": "a name", "NUMBER": "a number",
    "STRING": "some text", "OP": "a symbol", "KEYWORD": "a keyword",
    "INDENT": "an indented block", "DEDENT": "the block to end",
    "EOF": "the end of the program",
}


def _kind_word(kind):
    return _KIND_WORDS.get(kind, kind)


def _tok_word(t):
    if t.kind == "NEWLINE":
        return "the end of the line"
    if t.kind == "EOF":
        return "the end of the program"
    return repr(t.value)


def lex(source):
    """Turn source text into tokens, with Python-style INDENT/DEDENT."""
    tokens = []
    indent_stack = [0]
    lines = source.split("\n")
    bracket_depth = 0  # for ( and [ to allow multi-line

    for line_no, raw in enumerate(lines, start=1):
        if bracket_depth == 0:
            stripped = raw.lstrip(" ")
            no_comment = stripped.split("#", 1)[0].strip()
            if no_comment == "":
                continue
            indent = len(raw) - len(stripped)
            if "\t" in raw[:indent]:
                raise VidyaxError("use spaces for indentation, not TAB", line_no)
            if indent > indent_stack[-1]:
                indent_stack.append(indent)
                tokens.append(Token("INDENT", indent, line_no))
            while indent < indent_stack[-1]:
                indent_stack.pop()
                tokens.append(Token("DEDENT", None, line_no))
            if indent != indent_stack[-1]:
                raise VidyaxError(
                    "the indentation here doesn't line up with the block "
                    "above — use the same number of spaces", line_no)

        i = 0
        n = len(raw)
        produced = False
        while i < n:
            c = raw[i]
            if c == "#":
                break
            if c == " ":
                i += 1
                continue
            # string
            if c == '"':
                i += 1
                buf = []
                while i < n and raw[i] != '"':
                    if raw[i] == "\\" and i + 1 < n:
                        nxt = raw[i + 1]
                        buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                        i += 2
                        continue
                    buf.append(raw[i])
                    i += 1
                if i >= n:
                    raise VidyaxError('string not closed with "', line_no)
                i += 1
                tokens.append(Token("STRING", "".join(buf), line_no))
                produced = True
                continue
            # number
            if c.isdigit():
                j = i
                dot = False
                while j < n and (raw[j].isdigit() or (raw[j] == "." and not dot)):
                    if raw[j] == ".":
                        dot = True
                    j += 1
                text = raw[i:j]
                val = float(text) if dot else int(text)
                tokens.append(Token("NUMBER", val, line_no))
                i = j
                produced = True
                continue
            # name / keyword
            if c.isalpha() or c == "_":
                j = i
                while j < n and (raw[j].isalnum() or raw[j] == "_"):
                    j += 1
                word = raw[i:j]
                kind = "KEYWORD" if word in KEYWORDS else "NAME"
                tokens.append(Token(kind, word, line_no))
                i = j
                produced = True
                continue
            # two-char operators (==, !=, <=, >=)
            two = raw[i:i + 2]
            if len(two) == 2 and two in TWO_CHAR_OPS:
                tokens.append(Token("OP", two, line_no))
                i += 2
                produced = True
                continue
            # one-char operators
            if c in ONE_CHAR_OPS:
                if c in "([":
                    bracket_depth += 1
                elif c in ")]":
                    bracket_depth = max(0, bracket_depth - 1)
                tokens.append(Token("OP", c, line_no))
                i += 1
                produced = True
                continue
            raise VidyaxError(f"unknown character: {c!r}", line_no)

        if produced and bracket_depth == 0:
            tokens.append(Token("NEWLINE", None, line_no))

    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token("DEDENT", None, len(lines)))
    tokens.append(Token("EOF", None, len(lines)))
    return tokens


# =====================================================================
# 2. AST
# =====================================================================

class Node: pass

class Program(Node):
    def __init__(self, body): self.body = body
class Number(Node):
    def __init__(self, v): self.v = v
class Str(Node):
    def __init__(self, v): self.v = v
class Bool(Node):
    def __init__(self, v): self.v = v
class Null(Node): pass
class ListLit(Node):
    def __init__(self, items): self.items = items
class Var(Node):
    def __init__(self, name, line): self.name = name; self.line = line
class Assign(Node):
    def __init__(self, name, value): self.name = name; self.value = value
class Print(Node):
    def __init__(self, expr): self.expr = expr
class Input(Node):
    def __init__(self, prompt): self.prompt = prompt
class If(Node):
    def __init__(self, cond, body, orelse): self.cond = cond; self.body = body; self.orelse = orelse
class RepeatN(Node):
    def __init__(self, count, body): self.count = count; self.body = body
class ForEach(Node):
    def __init__(self, var, iterable, body): self.var = var; self.iterable = iterable; self.body = body
class FuncDef(Node):
    def __init__(self, name, params, body): self.name = name; self.params = params; self.body = body
class Return(Node):
    def __init__(self, value): self.value = value
class Break(Node): pass
class Continue(Node): pass
class TryCatch(Node):
    def __init__(self, try_body, err_var, catch_body):
        self.try_body = try_body; self.err_var = err_var; self.catch_body = catch_body
class Import(Node):
    def __init__(self, name): self.name = name
class ExprStmt(Node):
    def __init__(self, expr): self.expr = expr
class BinOp(Node):
    def __init__(self, op, l, r, line): self.op = op; self.l = l; self.r = r; self.line = line
class UnaryOp(Node):
    def __init__(self, op, operand, line): self.op = op; self.operand = operand; self.line = line
class Call(Node):
    def __init__(self, callee, args, line): self.callee = callee; self.args = args; self.line = line
class Member(Node):
    def __init__(self, obj, name, line): self.obj = obj; self.name = name; self.line = line
class Index(Node):
    def __init__(self, obj, idx, line): self.obj = obj; self.idx = idx; self.line = line
class GoTask(Node):
    """`go f(args)` — run the call as a concurrent task (docs/CONCURRENCY.md)."""
    def __init__(self, call, line): self.call = call; self.line = line


# =====================================================================
# 3. PARSER
# =====================================================================

class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0
        self.loop_depth = 0  # break/continue only valid when > 0
        self.func_depth = 0  # return only valid when > 0

    def peek(self, k=0):
        return self.toks[self.pos + k]

    def at(self, kind, value=None):
        t = self.peek()
        if t.kind != kind:
            return False
        return value is None or t.value == value

    def eat(self, kind=None, value=None):
        t = self.peek()
        if kind and t.kind != kind:
            if kind == "NEWLINE":
                raise VidyaxError(
                    "looks like more than one command on this line — "
                    "put each command on its own line", t.line)
            raise VidyaxError(
                f"expected {_kind_word(kind)}, but found {_tok_word(t)}", t.line)
        if value is not None and t.value != value:
            raise VidyaxError(
                f"expected {value!r} here, but found {_tok_word(t)}", t.line)
        self.pos += 1
        return t

    def skip_newlines(self):
        while self.at("NEWLINE"):
            self.pos += 1

    def guard_name(self, tok):
        """Built-in function names are reserved. Shadowing them would make
        the walker and the transpiler disagree (the transpiler rewrites
        built-in calls statically), so we reject it early — this also gives
        editors a clean static error via `vidyax check`."""
        if tok.value in BUILTIN_NAMES:
            raise VidyaxError(
                f"'{tok.value}' is a built-in function name — pick a different name",
                tok.line)
        return tok.value

    def parse(self):
        return Program(self.statements_until(("EOF",)))

    def statements_until(self, stop_kinds):
        stmts = []
        self.skip_newlines()
        while self.peek().kind not in stop_kinds:
            stmts.append(self.statement())
            self.skip_newlines()
        return stmts

    def block(self):
        self.eat("OP", ":")
        # inline body on the same line:  if x > 0: print "yes"
        if not self.at("NEWLINE"):
            return [self.statement()]
        self.eat("NEWLINE")
        self.eat("INDENT")
        body = self.statements_until(("DEDENT",))
        self.eat("DEDENT")
        return body

    def statement(self):
        # Stamp every statement node with its first token's line — the
        # bytecode compiler's line table (and the walker) rely on it.
        line = self.peek().line
        node = self._statement()
        if getattr(node, "line", None) is None:
            node.line = line
        return node

    def _statement(self):
        t = self.peek()
        if t.kind == "KEYWORD":
            if t.value == "print":    return self.stmt_print()
            if t.value == "if":       return self.stmt_if()
            if t.value == "rpt":      return self.stmt_repeat()
            if t.value == "for":      return self.stmt_for()
            if t.value == "func":     return self.stmt_func()
            if t.value == "return":   return self.stmt_return()
            if t.value == "use":      return self.stmt_import()
            if t.value == "try":      return self.stmt_try()
            if t.value == "break":
                if self.loop_depth == 0:
                    raise VidyaxError("'break' only works inside a loop", t.line)
                self.eat(); self.eat("NEWLINE"); return Break()
            if t.value == "continue":
                if self.loop_depth == 0:
                    raise VidyaxError("'continue' only works inside a loop", t.line)
                self.eat(); self.eat("NEWLINE"); return Continue()
            if t.value == "agent":
                raise VidyaxError("'agent' is not supported yet (roadmap)", t.line)
        # assignment: NAME ':' expr
        if t.kind == "NAME" and self.peek(1).kind == "OP" and self.peek(1).value == ":":
            name = self.guard_name(self.eat("NAME"))
            self.eat("OP", ":")
            value = self.expression()
            self.eat("NEWLINE")
            return Assign(name, value)
        # expression statement
        expr = self.expression()
        self.eat("NEWLINE")
        return ExprStmt(expr)

    def stmt_print(self):
        self.eat("KEYWORD", "print")
        expr = self.expression()
        self.eat("NEWLINE")
        return Print(expr)

    def stmt_if(self):
        self.eat("KEYWORD", "if")
        cond = self.expression()
        body = self.block()
        return If(cond, body, self._tail_else())

    def _tail_else(self):
        if self.at("KEYWORD", "elif"):
            self.eat("KEYWORD", "elif")
            c = self.expression()
            b = self.block()
            return [If(c, b, self._tail_else())]
        if self.at("KEYWORD", "else"):
            self.eat("KEYWORD", "else")
            return self.block()
        return []

    def stmt_repeat(self):
        self.eat("KEYWORD", "rpt")
        count = self.expression()
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return RepeatN(count, body)

    def stmt_for(self):
        self.eat("KEYWORD", "for")
        var = self.guard_name(self.eat("NAME"))
        self.eat("KEYWORD", "in")
        it = self.expression()
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return ForEach(var, it, body)

    def stmt_func(self):
        self.eat("KEYWORD", "func")
        name = self.guard_name(self.eat("NAME"))
        self.eat("OP", "(")
        params = []
        if not self.at("OP", ")"):
            params.append(self.guard_name(self.eat("NAME")))
            while self.at("OP", ","):
                self.eat("OP", ",")
                params.append(self.guard_name(self.eat("NAME")))
        self.eat("OP", ")")
        saved_loop = self.loop_depth
        self.loop_depth = 0   # a break inside a func can't target an outer loop
        self.func_depth += 1
        body = self.block()
        self.func_depth -= 1
        self.loop_depth = saved_loop
        return FuncDef(name, params, body)

    def stmt_return(self):
        t = self.eat("KEYWORD", "return")
        if self.func_depth == 0:
            raise VidyaxError("'return' only works inside a function", t.line)
        value = None
        if not self.at("NEWLINE"):
            value = self.expression()
        self.eat("NEWLINE")
        return Return(value)

    def stmt_import(self):
        self.eat("KEYWORD", "use")
        name = self.eat("NAME").value
        self.eat("NEWLINE")
        return Import(name)

    def stmt_try(self):
        self.eat("KEYWORD", "try")
        try_body = self.block()
        self.skip_newlines()
        if not self.at("KEYWORD", "catch"):
            raise VidyaxError("'try' must be followed by 'catch'", self.peek().line)
        self.eat("KEYWORD", "catch")
        err_var = None
        if self.at("NAME"):
            err_var = self.guard_name(self.eat("NAME"))
        catch_body = self.block()
        return TryCatch(try_body, err_var, catch_body)

    # --- expressions ---
    def expression(self):
        return self.p_or()

    def p_or(self):
        node = self.p_and()
        while self.at("KEYWORD", "or"):
            line = self.eat().line
            node = BinOp("or", node, self.p_and(), line)
        return node

    def p_and(self):
        node = self.p_equality()
        while self.at("KEYWORD", "and"):
            line = self.eat().line
            node = BinOp("and", node, self.p_equality(), line)
        return node

    def p_equality(self):
        node = self.p_compare()
        while self.at("OP", "==") or self.at("OP", "!="):
            op = self.eat(); node = BinOp(op.value, node, self.p_compare(), op.line)
        return node

    def p_compare(self):
        node = self.p_term()
        while self.peek().kind == "OP" and self.peek().value in ("<", ">", "<=", ">="):
            op = self.eat(); node = BinOp(op.value, node, self.p_term(), op.line)
        return node

    def p_term(self):
        node = self.p_factor()
        while self.peek().kind == "OP" and self.peek().value in ("+", "-"):
            op = self.eat(); node = BinOp(op.value, node, self.p_factor(), op.line)
        return node

    def p_factor(self):
        node = self.p_unary()
        while self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            op = self.eat(); node = BinOp(op.value, node, self.p_unary(), op.line)
        return node

    def p_unary(self):
        if self.at("KEYWORD", "not"):
            t = self.eat(); return UnaryOp("not", self.p_unary(), t.line)
        if self.at("OP", "-"):
            t = self.eat(); return UnaryOp("-", self.p_unary(), t.line)
        if self.at("KEYWORD", "go"):
            t = self.eat()
            call = self.p_postfix()
            if type(call).__name__ != "Call":
                raise VidyaxError(
                    "'go' needs a function call, like: go f(x)", t.line)
            return GoTask(call, t.line)
        return self.p_postfix()

    def starts_command_arg(self):
        t = self.peek()
        if t.kind in ("NUMBER", "STRING", "NAME"):
            return True
        if t.kind == "KEYWORD" and t.value in ("true", "false", "null"):
            return True
        if t.kind == "OP" and t.value in ("(", "["):
            return True
        return False

    def p_postfix(self):
        node = self.p_primary()
        while True:
            t = self.peek()
            if t.kind == "OP" and t.value == "(":
                self.eat("OP", "(")
                args = []
                if not self.at("OP", ")"):
                    args.append(self.expression())
                    while self.at("OP", ","):
                        self.eat("OP", ",")
                        args.append(self.expression())
                self.eat("OP", ")")
                node = Call(node, args, t.line)
            elif t.kind == "OP" and t.value == ".":
                self.eat("OP", ".")
                nt = self.peek()
                if nt.kind in ("NAME", "KEYWORD"):
                    name = self.eat().value
                else:
                    raise VidyaxError("expected a member name after '.'", t.line)
                member = Member(node, name, t.line)
                if self.starts_command_arg():
                    arg = self.expression()
                    node = Call(member, [arg], t.line)
                else:
                    node = member
            elif t.kind == "OP" and t.value == "[":
                self.eat("OP", "[")
                idx = self.expression()
                self.eat("OP", "]")
                node = Index(node, idx, t.line)
            else:
                break
        return node

    def p_primary(self):
        t = self.peek()
        if t.kind == "NUMBER":
            self.eat(); return Number(t.value)
        if t.kind == "STRING":
            self.eat(); return Str(t.value)
        if t.kind == "KEYWORD" and t.value == "true":
            self.eat(); return Bool(True)
        if t.kind == "KEYWORD" and t.value == "false":
            self.eat(); return Bool(False)
        if t.kind == "KEYWORD" and t.value == "null":
            self.eat(); return Null()
        if t.kind == "KEYWORD" and t.value == "ask":
            self.eat(); return Input(self.p_unary())
        if t.kind == "NAME":
            self.eat(); return Var(t.value, t.line)
        if t.kind == "OP" and t.value == "(":
            self.eat("OP", "(")
            e = self.expression()
            self.eat("OP", ")")
            return e
        if t.kind == "OP" and t.value == "[":
            self.eat("OP", "[")
            items = []
            if not self.at("OP", "]"):
                items.append(self.expression())
                while self.at("OP", ","):
                    self.eat("OP", ",")
                    items.append(self.expression())
            self.eat("OP", "]")
            return ListLit(items)
        if t.kind in ("NEWLINE", "DEDENT", "EOF"):
            raise VidyaxError(
                "this line looks unfinished — something is missing after here",
                t.line)
        raise VidyaxError(
            f"unexpected {_tok_word(t)} here — I didn't know what to do with it",
            t.line)


# =====================================================================
# 4. RUNTIME
# =====================================================================

class ReturnSignal(Exception):
    def __init__(self, value): self.value = value
class BreakSignal(Exception): pass
class ContinueSignal(Exception): pass

class Function:
    def __init__(self, decl, closure):
        self.decl = decl; self.closure = closure

class Environment:
    def __init__(self, parent=None, declared=()):
        self.vars = {}
        self.parent = parent
        # Names assigned somewhere in this function's body.
        # Scoping rule (identical to the transpiled Python, by design):
        # a name assigned anywhere in a function is LOCAL to that function.
        # Reading it before it has a value is an error, and it never leaks
        # to the outer scope. Names never assigned here read through to the
        # enclosing scope as usual.
        self.declared = set(declared)

    def get(self, name, line=None):
        env = self
        while env:
            if name in env.vars:
                return env.vars[name]
            if name in env.declared:
                raise VidyaxError(
                    f"variable '{name}' is assigned in this function "
                    "but used before it has a value", line, kind="name")
            env = env.parent
        raise VidyaxError(f"variable '{name}' is not defined", line, kind="name")

    def set(self, name, value):
        self.vars[name] = value


# vidyax_str is bound below from the shared RUNTIME (_vstr), so the walker
# and the transpiled code can never drift apart on value formatting.

def vidyax_truthy(v):
    if isinstance(v, bool): return v
    if v is None: return False
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, (str, list)): return len(v) > 0
    return True


def assigned_names(body):
    """Every name that gets a binding in this function body: assignments,
    loop vars, catch vars, nested func names, `use ai`. Does NOT descend
    into nested FuncDef bodies — those are their own scope. Used by
    call_function() so the walker follows the exact same scoping rule the
    transpiled Python follows naturally."""
    names = set()
    stack = list(body)
    while stack:
        s = stack.pop()
        t = type(s).__name__
        if t == "Assign":
            names.add(s.name)
        elif t == "If":
            stack.extend(s.body); stack.extend(s.orelse)
        elif t == "RepeatN":
            stack.extend(s.body)
        elif t == "ForEach":
            names.add(s.var); stack.extend(s.body)
        elif t == "TryCatch":
            if s.err_var:
                names.add(s.err_var)
            stack.extend(s.try_body); stack.extend(s.catch_body)
        elif t == "FuncDef":
            names.add(s.name)  # the func name binds locally; body = new scope
        elif t == "Import":
            names.add(s.name)  # `use ai` binds the name 'ai'
    return names


# The AI module lives in the shared RUNTIME below (class _AI) — one
# implementation for both engines. The old AIModule/BoundMethod pair that
# duplicated it (and drifted: different default model, no provider routing
# in the transpiled copy) is gone.


# =====================================================================
# 5. INTERPRETER
# =====================================================================

class Interpreter:
    def __init__(self):
        self.global_env = Environment()
        for name, fn in BUILTINS.items():
            self.global_env.set(name, fn)

    def run(self, program):
        for stmt in program.body:
            self.exec(stmt, self.global_env)

    def exec(self, node, env):
        m = getattr(self, "exec_" + type(node).__name__, None)
        if not m:
            raise VidyaxError(f"cannot execute {type(node).__name__}")
        return m(node, env)

    def exec_Assign(self, n, env):
        env.set(n.name, self.eval(n.value, env))

    def exec_Print(self, n, env):
        print(vidyax_str(self.eval(n.expr, env)))

    def exec_If(self, n, env):
        if vidyax_truthy(self.eval(n.cond, env)):
            self.exec_block(n.body, env)
        else:
            self.exec_block(n.orelse, env)

    def exec_RepeatN(self, n, env):
        for _ in _rt(RT["_rpt"], None, self.eval(n.count, env)):
            try:
                self.exec_block(n.body, env)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def exec_ForEach(self, n, env):
        it = _rt(RT["_iter"], None, self.eval(n.iterable, env))
        for item in it:
            env.set(n.var, item)
            try:
                self.exec_block(n.body, env)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def exec_FuncDef(self, n, env):
        env.set(n.name, Function(n, env))

    def exec_Return(self, n, env):
        val = self.eval(n.value, env) if n.value is not None else None
        raise ReturnSignal(val)

    def exec_Break(self, n, env): raise BreakSignal()
    def exec_Continue(self, n, env): raise ContinueSignal()

    def exec_TryCatch(self, n, env):
        try:
            self.exec_block(n.try_body, env)
        except (BreakSignal, ContinueSignal, ReturnSignal):
            raise  # control flow must pass through
        except VidyaxError as e:
            if n.err_var:
                env.set(n.err_var, e.msg)
            self.exec_block(n.catch_body, env)
        except Exception as e:
            if n.err_var:
                env.set(n.err_var, RT["_errtext"](e))
            self.exec_block(n.catch_body, env)

    def exec_Import(self, n, env):
        if n.name == "ai":
            env.set("ai", RT["_AI"]())
        elif n.name in ("web", "database"):
            raise VidyaxError(f"module '{n.name}' is not supported yet (roadmap)")
        else:
            raise VidyaxError(f"unknown module '{n.name}'")

    def exec_ExprStmt(self, n, env):
        self.eval(n.expr, env)

    def exec_block(self, body, env):
        for stmt in body:
            self.exec(stmt, env)

    def eval(self, node, env):
        m = getattr(self, "eval_" + type(node).__name__, None)
        if not m:
            raise VidyaxError(f"cannot evaluate {type(node).__name__}")
        return m(node, env)

    def eval_Number(self, n, env): return n.v
    def eval_Str(self, n, env): return n.v
    def eval_Bool(self, n, env): return n.v
    def eval_Null(self, n, env): return None
    def eval_ListLit(self, n, env): return [self.eval(x, env) for x in n.items]
    def eval_Var(self, n, env): return env.get(n.name, n.line)

    def eval_Input(self, n, env):
        prompt = self.eval(n.prompt, env)
        try:
            return input(vidyax_str(prompt) + " ")
        except EOFError:
            return ""

    def eval_UnaryOp(self, n, env):
        v = self.eval(n.operand, env)
        if n.op == "not": return not vidyax_truthy(v)
        if n.op == "-":
            return _rt(RT["_neg"], n.line, v)   # VM semantics: -true is -1

    def eval_BinOp(self, n, env):
        if n.op == "and":
            l = self.eval(n.l, env)
            return self.eval(n.r, env) if vidyax_truthy(l) else l
        if n.op == "or":
            l = self.eval(n.l, env)
            return l if vidyax_truthy(l) else self.eval(n.r, env)
        l = self.eval(n.l, env); r = self.eval(n.r, env)
        if n.op == "+": return _rt(RT["_add"], n.line, l, r)
        if n.op == "/": return _rt(RT["_div"], n.line, l, r)
        if n.op in ("-", "*", "%"):
            return _rt(RT["_arith"], n.line, n.op, l, r)
        if n.op == "==": return l == r
        if n.op == "!=": return l != r
        if n.op == "<": return _rt(RT["_cmp"], n.line, l, r) < 0
        if n.op == ">": return _rt(RT["_cmp"], n.line, l, r) > 0
        if n.op == "<=": return _rt(RT["_cmp"], n.line, l, r) <= 0
        if n.op == ">=": return _rt(RT["_cmp"], n.line, l, r) >= 0
        raise VidyaxError(f"unknown operator {n.op}", n.line, kind="runtime")

    def eval_Member(self, n, env):
        obj = self.eval(n.obj, env)
        return _rt(RT["_member"], n.line, obj, n.name)

    def eval_Index(self, n, env):
        obj = self.eval(n.obj, env)
        idx = self.eval(n.idx, env)
        return _rt(RT["_index"], n.line, obj, idx)

    def eval_GoTask(self, n, env):
        call = n.call
        callee = self.eval(call.callee, env)
        args = [self.eval(a, env) for a in call.args]   # eager, caller-side
        cname = (call.callee.name
                 if type(call.callee).__name__ == "Var" else "task")
        if isinstance(callee, Function):
            def thunk():
                try:
                    return self.call_function(callee, args, call.line)
                except VidyaxError as e:
                    raise RTError(e.msg)
        elif callable(callee):
            def thunk():
                return callee(*args)
        else:
            raise VidyaxError("this is not a function", n.line, kind="runtime")
        return RT["_VTask"](cname, thunk)

    def eval_Call(self, n, env):
        callee = self.eval(n.callee, env)
        args = [self.eval(a, env) for a in n.args]
        if isinstance(callee, Function):
            return self.call_function(callee, args, n.line)
        if callable(callee):  # built-ins and ai methods (shared runtime)
            return _rt(callee, n.line, *args)
        raise VidyaxError("this is not a function", n.line, kind="runtime")

    def call_function(self, fn, args, line):
        if len(args) != len(fn.decl.params):
            raise VidyaxError(
                f"function '{fn.decl.name}' needs {len(fn.decl.params)} args, "
                f"got {len(args)}", line, kind="runtime")
        declared = getattr(fn.decl, "_locals", None)
        if declared is None:
            declared = assigned_names(fn.decl.body) - set(fn.decl.params)
            fn.decl._locals = declared
        local = Environment(fn.closure, declared=declared)
        for p, a in zip(fn.decl.params, args):
            local.set(p, a)
        try:
            self.exec_block(fn.decl.body, local)
        except ReturnSignal as r:
            return r.value
        return None
# =====================================================================
# Type checker (semantic pass) — runs after parse, before transpile
# =====================================================================

def _walk(node):
    """Visit this node + all its descendants. Generic, works for any Node."""
    yield node
    for value in vars(node).values():
        if isinstance(value, Node):
            yield from _walk(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    yield from _walk(item)

_TYPE_NAMES = {Number: "number", Str: "text", Bool: "boolean",
               Null: "null", ListLit: "list"}

def infer_type(node):
    """Guess a node's type if it can be known from a literal. None = unknown."""
    return _TYPE_NAMES.get(type(node))

_ARITH = {"-", "/", "%"}
_COMPARE = {"<", ">", "<=", ">="}

def type_check(program):
    for node in _walk(program):
        if isinstance(node, BinOp) and node.op in _ARITH:
            for side in (node.l, node.r):
                t = infer_type(side)
                if t is not None and t != "number":
                    raise VidyaxError(
                        f"cannot use '{node.op}' on {t}, only numbers", node.line)
        if isinstance(node, BinOp) and node.op in _COMPARE:
            lt, rt = infer_type(node.l), infer_type(node.r)
            for t in (lt, rt):
                if t is not None and t not in ("number", "text"):
                    raise VidyaxError(
                        f"cannot use '{node.op}' on {t}, only numbers or text", node.line)
            if lt is not None and rt is not None and lt != rt:
                raise VidyaxError(
                    f"cannot use '{node.op}' between {lt} and {rt}, "
                    "both sides must be the same type", node.line)


# --- front-end phase boundaries: attach an error category ---
def _module_paths(base_dir):
    """Where `use X` looks for X.vx, in order."""
    return [base_dir,
            os.path.join(base_dir, "vx_modules"),
            os.path.join(os.path.expanduser("~"), ".vidyax", "modules")]


def expand_uses(ast, base_dir, _loading=None, _loaded=None):
    """Resolve every `use X` (except the builtin `ai` and the roadmap
    names) at the FRONT-END: the module file's statements are spliced in
    place of the `use`, like a compile-time include. Because this runs
    before the engines ever see the AST, all four engines get modules
    for free — and stay identical by construction.

    Rules: a module is included ONCE per program (repeats are skipped);
    cycles are an error; nested `use` resolves relative to the module's
    own directory first."""
    _loading = [] if _loading is None else _loading
    _loaded = set() if _loaded is None else _loaded
    out = []
    for s in ast.body:
        if (type(s).__name__ != "Import"
                or s.name in ("ai", "web", "database")):
            out.append(s)
            continue
        path = None
        for d in _module_paths(base_dir):
            cand = os.path.join(d, s.name + ".vx")
            if os.path.isfile(cand):
                path = os.path.abspath(cand)
                break
        if path is None:
            raise VidyaxError(
                f"module '{s.name}' not found — looked for '{s.name}.vx' "
                "next to the program, in vx_modules/, and in "
                "~/.vidyax/modules (install with: vidyax install ...)",
                getattr(s, "line", None))
        if path in _loading:
            raise VidyaxError(f"circular use: '{s.name}' is already being "
                              "loaded", getattr(s, "line", None))
        if path in _loaded:
            continue          # include-once
        _loaded.add(path)
        try:
            with open(path, encoding="utf-8") as f:
                mod_src = f.read()
        except OSError as e:
            raise VidyaxError(f"cannot read module '{s.name}': "
                              f"{e.strerror}", getattr(s, "line", None))
        try:
            mod_ast = Parser(lex(mod_src)).parse()
        except VidyaxError as e:
            e.msg = f"in module '{s.name}': {e.msg}"
            raise
        _loading.append(path)
        expand_uses(mod_ast, os.path.dirname(path), _loading, _loaded)
        _loading.pop()
        out.extend(mod_ast.body)
    ast.body = out
    return ast


def _parse_source(source, base_dir=None):
    """Lex + parse + resolve `use` modules. Any failure here is the code
    being written wrong."""
    try:
        ast = Parser(lex(source)).parse()
        expand_uses(ast, base_dir or os.getcwd())
        return ast
    except VidyaxError as e:
        if e.kind is None:
            e.kind = "syntax"
        raise


def _typecheck(ast):
    """Static type pass. Failures are type errors."""
    try:
        type_check(ast)
    except VidyaxError as e:
        if e.kind is None:
            e.kind = "type"
        raise
    return ast


def _runtime_kind(exc):
    """Classify a Python exception that escaped the generated/interpreted
    program: undefined/uninitialized names are name errors, the rest runtime."""
    return "name" if isinstance(exc, (NameError, UnboundLocalError)) else "runtime"

# =====================================================================
# 6. TRANSPILER  (Vidyax -> Python, for speed)
# =====================================================================

import keyword

# Runtime helpers injected into every compiled program.
RUNTIME = '''# --- Vidyax runtime (auto-generated) ---
import os as _os, json as _json, urllib.request as _ureq, urllib.error as _uerr
import math as _math, random as _random, functools as _ft, time as _time
import threading as _thr

class _VidyaxRuntime(Exception): pass

def _vstr(v):
    if v is True: return "true"
    if v is False: return "false"
    if v is None: return "null"
    if isinstance(v, float): return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, list): return "[" + ", ".join(_vstr(x) for x in v) + "]"
    if type(v).__name__ == "_VTask": return "<task %s>" % v.name
    return str(v)

def _add(a, b):
    # exactly the VM's do_add: text concat, list concat, numbers — else error
    if isinstance(a, str) or isinstance(b, str): return _vstr(a) + _vstr(b)
    if isinstance(a, list) and isinstance(b, list): return a + b
    if isinstance(a, (bool, int, float)) and isinstance(b, (bool, int, float)):
        return a + b
    raise _VidyaxRuntime("cannot add %s and %s" % (_b_type(a), _b_type(b)))

def _numlike2(a, b):
    return isinstance(a, (bool, int, float)) and isinstance(b, (bool, int, float))

def _div(a, b):
    if not _numlike2(a, b):
        raise _VidyaxRuntime("cannot do arithmetic on %s and %s"
                             % (_b_type(a), _b_type(b)))
    if b == 0: raise _VidyaxRuntime("cannot divide by 0")
    return a / b

def _arith(op, a, b):
    # -, *, % share the VM's rule: numbers only. Raw Python semantics
    # ("ab" * 2, "%s" % x, str TypeErrors) must never leak into Vidyax.
    if not _numlike2(a, b):
        raise _VidyaxRuntime("cannot do arithmetic on %s and %s"
                             % (_b_type(a), _b_type(b)))
    if op == "-": return a - b
    if op == "*": return a * b
    if b == 0: raise _VidyaxRuntime("cannot divide by 0")
    return a % b

def _neg(a):
    if not isinstance(a, (bool, int, float)):
        raise _VidyaxRuntime("cannot negate %s" % _b_type(a))
    return -a

def _cmp(a, b):
    # Ordering comparison shared by BOTH engines, mirroring the VM's
    # values_cmp exactly: -1/0/1, and the SAME error on incomparable
    # types (raw Python "'<' not supported..." must never leak out).
    def _numlike(v): return isinstance(v, (bool, int, float))
    if _numlike(a) and _numlike(b):
        x, y = float(a), float(b)
        return (x > y) - (x < y)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    if isinstance(a, list) and isinstance(b, list):
        for x, y in zip(a, b):
            if x == y: continue
            return _cmp(x, y)
        return (len(a) > len(b)) - (len(a) < len(b))
    raise _VidyaxRuntime("cannot compare %s with %s"
                         % (_b_type(a), _b_type(b)))

def _index(o, i):
    try: return o[int(i)]
    except Exception: raise _VidyaxRuntime("index out of range")

def _rpt(n):
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        raise _VidyaxRuntime("'rpt' needs a number")
    return range(int(n))

def _iter(x):
    if not isinstance(x, (list, str)):
        raise _VidyaxRuntime("'for ... in' needs a list or text")
    return x

def _call(f, *a):
    # Shared call gate: user-defined functions carry _vxargs/_vxname
    # (set by the transpiler) so arity errors read the same as the walker's.
    if not callable(f):
        raise _VidyaxRuntime("this is not a function")
    need = getattr(f, "_vxargs", None)
    if need is not None and len(a) != need:
        raise _VidyaxRuntime("function '%s' needs %s args, got %s"
                             % (getattr(f, "_vxname", "?"), need, len(a)))
    return f(*a)

# --- AI module: THE single implementation, used by BOTH engines ---
_AI_PROVIDERS = {
    "groq":   ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY"),
}

class _AI:
    def __init__(self):
        self.provider = "groq"
        self.model = "llama-3.1-8b-instant"
        self.system_prompt = None
        env = _os.environ.get("VIDYAX_MODEL")
        if env:
            self.open(env)
    def open(self, spec):
        # "model"            -> keep provider, switch model
        # "provider:model"   -> switch both (e.g. "openai:gpt-4o-mini")
        spec = str(spec)
        if ":" in spec:
            p, m = spec.split(":", 1)
            self.provider = p.strip().lower()
            if m.strip():
                self.model = m.strip()
        else:
            self.model = spec.strip()
        if self.provider not in _AI_PROVIDERS:
            raise _VidyaxRuntime(
                "unknown AI provider '%s' (available: %s)"
                % (self.provider, ", ".join(sorted(_AI_PROVIDERS))))
        return self
    def system(self, text):
        self.system_prompt = str(text)
        return self
    def ask(self, prompt):
        url, keyname = _AI_PROVIDERS[self.provider]
        key = _os.environ.get(keyname)
        if not key:
            raise _VidyaxRuntime(
                keyname + " is not set. Run: export " + keyname + "=...  "
                "(ai.ask needs internet & an API key)")
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": str(prompt)})
        body = _json.dumps({"model": self.model,
            "messages": messages}).encode()
        req = _ureq.Request(url,
            data=body, headers={"Authorization": "Bearer " + key,
                                "Content-Type": "application/json",
                                "User-Agent": "vidyax/1.1"})
        try:
            with _ureq.urlopen(req, timeout=60) as r:
                data = _json.loads(r.read().decode())
        except _uerr.HTTPError as e:
            raise _VidyaxRuntime("AI failed (HTTP %s): %s"
                % (e.code, e.read().decode("utf-8", "replace")[:200]))
        except Exception as e:
            raise _VidyaxRuntime("AI failed: %s" % e)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            detail = ""
            if isinstance(data, dict) and isinstance(data.get("error"), dict):
                detail = ": " + str(data["error"].get("message", ""))[:200]
            raise _VidyaxRuntime("AI gave an unexpected reply" + detail)

def _member(o, name):
    # Member-access policy, shared by both engines:
    # only Vidyax runtime objects (the ai module) expose members, and
    # underscore-prefixed Python internals are never reachable.
    if name.startswith("_"):
        raise _VidyaxRuntime("member '%s' is private" % name)
    if isinstance(o, _AI):
        try:
            return getattr(o, name)
        except AttributeError:
            raise _VidyaxRuntime("'ai' has no member '%s'" % name)
    raise _VidyaxRuntime("object has no member '%s'" % name)

# --- built-in functions ---
def _b_len(x):
    try: return len(x)
    except Exception: raise _VidyaxRuntime("len() needs a list or text")

def _b_range(*a):
    if any(not isinstance(x, (bool, int, float)) for x in a):
        raise _VidyaxRuntime("range() takes 1 to 3 numbers")
    a = [int(x) for x in a]
    if len(a) == 1: return list(range(a[0]))
    if len(a) == 2: return list(range(a[0], a[1]))
    if len(a) == 3: return list(range(a[0], a[1], a[2]))
    raise _VidyaxRuntime("range() takes 1 to 3 numbers")

def _b_text(x): return _vstr(x)

def _b_num(x):
    try:
        if isinstance(x, str) and ("." in x): return float(x)
        return int(x)
    except Exception:
        try: return float(x)
        except Exception: raise _VidyaxRuntime("cannot convert to number: " + _vstr(x))

def _b_upper(s): return _vstr(s).upper()
def _b_lower(s): return _vstr(s).lower()
def _b_split(s, sep=" "):
    sep = _vstr(sep)
    if sep == "": raise _VidyaxRuntime("empty separator")
    return _vstr(s).split(sep)
def _b_join(lst, sep=""):
    if not isinstance(lst, (list, str)):
        raise _VidyaxRuntime("join() needs a list")
    return _vstr(sep).join(_vstr(x) for x in lst)
def _b_push(lst, x):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("push() needs a list and a value")
    lst.append(x); return lst

def _b_abs(x):
    if not isinstance(x, (bool, int, float)):
        raise _VidyaxRuntime("abs() needs a number")
    return abs(x)

def _b_sum(x):
    if not isinstance(x, list) or any(
            not isinstance(v, (bool, int, float)) for v in x):
        raise _VidyaxRuntime("sum() needs a list of numbers")
    return sum(x)

def _minmax(args, want_max, fname):
    # mirrors the VM's minmax(): one list arg = its items, else the args;
    # comparisons via _cmp so mixed types fail with the same message
    items = (args[0] if len(args) == 1 and isinstance(args[0], list)
             else list(args))
    if len(items) == 0:
        raise _VidyaxRuntime("%s() needs at least one value" % fname)
    best = items[0]
    for v in items[1:]:
        c = _cmp(v, best)
        if (c > 0) if want_max else (c < 0):
            best = v
    return best

def _b_min(*a): return _minmax(a, False, "min")
def _b_max(*a): return _minmax(a, True, "max")
def _b_type(x):
    if isinstance(x, bool): return "bool"
    if isinstance(x, (int, float)): return "number"
    if isinstance(x, str): return "text"
    if isinstance(x, list): return "list"
    if x is None: return "null"
    if type(x).__name__ == "_VTask": return "task"
    return "object"

def _b_get(url):
    # Simple HTTP GET. Raises a Vidyax error on failure so the user can
    # handle it with try/catch, like every other error in the language.
    if not isinstance(url, str):
        raise _VidyaxRuntime("get() needs a text URL")
    try:
        req = _ureq.Request(url, headers={"User-Agent": "vidyax/1.1"})
        with _ureq.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except _uerr.HTTPError as e:
        raise _VidyaxRuntime("get() failed: HTTP %s %s" % (e.code, e.reason))
    except _uerr.URLError as e:
        raise _VidyaxRuntime("get() failed: cannot connect (%s)" % e.reason)
    except Exception as e:
        raise _VidyaxRuntime("get() failed: %s" % e)

def _b_readfile(path):
    if not isinstance(path, str):
        raise _VidyaxRuntime("readfile() needs a text path")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise _VidyaxRuntime("readfile() failed: %s" % (e.strerror or e))

def _b_writefile(path, txt):
    if not isinstance(path, str):
        raise _VidyaxRuntime("writefile() needs a text path and a value")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(_vstr(txt))
        return None
    except OSError as e:
        raise _VidyaxRuntime("writefile() failed: %s" % (e.strerror or e))

def _num_arg(fname, x):
    # bools count as numbers (true=1, false=0) — same as the VM's numlike()
    # and the rest of the language ("true + 1" is 2 everywhere).
    if not isinstance(x, (int, float)):
        raise _VidyaxRuntime("%s() needs a number" % fname)
    return x

def _b_floor(x): return _math.floor(_num_arg("floor", x))
def _b_ceil(x):  return _math.ceil(_num_arg("ceil", x))

def _b_round(x, nd=0):
    # Half away from zero (what beginners expect), NOT Python's banker's
    # rounding — and the exact formula the VM uses, so both engines agree.
    _num_arg("round", x); nd = int(_num_arg("round", nd))
    if nd < 0:
        raise _VidyaxRuntime("round() digits must be 0 or more")
    m = 10.0 ** nd
    v = x * m
    r = _math.floor(v + 0.5) if v >= 0 else _math.ceil(v - 0.5)
    return r / m if nd > 0 else int(r / m)

def _b_sqrt(x):
    if _num_arg("sqrt", x) < 0:
        raise _VidyaxRuntime("sqrt() needs a number >= 0")
    return _math.sqrt(x)

def _b_pow(x, y):
    try:
        r = float(_num_arg("pow", x)) ** float(_num_arg("pow", y))
    except Exception:
        raise _VidyaxRuntime("pow() result is not a number")
    if _math.isnan(r) or _math.isinf(r):
        raise _VidyaxRuntime("pow() result is not a number")
    return r

def _b_random(*a):
    if len(a) == 0:
        return _random.random()
    if len(a) == 2:
        lo, hi = int(_num_arg("random", a[0])), int(_num_arg("random", a[1]))
        if lo > hi:
            raise _VidyaxRuntime("random(a, b) needs a <= b")
        return _random.randint(lo, hi)
    raise _VidyaxRuntime("random() takes no values, or two whole numbers")

def _b_replace(s, old, new):
    old = _vstr(old)
    if old == "":
        raise _VidyaxRuntime("replace() needs a non-empty text to find")
    return _vstr(s).replace(old, _vstr(new))

def _b_trim(s): return _vstr(s).strip()

def _b_contains(x, item):
    if isinstance(x, list): return item in x
    if isinstance(x, str):  return _vstr(item) in x
    raise _VidyaxRuntime("contains() needs a list or text")

def _b_startswith(s, p): return _vstr(s).startswith(_vstr(p))
def _b_endswith(s, p):   return _vstr(s).endswith(_vstr(p))

def _b_pop(lst, i=None):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("pop() needs a list")
    if len(lst) == 0:
        raise _VidyaxRuntime("pop() on an empty list")
    try:
        return lst.pop(len(lst) - 1 if i is None else int(i))
    except Exception:
        raise _VidyaxRuntime("index out of range")

def _b_remove(lst, x):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("remove() needs a list")
    try:
        lst.remove(x)
    except ValueError:
        raise _VidyaxRuntime("remove(): value not in list")
    return lst

def _b_insert(lst, i, x):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("insert() needs a list")
    try:
        i = int(i)
    except Exception:
        raise _VidyaxRuntime("insert() needs a list")
    lst.insert(i, x)   # clamps like Python: out-of-range goes to an end
    return lst

def _sort_cat(v):
    if isinstance(v, bool) or isinstance(v, (int, float)): return "num"
    if isinstance(v, str):  return "text"
    if isinstance(v, list): return "list"
    return None   # null/functions: not orderable

def _b_sort(lst):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("sort() needs a list")
    if len(lst) > 1:
        c0 = _sort_cat(lst[0])
        for v in lst[1:]:
            if c0 is None or _sort_cat(v) != c0:
                raise _VidyaxRuntime("cannot compare %s with %s"
                                     % (_b_type(lst[0]), _b_type(v)))
        lst.sort(key=_ft.cmp_to_key(_cmp))   # VM ordering, VM error text
    return lst

def _b_reverse(lst):
    if not isinstance(lst, list):
        raise _VidyaxRuntime("reverse() needs a list")
    lst.reverse()
    return lst

def _b_find(x, item):
    if isinstance(x, list):
        for i, v in enumerate(x):
            if v == item: return i
        return -1
    if isinstance(x, str):
        return x.find(_vstr(item))
    raise _VidyaxRuntime("find() needs a list or text")

# --- tasks (`go` / wait) — docs/CONCURRENCY.md; Python's GIL IS the
# execution model: one interpreter lock, released inside blocking I/O ---
_ALL_TASKS = []

class _VTask:
    def __init__(self, name, thunk):
        self.name = name
        self.result = None
        self.err = None
        self.waited = False
        _ALL_TASKS.append(self)
        self._t = _thr.Thread(target=self._run, args=(thunk,))
        self._t.start()

    def _run(self, thunk):
        try:
            self.result = thunk()
        except _VidyaxRuntime as e:
            self.err = str(e)
        except Exception as e:   # noqa: never leak a raw traceback
            self.err = _errtext(e)

def _go(name, f, *args):
    return _VTask(name, lambda: _call(f, *args))

def _b_wait(*a):
    if len(a) != 1 or not isinstance(a[0], _VTask):
        raise _VidyaxRuntime("wait() needs a task (made with 'go')")
    t = a[0]
    t.waited = True
    t._t.join()
    if t.err is not None:
        raise _VidyaxRuntime(t.err)
    return t.result

def _finish_tasks():
    # Program end: nothing is silently lost — join every task, and a
    # failed task nobody waited for is reported like any uncaught error.
    while _ALL_TASKS:
        t = _ALL_TASKS.pop()
        t._t.join()
        if t.err is not None and not t.waited:
            raise _VidyaxRuntime("task '%s' failed: %s" % (t.name, t.err))

def _b_sleep(*a):
    if len(a) != 1 or not isinstance(a[0], (bool, int, float)) or a[0] < 0:
        raise _VidyaxRuntime("sleep() needs a number of seconds >= 0")
    _time.sleep(float(a[0]))
    return None

def _b_now(*a):
    if a:
        raise _VidyaxRuntime("now() takes no values")
    return _time.time()   # epoch seconds; for measuring durations

def _b_slice(x, a, b):
    if not isinstance(x, (list, str)):
        raise _VidyaxRuntime("slice() needs a list or text")
    try:
        return x[int(a):int(b)]
    except Exception:
        raise _VidyaxRuntime("slice() needs a list or text")

def _errtext(e):
    # Normalize Python error text into Vidyax-style wording. Used by BOTH
    # engines (try/catch + top-level reporting), so messages always match.
    m = str(e)
    if isinstance(e, UnboundLocalError):
        name = m.split("'")[1] if m.count("'") >= 2 else "?"
        # Top-level code runs inside _main(), where read-before-assign is
        # "not defined" (matching the walker and the VM); the "assigned in
        # this function" wording is only right inside a USER function.
        tb, fn = e.__traceback__, None
        while tb is not None:
            fn = tb.tb_frame.f_code.co_name
            tb = tb.tb_next
        if fn == "_main":
            return "variable '%s' is not defined" % name
        return ("variable '%s' is assigned in this function "
                "but used before it has a value" % name)
    if isinstance(e, NameError):
        if m.count("'") >= 2:
            return "variable '%s' is not defined" % m.split("'")[1]
        return m
    return m
# --- end runtime ---
'''


def _pyname(name):
    """Map a Vidyax identifier to a safe Python identifier."""
    if keyword.iskeyword(name) or name.startswith("_"):
        return "v_" + name
    return name


# Single source of truth: run the RUNTIME once to grab the built-ins,
# so the tree-walker and the transpiler share identical behaviour.
_RT_NS = {}
exec(RUNTIME, _RT_NS)

BUILTINS = {
    "len": _RT_NS["_b_len"], "range": _RT_NS["_b_range"],
    "text": _RT_NS["_b_text"], "num": _RT_NS["_b_num"],
    "upper": _RT_NS["_b_upper"], "lower": _RT_NS["_b_lower"],
    "split": _RT_NS["_b_split"], "join": _RT_NS["_b_join"],
    "push": _RT_NS["_b_push"], "abs": _RT_NS["_b_abs"],
    "sum": _RT_NS["_b_sum"], "min": _RT_NS["_b_min"],
    "max": _RT_NS["_b_max"], "type": _RT_NS["_b_type"],
    "get": _RT_NS["_b_get"],
    "readfile": _RT_NS["_b_readfile"], "writefile": _RT_NS["_b_writefile"],
    "floor": _RT_NS["_b_floor"], "ceil": _RT_NS["_b_ceil"],
    "round": _RT_NS["_b_round"], "sqrt": _RT_NS["_b_sqrt"],
    "pow": _RT_NS["_b_pow"], "random": _RT_NS["_b_random"],
    "replace": _RT_NS["_b_replace"], "trim": _RT_NS["_b_trim"],
    "contains": _RT_NS["_b_contains"],
    "startswith": _RT_NS["_b_startswith"], "endswith": _RT_NS["_b_endswith"],
    "pop": _RT_NS["_b_pop"], "remove": _RT_NS["_b_remove"],
    "insert": _RT_NS["_b_insert"], "sort": _RT_NS["_b_sort"],
    "reverse": _RT_NS["_b_reverse"], "find": _RT_NS["_b_find"],
    "slice": _RT_NS["_b_slice"],
    "sleep": _RT_NS["_b_sleep"], "now": _RT_NS["_b_now"],
    "wait": _RT_NS["_b_wait"],
}
BUILTIN_NAMES = set(BUILTINS)

# The tree-walker calls THESE — the same helpers the transpiled code calls.
RT = _RT_NS
RTError = _RT_NS["_VidyaxRuntime"]
vidyax_str = _RT_NS["_vstr"]


def _rt(fn, line, *args):
    """Call a shared runtime helper from the walker; convert its errors
    into VidyaxError so they carry a .vx line number."""
    try:
        return fn(*args)
    except RTError as e:
        raise VidyaxError(str(e), line, kind="runtime")


def _stmt_line(n):
    """Best source line for a statement. Statement nodes don't carry a line,
    but their expression children (which are where runtime errors fire) do."""
    ln = getattr(n, "line", None)
    if ln:
        return ln
    for attr in ("value", "expr", "cond", "count", "iterable", "prompt"):
        ln = getattr(getattr(n, attr, None), "line", None)
        if ln:
            return ln
    return None


class Transpiler:
    """Turn a Vidyax AST into Python source code."""
    def __init__(self):
        self.lines = []
        self.linemap = []      # parallel to self.lines: source .vx line per output line
        self.cur_line = 0      # .vx line of the statement being emitted
        self.rpt_counter = 0

    def emit(self, indent, text):
        self.lines.append("    " * indent + text)
        self.linemap.append(self.cur_line)

    def transpile(self, program):
        self.block(program.body, 1)  # body lives inside _main()
        if not self.lines:
            self.emit(1, "pass")
        return "\n".join(self.lines)

    def block(self, body, indent):
        if not body:
            self.emit(indent, "pass")
            return
        for stmt in body:
            self.stmt(stmt, indent)

    # --- statements ---
    def stmt(self, n, indent):
        t = type(n).__name__
        # remember the source line so every line emitted for this statement
        # maps back to the original .vx for runtime-error reporting
        self.cur_line = _stmt_line(n) or self.cur_line
        if t == "Assign":
            self.emit(indent, f"{_pyname(n.name)} = {self.expr(n.value)}")
        elif t == "Print":
            self.emit(indent, f"print(_vstr({self.expr(n.expr)}))")
        elif t == "If":
            self.emit(indent, f"if {self.expr(n.cond)}:")
            self.block(n.body, indent + 1)
            self._tail_else(n.orelse, indent)
        elif t == "RepeatN":
            v = f"_i{self.rpt_counter}"; self.rpt_counter += 1
            self.emit(indent, f"for {v} in _rpt({self.expr(n.count)}):")
            self.block(n.body, indent + 1)
        elif t == "ForEach":
            self.emit(indent, f"for {_pyname(n.var)} in _iter({self.expr(n.iterable)}):")
            self.block(n.body, indent + 1)
        elif t == "FuncDef":
            params = ", ".join(_pyname(p) for p in n.params)
            py = _pyname(n.name)
            self.emit(indent, f"def {py}({params}):")
            self.block(n.body, indent + 1)
            self.emit(indent, f"{py}._vxargs = {len(n.params)}")
            self.emit(indent, f"{py}._vxname = {n.name!r}")
        elif t == "Return":
            self.emit(indent, "return" if n.value is None else f"return {self.expr(n.value)}")
        elif t == "Break":
            self.emit(indent, "break")
        elif t == "Continue":
            self.emit(indent, "continue")
        elif t == "TryCatch":
            self.emit(indent, "try:")
            self.block(n.try_body, indent + 1)
            self.emit(indent, "except Exception as _exc:")
            if n.err_var:
                self.emit(indent + 1, f"{_pyname(n.err_var)} = _errtext(_exc)")
            self.block(n.catch_body, indent + 1)
        elif t == "Import":
            if n.name == "ai":
                self.emit(indent, "ai = _AI()")
            elif n.name in ("web", "database"):
                raise VidyaxError(f"module '{n.name}' is not supported yet (roadmap)")
            else:
                raise VidyaxError(f"unknown module '{n.name}'")
        elif t == "ExprStmt":
            self.emit(indent, self.expr(n.expr))
        else:
            raise VidyaxError(f"cannot compile {t}")

    def _tail_else(self, orelse, indent):
        if not orelse:
            return
        # elif chain comes through as a single nested If
        if len(orelse) == 1 and type(orelse[0]).__name__ == "If":
            inner = orelse[0]
            self.cur_line = _stmt_line(inner) or self.cur_line
            self.emit(indent, f"elif {self.expr(inner.cond)}:")
            self.block(inner.body, indent + 1)
            self._tail_else(inner.orelse, indent)
        else:
            self.emit(indent, "else:")
            self.block(orelse, indent + 1)

    # --- expressions ---
    def expr(self, n):
        t = type(n).__name__
        if t == "Number":
            return repr(n.v)
        if t == "Str":
            return json.dumps(n.v)
        if t == "Bool":
            return "True" if n.v else "False"
        if t == "Null":
            return "None"
        if t == "ListLit":
            return "[" + ", ".join(self.expr(x) for x in n.items) + "]"
        if t == "Var":
            return _pyname(n.name)
        if t == "Input":
            return f"input(_vstr({self.expr(n.prompt)}) + ' ')"
        if t == "UnaryOp":
            if n.op == "not":
                return f"(not {self.expr(n.operand)})"
            return f"_neg({self.expr(n.operand)})"
        if t == "BinOp":
            l = self.expr(n.l); r = self.expr(n.r)
            if n.op == "and": return f"({l} and {r})"
            if n.op == "or":  return f"({l} or {r})"
            if n.op == "+":   return f"_add({l}, {r})"
            if n.op == "/":   return f"_div({l}, {r})"
            if n.op in ("-", "*", "%"):
                return f"_arith({n.op!r}, {l}, {r})"
            if n.op in ("<", ">", "<=", ">="):   # ordering: VM semantics
                return f"(_cmp({l}, {r}) {n.op} 0)"
            return f"({l} {n.op} {r})"   # == and != map 1:1
        if t == "Call":
            args = ", ".join(self.expr(a) for a in n.args)
            callee = n.callee
            if type(callee).__name__ == "Var" and callee.name in BUILTIN_NAMES:
                return f"_b_{callee.name}({args})"
            joined = (", " + args) if args else ""
            return f"_call({self.expr(callee)}{joined})"
        if t == "GoTask":
            call = n.call
            args = ", ".join(self.expr(a) for a in call.args)
            callee = call.callee
            if type(callee).__name__ == "Var" and callee.name in BUILTIN_NAMES:
                fn, cname = f"_b_{callee.name}", callee.name
            else:
                fn = self.expr(callee)
                cname = (callee.name
                         if type(callee).__name__ == "Var" else "task")
            joined = (", " + args) if args else ""
            return f"_go({cname!r}, {fn}{joined})"
        if t == "Member":
            return f"_member({self.expr(n.obj)}, {n.name!r})"
        if t == "Index":
            return f"_index({self.expr(n.obj)}, {self.expr(n.idx)})"
        raise VidyaxError(f"cannot compile expression {t}")


def _transpile_program(source, standalone=True, base_dir=None):
    """Vidyax source -> (Python source string, {python_line: vx_line}).

    The line map lets the fast path translate a runtime traceback back to
    the original .vx line (the generated Python is compiled as <vidyax>)."""
    ast = _parse_source(source, base_dir)
    _typecheck(ast)
    tr = Transpiler()
    body = tr.transpile(ast)

    header = []
    if standalone:
        header.append("#!/usr/bin/env python3")
    header.append(RUNTIME)
    header.append("def _main():")
    header_str = "\n".join(header)
    offset = header_str.count("\n") + 1   # number of lines before the body

    footer = "\n".join([
        "",
        "if __name__ == '__main__':",
        "    import sys as _sys",
        "    try:",
        "        _main()",
        "    except _VidyaxRuntime as _e:",
        "        print('[Vidyax] ' + str(_e)); _sys.exit(1)",
        "    except Exception as _e:",
        "        print('[Vidyax] ' + _errtext(_e)); _sys.exit(1)",
    ])
    py = header_str + "\n" + body + "\n" + footer + "\n"
    # body line i (0-based) lands on python line offset + i + 1
    linemap = {offset + i + 1: vx for i, vx in enumerate(tr.linemap) if vx}
    return py, linemap


def compile_to_python(source, standalone=True, base_dir=None):
    """Vidyax source -> Python source string."""
    py, _ = _transpile_program(source, standalone, base_dir)
    return py


def _vx_line(tb, linemap):
    """Walk a traceback and return the .vx line of the deepest frame in the
    generated <vidyax> source that maps to a real statement. Runtime-helper
    frames (inside RUNTIME) aren't in the map, so they're skipped — the
    result is the user's own line, not the helper's."""
    line = None
    while tb is not None:
        f = tb.tb_frame
        if f.f_code.co_filename == "<vidyax>":
            mapped = linemap.get(tb.tb_lineno)
            if mapped:
                line = mapped
        tb = tb.tb_next
    return line


def run_fast_text(source, base_dir=None):
    """Transpile to Python and execute in-memory (the fast path).
    Raises VidyaxError on failure — used by the CLI and by the
    differential tests, which run every case through BOTH engines."""
    py, linemap = _transpile_program(source, standalone=False,
                                     base_dir=base_dir)
    ns = {"__name__": "_vax_main"}
    exec(compile(py, "<vidyax>", "exec"), ns)
    try:
        ns["_main"]()
        ns["_finish_tasks"]()   # join tasks; surface unwaited failures
    except VidyaxError:
        raise
    except Exception as e:
        line = _vx_line(e.__traceback__, linemap)
        # _VidyaxRuntime is defined inside ns (fresh class per program)
        if type(e).__name__ == "_VidyaxRuntime":
            raise VidyaxError(str(e), line, kind="runtime")
        # dynamic runtime errors the static type_check() pass couldn't
        # see — report them Vidyax-style instead of a raw traceback
        # (_errtext also maps top-level UnboundLocal -> "not defined")
        raise VidyaxError(ns["_errtext"](e), line, kind=_runtime_kind(e))


def run_fast(source, base_dir=None):
    try:
        run_fast_text(source, base_dir)
    except VidyaxError as e:
        print(e.show()); sys.exit(1)


def build_file(path):
    """Write a standalone <name>.py next to the .vx file."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    py = compile_to_python(source, standalone=True,
                           base_dir=os.path.dirname(os.path.abspath(path)))
    out = os.path.splitext(path)[0] + ".py"
    with open(out, "w", encoding="utf-8") as f:
        f.write(py)
    return out


# =====================================================================
# 6b. PACKAGE MANAGER  (vidyax install)
# =====================================================================

def _install_urls(spec):
    """Turn an install spec into candidate download URLs.
      user/repo         -> GitHub raw <repo>.vx (main, then master)
      user/repo@ref     -> that ref
      user/repo/path.vx -> that exact file in the repo
      http(s)://...     -> used verbatim
      file://... / path -> a local file (for offline use/testing)
    Returns (module_name, [urls])."""
    if spec.startswith(("http://", "https://", "file://")):
        name = os.path.splitext(os.path.basename(spec.split("?")[0]))[0]
        return name, [spec]
    ref, ref_given = "main", False
    if "@" in spec:
        spec, ref = spec.rsplit("@", 1)
        ref_given = True
    parts = spec.split("/")
    if len(parts) < 2:
        raise VidyaxError("install needs 'user/repo' or a URL")
    user, repo = parts[0], parts[1]
    base = f"https://raw.githubusercontent.com/{user}/{repo}"
    refs = [ref] if ref_given else ["main", "master"]
    if len(parts) > 2:                      # explicit path inside the repo
        sub = "/".join(parts[2:])
        if not sub.endswith(".vx"):
            sub += ".vx"
        name = os.path.splitext(os.path.basename(sub))[0]
        return name, [f"{base}/{r}/{sub}" for r in refs]
    # bare user/repo: fetch <repo>.vx from the repo root, main then master
    return repo, [f"{base}/{r}/{repo}.vx" for r in refs]


def install_module(spec, dest=None):
    """Download a single-file Vidyax module into vx_modules/. The file is
    parsed before it's saved, so a broken download never lands on disk."""
    import urllib.request
    import urllib.error
    name, urls = _install_urls(spec)
    dest = dest or os.path.join(os.getcwd(), "vx_modules")
    os.makedirs(dest, exist_ok=True)
    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "vidyax-install"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} for {url}"
            continue
        except urllib.error.URLError as e:
            last_err = f"cannot reach {url} ({e.reason})"
            continue
        except OSError as e:
            last_err = str(e)
            continue
        try:
            Parser(lex(data)).parse()          # validate before saving
        except VidyaxError as e:
            raise VidyaxError(f"downloaded module '{name}' has an error: "
                              f"{e.msg}")
        out = os.path.join(dest, name + ".vx")
        with open(out, "w", encoding="utf-8") as f:
            f.write(data)
        return name, out
    raise VidyaxError(f"install failed for '{spec}': {last_err}")


# =====================================================================
# 7. CLI
# =====================================================================

def run_file(path):
    """Default: fast path (transpile to Python, then run)."""
    if not os.path.exists(path):
        print(f"[Vidyax] file not found: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        source = f.read()
    run_fast(source, os.path.dirname(os.path.abspath(path)))


def walk_file(path):
    """Tree-walking interpreter (slower; for debugging)."""
    if not os.path.exists(path):
        print(f"[Vidyax] file not found: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        base_dir = os.path.dirname(os.path.abspath(path))
        ast = _parse_source(source, base_dir)
        _typecheck(ast)
        Interpreter().run(ast)
        RT["_finish_tasks"]()
    except VidyaxError as e:
        print(e.show())
        sys.exit(1)
    except Exception as e:
        # catch-all: dynamic runtime errors the static type_check() pass
        # couldn't see (values only known at runtime).
        print(VidyaxError(RT["_errtext"](e), kind=_runtime_kind(e)).show())
        sys.exit(1)


def check_source(source, base_dir=None):
    """Static check only: lex + parse + type_check, NO execution.
    Returns a list of {"line", "message"} dicts (empty if the code is clean).
    Used by editors for live error reporting."""
    errors = []
    try:
        _typecheck(_parse_source(source, base_dir))
    except VidyaxError as e:
        errors.append({"line": e.line if e.line is not None else 1,
                       "message": e.msg, "kind": e.kind})
    except Exception:
        # Never leak a Python traceback to the editor; just report nothing.
        return []
    return errors


def check_file(path):
    """Read from a file (or STDIN if path == '-'), print JSON errors, exit 0."""
    try:
        if path == "-":
            source = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as f:
                source = f.read()
    except Exception:
        print("[]")
        return
    base_dir = (os.getcwd() if path == "-"
                else os.path.dirname(os.path.abspath(path)))
    print(json.dumps(check_source(source, base_dir)))


def run_text(source, base_dir=None):
    """Tree-walk a program. Raises VidyaxError on failure — the walker
    twin of run_fast_text, used by the REPL and the differential tests."""
    ast = _parse_source(source, base_dir)
    _typecheck(ast)
    try:
        Interpreter().run(ast)
        RT["_finish_tasks"]()   # join tasks; surface unwaited failures
    except VidyaxError:
        raise
    except Exception as e:
        raise VidyaxError(RT["_errtext"](e), kind=_runtime_kind(e))


def _repl_exec(interp, src):
    try:
        prog = _typecheck(_parse_source(src))
        # echo the value of a single bare expression, like a calculator
        if len(prog.body) == 1 and type(prog.body[0]).__name__ == "ExprStmt":
            val = interp.eval(prog.body[0].expr, interp.global_env)
            if val is not None:
                print(vidyax_str(val))
        else:
            for st in prog.body:
                interp.exec(st, interp.global_env)
    except VidyaxError as e:
        print(e.show())
    except Exception as e:
        print(VidyaxError(RT["_errtext"](e), kind=_runtime_kind(e)).show())


def _repl_incomplete(src):
    """True if `src` parses as an UNFINISHED block — more lines can still
    complete it (e.g. `if x:` with no body yet, or `try:` without its
    `catch`). Real mistakes (bad tokens, unknown names) return False so
    they are reported immediately instead of swallowing more input."""
    try:
        _typecheck(_parse_source(src if src.endswith("\n") else src + "\n"))
        return False
    except VidyaxError as e:
        return ("the end of the program" in e.msg
                or "must be followed by 'catch'" in e.msg)
    except Exception:
        return False


def repl():
    print(f"Vidyax v{VERSION} REPL")
    print("  blocks:  end with a blank line to run.  Ctrl-C cancels a block,")
    print("           Ctrl-D exits")
    interp = Interpreter()
    pending = []
    while True:
        try:
            line = input("...  " if pending else "vidyax> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            # ^C drops the half-typed block but keeps the session alive
            print()
            pending = []
            continue
        if pending:
            if line.strip() == "":
                src = "\n".join(pending)
                if _repl_incomplete(src):
                    continue   # e.g. `try:` still waiting for its `catch`
                try:
                    _repl_exec(interp, src)
                except KeyboardInterrupt:
                    print("\n[Vidyax] stopped")
                pending = []
            else:
                pending.append(line)
            continue
        if line.strip() == "":
            continue
        # a trailing ':' *or* any still-unfinished construct opens a block
        if line.rstrip().endswith(":") or _repl_incomplete(line):
            pending = [line]
            continue
        try:
            _repl_exec(interp, line)
        except KeyboardInterrupt:
            print("\n[Vidyax] stopped")


def main():
    args = sys.argv[1:]
    if not args:
        repl()
        return
    if args[0] in ("-h", "--help", "help"):
        print(
            f"Vidyax v{VERSION}\n"
            "  vidyax                     start the interactive REPL\n"
            "  vidyax <file.vx>           run a file (fast: compiles to Python)\n"
            "  vidyax run <file.vx>       run a file\n"
            "  vidyax build <file.vx>     compile to a standalone <file>.py\n"
            "  vidyax bytecode <file.vx>  compile to VVM bytecode <file>.vxc\n"
            "  vidyax disasm <file.vxc>   disassemble VVM bytecode (or a .vx)\n"
            "  vidyax debug <file.vx>     run under the VVM line debugger\n"
            "  vidyax profile <file.vx>   run + per-line instruction profile\n"
            "  vidyax native <file.vx>    compile to a standalone native binary\n"
            "  vidyax walk <file.vx>      run with the tree-walker (debug)\n"
            "  vidyax check <file.vx|->    static check only, JSON errors (- = stdin)\n"
            "  vidyax lsp                 start the Language Server (stdio)\n"
            "  vidyax install <user/repo> download a module into vx_modules/\n"
            "  vidyax test                run built-in tests (both engines)\n"
        )
        return
    cmd = args[0]
    if cmd == "run":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax run <file.vx>"); sys.exit(1)
        run_file(args[1])
    elif cmd == "build":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax build <file.vx>"); sys.exit(1)
        try:
            out = build_file(args[1])
            print(f"[Vidyax] compiled -> {out}")
        except VidyaxError as e:
            print(e.show()); sys.exit(1)
    elif cmd == "bytecode":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax bytecode <file.vx>"); sys.exit(1)
        try:
            import vxc  # noqa: the VVM compiler lives in vxc.py
            print(f"[Vidyax] bytecode -> {vxc.compile_file(args[1])}")
        except VidyaxError as e:
            print(e.show()); sys.exit(1)
    elif cmd == "walk":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax walk <file.vx>"); sys.exit(1)
        walk_file(args[1])
    elif cmd == "check":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax check <file.vx | ->"); sys.exit(1)
        check_file(args[1])
    elif cmd in ("debug", "profile"):
        if len(args) < 2:
            print(f"[Vidyax] usage: vidyax {cmd} <file.vx> [vxvm flags]")
            sys.exit(1)
        vm_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "vm", "vxvm")
        if not os.path.exists(vm_bin):
            print("[Vidyax] vxvm is not built yet — run: make -C vm")
            sys.exit(1)
        try:
            import subprocess
            import tempfile
            import vxc  # noqa
            c = vxc.compile_source(open(args[1], encoding="utf-8").read())
            with tempfile.NamedTemporaryFile(suffix=".vxc") as f:
                f.write(c.serialize()); f.flush()
                # extra flags (e.g. --allow-net) pass straight to vxvm
                r = subprocess.run([vm_bin, f"--{cmd}", *args[2:], f.name])
            sys.exit(r.returncode)
        except VidyaxError as e:
            print(e.show()); sys.exit(1)
        except OSError as e:
            print(f"[Vidyax] cannot read {args[1]}: {e.strerror}"); sys.exit(1)
    elif cmd == "disasm":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax disasm <file.vxc|file.vx>"); sys.exit(1)
        try:
            import vxc  # noqa
            print(vxc.disasm_file(args[1]), end="")
        except VidyaxError as e:
            print(e.show()); sys.exit(1)
        except OSError as e:
            print(f"[Vidyax] cannot read {args[1]}: {e.strerror}"); sys.exit(1)
    elif cmd == "native":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax native <file.vx> [-o out]")
            sys.exit(1)
        out = None
        if "-o" in args:
            i = args.index("-o")
            if i + 1 >= len(args):
                print("[Vidyax] -o needs a path"); sys.exit(1)
            out = args[i + 1]
        try:
            import vxnative  # noqa
            print(f"[Vidyax] native -> {vxnative.native_file(args[1], out)}")
        except VidyaxError as e:
            print(e.show()); sys.exit(1)
        except OSError as e:
            print(f"[Vidyax] cannot read {args[1]}: {e.strerror}"); sys.exit(1)
    elif cmd == "lsp":
        import vxlsp  # noqa: the LSP server lives in vxlsp.py
        vxlsp.main()
    elif cmd == "test":
        from tests import run_all_tests  # noqa
        run_all_tests()
    elif cmd == "install":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax install <user/repo | url> ...")
            sys.exit(1)
        failed = False
        for spec in args[1:]:
            try:
                name, out = install_module(spec)
                print(f"[Vidyax] installed '{name}' -> {out}")
            except VidyaxError as e:
                print(e.show()); failed = True
        if failed:
            sys.exit(1)
    elif cmd == "fmt":
        print(f"[Vidyax] command '{cmd}' is not supported yet (roadmap)")
    elif cmd.endswith((".vx", ".vax")) or os.path.exists(cmd):
        run_file(cmd)  # direct: vidyax main.vx
    else:
        print(f"[Vidyax] unknown command or file: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
