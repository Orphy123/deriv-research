"""
regime.py — Pure-function primitives for Phase 0.5 regime-detection analysis.

See PROTOCOL.md for the pre-registered hypothesis and kill criteria. This
module is deliberately I/O-free: loading and plotting live in the orchestrator
(`scripts/analyze_regimes.py`).

Functions:
    mask_spike_ticks         — null out spike-size tick deltas and rebuild
                                a spike-free bid series (cumsum of remaining
                                deltas) to feed into minute aggregation.
    to_minute_bars           — 1-minute OHLC + close-to-close return bars.
    hourly_spike_counts      — per-H1 spike count aligned to minute-bar index.
    hourly_raw_drift         — per-H1 close-to-close drift on the RAW series.
    cleanliness_metric_b     — per-H1 residual of (raw drift) regressed on
                                (spike count). Positive residual = hour drifted
                                further than the spike count would predict.
    fit_two_state_hmm        — 2-state GaussianHMM on clipped 1-min returns,
                                returns model + Viterbi state sequence + run
                                lengths per state (in minutes).
    expanding_walkforward_folds — 6-fold (by default) expanding-window index
                                   slicing for out-of-sample validation.
"""

from __future__ import annotations

from itertools import groupby
from typing import Iterable

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# spike masking
# ---------------------------------------------------------------------------

def mask_spike_ticks(
    ticks: pd.DataFrame,
    point: float,
    p995_threshold_pts: float = 420.0,
    price_col: str = "bid",
) -> pd.DataFrame:
    """Return a copy of `ticks` with two extra columns:

        is_spike_tick : bool     — True where |Δprice| > p995_threshold_pts * point.
        bid_masked    : float    — reconstructed price where spike deltas are
                                   replaced with zero. Anchored at the first
                                   tick's price (so absolute level is not
                                   directly comparable to `bid`, but tick-to-
                                   tick drift is preserved modulo spike-sized
                                   jumps).

    This implements the "spike-mask first" discipline from PROTOCOL.md:
    downstream HMM and cleanliness metrics operate on `bid_masked`, not `bid`.
    """
    if ticks.empty:
        out = ticks.copy()
        out["is_spike_tick"] = False
        out["bid_masked"] = ticks[price_col] if price_col in ticks.columns else np.nan
        return out

    price = ticks[price_col].astype(float).to_numpy()
    delta = np.diff(price, prepend=price[0])  # first delta = 0 so price[0] is preserved
    delta_pts = np.abs(delta) / point if point > 0 else np.abs(delta)
    is_spike = delta_pts > p995_threshold_pts

    delta_masked = np.where(is_spike, 0.0, delta)
    bid_masked = price[0] + np.cumsum(delta_masked)

    out = ticks.copy()
    out["is_spike_tick"] = is_spike
    out["bid_masked"] = bid_masked
    return out


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def to_minute_bars(ticks_masked: pd.DataFrame) -> pd.DataFrame:
    """1-minute OHLC bars on the spike-masked series.

    Returns a DataFrame indexed by minute-start timestamps with columns:
        open, high, low, close, return, n_ticks

    `return` is the close-to-close first-difference (first row is dropped).
    Empty minutes (no ticks) are forward-filled from the previous bar's close
    for `close`, with `return = 0.0` assigned for those gaps. This matches
    Deriv's continuous 24/7 data model and avoids fake "jumps" across market
    gaps that don't exist on synthetics.
    """
    if ticks_masked.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "return", "n_ticks"])

    df = ticks_masked[["time_utc", "bid_masked"]].copy()
    df = df.set_index("time_utc").sort_index()

    agg = df["bid_masked"].resample("1min").agg(
        open="first",
        high="max",
        low="min",
        close="last",
    )
    n_ticks = df["bid_masked"].resample("1min").count().rename("n_ticks")
    bars = pd.concat([agg, n_ticks], axis=1)

    bars["close"] = bars["close"].ffill()
    bars["open"] = bars["open"].fillna(bars["close"])
    bars["high"] = bars["high"].fillna(bars["close"])
    bars["low"] = bars["low"].fillna(bars["close"])

    bars["return"] = bars["close"].diff().fillna(0.0)
    bars = bars.dropna(subset=["close"])

    return bars


def hourly_spike_counts(
    spike_times: pd.Series, index_hours: pd.DatetimeIndex
) -> pd.Series:
    """Count of spikes falling inside each hourly bucket in `index_hours`.

    `spike_times` is a timezone-aware Series of spike event timestamps
    (typically `spikes["time_utc"]` from the spike detector). `index_hours` is
    a floor("h") hour index aligned to the analysis period.
    """
    if len(spike_times) == 0:
        return pd.Series(0, index=index_hours, dtype=int)
    hours = pd.to_datetime(spike_times, utc=True).dt.floor("h")
    counts = hours.value_counts().sort_index()
    counts = counts.reindex(index_hours, fill_value=0)
    return counts.astype(int)


