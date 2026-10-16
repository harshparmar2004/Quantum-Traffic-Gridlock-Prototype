"""Standard-library HTTP Backend Server for Quantum Traffic Gridlock Dashboard.

Serves the cloud-beige/orange frontend from dashboard/ and exposes REST APIs:
- GET  /api/scenarios: List available scenarios (R, H, heavy_gridlock, asymmetric_rush_hour)
- POST /api/simulate: Simulate any 8-bit schedule on a given scenario
- POST /api/run_qaoa: Run full QAOA circuit training and 4,096 sampling
- GET  /api/verification: Run official verification vectors with pass/fail badges

Requires zero external packages (standard library http.server).
"""

from __future__ import annotations
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import traceback
from typing import Any, Dict
import urllib.parse

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic.model import cost, enumerate_all, simulate
from traffic.scenario import load_scenario, sample_random_scenario, validate_scenario
from traffic.qubo import build_qubo, solve_qubo_brute_force
from traffic.qaoa import sample_final_qaoa, train_qaoa
from traffic.qaoa_fourier import train_qaoa_fourier
from traffic.metrics import (
    compute_elite_enrichment,
    compute_expected_cost,
    compute_lift,
    compute_surrogate_regret,
    get_elite_set,
)
from traffic.baselines import alternating_baseline, greedy_baseline


DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"


