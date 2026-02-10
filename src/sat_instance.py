from dataclasses import dataclass, field
from typing import List, Set


## Modified this slightly from the 
## stencil to add a Clause dataclass, etc.

@dataclass
class Clause:
    # Using a list, since watched literals care about order.
    lits: List[int]
    w1: int = 0 
    w2: int = 1  
    learned: bool = False 

    def __post_init__(self):
        # Just ensure watch indices are valid.
        if len(self.lits) == 0:
            self.w1 = self.w2 = 0
        elif len(self.lits) == 1:
            self.w1 = self.w2 = 0
        else:
            self.w1 = 0
            self.w2 = 1



@dataclass
class SATInstance:
    vars: Set[int] = field(default_factory=set)
    clauses: List[Clause] = field(default_factory=list)
    
    def __init__(self, num_vars: int = 0, num_clauses: int = 0):
        self.vars = set()
        self.clauses = []

    def add_variable(self, literal: int):
        self.vars.add(abs(literal))

    def add_clause(self, clause: Set[int], learned: bool = False) -> int:    
        lits = list(clause)
        for l in lits:
            self.add_variable(l)

        cid = len(self.clauses)
        self.clauses.append(Clause(lits=lits, learned=learned))
        return cid

    @property
    def numVars(self) -> int:
        return len(self.vars)

    @property
    def numClauses(self) -> int:
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
