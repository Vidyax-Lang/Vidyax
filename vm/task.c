/*
 * task.c — `go` / wait on the VVM (docs/CONCURRENCY.md, Phase C).
 *
 * A task owns a full VmCtx (its own stack + frames) and one pthread.
 * Execution follows the design's GIL model: vx_gil serializes all
 * bytecode; only blocking builtins release it. So the GC — which runs
 * at safepoints while HOLDING the lock — sees every other context
 * frozen, and simply marks all of them via the vx_all_ctxs registry.
 *
 * Lifetime: a running task is pinned in the `live` list (a GC root) so
 * dropping the handle can't free a task mid-flight. HALT calls
 * tasks_finish(): every task is joined, and a failed task that nobody
 * waited for is reported like any uncaught error.
 */
#include "vx.h"

int vx_tasks_live = 0;

#define MAX_TASKS 256
static OTask *live[MAX_TASKS];
static int    nlive = 0;

/* mark helper for gc.c: every live task + its ctx's stack/frames */
OTask **vx_live_tasks(int *n) { *n = nlive; return live; }

static void *task_worker(void *arg) {
    OTask *t = (OTask *)arg;
    VX_LOCK();
    vx_ctx = t->ctx;
    if (t->ctx->x_nframes > 0) {
        vx_run_loop();               /* function task: run until RET */
        if (!t->ctx->failed)
            t->result = t->ctx->x_stack[t->ctx->x_sp - 1];
    } else {
        /* builtin/bound task: one direct call under the lock (the
         * builtin itself releases it around its blocking syscall) */
        jmp_armed = 1;
        if (setjmp(err_jmp) == 0) {
            Value callee = t->ctx->x_stack[0];
            int argc = t->ctx->x_sp - 1;
            if (callee.t == V_BUILTIN)
                t->result = ((Builtin *)callee.as.o)
                                ->fn(argc, &t->ctx->x_stack[1]);
            else   /* V_BOUND (ai.ask) — checked at spawn */
                t->result = ai_invoke(AS_BOUND(callee)->self,
                                      AS_BOUND(callee)->method,
                                      argc, &t->ctx->x_stack[1]);
        } else {
            t->ctx->failed = 1;
        }
    }
    if (t->ctx->failed)
        t->errtext = strdup(t->ctx->x_errmsg);
    t->done = 1;
    pthread_cond_broadcast(&vx_task_done);
    VX_UNLOCK();
    return NULL;
}

/* OP_GO: stack holds callee + argc args (like OP_CALL). Pops them,
 * pushes the task value. Runs on the SPAWNING thread, lock held. */
void task_spawn(int argc) {
    Value callee = stack[sp - argc - 1];
    if (callee.t != V_FUNC && callee.t != V_BUILTIN && callee.t != V_BOUND)
        vm_error("this is not a function");
    if (callee.t == V_FUNC && argc != AS_FUNC(callee)->proto->nparams)
        vm_error("function '%s' needs %d args, got %d",
                 AS_FUNC(callee)->proto->name->chars,
                 AS_FUNC(callee)->proto->nparams, argc);
    if (nlive >= MAX_TASKS) vm_error("too many tasks");

    OTask *t = (OTask *)alloc_obj(sizeof(OTask), O_TASK);
    if (callee.t == V_FUNC)
        t->name = AS_FUNC(callee)->proto->name;
    else if (callee.t == V_BUILTIN) {
        const char *bn = ((Builtin *)callee.as.o)->name;
        t->name = new_str(bn, (uint32_t)strlen(bn));
    } else
        t->name = NULL;   /* bound methods print as <task task> */
    t->started = t->done = t->waited = t->joined = 0;
    t->result = vnull();
    t->errtext = NULL;
    t->ctx = calloc(1, sizeof(VmCtx));
    if (!t->ctx) vm_error("out of memory");
    t->ctx->is_task = 1;

    /* move callee+args into the child ctx's stack */
    memcpy(t->ctx->x_stack, &stack[sp - argc - 1],
           (size_t)(argc + 1) * sizeof(Value));
    t->ctx->x_sp = argc + 1;
    sp -= argc + 1;

    if (callee.t == V_FUNC) {
        /* build the callee frame exactly like OP_CALL does */
        OFunc *fn = (OFunc *)callee.as.o;
        Proto *pr = fn->proto;
        VmCtx *c = t->ctx;
        memmove(&c->x_stack[0], &c->x_stack[1], (size_t)argc * sizeof(Value));
        c->x_sp = argc;
        for (int i = argc; i < pr->nslots; i++) {
            c->x_stack[c->x_sp].t = V_UNSET; c->x_stack[c->x_sp].as.o = NULL;
            c->x_sp++;
        }
        Env *env;
        if (pr->nescp > 0 || pr->ndecl > 0) {
            env = new_env(fn->closure, pr);
            for (int k = 0; k < pr->nescp; k++) {
                int pi = pr->escp[k];
                env_set(env, pr->params[pi], c->x_stack[pi]);
            }
        } else env = fn->closure;
        c->x_frames[0].proto = pr;
        c->x_frames[0].ip = 0;
        c->x_frames[0].env = env;
        c->x_frames[0].base = 0;
        c->x_nframes = 1;
    }
    /* builtin/bound: worker calls it directly from stack[0..argc] */

    live[nlive++] = t;
    vx_tasks_live++;
    vx_register_ctx(t->ctx);

    Value v; v.t = V_TASK; v.as.o = (Obj *)t;
    stack[sp++] = v;   /* always fits: we just freed argc+1 slots */

    t->started = 1;
    if (pthread_create(&t->thread, NULL, task_worker, t) != 0) {
        t->started = 0;
        vm_error("cannot start task");
    }
}

static void unlive(OTask *t) {
    for (int i = 0; i < nlive; i++)
        if (live[i] == t) { live[i] = live[--nlive]; vx_tasks_live--; break; }
}

static void join_task(OTask *t) {
    while (!t->done)
        pthread_cond_wait(&vx_task_done, &vx_gil);   /* releases the GIL */
    if (!t->joined) {
        VX_BLOCKING(pthread_join(t->thread, NULL));
        t->joined = 1;
        unlive(t);
    }
}

Value b_wait(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_TASK)
        vm_error("wait() needs a task (made with 'go')");
    OTask *t = AS_TASK(a[0]);
    t->waited = 1;
    join_task(t);
    if (t->errtext) vm_error("%s", t->errtext);
    return t->result;
}

void tasks_finish(void) {
    while (nlive > 0) {
        OTask *t = live[0];
        join_task(t);
        if (t->errtext && !t->waited)
            vm_error("task '%s' failed: %s",
                     t->name ? t->name->chars : "task", t->errtext);
    }
}
