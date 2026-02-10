import json
from pathlib import Path
from argparse import ArgumentParser
from dimacs_parser import DimacsParser
from model_timer import Timer

def main(args):
    input_file = args.input_file
    
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
            # run CDCL solver on parsed instance
            from solver import SATSolver
            solver = SATSolver(instance)
            sat, model = solver.solve()
            if sat:
                result = "SAT"
                # format solution as: "1 true 2 false"
                if model is not None:
                    solution = " ".join(f"{v} {'true' if val else 'false'}" for v, val in sorted(model.items()))
                # print(result, end="")
                # if solution is not None:
                #     print(f"\nAssignment: {solution}")
            else:
                result = "UNSAT"
                #print(result, end="")
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
