#include "vx.h"

/* ---- value constructors ---- */
Value vnull(void) { Value v; v.t = V_NULL; v.as.o = NULL; return v; }
Value vunset(void) { Value v; v.t = V_UNSET; v.as.o = NULL; return v; }
Value vbool(int b) { Value v; v.t = V_BOOL; v.as.b = !!b; return v; }
Value vnum(double n) { Value v; v.t = V_NUM; v.as.n = n; return v; }
Value vstr_o(OStr *s) { Value v; v.t = V_STR; v.as.o = (Obj *)s; return v; }
Value vlist_o(OList *l) { Value v; v.t = V_LIST; v.as.o = (Obj *)l; return v; }
Value vai_o(OAI *a) { Value v; v.t = V_AI; v.as.o = (Obj *)a; return v; }
Value vbound_o(OBound *b) { Value v; v.t = V_BOUND; v.as.o = (Obj *)b; return v; }
#define AS_STR(v)  ((OStr *)(v).as.o)
#define AS_LIST(v) ((OList *)(v).as.o)
#define AS_FUNC(v) ((OFunc *)(v).as.o)
#define AS_AI(v)   ((OAI *)(v).as.o)
#define AS_BOUND(v) ((OBound *)(v).as.o)

/* ---- environment (keys compared by pointer: const pool is deduped) ---- */
void env_set(Env *e, OStr *key, Value v) {
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
Value env_get(Env *e, OStr *key) {
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
void fmt_double(double v, char *buf, size_t n) {
    if (v != v) { snprintf(buf, n, "nan"); return; }
    if (isinf(v)) { snprintf(buf, n, v < 0 ? "-inf" : "inf"); return; }
    if (v == floor(v)) { snprintf(buf, n, "%.0f", v); return; }
    for (int prec = 1; prec <= 17; prec++) {
        snprintf(buf, n, "%.*g", prec, v);
        if (strtod(buf, NULL) == v) return;
    }
}

/* ---- string builder (SB typedef in vx.h) ---- */
void sb_init(SB *sb) { sb->cap = 64; sb->len = 0; sb->buf = xmalloc(64); }
void sb_put(SB *sb, const char *s, size_t n) {
    if (sb->len + n + 1 > sb->cap) {
        size_t old = sb->cap;
        while (sb->len + n + 1 > sb->cap) sb->cap *= 2;
        sb->buf = xrealloc(sb->buf, old, sb->cap);
    }
    memcpy(sb->buf + sb->len, s, n); sb->len += n; sb->buf[sb->len] = 0;
}
void sb_puts(SB *sb, const char *s) { sb_put(sb, s, strlen(s)); }

void vstr_into(SB *sb, Value v) {
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
OStr *vstr(Value v) {
    if (v.t == V_STR) return AS_STR(v);
    SB sb; sb_init(&sb);
    vstr_into(&sb, v);
    OStr *s = new_str(sb.buf, (uint32_t)sb.len);
    xfree(sb.buf, sb.cap);
    return s;
}

/* ---- semantics helpers ---- */
int truthy(Value v) {
    switch (v.t) {
    case V_NULL: return 0;
    case V_BOOL: return v.as.b;
    case V_NUM:  return v.as.n != 0;
    case V_STR:  return AS_STR(v)->len > 0;
    case V_LIST: return AS_LIST(v)->count > 0;
    default:     return 1;
    }
}
int numlike(Value v) { return v.t == V_NUM || v.t == V_BOOL; }
double as_num(Value v) { return v.t == V_BOOL ? (double)v.as.b : v.as.n; }
const char *type_name(Value v) {
    switch (v.t) {
    case V_BOOL: return "bool";  case V_NUM:  return "number";
    case V_STR:  return "text";  case V_LIST: return "list";
    case V_NULL: return "null";  default:     return "object";
    }
}
int values_eq(Value a, Value b) {
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
int values_cmp(Value a, Value b) {
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
Value do_add(Value a, Value b) {
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
Value do_index(Value o, Value iv) {
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