def hourly_raw_drift(ticks_raw: pd.DataFrame, price_col: str = "bid") -> pd.Series:
    """Per-H1 close-open drift on the RAW (unmasked) tick series.

    Returns a Series indexed by hour-start timestamps.
    """
    if ticks_raw.empty:
        return pd.Series(dtype=float)
    s = ticks_raw[["time_utc", price_col]].copy()
    s = s.set_index("time_utc").sort_index()
    price_hourly = s[price_col].resample("1h").agg(open="first", close="last")
    drift = (price_hourly["close"] - price_hourly["open"]).dropna()
    return drift


# ---------------------------------------------------------------------------
# cleanliness metric B
# ---------------------------------------------------------------------------

def cleanliness_metric_b(
    hourly_drift_raw: pd.Series,
    hourly_spike_counts_: pd.Series,
) -> tuple[pd.Series, dict]:
    """Per-H1 residual of observed drift regressed on spike count.

    Fits an ordinary least squares line:

        drift[h] = intercept + slope * spike_count[h] + residual[h]

    The residual is the "unexplained drift" — the component of each hour's
    move that is NOT accounted for by the number of spikes that fired. If
    drift regimes exist, this residual should be autocorrelated (Step 2) and
    its top quartile should identify hours with outsized directional drift
    relative to their spike load (Step 3).

    Returns:
        residuals : pd.Series indexed by hour-start.
        model     : dict with intercept, slope, r_squared, n.
    """
    df = pd.concat(
        [hourly_drift_raw.rename("drift"), hourly_spike_counts_.rename("n_sp")],
        axis=1,
    ).dropna()
    if len(df) < 10:
        empty = pd.Series(dtype=float)
        return empty, {"n": int(len(df)), "note": "insufficient data"}

    x = df["n_sp"].to_numpy(dtype=float)
    y = df["drift"].to_numpy(dtype=float)

    x_mean = x.mean()
    y_mean = y.mean()
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 0:
        slope = 0.0
    else:
        slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = float(y_mean - slope * x_mean)

    pred = intercept + slope * x
    resid = y - pred
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    residuals = pd.Series(resid, index=df.index, name="residual")
    model = {
        "intercept": intercept,
        "slope": slope,
        "r_squared": r2,
        "n": int(len(df)),
    }
    return residuals, model


# ---------------------------------------------------------------------------
# two-state HMM
# ---------------------------------------------------------------------------

