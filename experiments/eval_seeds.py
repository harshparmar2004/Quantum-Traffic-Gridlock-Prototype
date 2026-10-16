"""Evaluate QAOA performance across >=5 seeds on public and placeholder scenarios.

Generates a formatted markdown table reporting:
- Seed
- E_Q (mean official cost)
- Lift = (C_rand - E_Q) / (C_rand - C*)
- Elite Enrichment (top 13 schedules)
- Best Sample Cost
- Robustness = min(Lift) clipped to [0, 1]
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
    compute_robustness,
    get_elite_set,
)


SEEDS_DEFAULT = [0, 1, 2, 3, 4, 5, 6]


def evaluate_scenario_seeds(
    scenario_path: Union[str, Path],
    seeds: List[int],
    p: int = 3,
) -> Dict[str, Any]:
    scen = load_scenario(scenario_path)
    scen_name = scen.get("name", Path(scenario_path).stem)

    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]
    elite_set = get_elite_set(enum_res, elite_count=13)

    qubo_data = build_qubo(scen)
    h = qubo_data["h"]
    J = qubo_data["J"]

    seed_results = []
    lifts = []

    for seed in seeds:
        t0 = time.time()
        opt_res = train_qaoa(h, J, p=p, seed=seed, max_evals=300)
        _, counts, _ = sample_final_qaoa(h, J, opt_res, seed=seed, shots=4096)
        elapsed = time.time() - t0

        e_q = compute_expected_cost(counts, scen)
        lift = compute_lift(c_rand, e_q, c_star)
        enrichment = compute_elite_enrichment(counts, elite_set)

        best_sample = min(counts.keys(), key=lambda s: cost(s, scen))
        best_cost = cost(best_sample, scen)

        lifts.append(lift)
        seed_results.append({
            "seed": seed,
            "E_Q": round(e_q, 2),
            "lift": round(lift, 4),
            "elite_enrichment": round(enrichment, 2),
            "best_sample": best_sample,
            "best_sample_cost": round(best_cost, 2),
            "evals_used": opt_res["evaluations_used"],
            "time_sec": round(elapsed, 2),
        })

    robustness = compute_robustness(lifts)
    mean_lift = float(np.mean(lifts))
    mean_enrichment = float(np.mean([r["elite_enrichment"] for r in seed_results]))

    return {
        "scenario": scen_name,
        "C_star": c_star,
        "C_rand": c_rand,
        "seeds": seed_results,
        "mean_lift": round(mean_lift, 4),
        "robustness_clipped_min_lift": round(robustness, 4),
        "mean_enrichment": round(mean_enrichment, 2),
    }


def format_markdown_table(all_scenario_results: List[Dict[str, Any]]) -> str:
    lines = [
        "# Multi-Seed QAOA Performance Evaluation",
        "",
        "Evaluation across 7 independent random seeds (depth $p=3$, budget $\\le 300$ evaluations, 4096 shots per seed).",
        "",
    ]

    for res in all_scenario_results:
        scen = res["scenario"]
        lines.append(f"### Scenario: {scen} ($C^* = {res['C_star']}, C_{{rand}} = {res['C_rand']:.2f}$)")
        lines.append("")
        lines.append("| Seed | $E_Q$ (Mean Cost) | Lift | Elite Enrichment (Top 13) | Best Sample Cost | Evaluations | Time (s) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in res["seeds"]:
            lines.append(
                f"| {r['seed']} | {r['E_Q']} | {r['lift']:.4f} | {r['elite_enrichment']:.2f}x | {r['best_sample_cost']} | {r['evals_used']} | {r['time_sec']}s |"
            )
        lines.append("")
        lines.append(f"- **Mean Lift**: `{res['mean_lift']:.4f}`")
        lines.append(f"- **Robustness (Worst-Seed Lift Clipped to [0, 1])**: `{res['robustness_clipped_min_lift']:.4f}`")
        lines.append(f"- **Mean Elite Enrichment**: `{res['mean_enrichment']:.2f}x`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Multi-Seed Performance Evaluation for QAOA")
    parser.add_argument("--scenarios", nargs="+", default=["scenarios/R.json", "scenarios/H_placeholder.json"], help="Scenario paths to evaluate")
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS_DEFAULT, help="Seeds to run")
    parser.add_argument("--p", type=int, default=3, help="QAOA depth p")
    parser.add_argument("--out-md", type=str, default="experiments/eval_seeds_report.md", help="Path to markdown output")
    parser.add_argument("--out-json", type=str, default="experiments/eval_seeds_report.json", help="Path to JSON output")
    args = parser.parse_args()

    results = []
    for scen_path in args.scenarios:
        p = Path(scen_path)
        if p.exists():
            print(f"Running multi-seed evaluation on {scen_path} across seeds {args.seeds}...")
            scen_res = evaluate_scenario_seeds(p, args.seeds, p=args.p)
            results.append(scen_res)
            print(f"  Done {scen_res['scenario']}: Mean Lift = {scen_res['mean_lift']:.4f}, Robustness = {scen_res['robustness_clipped_min_lift']:.4f}")

    md_content = format_markdown_table(results)
    print("\n" + md_content)

    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md_content)

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Report saved to {args.out_md} and {args.out_json}")


if __name__ == "__main__":
    main()
