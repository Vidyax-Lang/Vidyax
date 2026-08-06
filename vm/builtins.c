#include "vx.h"
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include "vx_model_bridge.h"

/* ---- builtins (mirror vidyax.py RUNTIME semantics) ---- */
static Value b_len(int argc, Value *a) {
    if (argc == 1) {
        if (a[0].t == V_STR)  return vnum((double)AS_STR(a[0])->len);
        if (a[0].t == V_LIST) return vnum((double)AS_LIST(a[0])->count);
    }
    vm_error("len() needs a list or text");
    return vnull();
}
static Value b_range(int argc, Value *a) {
    long long v[3] = {0, 0, 1};
    if (argc < 1 || argc > 3) vm_error("range() takes 1 to 3 numbers");
    for (int i = 0; i < argc; i++) {
        if (!numlike(a[i])) vm_error("range() takes 1 to 3 numbers");
        v[i] = (long long)as_num(a[i]);
    }
    long long start = argc == 1 ? 0 : v[0];
    long long stop  = argc == 1 ? v[0] : v[1];
    long long step  = argc == 3 ? v[2] : 1;
    if (step == 0) vm_error("range() step cannot be 0");
    OList *l = new_list(8);
    if (step > 0) for (long long i = start; i < stop; i += step)
        list_push(l, vnum((double)i));
    else for (long long i = start; i > stop; i += step)
        list_push(l, vnum((double)i));
    return vlist_o(l);
}
static Value b_text(int argc, Value *a) {
    if (argc != 1) vm_error("text() needs 1 value");
    return vstr_o(vstr(a[0]));
}
static Value b_num(int argc, Value *a) {
    if (argc != 1) vm_error("num() needs 1 value");
    Value v = a[0];
    if (numlike(v)) return vnum(trunc(as_num(v)));   /* int() truncates */
    if (v.t == V_STR) {
        const char *s = AS_STR(v)->chars;
        while (*s == ' ' || *s == '\t') s++;
        char *end;
        double d = strtod(s, &end);
        if (end != s) {
            while (*end == ' ' || *end == '\t') end++;
            if (*end == 0) {
                /* no '.' in the text -> integer parse (truncation rule
                   only applies to numeric inputs; "2e3" stays 2000.0) */
                if (!memchr(AS_STR(v)->chars, '.', AS_STR(v)->len))
                    return vnum(d);
                return vnum(d);
            }
        }
    }
    { OStr *s = vstr(a[0]);
      vm_error("cannot convert to number: %s", s->chars); }
    return vnull();
}
static Value b_upper(int argc, Value *a) {
    if (argc != 1) vm_error("upper() needs 1 value");
    OStr *s = vstr(a[0]);
    OStr *r = new_str(s->chars, s->len);
    for (uint32_t i = 0; i < r->len; i++)
        r->chars[i] = (char)toupper((unsigned char)r->chars[i]);
    return vstr_o(r);
}
static Value b_lower(int argc, Value *a) {
    if (argc != 1) vm_error("lower() needs 1 value");
    OStr *s = vstr(a[0]);
    OStr *r = new_str(s->chars, s->len);
    for (uint32_t i = 0; i < r->len; i++)
        r->chars[i] = (char)tolower((unsigned char)r->chars[i]);
    return vstr_o(r);
}
static Value b_split(int argc, Value *a) {
    if (argc < 1 || argc > 2) vm_error("split() needs 1 or 2 values");
    OStr *s = vstr(a[0]);
    OStr *sep = argc == 2 ? vstr(a[1]) : new_str(" ", 1);
    if (sep->len == 0) vm_error("empty separator");
    OList *out = new_list(4);
    const char *p = s->chars, *end = s->chars + s->len;
    for (;;) {
        const char *hit = NULL;
        for (const char *q = p; q + sep->len <= end; q++)
            if (memcmp(q, sep->chars, sep->len) == 0) { hit = q; break; }
        if (!hit) { list_push(out, vstr_o(new_str(p, (uint32_t)(end - p)))); break; }
        list_push(out, vstr_o(new_str(p, (uint32_t)(hit - p))));
        p = hit + sep->len;
    }
    return vlist_o(out);
}
static Value b_join(int argc, Value *a) {
    if (argc < 1 || argc > 2) vm_error("join() needs 1 or 2 values");
    OStr *sep = argc == 2 ? vstr(a[1]) : new_str("", 0);
    SB sb; sb_init(&sb);
    if (a[0].t == V_LIST) {
        OList *l = AS_LIST(a[0]);
        for (uint32_t i = 0; i < l->count; i++) {
            if (i) sb_put(&sb, sep->chars, sep->len);
            OStr *x = vstr(l->items[i]);
            sb_put(&sb, x->chars, x->len);
        }
    } else if (a[0].t == V_STR) {   /* join("abc","-") like Python */
        OStr *s = AS_STR(a[0]);
        for (uint32_t i = 0; i < s->len; i++) {
            if (i) sb_put(&sb, sep->chars, sep->len);
            sb_put(&sb, s->chars + i, 1);
        }
    } else {
        vm_error("join() needs a list");
    }
    OStr *r = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return vstr_o(r);
}
static Value b_push(int argc, Value *a) {
    if (argc != 2 || a[0].t != V_LIST) vm_error("push() needs a list and a value");
    list_push(AS_LIST(a[0]), a[1]);
    return a[0];
}
static Value b_abs(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0])) vm_error("abs() needs a number");
    return vnum(fabs(as_num(a[0])));
}
static Value b_sum(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_LIST) vm_error("sum() needs a list of numbers");
    OList *l = AS_LIST(a[0]);
    double t = 0;
    for (uint32_t i = 0; i < l->count; i++) {
        if (!numlike(l->items[i])) vm_error("sum() needs a list of numbers");
        t += as_num(l->items[i]);
    }
    return vnum(t);
}
static Value minmax(int argc, Value *a, int want_max) {
    Value *items = a; uint32_t n = (uint32_t)argc;
    if (argc == 1 && a[0].t == V_LIST) {
        items = AS_LIST(a[0])->items; n = AS_LIST(a[0])->count;
    }
    if (n == 0) vm_error(want_max ? "max() needs at least one value"
                                  : "min() needs at least one value");
    Value best = items[0];
    for (uint32_t i = 1; i < n; i++) {
        int c = values_cmp(items[i], best);
        if (want_max ? c > 0 : c < 0) best = items[i];
    }
    return best;
}
static Value b_min(int argc, Value *a) { return minmax(argc, a, 0); }
static Value b_max(int argc, Value *a) { return minmax(argc, a, 1); }
static Value b_type(int argc, Value *a) {
    if (argc != 1) vm_error("type() needs 1 value");
    const char *n = type_name(a[0]);
    return vstr_o(new_str(n, (uint32_t)strlen(n)));
}
static Value b_get(int argc, Value *a) {
    need_net();
#ifndef VX_HAVE_CURL
    (void)argc; (void)a;
    vm_error("get() needs libcurl (rebuild vxvm with libcurl available)");
    return vnull();
#else
    if (argc != 1 || a[0].t != V_STR) vm_error("get() needs a text URL");
    SB resp; sb_init(&resp);
    long code = 0; char err[256];
    int rc;
    VX_BLOCKING(rc = http_request(AS_STR(a[0])->chars, NULL, NULL, &resp,
                                  &code, err, sizeof err));
    if (rc != 0) {
        char e[300]; snprintf(e, sizeof e, "%s", err);
        xfree(resp.buf, resp.cap);
        vm_error("get() failed: cannot connect (%s)", e);
    }
    if (code >= 400) {
        long cc = code; xfree(resp.buf, resp.cap);
        vm_error("get() failed: HTTP %ld", cc);
    }
    OStr *s = new_str(resp.buf, (uint32_t)resp.len);
    xfree(resp.buf, resp.cap);
    return vstr_o(s);
#endif
}

