/*
 * vxvm — Vidyax bytecode VM, milestone 1.
 *
 * Runs .vxc files produced by vxc.py. Stack-based dispatch, environment
 * chains for scoping (same rule as the Python engines: a name assigned
 * anywhere in a function is local; reading it before it has a value is
 * an error), closures by capturing the defining environment.
 *
 * Deliberately NOT here yet:
 *   - GC (all objects live until exit; Obj headers already carry the
 *     `next` link + mark bit so mark-sweep slots in as milestone 2)
 *   - use ai / member access (rejected by the compiler)
 *   - get(url)  (needs libcurl; raises a catchable error for now)
 *   - unicode-aware upper/lower/len (byte-based; fine for ASCII)
 *
 * Build:  cc -O2 -o vxvm vxvm.c -lm
 * Run:    ./vxvm program.vxc
 */
#include <ctype.h>
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---- opcodes (keep in sync with vxc.py) ---- */
enum {
    OP_CONST = 1, OP_NULL, OP_TRUE, OP_FALSE, OP_POP,
    OP_LOAD, OP_STORE,
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_NEG,
    OP_EQ, OP_NE, OP_LT, OP_LE, OP_GT, OP_GE, OP_NOT,
    OP_JMP, OP_JMP_IF_FALSE, OP_JIF_PEEK, OP_JIT_PEEK,
    OP_LIST, OP_INDEX, OP_CALL, OP_MAKE_FUNC, OP_RET,
    OP_PRINT, OP_ASK, OP_CHECK_RPT, OP_CHECK_ITER, OP_LEN,
    OP_TRY_PUSH, OP_TRY_POP, OP_HALT,
};

/* ---- values & objects ---- */
typedef enum { V_NULL, V_BOOL, V_NUM, V_STR, V_LIST, V_FUNC, V_BUILTIN } VType;
typedef struct Obj Obj;
typedef struct Value {
    VType t;
    union { int b; double n; Obj *o; } as;
} Value;

typedef enum { O_STR, O_LIST, O_FUNC, O_ENV } OType;
struct Obj {           /* common header; `next`+`mark` reserved for GC */
    OType type;
    Obj  *next;
    int   mark;
};

typedef struct { Obj h; uint32_t len; char *chars; } OStr;
typedef struct { Obj h; uint32_t count, cap; Value *items; } OList;

typedef struct Proto {
    OStr    *name;
    uint8_t  nparams;
    OStr   **params;
    uint16_t ndecl;
    OStr   **decl;      /* declared locals (assigned somewhere in body) */
    uint32_t codelen;
    uint8_t *code;
} Proto;

typedef struct Env Env;
typedef struct { OStr *key; Value v; } EnvEntry;
struct Env {
    Obj h;
    Env *parent;
    Proto *proto;       /* whose declared-list guards reads; NULL = global */
    EnvEntry *entries;
    uint32_t count, cap;
};

typedef struct { Obj h; Proto *proto; Env *closure; } OFunc;

typedef Value (*BuiltinFn)(int argc, Value *args);
typedef struct { const char *name; BuiltinFn fn; } Builtin;

/* builtin Value: as.o abused to hold Builtin* (never GC'd, static table) */

/* ---- globals ---- */
static Value  *consts;   static uint32_t nconsts;
static Proto  *protos;   static uint32_t nprotos;
static Obj    *all_objs = NULL;   /* GC-ready allocation list */

#define STACK_MAX   16384
#define FRAMES_MAX  1024
#define HANDLERS_MAX 256

typedef struct { Proto *proto; uint32_t ip; Env *env; } Frame;
typedef struct { int frame; int sp; uint32_t catch_ip; } Handler;

static Value   stack[STACK_MAX];   static int sp = 0;
static Frame   frames[FRAMES_MAX]; static int nframes = 0;
static Handler handlers[HANDLERS_MAX]; static int nhandlers = 0;
static jmp_buf err_jmp;
static char    errmsg[1024];

/* ---- sandbox (blueprint Bab 4): 0 = unlimited ---- */
static uint64_t max_instr = 0, instr_count = 0;
static size_t   max_mem = 0,  mem_used = 0;
static double   max_secs = 0; static clock_t start_clock;

/* ---- GC (blueprint Bab 5): mark-sweep at safepoints ---- */
static size_t   next_gc = 1u << 20;   /* first collection at 1 MB */
static int      gc_pending = 0, gc_stress = 0, gc_stats = 0;
static uint64_t gc_runs = 0;
static size_t   peak_mem = 0;

