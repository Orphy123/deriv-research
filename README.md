# deriv-research

Research repo for Deriv synthetic index (Boom 1000 / Crash 1000) trading edge.
**Not** a trading bot. This exists to answer one question before we write a
strategy:

> Does Deriv's spike process on Boom/Crash 1000 exhibit statistical structure
> that a systematic strategy can exploit, or is it memoryless (as designed)?

## Current status: Phase 0 + Phase 0.5 complete — both negative

**Phase 0:** spike process is memoryless; PSDC falsified.
**Phase 0.5:** hourly drift-regime structure absent; regime-filter hypothesis
falsified at Step 2 of the pre-registered protocol on both symbols.

See [FINDINGS.md](FINDINGS.md) for the full writeup and
[PROTOCOL.md](PROTOCOL.md) for the pre-registered Phase 0.5 hypothesis and
kill criteria. Phase 0.5 per-symbol verdicts live in
`data/analysis/<symbol>/regimes/VERDICT.md`.

Deriv synthetics research is closed at the Phase 0.5 boundary. Research
cycles redirected to the FTMO US30/US100 bot (separate repo).

## Setup

```powershell
cd C:\Users\Administrator\Desktop\deriv-research
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Drop your Deriv MT5 credentials in `config/accounts.yaml` (gitignored — see
`config/accounts.example.yaml` for the template).

## Commands

```powershell
# Reproducibility: on some Windows + numpy + MKL combos, OpenBLAS can't grab
# enough thread-pool memory. These two env vars make it single-threaded.
$env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"

# Phase 0 — test broker symbol strings & IPC chunk limits
.\venv\Scripts\python.exe -m scripts.probe_history

# Bulk download ticks (chunked, resumable — existing parquets are reused)
.\venv\Scripts\python.exe -m scripts.pull_history --days 90 --chunk-days 7

# Statistical tests: memorylessness + post-spike drift (Phase 0)
.\venv\Scripts\python.exe -m scripts.analyze_spikes
.\venv\Scripts\python.exe -m scripts.analyze_spikes --threshold 10000

# Phase 0.5 — regime detection (pre-registered; reads PROTOCOL.md + config)
# Sequential kill-gated: HMM regime duration -> cleanliness ACF ->
# top-quartile drift vs spread -> walk-forward. Halts on first kill.
.\venv\Scripts\python.exe -m scripts.analyze_regimes                    # primary + Boom exploratory
.\venv\Scripts\python.exe -m scripts.analyze_regimes --skip-exploratory # primary only
```

## Directory layout

```
config/          # YAML config (accounts.yaml is gitignored)
scripts/         # Runnable probes / pullers / analyses
src/             # Shared modules: logger, mt5_client, tick_io, spike_detector, regime
data/
  ticks/<symbol>/   # Chunked parquet tick store (gitignored)
  analysis/<symbol>/ # Per-symbol plots + summary.json (gitignored)
  analysis/<symbol>/regimes/ # Phase 0.5 per-symbol regime outputs + VERDICT.md
  *.parquet, *.json # Probe outputs (gitignored)
logs/            # Daily-rotated run logs (gitignored)
notebooks/       # (empty — we went script-first for reproducibility)
PROTOCOL.md      # Pre-registered Phase 0.5 hypothesis + kill criteria
```

## Hard rules for this repo

1. **No trading code.** This is a research repo. If we ever build a live
   bot based on any edge we find here, it lives in a *separate* repo.
2. **Never merge with the `uS30/` FTMO bot.** Isolation is a feature.
3. **Every analysis ships with a plot and a significance test**, not just
   summary stats.

## What's next

Nothing on this repo. Phase 0 and Phase 0.5 together cover the spike
process and the inter-spike drift process under pre-registered tests with
frozen kill thresholds. Both returned negative. Per `PROTOCOL.md` section
5, Deriv synthetics research is closed and research effort redirected to
the FTMO US30/US100 bot (separate repo).

The parquet tick store in `data/ticks/` is preserved in case a future
researcher wants to pre-register and run a different hypothesis on the
same data — for example H4/D1 drift regimes or cross-symbol dependence.
Any such follow-up must write its own PROTOCOL.md before running any
analysis code.
