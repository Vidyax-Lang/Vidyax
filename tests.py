# -*- coding: utf-8 -*-
"""Built-in tests for Vidyax v1.0. Run: python vidyax.py test"""
import io
import contextlib
import vidyax


def run(src):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        vidyax.run_text(src)
    return buf.getvalue()


CASES = [
    ('print "hi"\n', "hi\n"),
    ('x: 5\nprint x + 3\n', "8\n"),
    ('print "a" + "b"\n', "ab\n"),
    ('if 5 > 3:\n    print "yes"\n', "yes\n"),
    ('if 1 > 2:\n    print "a"\nelse:\n    print "b"\n', "b\n"),
    ('if 1 > 2:\n    print "a"\nelif 3 > 1:\n    print "c"\nelse:\n    print "d"\n', "c\n"),
    ('rpt 3:\n    print "x"\n', "x\nx\nx\n"),
    ('for i in [1, 2, 3]:\n    print i\n', "1\n2\n3\n"),
    ('func f(a, b):\n    return a * b\nprint f(4, 5)\n', "20\n"),
    ('print true\nprint false\nprint null\n', "true\nfalse\nnull\n"),
    ('print 10 / 4\n', "2.5\n"),
    ('print not false\n', "true\n"),
    ('print 5 >= 5 and 3 < 4\n', "true\n"),
    ('d: [10, 20, 30]\nprint d[1]\n', "20\n"),
    ('for c in "abc":\n    print c\n', "a\nb\nc\n"),
    ('print len([1, 2, 3])\n', "3\n"),
    ('print range(4)\n', "[0, 1, 2, 3]\n"),
    ('print upper("hi")\n', "HI\n"),
    ('print sum([1, 2, 3, 4])\n', "10\n"),
    ('print join(["a", "b"], "-")\n', "a-b\n"),
    ('func fac(n):\n    if n <= 1:\n        return 1\n    return n * fac(n - 1)\nprint fac(5)\n', "120\n"),
    ('t: 0\nfor i in range(1, 5):\n    t: t + i\nprint t\n', "10\n"),
    ('print type(get("http://0.0.0.0:1"))\n', "text\n"),
    ('try:\n    x: 1 / 0\ncatch e:\n    print "caught: " + e\n', "caught: cannot divide by 0\n"),
    ('try:\n    print 1 / 0\ncatch:\n    print "err"\nprint "after"\n', "err\nafter\n"),
]


def run_all_tests():
    passed = 0
    for i, (src, want) in enumerate(CASES, 1):
        try:
            out = run(src)
            if out == want:
                passed += 1
                print(f"  PASS test {i}")
            else:
                print(f"  FAIL test {i}: got {out!r}, want {want!r}")
        except Exception as e:
            print(f"  FAIL test {i}: error {e}")
    print(f"\n{passed}/{len(CASES)} tests passed")
