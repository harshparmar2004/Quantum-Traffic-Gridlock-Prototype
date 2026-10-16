"""Section 11 Innovation Extension: 3-Intersection Arterial Corridor (A -> B -> C).

Models a linear arterial cascade of three coordinated traffic intersections (A, B, C)
over four 30-second slots:
- 12 binary decision variables: [A1..A4, B1..B4, C1..C4] (12 qubits <= 16 limit)
- Directed link A -> B with transfer fraction f_AB
- Directed link B -> C with transfer fraction f_BC
- Grounded cumulative fluid queue dynamics with inter-intersection couplings
- Fast 12-qubit statevector QAOA simulation (4,096 states) executed entirely on CPU
"""

from __future__ import annotations
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Tuple
import numpy as np
from scipy.optimize import minimize

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.qubo import qubo_to_ising


def generate_corridor_scenario(seed: int = 42) -> Dict[str, Any]:
    """Generate a representative 3-intersection arterial corridor scenario."""
    rng = np.random.default_rng(seed)
    return {
        "name": "Arterial_Corridor_3x4",
        "intersections": ["A", "B", "C"],
        "num_qubits": 12,
        "capacity": 5,
        "storage": 8,
        "overflow_weight": 3.0,
        "switch_weight": 0.5,
        "links": {
            "A_to_B": {"approach": "EW", "fraction": 0.6},
            "B_to_C": {"approach": "EW", "fraction": 0.5},
        },
        "arrivals": {
            "A": {
                "NS": [int(x) for x in rng.integers(2, 6, size=4)],
                "EW": [int(x) for x in rng.integers(3, 7, size=4)],
            },
            "B": {
                "NS": [int(x) for x in rng.integers(2, 5, size=4)],
                "EW": [int(x) for x in rng.integers(1, 4, size=4)],
            },
            "C": {
                "NS": [int(x) for x in rng.integers(2, 6, size=4)],
                "EW": [int(x) for x in rng.integers(1, 5, size=4)],
            },
        },
    }


def build_corridor_qubo(scenario: Dict[str, Any], alpha: float = 1.0) -> Tuple[np.ndarray, float]:
    """Construct 12x12 upper-triangular QUBO for the 3-intersection arterial network."""
    cap = float(scenario["capacity"])
    sw = float(scenario["switch_weight"])
    arr = scenario["arrivals"]
    f_ab = float(scenario["links"]["A_to_B"]["fraction"])
    f_bc = float(scenario["links"]["B_to_C"]["fraction"])
    app_ab = scenario["links"]["A_to_B"]["approach"]
    app_bc = scenario["links"]["B_to_C"]["approach"]

    # 12 decision variables: A(0..3), B(4..7), C(8..11)
    queue_expressions = []

    for t in range(4):
        # Intersection A:
        # NS: q0 = sum arr, a[s] = -cap (for s <= t)
        q0_a_ns = float(sum(arr["A"]["NS"][: t + 1]))
        a_a_ns = np.zeros(12)
        a_a_ns[: t + 1] = -cap
        queue_expressions.append((q0_a_ns, a_a_ns))

        # EW: q0 = sum arr - cap*(t+1), a[s] = +cap
        q0_a_ew = float(sum(arr["A"]["EW"][: t + 1])) - cap * (t + 1)
        a_a_ew = np.zeros(12)
        a_a_ew[: t + 1] = cap
        queue_expressions.append((q0_a_ew, a_a_ew))

        # Intersection B:
        # NS
        q0_b_ns = float(sum(arr["B"]["NS"][: t + 1]))
        a_b_ns = np.zeros(12)
        a_b_ns[4: 4 + t + 1] = -cap
        queue_expressions.append((q0_b_ns, a_b_ns))

        # EW: transfers from A
        q0_b_ew = float(sum(arr["B"]["EW"][: t + 1])) - cap * (t + 1)
        a_b_ew = np.zeros(12)
        if app_ab == "EW":
            for s in range(1, t + 1):
                q0_b_ew += f_ab * cap
                a_b_ew[s - 1] -= f_ab * cap
        a_b_ew[4: 4 + t + 1] = cap
        queue_expressions.append((q0_b_ew, a_b_ew))

        # Intersection C:
        # NS
        q0_c_ns = float(sum(arr["C"]["NS"][: t + 1]))
        a_c_ns = np.zeros(12)
        a_c_ns[8: 8 + t + 1] = -cap
        queue_expressions.append((q0_c_ns, a_c_ns))

        # EW: transfers from B
        q0_c_ew = float(sum(arr["C"]["EW"][: t + 1])) - cap * (t + 1)
        a_c_ew = np.zeros(12)
        if app_bc == "EW":
            for s in range(1, t + 1):
                q0_c_ew += f_bc * cap
                a_c_ew[4 + s - 1] -= f_bc * cap
        a_c_ew[8: 8 + t + 1] = cap
        queue_expressions.append((q0_c_ew, a_c_ew))

    Q = np.zeros((12, 12))
    offset = 0.0

    # Quadratic drift
    for q0, a in queue_expressions:
        offset += alpha * q0 * q0
        for i in range(12):
            Q[i, i] += alpha * (2.0 * q0 * a[i] + a[i] ** 2)
            for j in range(i + 1, 12):
                Q[i, j] += alpha * (2.0 * a[i] * a[j])

    # Switching cost at A (0..3), B (4..7), C (8..11)
    for base in [0, 4, 8]:
        for t in range(3):
            i = base + t
            j = base + t + 1
            Q[i, i] += sw
            Q[j, j] += sw
            Q[i, j] -= 2.0 * sw

    return Q, float(offset)


