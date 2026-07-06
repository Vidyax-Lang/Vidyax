#include "vx.h"

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
    if (!allow_net)
        vm_error("network access is not allowed "
                 "(pass --allow-net to enable ai.ask / get)");
#ifndef VX_HAVE_CURL
    (void)argc; (void)a;
    vm_error("get() needs libcurl (rebuild vxvm with libcurl available)");
    return vnull();
#else
    if (argc != 1 || a[0].t != V_STR) vm_error("get() needs a text URL");
    SB resp; sb_init(&resp);
    long code = 0; char err[256];
    int rc = http_request(AS_STR(a[0])->chars, NULL, NULL, &resp, &code,
                          err, sizeof err);
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
    if (!allow_fs)
        vm_error("file access is not allowed "
                 "(pass --allow-fs to enable readfile / writefile)");
    if (argc != 1 || a[0].t != V_STR) vm_error("readfile() needs a text path");
    FILE *f = fopen(AS_STR(a[0])->chars, "rb");
    if (!f) vm_error("readfile() failed: %s", strerror(errno));
    SB sb; sb_init(&sb);
    char buf[4096]; size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) sb_put(&sb, buf, n);
    if (ferror(f)) {
        fclose(f); xfree(sb.buf, sb.cap);
        vm_error("readfile() failed: %s", strerror(errno));
    }
    fclose(f);
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return vstr_o(s);
}
static Value b_writefile(int argc, Value *a) {
    if (!allow_fs)
        vm_error("file access is not allowed "
                 "(pass --allow-fs to enable readfile / writefile)");
    if (argc != 2 || a[0].t != V_STR) vm_error("writefile() needs a text path and a value");
    OStr *txt = vstr(a[1]);
    FILE *f = fopen(AS_STR(a[0])->chars, "wb");
    if (!f) vm_error("writefile() failed: %s", strerror(errno));
    size_t written = fwrite(txt->chars, 1, txt->len, f);
    if (written != txt->len || fclose(f) != 0)
        vm_error("writefile() failed: %s", strerror(errno));
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
static Value b_slice(int argc, Value *a) {
    if (argc != 3 || !numlike(a[1]) || !numlike(a[2]))
        vm_error("slice() needs a list or text");
    long long n, lo = (long long)trunc(as_num(a[1])),
                 hi = (long long)trunc(as_num(a[2]));
    if (a[0].t == V_LIST)      n = AS_LIST(a[0])->count;
    else if (a[0].t == V_STR)  n = AS_STR(a[0])->len;
    else { vm_error("slice() needs a list or text"); return vnull(); }
    if (lo < 0) lo += n;                          /* Python x[a:b] rules */
    if (lo < 0) lo = 0;
    if (lo > n) lo = n;
    if (hi < 0) hi += n;
    if (hi < 0) hi = 0;
    if (hi > n) hi = n;
    if (hi < lo) hi = lo;
    if (a[0].t == V_STR)
        return vstr_o(new_str(AS_STR(a[0])->chars + lo, (uint32_t)(hi - lo)));
    OList *src = AS_LIST(a[0]), *out = new_list((uint32_t)(hi - lo) + 1);
    for (long long i = lo; i < hi; i++) list_push(out, src->items[i]);
    return vlist_o(out);
}

static Value b_sleep(int argc, Value *a) {
    if (argc != 1 || !numlike(a[0]) || as_num(a[0]) < 0)
        vm_error("sleep() needs a number of seconds >= 0");
    double s = as_num(a[0]);
    struct timespec ts;
    ts.tv_sec = (time_t)s;
    ts.tv_nsec = (long)((s - (double)ts.tv_sec) * 1e9);
    nanosleep(&ts, NULL);
    return vnull();
}
static Value b_now(int argc, Value *a) {
    (void)a;
    if (argc != 0) vm_error("now() takes no values");
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return vnum((double)ts.tv_sec + (double)ts.tv_nsec / 1e9);
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
    {"slice", b_slice}, {"sleep", b_sleep}, {"now", b_now},
};
const size_t NBUILTINS = sizeof BUILTINS / sizeof BUILTINS[0];

