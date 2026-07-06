# -*- coding: utf-8 -*-
"""Vidyax Language Server (LSP) — `vidyax lsp`.

A dependency-free LSP server over stdio (JSON-RPC with Content-Length
framing). Works with any LSP client: VS Code, Neovim (vim.lsp), Helix,
Emacs (eglot), etc.

Capabilities (v1):
  - diagnostics  : live errors on open/change, via vidyax.check_source
                   (the same shared front-end as every engine)
  - completion   : keywords + all builtins (with docs) + names defined
                   in the document (variables, functions, params)
  - hover        : signature + description for builtins
  - documentSymbol: functions + top-level variables (editor outline)

Example client config (Neovim 0.11+):
    vim.lsp.config['vidyax'] = {
        cmd = { 'vidyax', 'lsp' },
        filetypes = { 'vidyax' },
    }
    vim.lsp.enable('vidyax')
"""
import json
import re
import sys

import vidyax

# --- builtin documentation (shown on hover + completion detail) ---
BUILTIN_DOCS = {
    "len":       ("len(x)", "length of a text or list"),
    "range":     ("range(n) / range(a, b[, step])", "list of numbers"),
    "text":      ("text(x)", "convert a value to text"),
    "num":       ("num(x)", "convert text/value to a number"),
    "upper":     ("upper(s)", "text to UPPERCASE"),
    "lower":     ("lower(s)", "text to lowercase"),
    "split":     ("split(s, sep=\" \")", "split text into a list"),
    "join":      ("join(lst, sep=\"\")", "join a list into text"),
    "push":      ("push(lst, x)", "append x to the end of a list"),
    "abs":       ("abs(x)", "absolute value"),
    "sum":       ("sum(lst)", "sum of a list of numbers"),
    "min":       ("min(...)", "smallest value (list or arguments)"),
    "max":       ("max(...)", "largest value (list or arguments)"),
    "type":      ("type(x)", "type name as text"),
    "get":       ("get(url)", "HTTP GET, returns the body as text"),
    "readfile":  ("readfile(path)", "read a text file"),
    "writefile": ("writefile(path, x)", "write x (as text) to a file"),
    "floor":     ("floor(x)", "round down to a whole number"),
    "ceil":      ("ceil(x)", "round up to a whole number"),
    "round":     ("round(x[, digits])", "round half away from zero"),
    "sqrt":      ("sqrt(x)", "square root (x must be >= 0)"),
    "pow":       ("pow(x, y)", "x raised to the power y"),
    "random":    ("random() / random(a, b)", "random number"),
    "replace":   ("replace(s, old, new)", "replace every old with new"),
    "trim":      ("trim(s)", "strip whitespace from both ends"),
    "contains":  ("contains(x, item)", "membership test for list/text"),
    "startswith":("startswith(s, p)", "true if s starts with p"),
    "endswith":  ("endswith(s, p)", "true if s ends with p"),
    "pop":       ("pop(lst[, i])", "remove & return an item (default last)"),
    "remove":    ("remove(lst, x)", "remove the first x from the list"),
    "insert":    ("insert(lst, i, x)", "insert x at position i"),
    "sort":      ("sort(lst)", "sort the list in place"),
    "reverse":   ("reverse(lst)", "reverse the list in place"),
    "find":      ("find(x, item)", "first index of item, -1 if absent"),
    "slice":     ("slice(x, a, b)", "copy of items a..b-1 of a list/text"),
}

KEYWORDS = sorted(vidyax.KEYWORDS)

# LSP CompletionItemKind / SymbolKind constants
CI_KEYWORD, CI_FUNCTION, CI_VARIABLE = 14, 3, 6
SYM_FUNCTION, SYM_VARIABLE = 12, 13

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEF_FUNC = re.compile(r"^\s*func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", re.M)
_DEF_VAR = re.compile(r"^([A-Za-z_]\w*)\s*:", re.M)


