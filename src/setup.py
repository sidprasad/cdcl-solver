"""
Cython build configuration.
"""

from setuptools import setup, Extension
from Cython.Build import cythonize
import sys

# ── Aggressive C compiler flags ──────────────────────────────────
# These are passed straight through to the C compiler.

## Really milking the system here to get away with writing
## Python instead of C. 

extra_compile_args = [
    "-O3",                  # maximum optimisation (vs default -O2)
    "-march=native",        # tune for *this* CPU (SSE/AVX/etc.)
    "-finline-functions",   # inline even without `inline` keyword
    "-funroll-loops",       # unroll small loops
    "-ffast-math",          # allow reordering / fusing FP ops
    "-fomit-frame-pointer", # free up a register on x86
    "-DNDEBUG",             # strip C assert()s
]

extra_link_args = ["-O3"]



# LTO (link-time optimisation) lets the compiler inline *across*
# translation units.  Works on both GCC and Clang.
extra_compile_args.append("-flto")
extra_link_args.append("-flto")

# Cython compiler directives
cython_directives = {
    "boundscheck": False,       # no IndexError checks on list[i]
    "wraparound": False,        # no negative-index support
    "cdivision": True,          # C division semantics (no ZeroDivisionError)
    "nonecheck": False,         # no "is None" guard before attribute access
    "initializedcheck": False,  # no "is uninitialised" check on memoryviews
    "overflowcheck": False,     # no OverflowError on int arithmetic
    "language_level": "3",      # Python 3 semantics
}

modules = ["solver", "sat_instance", "dimacs_parser"]

extensions = [
    Extension(
        name=mod,
        sources=[f"{mod}.py"],
        libraries=["m"],          # link libm for C math (exp, log, etc.)
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
    )
    for mod in modules
]

setup(
    name="sat_solver",
    ext_modules=cythonize(
        extensions,
        compiler_directives=cython_directives,
        annotate=False, 
    ),
)
