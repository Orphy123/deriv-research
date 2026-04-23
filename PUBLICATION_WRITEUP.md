# Statistical Falsification of Trading Edges on Deriv Synthetic Indices

**A pre-registered quantitative case study**  
Oheneba Berko  
April 2026

## Abstract

This project tests whether Deriv's `Boom 1000 Index` and `Crash 1000 Index`
contain exploitable statistical structure for a retail systematic strategy.
Using 90 days of tick data (15.19 million ticks total), the research applies
pre-registered hypotheses, frozen kill thresholds, and sequential
cost-minimizing test gates. Two hypotheses were evaluated: (1) post-spike
drift capture driven by non-memoryless spike arrivals (Phase 0), and
(2) persistent inter-spike drift regimes detectable at hourly resolution
(Phase 0.5). Both hypotheses fail at pre-committed decision boundaries.
The Phase 0 spike-arrival process is consistent with memoryless behavior at the
high-power threshold, and no post-spike drift window significantly outperforms
random matched windows. In Phase 0.5, both primary and exploratory runs pass
regime-duration screening but fail the persistence gate: lag-1 autocorrelation
of the hourly cleanliness residual remains inside white-noise confidence bands.
The practical conclusion is a null: these instruments do not show tradeable
edge at tested effect sizes after spread-aware constraints.

## 1) Research Question

Can a retail trader extract positive expectancy on Deriv synthetic indices by
exploiting either:

1. spike-timing structure (post-spike drift capture), or
2. persistent inter-spike drift regimes (hour-level filter)?

The design intentionally tests structural prerequisites for whole strategy
families rather than optimizing one discretionary setup.

## 2) Data, Scope, and Reproducibility

- Source: Deriv MT5 historical ticks, chunked in 7-day parquet files.
- Window: `2026-01-18` to `2026-04-18` (90 days).
- Sample sizes:
  - `Boom 1000 Index`: 7,677,891 ticks
  - `Crash 1000 Index`: 7,509,682 ticks
- Total: 15,187,573 ticks.
- Repository artifacts:
  - protocol: `PROTOCOL.md`
  - findings: `FINDINGS.md`
  - phase summaries: `data/analysis/*/summary.json`
  - regime verdicts: `data/analysis/*/regimes/VERDICT.md`

All tests are script-driven (no notebook dependency), and thresholds for
Phase 0.5 are frozen in `config/config.yaml` under `regime_detection`.

## 3) Methodological Framework

### 3.1 Pre-registration and kill gates

The study uses explicit pre-registration and sequential kill criteria:
if a gate fails, downstream gates do not execute. This design reduces
researcher degrees of freedom and compute waste on null paths.

### 3.2 Phase 0 hypothesis (PSDC)

Hypothesis: if spikes anti-cluster, post-spike windows should carry favorable
drift and reduced immediate spike hazard.

Core tests:
- KS test of inter-arrival times vs exponential law
- hourly dispersion index of spike counts
- lag-1 autocorrelation of inter-arrivals
- empirical hazard profile vs constant-hazard expectation
- Welch tests: post-spike drift windows vs random matched windows

Window sizes: 50, 100, 300, and 600 ticks.

### 3.3 Phase 0.5 hypothesis (drift-regime detection)

Hypothesis: after spike masking and spike-count conditioning, hourly drift
residuals retain persistent structure that can support a spread-aware regime
filter.

Pre-registered steps:
1. K1: HMM median regime duration (minimum 45 min)
2. K2: lag-1 ACF magnitude of hourly cleanliness residual (minimum 0.15)
3. K3: top-quartile signed drift must exceed 1,430-point spread hurdle
4. K4: walk-forward post-cost stability (>= 4/6 positive folds and Sharpe > 1)

The HMM implementation is pure NumPy (scaled Baum-Welch + Viterbi), avoiding
platform-fragile compiled dependencies.

## 4) Results

### 4.1 Phase 0: spike process and post-spike drift

At the 10k spike threshold (high-power sample):

- **Boom 1000**
  - KS p-value: 0.258
  - dispersion index: 0.895
  - lag-1 inter-arrival ACF: -0.0056
  - lambda: 0.000947 events/s (mean inter-arrival ~1056 s)
- **Crash 1000**
  - KS p-value: 0.0729
  - dispersion index: 0.856
  - lag-1 inter-arrival ACF: +0.00065
  - lambda: 0.000870 events/s (mean inter-arrival ~1149 s)

Interpretation: no robust departure from memoryless behavior at this threshold.

For post-spike drift windows (50/100/300/600 ticks), no Welch test achieves
5% significance on either symbol. Representative example:

- Boom, 100 ticks: post-spike mean = -667 pts vs random mean = +640 pts,
  Welch p = 0.358 (not significant).

Spread economics further tighten feasibility: the pre-registered round-trip
hurdle of 1,430 points is larger than or comparable to observed gross drift
capture in tested windows.

### 4.2 Phase 0.5: regime detection

#### Step 1 (K1) - PASS

- Crash median regime duration: 173.5 min
- Boom median regime duration: 596.5 min
- K1 threshold: >= 45 min

These states are detectable in variance terms, but persistence in directional
hourly residual drift is what determines tradeability.

#### Step 2 (K2) - KILL

- Crash lag-1 ACF: -0.0409 (abs 0.0409)
- Boom lag-1 ACF: -0.0183 (abs 0.0183)
- K2 threshold: abs(ACF) >= 0.15
- White-noise 95% band: +/-0.0422 (n = 2,161 hours)

Both instruments fail K2 decisively; residual drift is statistically
indistinguishable from white noise at hour-to-hour lag.

Per protocol, Steps 3 and 4 do not execute after a K2 kill.

## 5) Conclusion

Across both phases, the tested edge families are falsified at pre-registered
decision gates. The evidence supports a null characterization at tested effect
sizes:

- spike arrivals are memoryless within available detection power,
- post-spike drift windows are not statistically favorable vs random windows,
- hourly residual drift persistence is too weak for regime filtering.

For practitioners, this means strategies whose expectancy depends on
post-spike asymmetry, spike anti-clustering, or hourly drift-regime persistence
can be rejected on current evidence without individual variant optimization.

## 6) Contribution and Research Discipline

The strongest contribution is methodological, not tactical:

- explicit pre-registration,
- frozen kill thresholds,
- exploratory/primary separation,
- pre-committed negative-result response.

This framework prevents hindsight threshold tuning and preserves inferential
integrity in small-team quantitative research.

## 7) Limitations and Future Work Boundaries

- Scope is limited to the tested window, symbols, and effect sizes.
- Null results do not imply all conceivable hypotheses are false.
- Any new hypothesis should begin with a fresh protocol, not threshold reuse or
  retrofitting on failed gates.

Per `PROTOCOL.md`, this specific Phase 0 / Phase 0.5 research line is closed.

## References to Repository Artifacts

- `PROTOCOL.md`
- `FINDINGS.md`
- `data/analysis/combined_summary.json`
- `data/analysis/regimes_combined_summary.json`
- `data/analysis/Crash_1000_Index/regimes/VERDICT.md`
- `data/analysis/Boom_1000_Index/regimes/VERDICT.md`
