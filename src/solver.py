from typing import Set, List, Dict, Optional, Tuple
from collections import defaultdict, deque
from sat_instance import SATInstance
import random
import math
import heapq


## Now these are hyperparameters we can tune and experiment with.
class SATSolver:
    def __init__(
        self,
        inst: SATInstance,
        var_decay: float = 0.95,
        clause_decay: float = 0.999,
        luby_base: int = 100,
        max_learnt: Optional[int] = None,
        max_learnt_min: int = 100,
        max_learnt_ratio: float = 1.0 / 3.0,
        max_learnt_growth: float = 1.1,
        transition: float = 4.26,
        sigma: float = 1.5,
        peak_random_prob: float = 0.5,
    ):
        self.inst = inst
        self.luby_base: int = luby_base
        self.max_learnt_fixed: Optional[int] = max_learnt
        self.max_learnt_min: int = max_learnt_min
        self.max_learnt_ratio: float = max_learnt_ratio
        self.max_learnt_growth: float = max_learnt_growth
        self.random_transition: float = transition
        self.random_sigma: float = sigma
        self.random_peak_prob: float = peak_random_prob

        vars = inst.vars

        ## Flat arrays indexed by variable number (1-based, slot 0 unused).
        ## This gives O(1) direct indexing instead of dict hash lookups.
        ## MiniSat uses the same approach with int8_t[].
        self.max_var: int = max(vars) if vars else 0
        n = self.max_var + 1  # array size

        ## Assignment: 0 = unassigned, 1 = True, -1 = False
        self.assignments: List[int] = [0] * n
        ## Decision level of each variable.
        self.levels: List[int] = [0] * n
        ## Reason clause ID for each variable. -1 = no reason (decision or unassigned).
        self.reasons: List[int] = [-1] * n
        ## VSIDS activity scores.
        self.activity: List[float] = [0.0] * n


        ## Needed for non-chronological backtracking.
        ## Literal assignment order.
        self.assignment_log: List[int] = []
    
        ## Index in assignment_log where each decision level starts.
        self.level_start: List[int] = []
        ## TODO: Could we optimize this with better data structures?  For example, instead of a list of all assigned literals, we could have a stack for each decision level.  Then backtracking just pops from the stacks.
        ## TODO: Could level start be a heap?

        ## The assignment whose implications are yet to be propagated.
        self.next_to_propagate: int  = 0

        ## Tracking unassigned variables. If none, we're done, else we can use this for random decisions.
        self.unassigned_set: Set[int] = set(vars)

        ## Adapted from MINISATS Variable State Independent Decaying Sum Algorithm.
        ## Activity scores are in self.activity[] (flat array above).
        ## - Every variable starts with an activity score of 0.
        ## - Whenever a conflict occurs, the
        ##   variables involved in the learned clause have their activity scores increased by `var_inc`.
        ## - After every conflict, ALL activity scores are divided by a decay factor.
        ##  Instead of touching every score, we increase `var_inc` by decay factor so that future increases are worth more.
        self.var_inc: float = 1.0 
        self.var_decay: float = var_decay       # This is something we can tune/ experiment with. Smaller values make older conflicts 
        # decay faster, so the solver focuses more on recent conflicts. Larger values retain more history, which could be good but
        ## present an issue when search gets deep.

        ## Max-heap ordered by activity. Negation since heapq is a min-heap by default.
        self.var_heap: List[Tuple[float, int]] = [(0.0, v) for v in vars]
        heapq.heapify(self.var_heap)

        ## ── Clause activity (for learned clause deletion) ────────────
        ## Mirrors VSIDS but for clauses: recently-useful learned clauses
        ## get bumped, older ones decay.  On cleanup we keep the top half
        ## by activity and delete the rest.
        self.clause_activity: Dict[int, float] = {}   # cid -> activity
        self.clause_inc: float = 1.0
        self.clause_decay: float = clause_decay
        ## How many learned clauses before we trigger a cleanup.
        self.max_learnt: int = max_learnt if max_learnt is not None else max_learnt_min
        ## Track which cids are learned and alive (not deleted).
        self.alive_learned: Set[int] = set()

        ## Maps a literal to the list of clause IDs watching it.
        self.watch_list: Dict[int, List[int]] = defaultdict(list)
        self._init_watches()

    def _init_watches(self) -> None:
        for cid, c in enumerate(self.inst.clauses):
            if len(c.lits) == 0:
                continue

            if len(c.lits) == 1:
                ## Dont need to append twice here, since 
                ## our propagation logic will handle it.
                self.watch_list[c.lits[0]].append(cid)
            else:
                self.watch_list[c.lits[c.w1]].append(cid)
                self.watch_list[c.lits[c.w2]].append(cid)


    ## Helper for VSIDS.
    def bump_activity(self, var: int) -> None:
        self.activity[var] += self.var_inc
        # Rescale if scores get dangerously large (avoids float overflow)
        if self.activity[var] > 1e100:
            for i in range(len(self.activity)):
                self.activity[i] *= 1e-100
            self.var_inc *= 1e-100
        heapq.heappush(self.var_heap, (-self.activity[var], var))

    def decay_activity(self) -> None:
        self.var_inc /= self.var_decay

    ## Clause activity helpers to prevent 
    ## the learned clause DB from exploding in size.
    def bump_clause_activity(self, cid: int) -> None:
        if cid not in self.clause_activity:
            return
        self.clause_activity[cid] += self.clause_inc
        # Same rescaling idea as variable activity to avoid float overflow.
        if self.clause_activity[cid] > 1e100:
            for c in self.clause_activity:
                self.clause_activity[c] *= 1e-100
            self.clause_inc *= 1e-100

    def decay_clause_activity(self) -> None:
        ## Same idea as VSIDS: inflate the increment instead of shrinking every score.
        ## Saves a small increment of time since its O(1) instead of O(num learned clauses).
        self.clause_inc /= self.clause_decay


    # When the number of learned clauses gets too large, 
    # we delete some to save memory and speed up propagation.
    # THis is also something MINISat does.
    def reduce_db(self) -> None:
        if not self.alive_learned:
            return

        # Determine which cids are locked (reason for a current assignment)
        locked: Set[int] = set()
        for v in self.inst.vars:
            r = self.reasons[v]
            if r != -1 and r in self.alive_learned:
                locked.add(r)

        # Sort removable learned clauses by activity (ascending)
        removable = [(self.clause_activity.get(cid, 0.0), cid)
                     for cid in self.alive_learned if cid not in locked]
        removable.sort()

        # Keep only half of the removable clauses.
        n_to_delete = len(removable) // 2
        for idx in range(n_to_delete):
            cid = removable[idx][1]
            self.delete_clause(cid)

    def delete_clause(self, cid: int) -> None:
        c = self.inst.clauses[cid]
        # Remove from watch lists
        if len(c.lits) >= 1:
            lit1 = c.lits[c.w1]
            wl = self.watch_list.get(lit1)
            if wl is not None:
                try: wl.remove(cid)
                except ValueError: pass
        if len(c.lits) >= 2:
            lit2 = c.lits[c.w2]
            wl = self.watch_list.get(lit2)
            if wl is not None:
                try: wl.remove(cid)
                except ValueError: pass
        # Hollow out the clause
        c.lits = []
        c.w1 = 0
        c.w2 = 0
        self.alive_learned.discard(cid)
        self.clause_activity.pop(cid, None)
        # Clear any reason references pointing to this clause
        for v in self.inst.vars:
            if self.reasons[v] == cid:
                self.reasons[v] = -1

    def get_level(self, literal: int) -> int:
        v = abs(literal)
        return self.levels[v]
    
    def get_lit_value(self, literal: int) -> Optional[bool]:
        v = abs(literal)
        val = self.assignments[v]
        if val == 0:
            return None  # unassigned
        # val is 1 (True) or -1 (False) for the variable;
        # for a negative literal, flip it.
        if literal > 0:
            return val == 1
        else:
            return val == -1
    
    def get_current_level(self) -> int:
        return len(self.level_start)

    def assign_lit(self, lit: int, reason_cid: Optional[int]) -> bool:
        v = abs(lit)
        val = 1 if lit > 0 else -1
        cur = self.assignments[v]
        if cur != 0:
            return cur == val  # must be consistent

        self.assignments[v] = val
        self.unassigned_set.discard(v)

        self.levels[v] = self.get_current_level()
        self.reasons[v] = reason_cid if reason_cid is not None else -1
        self.assignment_log.append(lit)

        return True

    # New decision level
    def decide(self, lit: int) -> bool:

        self.level_start.append(len(self.assignment_log))
        return self.assign_lit(lit, reason_cid=None)

    def backjump(self, level: int) -> None:
        if level < 0 or level > len(self.level_start):
            raise ValueError("Cannot backjump to level {}".format(level))
        cutoff = self.level_start[level] if level < len(self.level_start) else len(self.assignment_log)

        # Reset everythign above the cutoff.
        for lit in self.assignment_log[cutoff:]:
            v = abs(lit)
            self.assignments[v] = 0
            self.levels[v] = 0
            self.reasons[v] = -1
            self.unassigned_set.add(v)
            heapq.heappush(self.var_heap, (-self.activity[v], v))
        
        # And erase history.
        self.assignment_log = self.assignment_log[:cutoff]
        self.level_start = self.level_start[:level]
        self.next_to_propagate = min(self.next_to_propagate, len(self.assignment_log))



        
    # Now unit propagation with watched literals
    # Returns the conflicting clause ID, or None if no conflict.
    def propagate(self) -> Optional[int]:
        ## This is the complex part.
        ## Unlike DPLL, we look at clauses watching the negation of the assigned literal.

        while self.next_to_propagate < len(self.assignment_log):
            literal = self.assignment_log[self.next_to_propagate]
            self.next_to_propagate += 1

            neg_literal = -literal

            ## In-place filtering: read pointer (i) advances over every entry, write pointer (j) only advances for entries we keep.
            ## Entries that move their watch to another literal are dropped
            ## implicitly (j doesn't advance), so no remove() or `in` check needed.
            wl = self.watch_list[neg_literal]
            i = 0
            j = 0
            conflict_cid = None
            while i < len(wl):
                cid = wl[i]
                i += 1
                c = self.inst.clauses[cid]
                num_lits = len(c.lits)

                if num_lits == 0:
                    # Keep remaining entries and report conflict
                    wl[j] = cid; j += 1
                    conflict_cid = cid
                    break
                elif num_lits == 1:
                    # Unit clause — keep watching, try to propagate
                    wl[j] = cid; j += 1
                    l = c.lits[0]
                    val = self.get_lit_value(l)
                    if val is False:
                        conflict_cid = cid; break
                    elif val is None:
                        if not self.assign_lit(l, reason_cid=cid):
                            conflict_cid = cid; break
                    continue
                elif num_lits == 2:
                    l1 = c.lits[c.w1]
                    l2 = c.lits[c.w2]

                    if l1 == neg_literal:
                        other_idx = c.w2
                    elif l2 == neg_literal:
                        other_idx = c.w1
                    else:
                        # Stale
                        continue

                    # Binary clause: can't move the watch, always keep it
                    wl[j] = cid; j += 1
                    other_lit = c.lits[other_idx]
                    other_val = self.get_lit_value(other_lit)
                    if other_val is False:
                        conflict_cid = cid; break
                    elif other_val is None:
                        if not self.assign_lit(other_lit, reason_cid=cid):
                            conflict_cid = cid; break
                    continue
                else:
                    # General case (>=3 literals): try to find a replacement watch
                    if c.lits[c.w1] == neg_literal:
                        watched_idx = c.w1
                        other_idx = c.w2
                    elif c.lits[c.w2] == neg_literal:
                        watched_idx = c.w2
                        other_idx = c.w1
                    else:
                        # Stale
                        continue

                    replaced = False
                    for k, lit2 in enumerate(c.lits):
                        if k == other_idx:
                            continue
                        val2 = self.get_lit_value(lit2)
                        if val2 is True or val2 is None:
                            # Move the watch to lit2
                            if watched_idx == c.w1:
                                c.w1 = k
                            else:
                                c.w2 = k
                            self.watch_list[lit2].append(cid)
                            # Don't copy cid to wl[j] — effectively removed
                            replaced = True
                            break

                    if replaced:
                        continue

                    # No replacement — keep watching, propagate or conflict
                    wl[j] = cid; j += 1
                    other_lit = c.lits[other_idx]
                    other_val = self.get_lit_value(other_lit)
                    if other_val is False:
                        conflict_cid = cid; break
                    if other_val is None:
                        if not self.assign_lit(other_lit, reason_cid=cid):
                            conflict_cid = cid; break
                    continue

            # On early exit (conflict), copy remaining entries we haven't looked at
            while i < len(wl):
                wl[j] = wl[i]
                i += 1; j += 1
            # Truncate the list to the write pointer
            del wl[j:]

            if conflict_cid is not None:
                return conflict_cid
        return None   


    ## SO I think real speedups will come from optimizing conflict analysis.
    ## We're trying with the first Unique Implication Point (UIP) in the implication graph. 
    def analyze_conflict(self, conflict_cid: int) -> Tuple[Optional[List[int]], int]:
        if len(self.level_start) == 0:
            # Conflict at level 0 - UNSAT
            return None, -1
        
        current_level = self.get_current_level()
        conflict_clause = self.inst.clauses[conflict_cid]
        
        ## Prevents conflation between variables and lits.
        learned: Dict[int, int] = {}
        for lit in conflict_clause.lits:
            v = abs(lit)         
            learned[v] = lit
        
        # Count literals at current decision level
        def count_at_current_level() -> int:
            return sum(1 for v in learned if self.levels[v] == current_level)
        
        current_level_count = count_at_current_level()
        
        # Walk backwards through assignment log to resolve to first UIP
        i = len(self.assignment_log) - 1
        while current_level_count > 1 and i >= 0:
            # Get the assigned literal (the one that became true)
            assigned_lit = self.assignment_log[i]
            i -= 1
            v = abs(assigned_lit)
            
            # Check if this variable is in our learned clause
            if v not in learned:
                continue
            
            # The literal in learned clause must be the negation of assigned_lit
            # (since all literals in a conflict clause are false)
            lit_in_learned = learned[v]
            
            # Can only resolve on implied literals (not decisions)
            reason_cid = self.reasons[v]
            if reason_cid == -1:
                continue

            ## Bump clause activity: this reason clause was useful in analysis.
            self.bump_clause_activity(reason_cid)

            # Resolve: remove this variable, add other literals from reason clause
            del learned[v]
            
            reason_clause = self.inst.clauses[reason_cid]
            for reason_lit in reason_clause.lits:
                rv = abs(reason_lit)
                if rv != v and rv not in learned:
                    learned[rv] = reason_lit
            
            current_level_count = count_at_current_level()
        
        if not learned:
            return None, -1
        
        # Build learned clause with asserting literal first
        # The asserting literal is the one at current_level (should be exactly one)
        asserting_lit = None
        other_lits: List[int] = []
        backjump_level = 0
        
        for v, lit in learned.items():
            level = self.levels[v]
            if level == current_level:
                asserting_lit = lit
            else:
                other_lits.append(lit)
                if level > backjump_level:
                    backjump_level = level
        
        # Put asserting literal first in the learned clause
        if asserting_lit is not None:
            learned_clause = [asserting_lit] + other_lits
        else:
            learned_clause = other_lits
            backjump_level = 0

        ## VSIDS: increase activity for every variable in the learned clause.
        if learned_clause is not None:
            for lit in learned_clause:
                self.bump_activity(abs(lit))
        ## VSIDS: make older increments worth less relative to future ones.
        self.decay_activity()
        self.decay_clause_activity()

        return learned_clause, backjump_level



    ## Luby restart sequence (Luby, Sinclair & Zuckerman 1993).
    @staticmethod
    def luby(i: int) -> int:
        # Find the largest power of 2 <= i+1
        k = 1
        while k * 2 <= i + 1:
            k *= 2
        if k == i + 1:
            return k
        return SATSolver.luby(i - k + 1)


    def solve(self) -> Tuple[bool, Optional[Dict[int, bool]]]:
        # Initial propagation at level 0
        conflict = self.propagate()
        if conflict is not None:
            return False, None  # unsat


        ## Luby restarts: budget = luby(restart_number) * base_unit
        luby_base = self.luby_base  # base conflicts per Luby unit
        restart_number = 1
        max_conflicts = self.luby(restart_number) * luby_base
        conflict_count = 0

        ## Density-based randomness: use ORIGINAL clause count so learned
        ## clauses don't inflate the density over time.
        n_orig_clauses = sum(1 for c in self.inst.clauses if not c.learned)
        n_vars = len(self.inst.vars)
        density = n_orig_clauses / max(1, n_vars)

        ## Set the learned clause limit for reduce_db.
        if self.max_learnt_fixed is not None:
            self.max_learnt = self.max_learnt_fixed
        else:
            computed = int(n_orig_clauses * self.max_learnt_ratio)
            self.max_learnt = computed if computed > self.max_learnt_min else self.max_learnt_min

        ## Gaussian-shaped random decision probability, peaked at the 3-SAT phase transition (~4.26).  Far from the transition
        ## instances are easier, so deterministic negative branching
        ## is fine; near it we inject randomness to escape hard regions.
        ## This is sort of in line with what Serdar mentioned about randomness in class.
        transition = self.random_transition
        sigma = self.random_sigma
        peak_prob = self.random_peak_prob
        rand_prob = peak_prob * math.exp(-((density - transition) ** 2) / (2.0 * sigma * sigma))

        while True:

            if not self.unassigned_set:
                model = {v: (self.assignments[v] == 1) for v in self.inst.vars}
                return True, model

            # If we are near a phase transition, inject some randomness.
            if random.random() < rand_prob:
                ## Random variable + random polarity
                next_var = random.choice(tuple(self.unassigned_set))
                sign = random.choice([1, -1])
                self.decide(sign * next_var)
            else:
                ## Else, use the VSIDS heuristic to pick the highest-activity unassigned variable.
                next_var = None
                while self.var_heap:
                    neg_act, candidate = heapq.heappop(self.var_heap)
                    if candidate in self.unassigned_set:
                        next_var = candidate
                        break
                ## Fallback: if heap is exhausted but we still have unassigned variables, pick any
                if next_var is None:
                    next_var = next(iter(self.unassigned_set))
                ## Negative heuristic, as Haim et al mention is often better in practice.
                self.decide(-1 * next_var)

            
            # Propagate and handle conflicts
            while True:
                conflict = self.propagate()
                
                if conflict is None:
                    break  # No conflict, continue to next decision
                
                conflict_count += 1
                
                # Luby restart
                if conflict_count >= max_conflicts:
                    self.backjump(0)
                    conflict_count = 0
                    restart_number += 1
                    max_conflicts = self.luby(restart_number) * luby_base
                    #print(f"(Restart #{restart_number}, next conflict budget: {max_conflicts})")
                    break
                
                # Analyze conflict and determine backjump level
                learned_clause, backjump_level = self.analyze_conflict(conflict)
                
                if backjump_level < 0:
                    # UNSAT
                    return False, None
                
                # Non-chronological backjump
                self.backjump(backjump_level)
                
                # Add learned clause and set up watches
                if learned_clause is not None and len(learned_clause) > 0:
                    # Asserting literal is first in the clause
                    asserting_lit = learned_clause[0]
                    
                    cid = self.inst.add_clause(set(learned_clause), learned=True)
                    c = self.inst.clauses[cid]

                    ## Register with clause activity tracking.
                    self.clause_activity[cid] = 0.0
                    self.alive_learned.add(cid)
                    
                    # Set up watches for the new clause
                    if len(c.lits) == 1:
                        self.watch_list[c.lits[0]].append(cid)
                    elif len(c.lits) >= 2:
                        self.watch_list[c.lits[c.w1]].append(cid)
                        self.watch_list[c.lits[c.w2]].append(cid)

                    ## If we've accumulated too many learned clauses, clean up.
                    if len(self.alive_learned) > self.max_learnt:
                        self.reduce_db()
                        ## Gradually allow more clauses (MiniSat grows this over time).
                        self.max_learnt = int(self.max_learnt * self.max_learnt_growth)
                    
                    # Assign the asserting literal and loop to propagate it
                    self.assign_lit(asserting_lit, reason_cid=cid)
                    # Continue the inner while loop to propagate