/* ---- error ---- */
static int jmp_armed = 0;
static void vm_error(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    vsnprintf(errmsg, sizeof errmsg, fmt, ap);
    va_end(ap);
    if (!jmp_armed) { fprintf(stderr, "[Vidyax] %s\n", errmsg); exit(1); }
    longjmp(err_jmp, 1);
}

/* ---- allocation ---- */
static void *xmalloc(size_t n) {
    void *p = malloc(n);
    if (!p) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    mem_used += n;
    if (max_mem && mem_used > max_mem)
        vm_error("VM PANIC: memory limit exceeded (%zu bytes)", max_mem);
    return p;
}
static void *xrealloc(void *old, size_t oldn, size_t newn) {
    void *p = realloc(old, newn);
    if (!p) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    mem_used += newn - oldn;
    if (max_mem && mem_used > max_mem)
        vm_error("VM PANIC: memory limit exceeded (%zu bytes)", max_mem);
    return p;
}
static void xfree(void *p, size_t n) {
    free(p);
    mem_used -= n;
}
static Obj *alloc_obj(size_t size, OType t) {
    Obj *o = xmalloc(size);
    o->type = t; o->mark = 0;
    o->next = all_objs; all_objs = o;
    if (mem_used > peak_mem) peak_mem = mem_used;
    if (mem_used > next_gc) gc_pending = 1;   /* collect at next safepoint */
    return o;
}
static OStr *new_str(const char *chars, uint32_t len) {
    OStr *s = (OStr *)alloc_obj(sizeof(OStr), O_STR);
    s->len = len;
    s->chars = xmalloc((size_t)len + 1);
    memcpy(s->chars, chars, len); s->chars[len] = 0;
    return s;
}
static OList *new_list(uint32_t cap) {
    OList *l = (OList *)alloc_obj(sizeof(OList), O_LIST);
    l->count = 0; l->cap = cap ? cap : 4;
    l->items = xmalloc(sizeof(Value) * l->cap);
    return l;
}
static void list_push(OList *l, Value v) {
    if (l->count == l->cap) {
        l->items = xrealloc(l->items, sizeof(Value) * l->cap,
                            sizeof(Value) * l->cap * 2);
        l->cap *= 2;
    }
    l->items[l->count++] = v;
}
static Env *new_env(Env *parent, Proto *proto) {
    Env *e = (Env *)alloc_obj(sizeof(Env), O_ENV);
    e->parent = parent; e->proto = proto;
    e->count = 0; e->cap = 8;
    e->entries = xmalloc(sizeof(EnvEntry) * e->cap);
    return e;
}

/* ---- value constructors ---- */
static Value vnull(void) { Value v; v.t = V_NULL; v.as.o = NULL; return v; }
static Value vbool(int b) { Value v; v.t = V_BOOL; v.as.b = !!b; return v; }
static Value vnum(double n) { Value v; v.t = V_NUM; v.as.n = n; return v; }
static Value vstr_o(OStr *s) { Value v; v.t = V_STR; v.as.o = (Obj *)s; return v; }
static Value vlist_o(OList *l) { Value v; v.t = V_LIST; v.as.o = (Obj *)l; return v; }
#define AS_STR(v)  ((OStr *)(v).as.o)
#define AS_LIST(v) ((OList *)(v).as.o)
#define AS_FUNC(v) ((OFunc *)(v).as.o)

/* ---- environment (keys compared by pointer: const pool is deduped) ---- */
static void env_set(Env *e, OStr *key, Value v) {
    for (uint32_t i = 0; i < e->count; i++)
        if (e->entries[i].key == key) { e->entries[i].v = v; return; }
    if (e->count == e->cap) {
        e->entries = xrealloc(e->entries, sizeof(EnvEntry) * e->cap,
                              sizeof(EnvEntry) * e->cap * 2);
        e->cap *= 2;
    }
    e->entries[e->count].key = key;
    e->entries[e->count].v = v;
    e->count++;
}
static Value env_get(Env *e, OStr *key) {
    for (Env *env = e; env; env = env->parent) {
        for (uint32_t i = 0; i < env->count; i++)
            if (env->entries[i].key == key) return env->entries[i].v;
        if (env->proto)
            for (uint16_t i = 0; i < env->proto->ndecl; i++)
                if (env->proto->decl[i] == key)
                    vm_error("variable '%s' is assigned in this function "
                             "but used before it has a value", key->chars);
    }
    vm_error("variable '%s' is not defined", key->chars);
    return vnull();
}

