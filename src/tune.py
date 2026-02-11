"""
Optuna hyperparameter tuning for SAT solver.

Usage:
    python src/tune.py                     # Run with defaults
    python src/tune.py --n-trials 50       # Custom number of trials
    python src/tune.py --timeout 30        # Per-instance timeout in seconds
    python src/tune.py --dashboard         # Launch Optuna dashboard
"""

import os
import sys
import signal
from pathlib import Path
from argparse import ArgumentParser
from typing import List, Optional
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout

import optuna
from optuna.visualization import plot_optimization_history, plot_param_importances

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dimacs_parser import DimacsParser
from model_timer import Timer


def solve_with_timeout(instance_path: str, params: dict, timeout: float) -> Optional[float]:
    """
    Solve a single instance with given hyperparameters.
    Returns solve time if successful, None if timeout/error.
    """
    from solver import SATSolver
    
    try:
        instance = DimacsParser.parse_cnf_file(instance_path)
        if instance is None:
            return None
        
        solver = SATSolver(
            instance,
            var_decay=params["var_decay"],
            clause_decay=params["clause_decay"],
            luby_base=params["luby_base"],
            random_freq=params["random_freq"],
            max_learnt_ratio=params["max_learnt_ratio"],
            max_learnt_growth=params["max_learnt_growth"],
        )
        
        timer = Timer()
        timer.start()
        sat, model = solver.solve()
        timer.stop()
        
        return timer.getTime()
    except Exception as e:
        print(f"Error solving {instance_path}: {e}")
        return None


def _run_single(args):
    """Wrapper for multiprocessing."""
    instance_path, params, timeout = args
    return solve_with_timeout(instance_path, params, timeout)


def evaluate_params(
    params: dict,
    instances: List[str],
    timeout: float,
    penalty: float = None,
) -> float:
    """
    Evaluate hyperparameters across multiple instances.
    Returns aggregate score (lower is better).
    
    Scoring:
    - Sum of solve times for successful solves
    - Timeout penalty for timeouts (defaults to 2x timeout)
    """
    if penalty is None:
        penalty = timeout * 2
    
    total_time = 0.0
    
    for instance_path in instances:
        # Use process pool for timeout handling
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(solve_with_timeout, instance_path, params, timeout)
            try:
                result = future.result(timeout=timeout)
                if result is not None:
                    total_time += result
                else:
                    total_time += penalty
            except FuturesTimeout:
                total_time += penalty
                # Kill any lingering process
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                total_time += penalty
    
    return total_time


def objective(trial: optuna.Trial, instances: List[str], timeout: float) -> float:
    """Optuna objective function."""
    
    # Define the hyperparameter search space
    params = {
        # VSIDS variable decay (higher = more weight on old conflicts)
        "var_decay": trial.suggest_float("var_decay", 0.8, 0.99),
        
        # Clause activity decay (for learned clause deletion)
        "clause_decay": trial.suggest_float("clause_decay", 0.99, 0.9999),
        
        # Luby restart base (conflicts per Luby unit)
        "luby_base": trial.suggest_int("luby_base", 32, 512, log=True),
        
        # Random decision frequency
        "random_freq": trial.suggest_float("random_freq", 0.0, 0.1),
        
        # Learned clause limit as ratio of original clauses
        "max_learnt_ratio": trial.suggest_float("max_learnt_ratio", 0.1, 0.5),
        
        # Growth factor for learned clause limit after cleanup
        "max_learnt_growth": trial.suggest_float("max_learnt_growth", 1.05, 1.3),
    }
    
    # Evaluate and return score
    score = evaluate_params(params, instances, timeout)
    
    return score


