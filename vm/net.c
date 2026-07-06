#ifdef VX_HAVE_CURL
#include <curl/curl.h>
#endif
#include "vx.h"

/* ==================================================================
 * ai module + member access + HTTP  (mirrors vidyax.py's _AI / _member
 * / _b_get). Real requests go through libcurl; without it the two
 * network entry points raise a catchable error.
 * ================================================================== */

/* ---- minimal JSON: escape strings out, pull one string value in ---- */
static int is_hex(int c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
           (c >= 'A' && c <= 'F');
}
static unsigned hex_val(int c) {
    if (c >= '0' && c <= '9') return (unsigned)(c - '0');
    if (c >= 'a' && c <= 'f') return (unsigned)(c - 'a' + 10);
    return (unsigned)(c - 'A' + 10);
}
static void utf8_put(SB *sb, unsigned cp) {
    char b[4];
    if (cp < 0x80) { b[0] = (char)cp; sb_put(sb, b, 1); }
    else if (cp < 0x800) {
        b[0] = (char)(0xC0 | (cp >> 6)); b[1] = (char)(0x80 | (cp & 0x3F));
        sb_put(sb, b, 2);
    } else if (cp < 0x10000) {
        b[0] = (char)(0xE0 | (cp >> 12));
        b[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[2] = (char)(0x80 | (cp & 0x3F)); sb_put(sb, b, 3);
    } else {
        b[0] = (char)(0xF0 | (cp >> 18));
        b[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
        b[2] = (char)(0x80 | ((cp >> 6) & 0x3F));
        b[3] = (char)(0x80 | (cp & 0x3F)); sb_put(sb, b, 4);
    }
}
static void json_escape(SB *sb, const char *s, uint32_t len) {
    static const char *hex = "0123456789abcdef";
    for (uint32_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)s[i];
        switch (ch) {
        case '"':  sb_puts(sb, "\\\""); break;
        case '\\': sb_puts(sb, "\\\\"); break;
        case '\n': sb_puts(sb, "\\n"); break;
        case '\r': sb_puts(sb, "\\r"); break;
        case '\t': sb_puts(sb, "\\t"); break;
        case '\b': sb_puts(sb, "\\b"); break;
        case '\f': sb_puts(sb, "\\f"); break;
        default:
            if (ch < 0x20) {
                char u[6] = {'\\', 'u', '0', '0', hex[ch >> 4], hex[ch & 0xF]};
                sb_put(sb, u, 6);
            } else { char c = (char)ch; sb_put(sb, &c, 1); }
        }
    }
}
/* Read a JSON string literal at p (points at the opening quote), decoding
 * escapes into out. Returns 1 on a well-formed string. */
static int json_read_string(const char *p, SB *out) {
    if (*p != '"') return 0;
    p++;
    while (*p && *p != '"') {
        if (*p == '\\') {
            p++;
            switch (*p) {
            case '"':  sb_put(out, "\"", 1); break;
            case '\\': sb_put(out, "\\", 1); break;
            case '/':  sb_put(out, "/", 1);  break;
            case 'n':  sb_put(out, "\n", 1); break;
            case 't':  sb_put(out, "\t", 1); break;
            case 'r':  sb_put(out, "\r", 1); break;
            case 'b':  sb_put(out, "\b", 1); break;
            case 'f':  sb_put(out, "\f", 1); break;
            case 'u': {
                if (!is_hex(p[1]) || !is_hex(p[2]) ||
                    !is_hex(p[3]) || !is_hex(p[4])) return 0;
                unsigned cp = (hex_val(p[1]) << 12) | (hex_val(p[2]) << 8) |
                              (hex_val(p[3]) << 4) | hex_val(p[4]);
                p += 4;
                if (cp >= 0xD800 && cp <= 0xDBFF && p[1] == '\\' &&
                    p[2] == 'u' && is_hex(p[3]) && is_hex(p[4]) &&
                    is_hex(p[5]) && is_hex(p[6])) {
                    unsigned lo = (hex_val(p[3]) << 12) | (hex_val(p[4]) << 8) |
                                  (hex_val(p[5]) << 4) | hex_val(p[6]);
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    p += 6;
                }
                utf8_put(out, cp);
                break;
            }
            case 0: return 0;
            default: { char c = *p; sb_put(out, &c, 1); }
            }
            p++;
        } else { sb_put(out, p, 1); p++; }
    }
    return *p == '"';
}
/* Find "key" used as an object key with a string value; decode into out.
 * Good enough for the chat-completions replies we consume (any escaped
 * occurrence inside a value keeps its backslash, so it never matches). */
static int json_extract_string(const char *buf, const char *key, SB *out) {
    size_t klen = strlen(key);
    const char *p = buf;
    while ((p = strchr(p, '"')) != NULL) {
        if (strncmp(p + 1, key, klen) == 0 && p[1 + klen] == '"') {
            const char *q = p + 2 + klen;
            while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r') q++;
            if (*q == ':') {
                q++;
                while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r') q++;
                if (*q == '"') return json_read_string(q, out);
            }
        }
        p++;
    }
    return 0;
}

/* ---- HTTP transport (libcurl) ---- */
#ifdef VX_HAVE_CURL
static size_t http_write(char *ptr, size_t sz, size_t nm, void *ud) {
    sb_put((SB *)ud, ptr, sz * nm);
    return sz * nm;
}
/* Perform a request. body!=NULL -> POST JSON with Bearer auth. On transport
 * success returns 0 (HTTP status in *code, response in *resp); on failure
 * returns -1 with a message in err. */
int http_request(const char *url, const char *auth, const char *body,
                        SB *resp, long *code, char *err, size_t errn) {
    CURL *c = curl_easy_init();
    if (!c) { snprintf(err, errn, "curl init failed"); return -1; }
    struct curl_slist *hdrs = NULL;
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, http_write);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, resp);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "vidyax/1.1");
    curl_easy_setopt(c, CURLOPT_TIMEOUT, body ? 60L : 15L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    if (auth) {
        char ab[600];
        snprintf(ab, sizeof ab, "Authorization: Bearer %s", auth);
        hdrs = curl_slist_append(hdrs, ab);
    }
    if (body) {
        hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
        curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
        curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    }
    if (hdrs) curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    CURLcode rc = curl_easy_perform(c);
    if (rc == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, code);
    else snprintf(err, errn, "%s", curl_easy_strerror(rc));
    if (hdrs) curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
    return rc == CURLE_OK ? 0 : -1;
}
#endif

