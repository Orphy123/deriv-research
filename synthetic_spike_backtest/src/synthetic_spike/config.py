from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DataConfig:
    data_root: str
    symbols: list[str]


@dataclass(frozen=True)
class StrategyConfig:
    trigger_opposite_threshold_points: float
    watch_minutes: int
    max_hold_minutes: int
    entry_offset_ticks: int
    adverse_exit_mode: str
    direction_by_symbol: dict[str, str]


@dataclass(frozen=True)
class ExecutionConfig:
    fallback_spread_points: float
    slippage_points: float
    latency_ms: int


@dataclass(frozen=True)
class StressConfig:
    spread_multiplier: float
    slippage_multiplier: float


@dataclass(frozen=True)
class SweepConfig:
    trigger_opposite_threshold_points: list[float]
    watch_minutes: list[int]
    max_hold_minutes: list[int]
    entry_offset_ticks: list[int]


@dataclass(frozen=True)
class FeasibilityGates:
    min_trades_required: int
    min_baseline_expectancy_points: float
    min_stress_expectancy_points: float
    min_positive_month_ratio: float
    max_month_pnl_share: float


@dataclass(frozen=True)
class OutputConfig:
    out_dir: str


@dataclass(frozen=True)
class AppConfig:
    project_name: str
    project_version: str
    data: DataConfig
    strategy: StrategyConfig
    execution: ExecutionConfig
    stress: StressConfig
    sweep: SweepConfig
    gates: FeasibilityGates
    output: OutputConfig

    def with_overrides(self, **kwargs: Any) -> "AppConfig":
        fields = self.__dict__.copy()
        fields.update(kwargs)
        return AppConfig(**fields)


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    raw = _read_yaml(p)

    project = raw.get("project", {}) or {}
    data = raw.get("data", {}) or {}
    strategy = raw.get("strategy", {}) or {}
    execution = raw.get("execution", {}) or {}
    stress = raw.get("stress", {}) or {}
    sweep = raw.get("sweep", {}) or {}
    gates = raw.get("feasibility_gates", {}) or {}
    output = raw.get("output", {}) or {}

    return AppConfig(
        project_name=str(project.get("name", "synthetic_spike_backtest")),
        project_version=str(project.get("version", "1.0")),
        data=DataConfig(
            data_root=str(data["data_root"]),
            symbols=list(data["symbols"]),
        ),
        strategy=StrategyConfig(
            trigger_opposite_threshold_points=float(strategy["trigger_opposite_threshold_points"]),
            watch_minutes=int(strategy["watch_minutes"]),
            max_hold_minutes=int(strategy["max_hold_minutes"]),
            entry_offset_ticks=int(strategy.get("entry_offset_ticks", 0)),
            adverse_exit_mode=str(strategy.get("adverse_exit_mode", "first_adverse_tick")),
            direction_by_symbol={str(k): str(v) for k, v in dict(strategy["direction_by_symbol"]).items()},
        ),
        execution=ExecutionConfig(
            fallback_spread_points=float(execution["fallback_spread_points"]),
            slippage_points=float(execution.get("slippage_points", 0.0)),
            latency_ms=int(execution.get("latency_ms", 0)),
        ),
        stress=StressConfig(
            spread_multiplier=float(stress.get("spread_multiplier", 1.0)),
            slippage_multiplier=float(stress.get("slippage_multiplier", 1.0)),
        ),
        sweep=SweepConfig(
            trigger_opposite_threshold_points=[float(x) for x in sweep.get("trigger_opposite_threshold_points", [])],
            watch_minutes=[int(x) for x in sweep.get("watch_minutes", [])],
            max_hold_minutes=[int(x) for x in sweep.get("max_hold_minutes", [])],
            entry_offset_ticks=[int(x) for x in sweep.get("entry_offset_ticks", [])],
        ),
        gates=FeasibilityGates(
            min_trades_required=int(gates.get("min_trades_required", 30)),
            min_baseline_expectancy_points=float(gates.get("min_baseline_expectancy_points", 0.0)),
            min_stress_expectancy_points=float(gates.get("min_stress_expectancy_points", -100.0)),
            min_positive_month_ratio=float(gates.get("min_positive_month_ratio", 0.5)),
            max_month_pnl_share=float(gates.get("max_month_pnl_share", 0.8)),
        ),
        output=OutputConfig(
            out_dir=str(output.get("out_dir", "out")),
        ),
    )
