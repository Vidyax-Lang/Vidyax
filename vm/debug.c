/*
 * debug.c — the interactive VVM debugger (vxvm --debug prog.vxc).
 *
 * Line-level: the compiler's line table (format v3) maps bytecode back
 * to .vx lines. The dispatch loop calls debug_hook() before every
 * instruction; we only act when execution reaches a NEW source line.
 *
 * Commands (prompt/output on stderr, so program output stays clean):
 *   b N      set a breakpoint on .vx line N       d N   delete it
 *   c        continue                             s     step (into calls)
 *   n        next (step over calls)               bt    backtrace
 *   locals   current frame's variables            stack top of operand stack
 *   q        quit                                 h     help
 *
 * Known limit: the prompt reads stdin, so programs that use `ask` share
 * the same input stream — type the program's answer at its own prompt.
 */
#include "vx.h"

int vx_debug = 0;

#define MAX_BP 64
static uint32_t bps[MAX_BP];
static int nbps = 0;
static int step_mode = 1;        /* start paused on the first line */
static int step_depth = 0;       /* frame depth for 'n' (step over) */
static uint32_t last_line = 0;
static const Proto *last_proto = NULL;

static void print_value(Value v) {
    SB sb; sb_init(&sb);
    vstr_into(&sb, v);
    fprintf(stderr, "%s", sb.buf);
    xfree(sb.buf, sb.cap);
}

static void cmd_bt(void) {
    for (int i = nframes - 1; i >= 0; i--) {
        Frame *f = &frames[i];
        fprintf(stderr, "  #%d %s (line %u)\n", nframes - 1 - i,
                f->proto->name->chars, line_for(f->proto, f->ip));
    }
}

static void cmd_locals(Frame *fr) {
    int shown = 0;
    for (int j = 0; j < fr->proto->nslots; j++) {
        Value v = stack[fr->base + j];
        if (fr->proto->slot_names[j]->chars[0] == '$') continue;  /* hidden */
        fprintf(stderr, "  %s = ", fr->proto->slot_names[j]->chars);
        if (v.t == V_UNSET) fprintf(stderr, "<unset>");
        else print_value(v);
        fprintf(stderr, "\n");
        shown++;
    }
    /* env entries: only the frame's OWN scope — the global frame's env,
     * or a function env created for escaping locals. A function whose
     * env just points at its closure would otherwise list globals here. */
    if (fr->env && (fr->proto == &protos[0] || fr->env->proto == fr->proto)) {
        for (uint32_t j = 0; j < fr->env->count; j++) {
            Value v = fr->env->entries[j].v;
            if (v.t == V_BUILTIN) continue;   /* skip the builtin bindings */
            if (fr->env->entries[j].key->chars[0] == '$') continue;
            fprintf(stderr, "  %s = ", fr->env->entries[j].key->chars);
            print_value(v);
            fprintf(stderr, "\n");
            shown++;
        }
    }
    if (!shown) fprintf(stderr, "  (no variables yet)\n");
}

static void cmd_stack(Frame *fr) {
    int lo = fr->base + fr->proto->nslots;   /* below this = slots/frames */
    if (sp == lo) { fprintf(stderr, "  (operand stack empty)\n"); return; }
    for (int i = sp - 1; i >= lo && i >= sp - 8; i--) {
        fprintf(stderr, "  [%d] ", i - lo);
        print_value(stack[i]);
        fprintf(stderr, "\n");
    }
}

static void help(void) {
    fprintf(stderr,
        "  b N     breakpoint on line N     d N     delete breakpoint\n"
        "  c       continue                 s       step (into calls)\n"
        "  n       next (over calls)        bt      backtrace\n"
        "  locals  variables in this frame  stack   operand stack\n"
        "  q       quit                     h       this help\n");
}

static void prompt(Frame *fr, uint32_t line) {
    fprintf(stderr, "[vxdbg] line %u in %s\n", line, fr->proto->name->chars);
    char buf[128];
    for (;;) {
        fprintf(stderr, "(vxdbg) ");
        fflush(stderr);
        if (!fgets(buf, sizeof buf, stdin)) {   /* EOF: run to completion */
            fprintf(stderr, "\n");
            vx_debug = 0;
            return;
        }
        unsigned n;
        if (buf[0] == 'q') exit(0);
        if (buf[0] == 'c') return;
        if (buf[0] == 's') { step_mode = 1; return; }
        if (buf[0] == 'n') { step_mode = 2; step_depth = nframes; return; }
        if (sscanf(buf, "b %u", &n) == 1) {
            if (nbps < MAX_BP) {
                bps[nbps++] = n;
                fprintf(stderr, "  breakpoint at line %u\n", n);
            } else fprintf(stderr, "  too many breakpoints\n");
        } else if (sscanf(buf, "d %u", &n) == 1) {
            for (int i = 0; i < nbps; i++)
                if (bps[i] == n) { bps[i] = bps[--nbps]; break; }
            fprintf(stderr, "  breakpoint at line %u removed\n", n);
        } else if (strncmp(buf, "bt", 2) == 0) {
            cmd_bt();
        } else if (strncmp(buf, "locals", 6) == 0) {
            cmd_locals(fr);
        } else if (strncmp(buf, "stack", 5) == 0) {
            cmd_stack(fr);
        } else if (buf[0] == 'h' || buf[0] == '?') {
            help();
        } else if (buf[0] != '\n') {
            fprintf(stderr, "  unknown command (h = help)\n");
        }
    }
}

void debug_hook(void) {
    Frame *fr = &frames[nframes - 1];
    uint32_t line = line_for(fr->proto, fr->ip);
    if (line == 0) return;                       /* no line info here */
    if (line == last_line && fr->proto == last_proto) return;
    last_line = line;
    last_proto = fr->proto;

    int stop = 0;
    if (step_mode == 1) stop = 1;
    else if (step_mode == 2 && nframes <= step_depth) stop = 1;
    for (int i = 0; i < nbps && !stop; i++)
        if (bps[i] == line) stop = 1;
    if (!stop) return;
    step_mode = 0;
    prompt(fr, line);
}
