"""Traffic simulation and exact official cost model for Quantum Traffic Gridlock.

Two connected intersections A and B over four 30-second slots.
Decision bits ordered: A slot 1..4, followed by B slot 1..4.
Bit 1 = North-South (NS) green, Bit 0 = East-West (EW) green.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple, Union


def parse_schedule(schedule: Union[str, int, List[int], Tuple[int, ...]]) -> List[int]:
    """Parse schedule into a list of 8 binary integers [A1..A4, B1..B4]."""
    if isinstance(schedule, str):
        cleaned = schedule.replace(" ", "").replace("|", "")
        if len(cleaned) != 8 or not all(c in "01" for c in cleaned):
            raise ValueError(f"Schedule string must be 8 binary characters, got '{schedule}'")
        return [int(c) for c in cleaned]
    elif isinstance(schedule, int):
        if not (0 <= schedule < 256):
            raise ValueError(f"Integer schedule must be in [0, 255], got {schedule}")
        # schedule as integer: bit 0 is MSB or format as 8-bit string
        s = f"{schedule:08b}"
        return [int(c) for c in s]
    elif isinstance(schedule, (list, tuple)):
        if len(schedule) != 8 or not all(x in (0, 1) for x in schedule):
            raise ValueError(f"Schedule list must contain 8 binary integers (0 or 1), got {schedule}")
        return [int(x) for x in schedule]
    else:
        raise TypeError(f"Unsupported schedule type: {type(schedule)}")


def schedule_to_str(bits: List[int]) -> str:
    """Format 8-bit schedule as an 8-character string."""
    return "".join(str(b) for b in bits)


def simulate(
    schedule: Union[str, int, List[int], Tuple[int, ...]],
    scenario: Dict[str, Any],
) -> Tuple[float, float, float, int]:
    """Simulate the 4-slot traffic network and calculate official costs.

    Returns:
        (total_cost, delay, overflow, switches)
    """
    bits = parse_schedule(schedule)
    a_bits = bits[:4]
    b_bits = bits[4:]

    capacity = scenario["capacity"]
    storage = scenario["storage"]
    overflow_weight = float(scenario["overflow_weight"])
    switch_weight = float(scenario["switch_weight"])
    link_approach = scenario["link"]["approach"]
    link_fraction = float(scenario["link"]["fraction"])

    queues = {
        "A": {"NS": 0, "EW": 0},
        "B": {"NS": 0, "EW": 0},
    }
    transfers_to_b = {"NS": [0] * 4, "EW": [0] * 4}

    total_delay = 0.0
    total_overflow = 0.0

    for t in range(4):
        # Step 1: External arrivals + transfers arriving from preceding slot
        for inter in ("A", "B"):
            for app in ("NS", "EW"):
                queues[inter][app] += scenario["arrivals"][inter][app][t]
                if inter == "B":
                    queues[inter][app] += transfers_to_b[app][t]

        # Step 2: Service
        # 1 = NS green, 0 = EW green
        green_a = "NS" if a_bits[t] == 1 else "EW"
        green_b = "NS" if b_bits[t] == 1 else "EW"

        served_a = {}
        for app in ("NS", "EW"):
            served = min(queues[inter_name := "A"][app], capacity) if app == green_a else 0
            served_a[app] = served
            queues["A"][app] -= served

        served_b = {}
        for app in ("NS", "EW"):
            served = min(queues["B"][app], capacity) if app == green_b else 0
            served_b[app] = served
            queues["B"][app] -= served

        # Step 3: Record delay and overflow from queues remaining after service
        for inter in ("A", "B"):
            for app in ("NS", "EW"):
                q = queues[inter][app]
                total_delay += q
                total_overflow += max(0, q - storage)

        # Step 4: Transfer on directed A -> B link
        dep_a_link = served_a[link_approach]
        transfer_val = math.floor(link_fraction * dep_a_link + 0.5)
        if t + 1 < 4:
            transfers_to_b[link_approach][t + 1] += transfer_val

    # Switches: count bit changes between adjacent slots at each intersection (no pre-slot-1 cost)
    switches_a = sum(1 for t in range(3) if a_bits[t] != a_bits[t + 1])
    switches_b = sum(1 for t in range(3) if b_bits[t] != b_bits[t + 1])
    total_switches = switches_a + switches_b

    total_cost = total_delay + overflow_weight * total_overflow + switch_weight * total_switches
    return total_cost, total_delay, total_overflow, total_switches


def cost(
    schedule: Union[str, int, List[int], Tuple[int, ...]],
    scenario: Dict[str, Any],
) -> float:
    """Official cost function: cost(schedule, scenario)."""
    total_cost, _, _, _ = simulate(schedule, scenario)
    return total_cost


def enumerate_all(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Exhaustively evaluate all 256 schedules (benchmark only).

    Returns:
        dict with keys:
          'all_costs': dict { '00000000': cost, ... }
          'C_star': min cost among all 256
          'best_schedule': optimal 8-bit string (ties broken by ascending bitstring)
          'C_rand': uniform average cost across all 256
          'sorted_schedules': list of (bitstring, cost) sorted by cost asc, bitstring asc
    """
    all_costs: Dict[str, float] = {}
    for i in range(256):
        bitstr = f"{i:08b}"
        c = cost(bitstr, scenario)
        all_costs[bitstr] = c

    # Sort schedules: lowest cost first; break ties by ascending bitstring
    sorted_schedules = sorted(all_costs.items(), key=lambda item: (item[1], item[0]))
    best_schedule, c_star = sorted_schedules[0]
    c_rand = sum(all_costs.values()) / 256.0

    return {
        "all_costs": all_costs,
        "C_star": c_star,
        "best_schedule": best_schedule,
        "C_rand": c_rand,
        "sorted_schedules": sorted_schedules,
    }