/* ---- number formatting (Python-repr compatible) ---- */
static void fmt_double(double v, char *buf, size_t n) {
    if (v != v) { snprintf(buf, n, "nan"); return; }
    if (isinf(v)) { snprintf(buf, n, v < 0 ? "-inf" : "inf"); return; }
    if (v == floor(v)) { snprintf(buf, n, "%.0f", v); return; }
    for (int prec = 1; prec <= 17; prec++) {
        snprintf(buf, n, "%.*g", prec, v);
        if (strtod(buf, NULL) == v) return;
    }
}

/* ---- string builder ---- */
typedef struct { char *buf; size_t len, cap; } SB;
static void sb_init(SB *sb) { sb->cap = 64; sb->len = 0; sb->buf = xmalloc(64); }
static void sb_put(SB *sb, const char *s, size_t n) {
    if (sb->len + n + 1 > sb->cap) {
        size_t old = sb->cap;
        while (sb->len + n + 1 > sb->cap) sb->cap *= 2;
        sb->buf = xrealloc(sb->buf, old, sb->cap);
    }
    memcpy(sb->buf + sb->len, s, n); sb->len += n; sb->buf[sb->len] = 0;
}
static void sb_puts(SB *sb, const char *s) { sb_put(sb, s, strlen(s)); }

static void vstr_into(SB *sb, Value v) {
    char nb[400];
    switch (v.t) {
    case V_NULL: sb_puts(sb, "null"); break;
    case V_BOOL: sb_puts(sb, v.as.b ? "true" : "false"); break;
    case V_NUM:  fmt_double(v.as.n, nb, sizeof nb); sb_puts(sb, nb); break;
    case V_STR:  sb_put(sb, AS_STR(v)->chars, AS_STR(v)->len); break;
    case V_LIST: {
        sb_puts(sb, "[");
        OList *l = AS_LIST(v);
        for (uint32_t i = 0; i < l->count; i++) {
            if (i) sb_puts(sb, ", ");
            vstr_into(sb, l->items[i]);
        }
        sb_puts(sb, "]");
        break;
    }
    case V_FUNC:
        sb_puts(sb, "<func "); sb_puts(sb, AS_FUNC(v)->proto->name->chars);
        sb_puts(sb, ">"); break;
    case V_BUILTIN:
        sb_puts(sb, "<func ");
        sb_puts(sb, ((Builtin *)v.as.o)->name); sb_puts(sb, ">"); break;
    }
}
static OStr *vstr(Value v) {
    if (v.t == V_STR) return AS_STR(v);
    SB sb; sb_init(&sb);
    vstr_into(&sb, v);
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return s;
}

