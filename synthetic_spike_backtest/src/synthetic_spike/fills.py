from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostScenario:
    name: str
    spread_multiplier: float
    slippage_points: float


@dataclass(frozen=True)
class PriceLadder:
    bid: np.ndarray
    ask: np.ndarray
    mid: np.ndarray
    time_ns: np.ndarray


def build_price_ladder(ticks: pd.DataFrame, fallback_spread_points: float, point: float) -> PriceLadder:
    bid = ticks["bid"].astype(float).to_numpy()
    ask_raw = ticks["ask"].to_numpy()
    ask = np.array(ask_raw, dtype=float, copy=True)

    synthetic_ask = bid + fallback_spread_points * point
    invalid = ~np.isfinite(ask) | (ask <= 0) | (ask < bid)
    ask[invalid] = synthetic_ask[invalid]

    mid = (bid + ask) / 2.0
    time_ns = (
        pd.to_datetime(ticks["time_utc"], utc=True)
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .to_numpy(dtype="datetime64[ns]")
        .astype("int64")
    )
    return PriceLadder(bid=bid, ask=ask, mid=mid, time_ns=time_ns)


def latency_adjusted_index(time_ns: np.ndarray, event_idx: int, latency_ms: int) -> int:
    if event_idx < 0:
        return event_idx
    if latency_ms <= 0:
        return event_idx
    target_ns = int(time_ns[event_idx]) + int(latency_ms) * 1_000_000
    idx = int(np.searchsorted(time_ns, target_ns, side="left"))
    return min(idx, len(time_ns) - 1)


def _scaled_quotes(ladder: PriceLadder, idx: int, spread_multiplier: float) -> tuple[float, float, float]:
    bid = float(ladder.bid[idx])
    ask = float(ladder.ask[idx])
    mid = float(ladder.mid[idx])
    spread = max(ask - bid, 0.0)
    scaled_spread = spread * max(spread_multiplier, 0.0)
    scaled_bid = mid - scaled_spread / 2.0
    scaled_ask = mid + scaled_spread / 2.0
    return scaled_bid, scaled_ask, mid


def fill_prices_for_trade(
    side: str,
    entry_idx: int,
    exit_idx: int,
    ladder: PriceLadder,
    point: float,
    scenario: CostScenario,
) -> tuple[float, float, float, float, float]:
    b_ent, a_ent, m_ent = _scaled_quotes(ladder, entry_idx, scenario.spread_multiplier)
    b_ext, a_ext, m_ext = _scaled_quotes(ladder, exit_idx, scenario.spread_multiplier)
    slip = scenario.slippage_points * point

    if side == "LONG":
        entry_fill = a_ent + slip
        exit_fill = b_ext - slip
        gross_pts = (m_ext - m_ent) / point if point > 0 else (m_ext - m_ent)
        net_pts = (exit_fill - entry_fill) / point if point > 0 else (exit_fill - entry_fill)
    else:
        entry_fill = b_ent - slip
        exit_fill = a_ext + slip
        gross_pts = (m_ent - m_ext) / point if point > 0 else (m_ent - m_ext)
        net_pts = (entry_fill - exit_fill) / point if point > 0 else (entry_fill - exit_fill)

    return entry_fill, exit_fill, gross_pts, net_pts, float(slip / point if point > 0 else slip)
