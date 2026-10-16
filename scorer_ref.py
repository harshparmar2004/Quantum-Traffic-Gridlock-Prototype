"""Reference official scorer for Quantum Traffic Gridlock.

Evaluates an 8-bit schedule on a given traffic scenario JSON.
Does not construct QUBO or optimize.
"""

from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union


def score(
    scenario: Union[str, Path, Dict[str, Any]],
    schedule: Union[str, int, List[int]],
) -> Dict[str, Any]:
    """Calculate the official cost of an 8-bit schedule for a scenario.

    Schedule bits: A slot 1..4 followed by B slot 1..4.
    1 = NS green, 0 = EW green.
    """
    if isinstance(scenario, (str, Path)):
        with open(scenario, "r", encoding="utf-8") as f:
            scen_data = json.load(f)
    else:
        scen_data = scenario

    # Parse schedule
    if isinstance(schedule, str):
        cleaned = schedule.replace(" ", "").replace("|", "")
        bits = [int(c) for c in cleaned]
    elif isinstance(schedule, int):
        bits = [int(c) for c in f"{schedule:08b}"]
    else:
        bits = [int(c) for c in schedule]

    if len(bits) != 8:
        raise ValueError(f"Schedule must be exactly 8 bits, got length {len(bits)}")

    a_bits = bits[:4]
    b_bits = bits[4:]

    capacity = scen_data["capacity"]
    storage = scen_data["storage"]
    overflow_weight = float(scen_data["overflow_weight"])
    switch_weight = float(scen_data["switch_weight"])
    link_app = scen_data["link"]["approach"]
    link_frac = float(scen_data["link"]["fraction"])

    queues = {
        "A": {"NS": 0, "EW": 0},
        "B": {"NS": 0, "EW": 0},
    }
    transfers_to_b = {"NS": [0] * 4, "EW": [0] * 4}

    total_delay = 0.0
    total_overflow = 0.0

    for t in range(4):
        # 1. External arrivals and transfers
        for inter in ("A", "B"):
            for app in ("NS", "EW"):
                queues[inter][app] += scen_data["arrivals"][inter][app][t]
                if inter == "B":
                    queues[inter][app] += transfers_to_b[app][t]

        # 2. Service
        green_a = "NS" if a_bits[t] == 1 else "EW"
        green_b = "NS" if b_bits[t] == 1 else "EW"

        served_a = {}
        for app in ("NS", "EW"):
            s = min(queues["A"][app], capacity) if app == green_a else 0
            served_a[app] = s
            queues["A"][app] -= s

        served_b = {}
        for app in ("NS", "EW"):
            s = min(queues["B"][app], capacity) if app == green_b else 0
            served_b[app] = s
            queues["B"][app] -= s

        # 3. Delay and overflow
        for inter in ("A", "B"):
            for app in ("NS", "EW"):
                q = queues[inter][app]
                total_delay += q
                total_overflow += max(0, q - storage)

        # 4. Directed A -> B transfer
        dep_a_link = served_a[link_app]
        transfer_val = math.floor(link_frac * dep_a_link + 0.5)
        if t + 1 < 4:
            transfers_to_b[link_app][t + 1] += transfer_val

    switches_a = sum(1 for t in range(3) if a_bits[t] != a_bits[t + 1])
    switches_b = sum(1 for t in range(3) if b_bits[t] != b_bits[t + 1])
    total_switches = switches_a + switches_b

    total_cost = total_delay + overflow_weight * total_overflow + switch_weight * total_switches

    return {
        "cost": total_cost,
        "delay": total_delay,
        "overflow": total_overflow,
        "switches": total_switches,
        "schedule": "".join(str(b) for b in bits),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Official Reference Scorer for Quantum Traffic Gridlock")
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    parser.add_argument("--schedule", required=True, help="8-bit schedule (e.g. 10101010 or 1010|1010)")
    args = parser.parse_args()

    res = score(args.scenario, args.schedule)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