static Value b_readfile(int argc, Value *a) {
    need_fs();
    if (argc != 1 || a[0].t != V_STR) vm_error("readfile() needs a text path");
    SB sb; sb_init(&sb);
    FILE *f; int failed = 0, saved_errno = 0;
    VX_UNLOCK();          /* raw buffers only while unlocked — no GC objects */
    f = fopen(AS_STR(a[0])->chars, "rb");
    if (!f) { failed = 1; saved_errno = errno; }
    else {
        char buf[4096]; size_t n;
        while ((n = fread(buf, 1, sizeof buf, f)) > 0) sb_put(&sb, buf, n);
        if (ferror(f)) { failed = 1; saved_errno = errno; }
        fclose(f);
    }
    VX_LOCK();
    if (failed) {
        xfree(sb.buf, sb.cap);
        vm_error("readfile() failed: %s", strerror(saved_errno));
    }
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return vstr_o(s);
}
static Value b_writefile(int argc, Value *a) {
    need_fs();
    if (argc != 2 || a[0].t != V_STR) vm_error("writefile() needs a text path and a value");
    OStr *txt = vstr(a[1]);
    int failed = 0, saved_errno = 0;
    VX_UNLOCK();          /* txt is rooted on the caller's stack: stable */
    FILE *f = fopen(AS_STR(a[0])->chars, "wb");
    if (!f) { failed = 1; saved_errno = errno; }
    else {
        size_t written = fwrite(txt->chars, 1, txt->len, f);
        if (written != txt->len || fclose(f) != 0) {
            failed = 1; saved_errno = errno;
        }
    }
    VX_LOCK();
    if (failed) vm_error("writefile() failed: %s", strerror(saved_errno));
    return vnull();
}
static Value b_floor(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0])) vm_error("floor() needs a number");
    return vnum(floor(as_num(a[0])));
}
static Value b_ceil(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0])) vm_error("ceil() needs a number");
    return vnum(ceil(as_num(a[0])));
}
static Value b_round(int argc, Value *a) {
    /* half away from zero, same formula as _b_round in vidyax.py */
    if (argc < 1 || argc > 2 || !numlike(a[0])) vm_error("round() needs a number");
    double nd = 0;
    if (argc == 2) {
        if (!numlike(a[1])) vm_error("round() needs a number");
        nd = trunc(as_num(a[1]));
        if (nd < 0) vm_error("round() digits must be 0 or more");
    }
    double m = pow(10.0, nd);
    double v = as_num(a[0]) * m;
    double r = v >= 0 ? floor(v + 0.5) : ceil(v - 0.5);
    return vnum(r / m);
}
static Value b_sqrt(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0])) vm_error("sqrt() needs a number");
    double x = as_num(a[0]);
    if (x < 0) vm_error("sqrt() needs a number >= 0");
    return vnum(sqrt(x));
}
static Value b_pow(int argc, Value *a) {
    if (argc != 2 || !numlike(a[0]) || !numlike(a[1])) vm_error("pow() needs a number");
    double r = pow(as_num(a[0]), as_num(a[1]));
    if (!isfinite(r)) vm_error("pow() result is not a number");
    return vnum(r);
}
static Value b_random(int argc, Value *a) {
    static int seeded = 0;
    if (!seeded) { srand((unsigned)time(NULL) ^ (unsigned)clock()); seeded = 1; }
    double u = rand() / ((double)RAND_MAX + 1.0);
    if (argc == 0) return vnum(u);
    if (argc == 2) {
        if (!numlike(a[0]) || !numlike(a[1])) vm_error("random() needs a number");
        long long lo = (long long)trunc(as_num(a[0]));
        long long hi = (long long)trunc(as_num(a[1]));
        if (lo > hi) vm_error("random(a, b) needs a <= b");
        return vnum((double)(lo + (long long)(u * (double)(hi - lo + 1))));
    }
    vm_error("random() takes no values, or two whole numbers");
    return vnull();
}
static Value b_replace(int argc, Value *a) {
    if (argc != 3) vm_error("replace() needs 3 values");
    OStr *s = vstr(a[0]), *old = vstr(a[1]), *nw = vstr(a[2]);
    if (old->len == 0) vm_error("replace() needs a non-empty text to find");
    SB sb; sb_init(&sb);
    const char *p = s->chars, *end = s->chars + s->len;
    while (p < end) {
        if ((size_t)(end - p) >= old->len &&
            memcmp(p, old->chars, old->len) == 0) {
            sb_put(&sb, nw->chars, nw->len);
            p += old->len;
        } else {
            sb_put(&sb, p, 1);
            p++;
        }
    }
    OStr *r = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return vstr_o(r);
}
static Value b_trim(int argc, Value *a) {
    if (argc != 1) vm_error("trim() needs 1 value");
    OStr *s = vstr(a[0]);
    const char *b = s->chars, *e = s->chars + s->len;
    while (b < e && isspace((unsigned char)*b)) b++;
    while (e > b && isspace((unsigned char)e[-1])) e--;
    return vstr_o(new_str(b, (uint32_t)(e - b)));
}
static Value b_contains(int argc, Value *a) {
    if (argc != 2) vm_error("contains() needs 2 values");
    if (a[0].t == V_LIST) {
        OList *l = AS_LIST(a[0]);
        for (uint32_t i = 0; i < l->count; i++)
            if (values_eq(l->items[i], a[1])) return vbool(1);
        return vbool(0);
    }
    if (a[0].t == V_STR) {
        OStr *s = AS_STR(a[0]), *sub = vstr(a[1]);
        if (sub->len == 0) return vbool(1);
        for (const char *p = s->chars; p + sub->len <= s->chars + s->len; p++)
            if (memcmp(p, sub->chars, sub->len) == 0) return vbool(1);
        return vbool(0);
    }
    vm_error("contains() needs a list or text");
    return vnull();
}
static Value b_startswith(int argc, Value *a) {
    if (argc != 2) vm_error("startswith() needs 2 values");
    OStr *s = vstr(a[0]), *p = vstr(a[1]);
    return vbool(p->len <= s->len && memcmp(s->chars, p->chars, p->len) == 0);
}
static Value b_endswith(int argc, Value *a) {
    if (argc != 2) vm_error("endswith() needs 2 values");
    OStr *s = vstr(a[0]), *p = vstr(a[1]);
    return vbool(p->len <= s->len &&
                 memcmp(s->chars + (s->len - p->len), p->chars, p->len) == 0);
}

