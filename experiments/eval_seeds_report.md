# Multi-Seed QAOA Performance Evaluation

Evaluation across 7 independent random seeds (depth $p=3$, budget $\le 300$ evaluations, 4096 shots per seed).

### Scenario: R ($C^* = 72.0, C_{rand} = 151.25$)

| Seed | $E_Q$ (Mean Cost) | Lift | Elite Enrichment (Top 13) | Best Sample Cost | Evaluations | Time (s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 107.9 | 0.5471 | 3.01x | 72.0 | 300 | 0.41s |
| 1 | 108.04 | 0.5452 | 2.84x | 72.0 | 300 | 0.38s |
| 2 | 99.34 | 0.6550 | 7.66x | 72.0 | 300 | 0.48s |
| 3 | 109.11 | 0.5318 | 2.62x | 72.0 | 300 | 0.44s |
| 4 | 108.67 | 0.5373 | 2.82x | 72.0 | 300 | 0.38s |
| 5 | 108.18 | 0.5435 | 2.82x | 72.0 | 300 | 0.45s |
| 6 | 107.47 | 0.5525 | 3.06x | 72.0 | 300 | 0.38s |

- **Mean Lift**: `0.5589`
- **Robustness (Worst-Seed Lift Clipped to [0, 1])**: `0.5318`
- **Mean Elite Enrichment**: `3.55x`

### Scenario: H_placeholder ($C^* = 98.0, C_{rand} = 141.92$)

| Seed | $E_Q$ (Mean Cost) | Lift | Elite Enrichment (Top 13) | Best Sample Cost | Evaluations | Time (s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 125.75 | 0.3682 | 3.19x | 98.0 | 300 | 0.37s |
| 1 | 125.59 | 0.3718 | 3.38x | 98.0 | 300 | 0.42s |
| 2 | 125.45 | 0.3749 | 3.38x | 98.0 | 300 | 0.38s |
| 3 | 125.32 | 0.3781 | 3.04x | 98.0 | 300 | 0.35s |
| 4 | 125.66 | 0.3701 | 3.38x | 98.0 | 300 | 0.42s |
| 5 | 125.45 | 0.3750 | 3.28x | 98.0 | 300 | 0.4s |
| 6 | 125.29 | 0.3787 | 3.21x | 98.0 | 300 | 0.38s |

- **Mean Lift**: `0.3738`
- **Robustness (Worst-Seed Lift Clipped to [0, 1])**: `0.3682`
- **Mean Elite Enrichment**: `3.27x`
