# Vidyax LLM Cheat Sheet

A compact (~1.2k token) summary of the language, written to be pasted into
an LLM's system prompt so the model can write correct Vidyax programs.
Tested 7 Jul 2026: with only this sheet in context, `qwen/qwen3-32b`
passed 9/12 execution-verified tasks and `qwen/qwen3.6-27b` 9/10
(temperature 0, graded by running the code with `vidyax run` and
exact-matching stdout). The full human reference is
[REFERENCE.md](./REFERENCE.md).

Suggested framing before the sheet:

> You write programs in Vidyax, a small programming language. Use ONLY
> features documented here — this is NOT Python: assignment is
> `name: value`, no `while` (use `rpt N` + `break`), no `=` assignment,
> no f-strings. Reply with ONLY one fenced code block.

---

## Syntax
- One statement per line; blocks by indentation (like Python); comments `#`.
- Assignment: `name: value`   (COLON, never `=`)
- Print: `print expr`   Input: `x: ask "prompt"` (returns text)
- Types: number (42, 3.14), text ("hi", double quotes), true/false, null, list [1,2,3]
- Operators: + - * / %  == != < <= > >=  and or not.  `+` joins text and lists.
  `/` always gives a decimal. Index `x[i]` from 0.
- NO while loop. NO f-strings. NO `=`. NO dictionaries. NO single-quote strings.

## Control flow
```vidyax
if cond:
    ...
elif cond2:
    ...
else:
    ...
```

```vidyax
rpt N:          # repeat N times (N must be a number)
    ...
for item in list_or_text:
    ...
```
`break` / `continue` work inside loops.

## Functions (recursion supported)
```vidyax
func name(a, b):
    return a + b
```
`return` with no value returns null.

## Errors
```vidyax
try:
    ...
catch e:        # e = error message text; `catch:` without variable also OK
    ...
```

## Builtins (RESERVED — never use these as variable/parameter/loop names!)
```
len(x) range(n) range(a,b)->[a..b-1] text(x) num(x) upper(s) lower(s)
split(s,sep)  # sep must not be "" — to walk characters use `for c in s`
join(lst,sep) push(lst,x) abs(x) sum(lst) min(...) max(...)
type(x) get(url) readfile(p) writefile(p,x) floor(x) ceil(x) round(x[,d])
sqrt(x) pow(x,y) random([a,b]) replace(s,old,new) trim(s) contains(x,item)
startswith(s,p) endswith(s,p) pop(lst[,i]) remove(lst,x) insert(lst,i,x)
sort(lst)  # in place, returns null!
reverse(lst)  # in place, returns null!
find(x,item)->index or -1  slice(x,a,b)  sleep(s) now() wait(t)
```

## Keywords (also reserved)
```
print if elif else rpt for in func return ask use and or not true false
null break continue try catch agent go
```

## Example
```vidyax
func fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)

total: 0
for x in [1, 2, 3]:
    total: total + x
print total        # 6
print fact(5)      # 120
i: 0
rpt 100:
    i: i + 1
    if i % 7 == 0:
        break
print i            # 7
```
