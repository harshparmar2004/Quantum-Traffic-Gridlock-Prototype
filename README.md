# Quantum Traffic Gridlock

Quantum Optimization for Coordinated Urban Traffic Signals  
**IBM Qiskit Fall Fest 2026** | QC@IITI · IIT Indore

---

## Overview

`quantum-traffic-gridlock` is an end-to-end quantum optimization pipeline developed for the IBM Qiskit Fall Fest 2026 challenge. It coordinates traffic signal phases across two connected intersections ($A$ and $B$) over four 30-second time slots using the Quantum Approximate Optimization Algorithm (QAOA).

Key technical features:
- **Principled QUBO Formulation**: Derived from first-principles fluid queue dynamics and Lyapunov drift balance; **never** constructed by schedule enumeration or lookup.
- **8 Qubits (No Auxiliaries)**: Compact representation with exactly one qubit per intersection-slot pair.
- **Strict Competition Compliance**: QAOA depth $p \le 4$ (default $p=3$), $\le 300$ training evaluations, exactly 4,096 final shots, deterministic execution given seed, pure CPU execution (no network or Aer dependency).
- **Sub-5% Surrogate Regret**: Achieves **3.36% mean regret** across 300 random hidden-range scenarios and **0.00% regret** on Public Reference Scenario R.

---

## Bit Ordering Convention

Each schedule consists of **8 binary decision variables** ordered chronologically by intersection:

| Bit Index | Variable | Intersection | Time Slot | Meaning (1 / 0) |
| :---: | :---: | :---: | :---: | :---: |
| **0** | $x_{A,1}$ | Intersection A | Slot 1 (0–30s) | 1 = NS green, 0 = EW green |
| **1** | $x_{A,2}$ | Intersection A | Slot 2 (30–60s) | 1 = NS green, 0 = EW green |
| **2** | $x_{A,3}$ | Intersection A | Slot 3 (60–90s) | 1 = NS green, 0 = EW green |
| **3** | $x_{A,4}$ | Intersection A | Slot 4 (90–120s) | 1 = NS green, 0 = EW green |
| **4** | $x_{B,1}$ | Intersection B | Slot 1 (0–30s) | 1 = NS green, 0 = EW green |
| **5** | $x_{B,2}$ | Intersection B | Slot 2 (30–60s) | 1 = NS green, 0 = EW green |
| **6** | $x_{B,3}$ | Intersection B | Slot 3 (60–90s) | 1 = NS green, 0 = EW green |
| **7** | $x_{B,4}$ | Intersection B | Slot 4 (90–120s) | 1 = NS green, 0 = EW green |

*Qiskit Little-Endian Mapping*: Standard Qiskit measurement outcomes order qubits right-to-left (`q7...q0`). In our pipeline, bitstrings in `counts.json` and `schedule.json` are canonically normalized so that **bitstring index $i$ corresponds to decision variable $x_i$ (qubit $i$)**.

---

## Installation & Requirements

Requires **Python 3.10+**.

```bash
git clone https://github.com/your-org/quantum-traffic-gridlock.git
cd quantum-traffic-gridlock

# Install dependencies
pip install -r requirements.txt
```

Core dependencies:
- `qiskit >= 2.0.0`
- `numpy >= 1.24.0`
- `scipy >= 1.10.0`
- `qiskit-qasm3-import >= 0.5.0`
- `pytest >= 8.0.0` (for testing)
- `matplotlib >= 3.7.0` (for development/plots)

---

## Usage

### Run Optimization Pipeline

Execute on any scenario JSON file (Scenario R, H, or S):

```bash
python run.py --scenario scenarios/R.json --seed 7 --out out/R_seed7
```

CLI Options:
- `--scenario <path>`: Path to scenario JSON file (required).
- `--seed <int>`: Random seed for deterministic optimization and sampling (required).
- `--out <dir>`: Target output directory (required).
- `--p <int>`: QAOA circuit depth (default: 3, max: 4).
- `--max-evals <int>`: Maximum objective evaluations (default: 300, max: 300).
- `--variant {V0, V1, V2}`: QUBO formulation variant (default: `V2`).
- `--cvar-alpha <float>`: CVaR quantile parameter (default: 1.0 for standard expectation).
- `--quiet`: Suppress verbose stdout logs.

### Running Hidden Scenarios H and S

