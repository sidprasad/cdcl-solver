import cython
import array
from typing import List, Set


## Modified this slightly from the
## stencil to add a Clause class, etc.
##
## Now a cdef class via sat_instance.pxd so that w1, w2, learned are
## C struct fields instead of Python __dict__ entries.  Every access in
## the propagate inner loop becomes a direct pointer dereference (c->w1)
## instead of a hash-table lookup.
##
## lits stays as a plain Python list — Cython compiles list[i] into
## PyList_GET_ITEM (a direct C pointer offset), which is faster than
## array.array[i] through a generic object reference.

class Clause:
    lits: list
    w1: cython.int
    w2: cython.int
    learned: cython.bint

    def __init__(self, lits, w1: cython.int = 0, w2: cython.int = 1,
                 learned: cython.bint = False):
        self.lits = list(lits) if not isinstance(lits, list) else lits
        self.learned = learned
        # Ensure watch indices are valid.
        n: cython.int = len(self.lits)
        if n == 0:
            self.w1 = 0; self.w2 = 0
        elif n == 1:
            self.w1 = 0; self.w2 = 0
        else:
            self.w1 = 0; self.w2 = 1


class SATInstance:
    """Regular Python class — not performance-critical (accessed once at
    setup, not in the inner solve loop).  Clause is the hot one."""

    def __init__(self, num_vars: cython.int = 0, num_clauses: cython.int = 0):
        self.vars = set()
        self.clauses = []

    def add_variable(self, literal: cython.int):
        self.vars.add(abs(literal))

    def add_clause(self, lits, learned: cython.bint = False) -> cython.int:
        for l in lits:
            self.add_variable(l)

        cid: cython.int = len(self.clauses)
        self.clauses.append(Clause(lits=lits, learned=learned))
        return cid

    @property
    def numVars(self) -> cython.int:
        return len(self.vars)

    @property
    def numClauses(self) -> cython.int:
        return len(self.clauses)

    def __str__(self) -> str:
        out = []
        out.append(f"Number of variables: {self.numVars}")
        out.append(f"Number of clauses: {self.numClauses}")
        out.append(f"Variables: {sorted(self.vars)}")
        ## Keep the output shape the stencil expects.
        for i, c in enumerate(self.clauses):
            out.append(f"Clause {i}: {c.lits}")
        return "\n".join(out) + "\n"
