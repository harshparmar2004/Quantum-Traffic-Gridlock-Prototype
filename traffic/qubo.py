"""QUBO and Ising Hamiltonian derivation from grounded traffic fluid dynamics.

Variables:
  x_0..x_3: Intersection A green indicator for slots 1..4 (1 = NS, 0 = EW).
  x_4..x_7: Intersection B green indicator for slots 1..4 (1 = NS, 0 = EW).
No auxiliary variables (exactly 8 qubits).

Fluid Dynamics Formulation:
  Cumulative queue for approach k at intersection I after slot t:
    Q_{I,k,t}(x) = Inflow_{I,k,t}(x) - Service_{I,k,t}(x)
  which is an exact affine function of binary decision variables x:
    Q_{I,k,t}(x) = q0 + sum_{i=0}^7 a_i x_i

Surrogate Objective:
  H(x) = alpha * sum_{I,k,t} Q_{I,k,t}^2
       + beta * overflow_weight * sum_{I,k,t} OverflowPenalty(Q_{I,k,t}, storage, margin)
       + switch_weight * sum_{switches} (x_t + x_{t+1} - 2 x_t x_{t+1})

Reduction to Upper-Triangular QUBO:
  Since x_i in {0, 1}, x_i^2 = x_i. All diagonal terms fold into linear terms.
Conversion to Ising:
  x_i = (1 - Z_i) / 2 where Z_i in {-1, +1}.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


VARIABLE_NAMES = [
    "A_slot1", "A_slot2", "A_slot3", "A_slot4",
    "B_slot1", "B_slot2", "B_slot3", "B_slot4",
]

# Calibrated global default hyperparameters (derived from >=300 hidden-range scenarios)
DEFAULT_ALPHA = 1.0
DEFAULT_BETA = 0.05
DEFAULT_MARGIN = 1.0
DEFAULT_VARIANT = "V2"


def qubo_to_ising(
    Q: Union[np.ndarray, List[List[float]]],
    offset: float = 0.0,
) -> Tuple[List[float], Dict[str, float], float]:
    """Convert an 8x8 upper-triangular QUBO to an Ising Hamiltonian:
        H_Ising(Z) = ising_offset + sum_i h_i Z_i + sum_{i<j} J_{ij} Z_i Z_j
    via x_i = (1 - Z_i) / 2.
    """
    Q_arr = np.array(Q, dtype=float)
    n = Q_arr.shape[0]
    h = np.zeros(n)
    J_dict: Dict[str, float] = {}
    ising_offset = float(offset)

    for i in range(n):
        # Linear/diagonal term: Q_ii x_i = Q_ii/2 - (Q_ii/2) Z_i
        ising_offset += Q_arr[i, i] / 2.0
        h[i] -= Q_arr[i, i] / 2.0
        for j in range(i + 1, n):
            q_ij = Q_arr[i, j]
            if abs(q_ij) > 1e-12:
                # Quadratic term: Q_ij x_i x_j = Q_ij/4 - (Q_ij/4) Z_i - (Q_ij/4) Z_j + (Q_ij/4) Z_i Z_j
                ising_offset += q_ij / 4.0
                h[i] -= q_ij / 4.0
                h[j] -= q_ij / 4.0
                J_dict[f"({i},{j})"] = float(q_ij / 4.0)

    return h.tolist(), J_dict, float(ising_offset)


def build_qubo(
    scenario: Dict[str, Any],
    alpha: float = DEFAULT_ALPHA,
    beta: float = DEFAULT_BETA,
    margin: float = DEFAULT_MARGIN,
    variant: str = DEFAULT_VARIANT,
) -> Dict[str, Any]:
    """Construct a scenario-independent traffic QUBO matrix Q and Ising representation.

    Variants:
      'V0': Plain squared queue (Lyapunov-drift) + exact switching cost.
      'V1': V0 + quadratic overflow penalty on queues exceeding storage buffer.
      'V2': V1 + demand-capped effective service rates (better departure/transfer estimation).
    """
    cap = float(scenario["capacity"])
    storage = float(scenario["storage"])
    ow = float(scenario["overflow_weight"])
    sw = float(scenario["switch_weight"])
    link_app = scenario["link"]["approach"]
    link_frac = float(scenario["link"]["fraction"])
    arrivals = scenario["arrivals"]

    # Effective capacity per slot (V2 demand-capping)
    c_eff = {
        "A": {"NS": [cap] * 4, "EW": [cap] * 4},
        "B": {"NS": [cap] * 4, "EW": [cap] * 4},
    }
    if variant == "V2":
        for inter in ("A", "B"):
            for app in ("NS", "EW"):
                cum_arr = 0.0
                for s in range(4):
                    cum_arr += arrivals[inter][app][s]
                    d_est = cum_arr / (s + 1.0) + 1.0
                    c_eff[inter][app][s] = float(min(cap, max(1.0, d_est)))

    # Compute linear expressions Q_{I,k,t}(x) = q0 + sum_i a_i x_i
    # Variables: 0..3 are A_slot1..4, 4..7 are B_slot1..4
    queue_expressions = []
    for t in range(4):
        # Intersection A, approach NS: green = x_s
        q0_a_ns = float(sum(arrivals["A"]["NS"][: t + 1]))
        a_a_ns = np.zeros(8)
        for s in range(t + 1):
            a_a_ns[s] -= c_eff["A"]["NS"][s]
        queue_expressions.append(("A", "NS", t, q0_a_ns, a_a_ns))

        # Intersection A, approach EW: green = (1 - x_s)
        c_a_ew_sum = sum(c_eff["A"]["EW"][s] for s in range(t + 1))
        q0_a_ew = float(sum(arrivals["A"]["EW"][: t + 1])) - c_a_ew_sum
        a_a_ew = np.zeros(8)
        for s in range(t + 1):
            a_a_ew[s] += c_eff["A"]["EW"][s]
        queue_expressions.append(("A", "EW", t, q0_a_ew, a_a_ew))

        # Intersection B, approach NS: green = x_{4+s}
        q0_b_ns = float(sum(arrivals["B"]["NS"][: t + 1]))
        a_b_ns = np.zeros(8)
        if link_app == "NS":
            for s in range(1, t + 1):
                a_b_ns[s - 1] += link_frac * c_eff["A"]["NS"][s - 1]
        for s in range(t + 1):
            a_b_ns[4 + s] -= c_eff["B"]["NS"][s]
        queue_expressions.append(("B", "NS", t, q0_b_ns, a_b_ns))

        # Intersection B, approach EW: green = (1 - x_{4+s})
        c_b_ew_sum = sum(c_eff["B"]["EW"][s] for s in range(t + 1))
        q0_b_ew = float(sum(arrivals["B"]["EW"][: t + 1])) - c_b_ew_sum
        a_b_ew = np.zeros(8)
        if link_app == "EW":
            for s in range(1, t + 1):
                dep_c = c_eff["A"]["EW"][s - 1]
                q0_b_ew += link_frac * dep_c
                a_b_ew[s - 1] -= link_frac * dep_c
        for s in range(t + 1):
            a_b_ew[4 + s] += c_eff["B"]["EW"][s]
        queue_expressions.append(("B", "EW", t, q0_b_ew, a_b_ew))

    Q = np.zeros((8, 8))
    offset = 0.0

    # 1. Queue Balance / Lyapunov Drift: alpha * Q^2
    for inter, app, t, q0, a in queue_expressions:
        offset += alpha * q0 * q0
        for i in range(8):
            Q[i, i] += alpha * (2 * q0 * a[i] + a[i] ** 2)
            for j in range(i + 1, 8):
                Q[i, j] += alpha * (2 * a[i] * a[j])

        # 2. Overflow penalty (V1 and V2)
        if variant in ("V1", "V2") and beta > 0:
            q_max = q0 + sum(max(0.0, val) for val in a)
            if q_max > storage:
                d0 = q0 - (storage - margin)
                weight = beta * ow * max(0.1, (q_max - storage) / cap)
                offset += weight * d0 * d0
                for i in range(8):
                    Q[i, i] += weight * (2 * d0 * a[i] + a[i] ** 2)
                    for j in range(i + 1, 8):
                        Q[i, j] += weight * (2 * a[i] * a[j])

    # 3. Switching cost: switch_weight * (x_t + x_{t+1} - 2 x_t x_{t+1})
    for offset_idx in (0, 4):
        for t in range(3):
            i = offset_idx + t
            j = offset_idx + t + 1
            Q[i, i] += sw
            Q[j, j] += sw
            Q[i, j] -= 2.0 * sw

    # Convert to Ising
    h, J_dict, ising_offset = qubo_to_ising(Q, offset)

    return {
        "Q": Q.tolist(),
        "offset": float(offset),
        "h": h,
        "J": J_dict,
        "ising_offset": ising_offset,
        "variable_to_schedule_bit": VARIABLE_NAMES,
        "auxiliary_variables": [],
        "variant": variant,
        "constants": {
            "alpha": float(alpha),
            "beta": float(beta),
            "margin": float(margin),
        },
    }


def qubo_energy(
    x: Union[str, List[int], np.ndarray],
    Q: Union[List[List[float]], np.ndarray],
    offset: float = 0.0,
) -> float:
    """Calculate energy x^T Q x + offset for binary vector x."""
    if isinstance(x, str):
        x_vec = np.array([int(c) for c in x], dtype=float)
    else:
        x_vec = np.array(x, dtype=float)
    Q_arr = np.array(Q, dtype=float)
    return float(x_vec @ Q_arr @ x_vec + offset)


def ising_energy(
    z: Union[List[int], np.ndarray],
    h: List[float],
    J_dict: Dict[str, float],
    ising_offset: float = 0.0,
) -> float:
    """Calculate energy sum_i h_i Z_i + sum_{i<j} J_{ij} Z_i Z_j + ising_offset for Z in {-1, +1}."""
    z_arr = np.array(z, dtype=float)
    energy = ising_offset + float(np.dot(h, z_arr))
    for key, val in J_dict.items():
        # key is "(i,j)"
        parts = key.strip("()").split(",")
        i, j = int(parts[0]), int(parts[1])
        energy += val * z_arr[i] * z_arr[j]
    return float(energy)


def solve_qubo_brute_force(
    Q: Union[List[List[float]], np.ndarray],
    offset: float = 0.0,
) -> Tuple[str, float]:
    """Find the exact minimizer of the 8-variable QUBO by testing all 256 states."""
    best_energy = float("inf")
    best_schedule = "00000000"
    for i in range(256):
        bitstr = f"{i:08b}"
        e = qubo_energy(bitstr, Q, offset)
        if e < best_energy:
            best_energy = e
            best_schedule = bitstr
    return best_schedule, best_energy