def simulate_corridor_qaoa_cpu(
    Q: np.ndarray,
    offset: float,
    p: int = 2,
    seed: int = 42,
) -> Dict[str, Any]:
    """Simulate 12-qubit QAOA on CPU for the corridor network."""
    t0 = time.time()
    n = 12
    dim = 1 << n  # 4096 states

    # Convert to Ising
    h, J_dict, ising_offset = qubo_to_ising(Q, offset)
    scale = max(max(abs(x) for x in h), max(abs(v) for v in J_dict.values()))
    h_norm = np.array([x / scale for x in h])
    J_norm = {k: v / scale for k, v in J_dict.items()}

    # Compute 4096 diagonal energies
    energies = np.zeros(dim)
    for k in range(dim):
        z = np.array([1.0 - 2.0 * float((k >> i) & 1) for i in range(n)])
        e = float(np.dot(h_norm, z))
        for key, val in J_norm.items():
            parts = key.strip("()").split(",")
            i, j = int(parts[0]), int(parts[1])
            e += val * z[i] * z[j]
        energies[k] = e

    # QAOA propagation
    def run_sim(params):
        gamma_list = params[:p]
        beta_list = params[p:]
        psi = np.ones(dim, dtype=complex) / np.sqrt(dim)
        for layer in range(p):
            psi = psi * np.exp(-1j * gamma_list[layer] * energies)
            c = np.cos(beta_list[layer])
            s = -1j * np.sin(beta_list[layer])
            Ux = np.array([[c, s], [s, c]], dtype=complex)
            psi_tensor = psi.reshape([2] * n)
            for i in range(n):
                axis = n - 1 - i
                psi_tensor = np.tensordot(Ux, psi_tensor, axes=[[1], [axis]])
                psi_tensor = np.moveaxis(psi_tensor, 0, axis)
            psi = psi_tensor.flatten()
        return psi

    def loss(params):
        psi = run_sim(params)
        probs = np.abs(psi) ** 2
        return float(np.dot(probs, energies))

    # Optimize with COBYLA
    init_params = np.array([0.4] * p + [0.4] * p)
    res = minimize(loss, init_params, method="COBYLA", options={"maxiter": 60})

    opt_psi = run_sim(res.x)
    probs = np.abs(opt_psi) ** 2
    best_state_idx = int(np.argmin(energies))
    sampled_energy = float(np.dot(probs, energies))
    ground_energy = float(energies[best_state_idx])
    uniform_energy = float(np.mean(energies))
    lift = (uniform_energy - sampled_energy) / (uniform_energy - ground_energy)

    elapsed = time.time() - t0
    best_schedule_bits = "".join(str((best_state_idx >> i) & 1) for i in range(n))

    return {
        "network": "3-Intersection Corridor (A -> B -> C)",
        "num_qubits": n,
        "depth_p": p,
        "runtime_seconds": round(elapsed, 3),
        "ground_energy": round(ground_energy, 4),
        "sampled_energy": round(sampled_energy, 4),
        "uniform_energy": round(uniform_energy, 4),
        "lift": round(lift, 4),
        "best_schedule_12bits": best_schedule_bits,
        "qubit_allocation": {
            "Intersection_A": best_schedule_bits[0:4],
            "Intersection_B": best_schedule_bits[4:8],
            "Intersection_C": best_schedule_bits[8:12],
        },
    }


def main():
    scenario = generate_corridor_scenario(seed=2026)
    print(f"Constructing 12-qubit QUBO for 3-intersection corridor {scenario['intersections']}...")
    Q, offset = build_corridor_qubo(scenario)
    print(f"QUBO shape: {Q.shape}, non-zero terms: {np.count_nonzero(Q)}")

    print("Running 12-qubit QAOA on CPU (4,096 basis states)...")
    res = simulate_corridor_qaoa_cpu(Q, offset, p=2, seed=42)
    print("\n--- 12-QUBIT CORRIDOR EXTENSION RESULTS ---")
    print(f"Runtime:       {res['runtime_seconds']}s")
    print(f"QAOA Lift:     {res['lift']:.4f}")
    print(f"Optimal Sched: A={res['qubit_allocation']['Intersection_A']} | B={res['qubit_allocation']['Intersection_B']} | C={res['qubit_allocation']['Intersection_C']}")

    out_file = Path("experiments/extension_corridor_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()
