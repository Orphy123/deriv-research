"""
spike_detector.py — Pure function over a tick DataFrame that identifies
spike events.

A "spike" is defined as a single-tick absolute bid-price delta exceeding a
threshold in POINTS (where 1 point = symbol_info['point']). This is the
natural Boom/Crash spike definition: the engine's discontinuous price jump.

Direction convention:
  - UP spike   (delta > 0): observed on Boom 1000 (upward discontinuities)
  - DOWN spike (delta < 0): observed on Crash 1000 (downward discontinuities)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


SPIKE_COLS = [
    "time_utc", "time_msc", "price_before", "price_after",
    "delta_price", "delta_points", "direction", "row_idx",
]


def detect_spikes(
    ticks: pd.DataFrame,
    point: float,
    threshold_points: float,
    price_col: str = "bid",
) -> pd.DataFrame:
    """Return a DataFrame of spike events.

    Each row corresponds to a single-tick discontinuity where |Δprice| >
    threshold_points * point. The event timestamp is the AFTER-tick
    (when the spike became visible to the feed).
    """
    if ticks.empty:
        return pd.DataFrame(columns=SPIKE_COLS)

    price = ticks[price_col].astype(float).to_numpy()
    delta = np.diff(price, prepend=np.nan)
    delta_points = np.abs(delta) / point if point > 0 else np.abs(delta)
    mask = (~np.isnan(delta)) & (delta_points >= threshold_points)

    idx = np.where(mask)[0]
    if len(idx) == 0:
        return pd.DataFrame(columns=SPIKE_COLS)

    out = pd.DataFrame({
        "time_utc": ticks["time_utc"].iloc[idx].values,
        "time_msc": ticks["time_msc"].iloc[idx].values if "time_msc" in ticks.columns else np.nan,
        "price_before": price[idx - 1],
        "price_after": price[idx],
        "delta_price": delta[idx],
        "delta_points": delta_points[idx],
        "direction": np.where(delta[idx] > 0, "UP", "DOWN"),
        "row_idx": idx,
    })
    return out
