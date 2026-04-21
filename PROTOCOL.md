# Phase 0.5 Protocol — Regime Detection on Deriv Boom/Crash 1000

**Status:** PRE-REGISTERED. Committed before any analysis code runs.
**Locked on:** 2026-04-18
**Supersedes:** nothing. This document is read-only once the analysis begins.

This protocol exists because Phase 0 (`FINDINGS.md`) falsified the Post-Spike
Drift Capture hypothesis, and we are now deciding whether to spend one more
research cycle on a narrower hypothesis or to redirect to the US30/US100 bot.
Without pre-registration, the temptation to tweak thresholds after seeing
results is strong enough to invalidate the answer. This file prevents that.

## 1. Hypothesis

**Regime detection (drift-regime variant).** Deriv Boom/Crash 1000 price
processes exhibit persistent drift regimes at an hourly-to-daily timescale.
These regimes are statistically distinguishable from aggregate behavior and
identifiable in real time from price structure alone (specifically, from the
spike-masked drift residual). A subset of hours — "clean" regimes — exhibit
directional drift persistence large enough to overcome the round-trip spread.

The spike-process null from Phase 0 is accepted (spike arrival is
Poisson-memoryless within our power to detect). This hypothesis concerns the
**inter-spike drift process only**, which Phase 0 did not directly test.

If true, the edge is not a per-trade pattern but a regime filter — trade only
during detected clean regimes, stand aside otherwise.

If false, Phase 0 plus this test together exhaust the reasonable low-cost
hypothesis set for Deriv synthetics, and the rational move is to redirect
research effort to the FTMO US30/US100 bot (separate repo).

## 2. Primary test specification

**Symbol:** `Crash 1000 Index`
**Spike-detection threshold:** 10,000 points (the high-power threshold from
Phase 0, where the 30k sample rejected marginal at p=0.017 but 10k did not).
**Aggregation timeframe:** H1 (one-hour buckets).
**Holding window:** 600 ticks (matches the longest Phase 0 post-spike window
and represents roughly 15-20 minutes of wall-clock time).
**Spread hurdle:** **1,430 points round-trip.** Frozen from `FINDINGS.md`
(observed median round-trip cost). This value is NOT tunable.
**Spike-mask threshold:** single-tick |Δbid| > 420 points (≈ p99.5 of
non-spike single-tick motion from Phase 0).
**Data window:** the existing 90-day parquet store in
`data/ticks/Crash_1000_Index/`. No new pull.

## 3. Sequential tests and kill criteria

The orchestrator (`scripts/analyze_regimes.py`) runs the four steps in order.
A kill at any step terminates the investigation, writes `VERDICT.md`, and
halts further work. No step is permitted to execute unless its predecessor
passed.

**Tie-breaking:** all kill criteria use strict inequalities. A borderline
observation (e.g. median regime duration of 44.9 minutes against a 45-minute
threshold) is a kill. No rounding, no tolerance zone.

### K1 — Regime duration (Step 1)

- **Metric:** median Viterbi-decoded run-length of the spike-masked two-state
  HMM on 1-minute returns, taken over both states.
- **Kill rule:** `median_regime_duration_minutes < 45` → kill.
- **Rationale:** minimum viable setup is detection latency (~10-15 min on
  1-minute bars) plus holding window (~15-20 min). A regime shorter than 2×
  the hold window cannot be captured net of detection latency even if the
  drift is correct.

### K2 — Regime persistence (Step 2)

- **Metric:** absolute value of lag-1 autocorrelation of the hourly
  spike-masked cleanliness residual (Metric B from planning: observed H1
  signed drift on the spike-masked series minus expected drift conditional
  on spike count in that hour).
- **Kill rule:** `abs(acf_lag1) < 0.15` → kill.
- **Rationale:** regime filtering requires that "clean" hours be followed
  by clean hours more often than chance. Below 0.15 the hours are
  effectively independent and there is no persistent structure to detect.

### K3 — Effect size vs spread hurdle (Step 3)

- **Metric:** mean **signed** drift over 600 ticks following entries
  executed at the start of hours in the top quartile of the cleanliness
  metric, in the direction implied by the regime (long on Boom, short on
  Crash by construction). Reported in points.