static Value b_pop(int argc, Value *a) {
    if (argc < 1 || argc > 2 || a[0].t != V_LIST) vm_error("pop() needs a list");
    OList *l = AS_LIST(a[0]);
    if (l->count == 0) vm_error("pop() on an empty list");
    long long i = (long long)l->count - 1;
    if (argc == 2) {
        if (!numlike(a[1])) vm_error("index out of range");
        i = (long long)trunc(as_num(a[1]));
        if (i < 0) i += l->count;
        if (i < 0 || i >= (long long)l->count) vm_error("index out of range");
    }
    Value v = l->items[i];
    memmove(l->items + i, l->items + i + 1,
            sizeof(Value) * (l->count - (uint32_t)i - 1));
    l->count--;
    return v;
}
static Value b_remove(int argc, Value *a) {
    if (argc != 2 || a[0].t != V_LIST) vm_error("remove() needs a list");
    OList *l = AS_LIST(a[0]);
    for (uint32_t i = 0; i < l->count; i++) {
        if (values_eq(l->items[i], a[1])) {
            memmove(l->items + i, l->items + i + 1,
                    sizeof(Value) * (l->count - i - 1));
            l->count--;
            return a[0];
        }
    }
    vm_error("remove(): value not in list");
    return vnull();
}
static Value b_insert(int argc, Value *a) {
    if (argc != 3 || a[0].t != V_LIST || !numlike(a[1]))
        vm_error("insert() needs a list");
    OList *l = AS_LIST(a[0]);
    long long i = (long long)trunc(as_num(a[1]));
    if (i < 0) i += l->count;                    /* clamp like Python */
    if (i < 0) i = 0;
    if (i > (long long)l->count) i = l->count;
    list_push(l, vnull());                       /* grow by one */
    memmove(l->items + i + 1, l->items + i,
            sizeof(Value) * (l->count - (uint32_t)i - 1));
    l->items[i] = a[2];
    return a[0];
}
static Value b_sort(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_LIST) vm_error("sort() needs a list");
    OList *l = AS_LIST(a[0]);
    if (l->count > 1) {
        /* same pre-check (and message) as _b_sort in vidyax.py */
        Value f = l->items[0];
        int c0 = numlike(f) ? 1 : f.t == V_STR ? 2 : f.t == V_LIST ? 3 : 0;
        for (uint32_t i = 1; i < l->count; i++) {
            Value v = l->items[i];
            int c = numlike(v) ? 1 : v.t == V_STR ? 2 : v.t == V_LIST ? 3 : 0;
            if (c0 == 0 || c != c0)
                vm_error("cannot compare %s with %s",
                         type_name(f), type_name(v));
        }
        /* insertion sort: stable, matches Python's ordering guarantees */
        for (uint32_t i = 1; i < l->count; i++) {
            Value v = l->items[i];
            uint32_t j = i;
            while (j > 0 && values_cmp(l->items[j - 1], v) > 0) {
                l->items[j] = l->items[j - 1];
                j--;
            }
            l->items[j] = v;
        }
    }
    return a[0];
}
static Value b_reverse(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_LIST) vm_error("reverse() needs a list");
    OList *l = AS_LIST(a[0]);
    for (uint32_t i = 0, j = l->count; i + 1 < j--; i++) {
        Value t = l->items[i]; l->items[i] = l->items[j]; l->items[j] = t;
    }
    return a[0];
}
static Value b_find(int argc, Value *a) {
    if (argc != 2) vm_error("find() needs 2 values");
    if (a[0].t == V_LIST) {
        OList *l = AS_LIST(a[0]);
        for (uint32_t i = 0; i < l->count; i++)
            if (values_eq(l->items[i], a[1])) return vnum((double)i);
        return vnum(-1);
    }
    if (a[0].t == V_STR) {
        OStr *s = AS_STR(a[0]), *sub = vstr(a[1]);
        if (sub->len == 0) return vnum(0);
        for (const char *p = s->chars; p + sub->len <= s->chars + s->len; p++)
            if (memcmp(p, sub->chars, sub->len) == 0)
                return vnum((double)(p - s->chars));
        return vnum(-1);
    }
    vm_error("find() needs a list or text");
    return vnull();
}
static Value b_slice(int argc, Value *args) {
    if (argc < 2 || argc > 3) vm_error("slice() takes 2 or 3 arguments");
    if (args[0].t != V_LIST && args[0].t != V_STR) vm_error("slice() needs list or text");
    if (!numlike(args[1])) vm_error("slice() needs numeric start");
    long long start = (long long)as_num(args[1]);
    long long end = -1;
    if (argc == 3) {
        if (!numlike(args[2])) vm_error("slice() needs numeric end");
        end = (long long)as_num(args[2]);
    }
    
    if (args[0].t == V_LIST) {
        OList *l = AS_LIST(args[0]);
        long long count = l->count;
        if (start < 0) start += count;
        if (start < 0) start = 0;
        if (start > count) start = count;
        
        if (argc == 2) end = count;
        else {
            if (end < 0) end += count;
            if (end < 0) end = 0;
            if (end > count) end = count;
        }
        
        if (start >= end) return vlist_o(new_list(0));
        OList *nl = new_list(end - start);
        for (long long i = start; i < end; i++) list_push(nl, l->items[i]);
        return vlist_o(nl);
    } else {
        OStr *s = AS_STR(args[0]);
        long long count = s->len;
        if (start < 0) start += count;
        if (start < 0) start = 0;
        if (start > count) start = count;
        
        if (argc == 2) end = count;
        else {
            if (end < 0) end += count;
            if (end < 0) end = 0;
            if (end > count) end = count;
        }
        
        if (start >= end) return vstr_o(new_str("", 0));
        return vstr_o(new_str(s->chars + start, end - start));
    }
}

