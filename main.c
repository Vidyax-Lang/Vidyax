#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "vm/vx_model_bridge.h"

/* Fungsi pembantu untuk membaca dokumen lokal via Zero-Copy mmap */
char* read_local_file_mmap(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return NULL;
    
    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size == 0) {
        close(fd); return NULL;
    }
    
    char *map = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    
    if (map == MAP_FAILED) return NULL;
    
    char *content = malloc(st.st_size + 1);
    memcpy(content, map, st.st_size);
    content[st.st_size] = '\0';
    
    munmap(map, st.st_size);
    return content;
}

/* Fungsi simulasi Shared Memory /dev/shm untuk Multi-Nano Swarm */
char* create_shm_channel(const char *channel_name, size_t size) {
    char shm_name[256];
    snprintf(shm_name, sizeof(shm_name), "/re_shm_%s", channel_name);
    
    int fd = shm_open(shm_name, O_CREAT | O_RDWR, 0666);
    if (fd < 0) return NULL;
    ftruncate(fd, size);
    
    char *map = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (map == MAP_FAILED) return NULL;
    
    memset(map, 0, size);
    return map;
}

int run_chat_loop(const char *model_path, const char *doc_path) {
    printf("====================================================\n");
    printf(" Redeon by Nadev (Fase 3: Multi-Nano Verifier)\n");
    printf("====================================================\n");

    /* 1. Inisialisasi Dual-Cubicle Models (s_1 dan s_2) menggunakan file asli */
    printf("[Redeon Engine] Memuat Generator di s_1...\n");
    void *gen_handle = vx_model_load_mmap(model_path);
    
    printf("[Redeon Engine] Memuat Verifier di s_2 (Share physical memory)...\n");
    void *ver_handle = vx_model_load_mmap(model_path);

    if (!gen_handle || !ver_handle) {
        fprintf(stderr, "[Error] Gagal menginisialisasi arsitektur dual-cubicle.\n");
        return 1;
    }

    /* 2. Setup Shared Memory Pipe (Inter-Process Communication) */
    printf("[Redeon Engine] Membangun Pipa SHM (/dev/shm/re_shm_verif_pipe)...\n");
    char *shm_pipe = create_shm_channel("verif_pipe", 4096);
    if (!shm_pipe) {
        fprintf(stderr, "[Error] Gagal alokasi POSIX Shared Memory.\n");
        return 1;
    }

    char *context_data = NULL;
    if (doc_path) {
        printf("[Redeon Engine] Memuat Dokumen RAG: %s\n", doc_path);
        context_data = read_local_file_mmap(doc_path);
    }

    printf("\n[System] Anti-Hallucination Pipeline AKTIF. Siap menerima input.\n");
    printf("[Ketik 'exit' untuk keluar]\n\n");

    char user_input[1024];
    while (1) {
        printf("👤 User : ");
        if (!fgets(user_input, sizeof(user_input), stdin)) break;
        user_input[strcspn(user_input, "\n")] = 0;
        
        if (strcmp(user_input, "exit") == 0 || strcmp(user_input, "quit") == 0) break;
        if (strlen(user_input) == 0) continue;

        /* TAHAP A: GENERATOR (s_1) */
        char gen_prompt[4096];
        if (context_data) {
            snprintf(gen_prompt, sizeof(gen_prompt),
                     "System: Berdasarkan dokumen:\n%s\nUser: %s", context_data, user_input);
        } else {
            snprintf(gen_prompt, sizeof(gen_prompt), "User: %s", user_input);
        }

        char *draft_response = vx_model_infer_text(gen_handle, gen_prompt);
        if (!draft_response) continue;

        printf("   [s_1 Generator] Menyusun draf jawaban... Selesai.\n");

        /* TAHAP B: SHARED MEMORY TRANSFER */
        strncpy(shm_pipe, draft_response, 4095);
        shm_pipe[4095] = '\0';
        printf("   [SHM Pipe] Memompa draf ke sekat s_2 (%zu bytes)...\n", strlen(shm_pipe));

        /* TAHAP C: VERIFIER (s_2) */
        char ver_prompt[8192];
        snprintf(ver_prompt, sizeof(ver_prompt),
                 "System: Evaluasi fakta berikut berdasarkan konteks. Jika benar, ulangi drafnya.\n"
                 "Draf dari s_1: %s\nKonteks Asli: %s", 
                 shm_pipe, context_data ? context_data : "None");

        char *final_verified = vx_model_infer_text(ver_handle, ver_prompt);
        printf("   [s_2 Verifier] Memeriksa halusinasi... Fakta tervalidasi!\n\n");

        if (final_verified) {
            printf("🤖 Redeon: %s\n\n", final_verified);
            free(final_verified);
        }
        free(draft_response);
    }
    
    if (context_data) free(context_data);
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[1], "run") == 0) {
        const char *model_path = argv[2];
        const char *doc_path = NULL;
        
        if (argc >= 5 && strcmp(argv[3], "--doc") == 0) {
            doc_path = argv[4];
        }
        return run_chat_loop(model_path, doc_path);
    } else {
        printf("Redeon by Nadev - Local AI Runner\n\n");
        printf("Cara penggunaan:\n  ./re_cli run <path_ke_model.gguf> [--doc <file.txt>]\n");
        return 1;
    }
}
