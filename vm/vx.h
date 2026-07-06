/*
 * vx.h — shared types, globals, and cross-module API of the Vidyax VM.
 *
 * Modules:
 *   value.c    value constructors, env, number formatting, string builder,
 *              shared semantics (truthy/eq/cmp/add/index)
 *   gc.c       allocation accounting + mark-sweep GC (blueprint Bab 5)
 *   net.c      JSON + HTTP (libcurl) + the ai module
 *   builtins.c the builtin table (mirrors vidyax.py RUNTIME semantics)
 *   loader.c   .vxc loader + bytecode verifier (blueprint Bab 4)
 *   vm.c       globals, dispatch loop, CLI entry point
 */
#ifndef VX_H
#define VX_H

#include <ctype.h>
#include <errno.h>
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

#define AS_STR(v)  ((OStr *)(v).as.o)
#define AS_LIST(v) ((OList *)(v).as.o)
#define AS_FUNC(v) ((OFunc *)(v).as.o)
#define AS_AI(v)   ((OAI *)(v).as.o)
#define AS_BOUND(v) ((OBound *)(v).as.o)

/* ---- string builder ---- */
typedef struct { char *buf; size_t len, cap; } SB;

/* ---- execution state (defined in vm.c) ---- */
#define STACK_MAX   16384
#define FRAMES_MAX  1024
#define HANDLERS_MAX 256

typedef struct { Proto *proto; uint32_t ip; Env *env; int base; } Frame;
typedef struct { int frame; int sp; uint32_t catch_ip; } Handler;

extern Value  *consts;   extern uint32_t nconsts;
extern Proto  *protos;   extern uint32_t nprotos;
extern Obj    *all_objs;          /* GC allocation list */

extern Value   stack[STACK_MAX];   extern int sp;
extern Frame   frames[FRAMES_MAX]; extern int nframes;
extern Handler handlers[HANDLERS_MAX]; extern int nhandlers;
extern jmp_buf err_jmp;
extern char    errmsg[1024];
extern int     jmp_armed;

/* sandbox (blueprint Bab 4): 0 = unlimited */
extern uint64_t max_instr, instr_count;
extern size_t   max_mem,  mem_used;
extern double   max_secs; extern clock_t start_clock;
extern int      allow_net;  /* network (get/ai.ask) denied unless --allow-net */
extern int      allow_fs;   /* files (readfile/writefile) denied unless --allow-fs */

/* GC state (blueprint Bab 5) */
extern size_t   next_gc, peak_mem;
extern int      gc_pending, gc_stress, gc_stats;
extern uint64_t gc_runs;

/* ---- vm.c ---- */
#if defined(__GNUC__) || defined(__clang__)
#define VX_NORETURN __attribute__((noreturn))
#else
#define VX_NORETURN
#endif
VX_NORETURN void vm_error(const char *fmt, ...);

/* ---- gc.c ---- */
void *xmalloc(size_t n);
void *xrealloc(void *old, size_t oldn, size_t newn);
void  xfree(void *p, size_t n);
Obj  *alloc_obj(size_t size, OType t);
OStr *new_str(const char *chars, uint32_t len);
OList *new_list(uint32_t cap);
void  list_push(OList *l, Value v);
Env  *new_env(Env *parent, Proto *proto);
void  gc(void);

/* ---- value.c ---- */
Value vnull(void);
Value vunset(void);
Value vbool(int b);
Value vnum(double n);
Value vstr_o(OStr *s);
Value vlist_o(OList *l);
Value vai_o(OAI *a);
Value vbound_o(OBound *b);
void  env_set(Env *e, OStr *key, Value v);
Value env_get(Env *e, OStr *key);
void  fmt_double(double v, char *buf, size_t n);
void  sb_init(SB *sb);
void  sb_put(SB *sb, const char *s, size_t n);
void  sb_puts(SB *sb, const char *s);
void  vstr_into(SB *sb, Value v);
OStr *vstr(Value v);
int   truthy(Value v);
int   numlike(Value v);
double as_num(Value v);
const char *type_name(Value v);
int   values_eq(Value a, Value b);
int   values_cmp(Value a, Value b);
Value do_add(Value a, Value b);
Value do_index(Value o, Value iv);

/* ---- net.c ---- */
int   http_request(const char *url, const char *auth, const char *body,
                   SB *resp, long *code, char *err, size_t errcap);
OAI  *new_ai(void);
Value ai_invoke(OAI *self, int method, int argc, Value *args);
Value member_get(Value o, OStr *name);

/* ---- builtins.c ---- */
extern Builtin BUILTINS[];
extern const size_t NBUILTINS;

/* ---- loader.c ---- */
void load(const char *path);
void verify(void);

#endif /* VX_H */