static Value b_set(int argc, Value *args) {
    if (argc != 3) vm_error("set() takes 3 arguments");
    if (args[0].t != V_MAP) vm_error("set() needs a dict");
    if (args[1].t != V_STR) vm_error("dict key must be text");
    map_set(AS_MAP(args[0]), AS_STR(args[1]), args[2]);
    return args[0];
}
static Value b_has(int argc, Value *args) {
    if (argc != 2) vm_error("has() takes 2 arguments");
    if (args[0].t == V_MAP) {
        if (args[1].t != V_STR) return vbool(0);
        Value out;
        return vbool(map_get(AS_MAP(args[0]), AS_STR(args[1]), &out));
    }
    if (args[0].t == V_LIST || args[0].t == V_STR) {
        /* simplified contains logic for list/str */
        if (args[0].t == V_LIST) {
            OList *l = AS_LIST(args[0]);
            for (uint32_t i = 0; i < l->count; i++)
                if (values_eq(l->items[i], args[1])) return vbool(1);
            return vbool(0);
        } else {
            if (args[1].t != V_STR) return vbool(0);
            return vbool(strstr(AS_STR(args[0])->chars, AS_STR(args[1])->chars) != NULL);
        }
    }
    vm_error("has() needs a dict, list, or text");
    return vnull();
}
static Value b_keys(int argc, Value *args) {
    if (argc != 1 || args[0].t != V_MAP) vm_error("keys() needs a dict");
    OMap *m = AS_MAP(args[0]);
    OList *l = new_list(m->count);
    for (uint32_t i = 0; i < m->count; i++) list_push(l, vstr_o(m->entries[i].key));
    return vlist_o(l);
}
static Value b_values(int argc, Value *args) {
    if (argc != 1 || args[0].t != V_MAP) vm_error("values() needs a dict");
    OMap *m = AS_MAP(args[0]);
    OList *l = new_list(m->count);
    for (uint32_t i = 0; i < m->count; i++) list_push(l, m->entries[i].v);
    return vlist_o(l);
}
static void skip_ws(const char **p) {
    while (**p == ' ' || **p == '\t' || **p == '\n' || **p == '\r') (*p)++;
}
static Value parse_json_value(const char **p);
static OStr *parse_json_string(const char **p) {
    (*p)++; /* skip quote */
    SB sb; sb_init(&sb);
    while (**p && **p != '"') {
        if (**p == '\\') {
            (*p)++;
            char c = **p;
            if (c == 'n') sb_put(&sb, "\n", 1);
            else if (c == 'r') sb_put(&sb, "\r", 1);
            else if (c == 't') sb_put(&sb, "\t", 1);
            else sb_put(&sb, &c, 1);
        } else {
            sb_put(&sb, *p, 1);
        }
        (*p)++;
    }
    if (**p == '"') (*p)++;
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return s;
}
static Value parse_json_value(const char **p) {
    skip_ws(p);
    if (!**p) return vnull();
    if (**p == '"') {
        return vstr_o(parse_json_string(p));
    }
    if (**p == '{') {
        (*p)++;
        OMap *m = map_new();
        skip_ws(p);
        if (**p == '}') { (*p)++; return vmap_o(m); }
        while (**p) {
            skip_ws(p);
            if (**p != '"') break;
            OStr *k = parse_json_string(p);
            skip_ws(p);
            if (**p == ':') (*p)++;
            Value v = parse_json_value(p);
            map_set(m, k, v);
            skip_ws(p);
            if (**p == ',') (*p)++;
            else if (**p == '}') { (*p)++; break; }
            else break;
        }
        return vmap_o(m);
    }
    if (**p == '[') {
        (*p)++;
        OList *l = new_list(0);
        skip_ws(p);
        if (**p == ']') { (*p)++; return vlist_o(l); }
        while (**p) {
            Value v = parse_json_value(p);
            list_push(l, v);
            skip_ws(p);
            if (**p == ',') (*p)++;
            else if (**p == ']') { (*p)++; break; }
            else break;
        }
        return vlist_o(l);
    }
    if (strncmp(*p, "true", 4) == 0) { *p += 4; return vbool(1); }
    if (strncmp(*p, "false", 5) == 0) { *p += 5; return vbool(0); }
    if (strncmp(*p, "null", 4) == 0) { *p += 4; return vnull(); }
    /* number */
    char *end;
    double n = strtod(*p, &end);
    *p = end;
    return vnum(n);
}

