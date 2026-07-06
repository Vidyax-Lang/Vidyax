#ifdef VX_HAVE_CURL
#include <curl/curl.h>
#endif
#include "vx.h"

/* ---- globals (declared extern in vx.h) ---- */
Value  *consts;   uint32_t nconsts;
Proto  *protos;   uint32_t nprotos;
Obj    *all_objs = NULL;   /* GC-ready allocation list */

/* execution contexts: the main program owns one; every task adds one */
static VmCtx main_ctx;
_Thread_local VmCtx *vx_ctx = NULL;
VmCtx *vx_all_ctxs = NULL;
pthread_mutex_t vx_gil = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t  vx_task_done = PTHREAD_COND_INITIALIZER;

void vx_register_ctx(VmCtx *c) {
    c->next = vx_all_ctxs;
    vx_all_ctxs = c;
}

/* ---- sandbox (blueprint Bab 4): 0 = unlimited ---- */
uint64_t max_instr = 0, instr_count = 0;
size_t   max_mem = 0,  mem_used = 0;
double   max_secs = 0; clock_t start_clock;
int      allow_net = 0;   /* network (get/ai.ask) denied unless --allow-net */
int      allow_fs  = 0;   /* file access (readfile/writefile) denied unless --allow-fs */

/* ---- GC (blueprint Bab 5): mark-sweep at safepoints ---- */
size_t   next_gc = 1u << 20;   /* first collection at 1 MB */
int      gc_pending = 0, gc_stress = 0, gc_stats = 0;
uint64_t gc_runs = 0;
size_t   peak_mem = 0;

/* ---- error (errmsg/jmp are per-ctx via the vx.h macros) ---- */
void vm_error(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    vsnprintf(errmsg, sizeof errmsg, fmt, ap);
    va_end(ap);
    if (!jmp_armed) { fprintf(stderr, "[Vidyax] %s\n", errmsg); exit(1); }
    longjmp(err_jmp, 1);
}
/* ---- VM ---- */
static void push(Value v) {
    if (sp >= STACK_MAX) vm_error("stack overflow");
    stack[sp++] = v;
}
static Value pop(void) { return stack[--sp]; }

static void bytecode_task_runner(OTask *t) {
    vx_run_loop();               /* runs until the entry frame RETs */
    if (!vx_ctx->failed)
        t->result = stack[sp - 1];
}

static void run(void) {
    vx_task_runner = bytecode_task_runner;
    vx_ctx = &main_ctx;
    vx_register_ctx(&main_ctx);
    Env *global = new_env(NULL, NULL);
    /* register only the builtins the program can actually name */
    for (size_t b = 0; b < NBUILTINS; b++)
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
    /* main's slots (top-level escape analysis) live at the stack bottom */
    for (int i = 0; i < protos[0].nslots; i++)
        push(vunset());
    nframes = 1;
    vx_run_loop();
}

/* The dispatch loop. Also the execution engine for tasks: task.c gives a
 * child ctx one call frame and runs this until that frame returns
 * (nframes hits 0). Uncaught errors kill the process only on the main
 * ctx; a task ctx records the failure and returns to its worker. */
void vx_run_loop(void) {
    jmp_armed = 1;
    if (setjmp(err_jmp)) {
        /* runtime error: unwind to the innermost try handler, or die */
        if (nhandlers > 0) {
            Handler h = handlers[--nhandlers];
            nframes = h.frame + 1;
            sp = h.saved_sp;
            frames[nframes - 1].ip = h.catch_ip;
            push(vstr_o(new_str(errmsg, (uint32_t)strlen(errmsg))));
        } else if (vx_ctx->is_task) {
            vx_ctx->failed = 1;   /* errmsg already holds the text */
            return;
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
        if (vx_debug) debug_hook();
        if (vx_profile) prof_instr(frames[nframes - 1].proto,
                                   frames[nframes - 1].ip);
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
            if (v.t == V_UNSET) {  /* same rule, same words as the engines */
                if (fr == &frames[0])   /* top level says "not defined" */
                    vm_error("variable '%s' is not defined",
                             fr->proto->slot_names[ix]->chars);
                vm_error("variable '%s' is assigned in this function "
                         "but used before it has a value",
                         fr->proto->slot_names[ix]->chars);
            }
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
                if (vx_profile) prof_call(pr);
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
            if (nframes == 0)
                return;   /* a task's entry call returned: result on top */
            break;
        }
        case OP_GO: {
            uint8_t argc = code[fr->ip++];
            task_spawn(argc);
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
            ssize_t n;
            VX_BLOCKING(n = getline(&line, &cap, stdin));
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
            handlers[nhandlers].saved_sp = sp;
            handlers[nhandlers].catch_ip = t;
            nhandlers++;
            break;
        }
        case OP_TRY_POP:
            nhandlers--;
            break;
        case OP_HALT:
            tasks_finish();   /* join every task; report unwaited errors */
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
        else if (strcmp(argv[i], "--allow-net") == 0)
            allow_net = 1;   /* opt in to network for get() / ai.ask */
        else if (strcmp(argv[i], "--allow-fs") == 0)
            allow_fs = 1;    /* opt in to files for readfile() / writefile() */
        else if (strcmp(argv[i], "--debug") == 0)
            vx_debug = 1;    /* interactive line debugger (see debug.c) */
        else if (strcmp(argv[i], "--profile") == 0)
            vx_profile = 1;  /* per-line instruction profile (profile.c) */
        else if (strcmp(argv[i], "--gc-stress") == 0)
            gc_stress = 1;   /* collect at EVERY safepoint (testing) */
        else if (strcmp(argv[i], "--gc-stats") == 0)
            gc_stats = 1;
        else if (argv[i][0] != '-')
            path = argv[i];
        else {
            fprintf(stderr, "usage: vxvm [--max-instr N] [--max-mem BYTES]"
                    " [--max-time SECS] [--allow-net] [--allow-fs]"
                    " <program.vxc>\n");
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
    if (vx_profile) prof_init();
#ifdef VX_HAVE_CURL
    curl_global_init(CURL_GLOBAL_DEFAULT);
#endif
    VX_LOCK();          /* the interpreter lock; I/O builtins release it */
    start_clock = clock();
    run();
    VX_UNLOCK();
#ifdef VX_HAVE_CURL
    curl_global_cleanup();
#endif
    if (vx_profile) prof_report();
    return 0;
}
