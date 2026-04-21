from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .types import TriggerEvent


def _trigger_mask(symbol: str, delta: np.ndarray, threshold_price: float) -> np.ndarray:
    sym = symbol.lower()
    if "boom" in sym:
        return delta <= -threshold_price
    if "crash" in sym:
        return delta >= threshold_price
    raise ValueError(f"Unsupported symbol mapping for opposite trigger: {symbol}")


def detect_opposite_triggers(
    symbol: str,
    ticks: pd.DataFrame,
    point: float,
    threshold_points: float,
) -> list[TriggerEvent]:
    if ticks.empty:
        return []

    threshold_price = threshold_points * point
    bid = ticks["bid"].astype("float32").to_numpy()
    t = pd.to_datetime(ticks["time_utc"], utc=True).to_numpy()
    n = len(bid)
    if n < 2:
        return []

    out: list[TriggerEvent] = []
    chunk = 500_000
    for start in range(1, n, chunk):
        end = min(start + chunk, n)
        delta = bid[start:end] - bid[start - 1 : end - 1]
        mask = _trigger_mask(symbol, delta, threshold_price) & np.isfinite(delta)
        if not np.any(mask):
            continue
        local_idx = np.where(mask)[0]
        global_idx = local_idx + start
        delta_pts = delta[local_idx] / point if point > 0 else delta[local_idx]
        for gi, dp in zip(global_idx.tolist(), delta_pts.tolist()):
            out.append(
                TriggerEvent(
                    symbol=symbol,
                    trigger_idx=int(gi),
                    trigger_time=pd.Timestamp(t[gi]).to_pydatetime(),
                    trigger_kind="opposite_move",
                    delta_points=float(dp),
                )
            )
    return out


def trigger_indices(triggers: Iterable[TriggerEvent]) -> np.ndarray:
    return np.array([t.trigger_idx for t in triggers], dtype=np.int64)
