#define _GNU_SOURCE
#include "vx_subcortex_bridge.h"
#include "../../../tools/tokenectomy-oss/include/tokenectomy_subcortex.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stddef.h>
#include <sys/stat.h>
#include <unistd.h>
#if !defined(VX_SUBCORTEX_STATIC) && !defined(VX_SUBCORTEX_NOOP)
#include <dlfcn.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
#endif

/* Compile-time C-ABI struct layout checks matching Rust const assertions in src/ffi.rs */
typedef char vx_sa_tkmy_buf_sz[(sizeof(struct tkmy_buf) == 2 * sizeof(size_t)) ? 1 : -1];
typedef char vx_sa_tkmy_buf_off[(offsetof(struct tkmy_buf, len) == sizeof(size_t)) ? 1 : -1];
typedef char vx_sa_tkmy_res_st[(offsetof(struct tkmy_result, status) == 0) ? 1 : -1];
typedef char vx_sa_tkmy_res_out[(offsetof(struct tkmy_result, out) == sizeof(size_t)) ? 1 : -1];
typedef char vx_sa_tkmy_res_sz[(sizeof(struct tkmy_result) == 3 * sizeof(size_t)) ? 1 : -1];
typedef char vx_sa_tkmy_in_cap[(TKMY_MAX_INPUT_BYTES == 1048576u) ? 1 : -1];
typedef char vx_sa_tkmy_ast_cap[(TKMY_MAX_AST_BYTES == 131072u) ? 1 : -1];
typedef char vx_sa_tkmy_path_cap[(TKMY_MAX_PATH_BYTES == 4096u) ? 1 : -1];

#ifdef VX_SUBCORTEX_NOOP

Value b_subcortex_redact(int argc, Value *a) {
    (void)argc; (void)a;
    vm_error("subcortex: static library was not linked at compile time");
    return vnull();
}

Value b_subcortex_prune(int argc, Value *a) {
    (void)argc; (void)a;
    vm_error("subcortex: static library was not linked at compile time");
    return vnull();
}

Value b_subcortex_audit_ast(int argc, Value *a) {
    (void)argc; (void)a;
    vm_error("subcortex: static library was not linked at compile time");
    return vnull();
}

#else /* !VX_SUBCORTEX_NOOP */

static const char *subcortex_status_name(int32_t st) {
    switch (st) {
    case TKMY_OK:               return "OK";
    case TKMY_INVALID_INPUT:    return "INVALID_INPUT";
    case TKMY_UNKNOWN_LANG:     return "UNKNOWN_LANG";
    case TKMY_SYNTAX_ERROR:     return "SYNTAX_ERROR";
    case TKMY_LAZY_PLACEHOLDER: return "LAZY_PLACEHOLDER";
    case TKMY_TOO_LARGE:        return "TOO_LARGE";
    case TKMY_TIMEOUT:          return "TIMEOUT";
    case TKMY_INTERNAL:         return "INTERNAL";
    default:                    return "INTERNAL";
    }
}

#ifdef VX_SUBCORTEX_STATIC

static pthread_mutex_t subcortex_mu = PTHREAD_MUTEX_INITIALIZER;
static int subcortex_checked = 0;
static char subcortex_static_err[256];

