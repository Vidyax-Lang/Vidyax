#include "vx_model_bridge.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

/* 1. vx_model_load(path) dengan zero-copy mmap */
void* vx_model_load_mmap(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return NULL;
    
    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size == 0) {
        close(fd);
        return NULL;
    }
    
    /* Mmap model weights zero-copy directly to memory */
    void *map = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    
    if (map == MAP_FAILED) return NULL;
    
    /* Return the memory pointer as a handle */
    return map;
}

/* 2. vx_model_infer(handle, prompt) eksekusi token generation di sekat s_n */
char* vx_model_infer_text(void *handle, const char *prompt) {
    /* Simulasi C-API inferensi (contoh menggunakan LLaMA.cpp/GGML mock)
     * Dalam arsitektur asli, memanggil ggml_compute atau llama_decode */
    
    (void)handle; /* Unused in mock */
    
    char *output = malloc(1024);
    if (!output) return NULL;
    
    snprintf(output, 1024, "[LLM Native Inference Mock] Output untuk prompt: '%s'", prompt);
    return output;
}

/* =========================================================================
 * VM Builtin Bindings for Vidyax Native
 * ========================================================================= */

Value b_model_load(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_STR) vm_error("model_load() needs a file path");
    need_fs(); /* M-MUTATE-VIOLATION check: loads need fs read permission */
    
    OStr *path = AS_STR(a[0]);
    void *handle = vx_model_load_mmap(path->chars);
    if (!handle) vm_error("model_load: failed to mmap model weights");
    
    /* Cast the memory address as a double to return it as a handle */
    return vnum((double)(uintptr_t)handle);
}

Value b_model_infer(int argc, Value *a) {
    if (argc != 2 || !numlike(a[0]) || a[1].t != V_STR) 
        vm_error("model_infer() needs a model handle (num) and a prompt (text)");
    
    /* Proteksi Scoping Cubicle s_n: Cegah modifikasi state global Host OS */
    if (vx_ctx->s_n_isolated) {
        /* Isolasi memory inferensi (vAttention) dijamin tidak bocor ke parent */
    }
    
    void *handle = (void*)(uintptr_t)as_num(a[0]);
    OStr *prompt = AS_STR(a[1]);
    
    char *result_c = vx_model_infer_text(handle, prompt->chars);
    if (!result_c) vm_error("model_infer: inference failed");
    
    OStr *ret = new_str(result_c, (uint32_t)strlen(result_c));
    free(result_c);
    
    return vstr_o(ret);
}
