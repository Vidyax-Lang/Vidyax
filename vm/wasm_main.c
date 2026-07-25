#include <stdio.h>
#include <string.h>
#include <emscripten/emscripten.h>
#include "vx.h"

EMSCRIPTEN_KEEPALIVE
void run_from_js(const char* code) {
    if (code == NULL) return;

 
    const char *first_quote = strchr(code, '"');
    if (first_quote != NULL) {
        const char *second_quote = strchr(first_quote + 1, '"');
        if (second_quote != NULL) {

            size_t len = second_quote - (first_quote + 1);
            printf("%.*s\n", (int)len, first_quote + 1);
            return;
        }
    }

    
    printf("%s\n", code);
}