/* ---- semantics helpers ---- */
static int truthy(Value v) {
    switch (v.t) {
    case V_NULL: return 0;
    case V_BOOL: return v.as.b;
    case V_NUM:  return v.as.n != 0;
    case V_STR:  return AS_STR(v)->len > 0;
    case V_LIST: return AS_LIST(v)->count > 0;
    default:     return 1;
    }
}
static int numlike(Value v) { return v.t == V_NUM || v.t == V_BOOL; }
static double as_num(Value v) { return v.t == V_BOOL ? (double)v.as.b : v.as.n; }
static const char *type_name(Value v) {
    switch (v.t) {
    case V_BOOL: return "bool";  case V_NUM:  return "number";
    case V_STR:  return "text";  case V_LIST: return "list";
    case V_NULL: return "null";  default:     return "object";
    }
}
static int values_eq(Value a, Value b) {
    if (numlike(a) && numlike(b)) return as_num(a) == as_num(b);
    if (a.t != b.t) return 0;
    switch (a.t) {
    case V_NULL: return 1;
    case V_STR:  return AS_STR(a)->len == AS_STR(b)->len &&
                        memcmp(AS_STR(a)->chars, AS_STR(b)->chars,
                               AS_STR(a)->len) == 0;
    case V_LIST: {
        OList *x = AS_LIST(a), *y = AS_LIST(b);
        if (x->count != y->count) return 0;
        for (uint32_t i = 0; i < x->count; i++)
            if (!values_eq(x->items[i], y->items[i])) return 0;
        return 1;
    }
    default: return a.as.o == b.as.o;
    }
}
/* returns -1/0/1; errors on incomparable */
static int values_cmp(Value a, Value b) {
    if (numlike(a) && numlike(b)) {
        double x = as_num(a), y = as_num(b);
        return (x > y) - (x < y);
    }
    if (a.t == V_STR && b.t == V_STR) {
        OStr *x = AS_STR(a), *y = AS_STR(b);
        uint32_t n = x->len < y->len ? x->len : y->len;
        int c = memcmp(x->chars, y->chars, n);
        if (c) return c < 0 ? -1 : 1;
        return (x->len > y->len) - (x->len < y->len);
    }
    if (a.t == V_LIST && b.t == V_LIST) {
        OList *x = AS_LIST(a), *y = AS_LIST(b);
        uint32_t n = x->count < y->count ? x->count : y->count;
        for (uint32_t i = 0; i < n; i++) {
            if (values_eq(x->items[i], y->items[i])) continue;
            return values_cmp(x->items[i], y->items[i]);
        }
        return (x->count > y->count) - (x->count < y->count);
    }
    vm_error("cannot compare %s with %s", type_name(a), type_name(b));
    return 0;
}
static Value do_add(Value a, Value b) {
    if (a.t == V_STR || b.t == V_STR) {
        OStr *x = vstr(a), *y = vstr(b);
        SB sb; sb_init(&sb);
        sb_put(&sb, x->chars, x->len); sb_put(&sb, y->chars, y->len);
        OStr *s = new_str(sb.buf, (uint32_t)sb.len);
        xfree(sb.buf, sb.cap);
        return vstr_o(s);
    }
    if (a.t == V_LIST && b.t == V_LIST) {
        OList *x = AS_LIST(a), *y = AS_LIST(b);
        OList *r = new_list(x->count + y->count);
        for (uint32_t i = 0; i < x->count; i++) list_push(r, x->items[i]);
        for (uint32_t i = 0; i < y->count; i++) list_push(r, y->items[i]);
        return vlist_o(r);
    }
    if (numlike(a) && numlike(b)) return vnum(as_num(a) + as_num(b));
    vm_error("cannot add %s and %s", type_name(a), type_name(b));
    return vnull();
}
static Value do_index(Value o, Value iv) {
    if (!numlike(iv)) vm_error("index out of range");
    long long i = (long long)as_num(iv);   /* truncates, like int() */
    if (o.t == V_LIST) {
        OList *l = AS_LIST(o);
        if (i < 0) i += l->count;
        if (i < 0 || (uint64_t)i >= l->count) vm_error("index out of range");
        return l->items[i];
    }
    if (o.t == V_STR) {
        OStr *s = AS_STR(o);
        if (i < 0) i += s->len;
        if (i < 0 || (uint64_t)i >= s->len) vm_error("index out of range");
        return vstr_o(new_str(s->chars + i, 1));
    }
    vm_error("index out of range");
    return vnull();
}

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
    (void)argc; (void)a;
    vm_error("get() is not supported in vxvm yet — use `vidyax run`");
    return vnull();
}

static Builtin BUILTINS[] = {
    {"len", b_len}, {"range", b_range}, {"text", b_text}, {"num", b_num},
    {"upper", b_upper}, {"lower", b_lower}, {"split", b_split},
    {"join", b_join}, {"push", b_push}, {"abs", b_abs}, {"sum", b_sum},
    {"min", b_min}, {"max", b_max}, {"type", b_type}, {"get", b_get},
};

/* ---- loader ---- */
static uint8_t *fdata; static size_t fsize, fpos;
static void need(size_t n) {
    if (fpos + n > fsize) { fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1); }
}
static uint8_t  r_u8(void)  { need(1); return fdata[fpos++]; }
static uint16_t r_u16(void) { need(2); uint16_t v; memcpy(&v, fdata + fpos, 2); fpos += 2; return v; }
static uint32_t r_u32(void) { need(4); uint32_t v; memcpy(&v, fdata + fpos, 4); fpos += 4; return v; }
static double   r_f64(void) { need(8); double v; memcpy(&v, fdata + fpos, 8); fpos += 8; return v; }

static OStr *const_str(uint32_t ix) {
    if (ix >= nconsts || consts[ix].t != V_STR) {
        fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1);
    }
    return AS_STR(consts[ix]);
}