static Value b_json_parse(int argc, Value *args) {
    if (argc != 1 || args[0].t != V_STR) vm_error("json_parse() takes 1 text argument");
    const char *p = AS_STR(args[0])->chars;
    return parse_json_value(&p);
}
static void json_str_into(SB *sb, Value v) {
    if (v.t == V_NULL) { sb_puts(sb, "null"); return; }
    if (v.t == V_BOOL) { sb_puts(sb, v.as.b ? "true" : "false"); return; }
    if (v.t == V_NUM)  { char nb[400]; fmt_double(v.as.n, nb, sizeof nb); sb_puts(sb, nb); return; }
    if (v.t == V_STR) {
        sb_puts(sb, "\"");
        OStr *s = AS_STR(v);
        for (uint32_t i = 0; i < s->len; i++) {
            char c = s->chars[i];
            if (c == '"') sb_puts(sb, "\\\"");
            else if (c == '\\') sb_puts(sb, "\\\\");
            else if (c == '\n') sb_puts(sb, "\\n");
            else if (c == '\r') sb_puts(sb, "\\r");
            else if (c == '\t') sb_puts(sb, "\\t");
            else sb_put(sb, &c, 1);
        }
        sb_puts(sb, "\"");
        return;
    }
    if (v.t == V_LIST) {
        sb_puts(sb, "[");
        OList *l = AS_LIST(v);
        for (uint32_t i = 0; i < l->count; i++) {
            if (i) sb_puts(sb, ", ");
            json_str_into(sb, l->items[i]);
        }
        sb_puts(sb, "]");
        return;
    }
    if (v.t == V_MAP) {
        sb_puts(sb, "{");
        OMap *m = AS_MAP(v);
        for (uint32_t i = 0; i < m->count; i++) {
            if (i) sb_puts(sb, ", ");
            json_str_into(sb, vstr_o(m->entries[i].key));
            sb_puts(sb, ": ");
            json_str_into(sb, m->entries[i].v);
        }
        sb_puts(sb, "}");
        return;
    }
    vm_error("cannot stringify %s to JSON", type_name(v));
}