class Server:
    def __init__(self, inp, out):
        self.inp = inp
        self.out = out
        self.docs = {}          # uri -> text
        self.running = True

    # ---- JSON-RPC framing ----
    def read_message(self):
        length = None
        while True:
            line = self.inp.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
        if length is None:
            return None
        return json.loads(self.inp.read(length).decode("utf-8"))

    def send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.out.write(b"Content-Length: %d\r\n\r\n" % len(body))
        self.out.write(body)
        self.out.flush()

    def reply(self, msg_id, result):
        self.send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- features ----
    def diagnostics(self, uri):
        text = self.docs.get(uri, "")
        diags = []
        for e in vidyax.check_source(text):
            ln = max(0, e["line"] - 1)
            line_text = text.split("\n")[ln] if ln < len(text.split("\n")) else ""
            diags.append({
                "range": {"start": {"line": ln, "character": 0},
                          "end": {"line": ln, "character": max(1, len(line_text))}},
                "severity": 1,   # Error
                "source": "vidyax",
                "message": "%s error: %s" % (e.get("kind", "syntax"), e["message"]),
            })
        self.notify("textDocument/publishDiagnostics",
                    {"uri": uri, "diagnostics": diags})

    def completion(self, uri):
        items = []
        for kw in KEYWORDS:
            items.append({"label": kw, "kind": CI_KEYWORD})
        for name in sorted(vidyax.BUILTIN_NAMES):
            sig, desc = BUILTIN_DOCS.get(name, (name + "(...)", ""))
            items.append({"label": name, "kind": CI_FUNCTION,
                          "detail": sig, "documentation": desc})
        text = self.docs.get(uri, "")
        seen = set(vidyax.BUILTIN_NAMES) | set(KEYWORDS)
        for m in _DEF_FUNC.finditer(text):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                items.append({"label": m.group(1), "kind": CI_FUNCTION,
                              "detail": "func %s(%s)" % (m.group(1), m.group(2))})
            for p in m.group(2).split(","):
                p = p.strip()
                if p and p not in seen:
                    seen.add(p)
                    items.append({"label": p, "kind": CI_VARIABLE})
        for m in _DEF_VAR.finditer(text):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                items.append({"label": m.group(1), "kind": CI_VARIABLE})
        return items

    def word_at(self, uri, line, character):
        lines = self.docs.get(uri, "").split("\n")
        if line >= len(lines):
            return None
        for m in _WORD.finditer(lines[line]):
            if m.start() <= character <= m.end():
                return m.group(0)
        return None

    def hover(self, uri, pos):
        word = self.word_at(uri, pos["line"], pos["character"])
        if word in BUILTIN_DOCS:
            sig, desc = BUILTIN_DOCS[word]
            return {"contents": {"kind": "markdown",
                                 "value": "```vidyax\n%s\n```\n%s" % (sig, desc)}}
        if word in vidyax.KEYWORDS:
            return {"contents": {"kind": "markdown",
                                 "value": "`%s` — Vidyax keyword" % word}}
        return None

    def symbols(self, uri):
        text = self.docs.get(uri, "")
        out = []
        for m in _DEF_FUNC.finditer(text):
            ln = text.count("\n", 0, m.start())
            out.append({"name": m.group(1), "kind": SYM_FUNCTION,
                        "range": _line_range(ln),
                        "selectionRange": _line_range(ln)})
        for m in _DEF_VAR.finditer(text):
            ln = text.count("\n", 0, m.start())
            out.append({"name": m.group(1), "kind": SYM_VARIABLE,
                        "range": _line_range(ln),
                        "selectionRange": _line_range(ln)})
        return out

    # ---- dispatch ----
    def handle(self, msg):
        method = msg.get("method", "")
        params = msg.get("params", {})
        msg_id = msg.get("id")

        if method == "initialize":
            self.reply(msg_id, {
                "capabilities": {
                    "textDocumentSync": 1,   # full document sync
                    "completionProvider": {},
                    "hoverProvider": True,
                    "documentSymbolProvider": True,
                },
                "serverInfo": {"name": "vidyax-lsp",
                               "version": vidyax.VERSION},
            })
        elif method == "shutdown":
            self.reply(msg_id, None)
        elif method == "exit":
            self.running = False
        elif method == "textDocument/didOpen":
            uri = params["textDocument"]["uri"]
            self.docs[uri] = params["textDocument"]["text"]
            self.diagnostics(uri)
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            changes = params.get("contentChanges", [])
            if changes:
                self.docs[uri] = changes[-1]["text"]   # full sync
            self.diagnostics(uri)
        elif method == "textDocument/didClose":
            self.docs.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/completion":
            self.reply(msg_id, self.completion(params["textDocument"]["uri"]))
        elif method == "textDocument/hover":
            self.reply(msg_id, self.hover(params["textDocument"]["uri"],
                                          params["position"]))
        elif method == "textDocument/documentSymbol":
            self.reply(msg_id, self.symbols(params["textDocument"]["uri"]))
        elif msg_id is not None:
            # unknown REQUEST: answer (null) so the client never hangs;
            # unknown notifications are simply ignored
            self.reply(msg_id, None)

    def run(self):
        while self.running:
            msg = self.read_message()
            if msg is None:
                break
            try:
                self.handle(msg)
            except Exception as e:
                if msg.get("id") is not None:
                    self.send({"jsonrpc": "2.0", "id": msg["id"],
                               "error": {"code": -32603, "message": str(e)}})


def _line_range(ln):
    return {"start": {"line": ln, "character": 0},
            "end": {"line": ln, "character": 0}}


def main():
    Server(sys.stdin.buffer, sys.stdout.buffer).run()


if __name__ == "__main__":
    main()