class TrafficDashboardHandler(SimpleHTTPRequestHandler):
    """HTTP request handler supporting static dashboard files and JSON REST APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self):
        # Enable CORS for local testing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/scenarios":
            self.handle_get_scenarios()
        elif parsed.path == "/api/verification":
            self.handle_get_verification()
        elif parsed.path == "/" or parsed.path == "/index.html":
            index_path = DASHBOARD_DIR / "index.html"
            if index_path.exists():
                content = index_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "Dashboard index.html not found.")
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)

        try:
            req_data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception as e:
            self.send_json({"error": f"Invalid JSON payload: {str(e)}"}, status=400)
            return

        try:
            if parsed.path == "/api/simulate":
                self.handle_simulate(req_data)
            elif parsed.path == "/api/run_qaoa":
                self.handle_run_qaoa(req_data)
            else:
                self.send_json({"error": f"Endpoint not found: {parsed.path}"}, status=404)
        except Exception as e:
            traceback.print_exc()
            self.send_json({"error": str(e), "traceback": traceback.format_exc()}, status=500)

    def handle_get_scenarios(self):
        scenarios = {}
        for p in SCENARIOS_DIR.glob("*.json"):
            try:
                data = json.load(open(p, encoding="utf-8"))
                scenarios[p.stem] = data
            except Exception:
                pass
        self.send_json(scenarios)

    def handle_get_verification(self):
        scen_r = load_scenario(SCENARIOS_DIR / "R.json")
        vectors = [
            {"schedule": "10101010", "expected": 116.0},
            {"11111111": "11111111", "schedule": "11111111", "expected": 146.0},
            {"schedule": "00000000", "expected": 237.0},
            {"schedule": "01111001", "expected": 92.5},
        ]
        results = []
        all_passed = True
        for v in vectors:
            sched = v["schedule"]
            exp = v["expected"]
            c, d, o, s = simulate(sched, scen_r)
            passed = abs(c - exp) < 1e-6
            if not passed:
                all_passed = False
            results.append({
                "schedule": sched,
                "expected_cost": exp,
                "actual_cost": c,
                "delay": d,
                "overflow": o,
                "switches": s,
                "passed": passed,
            })
        self.send_json({"all_passed": all_passed, "verification_vectors": results})

    def handle_simulate(self, req: Dict[str, Any]):
        scenario = req.get("scenario")
        if isinstance(scenario, str):
            scenario = load_scenario(SCENARIOS_DIR / f"{scenario}.json")
        validate_scenario(scenario)

        schedule = req.get("schedule", "11101010")
        total_cost, delay, overflow, switches = simulate(schedule, scenario)

        # Build slot-by-slot detail for frontend animation
        bits = [int(c) for c in schedule.replace(" ", "").replace("|", "")]
        a_bits = bits[:4]
        b_bits = bits[4:]
        cap = scenario["capacity"]
        storage = scenario["storage"]
        link_app = scenario["link"]["approach"]
        link_frac = float(scenario["link"]["fraction"])

        qA = {"NS": 0, "EW": 0}
        qB = {"NS": 0, "EW": 0}
        transfers = [0, 0, 0, 0]
        history = []

        for t in range(4):
            qA["NS"] += scenario["arrivals"]["A"]["NS"][t]
            qA["EW"] += scenario["arrivals"]["A"]["EW"][t]
            qB["NS"] += scenario["arrivals"]["B"]["NS"][t]
            qB["EW"] += scenario["arrivals"]["B"]["EW"][t]
            if link_app == "EW":
                qB["EW"] += transfers[t]
            else:
                qB["NS"] += transfers[t]

            gA = "NS" if a_bits[t] == 1 else "EW"
            gB = "NS" if b_bits[t] == 1 else "EW"

            sA = {
                "NS": min(qA["NS"], cap) if gA == "NS" else 0,
                "EW": min(qA["EW"], cap) if gA == "EW" else 0,
            }
            qA["NS"] -= sA["NS"]
            qA["EW"] -= sA["EW"]

            sB = {
                "NS": min(qB["NS"], cap) if gB == "NS" else 0,
                "EW": min(qB["EW"], cap) if gB == "EW" else 0,
            }
            qB["NS"] -= sB["NS"]
            qB["EW"] -= sB["EW"]

            dep_link = sA[link_app]
            trans_val = int(math_floor := int(link_frac * dep_link + 0.5))
            if t + 1 < 4:
                transfers[t + 1] = trans_val

            history.append({
                "slot": t,
                "greenA": gA,
                "greenB": gB,
                "queuesA": dict(qA),
                "queuesB": dict(qB),
                "servedA": sA,
                "servedB": sB,
                "transferToB": trans_val,
                "delaySlot": qA["NS"] + qA["EW"] + qB["NS"] + qB["EW"],
                "overflowSlot": max(0, qA["NS"] - storage) + max(0, qA["EW"] - storage) + max(0, qB["NS"] - storage) + max(0, qB["EW"] - storage),
            })

        self.send_json({
            "schedule": schedule,
            "cost": total_cost,
            "delay": delay,
            "overflow": overflow,
            "switches": switches,
            "history": history,
        })

    def handle_run_qaoa(self, req: Dict[str, Any]):
        scenario = req.get("scenario")
        if isinstance(scenario, str):
            scenario = load_scenario(SCENARIOS_DIR / f"{scenario}.json")
        validate_scenario(scenario)

        seed = int(req.get("seed", 42))
        p = int(req.get("p", 3))
        param_mode = str(req.get("param_mode", "fourier"))
        max_evals = min(300, int(req.get("max_evals", 300)))

        # Ground truth enumeration
        enum_res = enumerate_all(scenario)
        c_star = enum_res["C_star"]
        c_rand = enum_res["C_rand"]
        best_exact_sched = enum_res["best_schedule"]
        elite_set = get_elite_set(enum_res, elite_count=13)

        # Baselines
        alt_res = alternating_baseline(scenario)
        greedy_res = greedy_baseline(scenario)

        # QUBO
        qubo_data = build_qubo(scenario, variant="V2")
        h, J = qubo_data["h"], qubo_data["J"]

        # Train QAOA
        if param_mode == "fourier":
            opt = train_qaoa_fourier(h, J, p=p, q=2, seed=seed, max_evals=max_evals)
        else:
            opt = train_qaoa(h, J, p=p, seed=seed, max_evals=max_evals)

        # Sample
        _, counts, qasm3_str = sample_final_qaoa(h, J, opt, seed=seed, shots=4096)
        e_q = compute_expected_cost(counts, scenario)
        lift = compute_lift(c_rand, e_q, c_star)
        enrichment = compute_elite_enrichment(counts, elite_set)

        # Top 10 schedules by shot count
        top_sampled = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_list = [
            {"schedule": s, "count": cnt, "official_cost": cost(s, scenario), "is_elite": s in elite_set}
            for s, cnt in top_sampled
        ]

        self.send_json({
            "scenario_name": scenario.get("name", "Scenario"),
            "seed": seed,
            "p": p,
            "param_mode": param_mode,
            "evaluations_used": opt["evaluations_used"],
            "C_star": c_star,
            "C_rand": c_rand,
            "best_exact_schedule": best_exact_sched,
            "E_Q": round(e_q, 2),
            "lift": round(lift, 4),
            "elite_enrichment": round(enrichment, 2),
            "baselines": {
                "alternating": {"schedule": alt_res["best_schedule"], "cost": alt_res["cost"]},
                "greedy": {"schedule": greedy_res["schedule"], "cost": greedy_res["cost"]},
            },
            "top_samples": top_list,
            "circuit_qasm": qasm3_str,
        })


def run_server(port: int = 8000, host: str = "0.0.0.0"):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, TrafficDashboardHandler)
    print(f"\n========================================================")
    print(f" Quantum Traffic Gridlock Dashboard Server Started!")
    print(f" Local URL:   http://localhost:{port}")
    print(f" Network URL: http://{host}:{port}")
    print(f" Dashboard:   {DASHBOARD_DIR / 'index.html'}")
    print(f" Press Ctrl+C to stop.")
    print(f"========================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server gracefully...")
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="Quantum Traffic Gridlock Web Dashboard Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)


if __name__ == "__main__":
    main()