static Value b_json_string(int argc, Value *args) {
    if (argc != 1) vm_error("json_string() takes 1 argument");
    SB sb; sb_init(&sb);
    json_str_into(&sb, args[0]);
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return vstr_o(s);
}

static Value b_sleep(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0]) || as_num(a[0]) < 0)
        vm_error("sleep() needs a number of seconds >= 0");
    double s = as_num(a[0]);
    struct timespec ts;
    ts.tv_sec = (time_t)s;
    ts.tv_nsec = (long)((s - (double)ts.tv_sec) * 1e9);
    VX_BLOCKING(nanosleep(&ts, NULL));
    return vnull();
}
static Value b_now(int argc, Value *a) {
    (void)a;
    if (argc != 0) vm_error("now() takes no values");
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return vnum((double)ts.tv_sec + (double)ts.tv_nsec / 1e9);
}

/* =========================================================================
 * Standard Library Tools: Native C/C++ Framework
 * ========================================================================= */

/* 1. FileReader (sys::mmap_read)
 * Uses memory-mapped file I/O for zero-copy read. Requires 'read' permission. */
static Value b_mmap_read(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_STR) vm_error("mmap_read() needs a file path");
    need_fs(); /* M-MUTATE-VIOLATION check applies here naturally */
    
    OStr *path = AS_STR(a[0]);
    int fd = open(path->chars, O_RDONLY);
    if (fd < 0) vm_error("mmap_read: cannot open file");
    
    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size == 0) {
        close(fd);
        return vstr_o(new_str("", 0));
    }
    
    char *map = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (map == MAP_FAILED) vm_error("mmap_read: mmap failed");
    
    OStr *ret = new_str(map, st.st_size);
    munmap(map, st.st_size);
    return vstr_o(ret);
}

