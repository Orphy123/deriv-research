# Phase 0 Findings — Does Boom/Crash 1000 have an exploitable spike structure?

**Date:** 2026-04-18
**Data:** 90 days of ticks per symbol, pulled directly from Deriv-Demo via MT5.
- Boom 1000 Index: 7,677,891 ticks (2026-01-18 → 2026-04-18)
- Crash 1000 Index: 7,509,682 ticks (2026-01-18 → 2026-04-18)

## TL;DR

**The Post-Spike Drift Capture (PSDC) hypothesis is falsified.**

The Deriv Boom/Crash 1000 spike process is statistically Poisson-memoryless
within our power to detect, and post-spike drift windows are **indistinguishable
from random windows** at every window size tested (50, 100, 300, 600 ticks) on
both symbols, across two spike-threshold settings (10k and 30k points).

In raw point terms, post-spike drift windows are often *worse* than random
windows for drift-direction entries. Combined with a round-trip spread cost
of ~1,430 points — about the size of the observed drift over 300-600 ticks —
this strategy is **negative-EV before spike losses**.

## Spike process characteristics

### Inter-arrival time distribution (is the process memoryless?)

| Test | Boom 1000 | Crash 1000 |
|---|---|---|
| n spikes (≥30k pts) | 6,795 | 5,251 |
| n spikes (≥10k pts) | 7,363 | 6,767 |
| KS test vs exponential (30k) | **p = 0.35** (fail to reject) | p = 0.017 (marginal reject) |
| KS test vs exponential (10k) | **p = 0.26** (fail to reject) | **p = 0.07** (fail to reject at 5%) |
| Dispersion index (hourly, 10k) | 0.895 | 0.856 |
| Lag-1 autocorr of inter-arrivals | −0.006 | +0.0006 |
| Mean λ (10k) | ~0.00095 events/s | ~0.00087 events/s |
| Mean inter-arrival time (10k) | ~1,056 s (~17.6 min) | ~1,149 s (~19.2 min) |

Interpretation: the process passes an exponential fit cleanly at the 10k
threshold (where we have more statistical power). The 30k-threshold marginal
rejection on Crash (p=0.017) disappears when we broaden the sample, suggesting
it was noise rather than signal. Dispersion index slightly below 1 (0.86–0.90)
indicates very mild under-dispersion — spikes are fractionally more regular
than Poisson — but the effect size is too small to translate to a detectable
post-spike drift edge.

Hazard plot for Crash (see `data/analysis/Crash_1000_Index/hazard.png`):
essentially flat noise around λ=0.0009, consistent with constant hazard rate
= memoryless process.

### Spike direction

As expected:
- Boom 1000: 7,361 UP spikes, 2 DOWN spikes (the 2 are likely detection noise
  at the 10k threshold).
- Crash 1000: 2 UP, 6,765 DOWN.

Directionality is deterministic per symbol.

### Spike magnitude

At the 30k-point threshold:
- Maximum observed spike (Boom, 30d): 573,860 points (~$11.48 loss at 0.2 lot
  for a short-against-spike trade).
- p99 single-tick delta (normal ticks): ~420 pts.
- Spikes are ≥71× larger than p99 normal-tick motion — cleanly bimodal.

## Post-spike drift — the crown jewel test

For every detected spike, we measured price change over the next N ticks
(drift-direction adjusted so positive = continuation, negative = reversion).
Compared to a random sample of 2,000 non-overlapping windows of the same
length.

### Boom 1000 (threshold 10k, n_post=7,363, n_rand=2,000)

| Window | Post-spike mean (pts) | Random mean (pts) | Welch p | Significant? |
|---|---|---|---|---|
| 50 ticks | +178.6 | +477.8 | 0.77 | no |
| 100 ticks | **−667.0** | +640.3 | 0.36 | no |
| 300 ticks | +1,784.5 | +1,686.1 | 0.97 | no |
| 600 ticks | +1,953.4 | +2,990.0 | 0.77 | no |

### Crash 1000 (threshold 10k, n_post=6,767, n_rand=2,000)

| Window | Post-spike mean (pts) | Random mean (pts) | Welch p | Significant? |
|---|---|---|---|---|
| 50 ticks | +85.8 | +364.9 | 0.44 | no |
| 100 ticks | −112.1 | −328.5 | 0.70 | no |
| 300 ticks | −336.6 | +621.2 | 0.30 | no |
| 600 ticks | +342.1 | +977.0 | 0.63 | no |

**No window, on either symbol, at either threshold, shows a statistically
significant edge.** Visual confirmation in `post_spike_drift.png` — the two
histograms overlap almost completely with a huge common variance from
spike-embedded windows in both populations.

### The only even-suggestive pattern

Boom at w=100 shows a persistent ~1,300-point gap between post-spike mean
(−667) and random mean (+640). If real, this would suggest *mild mean
reversion* in the first ~100 ticks after an UP spike before drift resumes.
**But p = 0.36, so we cannot distinguish this from noise.** Even if it were
real:

