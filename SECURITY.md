# Security Policy

## Security model

Vidyax is designed to run code you don't fully trust — including code
paths driven by AI output. Defense in depth, outermost first:

1. **Process sandbox (CLI flags, VM/native).** Network and file access
   are *denied by default*; grant them per run with `--allow-net` /
   `--allow-fs`. The VM adds resource limits: `--max-instr`,
   `--max-mem`, `--max-time`.
2. **In-language capability sandbox.** `sandbox deny net, fs:` removes
   capabilities for a block — including functions it calls and tasks it
   spawns. A sandbox can only *reduce* what the process was granted,
   never add. Use one per agent work zone so a hallucinated or
   prompt-injected reply can't trick that code path into touching files
   or the network.
3. **Bytecode verification.** Every `.vxc` is validated before it runs
   (opcodes, operand ranges, jump targets); corrupt input is rejected.
4. **No ambient authority.** The language has no subprocess/exec, no
   arbitrary FFI, and underscore members are unreachable, so programs
   can't escape into Python/C internals.

What this does **not** protect against: bugs in the C runtime itself
(mitigated by ASan/UBSan/TSan builds and a differential fuzzer in CI
practice), and misuse of data your program legitimately has access to.

## Reporting a vulnerability

Open a private report via GitHub Security Advisories on
`Vidyax-Lang/Vidyax`, or open an issue if the problem is not sensitive.
Only the latest release line is supported with fixes.