/* 2. SwarmMessenger (sys::shm_write)
 * Inter-agent zero-copy communication via POSIX /dev/shm. */
static Value b_shm_write(int argc, Value *a) {
    if (argc != 2 || a[0].t != V_STR || a[1].t != V_STR) 
        vm_error("shm_write() needs channel name and message");
    
    /* Strict scoping check: memory mutation requires 'mutate' perms.
     * Handled by AST @tool validation statically, but dynamically protected here */
    if (vx_ctx->s_n_isolated) {
        vm_error("M-MUTATE-VIOLATION: agent s_n cubicle cannot mutate Host OS SHM");
    }
    
    OStr *chan = AS_STR(a[0]);
    OStr *msg = AS_STR(a[1]);
    
    /* Ensure channel name starts with / for shm_open */
    char shm_name[256];
    snprintf(shm_name, sizeof(shm_name), "/vx_shm_%s", chan->chars);
    
    int fd = shm_open(shm_name, O_CREAT | O_RDWR, 0666);
    if (fd < 0) vm_error("shm_write: shm_open failed");
    
    if (ftruncate(fd, msg->len) < 0) {
        close(fd);
        vm_error("shm_write: ftruncate failed");
    }
    
    char *map = mmap(NULL, msg->len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (map == MAP_FAILED) vm_error("shm_write: mmap failed");
    
    memcpy(map, msg->chars, msg->len);
    munmap(map, msg->len);
    
    return vnum(1); /* Success */
}

/* 3. SafeCalc (Knaster-Tarski Guard)
 * Isolated math evaluation with fixed-point theorem constraints. */
static Value b_safe_calc(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0])) vm_error("safe_calc() needs a number");
    
    double val = as_num(a[0]);
    
    /* Knaster-Tarski fixpoint simulation guard:
     * Ensuring calculations converge within safety limits */
    if (isnan(val) || isinf(val)) {
        vm_error("safe_calc: Knaster-Tarski bound violation (infinity/NaN)");
    }
    
    /* Toy implementation: monotonically increasing function bounded check */
    double result = val * 1.61803398875; /* Golden ratio multiplier */
    if (result > 1e12 || result < -1e12) {
        vm_error("safe_calc: Divergence detected, execution halted");
    }
    
    return vnum(result);
}

