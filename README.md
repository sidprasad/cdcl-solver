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

#### Input Instance Densities

| Instance | Variables | Clauses | Density (clauses/vars) |
|---|---|---|---|
| C1065_064.cnf | 50 | 1065 | 21.30 |
| C1065_082.cnf | 50 | 1065 | 21.30 |
| C140.cnf | 1841 | 6306 | 3.43 |
| C1597_024.cnf | 75 | 1597 | 21.29 |
| C1597_060.cnf | 75 | 1597 | 21.29 |
| C1597_081.cnf | 75 | 1597 | 21.29 |
| C168_128.cnf | 1698 | 5425 | 3.19 |
| C175_145.cnf | 175 | 14577 | 83.30 |
| C181_3151.cnf | 181 | 3151 | 17.41 |
| C200_1806.cnf | 200 | 1806 | 9.03 |
| C208_120.cnf | 1608 | 5278 | 3.28 |
| C208_3254.cnf | 1876 | 7334 | 3.91 |
| C210_30.cnf | 1789 | 7426 | 4.15 |
| C210_55.cnf | 1755 | 5781 | 3.29 |
| C243_188.cnf | 24356 | 1884008 | 77.35 |
| C289_179.cnf | 28902 | 179895 | 6.22 |
| C459_4675.cnf | 459 | 4675 | 10.19 |
| C53_895.cnf | 5356 | 89506 | 16.71 |
| U50_1065_038.cnf | 50 | 1065 | 21.30 |
| U50_1065_045.cnf | 50 | 1065 | 21.30 |
| U50_4450_035.cnf | 50 | 4450 | 89.00 |
| U75_1597_024.cnf | 75 | 1597 | 21.29 |

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