static void subcortex_ensure_loaded(void) {
    char err_copy[256];
    err_copy[0] = '\0';

    pthread_mutex_lock(&subcortex_mu);
    if (subcortex_checked == 0) {
        uint32_t ver = tkmy_abi_version();
        size_t bsz = 0, rsz = 0, roff = 0;
        tkmy_abi_sizes(&bsz, &rsz, &roff);
        if (ver != TKMY_ABI_VERSION) {
            snprintf(subcortex_static_err, sizeof(subcortex_static_err),
                     "subcortex: ABI version mismatch (expected %u, got %u)",
                     (unsigned)TKMY_ABI_VERSION, (unsigned)ver);
            subcortex_checked = -1;
        } else if (bsz != sizeof(struct tkmy_buf) ||
                   rsz != sizeof(struct tkmy_result) ||
                   roff != offsetof(struct tkmy_result, out)) {
            snprintf(subcortex_static_err, sizeof(subcortex_static_err),
                     "subcortex: ABI struct layout mismatch (got %zu/%zu/%zu, expected %zu/%zu/%zu)",
                     bsz, rsz, roff,
                     sizeof(struct tkmy_buf),
                     sizeof(struct tkmy_result),
                     offsetof(struct tkmy_result, out));
            subcortex_checked = -1;
        } else {
            subcortex_checked = 1;
        }
    }
    int state = subcortex_checked;
    if (state < 0) {
        snprintf(err_copy, sizeof(err_copy), "%s", subcortex_static_err);
    }
    pthread_mutex_unlock(&subcortex_mu);

    if (state < 0) {
        vm_error("%s", err_copy);
    }
}

#define CALL_REDACT(p, n)          tkmy_subcortex_redact((p), (n))
#define CALL_PRUNE(p, n)           tkmy_subcortex_prune_log((p), (n))
#define CALL_AUDIT(pp, pl, cp, cl) tkmy_subcortex_audit_ast((pp), (pl), (cp), (cl))
#define CALL_FREE(b)               tkmy_buf_free((b))

#else /* Dynamic shared library loading for Engine 3 (vxvm) */

typedef uint32_t (*fn_abi_version_t)(void);
typedef void (*fn_abi_sizes_t)(size_t *, size_t *, size_t *);
typedef struct tkmy_result (*fn_bytes_op_t)(const uint8_t *, size_t);
typedef struct tkmy_result (*fn_audit_op_t)(const uint8_t *, size_t, const uint8_t *, size_t);
typedef void (*fn_buf_free_t)(struct tkmy_buf);

static pthread_mutex_t subcortex_mu = PTHREAD_MUTEX_INITIALIZER;
static int subcortex_state = 0; /* 0 = uninit, 1 = ok, -1 = failed */
static char subcortex_load_err[512];
static void *subcortex_handle = NULL;

static fn_abi_version_t p_abi_version = NULL;
static fn_abi_sizes_t   p_abi_sizes = NULL;
static fn_bytes_op_t    p_redact = NULL;
static fn_bytes_op_t    p_prune = NULL;
static fn_audit_op_t    p_audit = NULL;
static fn_buf_free_t    p_buf_free = NULL;

#ifdef __APPLE__
#define TKMY_DYLIB_EXT "dylib"
#else
#define TKMY_DYLIB_EXT "so"
#endif

/* Compact standalone FIPS 180-4 SHA-256 for pre-dlopen library digest pinning */
typedef struct {
    uint32_t state[8];
    uint64_t bitcount;
    uint8_t  buf[64];
    size_t   buflen;
} vx_sha256_ctx;

static const uint32_t vx_sha256_k[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
};

