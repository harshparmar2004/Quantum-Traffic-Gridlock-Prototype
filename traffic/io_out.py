"""Serialization utilities for run outputs: qubo.json, circuit.qasm, counts.json, schedule.json, metrics.json."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict


def write_outputs(
    out_dir: Union[str, Path],
    qubo_data: Dict[str, Any],
    qasm3_str: str,
    counts: Dict[str, int],
    schedules: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Path]:
    """Write all 5 required output files to the target output directory."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. qubo.json
    qubo_file = out_path / "qubo.json"
    with open(qubo_file, "w", encoding="utf-8") as f:
        json.dump(qubo_data, f, indent=2)

    # 2. circuit.qasm
    qasm_file = out_path / "circuit.qasm"
    with open(qasm_file, "w", encoding="utf-8") as f:
        f.write(qasm3_str)

    # 3. counts.json
    counts_file = out_path / "counts.json"
    with open(counts_file, "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2)

    # 4. schedule.json
    schedule_file = out_path / "schedule.json"
    with open(schedule_file, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2)

    # 5. metrics.json
    metrics_file = out_path / "metrics.json"
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    return {
        "qubo": qubo_file,
        "circuit": qasm_file,
        "counts": counts_file,
        "schedule": schedule_file,
        "metrics": metrics_file,
    }