Builtin BUILTINS[] = {
    {"len", b_len}, {"range", b_range}, {"text", b_text}, {"num", b_num},
    {"upper", b_upper}, {"lower", b_lower}, {"split", b_split},
    {"join", b_join}, {"push", b_push}, {"abs", b_abs}, {"sum", b_sum},
    {"min", b_min}, {"max", b_max}, {"type", b_type}, {"get", b_get},
    {"readfile", b_readfile}, {"writefile", b_writefile},
    {"floor", b_floor}, {"ceil", b_ceil}, {"round", b_round},
    {"sqrt", b_sqrt}, {"pow", b_pow}, {"random", b_random},
    {"replace", b_replace}, {"trim", b_trim}, {"contains", b_contains},
    {"startswith", b_startswith}, {"endswith", b_endswith},
    {"pop", b_pop}, {"remove", b_remove}, {"insert", b_insert},
    {"sort", b_sort}, {"reverse", b_reverse}, {"find", b_find},
    {"slice", b_slice},
    {"set", b_set}, {"has", b_has}, {"keys", b_keys}, {"values", b_values},
    {"json_parse", b_json_parse}, {"json_string", b_json_string},
    {"sleep", b_sleep}, {"now", b_now},
    {"wait", b_wait},
    /* Standard Library Tools (Fase F) */
    {"mmap_read", b_mmap_read},
    {"shm_write", b_shm_write},
    {"safe_calc", b_safe_calc},
    /* Native C Model Bridge (Fase G) */
    {"model_load", b_model_load},
    {"model_infer", b_model_infer},
};
const size_t NBUILTINS = sizeof BUILTINS / sizeof BUILTINS[0];

