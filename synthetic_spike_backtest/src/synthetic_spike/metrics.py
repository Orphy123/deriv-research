from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import AppConfig
from .fills import CostScenario, build_price_ladder, fill_prices_for_trade
from .simulator import SymbolSimulation
from .types import ScenarioResult


def _scenario_list(config: AppConfig) -> list[CostScenario]:
    return [
        CostScenario(name="spread_only", spread_multiplier=1.0, slippage_points=0.0),
        CostScenario(
            name="spread_plus_slippage",
            spread_multiplier=1.0,
            slippage_points=config.execution.slippage_points,
        ),
        CostScenario(
            name="stress",
            spread_multiplier=config.stress.spread_multiplier,
            slippage_points=config.execution.slippage_points * config.stress.slippage_multiplier,
        ),
    ]


def score_trades(
    trades: pd.DataFrame,
    sims: dict[str, SymbolSimulation],
    config: AppConfig,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()

    out = trades.copy()
    out["gross_points"] = np.nan
    for s in _scenario_list(config):
        out[f"net_points_{s.name}"] = np.nan
        out[f"entry_fill_{s.name}"] = np.nan
        out[f"exit_fill_{s.name}"] = np.nan

    ladders = {}
    for symbol, sim in sims.items():
        ladders[symbol] = build_price_ladder(
            ticks=sim.ticks,
            fallback_spread_points=config.execution.fallback_spread_points,
            point=sim.point,
        )

    for idx, row in out.iterrows():
        symbol = str(row["symbol"])
        entry_idx = int(row["entry_idx"])
        exit_idx = int(row["exit_idx"])
        side = str(row["side"])
        point = float(row["point"])
        ladder = ladders[symbol]

        # Gross from mid-to-mid.
        _, _, gross_pts, _, _ = fill_prices_for_trade(
            side=side,
            entry_idx=entry_idx,
            exit_idx=exit_idx,
            ladder=ladder,
            point=point,
            scenario=CostScenario(name="gross_proxy", spread_multiplier=0.0, slippage_points=0.0),
        )
        out.at[idx, "gross_points"] = gross_pts

        for s in _scenario_list(config):
            entry_fill, exit_fill, _, net_pts, _ = fill_prices_for_trade(
                side=side,
                entry_idx=entry_idx,
                exit_idx=exit_idx,
                ladder=ladder,
                point=point,
                scenario=s,
            )
            out.at[idx, f"net_points_{s.name}"] = net_pts
            out.at[idx, f"entry_fill_{s.name}"] = entry_fill
            out.at[idx, f"exit_fill_{s.name}"] = exit_fill
    return out


def summarize_by_scenario(scored_trades: pd.DataFrame, config: AppConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if scored_trades.empty:
        out["trades"] = 0
        out["scenarios"] = {}
        out["monthly"] = {}
        out["monthly_by_symbol"] = {}
        out["by_symbol"] = {}
        return out

    scenarios = ["gross"] + [s.name for s in _scenario_list(config)]
    metrics: dict[str, Any] = {}
    for s in scenarios:
        col = "gross_points" if s == "gross" else f"net_points_{s}"
        arr = scored_trades[col].astype(float).to_numpy()
        trades = int(len(arr))
        win_rate = float((arr > 0).mean()) if trades else 0.0
        result = ScenarioResult(
            name=s,
            trades=trades,
            win_rate=win_rate,
            mean_points=float(np.mean(arr)) if trades else 0.0,
            median_points=float(np.median(arr)) if trades else 0.0,
            total_points=float(np.sum(arr)) if trades else 0.0,
        )
        metrics[s] = asdict(result)

    df = scored_trades.copy()
    df["entry_month"] = pd.to_datetime(df["entry_time"], utc=True).dt.strftime("%Y-%m")
    monthly: dict[str, Any] = {}
    monthly_by_symbol: dict[str, Any] = {}
    for s in scenarios:
        col = "gross_points" if s == "gross" else f"net_points_{s}"
        by_m = (
            df.groupby("entry_month")[col]
            .agg(["count", "mean", "sum"])
            .rename(columns={"count": "trades", "mean": "mean_points", "sum": "total_points"})
        )
        monthly[s] = by_m.reset_index().to_dict(orient="records")
        by_sm = (
            df.groupby(["symbol", "entry_month"])[col]
            .agg(["count", "mean", "sum"])
            .rename(columns={"count": "trades", "mean": "mean_points", "sum": "total_points"})
            .reset_index()
        )
        monthly_by_symbol[s] = by_sm.to_dict(orient="records")

    by_symbol: dict[str, Any] = {}
    for s in scenarios:
        col = "gross_points" if s == "gross" else f"net_points_{s}"
        rows = (
            df.groupby("symbol")[col]
            .agg(["count", "mean", "median", "sum"])
            .rename(
                columns={
                    "count": "trades",
                    "mean": "mean_points",
                    "median": "median_points",
                    "sum": "total_points",
                }
            )
            .reset_index()
            .to_dict(orient="records")
        )
        by_symbol[s] = rows

    out["trades"] = int(len(scored_trades))
    out["scenarios"] = metrics
    out["monthly"] = monthly
    out["monthly_by_symbol"] = monthly_by_symbol
    out["by_symbol"] = by_symbol
    return out
