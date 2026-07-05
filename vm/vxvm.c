/*
 * vxvm — Vidyax bytecode VM, milestone 1.
 *
 * Runs .vxc files produced by vxc.py. Stack-based dispatch, environment
 * chains for scoping (same rule as the Python engines: a name assigned
 * anywhere in a function is local; reading it before it has a value is
 * an error), closures by capturing the defining environment.
 *
 * Deliberately NOT here yet:
 *   - unicode-aware upper/lower/len (byte-based; fine for ASCII)
 *
 * `use ai`, member access and get() are live: the ai module mirrors the
 * Python engines' implementation and ai.ask()/get() perform real HTTP via
 * libcurl. Build without libcurl (make CURL=0) and those two raise a
 * catchable error instead.
 *
 * Build:  make            (auto-detects libcurl via pkg-config)
 *         cc -O2 -DVX_HAVE_CURL -o vxvm vxvm.c -lm -lcurl
 * Run:    ./vxvm program.vxc
 */
#ifdef VX_HAVE_CURL
#include <curl/curl.h>
#endif
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
    OP_LOAD_SLOT, OP_STORE_SLOT,
    OP_AI_NEW, OP_GET_MEMBER,
};

/* ---- values & objects ---- */
typedef enum { V_NULL, V_BOOL, V_NUM, V_STR, V_LIST, V_FUNC, V_BUILTIN,
               V_AI, V_BOUND, /* ai module object + bound method */
               V_UNSET /* internal: slot declared but not yet assigned */ } VType;
typedef struct Obj Obj;
typedef struct Value {
    VType t;
    union { int b; double n; Obj *o; } as;
} Value;

typedef enum { O_STR, O_LIST, O_FUNC, O_ENV, O_AI, O_BOUND } OType;
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
    uint16_t nslots;     /* stack slots per call; first nparams = params */
    OStr   **slot_names; /* for the read-before-assign error message */
    uint8_t  nescp;      /* how many params escape into the heap env */
    uint8_t *escp;       /* their param indexes */
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

/* ai module object (mirrors vidyax.py _AI) + a method bound to one */
enum { PROV_GROQ = 0, PROV_OPENAI = 1 };
enum { AIM_OPEN = 0, AIM_SYSTEM = 1, AIM_ASK = 2 };
typedef struct { Obj h; int provider; OStr *model; OStr *system_prompt; } OAI;
typedef struct { Obj h; OAI *self; int method; } OBound;

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

typedef struct { Proto *proto; uint32_t ip; Env *env; int base; } Frame;
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
static Value vunset(void) { Value v; v.t = V_UNSET; v.as.o = NULL; return v; }
static Value vbool(int b) { Value v; v.t = V_BOOL; v.as.b = !!b; return v; }
static Value vnum(double n) { Value v; v.t = V_NUM; v.as.n = n; return v; }
static Value vstr_o(OStr *s) { Value v; v.t = V_STR; v.as.o = (Obj *)s; return v; }
static Value vlist_o(OList *l) { Value v; v.t = V_LIST; v.as.o = (Obj *)l; return v; }
static Value vai_o(OAI *a) { Value v; v.t = V_AI; v.as.o = (Obj *)a; return v; }
static Value vbound_o(OBound *b) { Value v; v.t = V_BOUND; v.as.o = (Obj *)b; return v; }
#define AS_STR(v)  ((OStr *)(v).as.o)
#define AS_LIST(v) ((OList *)(v).as.o)
#define AS_FUNC(v) ((OFunc *)(v).as.o)
#define AS_AI(v)   ((OAI *)(v).as.o)
#define AS_BOUND(v) ((OBound *)(v).as.o)

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
    case V_UNSET: sb_puts(sb, "<unset:bug>"); break;  /* must never leak */
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
    case V_AI: sb_puts(sb, "<ai>"); break;
    case V_BOUND: {
        static const char *mn[] = {"open", "system", "ask"};
        sb_puts(sb, "<func ai."); sb_puts(sb, mn[AS_BOUND(v)->method]);
        sb_puts(sb, ">"); break;
    }
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

