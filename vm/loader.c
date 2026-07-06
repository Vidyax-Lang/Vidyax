#include "vx.h"

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

void load(const char *path) {
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
    if (r_u8() != 3) {
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
        p->nlines = r_u32();
        p->line_off = xmalloc(sizeof(uint32_t) * (p->nlines ? p->nlines : 1));
        p->line_no  = xmalloc(sizeof(uint32_t) * (p->nlines ? p->nlines : 1));
        for (uint32_t j = 0; j < p->nlines; j++) {
            p->line_off[j] = r_u32();
            p->line_no[j]  = r_u32();
            if (j > 0 && p->line_off[j] < p->line_off[j - 1]) {
                fprintf(stderr, "[Vidyax] corrupt .vxc file\n"); exit(1);
            }
        }
    }
}

/* .vx line for a code offset: last run starting at or before ip (0 = unknown) */
uint32_t line_for(const Proto *p, uint32_t ip) {
    uint32_t line = 0;
    for (uint32_t j = 0; j < p->nlines && p->line_off[j] <= ip; j++)
        line = p->line_no[j];
    return line;
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
    case OP_CALL: case OP_GO: case OP_SBOX_ENTER: return 1;
    case OP_JMP: case OP_JMP_IF_FALSE: case OP_JIF_PEEK:
    case OP_JIT_PEEK: case OP_TRY_PUSH: return 4;
    case OP_NULL: case OP_TRUE: case OP_FALSE: case OP_POP:
    case OP_ADD: case OP_SUB: case OP_MUL: case OP_DIV: case OP_MOD:
    case OP_NEG: case OP_EQ: case OP_NE: case OP_LT: case OP_LE:
    case OP_GT: case OP_GE: case OP_NOT: case OP_INDEX: case OP_RET:
    case OP_PRINT: case OP_ASK: case OP_CHECK_RPT: case OP_CHECK_ITER:
    case OP_LEN: case OP_TRY_POP: case OP_HALT: case OP_AI_NEW:
    case OP_AGENT: case OP_SBOX_EXIT: return 0;
    default: return -1;
    }
}
void verify(void) {
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

