"""Fourier / Discrete Sine-Cosine Parameterization for QAOA.

Based on Zhou et al. (PRX Quantum 2020):
Instead of optimizing 2p independent angles in a high-dimensional landscape,
gamma and beta curves are parameterized in frequency space:
    gamma_l = sum_{k=1}^q u_k * sin((k - 0.5) * (l - 0.5) * pi / p)
    beta_l  = sum_{k=1}^q v_k * cos((k - 0.5) * (l - 0.5) * pi / p)

With q=2, an 8-variable optimization problem reduces from 2p dimensions to 4 dimensions,
enabling multi-restart COBYLA to converge significantly faster and find higher-lift distributions
within the strict 300-evaluation budget.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple
import numpy as np
from scipy.optimize import minimize

from traffic.qaoa import (
    BudgetCounter,
    EvaluationBudgetExceeded,
    compute_basis_energies,
    evaluate_qaoa_objective,
    simulate_qaoa_statevector,
)


def fourier_to_angles(
    u_vec: np.ndarray,
    v_vec: np.ndarray,
    p: int,
) -> Tuple[List[float], List[float]]:
    """Convert Fourier frequency coefficients (u, v) to layer angles (gamma, beta)."""
    q_u = len(u_vec)
    q_v = len(v_vec)

    gamma_list = []
    beta_list = []

    for l in range(1, p + 1):
        # gamma: discrete sine expansion
        g_l = 0.0
        for k in range(1, q_u + 1):
            g_l += u_vec[k - 1] * np.sin((k - 0.5) * (l - 0.5) * np.pi / float(p))
        gamma_list.append(float(g_l))

        # beta: discrete cosine expansion
        b_l = 0.0
        for k in range(1, q_v + 1):
            b_l += v_vec[k - 1] * np.cos((k - 0.5) * (l - 0.5) * np.pi / float(p))
        beta_list.append(float(b_l))

    return gamma_list, beta_list


def train_qaoa_fourier(
    h: List[float],
    J_dict: Dict[str, float],
    p: int = 3,
    q: int = 2,
    seed: int = 42,
    max_evals: int = 300,
    cvar_alpha: float = 1.0,
) -> Dict[str, Any]:
    """Train QAOA in Fourier parameter space under budget <= 300."""
    rng = np.random.default_rng(seed)

    all_coeffs = [abs(x) for x in h] + [abs(v) for v in J_dict.values()]
    scale = max(all_coeffs) if all_coeffs and max(all_coeffs) > 1e-12 else 1.0

    h_norm = [x / scale for x in h]
    J_norm = {k: v / scale for k, v in J_dict.items()}

    energies = compute_basis_energies(h_norm, J_norm)
    budget = BudgetCounter(max_evals=max_evals)

    # Initial frequency parameters (annealing ramp in frequency space)
    # For a linear ramp gamma ~ l/p, u1 dominates; for beta ~ (1 - l/p), v1 dominates
    initial_candidates = [
        np.array([0.65, 0.05, 0.65, -0.05][: 2 * q]),
        np.array([0.80, -0.10, 0.50, 0.10][: 2 * q]),
        rng.uniform(-0.5, 1.0, size=2 * q),
    ]

    best_energy = float("inf")
    best_uv = initial_candidates[0]

    for init_uv in initial_candidates:
        if budget.remaining <= 0:
            break

        max_iter = min(100, budget.remaining)

        def objective(uv):
            u_part = uv[:q]
            v_part = uv[q:]
            gamma_list, beta_list = fourier_to_angles(u_part, v_part, p)
            # Flatten into 2p format for statevector evaluation
            param_angles = np.array(gamma_list + beta_list)
            return evaluate_qaoa_objective(param_angles, p, energies, budget, cvar_alpha=cvar_alpha)

        try:
            res = minimize(
                objective,
                init_uv,
                method="COBYLA",
                options={"maxiter": max_iter, "rhobeg": 0.4, "tol": 1e-3},
            )
            if res.fun < best_energy:
                best_energy = float(res.fun)
                best_uv = np.array(res.x)
        except EvaluationBudgetExceeded:
            break

    opt_gamma, opt_beta = fourier_to_angles(best_uv[:q], best_uv[q:], p)

    return {
        "p": p,
        "q": q,
        "scale": float(scale),
        "h_norm": h_norm,
        "J_norm": J_norm,
        "optimal_u": best_uv[:q].tolist(),
        "optimal_v": best_uv[q:].tolist(),
        "optimal_gamma": opt_gamma,
        "optimal_beta": opt_beta,
        "final_energy": float(best_energy),
        "evaluations_used": int(budget.count),
    }
