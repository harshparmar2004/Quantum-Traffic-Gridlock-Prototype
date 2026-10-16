"""Unit tests for the official scorer and traffic simulation model."""

import json
from pathlib import Path
import pytest
from traffic.model import cost, enumerate_all, simulate
from traffic.scenario import load_scenario
from traffic.baselines import alternating_baseline, greedy_baseline
import scorer_ref


SCENARIO_R_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "R.json"


@pytest.fixture
def scenario_r():
    return load_scenario(SCENARIO_R_PATH)


def test_verification_vectors(scenario_r):
    """The four official verification vectors for Public Reference Scenario R must pass exactly."""
    vectors = [
        ("10101010", 116.0),
        ("11111111", 146.0),
        ("00000000", 237.0),
        ("01111001", 92.5),
    ]

    for bitstr, expected_cost in vectors:
        c, d, o, s = simulate(bitstr, scenario_r)
        assert c == expected_cost, f"Failed for {bitstr}: got {c}, expected {expected_cost}"

        # Also verify scorer_ref matches exactly
        ref_res = scorer_ref.score(scenario_r, bitstr)
        assert ref_res["cost"] == expected_cost
        assert ref_res["delay"] == d
        assert ref_res["overflow"] == o
        assert ref_res["switches"] == s


def test_all_256_schedules_consistency(scenario_r):
    """Verify that traffic.model and scorer_ref give identical results on all 256 schedules."""
    for i in range(256):
        bitstr = f"{i:08b}"
        c_model = cost(bitstr, scenario_r)
        c_ref = scorer_ref.score(scenario_r, bitstr)["cost"]
        assert c_model == c_ref, f"Mismatch on schedule {bitstr}: model={c_model}, ref={c_ref}"


def test_enumeration_properties(scenario_r):
    """Verify properties of full enumeration benchmark."""
    res = enumerate_all(scenario_r)
    assert len(res["all_costs"]) == 256
    assert res["C_star"] <= res["C_rand"]
    # Check that best schedule cost matches C_star
    assert res["all_costs"][res["best_schedule"]] == res["C_star"]


def test_baselines_run(scenario_r):
    """Verify alternating and greedy baselines execute and produce valid costs."""
    alt_res = alternating_baseline(scenario_r)
    assert "cost" in alt_res
    assert alt_res["best_schedule"] in alt_res["candidates"]

    greedy_res = greedy_baseline(scenario_r)
    assert "cost" in greedy_res
    assert len(greedy_res["schedule"]) == 8
    assert cost(greedy_res["schedule"], scenario_r) == greedy_res["cost"]
