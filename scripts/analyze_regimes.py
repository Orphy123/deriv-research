"""
analyze_regimes.py — Phase 0.5 regime-detection orchestrator.

Sequential kill-gated test of the drift-regime hypothesis described in
PROTOCOL.md. A kill at any step terminates the investigation, writes
VERDICT.md, and does NOT run subsequent steps.

The pre-registered kill thresholds live in config/config.yaml under
`regime_detection.kill` and are frozen by PROTOCOL.md. Do not tune.

Steps (see PROTOCOL.md for rationale):
    1. HMM regime duration on spike-masked 1-min returns.
    2. Lag-1 autocorrelation of hourly cleanliness residual.
    3. Top-quartile signed forward-drift vs spread hurdle.
    4. 6-fold expanding walk-forward with post-cost Sharpe.

Outputs (per primary symbol):
    data/analysis/<symbol>/regimes/step_1_hmm.json
    data/analysis/<symbol>/regimes/step_2_acf.json
    data/analysis/<symbol>/regimes/step_3_effect_size.json
    data/analysis/<symbol>/regimes/step_4_walkforward.json
    data/analysis/<symbol>/regimes/hmm_states.png
    data/analysis/<symbol>/regimes/cleanliness_acf.png
    data/analysis/<symbol>/regimes/effect_size.png
    data/analysis/<symbol>/regimes/walkforward.png
    data/analysis/<symbol>/regimes/VERDICT.md

Run:
    python -m scripts.analyze_regimes                         # primary + exploratory
    python -m scripts.analyze_regimes --skip-exploratory      # primary only
    python -m scripts.analyze_regimes --symbol "Boom 1000 Index"   # override
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config_loader import load_config
from src.logger import Logger
from src.regime import (
    cleanliness_metric_b,
    expanding_walkforward_folds,
    fit_two_state_hmm,
    forward_tick_drift,
    hourly_raw_drift,
    hourly_spike_counts,
    mask_spike_ticks,
    signed_drift_direction_for_symbol,
    to_minute_bars,
)
from src.spike_detector import detect_spikes
from src.tick_io import load_manifest, load_symbol_ticks, safe_symbol_dir


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def _savefig(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _dump_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def _tick_entry_index_for_hours(
    ticks: pd.DataFrame, hour_starts: pd.DatetimeIndex
) -> np.ndarray:
    """First tick index at or after each hour-start timestamp (or -1 if none)."""
    if ticks.empty or len(hour_starts) == 0:
        return np.zeros(len(hour_starts), dtype=np.int64)
    t_ns = ticks["time_utc"].astype("int64").to_numpy()
    h_ns = hour_starts.astype("int64").to_numpy()
    idx = np.searchsorted(t_ns, h_ns, side="left")
    idx = np.where(idx >= len(t_ns), -1, idx)
    return idx


def _shifted_topq_mask(values: pd.Series, direction_sign: int) -> pd.Series:
    """Using PRIOR-HOUR cleanliness to classify CURRENT hour (no look-ahead).

    The "favorable" residuals are those in the trade direction: for Boom (+1)
    high-positive residuals are clean; for Crash (-1) the most-negative
    residuals are clean. We multiply by direction_sign so that higher values
    always mean more favorable, then take the top quartile of the shifted
    series.
    """
    favorable = values * direction_sign
    prior = favorable.shift(1)
    q75 = prior.quantile(0.75)
    return (prior >= q75) & prior.notna(), q75


# ---------------------------------------------------------------------------
# VERDICT writer
# ---------------------------------------------------------------------------

FAIL_PARAGRAPH = (
    "The primary regime-detection hypothesis for Deriv Boom/Crash 1000 is "
    "rejected at Step {step}. Combined with the Phase 0 falsification of "
    "PSDC, this exhausts the pre-registered low-cost hypothesis set for "
    "this instrument class. I close out Deriv synthetics research at the "
    "Phase 0.5 boundary, preserve the parquet data store for possible "
    "future reference, and redirect research cycles to the FTMO US30/US100 "
    "bot. I will not run further tests on this hypothesis, on this data, "
    "with tweaked thresholds, or with additional exploratory variants "
    "promoted to primary. The exploratory results are informational only."
)


def write_verdict(
    out_dir: Path,
    symbol: str,
    status: str,
    killed_at_step: int | None,
    measurements: dict,
    thresholds: dict,
) -> None:
    """Write VERDICT.md summarizing the outcome of the primary run."""
    lines: list[str] = []
    lines.append(f"# Phase 0.5 VERDICT — {symbol}")
    lines.append("")
    lines.append(f"**Status:** {status}")
    lines.append(f"**Recorded:** {datetime.now(timezone.utc).isoformat()}")
    if killed_at_step is not None:
        lines.append(f"**Killed at step:** {killed_at_step}")
    lines.append("")
    lines.append("## Pre-registered thresholds (from PROTOCOL.md, frozen)")
    lines.append("")
    for k, v in thresholds.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    lines.append("## Observed measurements")
    lines.append("")
    for step_key, step_meas in measurements.items():
        lines.append(f"### {step_key}")
        lines.append("")
        for k, v in step_meas.items():
            if isinstance(v, float):
                lines.append(f"- `{k}`: {v:.6g}")
            else:
                lines.append(f"- `{k}`: {v}")
        lines.append("")
    if status == "KILL":
        lines.append("## Pre-committed response to a negative result")
        lines.append("")
        lines.append("> " + FAIL_PARAGRAPH.format(step=killed_at_step))
        lines.append("")
    else:
        lines.append("## Pre-committed response to a positive result")
        lines.append("")
        lines.append(
            "> All four gates passed. No live capital is deployed. "
            "Next step per PROTOCOL.md section 6: extend the data window "
            "to 365 days and re-run the same protocol without re-tuning "
            "thresholds, to check stability over a longer horizon before "
            "any design work on a bot."
        )
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("See PROTOCOL.md for the full pre-registration.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "VERDICT.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# STEP 1 — HMM regime duration
# ---------------------------------------------------------------------------

def run_step_1(
    minute_bars: pd.DataFrame,
    out_dir: Path,
    k1_min_minutes: float,
    log: Logger,
) -> tuple[bool, dict, pd.Series]:
    returns = minute_bars["return"].to_numpy()
    try:
        model, states, run_stats = fit_two_state_hmm(returns, seed=42)
    except Exception as e:
        log.error(f"Step 1 HMM fit failed: {e}")
        result = {"error": str(e)}
        _dump_json(result, out_dir / "step_1_hmm.json")
        return False, result, pd.Series(dtype=int)

    state_seq = pd.Series(states, index=minute_bars.index, name="hmm_state")

    median_min = run_stats["overall_median_minutes"]
    passed = bool(median_min >= k1_min_minutes)

    result = {
        "step": 1,
        "metric": "median_regime_duration_minutes",
        "kill_threshold": float(k1_min_minutes),
        "observed_median_minutes": float(median_min),
        "passed": passed,
        "run_stats": run_stats,
        "n_minute_bars": int(len(minute_bars)),
    }
    _dump_json(result, out_dir / "step_1_hmm.json")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    sample_n = min(20160, len(state_seq))  # ~14 days of minutes
    sample = state_seq.iloc[:sample_n]
    ax = axes[0]
    ax.plot(sample.index, sample.values, drawstyle="steps-post", linewidth=0.7)
    ax.set_yticks([0, 1])
    ax.set_ylabel("HMM state")
    ax.set_title(
        f"Two-state HMM Viterbi sequence (first ~14 days)\n"
        f"state means={run_stats['state_means']}"
    )
    ax = axes[1]
    for s, color in [(0, "C0"), (1, "C1")]:
        runs = run_stats[f"state_{s}"]
        if runs["n_runs"] == 0:
            continue
        from itertools import groupby
        lengths = [
            sum(1 for _ in g)
            for k, g in groupby(state_seq.values.tolist())
            if k == s
        ]
        bins = np.linspace(0, max(60, np.quantile(lengths, 0.99)), 50)
        ax.hist(lengths, bins=bins, alpha=0.55, color=color,
                label=f"state {s} (n={len(lengths)}, median={runs['median_minutes']:.1f} min)")
    ax.axvline(k1_min_minutes, color="red", linestyle="--",
               label=f"K1 kill threshold = {k1_min_minutes} min")
    ax.set_xlabel("Run length (minutes)")
    ax.set_ylabel("Run count")
    ax.set_title(
        f"Regime duration distribution | overall median={median_min:.1f} min  "
        f"=> {'PASS' if passed else 'KILL'}"
    )
    ax.legend()
    fig.tight_layout()
    _savefig(fig, out_dir / "hmm_states.png")

    log.info(
        f"[Step 1] median regime duration = {median_min:.1f} min  "
        f"(threshold {k1_min_minutes}) => {'PASS' if passed else 'KILL'}"
    )
    return passed, result, state_seq


# ---------------------------------------------------------------------------
# STEP 2 — Cleanliness residual lag-1 ACF
# ---------------------------------------------------------------------------

def run_step_2(
    cleanliness: pd.Series,
    out_dir: Path,
    k2_min_abs_acf: float,
    log: Logger,
    max_lag: int = 24,
) -> tuple[bool, dict]:
    c = cleanliness.dropna()
    if len(c) < 100:
        result = {"error": f"too few hours for ACF ({len(c)})",
                  "step": 2, "passed": False}
        _dump_json(result, out_dir / "step_2_acf.json")
        return False, result

    x = c.to_numpy()
    n = len(x)
    mean_x = x.mean()
    var_x = x.var(ddof=0)
    acf = np.zeros(max_lag + 1)
    acf[0] = 1.0
    for lag in range(1, max_lag + 1):
        if lag >= n:
            break
        cov = float(((x[: n - lag] - mean_x) * (x[lag:] - mean_x)).mean())
        acf[lag] = cov / var_x if var_x > 0 else 0.0
    lag1 = float(acf[1])
    abs_lag1 = abs(lag1)
    passed = bool(abs_lag1 >= k2_min_abs_acf)

    ci95 = 1.96 / np.sqrt(n)

    result = {
        "step": 2,
        "metric": "abs(acf_lag1)",
        "kill_threshold": float(k2_min_abs_acf),
        "observed_lag1": lag1,
        "observed_abs_lag1": abs_lag1,
        "acf_values": {f"lag_{i}": float(acf[i]) for i in range(max_lag + 1)},
        "white_noise_ci95": float(ci95),
        "n_hours": int(n),
        "passed": passed,
    }
    _dump_json(result, out_dir / "step_2_acf.json")

    fig, ax = plt.subplots(figsize=(10, 5))
    lags = np.arange(max_lag + 1)
    ax.stem(lags, acf, basefmt=" ")
    ax.axhline(0, color="k", linewidth=0.5)
    ax.axhline(+ci95, color="gray", linestyle=":", label=f"±1.96/√n = ±{ci95:.3f}")
    ax.axhline(-ci95, color="gray", linestyle=":")
    ax.axhline(+k2_min_abs_acf, color="red", linestyle="--",
               label=f"K2 kill band ±{k2_min_abs_acf}")
    ax.axhline(-k2_min_abs_acf, color="red", linestyle="--")
    ax.set_xlabel("Lag (hours)")
    ax.set_ylabel("Autocorrelation")
    ax.set_title(
        f"Hourly cleanliness residual ACF | lag-1 = {lag1:.4f}  "
        f"=> {'PASS' if passed else 'KILL'}"
    )
    ax.legend()
    fig.tight_layout()
    _savefig(fig, out_dir / "cleanliness_acf.png")

    log.info(
        f"[Step 2] lag-1 ACF = {lag1:.4f} (|{abs_lag1:.4f}| vs threshold "
        f"{k2_min_abs_acf}) => {'PASS' if passed else 'KILL'}"
    )
    return passed, result


# ---------------------------------------------------------------------------
# STEP 3 — Top-quartile signed forward drift vs spread
# ---------------------------------------------------------------------------

def run_step_3(
    ticks: pd.DataFrame,
    cleanliness: pd.Series,
    symbol: str,
    point: float,
    hold_ticks: int,
    spread_hurdle_pts: float,
    out_dir: Path,
    k3_min_signed_drift_pts: float,
    log: Logger,
) -> tuple[bool, dict]:
    direction_sign = signed_drift_direction_for_symbol(symbol)
    topq_mask, q75_favorable = _shifted_topq_mask(cleanliness, direction_sign)

    topq_hours = cleanliness.index[topq_mask]
    rest_hours = cleanliness.index[~topq_mask & cleanliness.shift(1).notna()]

    if len(topq_hours) < 50:
        result = {"error": f"too few top-quartile hours ({len(topq_hours)})",
                  "step": 3, "passed": False}
        _dump_json(result, out_dir / "step_3_effect_size.json")
        return False, result

    prices = ticks["bid"].astype(float).to_numpy()

    topq_entry_idx = _tick_entry_index_for_hours(ticks, topq_hours)
    rest_entry_idx = _tick_entry_index_for_hours(ticks, rest_hours)
    topq_entry_idx = topq_entry_idx[topq_entry_idx >= 0]
    rest_entry_idx = rest_entry_idx[rest_entry_idx >= 0]

    topq_raw = forward_tick_drift(prices, topq_entry_idx, hold_ticks)
    rest_raw = forward_tick_drift(prices, rest_entry_idx, hold_ticks)

    topq_signed = topq_raw * direction_sign
    rest_signed = rest_raw * direction_sign
    topq_signed_pts = topq_signed / point if point > 0 else topq_signed
    rest_signed_pts = rest_signed / point if point > 0 else rest_signed

    topq_mean_pts = float(topq_signed_pts.mean()) if len(topq_signed_pts) else float("nan")
    rest_mean_pts = float(rest_signed_pts.mean()) if len(rest_signed_pts) else float("nan")
    topq_std_pts = float(topq_signed_pts.std(ddof=1)) if len(topq_signed_pts) > 1 else float("nan")

    from scipy import stats as spst
    if len(topq_signed_pts) >= 30 and len(rest_signed_pts) >= 30:
        t_stat, t_p = spst.ttest_ind(topq_signed_pts, rest_signed_pts, equal_var=False)
    else:
        t_stat, t_p = float("nan"), float("nan")

    passed = bool(topq_mean_pts >= k3_min_signed_drift_pts)

    result = {
        "step": 3,
        "metric": "topq_mean_signed_drift_points",
        "kill_threshold": float(k3_min_signed_drift_pts),
        "spread_hurdle_points": float(spread_hurdle_pts),
        "direction_sign": int(direction_sign),
        "hold_window_ticks": int(hold_ticks),
        "n_topq_hours_classified": int(len(topq_hours)),
        "n_topq_trades_simulated": int(len(topq_signed_pts)),
        "n_rest_trades_simulated": int(len(rest_signed_pts)),
        "topq_mean_pts": topq_mean_pts,
        "topq_std_pts": topq_std_pts,
        "rest_mean_pts": rest_mean_pts,
        "welch_t": float(t_stat),
        "welch_p": float(t_p),
        "q75_favorable_cleanliness": float(q75_favorable),
        "passed": passed,
    }
    _dump_json(result, out_dir / "step_3_effect_size.json")

    fig, ax = plt.subplots(figsize=(10, 5))
    if len(topq_signed_pts) and len(rest_signed_pts):
        lo = min(topq_signed_pts.min(), rest_signed_pts.min())
        hi = max(topq_signed_pts.max(), rest_signed_pts.max())
        bins = np.linspace(lo, hi, 80)
        ax.hist(rest_signed_pts, bins=bins, alpha=0.5, density=True,
                label=f"rest n={len(rest_signed_pts)} mean={rest_mean_pts:.0f}pts")
        ax.hist(topq_signed_pts, bins=bins, alpha=0.5, density=True,
                label=f"top-Q n={len(topq_signed_pts)} mean={topq_mean_pts:.0f}pts")
    ax.axvline(0, color="k", linewidth=0.6)
    ax.axvline(k3_min_signed_drift_pts, color="red", linestyle="--",
               label=f"K3 threshold = {k3_min_signed_drift_pts} pts (spread hurdle)")
    ax.axvline(topq_mean_pts, color="C1", linestyle=":")
    ax.set_xlabel(f"Signed forward drift over {hold_ticks} ticks (points)")
    ax.set_ylabel("Density")
    ax.set_title(
        f"Step 3: top-Q mean = {topq_mean_pts:.0f}pts vs threshold "
        f"{k3_min_signed_drift_pts}pts => {'PASS' if passed else 'KILL'}"
    )
    ax.legend()
    fig.tight_layout()
    _savefig(fig, out_dir / "effect_size.png")

    log.info(
        f"[Step 3] top-Q mean signed drift = {topq_mean_pts:.1f} pts "
        f"(threshold {k3_min_signed_drift_pts}) => {'PASS' if passed else 'KILL'}"
    )
    return passed, result


# ---------------------------------------------------------------------------
# STEP 4 — Walk-forward
# ---------------------------------------------------------------------------

def run_step_4(
    ticks: pd.DataFrame,
    hourly_drift: pd.Series,
    hourly_counts: pd.Series,
    symbol: str,
    point: float,
    hold_ticks: int,
    spread_hurdle_pts: float,
    n_folds: int,
    k4_min_positive_folds: int,
    k4_min_sharpe: float,
    out_dir: Path,
    log: Logger,
) -> tuple[bool, dict]:
    direction_sign = signed_drift_direction_for_symbol(symbol)

    joint = pd.concat(
        [hourly_drift.rename("drift"), hourly_counts.rename("n_sp")],
        axis=1,
    ).dropna()
    n_hours = len(joint)
    folds = expanding_walkforward_folds(n_hours, k=n_folds)
    if not folds:
        result = {"error": f"cannot build {n_folds} folds from {n_hours} hours",
                  "step": 4, "passed": False}
        _dump_json(result, out_dir / "step_4_walkforward.json")
        return False, result

    prices = ticks["bid"].astype(float).to_numpy()
    hour_index = joint.index

    fold_results: list[dict] = []
    all_test_pnl_pts: list[float] = []

    for fi, (train_sl, test_sl) in enumerate(folds):
        train = joint.iloc[train_sl]
        test = joint.iloc[test_sl]

        x = train["n_sp"].to_numpy(dtype=float)
        y = train["drift"].to_numpy(dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = float(((x - x_mean) ** 2).sum())
        slope = float(((x - x_mean) * (y - y_mean)).sum() / denom) if denom > 0 else 0.0
        intercept = float(y_mean - slope * x_mean)

        train_resid = y - (intercept + slope * x)
        favorable_train = train_resid * direction_sign
        q75_train = float(np.quantile(favorable_train, 0.75))

        test_resid = test["drift"].to_numpy() - (intercept + slope * test["n_sp"].to_numpy())
        favorable_test = test_resid * direction_sign
        prior_favorable_test = np.roll(favorable_test, 1)
        prior_favorable_test[0] = np.nan

        topq_test_mask = (prior_favorable_test >= q75_train) & np.isfinite(prior_favorable_test)
        topq_hours_test = hour_index[test_sl.start + np.where(topq_test_mask)[0]]

        entry_idx = _tick_entry_index_for_hours(ticks, topq_hours_test)
        entry_idx = entry_idx[entry_idx >= 0]
        raw_drift = forward_tick_drift(prices, entry_idx, hold_ticks)
        signed_drift = raw_drift * direction_sign
        signed_drift_pts = signed_drift / point if point > 0 else signed_drift
        pnl_pts = signed_drift_pts - spread_hurdle_pts

        if len(pnl_pts) > 1:
            mean_pnl = float(pnl_pts.mean())
            std_pnl = float(pnl_pts.std(ddof=1))
            sharpe = mean_pnl / std_pnl * np.sqrt(len(pnl_pts)) if std_pnl > 0 else float("nan")
        else:
            mean_pnl = float("nan")
            std_pnl = float("nan")
            sharpe = float("nan")

        fold_results.append({
            "fold": fi,
            "n_train_hours": int(len(train)),
            "n_test_hours": int(len(test)),
            "n_test_trades": int(len(pnl_pts)),
            "q75_train": q75_train,
            "train_slope": slope,
            "train_intercept": intercept,
            "mean_gross_pts": float(signed_drift_pts.mean()) if len(signed_drift_pts) else float("nan"),
            "mean_net_pts": mean_pnl,
            "std_net_pts": std_pnl,
            "sharpe": float(sharpe),
            "positive": bool(np.isfinite(mean_pnl) and mean_pnl > 0),
        })
        all_test_pnl_pts.extend(pnl_pts.tolist())

    positive_folds = int(sum(1 for f in fold_results if f["positive"]))

    all_pnl = np.asarray(all_test_pnl_pts, dtype=float)
    if len(all_pnl) > 1 and np.nanstd(all_pnl, ddof=1) > 0:
        agg_sharpe = float(np.nanmean(all_pnl) / np.nanstd(all_pnl, ddof=1) * np.sqrt(len(all_pnl)))
    else:
        agg_sharpe = float("nan")

    passed = bool(
        positive_folds >= k4_min_positive_folds
        and np.isfinite(agg_sharpe)
        and agg_sharpe >= k4_min_sharpe
    )

    result = {
        "step": 4,
        "metric": "positive_folds AND aggregate_sharpe_net",
        "kill_thresholds": {
            "min_positive_folds": int(k4_min_positive_folds),
            "min_aggregate_sharpe": float(k4_min_sharpe),
        },
        "observed_positive_folds": positive_folds,
        "observed_aggregate_sharpe_net": agg_sharpe,
        "n_total_test_trades": int(len(all_pnl)),
        "mean_net_pts_all_folds": float(np.nanmean(all_pnl)) if len(all_pnl) else float("nan"),
        "spread_hurdle_pts": float(spread_hurdle_pts),
        "direction_sign": int(direction_sign),
        "hold_window_ticks": int(hold_ticks),
        "folds": fold_results,
        "passed": passed,
    }
    _dump_json(result, out_dir / "step_4_walkforward.json")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    fold_ids = [f["fold"] for f in fold_results]
    means = [f["mean_net_pts"] for f in fold_results]
    colors = ["C2" if f["positive"] else "C3" for f in fold_results]
    ax.bar(fold_ids, means, color=colors)
    ax.axhline(0, color="k", linewidth=0.6)
    ax.set_xlabel("Fold")
    ax.set_ylabel("Mean net P&L (points per trade)")
    ax.set_title(
        f"Per-fold mean net P&L | positive {positive_folds}/{len(fold_results)} "
        f"(K4 needs ≥{k4_min_positive_folds})"
    )

    ax = axes[1]
    if len(all_pnl):
        ax.plot(np.cumsum(all_pnl))
    ax.axhline(0, color="k", linewidth=0.6)
    ax.set_xlabel("Trade index (across all folds, concatenated)")
    ax.set_ylabel("Cumulative net P&L (points)")
    ax.set_title(
        f"Cumulative net P&L | agg Sharpe={agg_sharpe:.3f}  "
        f"=> {'PASS' if passed else 'KILL'}"
    )
    fig.tight_layout()
    _savefig(fig, out_dir / "walkforward.png")

    log.info(
        f"[Step 4] positive folds = {positive_folds}/{len(fold_results)}, "
        f"agg Sharpe = {agg_sharpe:.3f} (threshold folds≥{k4_min_positive_folds} "
        f"AND Sharpe≥{k4_min_sharpe}) => {'PASS' if passed else 'KILL'}"
    )
    return passed, result


# ---------------------------------------------------------------------------
# primary pipeline
# ---------------------------------------------------------------------------

def analyze_primary(
    symbol: str,
    threshold_points: float,
    cfg: dict,
    log: Logger,
) -> dict:
    rd_cfg = cfg["regime_detection"]
    out_dir = REPO_ROOT / "data" / "analysis" / safe_symbol_dir(symbol) / "regimes"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(symbol)
    point = float(manifest["info"].get("point", 0.0001))
    log.info(f"[{symbol}] loading ticks (point={point})")

    ticks = load_symbol_ticks(symbol, columns=["time_msc", "time_utc", "bid", "ask"])
    log.info(
        f"[{symbol}] loaded {len(ticks):,} ticks from {ticks['time_utc'].min()} "
        f"to {ticks['time_utc'].max()}"
    )

    spikes = detect_spikes(ticks, point=point, threshold_points=threshold_points)
    log.info(
        f"[{symbol}] detected {len(spikes):,} spikes at threshold={threshold_points:,} pts "
        f"(Phase 0.5 uses these only for hourly spike counts, not for trade signals)"
    )

    log.info(f"[{symbol}] spike-masking ticks at {rd_cfg['spike_mask_threshold_points']} pts")
    masked = mask_spike_ticks(
        ticks, point=point,
        p995_threshold_pts=float(rd_cfg["spike_mask_threshold_points"]),
    )
    n_masked = int(masked["is_spike_tick"].sum())
    log.info(f"[{symbol}] masked {n_masked:,} spike-sized tick deltas "
             f"({100*n_masked/max(1,len(masked)):.3f}% of ticks)")

    log.info(f"[{symbol}] building 1-minute bars on spike-masked series")
    minute_bars = to_minute_bars(masked)
    log.info(f"[{symbol}] {len(minute_bars):,} minute bars built")

    drift_raw = hourly_raw_drift(ticks, price_col="bid")
    counts = hourly_spike_counts(spikes["time_utc"], drift_raw.index)
    cleanliness, cm_model = cleanliness_metric_b(drift_raw, counts)
    log.info(
        f"[{symbol}] cleanliness model: intercept={cm_model['intercept']:.4f}, "
        f"slope={cm_model['slope']:.4f}, R²={cm_model['r_squared']:.4f}, n={cm_model['n']}"
    )

    thresholds = {
        "k1_min_regime_median_minutes": rd_cfg["kill"]["k1_min_regime_median_minutes"],
        "k2_min_abs_acf": rd_cfg["kill"]["k2_min_abs_acf"],
        "k3_min_topq_signed_drift_points": rd_cfg["kill"]["k3_min_topq_signed_drift_points"],
        "k4_min_positive_folds": rd_cfg["kill"]["k4_min_positive_folds"],
        "k4_min_walkforward_sharpe": rd_cfg["kill"]["k4_min_walkforward_sharpe"],
        "spread_points_roundtrip": rd_cfg["spread_points_roundtrip"],
        "hold_window_ticks": rd_cfg["hold_window_ticks"],
        "spike_mask_threshold_points": rd_cfg["spike_mask_threshold_points"],
    }
    measurements: dict = {}

    # --- Step 1 ---
    log.info(f"[{symbol}] === STEP 1: HMM regime duration ===")
    s1_pass, s1_result, _ = run_step_1(
        minute_bars, out_dir, float(rd_cfg["kill"]["k1_min_regime_median_minutes"]), log,
    )
    measurements["step_1_hmm"] = {k: v for k, v in s1_result.items()
                                    if k != "run_stats"}
    if not s1_pass:
        write_verdict(out_dir, symbol, "KILL", 1, measurements, thresholds)
        return {"status": "KILL", "killed_at_step": 1, "measurements": measurements}

    # --- Step 2 ---
    log.info(f"[{symbol}] === STEP 2: cleanliness residual lag-1 ACF ===")
    s2_pass, s2_result = run_step_2(
        cleanliness, out_dir, float(rd_cfg["kill"]["k2_min_abs_acf"]), log,
    )
    measurements["step_2_acf"] = {k: v for k, v in s2_result.items()
                                    if k != "acf_values"}
    if not s2_pass:
        write_verdict(out_dir, symbol, "KILL", 2, measurements, thresholds)
        return {"status": "KILL", "killed_at_step": 2, "measurements": measurements}

    # --- Step 3 ---
    log.info(f"[{symbol}] === STEP 3: top-quartile signed drift vs spread ===")
    s3_pass, s3_result = run_step_3(
        ticks, cleanliness, symbol, point,
        int(rd_cfg["hold_window_ticks"]),
        float(rd_cfg["spread_points_roundtrip"]),
        out_dir,
        float(rd_cfg["kill"]["k3_min_topq_signed_drift_points"]),
        log,
    )
    measurements["step_3_effect_size"] = s3_result
    if not s3_pass:
        write_verdict(out_dir, symbol, "KILL", 3, measurements, thresholds)
        return {"status": "KILL", "killed_at_step": 3, "measurements": measurements}

    # --- Step 4 ---
    log.info(f"[{symbol}] === STEP 4: walk-forward validation ===")
    s4_pass, s4_result = run_step_4(
        ticks, drift_raw, counts, symbol, point,
        int(rd_cfg["hold_window_ticks"]),
        float(rd_cfg["spread_points_roundtrip"]),
        int(rd_cfg["walkforward"]["n_folds"]),
        int(rd_cfg["kill"]["k4_min_positive_folds"]),
        float(rd_cfg["kill"]["k4_min_walkforward_sharpe"]),
        out_dir, log,
    )
    measurements["step_4_walkforward"] = {k: v for k, v in s4_result.items()
                                            if k != "folds"}
    if not s4_pass:
        write_verdict(out_dir, symbol, "KILL", 4, measurements, thresholds)
        return {"status": "KILL", "killed_at_step": 4, "measurements": measurements}

    write_verdict(out_dir, symbol, "PASS", None, measurements, thresholds)
    return {"status": "PASS", "killed_at_step": None, "measurements": measurements}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Override primary symbol")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override spike-detection threshold (points)")
    parser.add_argument("--skip-exploratory", action="store_true",
                        help="Run primary only, skip Boom 1000 exploratory pass")
    args = parser.parse_args()

    cfg = load_config()
    rd_cfg = cfg["regime_detection"]
    logs_dir = str(REPO_ROOT / "logs")
    log = Logger("analyze_regimes", logs_dir, level="INFO", print_to_console=True)

    primary_symbol = args.symbol or rd_cfg["primary_symbol"]
    threshold = args.threshold if args.threshold is not None else float(rd_cfg["primary_threshold_points"])

    log.info(f"Phase 0.5 regime detection | primary={primary_symbol} threshold={threshold} pts")
    log.info("See PROTOCOL.md for pre-registered hypothesis and kill criteria.")

    overall: dict = {"primary": {}, "exploratory": {}}

    try:
        primary_result = analyze_primary(primary_symbol, threshold, cfg, log)
        overall["primary"][primary_symbol] = primary_result
        log.info(
            f"PRIMARY VERDICT: {primary_result['status']} "
            f"(killed_at_step={primary_result['killed_at_step']})"
        )
    except Exception as e:
        import traceback
        log.error(f"[{primary_symbol}] primary pipeline failed: {e}\n{traceback.format_exc()}")
        overall["primary"][primary_symbol] = {"error": str(e)}

    if not args.skip_exploratory:
        for exp_sym in rd_cfg.get("exploratory", {}).get("symbols", []):
            log.info(f"=== EXPLORATORY: {exp_sym} (informational only, cannot override primary) ===")
            try:
                exp_result = analyze_primary(exp_sym, threshold, cfg, log)
                overall["exploratory"][exp_sym] = exp_result
                log.info(
                    f"EXPLORATORY {exp_sym}: {exp_result['status']} "
                    f"(killed_at_step={exp_result['killed_at_step']}) "
                    f"[does NOT affect primary verdict]"
                )
            except Exception as e:
                import traceback
                log.error(f"[{exp_sym}] exploratory pipeline failed: {e}\n{traceback.format_exc()}")
                overall["exploratory"][exp_sym] = {"error": str(e)}

    combined_path = REPO_ROOT / "data" / "analysis" / "regimes_combined_summary.json"
    _dump_json(overall, combined_path)
    log.info(f"Wrote combined summary: {combined_path}")
    log.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