#define VX_ROR32(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void vx_sha256_block(vx_sha256_ctx *c, const uint8_t blk[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = ((uint32_t)blk[i * 4] << 24) |
               ((uint32_t)blk[i * 4 + 1] << 16) |
               ((uint32_t)blk[i * 4 + 2] << 8) |
               ((uint32_t)blk[i * 4 + 3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = VX_ROR32(w[i - 15], 7) ^ VX_ROR32(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = VX_ROR32(w[i - 2], 17) ^ VX_ROR32(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = c->state[0], b = c->state[1], cc = c->state[2], d = c->state[3];
    uint32_t e = c->state[4], f = c->state[5], g = c->state[6], h = c->state[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = VX_ROR32(e, 6) ^ VX_ROR32(e, 11) ^ VX_ROR32(e, 25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + vx_sha256_k[i] + w[i];
        uint32_t S0 = VX_ROR32(a, 2) ^ VX_ROR32(a, 13) ^ VX_ROR32(a, 22);
        uint32_t maj = (a & b) ^ (a & cc) ^ (b & cc);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = cc; cc = b; b = a; a = t1 + t2;
    }
    c->state[0] += a; c->state[1] += b; c->state[2] += cc; c->state[3] += d;
    c->state[4] += e; c->state[5] += f; c->state[6] += g;  c->state[7] += h;
}

static void vx_sha256_init(vx_sha256_ctx *c) {
    c->state[0] = 0x6a09e667u; c->state[1] = 0xbb67ae85u;
    c->state[2] = 0x3c6ef372u; c->state[3] = 0xa54ff53au;
    c->state[4] = 0x510e527fu; c->state[5] = 0x9b05688cu;
    c->state[6] = 0x1f83d9abu; c->state[7] = 0x5be0cd19u;
    c->bitcount = 0;
    c->buflen = 0;
}

static void vx_sha256_update(vx_sha256_ctx *c, const uint8_t *data, size_t len) {
    c->bitcount += (uint64_t)len * 8ULL;
    size_t i = 0;
    if (c->buflen > 0) {
        while (i < len && c->buflen < 64) {
            c->buf[c->buflen++] = data[i++];
        }
        if (c->buflen == 64) {
            vx_sha256_block(c, c->buf);
            c->buflen = 0;
        }
    }
    while (i + 64 <= len) {
        vx_sha256_block(c, data + i);
        i += 64;
    }
    while (i < len) {
        c->buf[c->buflen++] = data[i++];
    }
}

static void vx_sha256_final(vx_sha256_ctx *c, uint8_t out[32]) {
    c->buf[c->buflen++] = 0x80u;
    if (c->buflen > 56) {
        while (c->buflen < 64) c->buf[c->buflen++] = 0;
        vx_sha256_block(c, c->buf);
        c->buflen = 0;
    }
    while (c->buflen < 56) c->buf[c->buflen++] = 0;
    for (int i = 0; i < 8; i++) {
        c->buf[56 + i] = (uint8_t)(c->bitcount >> ((7 - i) * 8));
    }
    vx_sha256_block(c, c->buf);
    for (int i = 0; i < 8; i++) {
        out[i * 4]     = (uint8_t)(c->state[i] >> 24);
        out[i * 4 + 1] = (uint8_t)(c->state[i] >> 16);
        out[i * 4 + 2] = (uint8_t)(c->state[i] >> 8);
        out[i * 4 + 3] = (uint8_t)(c->state[i]);
    }
}

static int parse_hex_sha256(const char *hex_in, uint8_t out[32]) {
    while (*hex_in == ' ' || *hex_in == '\t') hex_in++;
    for (int i = 0; i < 32; i++) {
        int hi = hex_in[i * 2];
        int lo = hex_in[i * 2 + 1];
        if (!hi || !lo) return -1;
        int hv = (hi >= '0' && hi <= '9') ? (hi - '0')
               : (hi >= 'a' && hi <= 'f') ? (hi - 'a' + 10)
               : (hi >= 'A' && hi <= 'F') ? (hi - 'A' + 10) : -1;
        int lv = (lo >= '0' && lo <= '9') ? (lo - '0')
               : (lo >= 'a' && lo <= 'f') ? (lo - 'a' + 10)
               : (lo >= 'A' && lo <= 'F') ? (lo - 'A' + 10) : -1;
        if (hv < 0 || lv < 0) return -1;
        out[i] = (uint8_t)((hv << 4) | lv);
    }
    const char *tail = hex_in + 64;
    while (*tail == ' ' || *tail == '\t' || *tail == '\r' || *tail == '\n') tail++;
    return (*tail == '\0') ? 0 : -1;
}

#ifndef VX_SUBCORTEX_PINNED_LIB
static int resolve_exe_dir(char *out, size_t cap) {
#ifdef __APPLE__
    uint32_t sz = (uint32_t)cap;
    if (_NSGetExecutablePath(out, &sz) != 0) return -1;
#else
    ssize_t n = readlink("/proc/self/exe", out, cap - 1);
    if (n <= 0) return -1;
    out[n] = '\0';
#endif
    char *slash = strrchr(out, '/');
    if (!slash) return -1;
    *slash = '\0';
    return 0;
}
#endif

/* Verifies canonical path ownership, non-group/world-writable file & parent directory
 * modes, optional SHA-256 digest pin, and opens via `/proc/self/fd/<fd>` on Linux to
 * eliminate TOCTOU between verification and `dlopen`. */
static void *verify_and_dlopen_trusted(const char *raw_path, int require_abs,
                                       char *err, size_t err_cap) {
    if (require_abs && raw_path[0] != '/') {
        snprintf(err, err_cap,
                 "subcortex: failed to load library (VX_SUBCORTEX_LIB must be an absolute path)");
        return NULL;
    }

    char resolved[PATH_MAX];
    if (!realpath(raw_path, resolved)) {
        snprintf(err, err_cap, "subcortex: failed to load library (%.256s: %.128s)",
                 raw_path, strerror(errno));
        return NULL;
    }

    char parent[PATH_MAX];
    snprintf(parent, sizeof(parent), "%s", resolved);
    char *slash = strrchr(parent, '/');
    if (!slash) {
        snprintf(err, err_cap, "subcortex: failed to load library (invalid canonical path)");
        return NULL;
    }
    if (slash == parent) {
        parent[1] = '\0';
    } else {
        *slash = '\0';
    }

    uid_t euid = geteuid();
    struct stat dir_st;
    if (stat(parent, &dir_st) != 0 || !S_ISDIR(dir_st.st_mode)) {
        snprintf(err, err_cap, "subcortex: failed to load library (invalid parent directory)");
        return NULL;
    }
    if (dir_st.st_uid != 0 && dir_st.st_uid != euid) {
        snprintf(err, err_cap,
                 "subcortex: failed to load library (untrusted parent directory owner uid=%u)",
                 (unsigned)dir_st.st_uid);
        return NULL;
    }
    if ((dir_st.st_mode & 0022) != 0) {
        snprintf(err, err_cap,
                 "subcortex: failed to load library (parent directory %.256s is group/world-writable)",
                 parent);
        return NULL;
    }

    int oflags = O_RDONLY;
#ifdef O_CLOEXEC
    oflags |= O_CLOEXEC;
#endif
#ifdef O_NOFOLLOW
    oflags |= O_NOFOLLOW;
#endif
    int fd = open(resolved, oflags);
    if (fd < 0) {
        snprintf(err, err_cap, "subcortex: failed to load library (%.256s: %.128s)",
                 resolved, strerror(errno));
        return NULL;
    }

    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        close(fd);
        snprintf(err, err_cap, "subcortex: failed to load library (not a regular file)");
        return NULL;
    }
    if (st.st_uid != 0 && st.st_uid != euid) {
        close(fd);
        snprintf(err, err_cap,
                 "subcortex: failed to load library (untrusted library owner uid=%u)",
                 (unsigned)st.st_uid);
        return NULL;
    }
    if ((st.st_mode & 0022) != 0) {
        close(fd);
        snprintf(err, err_cap,
                 "subcortex: failed to load library (library is group/world-writable)");
        return NULL;
    }

#ifdef VX_SUBCORTEX_PINNED_SHA256
    const char *expected_sha_hex = VX_SUBCORTEX_PINNED_SHA256;
#else
    const char *expected_sha_hex = getenv("VX_SUBCORTEX_SHA256");
#endif
    if (expected_sha_hex != NULL) {
        uint8_t want_digest[32];
        if (parse_hex_sha256(expected_sha_hex, want_digest) != 0) {
            close(fd);
            snprintf(err, err_cap,
                     "subcortex: failed to load library (invalid VX_SUBCORTEX_SHA256)");
            return NULL;
        }
        vx_sha256_ctx hctx;
        vx_sha256_init(&hctx);
        uint8_t chunk[32768];
        for (;;) {
            ssize_t nr = read(fd, chunk, sizeof(chunk));
            if (nr < 0) {
                if (errno == EINTR) continue;
                close(fd);
                snprintf(err, err_cap,
                         "subcortex: failed to load library (read error during SHA-256 check)");
                return NULL;
            }
            if (nr == 0) break;
            vx_sha256_update(&hctx, chunk, (size_t)nr);
        }
        uint8_t got_digest[32];
        vx_sha256_final(&hctx, got_digest);
        uint8_t diff = 0;
        for (int i = 0; i < 32; i++) {
            diff |= (uint8_t)(got_digest[i] ^ want_digest[i]);
        }
        if (diff != 0) {
            close(fd);
            snprintf(err, err_cap,
                     "subcortex: failed to load library (SHA-256 digest mismatch)");
            return NULL;
        }
    }

    dlerror();
    void *handle = NULL;
#ifdef __linux__
    char fd_path[64];
    snprintf(fd_path, sizeof(fd_path), "/proc/self/fd/%d", fd);
    handle = dlopen(fd_path, RTLD_NOW | RTLD_LOCAL);
#else
    struct stat st_post;
    if (stat(resolved, &st_post) == 0 &&
        st_post.st_dev == st.st_dev && st_post.st_ino == st.st_ino) {
        handle = dlopen(resolved, RTLD_NOW | RTLD_LOCAL);
    } else {
        snprintf(err, err_cap, "subcortex: failed to load library (TOCTOU inode change detected)");
        close(fd);
        return NULL;
    }
#endif
    const char *dle = handle ? NULL : dlerror();
    close(fd);
    if (!handle) {
        snprintf(err, err_cap, "subcortex: failed to load library (%.384s)",
                 dle ? dle : resolved);
        return NULL;
    }
    return handle;
}

static void subcortex_init_locked(void) {
#ifdef VX_SUBCORTEX_PINNED_LIB
    /* Compile-time pinned library path completely ignores VX_SUBCORTEX_LIB */
    subcortex_handle = verify_and_dlopen_trusted(
        VX_SUBCORTEX_PINNED_LIB, 1, subcortex_load_err, sizeof(subcortex_load_err));
    if (!subcortex_handle) {
        subcortex_state = -1;
        return;
    }
#else
    const char *env_path = getenv("VX_SUBCORTEX_LIB");
    if (env_path != NULL) {
        if (env_path[0] == '\0') {
            snprintf(subcortex_load_err, sizeof(subcortex_load_err),
                     "subcortex: failed to load library (VX_SUBCORTEX_LIB is empty)");
            subcortex_state = -1;
            return;
        }
        subcortex_handle = verify_and_dlopen_trusted(
            env_path, 1, subcortex_load_err, sizeof(subcortex_load_err));
        if (!subcortex_handle) {
            subcortex_state = -1;
            return;
        }
    } else {
        char exe_dir[PATH_MAX];
        char cand1[PATH_MAX];
        char cand2[PATH_MAX];
        snprintf(subcortex_load_err, sizeof(subcortex_load_err),
                 "subcortex: failed to load library (libtokenectomy." TKMY_DYLIB_EXT " not found)");

        if (resolve_exe_dir(exe_dir, sizeof(exe_dir)) == 0) {
            int w1 = snprintf(cand1, sizeof(cand1),
                              "%s/../../../tools/tokenectomy-oss/target/subcortex/release/libtokenectomy.%s",
                              exe_dir, TKMY_DYLIB_EXT);
            if (w1 > 0 && (size_t)w1 < sizeof(cand1)) {
                subcortex_handle = verify_and_dlopen_trusted(
                    cand1, 0, subcortex_load_err, sizeof(subcortex_load_err));
            }
            if (!subcortex_handle) {
                int w2 = snprintf(cand2, sizeof(cand2),
                                  "%s/../../../tools/tokenectomy-oss/target/release/libtokenectomy.%s",
                                  exe_dir, TKMY_DYLIB_EXT);
                if (w2 > 0 && (size_t)w2 < sizeof(cand2)) {
                    char second_err[512];
                    subcortex_handle = verify_and_dlopen_trusted(
                        cand2, 0, second_err, sizeof(second_err));
                }
            }
        }
        /* Security: NEVER fall back to bare dlopen("libtokenectomy.so") (blocks LD_LIBRARY_PATH hijack) */
        if (!subcortex_handle) {
            subcortex_state = -1;
            return;
        }
    }
#endif

    p_abi_version = (fn_abi_version_t)dlsym(subcortex_handle, "tkmy_abi_version");
    p_abi_sizes   = (fn_abi_sizes_t)dlsym(subcortex_handle, "tkmy_abi_sizes");
    p_redact      = (fn_bytes_op_t)dlsym(subcortex_handle, "tkmy_subcortex_redact");
    p_prune       = (fn_bytes_op_t)dlsym(subcortex_handle, "tkmy_subcortex_prune_log");
    p_audit       = (fn_audit_op_t)dlsym(subcortex_handle, "tkmy_subcortex_audit_ast");
    p_buf_free    = (fn_buf_free_t)dlsym(subcortex_handle, "tkmy_buf_free");

    if (!p_abi_version || !p_abi_sizes || !p_redact || !p_prune || !p_audit || !p_buf_free) {
        snprintf(subcortex_load_err, sizeof(subcortex_load_err),
                 "subcortex: missing required FFI symbol in shared library");
        dlclose(subcortex_handle);
        subcortex_handle = NULL;
        subcortex_state = -1;
        return;
    }

    uint32_t ver = p_abi_version();
    if (ver != TKMY_ABI_VERSION) {
        snprintf(subcortex_load_err, sizeof(subcortex_load_err),
                 "subcortex: ABI version mismatch (expected %u, got %u)",
                 (unsigned)TKMY_ABI_VERSION, (unsigned)ver);
        dlclose(subcortex_handle);
        subcortex_handle = NULL;
        subcortex_state = -1;
        return;
    }

    size_t bsz = 0, rsz = 0, roff = 0;
    p_abi_sizes(&bsz, &rsz, &roff);
    if (bsz != sizeof(struct tkmy_buf) ||
        rsz != sizeof(struct tkmy_result) ||
        roff != offsetof(struct tkmy_result, out)) {
        snprintf(subcortex_load_err, sizeof(subcortex_load_err),
                 "subcortex: ABI struct layout mismatch (got %zu/%zu/%zu, expected %zu/%zu/%zu)",
                 bsz, rsz, roff,
                 sizeof(struct tkmy_buf),
                 sizeof(struct tkmy_result),
                 offsetof(struct tkmy_result, out));
        dlclose(subcortex_handle);
        subcortex_handle = NULL;
        subcortex_state = -1;
        return;
    }

    subcortex_state = 1;
}

static void subcortex_ensure_loaded(void) {
    char err_copy[512];
    err_copy[0] = '\0';

    pthread_mutex_lock(&subcortex_mu);
    if (subcortex_state == 0) {
        subcortex_init_locked();
    }
    int st = subcortex_state;
    if (st < 0) {
        snprintf(err_copy, sizeof(err_copy), "%s", subcortex_load_err);
    }
    pthread_mutex_unlock(&subcortex_mu);

    if (st < 0) {
        vm_error("%s", err_copy);
    }
}

#define CALL_REDACT(p, n)          p_redact((p), (n))
#define CALL_PRUNE(p, n)           p_prune((p), (n))
#define CALL_AUDIT(pp, pl, cp, cl) p_audit((pp), (pl), (cp), (cl))
#define CALL_FREE(b)               p_buf_free((b))

#endif /* VX_SUBCORTEX_STATIC */

enum {
    SUBCORTEX_FUEL_REDACT = 0,
    SUBCORTEX_FUEL_PRUNE  = 1,
    SUBCORTEX_FUEL_AUDIT  = 2
};

/* Empirically calibrated against vxvm bytecode dispatch throughput (~90M instr/s, ~11.1 ns/instr)
 * and release FFI latencies across 140 B -> 1 MiB (including adversarial deep/error-dense ASTs
 * bounded by the 250 ms Tree-sitter progress_callback timeout):
 *   - redact:    512 + 2 * len   (167 B -> ~846 instr [6.5us]; 1 MiB -> ~2.10M instr [18.7ms])
 *   - prune_log: 1024 + 4 * len  (296 B -> ~2.2k instr [11.8us]; 1 MiB -> ~4.20M instr [41.9ms])
 *   - audit_ast: 3500 + 28 * bytes (156 B -> ~7.9k instr; 64 KiB -> ~1.84M instr [~21ms];
 *                                 128 KiB cap -> ~3.67M instr [~42ms i5-1235U / ~110ms N4020, >2x margin];
 *                                 >128 KiB rejected in O(1) with TKMY_TOO_LARGE) */
static void subcortex_charge_fuel(size_t input_bytes, int op_kind) {
    size_t max_cap = (op_kind == SUBCORTEX_FUEL_AUDIT)
        ? (size_t)(TKMY_MAX_AST_BYTES + TKMY_MAX_PATH_BYTES + 1)
        : (size_t)(TKMY_MAX_INPUT_BYTES + 1);
    size_t bounded = input_bytes > max_cap ? max_cap : input_bytes;
    uint64_t cost;
    switch (op_kind) {
    case SUBCORTEX_FUEL_REDACT:
        cost = 512ULL + 2ULL * (uint64_t)bounded;
        break;
    case SUBCORTEX_FUEL_PRUNE:
        cost = 1024ULL + 4ULL * (uint64_t)bounded;
        break;
    default:
        cost = 3500ULL + 28ULL * (uint64_t)bounded;
        break;
    }
    instr_count += cost;
    if (max_instr && instr_count > max_instr) {
        vm_error("VM PANIC: instruction limit exceeded (%llu)",
                 (unsigned long long)max_instr);
    }
    if (max_secs &&
        (double)(clock() - start_clock) / CLOCKS_PER_SEC > max_secs) {
        vm_error("VM PANIC: time limit exceeded (%.1fs)", max_secs);
    }
}

static void subcortex_check_post_clock_or_free(struct tkmy_buf b) {
    if (max_secs &&
        (double)(clock() - start_clock) / CLOCKS_PER_SEC > max_secs) {
        CALL_FREE(b);
        vm_error("VM PANIC: time limit exceeded (%.1fs)", max_secs);
    }
}

/* Converts a Rust-owned `tkmy_buf` into a GC-managed `OStr` while guaranteeing
 * `CALL_FREE(b)` always runs BEFORE any `vm_error` / `longjmp` on `--max-mem`. */
static OStr *subcortex_buf_into_ostr(struct tkmy_buf b) {
    if (b.ptr == NULL || b.len == 0) {
        CALL_FREE(b);
        return new_str("", 0);
    }
    if (b.len > (size_t)UINT32_MAX) {
        CALL_FREE(b);
        vm_error("subcortex: output exceeds Vidyax string limit");
    }
    if (b.len <= 4096) {
        char stack_copy[4096];
        size_t n = b.len;
        memcpy(stack_copy, b.ptr, n);
        CALL_FREE(b);
        return new_str(stack_copy, (uint32_t)n);
    }

    size_t needed = sizeof(OStr) + b.len + 1;
    if (max_mem &&
        __atomic_load_n(&mem_used, __ATOMIC_RELAXED) + needed > max_mem) {
        CALL_FREE(b);
        vm_error("VM PANIC: memory limit exceeded (%zu bytes)", max_mem);
    }
    OStr *s = new_str((const char *)b.ptr, (uint32_t)b.len);
    CALL_FREE(b);
    return s;
}

Value b_subcortex_redact(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_STR) {
        vm_error("subcortex_redact() needs 1 text value");
    }
    subcortex_ensure_loaded();

    OStr *in = AS_STR(a[0]);
    const uint8_t *ptr = (const uint8_t *)in->chars;
    size_t len = (size_t)in->len;
    subcortex_charge_fuel(len, SUBCORTEX_FUEL_REDACT);

    struct tkmy_result res;
    VX_BLOCKING(res = CALL_REDACT(ptr, len));
    subcortex_check_post_clock_or_free(res.out);

    if (res.status != TKMY_OK) {
        int32_t st = res.status;
        CALL_FREE(res.out);
        vm_error("subcortex_redact() failed: %s", subcortex_status_name(st));
    }

    return vstr_o(subcortex_buf_into_ostr(res.out));
}

Value b_subcortex_prune(int argc, Value *a) {
    if (argc != 1 || a[0].t != V_STR) {
        vm_error("subcortex_prune() needs 1 text value");
    }
    subcortex_ensure_loaded();

    OStr *in = AS_STR(a[0]);
    const uint8_t *ptr = (const uint8_t *)in->chars;
    size_t len = (size_t)in->len;
    subcortex_charge_fuel(len, SUBCORTEX_FUEL_PRUNE);

    struct tkmy_result res;
    VX_BLOCKING(res = CALL_PRUNE(ptr, len));
    subcortex_check_post_clock_or_free(res.out);

    if (res.status != TKMY_OK) {
        int32_t st = res.status;
        CALL_FREE(res.out);
        vm_error("subcortex_prune() failed: %s", subcortex_status_name(st));
    }

    return vstr_o(subcortex_buf_into_ostr(res.out));
}

/* Note: `path` is used strictly for extension-based language detection and is
 * NEVER opened on disk, so `need_fs()` is intentionally NOT required. */
Value b_subcortex_audit_ast(int argc, Value *a) {
    if (argc != 2 || a[0].t != V_STR || a[1].t != V_STR) {
        vm_error("subcortex_audit_ast() needs 2 text values (path, code)");
    }
    subcortex_ensure_loaded();

    OStr *path = AS_STR(a[0]);
    OStr *code = AS_STR(a[1]);
    const uint8_t *p_ptr = (const uint8_t *)path->chars;
    size_t p_len = (size_t)path->len;
    const uint8_t *c_ptr = (const uint8_t *)code->chars;
    size_t c_len = (size_t)code->len;
    subcortex_charge_fuel(p_len + c_len, SUBCORTEX_FUEL_AUDIT);

    struct tkmy_result res;
    VX_BLOCKING(res = CALL_AUDIT(p_ptr, p_len, c_ptr, c_len));
    subcortex_check_post_clock_or_free(res.out);

    char err_buf[512];
    size_t err_len = 0;
    if (res.out.ptr != NULL && res.out.len > 0) {
        err_len = res.out.len < (sizeof(err_buf) - 1)
            ? res.out.len
            : (sizeof(err_buf) - 1);
        memcpy(err_buf, res.out.ptr, err_len);
    }
    err_buf[err_len] = '\0';
    int32_t st = res.status;
    /* Free Rust buffer BEFORE any VM heap allocation or vm_error */
    CALL_FREE(res.out);

    if (st == TKMY_INTERNAL) {
        vm_error("subcortex_audit_ast() internal error");
    }

    const char *sname = subcortex_status_name(st);
    OMap *m = map_new();
    /* Explicit 4-field schema contract; callers look up keys by name (unordered map). */
    map_set(m, new_str("valid", 5), vbool(st == TKMY_OK));
    map_set(m, new_str("code", 4), vnum((double)st));
    map_set(m, new_str("status", 6), vstr_o(new_str(sname, (uint32_t)strlen(sname))));
    map_set(m, new_str("error", 5), vstr_o(new_str(err_buf, (uint32_t)err_len)));
    return vmap_o(m);
}

#endif /* !VX_SUBCORTEX_NOOP */
