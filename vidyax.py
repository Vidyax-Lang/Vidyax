#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vidyax - interpreter v1.0
"Code as simple as writing instructions."

Single file: lexer -> parser -> evaluator + CLI.
Usage:
    python vidyax.py run main.vx
    python vidyax.py test
"""

import sys
import os
import json
import urllib.request
import urllib.error

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
    """User-friendly error for Vidyax programs."""
    def __init__(self, msg, line=None):
        self.msg = msg
        self.line = line
        super().__init__(msg)

    def show(self):
        if self.line:
            return f"[Vidyax] line {self.line}: {self.msg}"
        return f"[Vidyax] {self.msg}"


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
                raise VidyaxError("inconsistent indentation", line_no)

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


# =====================================================================
# 3. PARSER
# =====================================================================

class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

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
            raise VidyaxError(f"expected {kind}, got {t.kind} ({t.value!r})", t.line)
        if value is not None and t.value != value:
            raise VidyaxError(f"expected {value!r}, got {t.value!r}", t.line)
        self.pos += 1
        return t

    def skip_newlines(self):
        while self.at("NEWLINE"):
            self.pos += 1

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
                self.eat(); self.eat("NEWLINE"); return Break()
            if t.value == "continue":
                self.eat(); self.eat("NEWLINE"); return Continue()
            if t.value in ("agent", "go"):
                raise VidyaxError(f"'{t.value}' is not supported yet (roadmap)", t.line)
        # assignment: NAME ':' expr
        if t.kind == "NAME" and self.peek(1).kind == "OP" and self.peek(1).value == ":":
            name = self.eat("NAME").value
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
        body = self.block()
        return RepeatN(count, body)

    def stmt_for(self):
        self.eat("KEYWORD", "for")
        var = self.eat("NAME").value
        self.eat("KEYWORD", "in")
        it = self.expression()
        body = self.block()
        return ForEach(var, it, body)

    def stmt_func(self):
        self.eat("KEYWORD", "func")
        name = self.eat("NAME").value
        self.eat("OP", "(")
        params = []
        if not self.at("OP", ")"):
            params.append(self.eat("NAME").value)
            while self.at("OP", ","):
                self.eat("OP", ",")
                params.append(self.eat("NAME").value)
        self.eat("OP", ")")
        body = self.block()
        return FuncDef(name, params, body)

    def stmt_return(self):
        self.eat("KEYWORD", "return")
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
            err_var = self.eat("NAME").value
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
            raise VidyaxError("incomplete expression", t.line)
        raise VidyaxError(f"unexpected '{t.value}'", t.line)


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
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def get(self, name, line=None):
        env = self
        while env:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise VidyaxError(f"variable '{name}' is not defined", line)

    def set(self, name, value):
        self.vars[name] = value


def vidyax_str(v):
    if v is True:  return "true"
    if v is False: return "false"
    if v is None:  return "null"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, list):
        return "[" + ", ".join(vidyax_str(x) for x in v) + "]"
    return str(v)


def vidyax_truthy(v):
    if isinstance(v, bool): return v
    if v is None: return False
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, (str, list)): return len(v) > 0
    return True


class AIModule:
    """Built-in 'ai' module. ai.open "model" to pick model, ai.ask "..." to ask."""
    def __init__(self):
        self.provider = "groq"
        self.model = os.environ.get("VIDYAX_MODEL", "llama-3.1-8b-instant")

    def open(self, spec):
        spec = str(spec)
        if ":" in spec:
            self.provider, self.model = spec.split(":", 1)
        else:
            self.model = spec
            return self

    def ask(self, prompt):
        if self.provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            keyname = "OPENAI_API_KEY"
        else:
            url = "https://api.groq.com/openai/v1/chat/completions"
            keyname = "GROQ_API_KEY"
        key = os.environ.get(keyname)
        if not key:
            raise VidyaxError(
                keyname + " is not set. Run: export " + keyname + "=..."
                "(ai.ask needs internet & an API key)"
            )
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": str(prompt)}]}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "vidyax/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise VidyaxError(f"AI failed ({e.code}): {e.read().decode()[:200]}")
        except Exception as e:
            raise VidyaxError(f"AI failed: {e}")


class BoundMethod:
    def __init__(self, fn): self.fn = fn
    def __call__(self, *a): return self.fn(*a)


# =====================================================================
# 5. INTERPRETER
# =====================================================================

class Interpreter:
    def __init__(self):
        self.global_env = Environment()
        self.modules = {}
        for name, fn in BUILTINS.items():
            self.global_env.set(name, BoundMethod(fn))

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
        count = self.eval(n.count, env)
        if not isinstance(count, (int, float)) or isinstance(count, bool):
            raise VidyaxError("'rpt' needs a number")
        for _ in range(int(count)):
            try:
                self.exec_block(n.body, env)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def exec_ForEach(self, n, env):
        it = self.eval(n.iterable, env)
        if not isinstance(it, (list, str)):
            raise VidyaxError("'for ... in' needs a list or text")
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
                env.set(n.err_var, str(e))
            self.exec_block(n.catch_body, env)

    def exec_Import(self, n, env):
        if n.name == "ai":
            mod = AIModule()
            self.modules["ai"] = mod
            env.set("ai", mod)
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
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise VidyaxError("'-' only works on numbers", n.line)
            return -v

    def eval_BinOp(self, n, env):
        if n.op == "and":
            l = self.eval(n.l, env)
            return self.eval(n.r, env) if vidyax_truthy(l) else l
        if n.op == "or":
            l = self.eval(n.l, env)
            return l if vidyax_truthy(l) else self.eval(n.r, env)
        l = self.eval(n.l, env); r = self.eval(n.r, env)
        if n.op == "+":
            if isinstance(l, str) or isinstance(r, str):
                return vidyax_str(l) + vidyax_str(r)
            if isinstance(l, list) and isinstance(r, list):
                return l + r
            return l + r
        if n.op == "-": return l - r
        if n.op == "*": return l * r
        if n.op == "/":
            if r == 0: raise VidyaxError("cannot divide by 0", n.line)
            return l / r
        if n.op == "%": return l % r
        if n.op == "==": return l == r
        if n.op == "!=": return l != r
        if n.op == "<": return l < r
        if n.op == ">": return l > r
        if n.op == "<=": return l <= r
        if n.op == ">=": return l >= r
        raise VidyaxError(f"unknown operator {n.op}", n.line)

    def eval_Member(self, n, env):
        obj = self.eval(n.obj, env)
        if isinstance(obj, AIModule):
            attr = getattr(obj, n.name, None)
            if callable(attr):
                return BoundMethod(attr)
            raise VidyaxError(f"'ai' has no member '{n.name}'", n.line)
        raise VidyaxError(f"object has no member '{n.name}'", n.line)

    def eval_Index(self, n, env):
        obj = self.eval(n.obj, env)
        idx = self.eval(n.idx, env)
        try:
            return obj[int(idx)]
        except Exception:
            raise VidyaxError("index out of range", n.line)

    def eval_Call(self, n, env):
        callee = self.eval(n.callee, env)
        args = [self.eval(a, env) for a in n.args]
        if isinstance(callee, BoundMethod):
            return callee(*args)
        if isinstance(callee, Function):
            return self.call_function(callee, args, n.line)
        raise VidyaxError("this is not a function", n.line)

    def call_function(self, fn, args, line):
        if len(args) != len(fn.decl.params):
            raise VidyaxError(
                f"function '{fn.decl.name}' needs {len(fn.decl.params)} args, "
                f"got {len(args)}", line)
        local = Environment(fn.closure)
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

def type_check(program):
    for node in _walk(program):
        if isinstance(node, BinOp) and node.op in _ARITH:
            for side in (node.l, node.r):
                t = infer_type(side)
                if t is not None and t != "number":
                    raise VidyaxError(
                        f"cannot use '{node.op}' on {t}, only numbers", node.line)

# =====================================================================
# 6. TRANSPILER  (Vidyax -> Python, for speed)
# =====================================================================

import keyword

# Runtime helpers injected into every compiled program.
RUNTIME = '''# --- Vidyax runtime (auto-generated) ---
import os as _os, json as _json, urllib.request as _ureq, urllib.error as _uerr

class _VidyaxRuntime(Exception): pass

def _vstr(v):
    if v is True: return "true"
    if v is False: return "false"
    if v is None: return "null"
    if isinstance(v, float): return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, list): return "[" + ", ".join(_vstr(x) for x in v) + "]"
    return str(v)

def _add(a, b):
    if isinstance(a, str) or isinstance(b, str): return _vstr(a) + _vstr(b)
    return a + b

def _div(a, b):
    if b == 0: raise _VidyaxRuntime("cannot divide by 0")
    return a / b

def _index(o, i):
    try: return o[int(i)]
    except Exception: raise _VidyaxRuntime("index out of range")

class _AI:
    def __init__(self):
        self.model = _os.environ.get("VIDYAX_MODEL", "llama-3.3-70b-versatile")
    def open(self, model):
        self.model = str(model); return self
    def ask(self, prompt):
        key = _os.environ.get("GROQ_API_KEY")
        if not key:
            raise _VidyaxRuntime("GROQ_API_KEY is not set (ai.ask needs internet & an API key)")
        body = _json.dumps({"model": self.model,
            "messages": [{"role": "user", "content": str(prompt)}]}).encode()
        req = _ureq.Request("https://api.groq.com/openai/v1/chat/completions",
            data=body, headers={"Authorization": "Bearer " + key,
                                "Content-Type": "application/json","User-Agent": "vidyax/1.0"})
        try:
            with _ureq.urlopen(req, timeout=60) as r:
                data = _json.loads(r.read().decode())
            return data["choices"][0]["message"]["content"]
        except _uerr.HTTPError as e:
            raise _VidyaxRuntime("AI failed (%s)" % e.code)
        except Exception as e:
            raise _VidyaxRuntime("AI failed: %s" % e)

# --- built-in functions ---
def _b_len(x):
    try: return len(x)
    except Exception: raise _VidyaxRuntime("len() needs a list or text")

def _b_range(*a):
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

def _b_upper(s): return str(s).upper()
def _b_lower(s): return str(s).lower()
def _b_split(s, sep=" "): return str(s).split(sep)
def _b_join(lst, sep=""): return str(sep).join(_vstr(x) for x in lst)
def _b_push(lst, x):
    lst.append(x); return lst
def _b_abs(x): return abs(x)
def _b_sum(x): return sum(x)
def _b_min(*a):
    return min(a[0]) if (len(a) == 1 and isinstance(a[0], list)) else min(a)
def _b_max(*a):
    return max(a[0]) if (len(a) == 1 and isinstance(a[0], list)) else max(a)
def _b_type(x):
    if isinstance(x, bool): return "bool"
    if isinstance(x, (int, float)): return "number"
    if isinstance(x, str): return "text"
    if isinstance(x, list): return "list"
    if x is None: return "null"
    return "object"

def _b_get(url):
    # Simple HTTP GET. Returns the response text, or an error string
    # (so the user's program does not crash on a bad connection).
    try:
        req = _ureq.Request(str(url), headers={"User-Agent": "Vidyax/0.1"})
        with _ureq.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except _uerr.HTTPError as e:
        return "ERROR_HTTP: %s %s" % (e.code, e.reason)
    except _uerr.URLError as e:
        return "ERROR_CONNECTION: %s" % e.reason
    except Exception as e:
        return "ERROR: %s" % e

def _errtext(e):
    # Normalize Python error text into Vidyax-style wording (for try/catch).
    m = str(e)
    if isinstance(e, NameError):
        return m.replace("name '", "variable '", 1)
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
}
BUILTIN_NAMES = set(BUILTINS)


class Transpiler:
    """Turn a Vidyax AST into Python source code."""
    def __init__(self):
        self.lines = []
        self.rpt_counter = 0

    def emit(self, indent, text):
        self.lines.append("    " * indent + text)

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
            self.emit(indent, f"for {v} in range(int({self.expr(n.count)})):")
            self.block(n.body, indent + 1)
        elif t == "ForEach":
            self.emit(indent, f"for {_pyname(n.var)} in {self.expr(n.iterable)}:")
            self.block(n.body, indent + 1)
        elif t == "FuncDef":
            params = ", ".join(_pyname(p) for p in n.params)
            self.emit(indent, f"def {_pyname(n.name)}({params}):")
            self.block(n.body, indent + 1)
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
            return f"(-{self.expr(n.operand)})"
        if t == "BinOp":
            l = self.expr(n.l); r = self.expr(n.r)
            if n.op == "and": return f"({l} and {r})"
            if n.op == "or":  return f"({l} or {r})"
            if n.op == "+":   return f"_add({l}, {r})"
            if n.op == "/":   return f"_div({l}, {r})"
            if n.op in ("-", "*", "%"): return f"({l} {n.op} {r})"
            return f"({l} {n.op} {r})"   # comparisons map 1:1
        if t == "Call":
            args = ", ".join(self.expr(a) for a in n.args)
            callee = n.callee
            if type(callee).__name__ == "Var" and callee.name in BUILTIN_NAMES:
                return f"_b_{callee.name}({args})"
            return f"{self.expr(callee)}({args})"
        if t == "Member":
            return f"{self.expr(n.obj)}.{n.name}"
        if t == "Index":
            return f"_index({self.expr(n.obj)}, {self.expr(n.idx)})"
        raise VidyaxError(f"cannot compile expression {t}")


def compile_to_python(source, standalone=True):
    """Vidyax source -> Python source string."""
    tokens = lex(source)
    ast = Parser(tokens).parse()
    type_check(ast)
    body = Transpiler().transpile(ast)
    parts = []
    if standalone:
        parts.append("#!/usr/bin/env python3")
    parts.append(RUNTIME)
    parts.append("def _main():")
    parts.append(body)
    parts.append("")
    parts.append("if __name__ == '__main__':")
    parts.append("    import sys as _sys")
    parts.append("    try:")
    parts.append("        _main()")
    parts.append("    except _VidyaxRuntime as _e:")
    parts.append("        print('[Vidyax] ' + str(_e)); _sys.exit(1)")
    return "\n".join(parts) + "\n"


def run_fast(source):
    """Transpile to Python and execute in-memory (the fast path)."""
    py = compile_to_python(source, standalone=False)
    ns = {"__name__": "_vax_main"}
    exec(compile(py, "<vidyax>", "exec"), ns)
    try:
        ns["_main"]()
    except Exception as e:
        # _VidyaxRuntime defined inside ns
        if type(e).__name__ == "_VidyaxRuntime":
            print("[Vidyax] " + str(e)); sys.exit(1)
        raise


def build_file(path):
    """Write a standalone <name>.py next to the .vx file."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    py = compile_to_python(source, standalone=True)
    out = os.path.splitext(path)[0] + ".py"
    with open(out, "w", encoding="utf-8") as f:
        f.write(py)
    return out


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
    try:
        run_fast(source)
    except VidyaxError as e:
        print(e.show())
        sys.exit(1)


