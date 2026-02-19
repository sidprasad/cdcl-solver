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

            n_vars = len(instance.vars)
            n_clauses = len(instance.clauses)
            density = n_clauses / n_vars if n_vars > 0 else 0.0

            if density <= 6.0:
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
                solver = SATSolver(
                    instance,
                    var_decay=0.95,
                    clause_decay=0.999,
                    luby_base=100,
                    random_freq=0.02,
                    max_learnt_ratio=0.15,
                    max_learnt_growth=1.05,
                )
            else:
                
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