- Required gain to break even on spread: 1,430 pts
- Observed post-spike move at w=100: 667 pts in favorable direction
- Net expected P&L: **−763 pts per trade** before any spike-catch losses

## Why the strategy fails

The dominant cost is not the spikes — it's the **spread**. At ~1,430 points
round-trip (observed median) the strategy needs price to move ~1.4× the
magnitude of the median 300-tick drift just to break even on entry-and-exit
cost, before any spike loss or slippage.

At 0.2 lots the spread cost per round trip is only $0.0286 — sounds tiny —
but the drift capture is also tiny (~$0.02-0.04 per trade gross), so
percentage-wise the spread annihilates the edge.

## Verdict

> The PSDC thesis — that post-spike windows provide favorable drift capture
> due to empirical anti-clustering in Deriv's PRNG — does not survive contact
> with 90 days of real tick data. The spike process behaves as Deriv designed
> it: memoryless Poisson. Post-spike windows are not favorable; in several
> configurations they are *less* favorable than random entries.

This is a clean statistical falsification. It saves us the several weeks of
building, tuning, and forward-testing a live bot around a hypothesis that
the data does not support.

## What could still work (lower-confidence ideas)

None of these are strong priors — they're what's left if we don't want to
abandon synthetics entirely. None should be pursued with live money without
the same level of statistical scrutiny this phase applied.

1. **Time-of-day drift patterns.** If Deriv's PRNG seeds include wall-clock
   time (plausible, not certain), specific hours might have detectably
   different drift rates. Testable in an afternoon.
2. **Pre-spike anomaly detection.** Rather than trading *after* spikes, look
   for volatility micro-structure in the 30-60s preceding a spike. This was
   the right idea in the original conversation but was framed as "avoid
   spikes" rather than "predict spikes." If spikes are genuinely memoryless,
   this also cannot work.
3. **Cross-symbol dependence.** Does a Boom spike alter the conditional
   distribution of Crash? Pearson correlation of spike timing is trivial to
   compute.
4. **Volatility-of-tick-delta as predictor.** Realized volatility in a
   sliding window may predict spike hazard if λ is non-stationary within
   each symbol. Weak prior, testable in a few hours.

If all of these also come up negative, the honest conclusion is: **synthetic
indices as designed are not tractable for positive-expectancy trading given
typical broker spreads.** The FTMO US30/US100 bot (real markets, real order
flow, structural edges) is a better use of time and capital.

## What we built (inventory)

- `scripts/probe_history.py` — verify symbol strings and test MT5
  copy_ticks_range chunk-size limits.
- `scripts/pull_history.py` — chunked bulk downloader (7-day chunks), wrote
  ~430MB of tick parquet to `data/ticks/`.
- `scripts/analyze_spikes.py` — the actual analysis (KS test, dispersion,
  hazard, post-spike drift vs random). Generates plots + JSON summary.
- `src/spike_detector.py` — pure-function spike detector used by the analysis
  (and reusable if we ever build a live bot on this).
- `src/tick_io.py` — loads and concatenates chunked parquet.
- `src/mt5_client.py` — research-only MT5 wrapper (no order methods).

The `data/ticks/` parquet store is reusable for any follow-up hypothesis
test without re-pulling.

---

# Phase 0.5 Findings — Does Boom/Crash 1000 have exploitable drift regimes?

**Date:** 2026-04-19
**Hypothesis:** Drift-regime detection. Phase 0's memorylessness result concerns
the spike arrival process. The inter-spike drift process was not directly
tested; it is possible (prior ~3-8% of producing a tradeable strategy) that
drift regimes exist at the hourly-to-daily scale and could be used as a filter
for when to trade.
**Pre-registration:** [PROTOCOL.md](PROTOCOL.md) — committed before any
analysis code ran.

## TL;DR

**The drift-regime hypothesis is falsified.** Both primary (Crash 1000) and
exploratory (Boom 1000) kill cleanly at Step 2 of the pre-registered protocol,
with the lag-1 autocorrelation of the hourly cleanliness residual sitting
inside the ±1.96/√n white-noise band. Hourly drift beyond what spikes explain
is essentially independent between consecutive hours. There is no persistent
regime structure to detect and therefore nothing to filter on.

Combined with the Phase 0 falsification of PSDC, Deriv synthetic indices
(Boom/Crash 1000) now have both the spike process and the inter-spike drift
process tested and come up empty at the pre-registered thresholds. Research
effort redirected to the FTMO US30/US100 bot per PROTOCOL section 5.

## Results

### Step 1 — HMM regime duration (both symbols PASS)

Two-state diagonal-Gaussian HMM (pure-numpy Baum-Welch + Viterbi) on
spike-masked 1-minute returns. Median Viterbi run-length, compared to the
pre-registered K1 kill threshold of 45 minutes:

