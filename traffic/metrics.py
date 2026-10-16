"""Evaluation metrics for Quantum Traffic Gridlock: Lift, Elite Enrichment, Surrogate Regret, Robustness."""

from __future__ import annotations
from typing import Any, Dict, List, Set, Tuple
from traffic.model import cost, enumerate_all


def compute_expected_cost(counts: Dict[str, int], scenario: Dict[str, Any]) -> float:
    """Compute E_Q: mean official cost of sampled shots."""
    total_shots = sum(counts.values())
    if total_shots == 0:
        return float("inf")
    total_cost_weighted = 0.0
    for bitstr, count in counts.items():
        if count > 0:
            total_cost_weighted += count * cost(bitstr, scenario)
    return total_cost_weighted / total_shots


def compute_lift(c_rand: float, e_q: float, c_star: float) -> float:
    """Compute Lift: (C_rand - E_Q) / (C_rand - C*)."""
    denom = c_rand - c_star
    if abs(denom) < 1e-9:
        return 1.0 if abs(e_q - c_star) < 1e-9 else 0.0
    return float((c_rand - e_q) / denom)


def get_elite_set(enum_result: Dict[str, Any], elite_count: int = 13) -> Set[str]:
    """Select exactly the `elite_count` (default 13) lowest-cost schedules.
    Ties broken by canonical ascending bitstring.
    """
    sorted_schedules = enum_result["sorted_schedules"]
    elite_items = sorted_schedules[:elite_count]
    return {bitstr for bitstr, _ in elite_items}


def compute_elite_enrichment(
    counts: Dict[str, int],
    elite_set: Set[str],
    total_states: int = 256,
) -> float:
    """Compute Elite Enrichment: (fraction of shots in elite set) / (|elite| / total_states).
    For 13 schedules out of 256, uniform random sampling has expected enrichment = 1.0.
    """
    total_shots = sum(counts.values())
    if total_shots == 0 or len(elite_set) == 0:
        return 0.0

    elite_shots = sum(counts.get(s, 0) for s in elite_set)
    shot_fraction = elite_shots / total_shots
    random_prob = len(elite_set) / float(total_states)
    return float(shot_fraction / random_prob)


def compute_surrogate_regret(c_qubo: float, c_star: float) -> float:
    """Compute Surrogate Regret: (C(x*_QUBO) - C*) / C*."""
    if abs(c_star) < 1e-9:
        return 0.0
    return float((c_qubo - c_star) / c_star)


def compute_robustness(lifts: List[float]) -> float:
    """Compute Robustness: min lift across seeds clipped to [0, 1]."""
    if not lifts:
        return 0.0
    m = min(lifts)
    return float(max(0.0, min(1.0, m)))
