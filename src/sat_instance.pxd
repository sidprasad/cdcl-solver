# C-level declarations for sat_instance.py
# This .pxd file acts as a "C header" — when solver.py is compiled,
# Cython reads this to generate direct struct field access (c->w1)
# instead of Python attribute lookups for Clause instances.

cdef class Clause:
    cdef public list lits        # plain list — Cython uses PyList_GET_ITEM
    cdef public int w1
    cdef public int w2
    cdef public bint learned
