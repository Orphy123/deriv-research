"""
analyze_spikes.py — The single most important analysis in this repo.

Asks one question per symbol:
    Is Boom/Crash 1000's spike process memoryless (iid Poisson) or does it
    exhibit statistical structure a strategy could exploit?

If memoryless: PSDC and every "post-spike" strategy has no edge by
construction. Stop building.
If structured: quantify the structure and use it to calibrate strategy
parameters.

Tests performed:
    1. Inter-arrival times: KS test vs exponential with measured λ.
       H0 = memoryless. Reject => structured.
    2. Dispersion index of spike count in 1-hour buckets. D=1 for Poisson,
       D<1 for under-dispersed (anti-clustering), D>1 for over-dispersed
       (clustering).
    3. Lag-1 autocorrelation of inter-arrival times. 0 for memoryless.
    4. Post-spike drift: for each spike, compute cumulative price change
       over the next N ticks (50, 100, 300, 600). Compare mean drift in
       "post-spike" windows to unconditional mean drift from random
       matched windows via Welch's t.
    5. Time-since-last-spike distribution: empirical hazard function.
       Constant hazard => memoryless.

Outputs:
    data/analysis/<symbol>/summary.json
    data/analysis/<symbol>/inter_arrival_hist.png
    data/analysis/<symbol>/hazard.png
    data/analysis/<symbol>/post_spike_drift.png

Run:
    python -m scripts.analyze_spikes                        # both symbols
    python -m scripts.analyze_spikes --symbol "Boom 1000 Index"
    python -m scripts.analyze_spikes --threshold 30000      # override pts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config_loader import load_config
from src.logger import Logger
from src.spike_detector import detect_spikes
from src.tick_io import load_manifest, load_symbol_ticks, safe_symbol_dir


def _savefig(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def analyze_inter_arrival(spikes: pd.DataFrame, out_dir: Path) -> dict:
    """KS test vs exponential + dispersion index + lag-1 autocorr."""
    if len(spikes) < 50:
        return {"n_spikes": int(len(spikes)), "note": "too few spikes for inter-arrival tests"}

    t = spikes["time_utc"].sort_values().values
    ia = np.diff(t).astype("timedelta64[ms]").astype(float) / 1000.0
    ia = ia[ia > 0]

    mean_ia = float(ia.mean())
    var_ia = float(ia.var(ddof=1))
    lam = 1.0 / mean_ia if mean_ia > 0 else np.nan

    ks_stat, ks_p = stats.kstest(ia, "expon", args=(0.0, mean_ia))

    if len(ia) > 2:
        r1 = float(np.corrcoef(ia[:-1], ia[1:])[0, 1])
    else:
        r1 = float("nan")

    t_series = pd.to_datetime(spikes["time_utc"], utc=True)
    hourly = t_series.dt.floor("h").value_counts().sort_index()
    disp_index = float(hourly.var(ddof=1) / hourly.mean()) if hourly.mean() > 0 else np.nan

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    ax = axes[0]
    ax.hist(ia, bins=80, density=True, alpha=0.6, label="Observed")
    xs = np.linspace(0, float(np.quantile(ia, 0.99)), 200)
    ax.plot(xs, lam * np.exp(-lam * xs), "r-", label=f"Exponential(λ={lam:.4f}/s)")
    ax.set_xlabel("Inter-arrival time (s)")
    ax.set_ylabel("Density")
    ax.set_title(f"Spike inter-arrival distribution\nKS p={ks_p:.4g}, n={len(ia)}")
    ax.legend()

    ax = axes[1]
    ax.hist(hourly.values, bins=min(30, hourly.max() + 1 if hourly.max() > 0 else 10))
    mean_hourly = float(hourly.mean())
    ax.axvline(mean_hourly, color="red", linestyle="--", label=f"mean={mean_hourly:.2f}")
    ax.set_xlabel("Spikes per hour")
    ax.set_ylabel("Hours")
    ax.set_title(f"Hourly spike count | Dispersion index={disp_index:.3f}")
    ax.legend()

    _savefig(fig, out_dir / "inter_arrival_hist.png")

    return {
        "n_spikes": int(len(spikes)),
        "mean_inter_arrival_s": mean_ia,
        "var_inter_arrival_s": var_ia,
        "lambda_per_sec": float(lam),
        "ks_stat": float(ks_stat),
        "ks_p_value": float(ks_p),
        "lag1_autocorr": r1,
        "hourly_mean": float(hourly.mean()),
        "hourly_var": float(hourly.var(ddof=1)),
        "dispersion_index": disp_index,
        "memoryless_rejected_at_5pct": bool(ks_p < 0.05),
    }


def analyze_hazard(spikes: pd.DataFrame, out_dir: Path) -> dict:
    """Empirical hazard function: if spikes are memoryless, hazard is flat."""
    if len(spikes) < 100:
        return {"note": "too few spikes for hazard analysis"}
    t = spikes["time_utc"].sort_values().values
    ia = np.diff(t).astype("timedelta64[ms]").astype(float) / 1000.0
    ia = ia[ia > 0]

    max_t = float(np.quantile(ia, 0.95))
    bins = np.linspace(0, max_t, 40)
    counts, edges = np.histogram(ia, bins=bins)
    at_risk = np.array([int((ia >= edges[i]).sum()) for i in range(len(counts))])
    width = np.diff(edges)
    hazard = np.where(at_risk > 0, counts / (at_risk * width), 0.0)
    centers = (edges[:-1] + edges[1:]) / 2

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(centers, hazard, marker="o", markersize=4)
    mean_hazard = 1.0 / float(ia.mean()) if ia.mean() > 0 else 0.0
    ax.axhline(mean_hazard, color="red", linestyle="--", label=f"Memoryless λ={mean_hazard:.4f}")
    ax.set_xlabel("Time since last spike (s)")
    ax.set_ylabel("Empirical hazard rate (events / s)")
    ax.set_title("Empirical hazard vs. Poisson (flat line)")
    ax.legend()
    _savefig(fig, out_dir / "hazard.png")
    return {
        "mean_hazard": mean_hazard,
        "hazard_max": float(hazard.max()),
        "hazard_min": float(hazard.min()),
    }


def analyze_post_spike_drift(
    ticks: pd.DataFrame,
    spikes: pd.DataFrame,
    point: float,
    out_dir: Path,
    windows: list[int] = (50, 100, 300, 600),
    n_random: int = 2000,
    seed: int = 42,
) -> dict:
    """For each spike, measure cumulative price delta over next N ticks.
    Compare to random-window baseline via Welch's t-test.

    Directionally-aware: for UP spikes we report drift in price units
    (always positive = continuation, negative = mean-reversion).
    """
    if spikes.empty or ticks.empty:
        return {"note": "no spikes or no ticks"}

    rng = np.random.default_rng(seed)
    price = ticks["bid"].astype(float).to_numpy()
    n = len(price)
    spike_idx = spikes["row_idx"].astype(int).to_numpy()
    spike_dir = spikes["direction"].to_numpy()

    results: dict = {}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes_flat = axes.flatten()

    for i, w in enumerate(windows):
        post_drifts = []
        for idx, d in zip(spike_idx, spike_dir):
            end = idx + w
            if end >= n:
                continue
            delta = price[end] - price[idx]
            if d == "UP":
                post_drifts.append(delta)
            else:
                post_drifts.append(-delta)
        post_drifts = np.array(post_drifts, dtype=float)

        valid_starts = np.arange(1, n - w - 1)
        if len(valid_starts) == 0:
            continue
        sample = rng.choice(valid_starts, size=min(n_random, len(valid_starts)), replace=False)
        rand_drifts = price[sample + w] - price[sample]

        if len(post_drifts) >= 30 and len(rand_drifts) >= 30:
            t_stat, t_p = stats.ttest_ind(post_drifts, rand_drifts, equal_var=False)
        else:
            t_stat, t_p = float("nan"), float("nan")

        results[f"w={w}"] = {
            "window_ticks": int(w),
            "n_post_spike": int(len(post_drifts)),
            "post_drift_mean_price": float(post_drifts.mean()) if len(post_drifts) else float("nan"),
            "post_drift_median_price": float(np.median(post_drifts)) if len(post_drifts) else float("nan"),
            "post_drift_mean_points": float(post_drifts.mean() / point) if point > 0 and len(post_drifts) else float("nan"),
            "rand_drift_mean_price": float(rand_drifts.mean()),
            "rand_drift_mean_points": float(rand_drifts.mean() / point) if point > 0 else float("nan"),
            "welch_t": float(t_stat),
            "welch_p": float(t_p),
            "significant_at_5pct": bool(t_p < 0.05) if not np.isnan(t_p) else False,
        }

        ax = axes_flat[i]
        bins = np.linspace(
            min(post_drifts.min(), rand_drifts.min()),
            max(post_drifts.max(), rand_drifts.max()),
            60,
        )
        ax.hist(rand_drifts, bins=bins, alpha=0.5, density=True, label=f"Random n={len(rand_drifts)}")
        ax.hist(post_drifts, bins=bins, alpha=0.5, density=True, label=f"Post-spike n={len(post_drifts)}")
        ax.axvline(0, color="k", linewidth=0.5)
        ax.axvline(post_drifts.mean() if len(post_drifts) else 0, color="C1", linestyle="--",
                   label=f"post-mean={post_drifts.mean():.3f}")
        ax.axvline(rand_drifts.mean(), color="C0", linestyle="--",
                   label=f"rand-mean={rand_drifts.mean():.3f}")
        ax.set_title(f"Post-spike drift, window={w} ticks | Welch p={t_p:.4g}")
        ax.set_xlabel("Δprice (drift-direction-adjusted)")
        ax.set_ylabel("Density")
        ax.legend(fontsize=7)

    fig.tight_layout()
    _savefig(fig, out_dir / "post_spike_drift.png")
    return results


def analyze_symbol(symbol: str, threshold_points: float, log: Logger) -> dict:
    out_dir = REPO_ROOT / "data" / "analysis" / safe_symbol_dir(symbol)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(symbol)
    point = manifest["info"].get("point", 0.0001)
    log.info(f"[{symbol}] loading ticks (point={point})...")

    ticks = load_symbol_ticks(symbol, columns=["time_msc", "time_utc", "bid", "ask"])
    log.info(f"[{symbol}] loaded {len(ticks):,} ticks from {ticks['time_utc'].min()} to {ticks['time_utc'].max()}")

    spikes = detect_spikes(ticks, point=point, threshold_points=threshold_points)
    log.info(f"[{symbol}] detected {len(spikes):,} spikes at threshold={threshold_points:,} pts")

    if not spikes.empty:
        log.info(
            f"[{symbol}] by direction: UP={int((spikes['direction']=='UP').sum()):,} "
            f"DOWN={int((spikes['direction']=='DOWN').sum()):,}"
        )

    summary: dict = {
        "symbol": symbol,
        "threshold_points": threshold_points,
        "point": point,
        "n_ticks": int(len(ticks)),
        "time_from": str(ticks["time_utc"].min()),
        "time_to": str(ticks["time_utc"].max()),
        "n_spikes": int(len(spikes)),
    }

    summary["inter_arrival"] = analyze_inter_arrival(spikes, out_dir)
    summary["hazard"] = analyze_hazard(spikes, out_dir)
    summary["post_spike_drift"] = analyze_post_spike_drift(ticks, spikes, point, out_dir)

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    ia = summary["inter_arrival"]
    log.info(
        f"[{symbol}] KS test vs exponential: stat={ia.get('ks_stat', float('nan')):.4f} "
        f"p={ia.get('ks_p_value', float('nan')):.4g}  "
        f"=> memoryless {'REJECTED' if ia.get('memoryless_rejected_at_5pct') else 'not rejected'}"
    )
    log.info(
        f"[{symbol}] Dispersion index (hourly): {ia.get('dispersion_index', float('nan')):.3f} "
        f"(1.0 = Poisson)"
    )
    log.info(
        f"[{symbol}] Lag-1 autocorr of inter-arrivals: {ia.get('lag1_autocorr', float('nan')):.4f} "
        f"(0 = memoryless)"
    )

    for w_key, w_res in summary["post_spike_drift"].items():
        if isinstance(w_res, dict) and "welch_p" in w_res:
            log.info(
                f"[{symbol}] post-spike {w_key}: "
                f"post_mean={w_res['post_drift_mean_points']:.1f}pts  "
                f"rand_mean={w_res['rand_drift_mean_points']:.1f}pts  "
                f"Welch p={w_res['welch_p']:.4g}  "
                f"{'*SIG*' if w_res['significant_at_5pct'] else 'n.s.'}"
            )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Single symbol; default analyses all available")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Spike threshold in points; default from config.yaml")
    args = parser.parse_args()

    logs_dir = str(REPO_ROOT / "logs")
    log = Logger("analyze_spikes", logs_dir, level="INFO", print_to_console=True)

    config = load_config()
    threshold = args.threshold
    if threshold is None:
        threshold = float(config.get("spike_detection", {}).get("threshold_points", 30000))

    data_ticks_root = REPO_ROOT / "data" / "ticks"
    available = [p.name for p in data_ticks_root.glob("*") if p.is_dir()]
    log.info(f"Available tick dirs: {available}")

    if args.symbol:
        targets = [args.symbol]
    else:
        targets = [d.replace("_", " ") for d in available]

    overall = {}
    for sym in targets:
        try:
            overall[sym] = analyze_symbol(sym, threshold, log)
        except Exception as e:
            import traceback
            log.error(f"[{sym}] analysis failed: {e}\n{traceback.format_exc()}")
            overall[sym] = {"error": str(e)}

    summary_path = REPO_ROOT / "data" / "analysis" / "combined_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(overall, f, indent=2, default=str)
    log.info(f"Wrote combined summary: {summary_path}")
    log.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
