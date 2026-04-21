from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import AppConfig
from .fills import build_price_ladder, latency_adjusted_index
from .simulator import SymbolSimulation


def _detect_exit(
    side: str,
    bid: np.ndarray,
    ask: np.ndarray,
    time_ns: np.ndarray,
    entry_idx: int,
    max_hold_minutes: int,
) -> tuple[int, str]:
    hold_ns = int(pd.Timedelta(minutes=max_hold_minutes).value)
    timeout_target = int(time_ns[entry_idx]) + hold_ns
    timeout_idx = int(np.searchsorted(time_ns, timeout_target, side="left"))
    if timeout_idx >= len(time_ns):
        timeout_idx = len(time_ns) - 1
        timeout_reason = "data_end"
    else:
        timeout_reason = "timeout"

    if entry_idx + 1 > timeout_idx:
        return timeout_idx, timeout_reason

    if side == "LONG":
        now = bid[entry_idx + 1 : timeout_idx + 1]
        prev = bid[entry_idx:timeout_idx]
        hit = np.where(now < prev)[0]
    else:
        now = ask[entry_idx + 1 : timeout_idx + 1]
        prev = ask[entry_idx:timeout_idx]
        hit = np.where(now > prev)[0]

    if len(hit) > 0:
        return entry_idx + 1 + int(hit[0]), "adverse_tick"
    return timeout_idx, timeout_reason


def manual_replay_sample(
    scored_trades: pd.DataFrame,
    sims: dict[str, SymbolSimulation],
    config: AppConfig,
    sample_size: int = 25,
    seed: int = 42,
) -> pd.DataFrame:
    if scored_trades.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "entry_idx",
                "recorded_exit_idx",
                "expected_exit_idx",
                "recorded_reason",
                "expected_reason",
                "match",
            ]
        )

    sample = (
        scored_trades.sample(n=min(sample_size, len(scored_trades)), random_state=seed)
        .sort_values(["symbol", "entry_idx"])
        .reset_index(drop=True)
    )
    ladders = {
        sym: build_price_ladder(
            ticks=sim.ticks,
            fallback_spread_points=config.execution.fallback_spread_points,
            point=sim.point,
        )
        for sym, sim in sims.items()
    }

    rows: list[dict[str, Any]] = []
    for _, trade in sample.iterrows():
        symbol = str(trade["symbol"])
        side = str(trade["side"])
        entry_idx = int(trade["entry_idx"])
        recorded_exit_idx = int(trade["exit_idx"])
        recorded_reason = str(trade["exit_reason"])
        ladder = ladders[symbol]

        raw_exit_idx, raw_reason = _detect_exit(
            side=side,
            bid=ladder.bid,
            ask=ladder.ask,
            time_ns=ladder.time_ns,
            entry_idx=entry_idx,
            max_hold_minutes=config.strategy.max_hold_minutes,
        )
        expected_exit_idx = latency_adjusted_index(
            ladder.time_ns, raw_exit_idx, config.execution.latency_ms
        )
        expected_reason = (
            "latency_miss"
            if expected_exit_idx <= entry_idx
            else raw_reason
        )

        rows.append(
            {
                "symbol": symbol,
                "entry_idx": entry_idx,
                "recorded_exit_idx": recorded_exit_idx,
                "expected_exit_idx": expected_exit_idx,
                "recorded_reason": recorded_reason,
                "expected_reason": expected_reason,
                "match": bool(
                    recorded_exit_idx == expected_exit_idx
                    and recorded_reason == expected_reason
                ),
            }
        )

    return pd.DataFrame(rows)