/* ==================================================================
 * ai module + member access + HTTP  (mirrors vidyax.py's _AI / _member
 * / _b_get). Real requests go through libcurl; without it the two
 * network entry points raise a catchable error.
 * ================================================================== */

/* ---- minimal JSON: escape strings out, pull one string value in ---- */
static int is_hex(int c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
           (c >= 'A' && c <= 'F');
}
static unsigned hex_val(int c) {
    if (c >= '0' && c <= '9') return (unsigned)(c - '0');
    if (c >= 'a' && c <= 'f') return (unsigned)(c - 'a' + 10);
    return (unsigned)(c - 'A' + 10);
}
static void utf8_put(SB *sb, unsigned cp) {
    char b[4];
    if (cp < 0x80) { b[0] = (char)cp; sb_put(sb, b, 1); }
    else if (cp < 0x800) {
        b[0] = (char)(0xC0 | (cp >> 6)); b[1] = (char)(0x80 | (cp & 0x3F));
        sb_put(sb, b, 2);
    } else if (cp < 0x10000) {
        b[0] = (char)(0xE0 | (cp >> 12));
        b[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[2] = (char)(0x80 | (cp & 0x3F)); sb_put(sb, b, 3);
    } else {
        b[0] = (char)(0xF0 | (cp >> 18));
        b[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
        b[2] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[3] = (char)(0x80 | (cp & 0x3F)); sb_put(sb, b, 4);
    }
}
static void json_escape(SB *sb, const char *s, uint32_t len) {
    static const char *hex = "0123456789abcdef";
    for (uint32_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)s[i];
        switch (ch) {
        case '"':  sb_puts(sb, "\\\""); break;
        case '\\': sb_puts(sb, "\\\\"); break;
        case '\n': sb_puts(sb, "\\n"); break;
        case '\r': sb_puts(sb, "\\r"); break;
        case '\t': sb_puts(sb, "\\t"); break;
        case '\b': sb_puts(sb, "\\b"); break;
        case '\f': sb_puts(sb, "\\f"); break;
        default:
            if (ch < 0x20) {
                char u[6] = {'\\', 'u', '0', '0', hex[ch >> 4], hex[ch & 0xF]};
                sb_put(sb, u, 6);
            } else { char c = (char)ch; sb_put(sb, &c, 1); }
        }
    }
}
/* Read a JSON string literal at p (points at the opening quote), decoding
 * escapes into out. Returns 1 on a well-formed string. */
static int json_read_string(const char *p, SB *out) {
    if (*p != '"') return 0;
    p++;
    while (*p && *p != '"') {
        if (*p == '\\') {
            p++;
            switch (*p) {
            case '"':  sb_put(out, "\"", 1); break;
            case '\\': sb_put(out, "\\", 1); break;
            case '/':  sb_put(out, "/", 1);  break;
            case 'n':  sb_put(out, "\n", 1); break;
            case 't':  sb_put(out, "\t", 1); break;
            case 'r':  sb_put(out, "\r", 1); break;
            case 'b':  sb_put(out, "\b", 1); break;
            case 'f':  sb_put(out, "\f", 1); break;
            case 'u': {
                if (!is_hex(p[1]) || !is_hex(p[2]) ||
                    !is_hex(p[3]) || !is_hex(p[4])) return 0;
                unsigned cp = (hex_val(p[1]) << 12) | (hex_val(p[2]) << 8) |
                              (hex_val(p[3]) << 4) | hex_val(p[4]);
                p += 4;
                if (cp >= 0xD800 && cp <= 0xDBFF && p[1] == '\\' &&
                    p[2] == 'u' && is_hex(p[3]) && is_hex(p[4]) &&
                    is_hex(p[5]) && is_hex(p[6])) {
                    unsigned lo = (hex_val(p[3]) << 12) | (hex_val(p[4]) << 8) |
                                  (hex_val(p[5]) << 4) | hex_val(p[6]);
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    p += 6;
                }
                utf8_put(out, cp);
                break;
            }
            case 0: return 0;
            default: { char c = *p; sb_put(out, &c, 1); }
            }
            p++;
        } else { sb_put(out, p, 1); p++; }
    }
    return *p == '"';
}
/* Find "key" used as an object key with a string value; decode into out.
 * Good enough for the chat-completions replies we consume (any escaped
 * occurrence inside a value keeps its backslash, so it never matches). */
static int json_extract_string(const char *buf, const char *key, SB *out) {
    size_t klen = strlen(key);
    const char *p = buf;
    while ((p = strchr(p, '"')) != NULL) {
        if (strncmp(p + 1, key, klen) == 0 && p[1 + klen] == '"') {
            const char *q = p + 2 + klen;
            while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r') q++;
            if (*q == ':') {
                q++;
                while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r') q++;
                if (*q == '"') return json_read_string(q, out);
            }
        }
        p++;
    }
    return 0;
}

/* ---- HTTP transport (libcurl) ---- */
#ifdef VX_HAVE_CURL
static size_t http_write(char *ptr, size_t sz, size_t nm, void *ud) {
    sb_put((SB *)ud, ptr, sz * nm);
    return sz * nm;
}
/* Perform a request. body!=NULL -> POST JSON with Bearer auth. On transport
 * success returns 0 (HTTP status in *code, response in *resp); on failure
 * returns -1 with a message in err. */
static int http_request(const char *url, const char *auth, const char *body,
                        SB *resp, long *code, char *err, size_t errn) {
    CURL *c = curl_easy_init();
    if (!c) { snprintf(err, errn, "curl init failed"); return -1; }
    struct curl_slist *hdrs = NULL;
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, http_write);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, resp);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "vidyax/1.1");
    curl_easy_setopt(c, CURLOPT_TIMEOUT, body ? 60L : 15L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    if (auth) {
        char ab[600];
        snprintf(ab, sizeof ab, "Authorization: Bearer %s", auth);
        hdrs = curl_slist_append(hdrs, ab);
    }
    if (body) {
        hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
        curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
        curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    }
    if (hdrs) curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    CURLcode rc = curl_easy_perform(c);
    if (rc == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, code);
    else snprintf(err, errn, "%s", curl_easy_strerror(rc));
    if (hdrs) curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
    return rc == CURLE_OK ? 0 : -1;
}
#endif

