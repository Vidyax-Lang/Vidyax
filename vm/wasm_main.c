#include <stdio.h>
#include <emscripten/emscripten.h>
#include "vx.h"

EMSCRIPTEN_KEEPALIVE
void run_from_js(const char* code) {
    if (code == NULL) return;

    printf("Code Vidyax Run: %s\n", code);
}