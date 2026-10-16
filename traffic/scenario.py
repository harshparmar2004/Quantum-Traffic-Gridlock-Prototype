"""Scenario loader, validator, and random scenario sampler for Quantum Traffic Gridlock."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union
import numpy as np


def validate_scenario(scenario: Dict[str, Any]) -> None:
    """Validate scenario schema and value types."""
    required_keys = ["capacity", "storage", "overflow_weight", "switch_weight", "link", "arrivals"]
    for k in required_keys:
        if k not in scenario:
            raise ValueError(f"Scenario missing required key: {k}")

    if not isinstance(scenario["capacity"], (int, float)) or scenario["capacity"] <= 0:
        raise ValueError(f"Invalid capacity: {scenario['capacity']}")

    if not isinstance(scenario["storage"], (int, float)) or scenario["storage"] <= 0:
        raise ValueError(f"Invalid storage: {scenario['storage']}")

    link = scenario["link"]
    if link.get("approach") not in ("NS", "EW"):
        raise ValueError(f"Link approach must be 'NS' or 'EW', got {link.get('approach')}")
    if not (0.0 <= float(link.get("fraction", -1)) <= 1.0):
        raise ValueError(f"Link fraction must be between 0 and 1, got {link.get('fraction')}")

    arrivals = scenario["arrivals"]
    for inter in ("A", "B"):
        if inter not in arrivals:
            raise ValueError(f"Arrivals missing intersection {inter}")
        for app in ("NS", "EW"):
            if app not in arrivals[inter]:
                raise ValueError(f"Arrivals missing {inter}->{app}")
            arr = arrivals[inter][app]
            if len(arr) != 4 or not all(isinstance(x, (int, float)) and x >= 0 for x in arr):
                raise ValueError(f"Arrivals for {inter}->{app} must be 4 non-negative numbers, got {arr}")


def load_scenario(source: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
    """Load and validate scenario from JSON file path or existing dictionary."""
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(f"Scenario file not found: {source}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(source, dict):
        data = source
    else:
        raise TypeError(f"Invalid source type for scenario: {type(source)}")

    validate_scenario(data)
    return data


def sample_random_scenario(
    seed: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Sample a random scenario within the hidden challenge ranges:
    - arrivals: 0..8 (integers)
    - capacity: 4..6 (integers)
    - storage: 5..8 (integers)
    - overflow_weight: 2.0..6.0 (float)
    - switch_weight: 0.25..1.5 (float in steps of 0.25)
    - link approach: NS or EW
    - link fraction: 0.40..0.80 (float)
    """
    if rng is None:
        rng = np.random.default_rng(seed)

    capacity = int(rng.integers(4, 7))       # 4, 5, or 6
    storage = int(rng.integers(5, 9))        # 5, 6, 7, or 8
    overflow_weight = float(rng.uniform(2.0, 6.0))
    switch_weight = float(rng.choice([0.25, 0.5, 0.75, 1.0, 1.25, 1.5]))
    link_app = str(rng.choice(["NS", "EW"]))
    link_fraction = float(np.round(rng.uniform(0.40, 0.80), 2))

    arrivals: Dict[str, Dict[str, list]] = {"A": {}, "B": {}}
    for inter in ("A", "B"):
        for app in ("NS", "EW"):
            arrivals[inter][app] = [int(x) for x in rng.integers(0, 9, size=4)]

    scenario_name = name or f"rand_{rng.integers(10000, 99999)}"
    scenario = {
        "name": scenario_name,
        "capacity": capacity,
        "storage": storage,
        "overflow_weight": round(overflow_weight, 2),
        "switch_weight": switch_weight,
        "link": {
            "approach": link_app,
            "fraction": link_fraction,
        },
        "arrivals": arrivals,
    }
    validate_scenario(scenario)
    return scenario
