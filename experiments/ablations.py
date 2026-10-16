"""Ablation studies on QAOA depth p, surrogate variants, initialization, and CVaR.

Generates real experimental ablation tables for the report.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.scenario import load_scenario
from traffic.model import enumerate_all, cost
from traffic.qubo import build_qubo
from traffic.qaoa import sample_final_qaoa, train_qaoa
from traffic.metrics import (
    compute_elite_enrichment,
    compute_expected_cost,
    compute_lift,
    get_elite_set,
)


def run_depth_ablation(scen: Dict[str, Any], seeds: List[int]) -> List[Dict[str, Any]]:
    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]
    elite_set = get_elite_set(enum_res, elite_count=13)

    qubo_data = build_qubo(scen, variant="V2")
    h = qubo_data["h"]
    J = qubo_data["J"]

    depth_results = []
    for p in [1, 2, 3, 4]:
        lifts = []
        enrichments = []
        costs = []
        t0 = time.time()
        for seed in seeds:
            opt = train_qaoa(h, J, p=p, seed=seed, max_evals=300)
            _, counts, _ = sample_final_qaoa(h, J, opt, seed=seed, shots=4096)
            e_q = compute_expected_cost(counts, scen)
            lift = compute_lift(c_rand, e_q, c_star)
            enrich = compute_elite_enrichment(counts, elite_set)
            lifts.append(lift)
            enrichments.append(enrich)
            costs.append(e_q)
        elapsed = time.time() - t0

        depth_results.append({
            "p": p,
            "mean_E_Q": round(float(np.mean(costs)), 2),
            "mean_lift": round(float(np.mean(lifts)), 4),
            "min_lift": round(float(np.min(lifts)), 4),
            "mean_enrichment": round(float(np.mean(enrichments)), 2),
            "time_per_seed": round(elapsed / len(seeds), 2),
        })

    return depth_results


def run_variant_ablation(scen: Dict[str, Any], seeds: List[int]) -> List[Dict[str, Any]]:
    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]
    elite_set = get_elite_set(enum_res, elite_count=13)

    variant_results = []
    for var in ["V0", "V1", "V2"]:
        qubo_data = build_qubo(scen, variant=var)
        h = qubo_data["h"]
        J = qubo_data["J"]

        lifts = []
        enrichments = []
        costs = []
        for seed in seeds:
            opt = train_qaoa(h, J, p=3, seed=seed, max_evals=300)
            _, counts, _ = sample_final_qaoa(h, J, opt, seed=seed, shots=4096)
            e_q = compute_expected_cost(counts, scen)
            lift = compute_lift(c_rand, e_q, c_star)
            enrich = compute_elite_enrichment(counts, elite_set)
            lifts.append(lift)
            enrichments.append(enrich)
            costs.append(e_q)

        variant_results.append({
            "variant": var,
            "mean_E_Q": round(float(np.mean(costs)), 2),
            "mean_lift": round(float(np.mean(lifts)), 4),
            "min_lift": round(float(np.min(lifts)), 4),
            "mean_enrichment": round(float(np.mean(enrichments)), 2),
        })

    return variant_results


def run_cvar_ablation(scen: Dict[str, Any], seeds: List[int]) -> List[Dict[str, Any]]:
    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]
    elite_set = get_elite_set(enum_res, elite_count=13)

    qubo_data = build_qubo(scen, variant="V2")
    h = qubo_data["h"]
    J = qubo_data["J"]

    cvar_results = []
    for alpha in [1.0, 0.5, 0.25]:
        lifts = []
        enrichments = []
        costs = []
        for seed in seeds:
            opt = train_qaoa(h, J, p=3, seed=seed, max_evals=300, cvar_alpha=alpha)
            _, counts, _ = sample_final_qaoa(h, J, opt, seed=seed, shots=4096)
            e_q = compute_expected_cost(counts, scen)
            lift = compute_lift(c_rand, e_q, c_star)
            enrich = compute_elite_enrichment(counts, elite_set)
            lifts.append(lift)
            enrichments.append(enrich)
            costs.append(e_q)

        cvar_results.append({
            "cvar_alpha": alpha,
            "mean_E_Q": round(float(np.mean(costs)), 2),
            "mean_lift": round(float(np.mean(lifts)), 4),
            "min_lift": round(float(np.min(lifts)), 4),
            "mean_enrichment": round(float(np.mean(enrichments)), 2),
        })

    return cvar_results


def main():
    parser = argparse.ArgumentParser(description="Run QAOA Ablation Studies")
    parser.add_argument("--scenario", default="scenarios/R.json", help="Path to scenario")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4], help="Seeds for averaging")
    parser.add_argument("--out", default="experiments/ablation_results.json", help="Output JSON path")
    args = parser.parse_args()

    scen = load_scenario(args.scenario)
    print(f"Running ablations on {args.scenario} across seeds {args.seeds}...")

    print("1. Running depth p in {1, 2, 3, 4} ablation...")
    depth_res = run_depth_ablation(scen, args.seeds)

    print("2. Running QUBO variant {V0, V1, V2} ablation...")
    var_res = run_variant_ablation(scen, args.seeds)

    print("3. Running CVaR alpha {1.0, 0.5, 0.25} ablation...")
    cvar_res = run_cvar_ablation(scen, args.seeds)

    summary = {
        "scenario": scen.get("name", "R"),
        "depth_ablation": depth_res,
        "variant_ablation": var_res,
        "cvar_ablation": cvar_res,
    }

    print("\n--- DEPTH ABLATION RESULTS ---")
    for r in depth_res:
        print(f"p={r['p']}: Mean Cost={r['mean_E_Q']}, Lift={r['mean_lift']:.4f}, Min Lift={r['min_lift']:.4f}, Enrichment={r['mean_enrichment']:.2f}x ({r['time_per_seed']}s/seed)")

    print("\n--- VARIANT ABLATION RESULTS ---")
    for r in var_res:
        print(f"{r['variant']}: Mean Cost={r['mean_E_Q']}, Lift={r['mean_lift']:.4f}, Min Lift={r['min_lift']:.4f}, Enrichment={r['mean_enrichment']:.2f}x")

    print("\n--- CVaR ABLATION RESULTS ---")
    for r in cvar_res:
        print(f"alpha={r['cvar_alpha']}: Mean Cost={r['mean_E_Q']}, Lift={r['mean_lift']:.4f}, Min Lift={r['min_lift']:.4f}, Enrichment={r['mean_enrichment']:.2f}x")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nAblation data saved to {args.out}")


if __name__ == "__main__":
    main()