/* ---- ai module ---- */
static const char *trim(const char *s, size_t len, size_t *outlen) {
    while (len && isspace((unsigned char)*s)) { s++; len--; }
    while (len && isspace((unsigned char)s[len - 1])) len--;
    *outlen = len;
    return s;
}
static void ai_open(OAI *self, const char *spec) {
    const char *colon = strchr(spec, ':');
    if (colon) {
        size_t plen; const char *pp = trim(spec, (size_t)(colon - spec), &plen);
        char prov[64];
        if (plen >= sizeof prov) plen = sizeof prov - 1;
        for (size_t i = 0; i < plen; i++)
            prov[i] = (char)tolower((unsigned char)pp[i]);
        prov[plen] = 0;
        int pv;
        if (strcmp(prov, "groq") == 0) pv = PROV_GROQ;
        else if (strcmp(prov, "openai") == 0) pv = PROV_OPENAI;
        else vm_error("unknown AI provider '%s' (available: groq, openai)",
                      prov);
        self->provider = pv;
        size_t mlen; const char *mm = trim(colon + 1, strlen(colon + 1), &mlen);
        if (mlen) self->model = new_str(mm, (uint32_t)mlen);
    } else {
        size_t mlen; const char *mm = trim(spec, strlen(spec), &mlen);
        self->model = new_str(mm, (uint32_t)mlen);
    }
}
static OAI *new_ai(void) {
    OAI *a = (OAI *)alloc_obj(sizeof(OAI), O_AI);
    a->provider = PROV_GROQ;
    a->model = new_str("llama-3.1-8b-instant", 20);
    a->system_prompt = NULL;
    const char *env = getenv("VIDYAX_MODEL");
    if (env && *env) ai_open(a, env);
    return a;
}
static OBound *new_bound(OAI *self, int method) {
    OBound *b = (OBound *)alloc_obj(sizeof(OBound), O_BOUND);
    b->self = self; b->method = method;
    return b;
}
static Value ai_ask(OAI *self, OStr *prompt) {
#ifndef VX_HAVE_CURL
    (void)self; (void)prompt;
    vm_error("ai.ask needs libcurl (rebuild vxvm with libcurl available)");
    return vnull();
#else
    const char *url, *keyname;
    if (self->provider == PROV_OPENAI) {
        url = "https://api.openai.com/v1/chat/completions";
        keyname = "OPENAI_API_KEY";
    } else {
        url = "https://api.groq.com/openai/v1/chat/completions";
        keyname = "GROQ_API_KEY";
    }
    const char *key = getenv(keyname);
    if (!key || !*key)
        vm_error("%s is not set. Run: export %s=...  "
                 "(ai.ask needs internet & an API key)", keyname, keyname);

    SB body; sb_init(&body);
    sb_puts(&body, "{\"model\":\"");
    json_escape(&body, self->model->chars, self->model->len);
    sb_puts(&body, "\",\"messages\":[");
    if (self->system_prompt) {
        sb_puts(&body, "{\"role\":\"system\",\"content\":\"");
        json_escape(&body, self->system_prompt->chars,
                    self->system_prompt->len);
        sb_puts(&body, "\"},");
    }
    sb_puts(&body, "{\"role\":\"user\",\"content\":\"");
    json_escape(&body, prompt->chars, prompt->len);
    sb_puts(&body, "\"}]}");

    SB resp; sb_init(&resp);
    long code = 0; char err[256];
    int rc = http_request(url, key, body.buf, &resp, &code, err, sizeof err);
    xfree(body.buf, body.cap);
    if (rc != 0) {
        char e[300]; snprintf(e, sizeof e, "%s", err);
        xfree(resp.buf, resp.cap);
        vm_error("AI failed: %s", e);
    }
    if (code >= 400) {
        char snippet[220]; snprintf(snippet, sizeof snippet, "%.200s",
                                    resp.buf ? resp.buf : "");
        long cc = code; xfree(resp.buf, resp.cap);
        vm_error("AI failed (HTTP %ld): %s", cc, snippet);
    }
    SB out; sb_init(&out);
    if (json_extract_string(resp.buf, "content", &out)) {
        OStr *s = new_str(out.buf, (uint32_t)out.len);
        xfree(out.buf, out.cap); xfree(resp.buf, resp.cap);
        return vstr_o(s);
    }
    xfree(out.buf, out.cap);
    SB em; sb_init(&em);
    if (json_extract_string(resp.buf, "message", &em)) {
        char detail[220]; snprintf(detail, sizeof detail, ": %.200s", em.buf);
        xfree(em.buf, em.cap); xfree(resp.buf, resp.cap);
        vm_error("AI gave an unexpected reply%s", detail);
    }
    xfree(em.buf, em.cap); xfree(resp.buf, resp.cap);
    vm_error("AI gave an unexpected reply");
    return vnull();
#endif
}
static Value ai_invoke(OAI *self, int method, int argc, Value *args) {
    static const char *mn[] = {"open", "system", "ask"};
    if (argc != 1) vm_error("ai.%s needs 1 argument", mn[method]);
    OStr *s = vstr(args[0]);
    if (method == AIM_OPEN) { ai_open(self, s->chars); return vai_o(self); }
    if (method == AIM_SYSTEM) { self->system_prompt = s; return vai_o(self); }
    return ai_ask(self, s);
}
/* Member-access policy shared with the Python engines: underscore names are
 * private everywhere; only the ai object exposes members. */
