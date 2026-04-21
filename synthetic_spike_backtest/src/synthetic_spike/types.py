from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


TradeSide = Literal["LONG", "SHORT"]
ExitReason = Literal["adverse_tick", "timeout", "data_end", "latency_miss"]
TriggerKind = Literal["opposite_move"]


@dataclass(frozen=True)
class TriggerEvent:
    symbol: str
    trigger_idx: int
    trigger_time: datetime
    trigger_kind: TriggerKind
    delta_points: float


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    side: TradeSide
    trigger_idx: int
    trigger_time: datetime
    entry_idx: int
    entry_time: datetime
    exit_idx: int
    exit_time: datetime
    exit_reason: ExitReason
    hold_seconds: float


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    trades: int
    win_rate: float
    mean_points: float
    median_points: float
    total_points: float
