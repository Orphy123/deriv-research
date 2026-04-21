from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from synthetic_spike.config import load_config
from synthetic_spike.fills import latency_adjusted_index
from synthetic_spike.simulator import _find_adverse_exit_idx, run_backtest
from synthetic_spike.state_machine import build_entry_candidates
from synthetic_spike.triggers import detect_opposite_triggers


def _ts(minutes: int) -> pd.Timestamp:
    return pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(minutes=minutes)


class CoreBehaviorTests(unittest.TestCase):
    def test_trigger_detection_boom_and_crash(self) -> None:
        boom_ticks = pd.DataFrame(
            {"time_utc": [_ts(0), _ts(1), _ts(2)], "bid": [100.0, 99.5, 99.4], "ask": [100.1, 99.6, 99.5]}
        )
        crash_ticks = pd.DataFrame(
            {"time_utc": [_ts(0), _ts(1), _ts(2)], "bid": [100.0, 100.3, 100.1], "ask": [100.1, 100.4, 100.2]}
        )

        boom = detect_opposite_triggers("Boom 1000 Index", boom_ticks, point=0.1, threshold_points=2)
        crash = detect_opposite_triggers("Crash 1000 Index", crash_ticks, point=0.1, threshold_points=2)
        self.assertEqual(len(boom), 1)
        self.assertEqual(boom[0].trigger_idx, 1)
        self.assertEqual(len(crash), 1)
        self.assertEqual(crash[0].trigger_idx, 1)

    def test_watch_resets_on_second_trigger(self) -> None:
        rows = []
        bids = []
        cur = 100.0
        for m in range(0, 21):
            if m == 1:
                cur -= 1.0  # trigger #1
            elif m == 2:
                cur -= 1.0  # trigger #2 (resets watch)
            bids.append(cur)
            rows.append(_ts(m))
        ticks = pd.DataFrame({"time_utc": rows, "bid": bids, "ask": [b + 0.1 for b in bids]})

        triggers = detect_opposite_triggers("Boom 1000 Index", ticks, point=1.0, threshold_points=0.5)
        entries = build_entry_candidates(
            symbol="Boom 1000 Index",
            ticks=ticks,
            triggers=triggers,
            watch_minutes=10,
            entry_offset_ticks=0,
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(pd.Timestamp(entries[0].entry_time), _ts(12))

    def test_adverse_exit_detection(self) -> None:
        bid = pd.Series([10.0, 10.1, 10.2, 10.19, 10.3]).to_numpy()
        ask = pd.Series([10.1, 10.2, 10.3, 10.29, 10.4]).to_numpy()
        idx_long = _find_adverse_exit_idx("LONG", bid=bid, ask=ask, start_idx=3, end_idx=4)
        self.assertEqual(idx_long, 3)

        bid_s = pd.Series([10.0, 9.9, 9.8, 9.85]).to_numpy()
        ask_s = pd.Series([10.1, 10.0, 9.9, 9.95]).to_numpy()
        idx_short = _find_adverse_exit_idx("SHORT", bid=bid_s, ask=ask_s, start_idx=3, end_idx=3)
        self.assertEqual(idx_short, 3)

    def test_latency_index(self) -> None:
        t_ns = pd.Series([0, 1_000_000_000, 2_000_000_000], dtype="int64").to_numpy()
        self.assertEqual(latency_adjusted_index(t_ns, 0, 0), 0)
        self.assertEqual(latency_adjusted_index(t_ns, 0, 1500), 2)

    def test_integration_timeout_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sym_dir = root / "data" / "ticks" / "Boom_1000_Index"
            sym_dir.mkdir(parents=True, exist_ok=True)

            times = [_ts(i) for i in range(0, 40)]
            bids = []
            cur = 100.0
            for i in range(0, 40):
                if i == 1:
                    cur -= 1.0  # opposite trigger
                else:
                    cur += 0.05  # monotonic rise -> no adverse tick for long
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

            manifest = {
                "symbol": "Boom 1000 Index",
                "info": {"point": 1.0},
                "chunks": [],
            }
            with open(sym_dir / "_index.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            cfg_yaml = root / "cfg.yaml"
            cfg_yaml.write_text(
                "\n".join(
                    [
                        "project:",
                        "  name: test",
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
                        "  spread_multiplier: 1.0",
                        "  slippage_multiplier: 1.0",
                        "sweep:",
                        "  trigger_opposite_threshold_points: [0.5]",
                        "  watch_minutes: [10]",
                        "  max_hold_minutes: [15]",
                        "  entry_offset_ticks: [0]",
                        "feasibility_gates:",
                        "  min_trades_required: 1",
                        "  min_baseline_expectancy_points: 0",
                        "  min_stress_expectancy_points: 0",
                        "  min_positive_month_ratio: 0",
                        "  max_month_pnl_share: 1",
                        "output:",
                        f"  out_dir: \"{(root / 'out').as_posix()}\"",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = load_config(cfg_yaml)
            trades, _ = run_backtest(cfg)
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades.iloc[0]["exit_reason"], "timeout")


if __name__ == "__main__":
    unittest.main()
