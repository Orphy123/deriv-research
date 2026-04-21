# Phase 0.5 VERDICT — Boom 1000 Index

**Status:** KILL
**Recorded:** 2026-04-19T04:57:29.845489+00:00
**Killed at step:** 2

## Pre-registered thresholds (from PROTOCOL.md, frozen)

- `k1_min_regime_median_minutes`: 45
- `k2_min_abs_acf`: 0.15
- `k3_min_topq_signed_drift_points`: 1430
- `k4_min_positive_folds`: 4
- `k4_min_walkforward_sharpe`: 1.0
- `spread_points_roundtrip`: 1430
- `hold_window_ticks`: 600
- `spike_mask_threshold_points`: 420

## Observed measurements

### step_1_hmm

- `step`: 1
- `metric`: median_regime_duration_minutes
- `kill_threshold`: 45
- `observed_median_minutes`: 596.5
- `passed`: True
- `n_minute_bars`: 129601

### step_2_acf

- `step`: 2
- `metric`: abs(acf_lag1)
- `kill_threshold`: 0.15
- `observed_lag1`: -0.0183015
- `observed_abs_lag1`: 0.0183015
- `white_noise_ci95`: 0.0421627
- `n_hours`: 2161
- `passed`: False

## Pre-committed response to a negative result

> The primary regime-detection hypothesis for Deriv Boom/Crash 1000 is rejected at Step 2. Combined with the Phase 0 falsification of PSDC, this exhausts the pre-registered low-cost hypothesis set for this instrument class. I close out Deriv synthetics research at the Phase 0.5 boundary, preserve the parquet data store for possible future reference, and redirect research cycles to the FTMO US30/US100 bot. I will not run further tests on this hypothesis, on this data, with tweaked thresholds, or with additional exploratory variants promoted to primary. The exploratory results are informational only.

---

See PROTOCOL.md for the full pre-registration.