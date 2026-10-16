"""Section 11 Innovation Extension: MUTCD Minimum-Green & Clearance Safety Constraints.

In urban traffic engineering (MUTCD standards), signals cannot alternate phases
every 30 seconds due to amber clearance loss and pedestrian safety.
We formulate an exact quadratic penalty based on the discrete second difference (Laplacian):
    Penalty_t = lambda_safety * (x_{t-1} - 2 * x_t + x_{t+1})^2

Characteristics:
- Flutter patterns [0, 1, 0] and [1, 0, 1] incur penalty = 4 * lambda
- Smooth 2-slot green patterns [1, 1, 0] incur penalty = 1 * lambda
- Steady state patterns [1, 1, 1] and [0, 0, 0] incur penalty = 0
- Fully quadratic in decision variables (x_i^2 = x_i), requiring zero auxiliary variables!
"""

from __future__ import annotations
import json
from pathlib import Path
import sys
from typing import Any, Dict, List
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.scenario import load_scenario
from traffic.qubo import build_qubo, solve_qubo_brute_force
from traffic.model import cost, enumerate_all


def add_minimum_green_penalty(
    Q: np.ndarray,
    lambda_safety: float = 2.0,
) -> np.ndarray:
    """Add the quadratic minimum-green safety penalty to QUBO matrix Q."""
    Q_safe = np.copy(Q)
    # Applied to Intersection A (0..3) and B (4..7)
    for offset_idx in (0, 4):
        for t in (1, 2):
            prev_idx = offset_idx + t - 1
            curr_idx = offset_idx + t
            next_idx = offset_idx + t + 1

            # (x_{t-1} - 2 x_t + x_{t+1})^2 = x_{t-1} + 4 x_t + x_{t+1}
            # - 4 x_{t-1} x_t - 4 x_t x_{t+1} + 2 x_{t-1} x_{t+1}
            # Fold diagonals:
            Q_safe[prev_idx, prev_idx] += lambda_safety * 1.0
            Q_safe[curr_idx, curr_idx] += lambda_safety * 4.0
            Q_safe[next_idx, next_idx] += lambda_safety * 1.0

            # Off-diagonals (upper-triangular):
            # prev and curr
            Q_safe[prev_idx, curr_idx] -= lambda_safety * 4.0
            # curr and next
            Q_safe[curr_idx, next_idx] -= lambda_safety * 4.0
            # prev and next
            Q_safe[prev_idx, next_idx] += lambda_safety * 2.0

    return Q_safe


def evaluate_safety_extension(scenario_path: str = "scenarios/R.json") -> Dict[str, Any]:
    scen = load_scenario(scenario_path)
    qubo_data = build_qubo(scen)
    Q_orig = np.array(qubo_data["Q"])
    offset = qubo_data["offset"]

    results = []
    for lmb in [0.0, 1.0, 2.5, 5.0]:
        Q_safe = add_minimum_green_penalty(Q_orig, lambda_safety=lmb)
        best_sched, best_e = solve_qubo_brute_force(Q_safe, offset)
        c = cost(best_sched, scen)

        # Count 1-slot flutters in schedule (010 or 101)
        a_bits = best_sched[:4]
        b_bits = best_sched[4:]
        flutters_a = sum(1 for t in (1, 2) if a_bits[t] != a_bits[t - 1] and a_bits[t] != a_bits[t + 1])
        flutters_b = sum(1 for t in (1, 2) if b_bits[t] != b_bits[t - 1] and b_bits[t] != b_bits[t + 1])
        total_flutters = flutters_a + flutters_b

        results.append({
            "lambda_safety": lmb,
            "best_schedule": best_sched,
            "official_cost": c,
            "flutters_count": total_flutters,
            "flutter_free": total_flutters == 0,
        })

    return {
        "scenario": scen.get("name", "R"),
        "safety_sweep": results,
    }


def main():
    res = evaluate_safety_extension("scenarios/R.json")
    print("--- MUTCD MINIMUM-GREEN SAFETY EXTENSION ---")
    print("| Lambda Safety | Best Schedule | Official Cost | Flutter Violations | Safe? |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for r in res["safety_sweep"]:
        print(f"| {r['lambda_safety']} | {r['best_schedule']} | {r['official_cost']} | {r['flutters_count']} | {r['flutter_free']} |")

    out_file = Path("experiments/extension_safety_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    main()