The pipeline runs unmodified on any hidden scenario conforming to the competition JSON schema:

```bash
python run.py --scenario scenarios/H.json --seed 42 --out out/H_seed42
```

---

## Output Files

Each run generates five deliverables in the specified output directory:

1. **`qubo.json`**:
   - $8 \times 8$ upper-triangular QUBO matrix $Q$ and constant offset.
   - Corresponding Ising Hamiltonian terms ($h$, $J$, and `ising_offset`).
   - Variable-to-schedule bit mapping and empty `auxiliary_variables` list.
   - Formulation variant and hyperparameters used.
2. **`circuit.qasm`**:
   - Final bound-parameter QAOA circuit exported in **OpenQASM 3** format.
3. **`counts.json`**:
   - Exactly 4,096 raw sampled measurement shots (`bitstring -> count`).
4. **`schedule.json`**:
   - Most frequent sample, best sample by official cost, QUBO exact minimizer, and optional hybrid classical refinement, with documented bit ordering.
5. **`metrics.json`**:
   - Detailed diagnostics: $C^*$, $C_{\text{rand}}$, $E_Q$, Lift, Elite Enrichment (top 13 schedules), Surrogate Regret, function evaluations, and runtime.

---

## Authoritative Scorer

Run the official reference scorer to evaluate any 8-bit schedule:

```bash
python scorer.py --scenario scenarios/R.json --schedule 10101010
```

---

## Experiments & Benchmarks

1. **Surrogate Regret Calibration** ($\ge 300$ random hidden-range scenarios):
   ```bash
   python experiments/calibrate_surrogate.py --num-scenarios 300 --seed 42
   ```
2. **Multi-Seed Robustness Evaluation** (seeds $0 \dots 6$):
   ```bash
   python experiments/eval_seeds.py --scenarios scenarios/R.json scenarios/H_placeholder.json
   ```
3. **Ablation Studies** (depth $p$, variants, CVaR):
   ```bash
   python experiments/ablations.py --scenario scenarios/R.json --seeds 0 1 2 3 4
   ```

---

## Test Suite

Run the full automated test suite (13 tests):

```bash
pytest -v tests/
```

Test coverage:
- `test_scorer.py`: All 4 official verification vectors and full 256-schedule consistency.
- `test_qubo.py`: QUBO matrix geometry, QUBO $\leftrightarrow$ Ising algebraic equivalence, and sub-5% surrogate regret on R.
- `test_qaoa.py`: Seed determinism, exact 4,096 shot count, evaluation budget compliance, and round-trip OpenQASM 3 reload.
- `test_no_hardcoding.py`: Multi-scenario generalization across 5 diverse random instances, verifying absence of static lookups.

---

## Repository Structure

```
quantum-traffic-gridlock/
  run.py                    # Main CLI entry point
  scorer.py                 # Official scorer entry point
  scorer_ref.py             # Reference authoritative evaluator
  pyproject.toml            # Project and pytest configuration
  requirements.txt          # Package dependencies
  README.md                 # Project documentation
  AI_DISCLOSURE.md          # 1-page required AI assistance declaration
  scenarios/
    R.json                  # Official public reference scenario R
    H_placeholder.json      # Representative hidden-range scenario
  traffic/
    __init__.py             # Traffic package init
    model.py                # Exact 4-slot simulator and cost model
    scenario.py             # JSON validator and random scenario sampler
    qubo.py                 # Grounded fluid queue QUBO & Ising Hamiltonian builder
    qaoa.py                 # QAOA circuit, fast statevector trainer, 4096-shot sampler
    baselines.py            # All 6 required benchmark baselines
    metrics.py              # Lift, elite enrichment, surrogate regret, robustness
    io_out.py               # Deliverable file serializers
  experiments/
    calibrate_surrogate.py  # Global QUBO hyperparameter validation
    eval_seeds.py           # Multi-seed performance table generator
    ablations.py            # Systematic ablations across depth, variants, and objectives
  report/
    report.md               # 3-page technical report with real experimental figures
  tests/
    test_scorer.py          # Verification vector and consistency tests
    test_qubo.py            # QUBO and Ising formulation tests
    test_qaoa.py            # QAOA sampling, budget, and OpenQASM 3 tests
    test_no_hardcoding.py   # Generalization and integrity tests
```
