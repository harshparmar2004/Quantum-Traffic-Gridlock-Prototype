"""Tests ensuring scenario independence and lack of hardcoded lookups."""

from pathlib import Path
import numpy as np
import pytest
from traffic.scenario import sample_random_scenario
from traffic.qubo import build_qubo, solve_qubo_brute_force
from traffic.model import cost, enumerate_all
from run import execute_pipeline


def test_no_hardcoding_across_scenarios(tmp_path):
    """Pipeline must execute unmodified on multiple diverse random scenarios producing distinct valid results."""
    rng = np.random.default_rng(2026)
    scenario_files = []

    for i in range(5):
        scen = sample_random_scenario(rng=rng, name=f"random_scen_{i}")
        file_path = tmp_path / f"scen_{i}.json"
        import json
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(scen, f)
        scenario_files.append(file_path)

    results = []
    for i, scen_file in enumerate(scenario_files):
        out_dir = tmp_path / f"out_{i}"
        metrics = execute_pipeline(
            scenario_path=scen_file,
            seed=100 + i,
            out_dir=out_dir,
            p=2,
            max_evals=100,
            verbose=False,
        )
        assert metrics["total_shots"] == 4096
        assert metrics["evaluations_used"] <= 100
        assert metrics["C_star"] <= metrics["C_rand"]
        assert (out_dir / "qubo.json").exists()
        assert (out_dir / "circuit.qasm").exists()
        assert (out_dir / "counts.json").exists()
        assert (out_dir / "schedule.json").exists()
        assert (out_dir / "metrics.json").exists()
        results.append(metrics)

    # Verify that different scenarios produced different optimal costs and schedules (no static lookup)
    c_stars = [r["C_star"] for r in results]
    assert len(set(c_stars)) > 1, f"Expected varied C* across scenarios, got {c_stars}"


def test_no_r_arrivals_hardcoded_in_source():
    """Verify that Scenario R's specific arrivals are not hard-coded in library code."""
    r_arrivals_sig = "3, 6, 6, 3"
    project_root = Path(__file__).resolve().parent.parent
    traffic_src = list((project_root / "traffic").glob("*.py"))

    for src_file in traffic_src:
        content = src_file.read_text(encoding="utf-8")
        assert r_arrivals_sig not in content, f"Found hard-coded Scenario R arrivals in {src_file.name}"
