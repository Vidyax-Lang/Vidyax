#ifndef VX_MODEL_BRIDGE_H
#define VX_MODEL_BRIDGE_H

#include "vx.h"

// C-Level API
void* vx_model_load_mmap(const char *path);
char* vx_model_infer_text(void *handle, const char *prompt);

// VM Bindings for Native Tools
Value b_model_load(int argc, Value *a);
Value b_model_infer(int argc, Value *a);

#endif
