from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import AppConfig
from .fills import PriceLadder, build_price_ladder, latency_adjusted_index
from .io_ticks import load_manifest, load_symbol_ticks
from .state_machine import EntryCandidate, build_entry_candidates
from .triggers import detect_opposite_triggers


@dataclass(frozen=True)
class SymbolSimulation:
    symbol: str
    point: float
    trades: pd.DataFrame
    ticks: pd.DataFrame


@dataclass(frozen=True)
class SymbolData:
    symbol: str
    point: float
    ticks: pd.DataFrame
    ladder: PriceLadder


def _to_dt(time_ns: int) -> pd.Timestamp:
    return pd.Timestamp(time_ns, tz="UTC")


def _find_adverse_exit_idx(
    side: str,
    bid: np.ndarray,
    ask: np.ndarray,
    start_idx: int,
    end_idx: int,
) -> int:
    if start_idx > end_idx or start_idx <= 0:
        return -1
    if side == "LONG":
        segment_now = bid[start_idx : end_idx + 1]
        segment_prev = bid[start_idx - 1 : end_idx]
        hit = np.where(segment_now < segment_prev)[0]
    else:
        segment_now = ask[start_idx : end_idx + 1]
        segment_prev = ask[start_idx - 1 : end_idx]
        hit = np.where(segment_now > segment_prev)[0]
    if len(hit) == 0:
        return -1
    return start_idx + int(hit[0])


def load_symbol_data(config: AppConfig, symbol: str) -> SymbolData:
    manifest = load_manifest(symbol, config.data.data_root)
    point = float(manifest["info"]["point"])
    ticks = load_symbol_ticks(
        symbol=symbol,
        data_root=config.data.data_root,
        columns=["time_utc", "time_msc", "bid", "ask"],
    )
    ladder = build_price_ladder(
        ticks=ticks,
        fallback_spread_points=config.execution.fallback_spread_points,
        point=point,
    )
    return SymbolData(symbol=symbol, point=point, ticks=ticks, ladder=ladder)


def simulate_entries(
    symbol_data: SymbolData,
    entries: list[EntryCandidate],
    side: str,
    max_hold_minutes: int,
    latency_ms: int,
) -> pd.DataFrame:
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"Invalid side for {symbol_data.symbol}: {side}")
    time_ns = symbol_data.ladder.time_ns
    hold_ns = int(pd.Timedelta(minutes=max_hold_minutes).value)
    n_ticks = len(time_ns)
    position_busy_until = -1
    rows: list[dict[str, Any]] = []

    for cand in entries:
        if cand.entry_idx <= position_busy_until:
            continue

        entry_idx = latency_adjusted_index(time_ns, cand.entry_idx, latency_ms)
        if entry_idx >= n_ticks - 1:
            continue

        timeout_target = int(time_ns[entry_idx]) + hold_ns
        timeout_idx = int(np.searchsorted(time_ns, timeout_target, side="left"))
        if timeout_idx >= n_ticks:
            timeout_idx = n_ticks - 1
            timeout_reason = "data_end"
        else:
            timeout_reason = "timeout"

        adverse_idx = _find_adverse_exit_idx(
            side=side,
            bid=symbol_data.ladder.bid,
            ask=symbol_data.ladder.ask,
            start_idx=entry_idx + 1,
            end_idx=timeout_idx,
        )

        if adverse_idx >= 0:
            raw_exit_idx = adverse_idx
            exit_reason = "adverse_tick"
        else:
            raw_exit_idx = timeout_idx
            exit_reason = timeout_reason

        exit_idx = latency_adjusted_index(time_ns, raw_exit_idx, latency_ms)
        if exit_idx <= entry_idx:
            exit_idx = min(entry_idx + 1, n_ticks - 1)
            exit_reason = "latency_miss"

        position_busy_until = exit_idx
        rows.append(
            {
                "symbol": symbol_data.symbol,
                "side": side,
                "trigger_idx": cand.trigger_idx,
                "trigger_time": cand.trigger_time,
                "entry_idx": entry_idx,
                "entry_time": _to_dt(int(time_ns[entry_idx])),
                "exit_idx": exit_idx,
                "exit_time": _to_dt(int(time_ns[exit_idx])),
                "exit_reason": exit_reason,
                "hold_seconds": float((int(time_ns[exit_idx]) - int(time_ns[entry_idx])) / 1e9),
                "point": symbol_data.point,
            }
        )
    return pd.DataFrame(rows)


def simulate_symbol(config: AppConfig, symbol: str) -> SymbolSimulation:
    symbol_data = load_symbol_data(config, symbol)

    triggers = detect_opposite_triggers(
        symbol=symbol,
        ticks=symbol_data.ticks,
        point=symbol_data.point,
        threshold_points=config.strategy.trigger_opposite_threshold_points,
    )
    entries = build_entry_candidates(
        symbol=symbol,
        ticks=symbol_data.ticks,
        triggers=triggers,
        watch_minutes=config.strategy.watch_minutes,
        entry_offset_ticks=config.strategy.entry_offset_ticks,
    )

    side = config.strategy.direction_by_symbol.get(symbol, "")
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"No valid direction mapping for {symbol}: {side}")

    trades = simulate_entries(
        symbol_data=symbol_data,
        entries=entries,
        side=side,
        max_hold_minutes=config.strategy.max_hold_minutes,
        latency_ms=config.execution.latency_ms,
    )
    return SymbolSimulation(
        symbol=symbol_data.symbol,
        point=symbol_data.point,
        trades=trades,
        ticks=symbol_data.ticks,
    )


def run_backtest(config: AppConfig) -> tuple[pd.DataFrame, dict[str, SymbolSimulation]]:
    all_trades: list[pd.DataFrame] = []
    sims: dict[str, SymbolSimulation] = {}
    for symbol in config.data.symbols:
        sim = simulate_symbol(config, symbol)
        sims[symbol] = sim
        if not sim.trades.empty:
            all_trades.append(sim.trades)
    if not all_trades:
        return pd.DataFrame(), sims
    return pd.concat(all_trades, ignore_index=True), sims
