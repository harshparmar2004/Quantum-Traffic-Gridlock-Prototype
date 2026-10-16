"""Section 11 Innovation Extension: Quantum Noise Resilience & Zero-Noise Extrapolation (ZNE).

Simulates NISQ depolarizing noise channels on CPU without external dependencies (no qiskit-aer):
    E(rho) = (1 - lambda) * rho + (lambda / 3) * (X rho X + Y rho Y + Z rho Z)

Demonstrates:
1. Performance degradation under increasing physical noise rates lambda in [0, 0.04]
2. Recovery of ideal sampling quality using Richardson Zero-Noise Extrapolation (ZNE)
"""

from __future__ import annotations
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.scenario import load_scenario
from traffic.model import enumerate_all, cost
from traffic.qubo import build_qubo
from traffic.qaoa import train_qaoa, simulate_qaoa_statevector, compute_basis_energies
from traffic.metrics import compute_expected_cost, compute_lift


def simulate_noisy_qaoa_density_matrix(
    energies: np.ndarray,
    gamma_list: List[float],
    beta_list: List[float],
    depol_rate: float = 0.01,
) -> np.ndarray:
    """Simulate QAOA under depolarizing noise channel using diagonal density approximation."""
    # Compute clean pure state
    psi = simulate_qaoa_statevector(energies, gamma_list, beta_list)
    clean_probs = np.abs(psi) ** 2

    if depol_rate <= 1e-9:
        return clean_probs

    # Under 8-qubit local depolarizing channels with rate lambda per layer:
    # effective channel probability of preserving state across p layers is (1 - lambda)^(8*p)
    p = len(gamma_list)
    survival_prob = (1.0 - depol_rate) ** (8 * p)

    # Mixed distribution: survival * clean + (1 - survival) * maximally mixed (uniform)
    uniform_prob = np.ones(256) / 256.0
    noisy_probs = survival_prob * clean_probs + (1.0 - survival_prob) * uniform_prob
    return noisy_probs / np.sum(noisy_probs)


def evaluate_zne(scenario_path: str = "scenarios/R.json") -> Dict[str, Any]:
    scen = load_scenario(scenario_path)
    enum_res = enumerate_all(scen)
    c_star = enum_res["C_star"]
    c_rand = enum_res["C_rand"]

    qubo_data = build_qubo(scen)
    h, J = qubo_data["h"], qubo_data["J"]
    opt = train_qaoa(h, J, p=3, seed=42)

    # Map computational basis index i to standard schedule bitstring where qubit q is index q
    all_costs = np.zeros(256)
    for i in range(256):
        bitstr = "".join(str((i >> q) & 1) for q in range(8))
        all_costs[i] = enum_res["all_costs"][bitstr]
    energies = compute_basis_energies(opt["h_norm"], opt["J_norm"])

    noise_levels = [0.0, 0.005, 0.01, 0.02, 0.03]
    measured_lifts = []

    for lmb in noise_levels:
        probs = simulate_noisy_qaoa_density_matrix(energies, opt["optimal_gamma"], opt["optimal_beta"], depol_rate=lmb)
        e_q = float(np.dot(probs, all_costs))
        lift = compute_lift(c_rand, e_q, c_star)
        measured_lifts.append(lift)

    # Richardson extrapolation from noise levels lambda=0.01 and 2*lambda=0.02
    # ZNE estimate: E_0 = 2 * E(lambda) - E(2*lambda)
    idx_1 = noise_levels.index(0.01)
    idx_2 = noise_levels.index(0.02)
    zne_lift = 2.0 * measured_lifts[idx_1] - measured_lifts[idx_2]

    return {
        "scenario": scen.get("name", "R"),
        "noise_levels": noise_levels,
        "measured_lifts": [round(x, 4) for x in measured_lifts],
        "ideal_lift_zero_noise": round(measured_lifts[0], 4),
        "unmitigated_lift_at_1pct_noise": round(measured_lifts[idx_1], 4),
        "zne_mitigated_lift": round(zne_lift, 4),
        "mitigation_error": round(abs(zne_lift - measured_lifts[0]), 4),
    }


def main():
    res = evaluate_zne("scenarios/R.json")
    print("--- QUANTUM NOISE RESILIENCE & ZNE MITIGATION ---")
    for lmb, lift in zip(res["noise_levels"], res["measured_lifts"]):
        print(f"Noise Rate lambda={lmb:0.3f} -> Measured Lift: {lift:.4f}")
    print(f"\nIdeal Lift (Zero Noise):     {res['ideal_lift_zero_noise']:.4f}")
    print(f"Unmitigated (1% Noise):      {res['unmitigated_lift_at_1pct_noise']:.4f}")
    print(f"ZNE Mitigated Estimate:      {res['zne_mitigated_lift']:.4f} (Error: {res['mitigation_error']:.4f})")

    out_file = Path("experiments/extension_noise_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
