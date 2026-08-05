_RT_NS = {}
RUNTIME = """
class _Agent:
    def __call__(self):
        global _S_N_CUBICLE
        old_s_n = _S_N_CUBICLE
        _S_N_CUBICLE = True

_S_N_CUBICLE = False

def _perm_fs():
    global _S_N_CUBICLE
    if _S_N_CUBICLE:
        print("CUBICLE")
    else:
        print("NO CUBICLE")
"""
exec(RUNTIME, _RT_NS)
_RT_NS["_perm_fs"]()
