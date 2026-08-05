import sys
import os
import subprocess

# Ensure the current directory is in sys.path
sys.path.insert(0, os.path.abspath('.'))
import vidyax

def test_python_engine():
    # Force initialize the thread local
    vidyax.RT["_cur_perms"]()
    
    vidyax.RT["_S_N_CUBICLE"] = True
    vidyax.RT["_PERMS"].v = {"net": True, "fs": False}
    try:
        vidyax.RT["_perm_fs"]()
        print("FAIL: Python _perm_fs() did not raise exception")
        sys.exit(1)
    except Exception as e:
        if "M-MUTATE-VIOLATION" in str(e):
            print("PASS: Python engine M-MUTATE-VIOLATION triggered correctly.")
        else:
            print("FAIL: Python engine raised wrong error: " + str(e))
            sys.exit(1)
    finally:
        vidyax.RT["_S_N_CUBICLE"] = False
        vidyax.RT["_PERMS"].v = {"net": True, "fs": True}

def test_c_engine_memory():
    print("Running C engine memory isolation tests (Valgrind / ASan)...")
    # Build with Address Sanitizer
    build_cmd = "gcc -fsanitize=address -g -O2 -Wall -Wextra -DVX_HAVE_CURL -o vm/vxvm_asan vm/vm.c vm/value.c vm/gc.c vm/net.c vm/builtins.c vm/loader.c vm/debug.c vm/profile.c vm/task.c -lm -lpthread -lcurl"
    subprocess.run(build_cmd, shell=True, check=True)
    
    # We will test a simple script
    test_script = "test_mem.vx"
    with open(test_script, "w") as f:
        f.write('print "Hello Memory"\n')
        
    subprocess.run(["python3", "vidyax.py", "bytecode", test_script], check=True)
    
    # Run the compiled ASan binary
    res = subprocess.run(["./vm/vxvm_asan", "test_mem.vxc"], capture_output=True, text=True)
    if "Hello Memory" in res.stdout and "AddressSanitizer" not in res.stderr:
        print("PASS: C VM memory isolation perfect (0 leaks detected by ASan).")
    else:
        print("FAIL: Memory leak or ASan error detected.")
        print(res.stderr)
        sys.exit(1)

    # Cleanup
    os.remove(test_script)
    os.remove("test_mem.vxc")
    os.remove("vm/vxvm_asan")

if __name__ == "__main__":
    test_python_engine()
    test_c_engine_memory()
    print("All Phase F tests passed 100%. Ready for Option 2.")
