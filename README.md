# Deriv Synthetic Indices Research

Pre-registered quantitative research on `Boom 1000 Index` and
`Crash 1000 Index` to test whether their price process contains a tradeable
statistical edge.

This repository is a **research artifact**, not a trading bot.

## Research question

Do Deriv synthetic indices exhibit exploitable structure for systematic trading,
or do they behave as approximately memoryless processes once costs are included?

## Current verdict (archived)

- **Phase 0:** Post-Spike Drift Capture (PSDC) falsified.
- **Phase 0.5:** Drift-regime filter hypothesis killed at Step 2 (ACF gate)
  on both primary and exploratory runs.
- **Status:** this research line is closed at the pre-registered boundary.

## Document map

- `PROTOCOL.md` - pre-registered Phase 0.5 hypothesis and kill criteria.
- `FINDINGS.md` - full technical findings and interpretation.
- `PUBLICATION_WRITEUP.md` - publication-style manuscript draft.
- `data/analysis/*/summary.json` - Phase 0 machine-readable outputs.
- `data/analysis/*/regimes/VERDICT.md` - Phase 0.5 verdict artifacts.

## Quick start

```powershell
cd C:\Users\Administrator\Desktop\deriv-research
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Add MT5 credentials to `config/accounts.yaml` (template:
`config/accounts.example.yaml`).

## Reproduce results

```powershell
# Optional stability on some Windows OpenBLAS/MKL setups
$env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"

# 1) Confirm broker symbols and history limits
.\venv\Scripts\python.exe -m scripts.probe_history

# 2) Pull or refresh chunked tick store (90 days, resumable)
.\venv\Scripts\python.exe -m scripts.pull_history --days 90 --chunk-days 7

# 3) Phase 0 analysis: memorylessness + post-spike drift tests
.\venv\Scripts\python.exe -m scripts.analyze_spikes --threshold 10000

# 4) Phase 0.5 analysis: pre-registered sequential kill-gated regime test
.\venv\Scripts\python.exe -m scripts.analyze_regimes
```

## Artifacts and outputs

- Tick parquet store (local, gitignored): `data/ticks/<symbol>/`
- Phase 0 summaries (tracked JSON): `data/analysis/<symbol>/summary.json`
- Phase 0.5 step artifacts: `data/analysis/<symbol>/regimes/step_*.json`
- Phase 0.5 verdict files: `data/analysis/<symbol>/regimes/VERDICT.md`
- Combined summaries:
  - `data/analysis/combined_summary.json`
  - `data/analysis/regimes_combined_summary.json`

Note: heavy outputs (`.parquet`, `.csv`, `.png`) are local-only by default.

## Repository structure

```text
config/                        # YAML config (credentials file is gitignored)
scripts/                       # executable pull/probe/analysis entry points
src/                           # shared research modules
data/                          # local tick store + tracked analysis summaries
synthetic_spike_backtest/      # separate strategy sandbox (latest: inconclusive)
PROTOCOL.md                    # pre-registration
FINDINGS.md                    # technical report
PUBLICATION_WRITEUP.md         # manuscript-style version
```

## Scope and governance

- No live trading code in this repository.
- No threshold retuning after pre-registered kills.
- Exploratory results do not override primary verdicts.
- Any future hypothesis on this data requires a new protocol before execution.
