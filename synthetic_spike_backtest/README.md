# Synthetic Spike Backtest

Standalone backtesting project for a Deriv synthetic strategy based on:

- opposite-direction trigger events,
- quiet watch period,
- timed entry,
- immediate adverse tick exits,
- strict max-hold timeout,
- explicit feasibility gates.

## Quick Start

```powershell
cd C:\Users\Administrator\Desktop\deriv-research\synthetic_spike_backtest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m synthetic_spike.cli run --config config/defaults.yaml
```

## Sweep + Feasibility

```powershell
python -m synthetic_spike.cli sweep --config config/defaults.yaml
```

Outputs are written under `out/` by default:

- `trades_*.csv`: full trade-level records.
- `summary_*.json`: scenario metrics.
- `sweep_results.csv`: parameter-grid results.
- `feasibility_report.md`: go/no-go recommendation.

## Versioned Rule Source

V1 behavior is frozen in `SPEC.md`.
