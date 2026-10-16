"""QAOA circuit construction, fast exact statevector training, and deterministic 4096-shot sampler.

Complies strictly with IBM Qiskit Fall Fest 2026 rules:
- 8 qubits (no auxiliary variables)
- Circuit depth p <= 4 (default p = 3)
- Max 300 total objective function evaluations across all restarts
- Exact 4096 shots sampled deterministically from the final bound state
- Export to valid OpenQASM 3 format
"""

from __future__ import annotations
import math
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import numpy as np
from scipy.optimize import minimize

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
import qiskit.qasm3


MAX_EVALS_DEFAULT = 300
DEFAULT_P = 3


class EvaluationBudgetExceeded(Exception):
    """Raised when evaluation budget is exhausted."""
    pass


class BudgetCounter:
    """Thread-safe and restart-aware function evaluation counter."""

    def __init__(self, max_evals: int = MAX_EVALS_DEFAULT):
        self.max_evals = max_evals
        self.count = 0

    def increment(self) -> None:
        if self.count >= self.max_evals:
            raise EvaluationBudgetExceeded(f"Budget of {self.max_evals} evaluations exceeded.")
        self.count += 1

    @property
    def remaining(self) -> int:
        return max(0, self.max_evals - self.count)


def build_qaoa_circuit(
    h: List[float],
    J_dict: Dict[str, float],
    gamma_list: List[float],
    beta_list: List[float],
    include_measurements: bool = False,
) -> QuantumCircuit:
    """Build the 8-qubit QAOA QuantumCircuit with bound parameter angles.

    - Layer 0: Hadamard on all 8 qubits.
    - For layer l in 1..p:
        - Cost unitary: RZ(2 * gamma * h_i) and RZZ(2 * gamma * J_ij).
        - Mixer unitary: RX(2 * beta) on all 8 qubits.
    """
    p = len(gamma_list)
    qc = QuantumCircuit(8)
    qc.h(range(8))

    for layer in range(p):
        gamma = gamma_list[layer]
        beta = beta_list[layer]

        # Cost unitary e^{-i gamma H_C}
        for i in range(8):
            if abs(h[i]) > 1e-12:
                qc.rz(2.0 * gamma * h[i], i)

        for key, val in J_dict.items():
            parts = key.strip("()").split(",")
            i, j = int(parts[0]), int(parts[1])
            if abs(val) > 1e-12:
                qc.rzz(2.0 * gamma * val, i, j)

        # Mixer unitary e^{-i beta sum X}
        for i in range(8):
            qc.rx(2.0 * beta, i)

    if include_measurements:
        qc.measure_all()

    return qc


def compute_basis_energies(h: List[float], J_dict: Dict[str, float]) -> np.ndarray:
    """Compute the 256 computational basis energies for the normalized Ising Hamiltonian.

    Basis state index k in [0, 255]:
    Qubit i state is bit i of k: (k >> i) & 1.
    Spin Z_i = +1 if bit is 0, -1 if bit is 1.
    """
    h_arr = np.array(h, dtype=float)
    energies = np.zeros(256, dtype=float)

    for k in range(256):
        z = np.array([1.0 - 2.0 * float((k >> i) & 1) for i in range(8)])
        e = float(np.dot(h_arr, z))
        for key, val in J_dict.items():
            parts = key.strip("()").split(",")
            i, j = int(parts[0]), int(parts[1])
            e += val * z[i] * z[j]
        energies[k] = e

    return energies


def simulate_qaoa_statevector(
    energies: np.ndarray,
    gamma_list: List[float],
    beta_list: List[float],
) -> np.ndarray:
    """Simulate exact 8-qubit QAOA statevector propagation using tensordot."""
    p = len(gamma_list)
    # Uniform superposition state: |+>^8
    psi = np.ones(256, dtype=complex) / 16.0

    for layer in range(p):
        gamma = gamma_list[layer]
        beta = beta_list[layer]

        # 1. Cost layer: diagonal phase rotation
        psi = psi * np.exp(-1j * gamma * energies)

        # 2. Mixer layer: single-qubit RX(2*beta) on all 8 qubits
        c = np.cos(beta)
        s = -1j * np.sin(beta)
        Ux = np.array([[c, s], [s, c]], dtype=complex)

        psi_tensor = psi.reshape([2] * 8)
        for i in range(8):
            # In Qiskit, index k = sum_{i=0}^7 q_i 2^i, so qubit i corresponds to axis (7 - i)
            axis = 7 - i
            psi_tensor = np.tensordot(Ux, psi_tensor, axes=[[1], [axis]])
            psi_tensor = np.moveaxis(psi_tensor, 0, axis)
        psi = psi_tensor.flatten()

    return psi


