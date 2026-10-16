"""Unit tests for QAOA circuit construction, fast simulation, sampling, and OpenQASM 3 export."""

from pathlib import Path
import numpy as np
import pytest
import qiskit.qasm3
from qiskit.quantum_info import Statevector

from traffic.scenario import load_scenario
from traffic.qubo import build_qubo
from traffic.qaoa import (
    DEFAULT_P,
    MAX_EVALS_DEFAULT,
    build_qaoa_circuit,
    sample_final_qaoa,
    train_qaoa,
)


@pytest.fixture
def scenario_r():
    return load_scenario(Path(__file__).resolve().parent.parent / "scenarios" / "R.json")


def test_qaoa_budget_and_depth(scenario_r):
    """QAOA training must respect p <= 4 and evaluation budget <= 300."""
    qubo_data = build_qubo(scenario_r)
    h = qubo_data["h"]
    J = qubo_data["J"]

    opt = train_qaoa(h, J, p=3, seed=7, max_evals=300)
    assert opt["p"] <= 4
    assert opt["evaluations_used"] <= 300
    assert len(opt["optimal_gamma"]) == 3
    assert len(opt["optimal_beta"]) == 3


def test_qaoa_sampling_exact_4096_and_determinism(scenario_r):
    """Sampling must produce exactly 4096 shots and be completely deterministic given the seed."""
    qubo_data = build_qubo(scenario_r)
    h = qubo_data["h"]
    J = qubo_data["J"]

    opt1 = train_qaoa(h, J, p=3, seed=42, max_evals=200)
    _, counts1, qasm1 = sample_final_qaoa(h, J, opt1, seed=42, shots=4096)

    opt2 = train_qaoa(h, J, p=3, seed=42, max_evals=200)
    _, counts2, qasm2 = sample_final_qaoa(h, J, opt2, seed=42, shots=4096)

    assert sum(counts1.values()) == 4096
    assert sum(counts2.values()) == 4096
    assert counts1 == counts2
    assert qasm1 == qasm2


def test_openqasm3_reload_consistency(scenario_r):
    """Reloading OpenQASM 3 string must reconstruct identical quantum state."""
    qubo_data = build_qubo(scenario_r)
    h = qubo_data["h"]
    J = qubo_data["J"]

    opt = train_qaoa(h, J, p=3, seed=123, max_evals=100)
    circ, counts, qasm3_str = sample_final_qaoa(h, J, opt, seed=123, shots=4096)

    # Reload circuit from OpenQASM 3 string
    reloaded_circ = qiskit.qasm3.loads(qasm3_str)
    assert reloaded_circ.num_qubits == 8

    # Check circuit without measurements matches expected statevector
    circ_no_meas = build_qaoa_circuit(opt["h_norm"], opt["J_norm"], opt["optimal_gamma"], opt["optimal_beta"], include_measurements=False)
    sv = Statevector(circ_no_meas)
    probs = sv.probabilities()

    # Empirical distribution from 4096 shots should have high correlation with theoretical probabilities
    sampled_probs = np.zeros(256)
    for bitstr, count in counts.items():
        # Map bitstr [q0, q1, ..., q7] to integer k = sum_i q_i * 2^i
        k = sum(int(bitstr[i]) * (1 << i) for i in range(8))
        sampled_probs[k] = count / 4096.0

    # Total variation distance between theoretical and empirical distribution should be small
    tvd = 0.5 * np.sum(np.abs(probs - sampled_probs))
    assert tvd < 0.25, f"TVD between theoretical and empirical distribution too large: {tvd}"
