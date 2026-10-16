"""Main CLI Entry Point for Quantum Traffic Gridlock.

Usage:
    python run.py --scenario <scenario.json> --seed <int> --out <dir>
"""

from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
from typing import Any, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.model import cost, enumerate_all
from traffic.scenario import load_scenario
from traffic.qubo import (
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    DEFAULT_MARGIN,
    DEFAULT_VARIANT,
    build_qubo,
    solve_qubo_brute_force,
)
from traffic.qaoa import (
    DEFAULT_P,
    MAX_EVALS_DEFAULT,
    sample_final_qaoa,
    train_qaoa,
)
from traffic.baselines import (
    alternating_baseline,
    classical_refinement_hybrid,
    greedy_baseline,
    uniform_random_baseline,
)
from traffic.metrics import (
    compute_elite_enrichment,
    compute_expected_cost,
    compute_lift,
    compute_surrogate_regret,
    get_elite_set,
)
from traffic.io_out import write_outputs


def execute_pipeline(
    scenario_path: Union[str, Path],
    seed: int,
    out_dir: Union[str, Path],
    p: int = DEFAULT_P,
    max_evals: int = MAX_EVALS_DEFAULT,
    variant: str = DEFAULT_VARIANT,
    cvar_alpha: float = 1.0,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Execute complete quantum optimization pipeline end-to-end."""
    t0 = time.time()
    scen = load_scenario(scenario_path)
    scen_name = scen.get("name", Path(scenario_path).stem)

    if verbose:
        print(f"============================================================")
        print(f"  QUANTUM TRAFFIC GRIDLOCK: {scen_name} (Seed {seed})")
        print(f"============================================================")
        print(f"Capacity: {scen['capacity']}, Storage: {scen['storage']}, Overflow Weight: {scen['overflow_weight']}, Switch Weight: {scen['switch_weight']}")
        print(f"Link: A -> B on {scen['link']['approach']} (fraction {scen['link']['fraction']})")

    # Step 1: Benchmark enumeration (authoritative ground truth C*)
    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    best_exact_sched = enum_res["best_schedule"]
    c_rand = enum_res["C_rand"]

    # Step 2: Classical Baselines
    alt_res = alternating_baseline(scen)
    greedy_res = greedy_baseline(scen)
    rand_res = uniform_random_baseline(enum_res)

    # Step 3: QUBO formulation
    qubo_data = build_qubo(scen, variant=variant)
    best_qubo_sched, _ = solve_qubo_brute_force(qubo_data["Q"], qubo_data["offset"])
    c_qubo_minimizer = cost(best_qubo_sched, scen)
    surrogate_regret = compute_surrogate_regret(c_qubo_minimizer, c_star)

    # Step 4: QAOA Training
    h = qubo_data["h"]
    J = qubo_data["J"]
    opt_res = train_qaoa(h, J, p=p, seed=seed, max_evals=max_evals, cvar_alpha=cvar_alpha)

    # Step 5: QAOA 4096-Shot Sampling
    circ_with_meas, counts, qasm3_str = sample_final_qaoa(h, J, opt_res, seed=seed, shots=4096)

    # Step 6: Post-Sampling Diagnostics & Decoded Schedules
    e_q = compute_expected_cost(counts, scen)
    lift = compute_lift(c_rand, e_q, c_star)

    elite_set = get_elite_set(enum_res, elite_count=13)
    enrichment = compute_elite_enrichment(counts, elite_set)

    # Find most frequent sample
    most_freq_sched = max(counts.items(), key=lambda item: item[1])[0]
    most_freq_cost = cost(most_freq_sched, scen)

    # Find best sample among shots by official cost
    best_sample_sched = min(counts.keys(), key=lambda s: cost(s, scen))
    best_sample_cost = cost(best_sample_sched, scen)

    # Optional classical hybrid refinement from best sample
    hybrid_sched, hybrid_cost = classical_refinement_hybrid(best_sample_sched, scen)

    elapsed = time.time() - t0

    # Step 7: Format output structures
    schedules = {
        "bit_order_documentation": (
            "8 decision bits: index 0..3 = Intersection A slots 1..4; "
            "index 4..7 = Intersection B slots 1..4. "
            "Bit value: 1 = North-South (NS) green, 0 = East-West (EW) green."
        ),
        "most_frequent_sample": {
            "schedule": most_freq_sched,
            "count": counts[most_freq_sched],
            "fraction": counts[most_freq_sched] / 4096.0,
            "official_cost": most_freq_cost,
        },
        "best_sample_by_official_cost": {
            "schedule": best_sample_sched,
            "official_cost": best_sample_cost,
            "count": counts[best_sample_sched],
        },
        "qubo_exact_minimizer": {
            "schedule": best_qubo_sched,
            "official_cost": c_qubo_minimizer,
        },
        "hybrid_refined_schedule": {
            "description": "Optional classical 1-bit local search refinement initialized from best QAOA sample",
            "schedule": hybrid_sched,
            "official_cost": hybrid_cost,
        },
    }

    metrics = {
        "scenario_name": scen_name,
        "seed": seed,
        "runtime_seconds": round(elapsed, 3),
        "p": p,
        "evaluations_used": opt_res["evaluations_used"],
        "max_evaluations_budget": max_evals,
        "total_shots": 4096,
        "C_star": c_star,
        "best_exact_schedule": best_exact_sched,
        "C_rand": c_rand,
        "E_Q": e_q,
        "lift": lift,
        "elite_enrichment": enrichment,
        "surrogate_regret": surrogate_regret,
        "qubo_variant": variant,
        "baselines": {
            "1_alternating_best": {
                "schedule": alt_res["best_schedule"],
                "cost": alt_res["cost"],
            },
            "2_greedy_per_slot": {
                "schedule": greedy_res["schedule"],
                "cost": greedy_res["cost"],
            },
            "3_exact_enumeration_C_star": {
                "schedule": best_exact_sched,
                "cost": c_star,
            },
            "4_uniform_random_expected": {
                "cost": c_rand,
            },
            "5_qubo_exact_minimizer": {
                "schedule": best_qubo_sched,
                "cost": c_qubo_minimizer,
                "regret": surrogate_regret,
            },
            "6_qaoa_raw_mean_E_Q": {
                "mean_cost": e_q,
                "best_sample_cost": best_sample_cost,
                "most_frequent_cost": most_freq_cost,
                "lift": lift,
                "elite_enrichment": enrichment,
            },
            "6b_hybrid_classical_refinement": {
                "schedule": hybrid_sched,
                "cost": hybrid_cost,
            },
        },
    }

    # Step 8: Write all deliverables to disk
    out_files = write_outputs(out_dir, qubo_data, qasm3_str, counts, schedules, metrics)

    if verbose:
        print(f"\n--- BASELINES & BENCHMARK COMPARISON ({scen_name}) ---")
        print(f"  (1) Alternating Best:        Cost = {alt_res['cost']:.1f}  (Sched: {alt_res['best_schedule']})")
        print(f"  (2) Per-slot Greedy:         Cost = {greedy_res['cost']:.1f}  (Sched: {greedy_res['schedule']})")
        print(f"  (3) Exact Enumeration (C*):  Cost = {c_star:.1f}  (Sched: {best_exact_sched})")
        print(f"  (4) Uniform-Random (C_rand): Cost = {c_rand:.2f}")
        print(f"  (5) QUBO Minimizer (Ceiling):Cost = {c_qubo_minimizer:.1f}  (Regret: {surrogate_regret*100:.2f}%)")
        print(f"  (6) QAOA Raw Mean (E_Q):     Cost = {e_q:.2f}  (Lift: {lift:.4f}, Elite Enrichment: {enrichment:.2f}x)")
        print(f"      QAOA Best Sample:        Cost = {best_sample_cost:.1f}  (Sched: {best_sample_sched})")
        print(f"      QAOA Most Frequent:      Cost = {most_freq_cost:.1f}  (Count: {counts[most_freq_sched]}/4096)")
        print(f"  [Hybrid Refined]:            Cost = {hybrid_cost:.1f}  (Sched: {hybrid_sched})")
        print(f"\nSaved 5 output files in: {out_dir}")
        print(f"Pipeline executed in {elapsed:.2f}s ({opt_res['evaluations_used']} evals used).")

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Quantum Traffic Gridlock - IBM Qiskit Fall Fest 2026")
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    parser.add_argument("--seed", type=int, required=True, help="Random seed for deterministic optimization and sampling")
    parser.add_argument("--out", required=True, help="Directory to save output files")
    parser.add_argument("--p", type=int, default=DEFAULT_P, help=f"QAOA depth p (default: {DEFAULT_P}, max: 4)")
    parser.add_argument("--max-evals", type=int, default=MAX_EVALS_DEFAULT, help=f"Maximum objective evaluations (default: {MAX_EVALS_DEFAULT})")
    parser.add_argument("--variant", type=str, default=DEFAULT_VARIANT, choices=["V0", "V1", "V2"], help="QUBO formulation variant")
    parser.add_argument("--cvar-alpha", type=float, default=1.0, help="CVaR alpha parameter (default 1.0 for standard expectation)")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose stdout")
    args = parser.parse_args()

    if args.p > 4:
        raise ValueError(f"QAOA depth p must be <= 4 by competition rules, got {args.p}")
    if args.max_evals > 300:
        raise ValueError(f"Maximum evaluations must be <= 300 by competition rules, got {args.max_evals}")

    execute_pipeline(
        scenario_path=args.scenario,
        seed=args.seed,
        out_dir=args.out,
        p=args.p,
        max_evals=args.max_evals,
        variant=args.variant,
        cvar_alpha=args.cvar_alpha,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
