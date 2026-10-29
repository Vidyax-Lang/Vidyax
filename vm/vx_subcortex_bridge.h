#ifndef VX_SUBCORTEX_BRIDGE_H
#define VX_SUBCORTEX_BRIDGE_H

#include "vx.h"

Value b_subcortex_redact(int argc, Value *a);
Value b_subcortex_prune(int argc, Value *a);
Value b_subcortex_audit_ast(int argc, Value *a);

#endif /* VX_SUBCORTEX_BRIDGE_H */