def fit_two_state_hmm(
    minute_returns: np.ndarray,
    seed: int = 42,
    clip_quantiles: tuple[float, float] = (0.001, 0.999),
    n_iter: int = 100,
    tol: float = 1e-4,
) -> tuple[dict, np.ndarray, dict]:
    """Fit a 2-state diagonal-Gaussian HMM on clipped 1-minute returns.

    Pure-numpy Baum-Welch EM in log-space with Viterbi decoding. Written
    inline rather than depending on hmmlearn so the project doesn't require
    a C++ toolchain on Windows / Python 3.14 where the hmmlearn wheel is
    unavailable.

    Clipping at (0.1%, 99.9%) prevents residual fat-tail outliers (even after
    spike masking, 1-minute return distributions on these instruments retain
    meaningful excess kurtosis) from dominating the variance estimate and
    producing a degenerate one-state fit.

    Returns:
        model     : dict {pi, A, mu, var, log_likelihood, n_iter_ran, converged}
        states    : np.ndarray of Viterbi-decoded state assignments (length
                    matches input).
        run_stats : dict with per-state median / mean / n-runs, plus the
                    overall median run-length.
    """
    r = np.asarray(minute_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 1000:
        raise ValueError(f"Need at least 1000 minute bars, got {len(r)}.")

    lo, hi = np.quantile(r, clip_quantiles[0]), np.quantile(r, clip_quantiles[1])
    r = np.clip(r, lo, hi)
    T = len(r)
    K = 2

    rng = np.random.default_rng(seed)
    _ = rng  # reserved; deterministic init below

    pi = np.array([0.5, 0.5])
    A = np.array([[0.95, 0.05], [0.05, 0.95]])
    mu = np.array([float(np.quantile(r, 0.25)), float(np.quantile(r, 0.75))])
    var = np.array([float(r.var()), float(r.var())])
    var = np.maximum(var, 1e-10)

    log_ll_prev = -np.inf
    log_ll = -np.inf
    converged = False
    iter_ran = 0

    # Scaled (Rabiner) forward-backward with K=2 hand-rolled scalar inner
    # loop. Vectorized log-space variants spend most of their time in numpy
    # call overhead at T~100k and K=2; scalar arithmetic in a tight Python
    # loop is substantially faster in practice on this shape.
    for it in range(n_iter):
        iter_ran = it + 1

        inv_sqrt = 1.0 / np.sqrt(2.0 * np.pi * var)
        b = inv_sqrt[None, :] * np.exp(
            -0.5 * (r[:, None] - mu[None, :]) ** 2 / var[None, :]
        )
        b = np.maximum(b, 1e-300)

        # Forward (scaled)
        alpha = np.empty((T, K))
        c_scale = np.empty(T)

        tmp0 = pi[0] * b[0, 0]
        tmp1 = pi[1] * b[0, 1]
        s = tmp0 + tmp1
        c_scale[0] = s
        alpha[0, 0] = tmp0 / s
        alpha[0, 1] = tmp1 / s

        a00, a01, a10, a11 = A[0, 0], A[0, 1], A[1, 0], A[1, 1]

        for t in range(1, T):
            p0 = alpha[t - 1, 0]
            p1 = alpha[t - 1, 1]
            n0 = (p0 * a00 + p1 * a10) * b[t, 0]
            n1 = (p0 * a01 + p1 * a11) * b[t, 1]
            s = n0 + n1
            if s <= 0.0:
                s = 1e-300
                n0 = 0.5
                n1 = 0.5
            c_scale[t] = s
            alpha[t, 0] = n0 / s
            alpha[t, 1] = n1 / s

        log_ll = float(np.log(c_scale).sum())

        # Backward (scaled by forward's c_scale)
        beta = np.empty((T, K))
        beta[T - 1, 0] = 1.0
        beta[T - 1, 1] = 1.0
        for t in range(T - 2, -1, -1):
            b0 = b[t + 1, 0] * beta[t + 1, 0]
            b1 = b[t + 1, 1] * beta[t + 1, 1]
            n0 = a00 * b0 + a01 * b1
            n1 = a10 * b0 + a11 * b1
            cs = c_scale[t + 1]
            beta[t, 0] = n0 / cs
            beta[t, 1] = n1 / cs

        # Posteriors (Rabiner convention: gamma = alpha_scaled * beta_scaled)
        gamma = alpha * beta

        # xi[t,i,j] = alpha_t(i) * A[i,j] * b[t+1,j] * beta[t+1,j] / c[t+1]
        xi_sum = np.zeros((K, K))
        inv_c = 1.0 / c_scale[1:]
        # Vectorized xi_sum: (T-1, 2, 2)
        t_b = b[1:, None, :] * beta[1:, None, :]
        t_a = alpha[:-1, :, None]
        xi = t_a * A[None, :, :] * t_b * inv_c[:, None, None]
        xi_sum = xi.sum(axis=0)

        # M-step
        g0 = gamma[0]
        pi = g0 / g0.sum() if g0.sum() > 0 else pi

        gamma_sum_ex_last = gamma[:-1].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            A_new = xi_sum / gamma_sum_ex_last[:, None]
        A_new = np.where(np.isfinite(A_new), A_new, A)
        row_sums = A_new.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums > 0, row_sums, 1.0)
        A = A_new / row_sums

        w = gamma.sum(axis=0)
        w_safe = np.maximum(w, 1e-12)
        mu = (gamma * r[:, None]).sum(axis=0) / w_safe
        var = (gamma * (r[:, None] - mu[None, :]) ** 2).sum(axis=0) / w_safe
        var = np.maximum(var, 1e-10)

        if np.isfinite(log_ll) and np.isfinite(log_ll_prev):
            if abs(log_ll - log_ll_prev) < tol * max(1.0, abs(log_ll_prev)):
                converged = True
                break
        log_ll_prev = log_ll

    # Viterbi decoding in log-space with final parameters
    log_b = -0.5 * np.log(2.0 * np.pi * var[None, :]) \
            - 0.5 * (r[:, None] - mu[None, :]) ** 2 / var[None, :]
    log_A = np.log(A + 1e-300)
    log_pi = np.log(pi + 1e-300)

    log_delta = np.empty((T, K))
    psi = np.zeros((T, K), dtype=np.int64)
    log_delta[0, 0] = log_pi[0] + log_b[0, 0]
    log_delta[0, 1] = log_pi[1] + log_b[0, 1]
    lA00, lA01, lA10, lA11 = log_A[0, 0], log_A[0, 1], log_A[1, 0], log_A[1, 1]
    for t in range(1, T):
        p0 = log_delta[t - 1, 0]
        p1 = log_delta[t - 1, 1]
        c0_from0 = p0 + lA00
        c0_from1 = p1 + lA10
        c1_from0 = p0 + lA01
        c1_from1 = p1 + lA11
        if c0_from0 >= c0_from1:
            log_delta[t, 0] = c0_from0 + log_b[t, 0]
            psi[t, 0] = 0
        else:
            log_delta[t, 0] = c0_from1 + log_b[t, 0]
            psi[t, 0] = 1
        if c1_from0 >= c1_from1:
            log_delta[t, 1] = c1_from0 + log_b[t, 1]
            psi[t, 1] = 0
        else:
            log_delta[t, 1] = c1_from1 + log_b[t, 1]
            psi[t, 1] = 1
    states = np.zeros(T, dtype=np.int64)
    states[T - 1] = int(np.argmax(log_delta[T - 1]))
    for t in range(T - 2, -1, -1):
        states[t] = int(psi[t + 1, states[t + 1]])

    # run-length stats
    runs: list[tuple[int, int]] = [
        (int(k), sum(1 for _ in g)) for k, g in groupby(states.tolist())
    ]
    runs_by_state: dict[int, list[int]] = {0: [], 1: []}
    for k, length in runs:
        runs_by_state.setdefault(k, []).append(length)

    def _stat(lengths: list[int]) -> dict:
        if not lengths:
            return {"n_runs": 0, "median_minutes": float("nan"),
                    "mean_minutes": float("nan")}
        arr = np.asarray(lengths, dtype=float)
        return {
            "n_runs": int(len(lengths)),
            "median_minutes": float(np.median(arr)),
            "mean_minutes": float(arr.mean()),
        }

    all_lengths = [l for _, l in runs]
    overall_median = float(np.median(all_lengths)) if all_lengths else float("nan")

    run_stats = {
        "state_0": _stat(runs_by_state.get(0, [])),
        "state_1": _stat(runs_by_state.get(1, [])),
        "overall_median_minutes": overall_median,
        "n_total_runs": len(runs),
        "state_means": [float(mu[0]), float(mu[1])],
        "state_vars": [float(var[0]), float(var[1])],
        "n_iter_ran": int(iter_ran),
        "converged": bool(converged),
    }
    model = {
        "pi": pi.tolist(),
        "A": A.tolist(),
        "mu": mu.tolist(),
        "var": var.tolist(),
        "log_likelihood": float(log_ll),
        "n_iter_ran": int(iter_ran),
        "converged": bool(converged),
    }
    return model, states, run_stats