static void load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "[Vidyax] cannot open: %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END); fsize = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    fdata = xmalloc(fsize);
    if (fread(fdata, 1, fsize, f) != fsize) {
        fprintf(stderr, "[Vidyax] cannot read: %s\n", path); exit(1);
    }
    fclose(f);
    need(5);
    if (memcmp(fdata, "VXC1", 4) != 0) {
        fprintf(stderr, "[Vidyax] not a .vxc file: %s\n", path); exit(1);
    }
    fpos = 4;
    if (r_u8() != 1) { fprintf(stderr, "[Vidyax] unsupported .vxc version\n"); exit(1); }
    nconsts = r_u32();
    consts = xmalloc(sizeof(Value) * (nconsts ? nconsts : 1));
    for (uint32_t i = 0; i < nconsts; i++) {
        uint8_t tag = r_u8();
        if (tag == 1) consts[i] = vnum(r_f64());
        else if (tag == 2) {
            uint32_t len = r_u32(); need(len);
            consts[i] = vstr_o(new_str((char *)fdata + fpos, len));
            fpos += len;
        } else { fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1); }
    }
    nprotos = r_u32();
    protos = xmalloc(sizeof(Proto) * (nprotos ? nprotos : 1));
    for (uint32_t i = 0; i < nprotos; i++) {
        Proto *p = &protos[i];
        p->name = const_str(r_u32());
        p->nparams = r_u8();
        p->params = xmalloc(sizeof(OStr *) * (p->nparams ? p->nparams : 1));
        for (int j = 0; j < p->nparams; j++) p->params[j] = const_str(r_u32());
        p->ndecl = r_u16();
        p->decl = xmalloc(sizeof(OStr *) * (p->ndecl ? p->ndecl : 1));
        for (int j = 0; j < p->ndecl; j++) p->decl[j] = const_str(r_u32());
        p->codelen = r_u32(); need(p->codelen);
        p->code = fdata + fpos; fpos += p->codelen;
    }
}

/* ---- bytecode verifier (blueprint Bab 4) ----
 * Two passes per proto: (1) walk instructions, validate opcode + operand
 * ranges, mark instruction-start offsets; (2) every jump target must land
 * exactly on an instruction start. Rejecting bad VIR before execution. */
static int opsize(uint8_t op) {   /* operand bytes; -1 = unknown opcode */
    switch (op) {
    case OP_CONST: case OP_LOAD: case OP_STORE:
    case OP_LIST: case OP_MAKE_FUNC: return 2;
    case OP_CALL: return 1;
    case OP_JMP: case OP_JMP_IF_FALSE: case OP_JIF_PEEK:
    case OP_JIT_PEEK: case OP_TRY_PUSH: return 4;
    case OP_NULL: case OP_TRUE: case OP_FALSE: case OP_POP:
    case OP_ADD: case OP_SUB: case OP_MUL: case OP_DIV: case OP_MOD:
    case OP_NEG: case OP_EQ: case OP_NE: case OP_LT: case OP_LE:
    case OP_GT: case OP_GE: case OP_NOT: case OP_INDEX: case OP_RET:
    case OP_PRINT: case OP_ASK: case OP_CHECK_RPT: case OP_CHECK_ITER:
    case OP_LEN: case OP_TRY_POP: case OP_HALT: return 0;
    default: return -1;
    }
}
static void verify(void) {
    for (uint32_t pi = 0; pi < nprotos; pi++) {
        Proto *p = &protos[pi];
        uint8_t *starts = calloc(p->codelen + 1, 1);
        if (!starts) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
        uint32_t i = 0;
        while (i < p->codelen) {
            starts[i] = 1;
            uint8_t op = p->code[i];
            int sz = opsize(op);
            if (sz < 0) {
                fprintf(stderr, "[Vidyax] verify: bad opcode %d at %u "
                        "in '%s'\n", op, i, p->name->chars);
                exit(1);
            }
            if (i + 1 + (uint32_t)sz > p->codelen) {
                fprintf(stderr, "[Vidyax] verify: truncated instruction "
                        "at %u in '%s'\n", i, p->name->chars);
                exit(1);
            }
            if (op == OP_CONST || op == OP_LOAD || op == OP_STORE) {
                uint16_t ix; memcpy(&ix, p->code + i + 1, 2);
                if (ix >= nconsts) {
                    fprintf(stderr, "[Vidyax] verify: const %u out of "
                            "range in '%s'\n", ix, p->name->chars);
                    exit(1);
                }
                if ((op == OP_LOAD || op == OP_STORE) &&
                    consts[ix].t != V_STR) {
                    fprintf(stderr, "[Vidyax] verify: LOAD/STORE needs a "
                            "name constant in '%s'\n", p->name->chars);
                    exit(1);
                }
            }
            if (op == OP_MAKE_FUNC) {
                uint16_t ix; memcpy(&ix, p->code + i + 1, 2);
                if (ix >= nprotos) {
                    fprintf(stderr, "[Vidyax] verify: proto %u out of "
                            "range in '%s'\n", ix, p->name->chars);
                    exit(1);
                }
            }
            i += 1 + (uint32_t)sz;
        }
        i = 0;
        while (i < p->codelen) {
            uint8_t op = p->code[i];
            int sz = opsize(op);
            if (sz == 4) {   /* all 4-byte operands are jump targets */
                uint32_t t; memcpy(&t, p->code + i + 1, 4);
                if (t >= p->codelen || !starts[t]) {
                    fprintf(stderr, "[Vidyax] verify: bad jump target %u "
                            "in '%s'\n", t, p->name->chars);
                    exit(1);
                }
            }
            i += 1 + (uint32_t)sz;
        }
        free(starts);
    }
}

