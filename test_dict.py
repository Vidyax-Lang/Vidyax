#!/usr/bin/env python3
# --- Vidyax runtime (auto-generated) ---
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
    if isinstance(v, dict): return "{" + ", ".join(_vstr(k) + ": " + _vstr(val) for k, val in v.items()) + "}"
    if type(v).__name__ == "_VTask": return "<task %s>" % v.name
    if type(v).__name__ == "_Agent": return "<agent %s>" % v._name
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
    if isinstance(o, dict):
        if i not in o: raise _VidyaxRuntime(f"key '{_vstr(i)}' not found in dict")
        return o[i]
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
    def _ask_messages(self, messages):
        # POST a full message list and return the reply text. Shared by
        # ai.ask (stateless) and _Agent (stateful, sends its history).
        _perm_net()
        url, keyname = _AI_PROVIDERS[self.provider]
        key = _os.environ.get(keyname)
        if not key:
            raise _VidyaxRuntime(
                keyname + " is not set. Run: export " + keyname + "=...  "
                "(ai.ask needs internet & an API key)")
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

    def ask(self, prompt):
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": str(prompt)})
        return self._ask_messages(messages)


class _Agent:
    # A named, stateful AI persona (docs/CONCURRENCY.md Phase E). Config
    # is fixed at declaration; each call appends to a running conversation
    # history, so the agent "remembers". One agent = one conversation —
    # for independent parallel work, make several agents.
    def __init__(self, name, model=None, system=None):
        self._name = name
        self._ai = _AI()
        if model is not None:
            self._ai.open(_vstr(model))
        if system is not None:
            self._ai.system(_vstr(system))
        self._history = []
        # Fase F: Scoping Cubicle (s_n) isolation
        # Ensures agent state is strictly scoped and cannot mutate Host OS (s_0)
        self.scope = "s_n"

    def __call__(self, *args):
        if len(args) != 1:
            raise _VidyaxRuntime(
                "agent '%s' needs 1 message, got %d" % (self._name, len(args)))
        
        # Fase F: Enforce s_n Scoping Cubicle
        global _S_N_CUBICLE
        old_s_n = _S_N_CUBICLE
        _S_N_CUBICLE = True
        old_perms = _sandbox_enter(["fs"])
        try:
            self._history.append({"role": "user", "content": _vstr(args[0])})
            messages = []
            if self._ai.system_prompt:
                messages.append({"role": "system",
                                 "content": self._ai.system_prompt})
            messages.extend(self._history)
            reply = self._ai._ask_messages(messages)
            self._history.append({"role": "assistant", "content": reply})
            return reply
        finally:
            _sandbox_exit(old_perms)
            _S_N_CUBICLE = old_s_n

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

def _b_set(obj, k, v):
    if isinstance(obj, dict):
        obj[k] = v
        return obj
    raise _VidyaxRuntime("set() needs a dict")
def _b_has(obj, k):
    if isinstance(obj, dict): return k in obj
    if isinstance(obj, (list, str)): return k in obj
    raise _VidyaxRuntime("has() needs a dict, list, or text")
def _b_keys(obj):
    if not isinstance(obj, dict): raise _VidyaxRuntime("keys() needs a dict")
    return list(obj.keys())
def _b_values(obj):
    if not isinstance(obj, dict): raise _VidyaxRuntime("values() needs a dict")
    return list(obj.values())
def _b_json_parse(s):
    try: return _json.loads(_vstr(s))
    except Exception as e: raise _VidyaxRuntime("json_parse error: " + str(e))
def _b_json_string(obj):
    try: return _json.dumps(obj)
    except Exception as e: raise _VidyaxRuntime("json_string error: " + str(e))

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
    if isinstance(x, dict): return "dict"
    if x is None: return "null"
    if type(x).__name__ == "_VTask": return "task"
    if type(x).__name__ == "_Agent": return "agent"
    return "object"

def _b_get(url):
    # Simple HTTP GET. Raises a Vidyax error on failure so the user can
    # handle it with try/catch, like every other error in the language.
    if not isinstance(url, str):
        raise _VidyaxRuntime("get() needs a text URL")
    _perm_net()
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
    _perm_fs()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise _VidyaxRuntime("readfile() failed: %s" % (e.strerror or e))