static Value member_get(Value o, OStr *name) {
    if (name->len > 0 && name->chars[0] == '_')
        vm_error("member '%s' is private", name->chars);
    if (o.t == V_AI) {
        OAI *a = AS_AI(o);
        const char *nm = name->chars;
        if (strcmp(nm, "open") == 0)   return vbound_o(new_bound(a, AIM_OPEN));
        if (strcmp(nm, "system") == 0) return vbound_o(new_bound(a, AIM_SYSTEM));
        if (strcmp(nm, "ask") == 0)    return vbound_o(new_bound(a, AIM_ASK));
        if (strcmp(nm, "model") == 0)  return vstr_o(a->model);
        if (strcmp(nm, "provider") == 0)
            return vstr_o(a->provider == PROV_OPENAI
                          ? new_str("openai", 6) : new_str("groq", 4));
        if (strcmp(nm, "system_prompt") == 0)
            return a->system_prompt ? vstr_o(a->system_prompt) : vnull();
        vm_error("'ai' has no member '%s'", name->chars);
    }
    vm_error("object has no member '%s'", name->chars);
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
    if (r_u8() != 2) {
        fprintf(stderr, "[Vidyax] unsupported .vxc version "
                "(recompile with: vidyax bytecode <file.vx>)\n");
        exit(1);
    }
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
        p->nslots = r_u16();
        if (p->nslots < p->nparams) {
            fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1);
        }
        p->slot_names = xmalloc(sizeof(OStr *) * (p->nslots ? p->nslots : 1));
        for (int j = 0; j < p->nslots; j++) p->slot_names[j] = const_str(r_u32());
        p->nescp = r_u8();
        p->escp = xmalloc(p->nescp ? p->nescp : 1);
        for (int j = 0; j < p->nescp; j++) {
            p->escp[j] = r_u8();
            if (p->escp[j] >= p->nparams) {
                fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1);
            }
        }
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
    case OP_LIST: case OP_MAKE_FUNC: case OP_GET_MEMBER:
    case OP_LOAD_SLOT: case OP_STORE_SLOT: return 2;
    case OP_CALL: return 1;
    case OP_JMP: case OP_JMP_IF_FALSE: case OP_JIF_PEEK:
    case OP_JIT_PEEK: case OP_TRY_PUSH: return 4;
    case OP_NULL: case OP_TRUE: case OP_FALSE: case OP_POP:
    case OP_ADD: case OP_SUB: case OP_MUL: case OP_DIV: case OP_MOD:
    case OP_NEG: case OP_EQ: case OP_NE: case OP_LT: case OP_LE:
    case OP_GT: case OP_GE: case OP_NOT: case OP_INDEX: case OP_RET:
    case OP_PRINT: case OP_ASK: case OP_CHECK_RPT: case OP_CHECK_ITER:
    case OP_LEN: case OP_TRY_POP: case OP_HALT: case OP_AI_NEW: return 0;
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
            if (op == OP_CONST || op == OP_LOAD || op == OP_STORE ||
                op == OP_GET_MEMBER) {
                uint16_t ix; memcpy(&ix, p->code + i + 1, 2);
                if (ix >= nconsts) {
                    fprintf(stderr, "[Vidyax] verify: const %u out of "
                            "range in '%s'\n", ix, p->name->chars);
                    exit(1);
                }
                if ((op == OP_LOAD || op == OP_STORE ||
                     op == OP_GET_MEMBER) && consts[ix].t != V_STR) {
                    fprintf(stderr, "[Vidyax] verify: LOAD/STORE/GET_MEMBER "
                            "needs a name constant in '%s'\n", p->name->chars);
                    exit(1);
                }
            }
            if (op == OP_LOAD_SLOT || op == OP_STORE_SLOT) {
                uint16_t ix; memcpy(&ix, p->code + i + 1, 2);
                if (ix >= p->nslots) {
                    fprintf(stderr, "[Vidyax] verify: slot %u out of "
                            "range in '%s'\n", ix, p->name->chars);
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
    case O_AI: {
        OAI *a = (OAI *)o;
        mark_obj((Obj *)a->model);
        mark_obj((Obj *)a->system_prompt);
        break;
    }
    case O_BOUND:
        mark_obj((Obj *)((OBound *)o)->self);
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
    if (v.t == V_STR || v.t == V_LIST || v.t == V_FUNC ||
        v.t == V_AI || v.t == V_BOUND)
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
    case O_AI:
        mem_used -= sizeof(OAI);
        break;
    case O_BOUND:
        mem_used -= sizeof(OBound);
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
    frames[0].base = 0;
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
        case OP_LOAD_SLOT: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            Value v = stack[fr->base + ix];
            if (v.t == V_UNSET)   /* same rule, same words as the engines */
                vm_error("variable '%s' is assigned in this function "
                         "but used before it has a value",
                         fr->proto->slot_names[ix]->chars);
            push(v);
            break;
        }
        case OP_STORE_SLOT: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            stack[fr->base + ix] = pop();
            break;
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
            } else if (callee.t == V_BOUND) {
                OBound *bm = AS_BOUND(callee);
                Value r = ai_invoke(bm->self, bm->method, argc,
                                    &stack[sp - argc]);
                sp -= argc + 1;
                push(r);
            } else if (callee.t == V_FUNC) {
                OFunc *fn = AS_FUNC(callee);
                Proto *pr = fn->proto;
                if (argc != pr->nparams)
                    vm_error("function '%s' needs %d args, got %d",
                             pr->name->chars, pr->nparams, argc);
                if (nframes >= FRAMES_MAX) vm_error("recursion too deep");
                /* args become the first stack slots: shift them one
                   position down, over the callee value */
                int base = sp - argc - 1;
                memmove(&stack[base], &stack[base + 1],
                        (size_t)argc * sizeof(Value));
                sp = base + argc;
                for (int i = argc; i < pr->nslots; i++)
                    push(vunset());
                Env *env;
                if (pr->nescp > 0 || pr->ndecl > 0) {
                    /* something escapes -> it needs a heap home */
                    env = new_env(fn->closure, pr);
                    for (int k = 0; k < pr->nescp; k++) {
                        int pi = pr->escp[k];
                        env_set(env, pr->params[pi], stack[base + pi]);
                    }
                } else {
                    /* nothing escapes: NO allocation at all — the frame
                       reuses the closure env just for outward reads */
                    env = fn->closure;
                }
                frames[nframes].proto = pr;
                frames[nframes].ip = 0;
                frames[nframes].env = env;
                frames[nframes].base = base;
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
        case OP_AI_NEW:
            push(vai_o(new_ai()));
            break;
        case OP_GET_MEMBER: {
            uint16_t ix; memcpy(&ix, code + fr->ip, 2); fr->ip += 2;
            Value obj = pop();
            push(member_get(obj, AS_STR(consts[ix])));
            break;
        }
        case OP_RET: {
            /* drop try handlers opened in this frame (return inside try) */
            while (nhandlers > 0 && handlers[nhandlers - 1].frame == nframes - 1)
                nhandlers--;
            Value r = pop();
            sp = frames[nframes - 1].base;
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
#ifdef VX_HAVE_CURL
    curl_global_init(CURL_GLOBAL_DEFAULT);
#endif
    start_clock = clock();
    run();
#ifdef VX_HAVE_CURL
    curl_global_cleanup();
#endif
    return 0;
}