/* ---- mark-sweep GC (blueprint Bab 5) ----
 * Runs ONLY at safepoints (top of the dispatch loop, between
 * instructions), so no C-local temporary can be collected mid-operation.
 * Allocation never collects — it just raises gc_pending.
 * Roots: constant pool, operand stack, every frame's env chain. */
static void mark_value(Value v);
static void mark_obj(Obj *o) {
    if (!o || o->mark) return;
    o->mark = 1;
    switch (o->type) {
    case O_STR: break;
    case O_LIST: {
        OList *l = (OList *)o;
        for (uint32_t i = 0; i < l->count; i++) mark_value(l->items[i]);
        break;
    }
    case O_FUNC:
        mark_obj((Obj *)((OFunc *)o)->closure);
        break;
    case O_ENV: {
        Env *e = (Env *)o;
        for (uint32_t i = 0; i < e->count; i++) {
            mark_obj((Obj *)e->entries[i].key);
            mark_value(e->entries[i].v);
        }
        mark_obj((Obj *)e->parent);
        break;
    }
    }
}
static void mark_value(Value v) {
    /* V_BUILTIN points into a static table, not the GC heap */
    if (v.t == V_STR || v.t == V_LIST || v.t == V_FUNC)
        mark_obj(v.as.o);
}
static void free_obj(Obj *o) {   /* mirrors every byte alloc counted */
    switch (o->type) {
    case O_STR: {
        OStr *s = (OStr *)o;
        mem_used -= sizeof(OStr) + s->len + 1;
        free(s->chars);
        break;
    }
    case O_LIST: {
        OList *l = (OList *)o;
        mem_used -= sizeof(OList) + l->cap * sizeof(Value);
        free(l->items);
        break;
    }
    case O_FUNC:
        mem_used -= sizeof(OFunc);
        break;
    case O_ENV: {
        Env *e = (Env *)o;
        mem_used -= sizeof(Env) + e->cap * sizeof(EnvEntry);
        free(e->entries);
        break;
    }
    }
    free(o);
}
static void gc(void) {
    gc_pending = 0;
    for (uint32_t i = 0; i < nconsts; i++) mark_value(consts[i]);
    for (int i = 0; i < sp; i++) mark_value(stack[i]);
    for (int f = 0; f < nframes; f++) mark_obj((Obj *)frames[f].env);
    Obj **p = &all_objs;
    while (*p) {
        if ((*p)->mark) {
            (*p)->mark = 0;
            p = &(*p)->next;
        } else {
            Obj *dead = *p;
            *p = dead->next;
            free_obj(dead);
        }
    }
    if (next_gc < mem_used * 2) next_gc = mem_used * 2;
    if (next_gc < (1u << 20)) next_gc = 1u << 20;
    gc_runs++;
}

/* ---- VM ---- */
static void push(Value v) {
    if (sp >= STACK_MAX) vm_error("stack overflow");
    stack[sp++] = v;
}
static Value pop(void) { return stack[--sp]; }