def _b_writefile(path, txt):
    if not isinstance(path, str):
        raise _VidyaxRuntime("writefile() needs a text path and a value")
    _perm_fs()
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

# --- Standard Library Tools (Fase F Stub for Python walk engine) ---
def _b_mmap_read(path):
    _perm_fs()
    with open(path, "r") as f:
        return f.read()

def _b_shm_write(chan, msg):
    if _S_N_CUBICLE:
        raise _VidyaxRuntime("M-MUTATE-VIOLATION: agent s_n cubicle cannot mutate Host OS SHM")
    # Stub: writing to shm not fully emulated in Python walk engine
    return 1

def _b_safe_calc(val):
    if not isinstance(val, (int, float)):
        raise _VidyaxRuntime("safe_calc() needs a number")
    if _math.isinf(val) or _math.isnan(val):
        raise _VidyaxRuntime("safe_calc: Knaster-Tarski bound violation (infinity/NaN)")
    res = val * 1.61803398875
    if res > 1e12 or res < -1e12:
        raise _VidyaxRuntime("safe_calc: Divergence detected, execution halted")
    return res

# --- Native C Model Bridge (Fase G Stub for Python walk engine) ---
def _b_model_load(path):
    _perm_fs()
    # Stub: return a dummy handle
    return 1337

def _b_model_infer(handle, prompt):
    if _S_N_CUBICLE:
        pass # isolation check
    return "[LLM Python Stub Inference] Response for: '" + str(prompt) + "'"

# --- sandbox permissions (per-thread; capability model) --------------
# The Python engines start with everything allowed (like today); the C
# engines start from the --allow-* flags. A `sandbox deny ...:` block can
# only REDUCE the set; tasks inherit the spawner's set at `go` time.
_PERMS = _thr.local()
_S_N_CUBICLE = False

def _cur_perms():
    p = getattr(_PERMS, "v", None)
    if p is None:
        p = {"net": True, "fs": True}
        _PERMS.v = p
    return p

def _sandbox_enter(denies):
    old = dict(_cur_perms())
    new = dict(old)
    for d in denies:
        new[d] = False
    _PERMS.v = new
    return old

def _sandbox_exit(old):
    _PERMS.v = old

def _perm_net():
    if not _cur_perms()["net"]:
        raise _VidyaxRuntime("network access is not allowed here "
                             "(blocked by 'sandbox deny net')")

def _perm_fs():
    if not _cur_perms()["fs"]:
        global _S_N_CUBICLE
        if _S_N_CUBICLE:
            raise _VidyaxRuntime("M-MUTATE-VIOLATION: agent s_n cubicle cannot mutate Host OS (s_0)")
        raise _VidyaxRuntime("file access is not allowed here "
                             "(blocked by 'sandbox deny fs')")

# --- tasks (`go` / wait) — docs/CONCURRENCY.md; Python's GIL IS the
# execution model: one interpreter lock, released inside blocking I/O ---
_ALL_TASKS = []

class _VTask:
    def __init__(self, name, thunk):
        self.name = name
        self.result = None
        self.err = None
        self.waited = False
        self._perms = dict(_cur_perms())   # capabilities travel with it
        _ALL_TASKS.append(self)
        self._t = _thr.Thread(target=self._run, args=(thunk,))
        self._t.start()

    def _run(self, thunk):
        _PERMS.v = self._perms
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

def _main():
    d = {"a": 1, "b": 2}
    print(_vstr(_index(d, "a")))
    _b_set(d, "c", 3)
    print(_vstr(_b_json_string(d)))
    p = _b_json_parse("{\"test\": 123}")
    print(_vstr(_index(p, "test")))

if __name__ == '__main__':
    import sys as _sys
    try:
        _main()
    except _VidyaxRuntime as _e:
        print('[Vidyax] ' + str(_e)); _sys.exit(1)
    except Exception as _e:
        print('[Vidyax] ' + _errtext(_e)); _sys.exit(1)
