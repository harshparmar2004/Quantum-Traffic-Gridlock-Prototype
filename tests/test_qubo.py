"""Unit tests for QUBO and Ising formulation."""

import numpy as np
import pytest
from traffic.scenario import load_scenario, sample_random_scenario
from traffic.model import cost, enumerate_all
from traffic.qubo import (
    build_qubo,
    ising_energy,
    qubo_energy,
    qubo_to_ising,
    solve_qubo_brute_force,
)


@pytest.fixture
def scenario_r():
    from pathlib import Path
    return load_scenario(Path(__file__).resolve().parent.parent / "scenarios" / "R.json")


def test_qubo_shape_and_upper_triangular(scenario_r):
    """QUBO matrix must be exactly 8x8 and upper-triangular."""
    qubo_data = build_qubo(scenario_r)
    Q = np.array(qubo_data["Q"])
    assert Q.shape == (8, 8)
    assert len(qubo_data["auxiliary_variables"]) == 0
    assert len(qubo_data["variable_to_schedule_bit"]) == 8

    # Lower triangular elements (excluding diagonal) must be zero
    for i in range(8):
        for j in range(i):
            assert abs(Q[i, j]) < 1e-12, f"Q[{i},{j}] should be 0, got {Q[i, j]}"


def test_qubo_ising_energy_identity(scenario_r):
    """QUBO energy must exactly equal Ising energy for all 256 basis states."""
    qubo_data = build_qubo(scenario_r)
    Q = qubo_data["Q"]
    offset = qubo_data["offset"]
    h = qubo_data["h"]
    J = qubo_data["J"]
    ising_offset = qubo_data["ising_offset"]

    for i in range(256):
        bitstr = f"{i:08b}"
        x = [int(c) for c in bitstr]
        z = [1 - 2 * b for b in x]  # 0 -> +1, 1 -> -1

        e_qubo = qubo_energy(x, Q, offset)
        e_ising = ising_energy(z, h, J, ising_offset)
        assert abs(e_qubo - e_ising) < 1e-10, f"Energy mismatch for state {bitstr}: {e_qubo} vs {e_ising}"


def test_qubo_surrogate_regret_on_r(scenario_r):
    """QUBO surrogate must achieve <= 5% regret on reference scenario R."""
    qubo_data = build_qubo(scenario_r)
    best_sched, _ = solve_qubo_brute_force(qubo_data["Q"], qubo_data["offset"])
    c_qubo = cost(best_sched, scenario_r)
    enum_res = enumerate_all(scenario_r)
    c_star = enum_res["C_star"]

    regret = (c_qubo - c_star) / c_star
    assert regret <= 0.05, f"Surrogate regret {regret*100:.2f}% exceeds 5% on Scenario R"


def test_qubo_on_random_scenarios():
    """Verify QUBO formulation works seamlessly on randomly sampled hidden-range scenarios."""
    rng = np.random.default_rng(999)
    for _ in range(5):
        scen = sample_random_scenario(rng=rng)
        qubo_data = build_qubo(scen)
        assert len(qubo_data["Q"]) == 8
        assert len(qubo_data["h"]) == 8
        best_sched, _ = solve_qubo_brute_force(qubo_data["Q"], qubo_data["offset"])
        assert len(best_sched) == 8
        c = cost(best_sched, scen)
        assert c >= 0.0
