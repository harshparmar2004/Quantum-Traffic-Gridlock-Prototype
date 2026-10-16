"""Baseline algorithms and diagnostic evaluators for Quantum Traffic Gridlock."""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple, Union
from traffic.model import cost, enumerate_all, parse_schedule, schedule_to_str


def alternating_baseline(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline 1: Best of four alternating schedules.
    A in {1010, 0101} x B in {1010, 0101}.
    """
    candidates = [
        "10101010",
        "10100101",
        "01011010",
        "01010101",
    ]
    scored = []
    for cand in candidates:
        c = cost(cand, scenario)
        scored.append((c, cand))
    scored.sort(key=lambda item: (item[0], item[1]))
    best_c, best_sched = scored[0]
    return {
        "name": "alternating_best",
        "best_schedule": best_sched,
        "cost": best_c,
        "candidates": {cand: c for c, cand in scored},
    }


def greedy_baseline(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline 2: Per-slot greedy control serving the larger queue after arrivals (ties to NS).

    At each slot t:
    1. Queue receives external arrivals (and B receives previous slot's transfer).
    2. Intersection serves approach with larger queue; if equal, ties break to NS (bit 1).
    3. Departures on linked approach generate transfer to B for slot t+1.
    4. Queues update after service.
    Returns the resulting 8-bit schedule and its official cost.
    """
    capacity = scenario["capacity"]
    link_app = scenario["link"]["approach"]
    link_fraction = float(scenario["link"]["fraction"])

    queues = {
        "A": {"NS": 0, "EW": 0},
        "B": {"NS": 0, "EW": 0},
    }
    transfers_to_b = {"NS": [0] * 4, "EW": [0] * 4}

    a_bits: List[int] = []
    b_bits: List[int] = []

    for t in range(4):
        # A arrivals
        queues["A"]["NS"] += scenario["arrivals"]["A"]["NS"][t]
        queues["A"]["EW"] += scenario["arrivals"]["A"]["EW"][t]

        # Greedy choice for A: tie breaks to NS (1)
        if queues["A"]["NS"] >= queues["A"]["EW"]:
            bit_a = 1
            served_app_a = "NS"
        else:
            bit_a = 0
            served_app_a = "EW"
        a_bits.append(bit_a)

        # Service at A
        dep_a = min(queues["A"][served_app_a], capacity)
        queues["A"][served_app_a] -= dep_a

        # Transfer calculation
        link_dep_a = dep_a if served_app_a == link_app else 0
        transfer_val = math.floor(link_fraction * link_dep_a + 0.5)
        if t + 1 < 4:
            transfers_to_b[link_app][t + 1] += transfer_val

        # B arrivals + transfers
        queues["B"]["NS"] += scenario["arrivals"]["B"]["NS"][t] + transfers_to_b["NS"][t]
        queues["B"]["EW"] += scenario["arrivals"]["B"]["EW"][t] + transfers_to_b["EW"][t]

        # Greedy choice for B: tie breaks to NS (1)
        if queues["B"]["NS"] >= queues["B"]["EW"]:
            bit_b = 1
            served_app_b = "NS"
        else:
            bit_b = 0
            served_app_b = "EW"
        b_bits.append(bit_b)

        # Service at B
        dep_b = min(queues["B"][served_app_b], capacity)
        queues["B"][served_app_b] -= dep_b

    schedule_bits = a_bits + b_bits
    sched_str = schedule_to_str(schedule_bits)
    official_c = cost(sched_str, scenario)

    return {
        "name": "greedy_per_slot",
        "schedule": sched_str,
        "cost": official_c,
    }


def uniform_random_baseline(enum_result: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline 4: Expected cost under uniform random schedule selection."""
    return {
        "name": "uniform_random",
        "cost": enum_result["C_rand"],
    }


def qubo_minimizer_baseline(
    qubo_data: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """Baseline 5: Exact minimizer of the QUBO evaluated by official scorer (surrogate ceiling).

    Searches all 256 bitstrings for min(x^T Q x + offset), then scores that schedule with the official scorer.
    """
    Q = qubo_data["Q"]
    offset = qubo_data.get("offset", 0.0)

    best_energy = float("inf")
    best_qubo_bits = "00000000"

    for i in range(256):
        bitstr = f"{i:08b}"
        x = [int(c) for c in bitstr]
        energy = offset
        for r in range(8):
            for c in range(r, 8):
                if x[r] and x[c]:
                    energy += Q[r][c]
        if energy < best_energy:
            best_energy = energy
            best_qubo_bits = bitstr

    official_c = cost(best_qubo_bits, scenario)
    return {
        "name": "qubo_exact_minimizer",
        "schedule": best_qubo_bits,
        "qubo_energy": best_energy,
        "official_cost": official_c,
    }


def classical_refinement_hybrid(
    seed_schedule: str,
    scenario: Dict[str, Any],
) -> Tuple[str, float]:
    """Optional hybrid refinement: 1-bit flip local hill-climbing on official cost."""
    current_bits = [int(c) for c in seed_schedule]
    current_cost = cost(current_bits, scenario)

    improved = True
    while improved:
        improved = False
        for bit_idx in range(8):
            neighbor = list(current_bits)
            neighbor[bit_idx] = 1 - neighbor[bit_idx]
            cand_cost = cost(neighbor, scenario)
            if cand_cost < current_cost:
                current_cost = cand_cost
                current_bits = neighbor
                improved = True
                break

    return schedule_to_str(current_bits), current_cost
