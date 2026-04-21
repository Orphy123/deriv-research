from __future__ import annotations

from dataclasses import replace
from itertools import product
from typing import Any

import pandas as pd

from .config import AppConfig
from .metrics import score_trades, summarize_by_scenario
from .reporting import evaluate_feasibility
from .simulator import SymbolSimulation, load_symbol_data, simulate_entries
from .state_machine import build_entry_candidates
from .triggers import detect_opposite_triggers


def run_parameter_sweep(config: AppConfig) -> pd.DataFrame:
    symbol_data = {sym: load_symbol_data(config, sym) for sym in config.data.symbols}
    trigger_cache: dict[tuple[str, float], list] = {}
    for sym, data in symbol_data.items():
        for threshold in config.sweep.trigger_opposite_threshold_points:
            trigger_cache[(sym, float(threshold))] = detect_opposite_triggers(
                symbol=sym,
                ticks=data.ticks,
                point=data.point,
                threshold_points=float(threshold),
            )

    rows: list[dict[str, Any]] = []
    for threshold, watch, hold, offset in product(
        config.sweep.trigger_opposite_threshold_points,
        config.sweep.watch_minutes,
        config.sweep.max_hold_minutes,
        config.sweep.entry_offset_ticks,
    ):
        strategy = replace(
            config.strategy,
            trigger_opposite_threshold_points=float(threshold),
            watch_minutes=int(watch),
            max_hold_minutes=int(hold),
            entry_offset_ticks=int(offset),
        )
        cfg = replace(config, strategy=strategy)
        sims: dict[str, SymbolSimulation] = {}
        trade_chunks: list[pd.DataFrame] = []
        for sym, data in symbol_data.items():
            triggers = trigger_cache[(sym, float(threshold))]
            entries = build_entry_candidates(
                symbol=sym,
                ticks=data.ticks,
                triggers=triggers,
                watch_minutes=int(watch),
                entry_offset_ticks=int(offset),
            )
            side = cfg.strategy.direction_by_symbol.get(sym, "")
            trades = simulate_entries(
                symbol_data=data,
                entries=entries,
                side=side,
                max_hold_minutes=int(hold),
                latency_ms=cfg.execution.latency_ms,
            )
            sims[sym] = SymbolSimulation(symbol=sym, point=data.point, trades=trades, ticks=data.ticks)
            if not trades.empty:
                trade_chunks.append(trades)
        trades = pd.concat(trade_chunks, ignore_index=True) if trade_chunks else pd.DataFrame()
        scored = score_trades(trades, sims, cfg)
        summary = summarize_by_scenario(scored, cfg)
        feas = evaluate_feasibility(summary, cfg)
        baseline = summary.get("scenarios", {}).get("spread_plus_slippage", {})
        stress = summary.get("scenarios", {}).get("stress", {})
        rows.append(
            {
                "threshold_points": threshold,
                "watch_minutes": watch,
                "max_hold_minutes": hold,
                "entry_offset_ticks": offset,
                "trades": int(summary.get("trades", 0)),
                "baseline_mean_points": float(baseline.get("mean_points", 0.0)),
                "baseline_win_rate": float(baseline.get("win_rate", 0.0)),
                "stress_mean_points": float(stress.get("mean_points", 0.0)),
                "decision": feas["decision"],
            }
        )
    return pd.DataFrame(rows).sort_values(
        by=["decision", "baseline_mean_points", "trades"],
        ascending=[True, False, False],
    )
