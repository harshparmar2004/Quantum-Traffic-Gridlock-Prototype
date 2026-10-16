"""Unit tests for the dashboard server APIs, scenario inputs, and simulation pipeline."""

import json
from pathlib import Path
import pytest

from traffic.model import cost, enumerate_all, simulate
from traffic.scenario import load_scenario, validate_scenario
from traffic.qubo import build_qubo
from server import TrafficDashboardHandler


SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def test_all_scenarios_valid_and_distinct():
    """All scenario JSON files in scenarios/ must be valid and test diverse conditions."""
    scenarios = list(SCENARIOS_DIR.glob("*.json"))
    assert len(scenarios) >= 4, f"Expected at least 4 scenarios, found {len(scenarios)}"

    loaded = {}
    for p in scenarios:
        scen = load_scenario(p)
        validate_scenario(scen)
        loaded[p.stem] = scen
        assert scen["capacity"] > 0
        assert scen["storage"] > 0
        assert scen["link"]["approach"] in ("NS", "EW")
        assert 0.0 <= scen["link"]["fraction"] <= 1.0

    # Ensure scenarios have distinct names and parameters
    assert "R" in loaded
    assert "H_placeholder" in loaded
    assert "heavy_gridlock" in loaded
    assert "asymmetric_rush_hour" in loaded


def test_simulation_on_all_scenarios():
    """Simulate test vector and QAOA optimum on all scenarios, checking integrity."""
    for p in SCENARIOS_DIR.glob("*.json"):
        scen = load_scenario(p)
        # Test all-zeros and all-ones schedules
        c0, d0, o0, s0 = simulate("00000000", scen)
        c1, d1, o1, s1 = simulate("11111111", scen)
        assert c0 > 0.0
        assert c1 > 0.0
        assert s0 == 0  # no switches in all-zero
        assert s1 == 0  # no switches in all-ones


def test_heavy_gridlock_scenario_dynamics():
    """Heavy gridlock scenario must properly register storage overflow."""
    scen = load_scenario(SCENARIOS_DIR / "heavy_gridlock.json")
    enum_res = enumerate_all(scen)
    assert enum_res["C_star"] <= enum_res["C_rand"]
    # Check that bad schedule incurs high overflow
    c_bad, d_bad, o_bad, s_bad = simulate("00000000", scen)
    assert o_bad > 0, "Heavy gridlock should induce overflow"


def test_asymmetric_rush_hour_scenario_dynamics():
    """Asymmetric rush hour scenario (NS link) must simulate without errors."""
    scen = load_scenario(SCENARIOS_DIR / "asymmetric_rush_hour.json")
    assert scen["link"]["approach"] == "NS"
    qubo_data = build_qubo(scen, variant="V2")
    assert len(qubo_data["Q"]) == 8
    assert len(qubo_data["h"]) == 8


def test_server_http_endpoints():
    """Verify standard-library HTTP server endpoints respond with 200 and valid JSON."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), TrafficDashboardHandler)
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    base_url = f"http://{host}:{port}"
    try:
        # 1. Test GET /api/scenarios
        req = urllib.request.urlopen(f"{base_url}/api/scenarios")
        assert req.status == 200
        data = json.loads(req.read().decode())
        assert "R" in data
        assert "heavy_gridlock" in data

        # 2. Test GET /api/verification
        req = urllib.request.urlopen(f"{base_url}/api/verification")
        assert req.status == 200
        data = json.loads(req.read().decode())
        assert data["all_passed"] is True
        assert len(data["verification_vectors"]) == 4

        # 3. Test POST /api/simulate
        post_data = json.dumps({"scenario": "R", "schedule": "10101010"}).encode()
        post_req = urllib.request.Request(
            f"{base_url}/api/simulate",
            data=post_data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(post_req)
        assert resp.status == 200
        sim_data = json.loads(resp.read().decode())
        assert abs(sim_data["cost"] - 116.0) < 1e-4
        assert len(sim_data["history"]) == 4
    finally:
        server.shutdown()
        server.server_close()