/* ---- ai module ---- */
static const char *trim(const char *s, size_t len, size_t *outlen) {
    while (len && isspace((unsigned char)*s)) { s++; len--; }
    while (len && isspace((unsigned char)s[len - 1])) len--;
    *outlen = len;
    return s;
}
static void ai_open(OAI *self, const char *spec) {
    const char *colon = strchr(spec, ':');
    if (colon) {
        size_t plen; const char *pp = trim(spec, (size_t)(colon - spec), &plen);
        char prov[64];
        if (plen >= sizeof prov) plen = sizeof prov - 1;
        for (size_t i = 0; i < plen; i++)
            prov[i] = (char)tolower((unsigned char)pp[i]);
        prov[plen] = 0;
        int pv;
        if (strcmp(prov, "groq") == 0) pv = PROV_GROQ;
        else if (strcmp(prov, "openai") == 0) pv = PROV_OPENAI;
        else vm_error("unknown AI provider '%s' (available: groq, openai)",
                      prov);
        self->provider = pv;
        size_t mlen; const char *mm = trim(colon + 1, strlen(colon + 1), &mlen);
        if (mlen) self->model = new_str(mm, (uint32_t)mlen);
    } else {
        size_t mlen; const char *mm = trim(spec, strlen(spec), &mlen);
        self->model = new_str(mm, (uint32_t)mlen);
    }
}
OAI *new_ai(void) {
    OAI *a = (OAI *)alloc_obj(sizeof(OAI), O_AI);
    a->provider = PROV_GROQ;
    a->model = new_str("llama-3.1-8b-instant", 20);
    a->system_prompt = NULL;
    const char *env = getenv("VIDYAX_MODEL");
    if (env && *env) ai_open(a, env);
    return a;
}
static OBound *new_bound(OAI *self, int method) {
    OBound *b = (OBound *)alloc_obj(sizeof(OBound), O_BOUND);
    b->self = self; b->method = method;
    return b;
}
static Value ai_ask(OAI *self, OStr *prompt) {
    if (!allow_net)
        vm_error("network access is not allowed "
                 "(pass --allow-net to enable ai.ask / get)");
#ifndef VX_HAVE_CURL
    (void)self; (void)prompt;
    vm_error("ai.ask needs libcurl (rebuild vxvm with libcurl available)");
    return vnull();
#else
    const char *url, *keyname;
    if (self->provider == PROV_OPENAI) {
        url = "https://api.openai.com/v1/chat/completions";
        keyname = "OPENAI_API_KEY";
    } else {
        url = "https://api.groq.com/openai/v1/chat/completions";
        keyname = "GROQ_API_KEY";
    }
    const char *key = getenv(keyname);
    if (!key || !*key)
        vm_error("%s is not set. Run: export %s=...  "
                 "(ai.ask needs internet & an API key)", keyname, keyname);

    SB body; sb_init(&body);
    sb_puts(&body, "{\"model\":\"");
    json_escape(&body, self->model->chars, self->model->len);
    sb_puts(&body, "\",\"messages\":[");
    if (self->system_prompt) {
        sb_puts(&body, "{\"role\":\"system\",\"content\":\"");
        json_escape(&body, self->system_prompt->chars,
                    self->system_prompt->len);
        sb_puts(&body, "\"},");
    }
    sb_puts(&body, "{\"role\":\"user\",\"content\":\"");
    json_escape(&body, prompt->chars, prompt->len);
    sb_puts(&body, "\"}]}");

    SB resp; sb_init(&resp);
    long code = 0; char err[256];
    int rc = http_request(url, key, body.buf, &resp, &code, err, sizeof err);
    xfree(body.buf, body.cap);
    if (rc != 0) {
        char e[300]; snprintf(e, sizeof e, "%s", err);
        xfree(resp.buf, resp.cap);
        vm_error("AI failed: %s", e);
    }
    if (code >= 400) {
        char snippet[220]; snprintf(snippet, sizeof snippet, "%.200s",
                                    resp.buf ? resp.buf : "");
        long cc = code; xfree(resp.buf, resp.cap);
        vm_error("AI failed (HTTP %ld): %s", cc, snippet);
    }
    SB out; sb_init(&out);
    if (json_extract_string(resp.buf, "content", &out)) {
        OStr *s = new_str(out.buf, (uint32_t)out.len);
        xfree(out.buf, out.cap); xfree(resp.buf, resp.cap);
        return vstr_o(s);
    }
    xfree(out.buf, out.cap);
    SB em; sb_init(&em);
    if (json_extract_string(resp.buf, "message", &em)) {
        char detail[220]; snprintf(detail, sizeof detail, ": %.200s", em.buf);
        xfree(em.buf, em.cap); xfree(resp.buf, resp.cap);
        vm_error("AI gave an unexpected reply%s", detail);
    }
    xfree(em.buf, em.cap); xfree(resp.buf, resp.cap);
    vm_error("AI gave an unexpected reply");
    return vnull();
#endif
}
Value ai_invoke(OAI *self, int method, int argc, Value *args) {
    static const char *mn[] = {"open", "system", "ask"};
    if (argc != 1) vm_error("ai.%s needs 1 argument", mn[method]);
    OStr *s = vstr(args[0]);
    if (method == AIM_OPEN) { ai_open(self, s->chars); return vai_o(self); }
    if (method == AIM_SYSTEM) { self->system_prompt = s; return vai_o(self); }
    return ai_ask(self, s);
}
/* Member-access policy shared with the Python engines: underscore names are
 * private everywhere; only the ai object exposes members. */
Value member_get(Value o, OStr *name) {
    if (name->len > 0 && name->chars[0] == '_')
        vm_error("member '%s' is private", name->chars);
    if (o.t == V_AI) {
        OAI *a = AS_AI(o);
        const char *nm = name->chars;
        if (strcmp(nm, "open") == 0)   return vbound_o(new_bound(a, AIM_OPEN));
        if (strcmp(nm, "system") == 0) return vbound_o(new_bound(a, AIM_SYSTEM));
        if (strcmp(nm, "ask") == 0)    return vbound_o(new_bound(a, AIM_ASK));
        if (strcmp(nm, "model") == 0)  return vstr_o(a->model);
        if (strcmp(nm, "provider") == 0)
            return vstr_o(a->provider == PROV_OPENAI
                          ? new_str("openai", 6) : new_str("groq", 4));
        if (strcmp(nm, "system_prompt") == 0)
            return a->system_prompt ? vstr_o(a->system_prompt) : vnull();
        vm_error("'ai' has no member '%s'", name->chars);
    }
    vm_error("object has no member '%s'", name->chars);
    return vnull();
}