| Symbol | Median regime duration | K1 threshold | Result |
|---|---|---|---|
| Crash 1000 Index | **173.5 min** | ≥ 45 min | PASS |
| Boom 1000 Index | **596.5 min** | ≥ 45 min | PASS |

The HMM identifies persistent states comfortably — but, crucially, these are
*volatility* regimes (high-variance vs low-variance 1-minute return periods),
not drift regimes. Whether those volatility states translate to tradeable
hourly drift structure is what Step 2 tests.

### Step 2 — Hourly cleanliness residual autocorrelation (both symbols KILL)

Per-hour residual of observed H1 drift regressed on H1 spike count
(`drift = α + β · n_spikes + residual`). The residual captures the
*unexplained* drift component not accounted for by spike occurrence. If drift
regimes exist, this residual should be autocorrelated hour-to-hour.

| Symbol | Lag-1 ACF | |ACF| | K2 threshold | 95% white-noise band | Result |
|---|---|---|---|---|---|
| Crash 1000 Index | **−0.041** | 0.041 | ≥ 0.15 | ±0.042 | **KILL** |
| Boom 1000 Index | **−0.018** | 0.018 | ≥ 0.15 | ±0.042 | **KILL** |

Both observed lag-1 ACFs sit inside or on the edge of the ±1.96/√n white-noise
band for n=2,161 hours. The cleanliness residual is statistically
indistinguishable from white noise on both symbols. The K2 kill margin is
roughly 4× for Crash and 8× for Boom — not borderline.

The linear fit shows 72-74% of hourly drift variance is explained by spike
count alone (Crash R² = 0.743, Boom R² = 0.726). The residual 26-28% carries
no persistent structure.

Steps 3 and 4 were not executed, per the pre-registered sequential kill
protocol.

## What this rules out

- **Hourly drift regimes on Crash 1000 and Boom 1000** at an effect size
  large enough to filter trades on. A |lag-1 ACF| < 0.042 bounds the
  autocorrelation at a magnitude where detection latency would consume any
  detectable persistence.
- **Simple non-stationarity in drift as a tradeable filter.** Even if slow
  regimes exist at timescales beyond H1 (daily, weekly), they are not picked
  up by hourly conditioning on spike count.

## What this does NOT rule out

- Regimes at timescales we did not test (H4, D1 as conditioning timeframes
  could be run as further exploratory variants; the protocol forbids
  promoting those to primary, but nothing prevents a future researcher from
  running them with pre-registered kill thresholds of their own choosing).
- Non-linear drift-spike relationships (we only tested linear regression).
- Interaction effects between the two symbols (cross-symbol tests would be
  a separate investigation with its own pre-registration).

These are strictly weaker priors than the one we just tested, and each would
need its own PROTOCOL before being run.

## Verdict

> Both Phase 0 (spike process) and Phase 0.5 (drift process) pre-registered
> tests on Deriv Boom/Crash 1000 return negative. The pre-committed response
> from PROTOCOL.md section 5 takes effect:
>
> *"I close out Deriv synthetics research at the Phase 0.5 boundary,
> preserve the parquet data store for possible future reference, and
> redirect research cycles to the FTMO US30/US100 bot. I will not run
> further tests on this hypothesis, on this data, with tweaked thresholds,
> or with additional exploratory variants promoted to primary."*

Artifacts:

- [data/analysis/Crash_1000_Index/regimes/VERDICT.md](data/analysis/Crash_1000_Index/regimes/VERDICT.md)
- [data/analysis/Boom_1000_Index/regimes/VERDICT.md](data/analysis/Boom_1000_Index/regimes/VERDICT.md)
- `step_1_hmm.json`, `step_2_acf.json`, `hmm_states.png`, `cleanliness_acf.png` per symbol.
- `data/analysis/regimes_combined_summary.json` — combined primary + exploratory output.

## What was built in Phase 0.5

- `PROTOCOL.md` — pre-registered hypothesis, primary/exploratory split, kill
  thresholds K1-K4, and the pre-committed response-to-negative-result
  paragraph.
- `src/regime.py` — spike-masking, 1-minute bar construction, cleanliness
  metric (Metric B residual), self-contained pure-numpy 2-state Gaussian HMM
  with Baum-Welch EM and Viterbi decoding (written inline to avoid depending
  on `hmmlearn`, which has no Windows/Python 3.14 wheel), and
  expanding-window walk-forward helper.
- `scripts/analyze_regimes.py` — sequential kill-gated orchestrator that
  writes `VERDICT.md` on both kill and pass paths and halts on the first
  kill without running subsequent steps.
- `config/config.yaml` — new `regime_detection:` section with all frozen
  thresholds referenced by the orchestrator.

The existing 90-day parquet store was reused directly — no new data pull.