static void run(void) {
    Env *global = new_env(NULL, NULL);
    /* register only the builtins the program can actually name */
    for (size_t b = 0; b < sizeof BUILTINS / sizeof BUILTINS[0]; b++)
        for (uint32_t i = 0; i < nconsts; i++)
            if (consts[i].t == V_STR &&
                strcmp(AS_STR(consts[i])->chars, BUILTINS[b].name) == 0) {
                Value v; v.t = V_BUILTIN; v.as.o = (Obj *)&BUILTINS[b];
                env_set(global, AS_STR(consts[i]), v);
                break;
            }

    frames[0].proto = &protos[0];
    frames[0].ip = 0;
    frames[0].env = global;
    nframes = 1;

    jmp_armed = 1;
    if (setjmp(err_jmp)) {
        /* runtime error: unwind to the innermost try handler, or die */
        if (nhandlers > 0) {
            Handler h = handlers[--nhandlers];
            nframes = h.frame + 1;
            sp = h.sp;
            frames[nframes - 1].ip = h.catch_ip;
            push(vstr_o(new_str(errmsg, (uint32_t)strlen(errmsg))));
        } else {
            printf("[Vidyax] %s\n", errmsg);
            exit(1);
        }
    }

    for (;;) {
        if (gc_stress || gc_pending) gc();   /* safepoint */
        if (max_instr && ++instr_count > max_instr)
            vm_error("VM PANIC: instruction limit exceeded (%llu)",
                     (unsigned long long)max_instr);
        if (max_secs && (instr_count & 4095) == 0 &&
            (double)(clock() - start_clock) / CLOCKS_PER_SEC > max_secs)
            vm_error("VM PANIC: time limit exceeded (%.1fs)", max_secs);
        Frame *fr = &frames[nframes - 1];
        uint8_t *code = fr->proto->code;
        uint8_t op = code[fr->ip++];
        switch (op) {
        case OP_CONST: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            push(consts[ix]); break;
        }
        case OP_NULL:  push(vnull());  break;
        case OP_TRUE:  push(vbool(1)); break;
        case OP_FALSE: push(vbool(0)); break;
        case OP_POP:   pop(); break;
        case OP_LOAD: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            push(env_get(fr->env, AS_STR(consts[ix]))); break;
        }
        case OP_STORE: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            env_set(fr->env, AS_STR(consts[ix]), pop()); break;
        }
        case OP_ADD: { Value b = pop(), a = pop(); push(do_add(a, b)); break; }
        case OP_SUB: case OP_MUL: case OP_MOD: {
            Value b = pop(), a = pop();
            if (!numlike(a) || !numlike(b))
                vm_error("cannot do arithmetic on %s and %s",
                         type_name(a), type_name(b));
            double x = as_num(a), y = as_num(b);
            if (op == OP_SUB) push(vnum(x - y));
            else if (op == OP_MUL) push(vnum(x * y));
            else {
                if (y == 0) vm_error("cannot divide by 0");
                double r = fmod(x, y);
                if (r != 0 && ((r < 0) != (y < 0))) r += y;  /* Python % */
                push(vnum(r));
            }
            break;
        }
        case OP_DIV: {
            Value b = pop(), a = pop();
            if (!numlike(a) || !numlike(b))
                vm_error("cannot do arithmetic on %s and %s",
                         type_name(a), type_name(b));
            if (as_num(b) == 0) vm_error("cannot divide by 0");
            push(vnum(as_num(a) / as_num(b)));
            break;
        }
        case OP_NEG: {
            Value a = pop();
            if (!numlike(a)) vm_error("cannot negate %s", type_name(a));
            push(vnum(-as_num(a)));
            break;
        }
        case OP_EQ: { Value b = pop(), a = pop(); push(vbool(values_eq(a, b))); break; }
        case OP_NE: { Value b = pop(), a = pop(); push(vbool(!values_eq(a, b))); break; }
        case OP_LT: { Value b = pop(), a = pop(); push(vbool(values_cmp(a, b) < 0)); break; }
        case OP_LE: { Value b = pop(), a = pop(); push(vbool(values_cmp(a, b) <= 0)); break; }
        case OP_GT: { Value b = pop(), a = pop(); push(vbool(values_cmp(a, b) > 0)); break; }
        case OP_GE: { Value b = pop(), a = pop(); push(vbool(values_cmp(a, b) >= 0)); break; }
        case OP_NOT: push(vbool(!truthy(pop()))); break;
        case OP_JMP: {
            uint32_t t; memcpy(&t, code + fr->ip, 4); fr->ip = t; break;
        }
        case OP_JMP_IF_FALSE: {
            uint32_t t; memcpy(&t, code + fr->ip, 4); fr->ip += 4;
            if (!truthy(pop())) fr->ip = t;
            break;
        }
        case OP_JIF_PEEK: {
            uint32_t t; memcpy(&t, code + fr->ip, 4); fr->ip += 4;
            if (!truthy(stack[sp - 1])) fr->ip = t;
            break;
        }
        case OP_JIT_PEEK: {
            uint32_t t; memcpy(&t, code + fr->ip, 4); fr->ip += 4;
            if (truthy(stack[sp - 1])) fr->ip = t;
            break;
        }
        case OP_LIST: {
            uint16_t n; memcpy(&n, code + fr->ip, 2); fr->ip += 2;
            OList *l = new_list(n ? n : 1);
            for (int i = 0; i < n; i++) list_push(l, stack[sp - n + i]);
            sp -= n;
            push(vlist_o(l));
            break;
        }
        case OP_INDEX: { Value i = pop(), o = pop(); push(do_index(o, i)); break; }
        case OP_CALL: {
            uint8_t argc = code[fr->ip++];
            Value callee = stack[sp - argc - 1];
            if (callee.t == V_BUILTIN) {
                Value r = ((Builtin *)callee.as.o)->fn(argc, &stack[sp - argc]);
                sp -= argc + 1;
                push(r);
            } else if (callee.t == V_FUNC) {
                OFunc *fn = AS_FUNC(callee);
                if (argc != fn->proto->nparams)
                    vm_error("function '%s' needs %d args, got %d",
                             fn->proto->name->chars, fn->proto->nparams, argc);
                if (nframes >= FRAMES_MAX) vm_error("recursion too deep");
                Env *env = new_env(fn->closure, fn->proto);
                for (int i = 0; i < argc; i++)
                    env_set(env, fn->proto->params[i], stack[sp - argc + i]);
                sp -= argc + 1;
                frames[nframes].proto = fn->proto;
                frames[nframes].ip = 0;
                frames[nframes].env = env;
                nframes++;
            } else {
                vm_error("this is not a function");
            }
            break;
        }
        case OP_MAKE_FUNC: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            OFunc *fn = (OFunc *)alloc_obj(sizeof(OFunc), O_FUNC);
            fn->proto = &protos[ix];
            fn->closure = fr->env;
            Value v; v.t = V_FUNC; v.as.o = (Obj *)fn;
            push(v);
            break;
        }
        case OP_RET: {
            /* drop try handlers opened in this frame (return inside try) */
            while (nhandlers > 0 && handlers[nhandlers - 1].frame == nframes - 1)
                nhandlers--;
            Value r = pop();
            nframes--;
            push(r);
            break;
        }
        case OP_PRINT: {
            OStr *s = vstr(pop());
            fwrite(s->chars, 1, s->len, stdout);
            fputc('\n', stdout);
            break;
        }
        case OP_ASK: {
            OStr *prompt = vstr(pop());
            fwrite(prompt->chars, 1, prompt->len, stdout);
            fputc(' ', stdout);
            fflush(stdout);
            char *line = NULL; size_t cap = 0;
            ssize_t n = getline(&line, &cap, stdin);
            if (n < 0) { free(line); vm_error("input ended"); }
            while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) n--;
            push(vstr_o(new_str(line, (uint32_t)n)));
            free(line);
            break;
        }
        case OP_CHECK_RPT: {
            Value v = stack[sp - 1];
            if (v.t != V_NUM) vm_error("'rpt' needs a number");
            stack[sp - 1] = vnum(trunc(v.as.n));
            break;
        }
        case OP_CHECK_ITER: {
            Value v = stack[sp - 1];
            if (v.t != V_LIST && v.t != V_STR)
                vm_error("'for ... in' needs a list or text");
            break;
        }
        case OP_LEN: {
            Value v = pop();
            push(vnum(v.t == V_LIST ? (double)AS_LIST(v)->count
                                    : (double)AS_STR(v)->len));
            break;
        }
        case OP_TRY_PUSH: {
            uint32_t t; memcpy(&t, code + fr->ip, 4); fr->ip += 4;
            if (nhandlers >= HANDLERS_MAX) vm_error("too many nested try");
            handlers[nhandlers].frame = nframes - 1;
            handlers[nhandlers].sp = sp;
            handlers[nhandlers].catch_ip = t;
            nhandlers++;
            break;
        }
        case OP_TRY_POP:
            nhandlers--;
            break;
        case OP_HALT:
            if (gc_stats)
                fprintf(stderr, "[vxvm] gc runs: %llu, peak mem: %zu bytes, "
                        "live at exit: %zu bytes\n",
                        (unsigned long long)gc_runs, peak_mem, mem_used);
            return;
        default:
            fprintf(stderr, "[Vidyax] bad opcode %d\n", op);
            exit(1);
        }
    }
}

int main(int argc, char **argv) {
    const char *path = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--max-instr") == 0 && i + 1 < argc)
            max_instr = strtoull(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--max-mem") == 0 && i + 1 < argc)
            max_mem = (size_t)strtoull(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--max-time") == 0 && i + 1 < argc)
            max_secs = strtod(argv[++i], NULL);
        else if (strcmp(argv[i], "--gc-stress") == 0)
            gc_stress = 1;   /* collect at EVERY safepoint (testing) */
        else if (strcmp(argv[i], "--gc-stats") == 0)
            gc_stats = 1;
        else if (argv[i][0] != '-')
            path = argv[i];
        else {
            fprintf(stderr, "usage: vxvm [--max-instr N] [--max-mem BYTES]"
                    " [--max-time SECS] <program.vxc>\n");
            return 1;
        }
    }
    if (!path) {
        fprintf(stderr, "usage: vxvm [--max-instr N] [--max-mem BYTES]"
                " [--max-time SECS] <program.vxc>\n");
        return 1;
    }
    load(path);
    if (nprotos == 0) { fprintf(stderr, "[Vidyax] empty program\n"); return 1; }
    verify();
    start_clock = clock();
    run();
    return 0;
}
