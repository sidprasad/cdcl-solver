from typing import Set, List, Dict, Optional, Tuple  # Optional kept for solve() return type
from collections import defaultdict, deque
from sat_instance import SATInstance
import random
import heapq
import array
import cython


## Now these are hyperparameters we can tune and experiment with.
class SATSolver:
    def __init__(
        self,
        inst: SATInstance,
        var_decay: float = 0.95,
        clause_decay: float = 0.999,
        luby_base: int = 100,
        max_learnt: int = -1,
        max_learnt_min: int = 100,
        max_learnt_ratio: float = 1.0 / 3.0,
        max_learnt_growth: float = 1.1,
        random_freq: float = 0.02,
    ):
        self.inst = inst
        self.luby_base: int = luby_base
        self.max_learnt_fixed: int = max_learnt
        self.max_learnt_min: int = max_learnt_min
        self.max_learnt_ratio: float = max_learnt_ratio
        self.max_learnt_growth: float = max_learnt_growth
        self.random_freq: float = random_freq

        vars = inst.vars

        ## Flat arrays indexed by variable number (1-based, slot 0 unused).
        ## This gives O(1) direct indexing instead of dict hash lookups.
        ## MiniSat uses the same approach with int8_t[].
        self.max_var: int = max(vars) if vars else 0
        n = self.max_var + 1  # array size

        ## Assignment: 0 = unassigned, 1 = True, -1 = False
        ## array.array('i') gives Cython typed memoryview access.
        self.assignments = array.array('i', [0] * n)
        ## Decision level of each variable.
        self.levels = array.array('i', [0] * n)
        ## Reason clause ID for each variable. -1 = no reason (decision or unassigned).
        self.reasons = array.array('i', [-1] * n)
        ## VSIDS activity scores.
        self.activity = array.array('d', [0.0] * n)

        ## Reusable flat buffer for analyze_conflict.
        self._learned_buf = array.array('i', [0] * n)

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

        ## Mirrors VSIDS but for clauses: recently-useful learned clauses
        ## get bumped, older ones decay.  On cleanup we keep the top half
        ## by activity and delete the rest.
        self.clause_activity: Dict[int, float] = {}   # cid -> activity
        self.clause_inc: float = 1.0
        self.clause_decay: float = clause_decay
        ## LBD (Literal Block Distance) = number of distinct decision levels
        ## in a learned clause.  Glucose (Audemard & Simon, IJCAI 2009) showed
        ## that LBD is a much better quality metric than clause size or activity.
        ## Clauses with LBD <= 2 ("glue clauses") are almost always useful and
        ## are kept permanently.
        self.clause_lbd: Dict[int, int] = {}   # cid -> LBD
        ## How many learned clauses before we trigger a cleanup.
        self.max_learnt: int = max_learnt if max_learnt >= 0 else max_learnt_min
        ## Track which cids are learned and alive (not deleted).
        self.alive_learned: Set[int] = set()

        ## Maps a literal to the list of clause IDs watching it.
        ## Flat list indexed by (literal + max_var) eliminates dict hash lookups.
        ## Literals range from -max_var to +max_var, so size = 2*max_var+1.
        ## Inner arrays are array.array('i') so propagate can cast to typed
        ## memoryview for direct C-level index access in the hot loop.
        self._wl_off: int = self.max_var
        self.watch_list = [array.array('i') for _ in range(2 * self.max_var + 1)]
        self._init_watches()

    def _init_watches(self) -> None:
        wl_off = self._wl_off
        watch_list = self.watch_list
        for cid, c in enumerate(self.inst.clauses):
            if len(c.lits) == 0:
                continue

            if len(c.lits) == 1:
                ## Dont need to append twice here, since 
                ## our propagation logic will handle it.
                watch_list[c.lits[0] + wl_off].append(cid)
            else:
                watch_list[c.lits[c.w1] + wl_off].append(cid)
                watch_list[c.lits[c.w2] + wl_off].append(cid)


    ## Helper for VSIDS.
    @cython.boundscheck(False)
    @cython.wraparound(False)
    def bump_activity(self, var: cython.int) -> None:
        activity: cython.double[:] = self.activity
        v: cython.int = var
        activity[v] += self.var_inc
        # Rescale if scores get dangerously large (avoids float overflow)
        if activity[v] > 1e100:
            i: cython.int
            for i in range(len(self.activity)):
                activity[i] *= 1e-100
            self.var_inc *= 1e-100
        heapq.heappush(self.var_heap, (-activity[v], var))

    ## Clause activity helpers to prevent 
    ## the learned clause DB from exploding in size.
    @cython.boundscheck(False)
    @cython.wraparound(False)
    def bump_clause_activity(self, cid: int) -> None:
        if cid not in self.clause_activity:
            return
        self.clause_activity[cid] += self.clause_inc
        # Same rescaling idea as variable activity to avoid float overflow.
        if self.clause_activity[cid] > 1e100:
            for c in self.clause_activity:
                self.clause_activity[c] *= 1e-100
            self.clause_inc *= 1e-100


    # When the number of learned clauses gets too large, 
    # we delete some to save memory and speed up propagation.
    # THis is also something MINISat does.
    @cython.boundscheck(False)
    @cython.wraparound(False)
    def reduce_db(self) -> None:
        if not self.alive_learned:
            return

        # Determine which cids are locked (reason for a current assignment)
        reasons: cython.int[:] = self.reasons
        locked: Set[int] = set()
        _v: cython.int
        for _v in self.inst.vars:
            r = reasons[_v]
            if r != -1 and r in self.alive_learned:
                locked.add(r)

        # Collect removable clauses: skip locked and glue (LBD <= 2).
        # Sort by (LBD, -activity) so high-LBD low-activity clauses die first.
        clause_lbd = self.clause_lbd
        removable = []
        for cid in self.alive_learned:
            if cid in locked:
                continue
            lbd = clause_lbd.get(cid, 100)
            if lbd <= 2:
                continue  # glue clause — always keep
            removable.append((lbd, -self.clause_activity.get(cid, 0.0), cid))
        removable.sort()

        # Delete the worse half of removable clauses.
        n_to_delete = len(removable) // 2
        clauses = self.inst.clauses
        cact = self.clause_activity
        deleted_cids = set()
        for idx in range(n_to_delete):
            cid = removable[idx][2]
            c = clauses[cid]
            c.lits = []
            c.w1 = 0
            c.w2 = 0
            deleted_cids.add(cid)
            cact.pop(cid, None)
            clause_lbd.pop(cid, None)
        # Bulk set subtraction — faster than N individual discards
        self.alive_learned -= deleted_cids

    # def get_level(self, literal: int) -> int:
    #     v = abs(literal)
    #     return self.levels[v]
    

    @cython.boundscheck(False)
    @cython.wraparound(False)
    def get_lit_value(self, literal: int) -> int:
        """Return 1 (satisfied), -1 (falsified), or 0 (unassigned)."""
        v = abs(literal)
        val = self.assignments[v]
        # val is 1 (True) or -1 (False) for the variable, 0 unassigned.
        # For a negative literal, flip the sign.
        if literal > 0:
            return val
        else:
            return -val
    
    def get_current_level(self) -> int:
        return len(self.level_start)

    @cython.boundscheck(False)
    @cython.wraparound(False)
    def assign_lit(self, lit: int, reason_cid: int) -> bool:
        assignments: cython.int[:] = self.assignments
        levels: cython.int[:] = self.levels
        reasons: cython.int[:] = self.reasons
        v: cython.int = abs(lit)
        val: cython.int = 1 if lit > 0 else -1
        cur: cython.int = assignments[v]
        if cur != 0:
            return cur == val  # must be consistent

        assignments[v] = val
        self.unassigned_set.discard(v)

        levels[v] = self.get_current_level()
        reasons[v] = reason_cid
        self.assignment_log.append(lit)

        return True

    # New decision level
    def decide(self, lit: int) -> bool:

        self.level_start.append(len(self.assignment_log))
        return self.assign_lit(lit, reason_cid=-1)

    @cython.boundscheck(False)
    @cython.wraparound(False)
    def backjump(self, level: int) -> None:
        if level < 0 or level > len(self.level_start):
            raise ValueError("Cannot backjump to level {}".format(level))
        cutoff = self.level_start[level] if level < len(self.level_start) else len(self.assignment_log)

        assignments: cython.int[:] = self.assignments
        levels: cython.int[:] = self.levels
        reasons: cython.int[:] = self.reasons
        activity: cython.double[:] = self.activity

        # Reset everything above the cutoff.
        _bv: cython.int
        for lit in self.assignment_log[cutoff:]:
            _bv = abs(lit)
            assignments[_bv] = 0
            levels[_bv] = 0
            reasons[_bv] = -1
            self.unassigned_set.add(_bv)
            heapq.heappush(self.var_heap, (-activity[_bv], _bv))
        
        # And erase history.
        self.assignment_log = self.assignment_log[:cutoff]
        self.level_start = self.level_start[:level]
        self.next_to_propagate = min(self.next_to_propagate, len(self.assignment_log))



        
    # Unit propagation with 2-watched literals.
    # Returns the conflicting clause ID, or -1 if no conflict.
    @cython.boundscheck(False)
    @cython.wraparound(False)
    def propagate(self) -> int:
        assignment_log = self.assignment_log
        assignments: cython.int[:] = self.assignments
        wl_off: cython.int = self._wl_off
        watch_list = self.watch_list
        clauses = self.inst.clauses

        # All C-typed locals for the inner loop — no Python objects.
        _v: cython.int
        _a: cython.int
        val: cython.int
        cid: cython.int
        num_lits: cython.int
        ri: cython.int          # read index into watch list
        wi: cython.int          # write index (compaction)
        n: cython.int
        k: cython.int
        found: cython.int       # 1 = replacement watch found (replaces Python bool)
        conflict_cid: cython.int

        while self.next_to_propagate < len(assignment_log):
            literal = assignment_log[self.next_to_propagate]
            self.next_to_propagate += 1
            neg_literal = -literal

            # In-place compaction: ri scans every entry, wi tracks entries
            # we keep.  Entries whose watch moves elsewhere are simply
            # skipped (wi doesn't advance).  Zero allocation.
            wl = watch_list[neg_literal + wl_off]
            wl_buf: cython.int[:] = wl
            ri = 0
            wi = 0
            n = len(wl_buf)
            conflict_cid = -1

            while ri < n:
                cid = wl_buf[ri]; ri += 1
                c = clauses[cid]
                lits = c.lits
                num_lits = len(lits)

                if num_lits == 0:
                    continue  # deleted clause — drop

                if num_lits == 1:
                    wl_buf[wi] = cid; wi += 1
                    _v = abs(lits[0]); _a = assignments[_v]
                    val = _a if lits[0] > 0 else -_a
                    if val < 0:
                        conflict_cid = cid; break
                    if val == 0 and not self.assign_lit(lits[0], reason_cid=cid):
                        conflict_cid = cid; break
                    continue

                if num_lits == 2:
                    if lits[c.w1] == neg_literal:
                        other_lit = lits[c.w2]
                    elif lits[c.w2] == neg_literal:
                        other_lit = lits[c.w1]
                    else:
                        continue  # stale
                    wl_buf[wi] = cid; wi += 1
                    _v = abs(other_lit); _a = assignments[_v]
                    val = _a if other_lit > 0 else -_a
                    if val < 0:
                        conflict_cid = cid; break
                    if val == 0 and not self.assign_lit(other_lit, reason_cid=cid):
                        conflict_cid = cid; break
                    continue

                # >=3 literals: try to move the falsified watch
                if lits[c.w1] == neg_literal:
                    watched_idx = c.w1; other_idx = c.w2
                elif lits[c.w2] == neg_literal:
                    watched_idx = c.w2; other_idx = c.w1
                else:
                    continue  # stale

                found = 0
                k = 0
                while k < num_lits:
                    if k != other_idx:
                        lit2 = lits[k]
                        _v = abs(lit2); _a = assignments[_v]
                        val = _a if lit2 > 0 else -_a
                        if val >= 0:
                            if watched_idx == c.w1:
                                c.w1 = k
                            else:
                                c.w2 = k
                            watch_list[lit2 + wl_off].append(cid)
                            found = 1
                            break
                    k += 1

                if found:
                    continue  # watch moved; not kept here

                # Can't move watch — keep it, propagate the other literal
                wl_buf[wi] = cid; wi += 1
                other_lit = lits[other_idx]
                _v = abs(other_lit); _a = assignments[_v]
                val = _a if other_lit > 0 else -_a
                if val < 0:
                    conflict_cid = cid; break
                if val == 0 and not self.assign_lit(other_lit, reason_cid=cid):
                    conflict_cid = cid; break

            # Copy unprocessed entries on early exit, then truncate.
            while ri < n:
                wl_buf[wi] = wl_buf[ri]; ri += 1; wi += 1
            # Release the memoryview before resizing the underlying array.
            wl_buf = None
            del wl[wi:]

            if conflict_cid >= 0:
                return conflict_cid

        return -1


    ## 1-UIP conflict analysis with LBD computation.
    @cython.boundscheck(False)
    @cython.wraparound(False)
    def analyze_conflict(self, conflict_cid: int) -> Tuple[List[int], int, int]:
        if len(self.level_start) == 0:
            # Conflict at level 0 - UNSAT
            return [], -1, 0
        
        current_level = self.get_current_level()
        conflict_clause = self.inst.clauses[conflict_cid]
        
        ## Flat array replaces Dict[int, int]: learned_buf[v] = literal (0 = absent).
        ## Every lookup/insert/delete is a single C array index instead of a dict hash.
        learned_buf: cython.int[:] = self._learned_buf
        learned_trail: List[int] = []  # variables touched (for iteration + cleanup)
        learned_count: cython.int = 0
        ## Running counter of literals at the current decision level.
        current_level_count: cython.int = 0
        levels: cython.int[:] = self.levels
        reasons: cython.int[:] = self.reasons
        v: cython.int
        rv: cython.int
        tv: cython.int
        tlit: cython.int
        lv: cython.int
        for lit in conflict_clause.lits:
            v = abs(lit)
            if learned_buf[v] == 0:
                learned_trail.append(v)
                learned_count += 1
            learned_buf[v] = lit
            if levels[v] == current_level:
                current_level_count += 1
        
        # Walk backwards through assignment log to resolve to first UIP
        i: cython.int = len(self.assignment_log) - 1
        while current_level_count > 1 and i >= 0:
            assigned_lit = self.assignment_log[i]
            i -= 1
            v = abs(assigned_lit)
            
            # Check if this variable is in our learned clause
            if learned_buf[v] == 0:
                continue
            
            # Can only resolve on implied literals (not decisions)
            reason_cid = reasons[v]
            if reason_cid == -1:
                continue

            ## Bump clause activity: this reason clause was useful in analysis.
            self.bump_clause_activity(reason_cid)

            # Resolve: remove this variable, add other literals from reason clause
            learned_buf[v] = 0
            learned_count -= 1
            current_level_count -= 1
            
            reason_clause = self.inst.clauses[reason_cid]
            for reason_lit in reason_clause.lits:
                rv = abs(reason_lit)
                if rv != v and learned_buf[rv] == 0:
                    learned_buf[rv] = reason_lit
                    learned_trail.append(rv)
                    learned_count += 1
                    if levels[rv] == current_level:
                        current_level_count += 1
        
        if learned_count == 0:
            # Cleanup buffer
            for tv in learned_trail:
                learned_buf[tv] = 0
            return [], -1, 0

        # Build learned clause with asserting literal first
        asserting_lit = None
        other_lits: List[int] = []
        backjump_level: cython.int = 0
        
        for tv in learned_trail:
            tlit = learned_buf[tv]
            if tlit == 0:
                continue  # deleted during resolution
            lv = levels[tv]
            if lv == current_level:
                asserting_lit = tlit
            else:
                other_lits.append(tlit)
                if lv > backjump_level:
                    backjump_level = lv
        
        # Put asserting literal first in the learned clause
        if asserting_lit is not None:
            learned_clause = [asserting_lit] + other_lits
        else:
            learned_clause = other_lits
            backjump_level = 0

        ## LBD = number of distinct decision levels in the learned clause.
        ## Computed via a small set over the levels we already collected.
        lbd_set: Set[int] = set()
        for tv in learned_trail:
            tlit = learned_buf[tv]
            if tlit != 0:
                lbd_set.add(levels[tv])
        lbd: int = len(lbd_set)

        ## VSIDS: increase activity for every variable in the learned clause.
        if learned_clause is not None:
            for lit in learned_clause:
                self.bump_activity(abs(lit))
        ## VSIDS: make older increments worth less relative to future ones.
        self.var_inc /= self.var_decay

        ## Same idea as VSIDS: inflate the increment instead of shrinking every score.
        self.clause_inc /= self.clause_decay

        # Cleanup buffer for next call
        for tv in learned_trail:
            learned_buf[tv] = 0

        return learned_clause, backjump_level, lbd


    ## Precomputed table avoids recursive calls on every restart.
    @staticmethod
    def _build_luby_table(size: int) -> List[int]:
        table: List[int] = [0] * (size + 1)
        for i in range(1, size + 1):
            k = 1
            while k * 2 <= i + 1:
                k *= 2
            if k == i + 1:
                table[i] = k
            else:
                table[i] = table[i - k + 1]
        return table

    _LUBY_TABLE: List[int] = _build_luby_table.__func__(1000)

    @staticmethod
    def luby(i: int) -> int:
        if i <= 1000:
            return SATSolver._LUBY_TABLE[i]
        k = 1
        while k * 2 <= i + 1:
            k *= 2
        if k == i + 1:
            return k
        return SATSolver.luby(i - k + 1)


    @cython.boundscheck(False)
    @cython.wraparound(False)
    def solve(self) -> Tuple[bool, Optional[Dict[int, bool]]]:
        # Initial propagation at level 0
        conflict = self.propagate()
        if conflict >= 0:
            return False, None  # unsat


        ## Luby restarts: budget = luby(restart_number) * base_unit
        luby_base = self.luby_base  # base conflicts per Luby unit
        restart_number = 1
        max_conflicts = self.luby(restart_number) * luby_base
        conflict_count = 0

        ## Clause counts for learned-clause limit.
        n_orig_clauses = sum(1 for c in self.inst.clauses if not c.learned)

        ## Set the learned clause limit for cleaning up the clause database.
        if self.max_learnt_fixed >= 0:
            self.max_learnt = self.max_learnt_fixed
        else:
            computed = int(n_orig_clauses * self.max_learnt_ratio)
            self.max_learnt = computed if computed > self.max_learnt_min else self.max_learnt_min

        ## Fixed random decision frequency (MiniSat-style).
        rand_prob = self.random_freq

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
                ## Always-negative polarity (MiniSat 1.0 heuristic).
                ## Phase saving hurt UNSAT instances badly — the solver
                ## kept returning to the same failing region instead of
                ## exploring widely to prove unsatisfiability.
                self.decide(-next_var)

            
            # Propagate and handle conflicts
            while True:
                conflict = self.propagate()
                
                if conflict < 0:
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
                learned_clause, backjump_level, lbd = self.analyze_conflict(conflict)
                
                if backjump_level < 0:
                    # UNSAT
                    return False, None
                
                # Non-chronological backjump
                self.backjump(backjump_level)
                
                # Add learned clause and set up watches
                if len(learned_clause) > 0:
                    # Asserting literal is first in the clause
                    asserting_lit = learned_clause[0]
                    
                    cid = self.inst.add_clause(learned_clause, learned=True)
                    c = self.inst.clauses[cid]

                    ## Register with clause activity + LBD tracking.
                    self.clause_activity[cid] = 0.0
                    self.clause_lbd[cid] = lbd
                    self.alive_learned.add(cid)
                    
                    # Set up watches for the new clause
                    if len(c.lits) == 1:
                        self.watch_list[c.lits[0] + self._wl_off].append(cid)
                    elif len(c.lits) >= 2:
                        self.watch_list[c.lits[c.w1] + self._wl_off].append(cid)
                        self.watch_list[c.lits[c.w2] + self._wl_off].append(cid)

                    ## If we've accumulated too many learned clauses, clean up.
                    if len(self.alive_learned) > self.max_learnt:
                        self.reduce_db()
                        ## Gradually allow more clauses (MiniSat grows this over time).
                        self.max_learnt = int(self.max_learnt * self.max_learnt_growth)
                    
                    # Assign the asserting literal and loop to propagate it
                    self.assign_lit(asserting_lit, reason_cid=cid)
                    # Continue the inner while loop to propagate
