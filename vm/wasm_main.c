#include <stdio.h>
#include <emscripten/emscripten.h>

EMSCRIPTEN_KEEPALIVE
void run_from_js(const char* code) {
    printf("Code Vidyax Run: %s\n", code);
}