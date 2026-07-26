
#include <emscripten.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>


extern int vx_run_program(const char *vxc_path,
                           uint64_t max_instr_limit, double max_secs_limit,
                           int net_allowed, int fs_allowed);

static const char *WASM_VXC_PATH = "/tmp/playground.vxc";

EMSCRIPTEN_KEEPALIVE
int run_from_js(const uint8_t *bytecode, int len,
                 int allow_net_flag, int allow_fs_flag) {
    if (bytecode == NULL || len <= 0) {
        fprintf(stderr, "[vidyax-wasm] Error: bytecode kosong.\n");
        return 70;
    }

    FILE *f = fopen(WASM_VXC_PATH, "wb");
    if (!f) {
        fprintf(stderr, "[vidyax-wasm] Error: gagal menulis ke MEMFS.\n");
        return 74;
    }
    fwrite(bytecode, 1, (size_t)len, f);
    fclose(f);

    return vx_run_program(WASM_VXC_PATH,
                           /*max_instr=*/50000000ULL, /*max_secs=*/5.0,
                           allow_net_flag, allow_fs_flag);
}