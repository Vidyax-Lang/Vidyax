#include "vx.h"

/* allocation + mark-sweep GC (blueprint Bab 5) */
/* ---- allocation ---- */
/* byte accounting is ATOMIC: raw buffers (e.g. the HTTP body builder)
 * may grow while the interpreter lock is released. GC objects
 * themselves are only ever created while HOLDING the lock. */
void *xmalloc(size_t n) {
    void *p = malloc(n);
    if (!p) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    size_t used = __atomic_add_fetch(&mem_used, n, __ATOMIC_RELAXED);
    if (max_mem && used > max_mem)
        vm_error("VM PANIC: memory limit exceeded (%zu bytes)", max_mem);
    return p;
}
void *xrealloc(void *old, size_t oldn, size_t newn) {
    void *p = realloc(old, newn);
    if (!p) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    size_t used = __atomic_add_fetch(&mem_used, newn - oldn, __ATOMIC_RELAXED);
    if (max_mem && used > max_mem)
        vm_error("VM PANIC: memory limit exceeded (%zu bytes)", max_mem);
    return p;
}
void xfree(void *p, size_t n) {
    free(p);
    __atomic_sub_fetch(&mem_used, n, __ATOMIC_RELAXED);
}
Obj *alloc_obj(size_t size, OType t) {
    Obj *o = xmalloc(size);
    o->type = t; o->mark = 0;
    o->next = all_objs; all_objs = o;
    if (mem_used > peak_mem) peak_mem = mem_used;
    if (mem_used > next_gc) gc_pending = 1;   /* collect at next safepoint */
    return o;
}
OStr *new_str(const char *chars, uint32_t len) {
    OStr *s = (OStr *)alloc_obj(sizeof(OStr), O_STR);
    s->len = len;
    s->chars = xmalloc((size_t)len + 1);
    memcpy(s->chars, chars, len); s->chars[len] = 0;
    return s;
}
OList *new_list(uint32_t cap) {
    OList *l = (OList *)alloc_obj(sizeof(OList), O_LIST);
    l->count = 0; l->cap = cap ? cap : 4;
    l->items = xmalloc(sizeof(Value) * l->cap);
    return l;
}
void list_push(OList *l, Value v) {
    if (l->count == l->cap) {
        l->items = xrealloc(l->items, sizeof(Value) * l->cap,
                            sizeof(Value) * l->cap * 2);
        l->cap *= 2;
    }
    l->items[l->count++] = v;
}
Env *new_env(Env *parent, Proto *proto) {
    Env *e = (Env *)alloc_obj(sizeof(Env), O_ENV);
    e->parent = parent; e->proto = proto;
    e->count = 0; e->cap = 8;
    e->entries = xmalloc(sizeof(EnvEntry) * e->cap);
    return e;
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
    case O_TASK: {
        OTask *t = (OTask *)o;
        mark_obj((Obj *)t->name);
        mark_value(t->result);
        break;
    }
    case O_AGENT: {
        OAgent *a = (OAgent *)o;
        mark_obj((Obj *)a->name);
        mark_obj((Obj *)a->ai);
        mark_obj((Obj *)a->history);
        break;
    }
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
        v.t == V_AI || v.t == V_BOUND || v.t == V_TASK)
        mark_obj(v.as.o);
}
static void free_obj(Obj *o) {   /* mirrors every byte alloc counted */
    switch (o->type) {
    case O_STR: {
        OStr *s = (OStr *)o;
        __atomic_sub_fetch(&mem_used, sizeof(OStr) + s->len + 1, __ATOMIC_RELAXED);
        free(s->chars);
        break;
    }
    case O_LIST: {
        OList *l = (OList *)o;
        __atomic_sub_fetch(&mem_used, sizeof(OList) + l->cap * sizeof(Value), __ATOMIC_RELAXED);
        free(l->items);
        break;
    }
    case O_FUNC:
        __atomic_sub_fetch(&mem_used, sizeof(OFunc), __ATOMIC_RELAXED);
        break;
    case O_AI:
        __atomic_sub_fetch(&mem_used, sizeof(OAI), __ATOMIC_RELAXED);
        break;
    case O_BOUND:
        __atomic_sub_fetch(&mem_used, sizeof(OBound), __ATOMIC_RELAXED);
        break;
    case O_AGENT:
        __atomic_sub_fetch(&mem_used, sizeof(OAgent), __ATOMIC_RELAXED);
        break;
    case O_TASK: {   /* only ever swept after it was joined */
        OTask *t = (OTask *)o;
        __atomic_sub_fetch(&mem_used, sizeof(OTask), __ATOMIC_RELAXED);
        free(t->ctx);        /* plain calloc — outside the accounting */
        free(t->errtext);
        break;
    }
    case O_ENV: {
        Env *e = (Env *)o;
        __atomic_sub_fetch(&mem_used, sizeof(Env) + e->cap * sizeof(EnvEntry), __ATOMIC_RELAXED);
        free(e->entries);
        break;
    }
    }
    free(o);
}
void gc(void) {
    gc_pending = 0;
    for (uint32_t i = 0; i < nconsts; i++) mark_value(consts[i]);
    /* roots: EVERY execution context (main + all tasks), frozen while we
     * hold the interpreter lock */
    for (VmCtx *c = vx_all_ctxs; c; c = c->next) {
        for (int i = 0; i < c->x_sp; i++) mark_value(c->x_stack[i]);
        for (int f = 0; f < c->x_nframes; f++)
            mark_obj((Obj *)c->x_frames[f].env);
    }
    {   /* live tasks are roots too (handle may have been dropped) */
        int nt; OTask **ts = vx_live_tasks(&nt);
        for (int i = 0; i < nt; i++) mark_obj((Obj *)ts[i]);
    }
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