def evaluate_qaoa_objective(
    params: np.ndarray,
    p: int,
    energies: np.ndarray,
    budget: BudgetCounter,
    cvar_alpha: float = 1.0,
) -> float:
    """Compute expectation value or CVaR of normalized Ising energy."""
    budget.increment()

    gamma_list = params[:p].tolist()
    beta_list = params[p:].tolist()

    psi = simulate_qaoa_statevector(energies, gamma_list, beta_list)
    probs = np.abs(psi) ** 2

    if cvar_alpha >= 1.0:
        # Standard expectation value
        return float(np.dot(probs, energies))
    else:
        # CVaR objective: average over lowest cvar_alpha quantile
        sorted_indices = np.argsort(energies)
        cum_prob = 0.0
        cvar_sum = 0.0
        for idx in sorted_indices:
            p_k = probs[idx]
            if cum_prob + p_k <= cvar_alpha:
                cvar_sum += p_k * energies[idx]
                cum_prob += p_k
            else:
                remaining = cvar_alpha - cum_prob
                cvar_sum += remaining * energies[idx]
                break
        return float(cvar_sum / cvar_alpha)


def train_qaoa(
    h: List[float],
    J_dict: Dict[str, float],
    p: int = DEFAULT_P,
    seed: int = 42,
    max_evals: int = MAX_EVALS_DEFAULT,
    cvar_alpha: float = 1.0,
) -> Dict[str, Any]:
    """Train QAOA variational parameters (gamma, beta) using multi-restart COBYLA."""
    rng = np.random.default_rng(seed)

    # 1. Normalization: scale coefficients so gamma ranges are sensible
    all_coeffs = [abs(x) for x in h] + [abs(v) for v in J_dict.values()]
    scale = max(all_coeffs) if all_coeffs and max(all_coeffs) > 1e-12 else 1.0

    h_norm = [x / scale for x in h]
    J_norm = {k: v / scale for k, v in J_dict.items()}

    energies = compute_basis_energies(h_norm, J_norm)
    budget = BudgetCounter(max_evals=max_evals)

    # Initial parameter schedules
    # Restart 0: Linear ramp (Trotterized quantum annealing)
    gamma_ramp = [(l + 0.5) / p * 0.7 for l in range(p)]
    beta_ramp = [(1.0 - (l + 0.5) / p) * 0.7 for l in range(p)]
    initial_candidates = [np.array(gamma_ramp + beta_ramp)]

    # 2 additional random restarts (3 restarts total)
    for _ in range(2):
        rand_gamma = rng.uniform(0.0, np.pi, size=p)
        rand_beta = rng.uniform(0.0, np.pi / 2.0, size=p)
        initial_candidates.append(np.concatenate([rand_gamma, rand_beta]))

    best_energy = float("inf")
    best_params = initial_candidates[0]

    for init_p in initial_candidates:
        if budget.remaining <= 0:
            break

        max_iter_for_run = min(100, budget.remaining)

        def objective(x):
            return evaluate_qaoa_objective(x, p, energies, budget, cvar_alpha=cvar_alpha)

        try:
            res = minimize(
                objective,
                init_p,
                method="COBYLA",
                options={"maxiter": max_iter_for_run, "rhobeg": 0.5, "tol": 1e-3},
            )
            if res.fun < best_energy:
                best_energy = float(res.fun)
                best_params = np.array(res.x)
        except EvaluationBudgetExceeded:
            break

    opt_gamma = (best_params[:p]).tolist()
    opt_beta = (best_params[p:]).tolist()

    return {
        "p": p,
        "scale": float(scale),
        "h_norm": h_norm,
        "J_norm": J_norm,
        "optimal_gamma": opt_gamma,
        "optimal_beta": opt_beta,
        "final_energy": float(best_energy),
        "evaluations_used": int(budget.count),
    }


def sample_final_qaoa(
    h: List[float],
    J_dict: Dict[str, float],
    opt_result: Dict[str, Any],
    seed: int,
    shots: int = 4096,
) -> Tuple[QuantumCircuit, Dict[str, int], str]:
    """Sample exactly `shots` (default 4096) from the trained QAOA circuit deterministically."""
    h_norm = opt_result["h_norm"]
    J_norm = opt_result["J_norm"]
    opt_gamma = opt_result["optimal_gamma"]
    opt_beta = opt_result["optimal_beta"]

    # 1. Build circuit without measurements for statevector sampling
    circ_no_meas = build_qaoa_circuit(h_norm, J_norm, opt_gamma, opt_beta, include_measurements=False)
    sv = Statevector(circ_no_meas)
    sv.seed(seed)

    # 2. Sample counts
    raw_counts = sv.sample_counts(shots)

    # 3. Standardize bitstring keys:
    # Qiskit sample_counts returns little-endian keys [q7, q6, ..., q0].
    # Reversing maps bit index i to schedule bit i (qubit i): [A1..A4, B1..B4].
    standard_counts: Dict[str, int] = {}
    for raw_key, count in raw_counts.items():
        standard_key = str(raw_key)[::-1]
        standard_counts[standard_key] = int(count)

    # Verify shot count
    total_shots = sum(standard_counts.values())
    if total_shots != shots:
        raise ValueError(f"Expected exactly {shots} shots, got {total_shots}")

    # 4. Build circuit with measurements for OpenQASM 3 export
    circ_with_meas = build_qaoa_circuit(h_norm, J_norm, opt_gamma, opt_beta, include_measurements=True)
    qasm3_str = qiskit.qasm3.dumps(circ_with_meas)

    return circ_with_meas, standard_counts, qasm3_str