# ---------------------------------------------------------------------------
# walk-forward
# ---------------------------------------------------------------------------

def expanding_walkforward_folds(
    n: int, k: int = 6, initial_train_frac: float = 0.5
) -> list[tuple[slice, slice]]:
    """Yield k expanding-window (train, test) slices over range(n).

    Initial training window is `initial_train_frac * n`. The remaining tail is
    divided into k equal (or near-equal) test blocks; each fold's training
    window extends up to the start of its test block.
    """
    if n < 10 or k < 1:
        return []
    init = max(1, int(n * initial_train_frac))
    tail = n - init
    if tail < k:
        return []
    base = tail // k
    folds: list[tuple[slice, slice]] = []
    for i in range(k):
        train_end = init + i * base
        test_end = train_end + base if i < k - 1 else n
        folds.append((slice(0, train_end), slice(train_end, test_end)))
    return folds


# ---------------------------------------------------------------------------
# helpers used by multiple steps
# ---------------------------------------------------------------------------

def signed_drift_direction_for_symbol(symbol: str) -> int:
    """Trade-direction sign implied by the regime-detection hypothesis.

    Boom 1000 exhibits UP-spike discontinuities and positive inter-spike
    drift during "clean" regimes — so long is the signed direction (+1).

    Crash 1000 is the mirror — short during clean regimes (-1).
    """
    s = symbol.lower()
    if "boom" in s:
        return +1
    if "crash" in s:
        return -1
    return +1


def forward_tick_drift(
    prices: np.ndarray, entry_indices: Iterable[int], hold_ticks: int
) -> np.ndarray:
    """Cumulative price change over the next `hold_ticks` ticks for each entry."""
    p = np.asarray(prices, dtype=float)
    n = len(p)
    out: list[float] = []
    for idx in entry_indices:
        i = int(idx)
        j = i + int(hold_ticks)
        if j < n and i >= 0:
            out.append(float(p[j] - p[i]))
    return np.asarray(out, dtype=float)
