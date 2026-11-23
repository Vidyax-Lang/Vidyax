/*
 * Vidyax Standalone Zero-Python CLI
 * Embeds the 3-stage self-hosted Vidyax compiler (vxc.vxc) directly inside the
 * native C virtual machine binary. Zero Python dependency at runtime.
 */

#include "vx.h"
#include "vxc_embedded.h"
#include <sys/wait.h>
#include <unistd.h>

extern int vx_execute_vxc(const char *path);

static int ends_with(const char *s, const char *suffix) {
    size_t ls = strlen(s), lsf = strlen(suffix);
    return ls >= lsf && strcmp(s + ls - lsf, suffix) == 0;
}

static int compile_vx_with_embedded_vxc(const char *src_path, const char *out_vxc_path) {
    char compiler_tmp[] = "/tmp/vidyax_vxc_XXXXXX";
    int fd = mkstemp(compiler_tmp);
    if (fd < 0) {
        fprintf(stderr, "[Vidyax] failed to create temporary compiler file\n");
        return 1;
    }
    size_t written = 0;
    while (written < VXC_EMBEDDED_LEN) {
        ssize_t n = write(fd, VXC_EMBEDDED_BYTECODE + written, VXC_EMBEDDED_LEN - written);
        if (n <= 0) {
            close(fd);
            unlink(compiler_tmp);
            fprintf(stderr, "[Vidyax] failed to write embedded compiler bytecode\n");
            return 1;
        }
        written += (size_t)n;
    }
    close(fd);

    pid_t pid = fork();
    if (pid < 0) {
        unlink(compiler_tmp);
        fprintf(stderr, "[Vidyax] fork failed during compilation\n");
        return 1;
    }
    if (pid == 0) {
        /* Child process runs self-hosted vxc.vxc with isolated VM state */
        char *c_argv[2] = { (char *)src_path, (char *)out_vxc_path };
        vx_argc = 2;
        vx_argv = c_argv;
        allow_fs = 1;
        allow_net = 0;
        vx_debug = 0;
        vx_profile = 0;
        max_instr = 0;
        max_mem = 0;
        max_secs = 0.0;
        int rc = vx_execute_vxc(compiler_tmp);
        _exit(rc);
    }

    int status = 0;
    waitpid(pid, &status, 0);
    unlink(compiler_tmp);
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return 1;
    }
    return 0;
}

static void print_usage(void) {
    fprintf(stderr,
        "Vidyax v1.3 (Zero-Python Standalone Native Runtime + Self-Hosted Compiler)\n"
        "usage:\n"
        "  vidyax [flags] <program.vx | program.vxc> [args...]\n"
        "  vidyax compile <input.vx> [-o <output.vxc>]\n"
        "  vidyax --version\n"
        "flags:\n"
        "  --allow-net        allow network access (denied by default)\n"
        "  --allow-fs         allow filesystem access (denied by default)\n"
        "  --max-instr N      halt after N bytecode instructions\n"
        "  --max-mem BYTES    cap GC heap bytes\n"
        "  --max-time SECS    halt after SECS wall-clock seconds\n"
        "  --profile          print deterministic instruction profile\n"
        "  --debug            launch interactive line debugger\n"
    );
}

int main(int argc, char **argv) {
    if (argc < 2) {
        print_usage();
        return 1;
    }
    if (strcmp(argv[1], "--version") == 0 || strcmp(argv[1], "-v") == 0) {
        printf("vidyax 1.3.0 (zero-python standalone C VM + embedded self-hosted vxc %zu bytes)\n",
               (size_t)VXC_EMBEDDED_LEN);
        return 0;
    }
    if (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0) {
        print_usage();
        return 0;
    }

    /* Subcommand: vidyax compile <input.vx> [-o <output.vxc>] */
    if (strcmp(argv[1], "compile") == 0) {
        if (argc < 3) {
            fprintf(stderr, "usage: vidyax compile <input.vx> [-o <output.vxc>]\n");
            return 1;
        }
        const char *in_path = argv[2];
        char out_buf[1024];
        const char *out_path = NULL;
        if (argc >= 5 && strcmp(argv[3], "-o") == 0) {
            out_path = argv[4];
        } else {
            snprintf(out_buf, sizeof(out_buf), "%sc", in_path);
            out_path = out_buf;
        }
        if (compile_vx_with_embedded_vxc(in_path, out_path) != 0) {
            return 1;
        }
        printf("[Vidyax] compiled -> %s\n", out_path);
        return 0;
    }

    const char *path = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "run") == 0 && path == NULL) {
            continue;
        } else if (strcmp(argv[i], "--max-instr") == 0 && i + 1 < argc) {
            max_instr = strtoull(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--max-mem") == 0 && i + 1 < argc) {
            max_mem = (size_t)strtoull(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--max-time") == 0 && i + 1 < argc) {
            max_secs = strtod(argv[++i], NULL);
        } else if (strcmp(argv[i], "--allow-net") == 0) {
            allow_net = 1;
        } else if (strcmp(argv[i], "--allow-fs") == 0) {
            allow_fs = 1;
        } else if (strcmp(argv[i], "--debug") == 0) {
            vx_debug = 1;
        } else if (strcmp(argv[i], "--profile") == 0) {
            vx_profile = 1;
        } else if (strcmp(argv[i], "--gc-stress") == 0) {
            gc_stress = 1;
        } else if (strcmp(argv[i], "--gc-stats") == 0) {
            gc_stats = 1;
        } else if (argv[i][0] != '-') {
            path = argv[i];
            vx_argc = argc - (i + 1);
            vx_argv = (vx_argc > 0) ? &argv[i + 1] : NULL;
            break;
        } else {
            print_usage();
            return 1;
        }
    }

    if (!path) {
        print_usage();
        return 1;
    }

    if (ends_with(path, ".vxc")) {
        return vx_execute_vxc(path);
    }

    /* Compile .vx directly via embedded self-hosted vxc.vxc, then execute */
    char out_tmp[] = "/tmp/vidyax_run_XXXXXX";
    int fd = mkstemp(out_tmp);
    if (fd < 0) {
        fprintf(stderr, "[Vidyax] failed to allocate temporary bytecode file\n");
        return 1;
    }
    close(fd);

    if (compile_vx_with_embedded_vxc(path, out_tmp) != 0) {
        unlink(out_tmp);
        return 1;
    }

    int rc = vx_execute_vxc(out_tmp);
    unlink(out_tmp);
    return rc;
}
