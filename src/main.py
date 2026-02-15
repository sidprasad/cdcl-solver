import json
import random
from pathlib import Path
from argparse import ArgumentParser
from dimacs_parser import DimacsParser
from model_timer import Timer

def main(args):
    input_file = args.input_file
    random.seed(42)  # deterministic runs for reproducibility
    
    if not input_file:
        print("Usage: python3 src/main.py <cnf file>")
        return

    path = Path(input_file)
    filename = path.name
    
    timer = Timer()
    timer.start()
    
    # result and solution placeholders
    result = "--"
    solution = None

    try:
        instance = DimacsParser.parse_cnf_file(input_file)
        if instance:
            from solver import SATSolver

            ## ── Instance-adaptive hyperparameters ──────────────────
            ## Classify by clause/variable density and choose config.
            ## Idea from SATzilla / AutoFolio portfolio-solver approach
            ## (Xu et al. 2008, Lindauer et al. 2015) — lightweight
            ## version using density as the single discriminating feature.
            ##
            ## Density thresholds informed by:
            ##  - 3-SAT phase transition at ~4.26 (Vardi et al.)
            ##  - picoSAT rapid-restart insight for dense instances
            ##    (Biere, SAT 2008)
            ##  - MiniSat defaults for structured / low-density instances
            ##    (Eén & Sörensson, SAT 2003)
            n_vars = len(instance.vars)
            n_clauses = len(instance.clauses)
            density = n_clauses / n_vars if n_vars > 0 else 0.0

            if density <= 6.0:
                ## Low-density / large structured instances.
                ## Long VSIDS memory (var_decay~0.99) keeps focus on the
                ## same region of the search space — good for structured
                ## formulas (Eén & Sörensson, MiniSat tech report).
                ## Longer Luby runs let propagation exploit structure
                ## before restarting (Luby et al. 1993).
                print(f"Low-density instance (density={density:.2f}), using long-term VSIDS and longer restarts")
                solver = SATSolver(
                    instance,
                    var_decay=0.99,
                    clause_decay=0.999,
                    luby_base=512,
                    random_freq=0.005,
                    max_learnt_ratio=0.5,
                    max_learnt_growth=1.05,
                )
            elif density <= 30.0:
                ## Medium-density — near or above 3-SAT phase transition.
                ## Default MiniSat-style settings work well here.
                print(f"Medium-density instance (density={density:.2f}), using default MiniSat-style parameters")
                solver = SATSolver(
                    instance,
                    var_decay=0.95,
                    clause_decay=0.999,
                    luby_base=100,
                    random_freq=0.02,
                    max_learnt_ratio=1.0 / 3.0,
                    max_learnt_growth=1.1,
                )
            else:
                ## High-density — massively constrained.
                ## Fast VSIDS decay (0.85) forgets old conflicts quickly,
                ## avoiding commitment to stale search directions Rapid restarts 
                # (let the solver escape bad regions early. Higher
                # random_freq provides diversification to avoid plateaus.
                # Aggressive learned-clause cleanup prevents memory blowup
                ## when clauses/var ratio is enormous.
                print(f"High-density instance (density={density:.2f}), using fast VSIDS decay and rapid restarts")
                solver = SATSolver(
                    instance,
                    var_decay=0.85,
                    clause_decay=0.9995,
                    luby_base=32,
                    random_freq=0.08,
                    max_learnt_ratio=0.15,
                    max_learnt_growth=1.2,
                )

            sat, model = solver.solve()
            if sat:
                result = "SAT"
                if model is not None:
                    solution = " ".join(f"{v} {'true' if val else 'false'}" for v, val in sorted(model.items()))
            else:
                result = "UNSAT"
    except Exception as e:
        print(f"Error: {e}")

    timer.stop()
    
    printSol = {
        "Instance": filename,
        "Time": f"{timer.getTime():.2f}",
        "Result": result
    }
    if solution is not None:
        printSol["Solution"] = solution

    print(json.dumps(printSol))

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("input_file", type=str)
    args = parser.parse_args()
    main(args)
