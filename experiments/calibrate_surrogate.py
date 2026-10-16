"""Calibration script for QUBO surrogate parameters on random hidden-range scenarios.

Generates >= 300 random scenarios from the challenge's hidden parameter ranges.
Evaluates surrogate regret = (C(x*_QUBO) - C*) / C* across all scenarios.
Selects and validates global constants (alpha, beta, margin, variant) minimizing regret.
NEVER tunes constants specifically on scenario R.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.model import cost, enumerate_all
from traffic.scenario import load_scenario, sample_random_scenario
from traffic.qubo import (
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    DEFAULT_MARGIN,
    DEFAULT_VARIANT,
    build_qubo,
    solve_qubo_brute_force,
)


def evaluate_configuration(
    scenarios: List[Dict[str, Any]],
    true_solutions: List[Dict[str, Any]],
    alpha: float,
    beta: float,
    margin: float,
    variant: str,
) -> Dict[str, Any]:
    """Evaluate surrogate regret of a configuration across a set of scenarios."""
    regrets = []
    qubo_schedules = []

    for scen, true_sol in zip(scenarios, true_solutions):
        qubo_data = build_qubo(scen, alpha=alpha, beta=beta, margin=margin, variant=variant)
        best_sched, _ = solve_qubo_brute_force(qubo_data["Q"], qubo_data["offset"])
        qubo_schedules.append(best_sched)

        c_qubo = cost(best_sched, scen)
        c_star = true_sol["C_star"]
        regret = (c_qubo - c_star) / c_star if c_star > 1e-9 else 0.0
        regrets.append(regret)

    regrets_arr = np.array(regrets)
    return {
        "alpha": alpha,
        "beta": beta,
        "margin": margin,
        "variant": variant,
        "mean_regret": float(np.mean(regrets_arr)),
        "median_regret": float(np.median(regrets_arr)),
        "p90_regret": float(np.percentile(regrets_arr, 90)),
        "max_regret": float(np.max(regrets_arr)),
        "zero_regret_fraction": float(np.mean(regrets_arr < 1e-9)),
    }


def main():
    parser = argparse.ArgumentParser(description="Calibrate QUBO Surrogate on Hidden-Range Scenarios")
    parser.add_argument("--num-scenarios", type=int, default=300, help="Number of random scenarios (>=300)")
    parser.add_argument("--seed", type=int, default=42, help="Fixed random seed for scenario generator")
    parser.add_argument("--out", type=str, default="experiments/calibration_results.json", help="Output path")
    args = parser.parse_args()

    print(f"Generating {args.num_scenarios} random hidden-range scenarios with seed {args.seed}...")
    rng = np.random.default_rng(args.seed)
    scenarios = [
        sample_random_scenario(rng=rng, name=f"calib_{i:04d}")
        for i in range(args.num_scenarios)
    ]

    print("Computing benchmark exact optima (C*) for all scenarios via full enumeration...")
    t0 = time.time()
    true_solutions = [enumerate_all(scen) for scen in scenarios]
    elapsed = time.time() - t0
    print(f"Enumeration completed in {elapsed:.2f}s ({elapsed / args.num_scenarios * 1000:.1f}ms per scenario).")

    # Evaluate the primary default configuration
    print(f"\nEvaluating calibrated configuration (alpha={DEFAULT_ALPHA}, beta={DEFAULT_BETA}, margin={DEFAULT_MARGIN}, variant={DEFAULT_VARIANT})...")
    default_stats = evaluate_configuration(
        scenarios, true_solutions,
        alpha=DEFAULT_ALPHA, beta=DEFAULT_BETA, margin=DEFAULT_MARGIN, variant=DEFAULT_VARIANT
    )
    print(f"Results on {args.num_scenarios} random scenarios:")
    print(f"  Mean Regret:   {default_stats['mean_regret'] * 100:.2f}%  (Target: <=5.0%)")
    print(f"  Median Regret: {default_stats['median_regret'] * 100:.2f}%")
    print(f"  90th % Regret: {default_stats['p90_regret'] * 100:.2f}%")
    print(f"  Exact Optima:  {default_stats['zero_regret_fraction'] * 100:.1f}% of scenarios")

    # Also evaluate on Scenario R
    scen_r_path = Path("scenarios/R.json")
    if scen_r_path.exists():
        scen_r = load_scenario(scen_r_path)
        true_r = enumerate_all(scen_r)
        r_stats = evaluate_configuration(
            [scen_r], [true_r],
            alpha=DEFAULT_ALPHA, beta=DEFAULT_BETA, margin=DEFAULT_MARGIN, variant=DEFAULT_VARIANT
        )
        print(f"\nResults on Scenario R:")
        print(f"  Regret on R:   {r_stats['mean_regret'] * 100:.2f}%")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "num_scenarios": args.num_scenarios,
            "seed": args.seed,
            "default_configuration": default_stats,
            "scenario_r_result": r_stats if scen_r_path.exists() else None,
        }, f, indent=2)
    print(f"\nCalibration saved to {out_path}")


if __name__ == "__main__":
    main()
