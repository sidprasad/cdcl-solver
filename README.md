# Sources

- https://en.wikipedia.org/wiki/Conflict-driven_clause_learning
- GRASP
- https://arxiv.org/abs/1702.08392 for learnign abotu k-CNF phase transitions, density.
    - I thought I would  have some kind of phase transition heuristic (peaked at 4.26 which is what Vardi et al said was a phase transition point for 3-SAT.) However, this didn't seem to help. We were never hitting this path for the harder density instances in the test input suite. 
   - Instead, moved to something Serdar suggested-- just fixed random frequency / diversification.
   - I did briefly toy with the idea of just giving UNSAT for extremely high density. This means my solver would not be complete, however. On the other hand, it would be correct with high probability, and extremly fast on some UNSAT cases.


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


- Clause min: Clause minimization (simple/ccmin-mode-1) implemented. After 1-UIP conflict analysis, each non-asserting literal is checked: if every antecedent in its reason clause is already in the learned clause or at level 0, the literal is removed as redundant.

Key insight during implementation: VSIDS activity bumps must happen on the pre-minimized clause. Bumping after minimization changed the variable ordering heuristic and caused a 2-3x regression. Moving bumps before minimization preserved VSIDS behavior while producing shorter, more powerful learned clauses.



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


## Instance-Adaptive Hyperparameters

Instead of one fixed configuration, the solver classifies instances by their
clause-to-variable density at startup and selects a tuned parameter profile.
This is a zero-runtime-cost optimisation — classification is a single division
before the solve loop.

**Density clusters and rationale:**

| Cluster | Density | `var_decay` | `luby_base` | `random_freq` | `max_learnt_ratio` |
|---|---|---|---|---|---|
| Low (≤ 6) | Structured, large | 0.99 | 512 | 0.005 | 0.50 |
| Medium (6–30) | Phase-transition region | 0.95 | 100 | 0.02 | 0.33 |
| High (> 30) | Massively constrained | 0.85 | 32 | 0.08 | 0.15 |

**Sources / inspiration:**

- **Portfolio approach**: Xu, Hutter, Hoos & Leyton-Brown, "SATzilla: Portfolio-based Algorithm Selection for SAT" (JAIR, 2008). Uses instance features to pick the right solver; we apply the same idea within a single solver by switching hyperparameters.
- **Phase transition**: Vardi et al. The 3-SAT phase transition at density ~4.26 sits inside our low-density cluster; medium starts above it.
- **High-density / rapid restarts**: Dense, hard instances benefit from very frequent restarts.
- **Random diversification**: Higher `random_freq` for dense instances.


## Now, less interesting optimizations for Cython compilation / Minisat inspo

- I worried that CPython compilation was a bottleneck, esp with Dicts. But since CNF variables are 1-indexed positive integers, so we can use lists of size max_var + 1 and index directly. This is basically what MINISAT does as well, they use a dict thing.

| Before (dict)	| After (list)	| Encoding |
--------------------------------------------
assignments: Dict[int, Optional[bool]]| self.assignments: List[int]	 | 0 = unassigned, 1 = True, -1 = False |
levels: Dict[int, int]	| levels: List[int]	| same values, direct index | 
reasons: Dict[int, Optional[int]]| self.reasons: List[int]	|-1 = no reason, Any non-negative integer → the cid of the clause that forced it |
activity: Dict[int, float]	| self.activity: List[float]	| same values, direct index |


Similarly, for Cython infrastructure, I then started moving from Option[...] to using raw ints.

For example, in propagate, there's no reason to deal with Option[bool]. INstead:

- False  < 0
- True  > 0
- Unassigned / None  == 0
- So then checks like is True or is Unassigned can just be simple compilations.


- Next, inlining some function calls (e.g. `get_lit_value`)