def main():
    parser = ArgumentParser(description="Tune SAT solver hyperparameters with Optuna")
    parser.add_argument("--n-trials", type=int, default=10, help="Number of Optuna trials")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-instance timeout (seconds)")
    parser.add_argument("--study-name", type=str, default="sat_solver_tuning", help="Optuna study name")
    parser.add_argument("--storage", type=str, default=None, help="Optuna storage URL (e.g., sqlite:///optuna.db)")
    parser.add_argument("--instances", type=str, nargs="+", default=None, help="Instance files to tune on")
    parser.add_argument("--train-ratio", type=float, default=0.5, help="Fraction of instances for training (default: 0.5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for train/test split")
    parser.add_argument("--dashboard", action="store_true", help="Launch Optuna dashboard after tuning")
    parser.add_argument("--load-study", action="store_true", help="Load existing study instead of creating new")
    args = parser.parse_args()
    
    # Resolve instance paths
    project_root = Path(__file__).parent.parent
    input_dir = project_root / "input"
    
    if args.instances:
        instances = [str(project_root / p) for p in args.instances]
    else:
        # Auto-discover all .cnf files in input/
        instances = sorted([str(p) for p in input_dir.glob("*.cnf")])
    
    # Verify instances exist
    for inst in instances:
        if not Path(inst).exists():
            print(f"Warning: Instance not found: {inst}")
    instances = [inst for inst in instances if Path(inst).exists()]
    
    if not instances:
        print("Error: No valid instances found!")
        return
    
    # Train/test split
    import random as rand_module
    rand_module.seed(args.seed)
    shuffled = instances.copy()
    rand_module.shuffle(shuffled)
    
    split_idx = int(len(shuffled) * args.train_ratio)
    train_instances = shuffled[:split_idx]
    test_instances = shuffled[split_idx:]
    
    print(f"Found {len(instances)} total instances")
    print(f"Train set: {len(train_instances)} instances ({args.train_ratio*100:.0f}%)")
    print(f"Test set:  {len(test_instances)} instances ({(1-args.train_ratio)*100:.0f}%)")
    print(f"Timeout: {args.timeout}s per instance")
    print(f"Running {args.n_trials} trials...")
    print()
    
    print("Train instances:")
    for inst in train_instances:
        print(f"  - {Path(inst).name}")
    print("\nTest instances:")
    for inst in test_instances:
        print(f"  - {Path(inst).name}")
    print()
    
    # Create or load study
    storage = args.storage or f"sqlite:///{project_root}/optuna_study.db"
    
    if args.load_study:
        study = optuna.load_study(study_name=args.study_name, storage=storage)
    else:
        study = optuna.create_study(
            study_name=args.study_name,
            storage=storage,
            direction="minimize",  # Minimize total solve time
            load_if_exists=True,
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(),
        )
    
    # Run optimization on train set
    study.optimize(
        lambda trial: objective(trial, train_instances, args.timeout),
        n_trials=args.n_trials,
        show_progress_bar=True,
    )
    
    # Report results
    print("\n" + "=" * 60)
    print("TUNING COMPLETE")
    print("=" * 60)
    print(f"\nBest trial: #{study.best_trial.number}")
    print(f"Best score (train): {study.best_value:.2f}s (total solve time)")
    print("\nBest hyperparameters:")
    for key, value in study.best_params.items():
        print(f"  {key}: {value}")
    
    # Evaluate on test set
    if test_instances:
        print("\n" + "-" * 60)
        print("Evaluating best params on TEST set...")
        print("-" * 60)
        test_score = evaluate_params(study.best_params, test_instances, args.timeout)
        print(f"Test score: {test_score:.2f}s (total solve time on {len(test_instances)} instances)")
    
    # Generate code snippet
    print("\n" + "-" * 60)
    print("Use these in your solver:")
    print("-" * 60)
    print("solver = SATSolver(")
    print("    instance,")
    for key, value in study.best_params.items():
        if isinstance(value, float):
            print(f"    {key}={value:.6f},")
        else:
            print(f"    {key}={value},")
    print(")")
    
    # Save plots if possible
    try:
        import plotly
        fig = plot_optimization_history(study)
        fig.write_html(str(project_root / "optuna_history.html"))
        print(f"\nOptimization history saved to: optuna_history.html")
        
        if len(study.trials) > 10:
            fig = plot_param_importances(study)
            fig.write_html(str(project_root / "optuna_importance.html"))
            print(f"Parameter importance saved to: optuna_importance.html")
    except ImportError:
        print("\nTip: Install plotly for visualization: pip install plotly")
    except Exception as e:
        print(f"\nCould not save plots: {e}")
    
    # Launch dashboard if requested
    if args.dashboard:
        print("\nLaunching Optuna dashboard...")
        os.system(f"optuna-dashboard {storage}")


if __name__ == "__main__":
    main()