def walk_file(path):
    """Tree-walking interpreter (slower; for debugging)."""
    if not os.path.exists(path):
        print(f"[Vidyax] file not found: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        tokens = lex(source)
        ast = Parser(tokens).parse()
        type_check(ast)
        Interpreter().run(ast)
    except VidyaxError as e:
        print(e.show())
        sys.exit(1)


def run_text(source):
    tokens = lex(source)
    ast = Parser(tokens).parse()
    Interpreter().run(ast)


def _repl_exec(interp, src):
    try:
        prog = Parser(lex(src)).parse()
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
    except (BreakSignal, ContinueSignal, ReturnSignal):
        print("[Vidyax] break/continue/return only work inside loops/functions")
    except Exception as e:
        print("[Vidyax] " + str(e))


def repl():
    print("Vidyax v1.0 REPL")
    print("  one-liners:  func sq(n): return n * n   then   sq(12)")
    print("  blocks:      type lines, end with a blank line.  Ctrl-D to exit")
    interp = Interpreter()
    pending = []
    while True:
        try:
            line = input("...  " if pending else "vidyax> ")
        except EOFError:
            print()
            break
        if pending:
            if line.strip() == "":
                _repl_exec(interp, "\n".join(pending))
                pending = []
            else:
                pending.append(line)
            continue
        if line.strip() == "":
            continue
        if line.rstrip().endswith(":"):
            pending = [line]   # start a block; finish it with a blank line
            continue
        _repl_exec(interp, line)


def main():
    args = sys.argv[1:]
    if not args:
        repl()
        return
    if args[0] in ("-h", "--help", "help"):
        print(
            "Vidyax v1.0\n"
            "  vidyax                     start the interactive REPL\n"
            "  vidyax <file.vx>           run a file (fast: compiles to Python)\n"
            "  vidyax run <file.vx>       run a file\n"
            "  vidyax build <file.vx>     compile to a standalone <file>.py\n"
            "  vidyax walk <file.vx>      run with the tree-walker (debug)\n"
            "  vidyax test                run built-in tests\n"
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
    elif cmd == "walk":
        if len(args) < 2:
            print("[Vidyax] usage: vidyax walk <file.vx>"); sys.exit(1)
        walk_file(args[1])
    elif cmd == "test":
        from tests import run_all_tests  # noqa
        run_all_tests()
    elif cmd in ("fmt", "install"):
        print(f"[Vidyax] command '{cmd}' is not supported yet (roadmap)")
    elif cmd.endswith((".vx", ".vax")) or os.path.exists(cmd):
        run_file(cmd)  # direct: vidyax main.vx
    else:
        print(f"[Vidyax] unknown command or file: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
