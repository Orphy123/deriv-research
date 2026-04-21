from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from synthetic_spike.config import load_config
from synthetic_spike.simulator import run_backtest
from synthetic_spike.sweeps import run_parameter_sweep


def _base_ts(i: int) -> pd.Timestamp:
    return pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(minutes=i)


def _write_fixture(root: Path) -> Path:
    sym_dir = root / "data" / "ticks" / "Boom_1000_Index"
    sym_dir.mkdir(parents=True, exist_ok=True)
    times = [_base_ts(i) for i in range(0, 120)]
    bids = []
    cur = 100.0
    for i in range(0, 120):
        if i in {10, 40, 70}:
            cur -= 1.2
        else:
            cur += 0.03
        bids.append(cur)
    asks = [b + 0.1 for b in bids]
    ticks = pd.DataFrame(
        {
            "time_utc": times,
            "time_msc": [int(t.value / 1_000_000) for t in times],
            "bid": bids,
            "ask": asks,
        }
    )
    ticks.to_parquet(sym_dir / "Boom_1000_Index_20260101_20260102.parquet", index=False)
    with open(sym_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump({"symbol": "Boom 1000 Index", "info": {"point": 1.0}, "chunks": []}, f)

    cfg_path = root / "cfg.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: reg",
                "  version: '1.0'",
                "data:",
                f"  data_root: \"{(root / 'data').as_posix()}\"",
                "  symbols: ['Boom 1000 Index']",
                "strategy:",
                "  trigger_opposite_threshold_points: 0.5",
                "  watch_minutes: 10",
                "  max_hold_minutes: 15",
                "  entry_offset_ticks: 0",
                "  adverse_exit_mode: first_adverse_tick",
                "  direction_by_symbol:",
                "    Boom 1000 Index: LONG",
                "execution:",
                "  fallback_spread_points: 1.0",
                "  slippage_points: 0.0",
                "  latency_ms: 0",
                "stress:",
                "  spread_multiplier: 1.2",
                "  slippage_multiplier: 2.0",
                "sweep:",
                "  trigger_opposite_threshold_points: [0.5, 1.0]",
                "  watch_minutes: [10]",
                "  max_hold_minutes: [15]",
                "  entry_offset_ticks: [0, 1]",
                "feasibility_gates:",
                "  min_trades_required: 1",
                "  min_baseline_expectancy_points: 0",
                "  min_stress_expectancy_points: -1000",
                "  min_positive_month_ratio: 0",
                "  max_month_pnl_share: 1",
                "output:",
                f"  out_dir: \"{(root / 'out').as_posix()}\"",
            ]
        ),
        encoding="utf-8",
    )
    return cfg_path


class RegressionTests(unittest.TestCase):
    def test_backtest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(_write_fixture(Path(td)))
            t1, _ = run_backtest(cfg)
            t2, _ = run_backtest(cfg)
            cols = ["symbol", "side", "trigger_idx", "entry_idx", "exit_idx", "exit_reason"]
            self.assertEqual(t1[cols].to_dict(orient="records"), t2[cols].to_dict(orient="records"))

    def test_sweep_grid_count_and_stability(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(_write_fixture(Path(td)))
            s1 = run_parameter_sweep(cfg).reset_index(drop=True)
            s2 = run_parameter_sweep(cfg).reset_index(drop=True)
            self.assertEqual(len(s1), 4)
            self.assertEqual(s1.to_dict(orient="records"), s2.to_dict(orient="records"))


if __name__ == "__main__":
    unittest.main()
