# Sources

- https://en.wikipedia.org/wiki/Conflict-driven_clause_learning
- GRASP
- https://arxiv.org/abs/1702.08392 for learnign abotu k-CNF phase transitions, density.
- Led to https://www.cs.utexas.edu/~marijn/publications/rapid.pdf for restarts
   - Luby et al : Sequence of restart sizes based on constant unit run. This is what MiniSat does.
   - "The solver picoSAT [7] introduced a frequent restart strategy in which the
restart length grows geometrically until it reaches a bound. At this point the restart
sequence starts again and the bound grows geometrically."
   - "Another approach, which receives much attention lately, combines an underlying uniform restart strategy with a
dynamic element which can induce, or suppress, restarts. The dynamic decision can be
made according to variable agility [6–8], variety of decision levels in learnt clauses and
backtrack sizes [9, 10], or using local search techniques [11]."


- Direction Heuristics in MiniSat are always -ve: The direction heuristics in MiniSAT are very minimalistic: It uses negative branching: i.e. the decision variable is always assigned to false.
Although it might seem a bit arbitrary, it is not. Two properties of this heuristic contribute the fast performance. First, it consequently chooses the same sign. Therefore it
keeps searching in the same search space. Second, always branching on false is much
better than always branching on true.

## Structure

Needs to have the following structure:
```
/solution
|_ src/
|_ compile.sh
|_ run.sh
|_ runAll.sh
|_ results.log
|_ report.pdf
|_ team.txt
```

### Learnings
- Negative heuristic for lits (a la minisat) better than positive.
- Density heuristic could be improved. Luby gives short initial probes that geometrically grow, letting the solver escape bad search regions early while allowing long runs later.


- Need better decision procedures than pure next. So we use VSIDS. Again, super inspired from minisat.
- I worried that CPython compilation was a bottleneck, esp with Dicts. But since CNF variables are 1-indexed positive integers, so we can use lists of size max_var + 1 and index directly. This is basically what MINISAT does as well, they use a dict thing.

| Before (dict)	| After (list)	| Encoding |
--------------------------------------------
assignments: Dict[int, Optional[bool]]| self.assignments: List[int]	 | 0 = unassigned, 1 = True, -1 = False |
levels: Dict[int, int]	| levels: List[int]	| same values, direct index | 
reasons: Dict[int, Optional[int]]| self.reasons: List[int]	|-1 = no reason |
activity: Dict[int, float]	| self.activity: List[float]	| same values, direct index |