- **Kill rule:** `topq_signed_drift_points < 1,430` → kill.
- **Rationale:** a positive mean that does not exceed the round-trip spread
  hurdle is not tradeable. Parity is not sufficient; the plan target is
  parity (1,430 pts) as the minimum, but any honest strategy will need
  noticeable headroom above that to survive slippage and variance — we
  accept the parity threshold as the pass gate because anything less is a
  deterministic loss and we refuse to live-test something guaranteed to
  lose money.

### K4 — Out-of-sample walk-forward (Step 4)

- **Metric:** 6-fold expanding-window walk-forward. For each fold, fit the
  regime detector (HMM + cleanliness quartile cutoffs) on the training
  segment, simulate entries at the start of each top-quartile hour in the
  held-out segment holding 600 ticks, net of the 1,430-pt round-trip spread.
- **Kill rule:** `(positive_folds < 4)` OR `(aggregate_sharpe_after_costs < 1.0)`
  → kill.
- **Rationale:** a real edge generalizes across time. Four of six folds
  positive is a minimal stability bar; an aggregate post-cost Sharpe of 1.0
  is the minimum to justify forward work on a new instrument class.

## 4. Primary vs exploratory separation

**Primary:** Crash 1000 Index at 10k threshold, H1 aggregation. The four
kill gates above apply to this series alone. This is the test that decides
the hypothesis.

**Exploratory (report only, never promote to primary):**

- Boom 1000 Index at 10k threshold, H1 aggregation — same metric pipeline.
- Crash 1000 Index at 10k threshold, H4 and D1 aggregation — same metric
  pipeline with longer buckets.

Exploratory results are written to the `step_*.json` artifacts for
traceability, but they **cannot rescue a primary-test kill**. Even if every
exploratory variant passes all four gates, the primary kill stands and the
investigation terminates. This rule exists specifically to prevent the
garden-of-forking-paths failure mode.

Multiple-testing context: with 4 exploratory variants on 4 metrics, the
Bonferroni-adjusted α is 0.05 / 16 ≈ 0.003 for any individual exploratory
significance claim. Report p-values raw; flag significance at this corrected
α only.

## 5. What does a negative result look like, and what will I do with it

If the primary test kills at any step K, the following paragraph takes
effect and is copied verbatim into `VERDICT.md`:

> The primary regime-detection hypothesis for Deriv Boom/Crash 1000 is
> rejected at Step K. Combined with the Phase 0 falsification of PSDC, this
> exhausts the pre-registered low-cost hypothesis set for this instrument
> class. I close out Deriv synthetics research at the Phase 0.5 boundary,
> preserve the parquet data store for possible future reference, and
> redirect research cycles to the FTMO US30/US100 bot. I will not run
> further tests on this hypothesis, on this data, with tweaked thresholds,
> or with additional exploratory variants promoted to primary. The
> exploratory results are informational only.

I have read and accepted this paragraph before the analysis runs.

## 6. What does a positive result look like

If all four gates pass:

- `VERDICT.md` records the four measurements with their thresholds.
- No live capital is deployed on the basis of this result.
- Any subsequent live bot lives in a separate repo (hard repo rule #1).
- The next step is extending the data window to 365 days and re-running the
  same protocol without re-tuning thresholds, to check stability over a
  longer horizon before any design work on a bot.

## 7. Reproducibility

- Random seeds: HMM fit uses `seed=42`; walk-forward sampling uses `seed=42`.
- Single-threaded numpy: `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`
  (matches Phase 0 reproducibility note in `README.md`).
- Code entry point: `python -m scripts.analyze_regimes` (no arguments for
  the primary run; `--symbol` and `--skip-exploratory` flags exist for
  re-inspection but do not change the primary outcome).

## 8. What this protocol forbids

- Re-running with different spike-mask thresholds after seeing Step 1.
- Changing kill thresholds after seeing any step's result.
- Promoting an exploratory series to primary after the primary fails.
- Declaring a "trend" in borderline results to justify continuation.
- Any live-capital deployment on a positive result without the 365-day
  re-validation described in section 6.
