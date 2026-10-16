"""Standard Programmatic Solver Interface for Quantum Traffic Gridlock.

Provides solve() conforming to competition requirements and programmatic evaluations.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import json
import time

from traffic.scenario import load_scenario, validate_scenario
from traffic.qubo import build_qubo
from traffic.qaoa import sample_final_qaoa, train_qaoa
from traffic.qaoa_fourier import train_qaoa_fourier
from traffic.model import cost, enumerate_all
from traffic.metrics import (
    compute_elite_enrichment,
    compute_expected_cost,
    compute_lift,
    compute_surrogate_regret,
    get_elite_set,
)


def solve(
    scenario_input: str | Path | Dict[str, Any],
    seed: int = 42,
    p: int = 3,
    out_dir: str | Path | None = None,
    param_mode: str = "fourier",
    max_evals: int = 300,
    shots: int = 4096,
) -> Dict[str, Any]:
    """Solve the Quantum Traffic Gridlock problem for a given scenario.
    
    Args:
        scenario_input: Path to scenario.json or loaded scenario dictionary
        seed: Random seed for deterministic reproducibility
        p: QAOA circuit depth (default: 3, max: 4)
        out_dir: Optional directory to serialize deliverables
        param_mode: 'fourier' (default, high Lift) or 'standard'
        max_evals: Function evaluation budget (default: 300)
        shots: Final measurement shots (default: 4096)
        
    Returns:
        Dictionary containing optimal schedule, metrics, counts, and QASM.
    """
    t_start = time.perf_counter()

    if isinstance(scenario_input, (str, Path)):
        scenario = load_scenario(scenario_input)
    else:
        scenario = scenario_input
    validate_scenario(scenario)

    # 1. Ground truth enumeration benchmark
    enum_res = enumerate_all(scenario)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]
    elite_set = get_elite_set(enum_res, elite_count=13)

    # 2. Formulate QUBO
    qubo_data = build_qubo(scenario, variant="V2")
    h, J = qubo_data["h"], qubo_data["J"]

    # 3. Train QAOA
    if param_mode == "fourier":
        opt = train_qaoa_fourier(h, J, p=p, q=2, seed=seed, max_evals=max_evals)
    else:
        opt = train_qaoa(h, J, p=p, seed=seed, max_evals=max_evals)

    # 4. Sample 4,096 shots
    _, counts, qasm3_str = sample_final_qaoa(h, J, opt, seed=seed, shots=shots)

    # 5. Evaluate diagnostics
    e_q = compute_expected_cost(counts, scenario)
    lift = compute_lift(c_rand, e_q, c_star)
    enrichment = compute_elite_enrichment(counts, elite_set)

    # Best sampled shot
    best_sample = min(counts.keys(), key=lambda s: cost(s, scenario))
    best_sample_cost = cost(best_sample, scenario)
    most_freq_sample = max(counts.keys(), key=lambda s: counts[s])

    t_elapsed = time.perf_counter() - t_start

    result = {
        "schedule": best_sample,
        "official_cost": best_sample_cost,
        "C_star": c_star,
        "C_rand": c_rand,
        "E_Q": round(e_q, 2),
        "lift": round(lift, 4),
        "elite_enrichment": round(enrichment, 2),
        "evaluations_used": opt["evaluations_used"],
        "runtime_seconds": round(t_elapsed, 3),
        "most_frequent_schedule": most_freq_sample,
        "counts": counts,
        "qasm": qasm3_str,
    }

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "qubo.json").write_text(json.dumps(qubo_data, indent=2), encoding="utf-8")
        (out_path / "circuit.qasm").write_text(qasm3_str, encoding="utf-8")
        (out_path / "counts.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
        (out_path / "schedule.json").write_text(json.dumps({"schedule": best_sample, "cost": best_sample_cost}, indent=2), encoding="utf-8")
        (out_path / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Quantum Traffic Gridlock Solver")
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    parser.add_argument("--out", default=None, help="Output directory")
    args = parser.parse_args()

    res = solve(args.scenario, seed=args.seed, out_dir=args.out)
    print(f"Optimal Schedule: {res['schedule']} (Cost: {res['official_cost']})")
    print(f"Lift: {res['lift']} | Elite Enrichment: {res['elite_enrichment']}x | Time: {res['runtime_seconds']}s")
