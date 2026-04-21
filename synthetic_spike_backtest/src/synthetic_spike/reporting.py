from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import AppConfig


def evaluate_feasibility(summary: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    gates = config.gates
    scenarios = summary.get("scenarios", {})
    monthly = summary.get("monthly", {})
    trades = int(summary.get("trades", 0))

    baseline_mean = float(scenarios.get("spread_plus_slippage", {}).get("mean_points", 0.0))
    stress_mean = float(scenarios.get("stress", {}).get("mean_points", 0.0))

    month_rows = monthly.get("spread_plus_slippage", [])
    mdf = pd.DataFrame(month_rows) if month_rows else pd.DataFrame(columns=["entry_month", "total_points"])
    if not mdf.empty:
        total_by_month = pd.to_numeric(mdf["total_points"], errors="coerce").fillna(0.0)
        positive_month_ratio = float((total_by_month > 0).mean())
        denom = float(total_by_month.abs().sum())
        max_month_share = float(total_by_month.abs().max() / denom) if denom > 0 else 1.0
    else:
        positive_month_ratio = 0.0
        max_month_share = 1.0

    checks = {
        "trade_count_ok": trades >= gates.min_trades_required,
        "baseline_expectancy_ok": baseline_mean >= gates.min_baseline_expectancy_points,
        "stress_expectancy_ok": stress_mean >= gates.min_stress_expectancy_points,
        "positive_month_ratio_ok": positive_month_ratio >= gates.min_positive_month_ratio,
        "month_concentration_ok": max_month_share <= gates.max_month_pnl_share,
    }

    if not checks["trade_count_ok"]:
        decision = "inconclusive"
    elif all(checks.values()):
        decision = "proceed_to_demo_bot"
    else:
        decision = "stop_and_revise"

    return {
        "decision": decision,
        "checks": checks,
        "observed": {
            "trades": trades,
            "baseline_mean_points": baseline_mean,
            "stress_mean_points": stress_mean,
            "positive_month_ratio": positive_month_ratio,
            "max_month_pnl_share": max_month_share,
        },
        "thresholds": {
            "min_trades_required": gates.min_trades_required,
            "min_baseline_expectancy_points": gates.min_baseline_expectancy_points,
            "min_stress_expectancy_points": gates.min_stress_expectancy_points,
            "min_positive_month_ratio": gates.min_positive_month_ratio,
            "max_month_pnl_share": gates.max_month_pnl_share,
        },
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def write_feasibility_markdown(path: Path, result: dict[str, Any], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    obs = result["observed"]
    checks = result["checks"]
    thresholds = result["thresholds"]
    lines = [
        "# Feasibility Report",
        "",
        f"Decision: **{result['decision']}**",
        "",
        "## Observed",
        "",
        f"- Trades: {obs['trades']}",
        f"- Baseline mean points (`spread_plus_slippage`): {obs['baseline_mean_points']:.2f}",
        f"- Stress mean points: {obs['stress_mean_points']:.2f}",
        f"- Positive month ratio: {obs['positive_month_ratio']:.2%}",
        f"- Max month PnL share: {obs['max_month_pnl_share']:.2%}",
        "",
        "## Gate Checks",
        "",
    ]
    for k, v in checks.items():
        lines.append(f"- {k}: {'PASS' if v else 'FAIL'}")

    lines.extend(["", "## Thresholds", ""])
    for k, v in thresholds.items():
        lines.append(f"- {k}: {v}")

    sc = summary.get("scenarios", {})
    lines.extend(["", "## Scenario Summary", ""])
    for name, row in sc.items():
        lines.append(
            f"- {name}: trades={row['trades']} | mean={row['mean_points']:.2f} pts | "
            f"median={row['median_points']:.2f} | win_rate={row['win_rate']:.2%} | total={row['total_points']:.2f}"
        )

    by_symbol = summary.get("by_symbol", {}).get("spread_plus_slippage", [])
    if by_symbol:
        lines.extend(["", "## Baseline By Symbol", ""])
        for row in by_symbol:
            lines.append(
                f"- {row['symbol']}: trades={int(row['trades'])} | "
                f"mean={float(row['mean_points']):.2f} | "
                f"median={float(row['median_points']):.2f} | "
                f"total={float(row['total_points']):.2f}"
            )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
