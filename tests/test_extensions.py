"""Unit tests for Section 11 Innovation Extensions and Fourier QAOA."""

from pathlib import Path
import numpy as np
import pytest

from traffic.scenario import load_scenario
from traffic.qubo import build_qubo
from traffic.qaoa_fourier import fourier_to_angles, train_qaoa_fourier
from experiments.extension_corridor import build_corridor_qubo, generate_corridor_scenario, simulate_corridor_qaoa_cpu
from experiments.extension_safety import add_minimum_green_penalty
from experiments.extension_noise_zne import evaluate_zne


@pytest.fixture
def scenario_r():
    return load_scenario(Path(__file__).resolve().parent.parent / "scenarios" / "R.json")


def test_fourier_qaoa_angles_and_budget(scenario_r):
    """Fourier parameterization must reduce optimization dimensionality while respecting budget."""
    qubo_data = build_qubo(scenario_r)
    h, J = qubo_data["h"], qubo_data["J"]

    u = np.array([0.5, -0.1])
    v = np.array([0.6, 0.1])
    gamma, beta = fourier_to_angles(u, v, p=3)
    assert len(gamma) == 3
    assert len(beta) == 3

    opt = train_qaoa_fourier(h, J, p=3, q=2, seed=42, max_evals=100)
    assert opt["evaluations_used"] <= 100
    assert len(opt["optimal_gamma"]) == 3
    assert len(opt["optimal_beta"]) == 3


def test_corridor_12qubit_extension():
    """12-qubit corridor QUBO must construct properly and solve on CPU."""
    scen = generate_corridor_scenario(seed=42)
    Q, offset = build_corridor_qubo(scen)
    assert Q.shape == (12, 12)
    assert np.allclose(Q, np.triu(Q))  # upper-triangular

    res = simulate_corridor_qaoa_cpu(Q, offset, p=1, seed=42)
    assert res["num_qubits"] == 12
    assert len(res["best_schedule_12bits"]) == 12
    assert res["runtime_seconds"] < 5.0  # CPU simulation must run quickly


def test_minimum_green_safety_penalty(scenario_r):
    """Safety penalty must penalize 1-slot fluttering schedules more than smooth schedules."""
    qubo_data = build_qubo(scenario_r)
    Q = np.array(qubo_data["Q"])

    Q_safe = add_minimum_green_penalty(Q, lambda_safety=5.0)
    assert Q_safe.shape == (8, 8)
    assert np.allclose(Q_safe, np.triu(Q_safe))

    # Fluttering schedule 10101010 vs smooth schedule 11001100
    x_flutter = np.array([1, 0, 1, 0, 1, 0, 1, 0])
    x_smooth = np.array([1, 1, 0, 0, 1, 1, 0, 0])

    penalty_flutter = float(x_flutter @ (Q_safe - Q) @ x_flutter)
    penalty_smooth = float(x_smooth @ (Q_safe - Q) @ x_smooth)

    assert penalty_flutter > penalty_smooth, f"Flutter penalty ({penalty_flutter}) should exceed smooth ({penalty_smooth})"


def test_noise_zne_extension():
    """Zero-Noise Extrapolation must compute valid mitigated estimate."""
    res = evaluate_zne("scenarios/R.json")
    assert "zne_mitigated_lift" in res
    assert res["measured_lifts"][0] > res["measured_lifts"][-1]  # noise degrades lift
    assert abs(res["zne_mitigated_lift"] - res["ideal_lift_zero_noise"]) < 0.10
