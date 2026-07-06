/*
 * profile.c — the VVM profiler (vxvm --profile prog.vxc).
 *
 * Deterministic: counts INSTRUCTIONS, not samples — the same program
 * always yields the same profile. Costs are attributed per function
 * (proto) and per .vx line via the format-v3 line table; a per-offset
 * cache makes the per-instruction hook O(1).
 *
 * The report goes to stderr after the program finishes, so stdout stays
 * clean. Profiler bookkeeping uses plain malloc on purpose: it must not
 * count against --max-mem or move the GC thresholds of the program
 * being measured.
 */
#include "vx.h"

int vx_profile = 0;

typedef struct {
    uint64_t  instr, calls;
    uint32_t *line_at;       /* code offset -> .vx line (cache) */
    uint64_t *line_count;    /* .vx line -> instruction count */
    uint32_t  maxline;
} PProto;

static PProto  *pp = NULL;
static uint32_t npp = 0;
static clock_t  prof_t0;

void prof_init(void) {
    npp = nprotos;
    pp = calloc(npp, sizeof(PProto));
    if (!pp) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    for (uint32_t i = 0; i < npp; i++) {
        Proto *p = &protos[i];
        pp[i].line_at = calloc(p->codelen ? p->codelen : 1, sizeof(uint32_t));
        if (!pp[i].line_at) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
        uint32_t line = 0, run = 0;
        for (uint32_t off = 0; off < p->codelen; off++) {
            while (run < p->nlines && p->line_off[run] <= off)
                line = p->line_no[run++];
            pp[i].line_at[off] = line;
            if (line > pp[i].maxline) pp[i].maxline = line;
        }
        pp[i].line_count = calloc(pp[i].maxline + 1, sizeof(uint64_t));
        if (!pp[i].line_count) { fprintf(stderr, "[Vidyax] out of memory\n"); exit(1); }
    }
    prof_t0 = clock();
}

void prof_instr(const Proto *p, uint32_t ip) {
    PProto *q = &pp[p - protos];
    q->instr++;
    if (ip < p->codelen) q->line_count[q->line_at[ip]]++;
}

void prof_call(const Proto *p) {
    pp[p - protos].calls++;
}

typedef struct { uint32_t proto, line; uint64_t n; } HotLine;

void prof_report(void) {
    double secs = (double)(clock() - prof_t0) / CLOCKS_PER_SEC;
    uint64_t total = 0;
    for (uint32_t i = 0; i < npp; i++) total += pp[i].instr;
    fprintf(stderr, "\n== Vidyax profile ==\n");
    fprintf(stderr, "total: %llu instr in %.3fs cpu",
            (unsigned long long)total, secs);
    if (secs > 0)
        fprintf(stderr, " (%.1f M instr/s)", (double)total / secs / 1e6);
    fprintf(stderr, "\n\nper function:\n");

    /* protos sorted by instruction count (selection: nprotos is small) */
    for (uint32_t shown = 0; shown < npp; shown++) {
        uint32_t best = npp; uint64_t bn = 0;
        for (uint32_t i = 0; i < npp; i++) {
            if (pp[i].instr == (uint64_t)-1) continue;   /* already shown */
            if (best == npp || pp[i].instr > bn) { best = i; bn = pp[i].instr; }
        }
        if (best == npp || bn == 0) break;
        fprintf(stderr, "  %-16s calls %-8llu instr %-12llu (%.1f%%)\n",
                protos[best].name->chars,
                (unsigned long long)pp[best].calls,
                (unsigned long long)bn,
                total ? 100.0 * (double)bn / (double)total : 0.0);
        pp[best].instr = (uint64_t)-1;
    }

    /* top-10 hot lines across every proto */
    fprintf(stderr, "\nhot lines:\n");
    HotLine top[10] = {{0, 0, 0}};
    for (uint32_t i = 0; i < npp; i++)
        for (uint32_t l = 0; l <= pp[i].maxline; l++) {
            uint64_t n = pp[i].line_count[l];
            if (n == 0) continue;
            for (int k = 0; k < 10; k++)
                if (n > top[k].n) {
                    memmove(top + k + 1, top + k, (9 - k) * sizeof top[0]);
                    top[k].proto = i; top[k].line = l; top[k].n = n;
                    break;
                }
        }
    for (int k = 0; k < 10 && top[k].n; k++)
        fprintf(stderr, "  line %-4u in %-16s %-12llu (%.1f%%)\n",
                top[k].line, protos[top[k].proto].name->chars,
                (unsigned long long)top[k].n,
                total ? 100.0 * (double)top[k].n / (double)total : 0.0);
}
