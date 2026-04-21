from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

from .types import TriggerEvent


@dataclass(frozen=True)
class EntryCandidate:
    symbol: str
    trigger_idx: int
    trigger_time: datetime
    entry_idx: int
    entry_time: datetime


def build_entry_candidates(
    symbol: str,
    ticks: pd.DataFrame,
    triggers: Iterable[TriggerEvent],
    watch_minutes: int,
    entry_offset_ticks: int = 0,
) -> list[EntryCandidate]:
    if ticks.empty:
        return []

    trigger_list = sorted(triggers, key=lambda x: x.trigger_idx)
    if not trigger_list:
        return []

    t_ns = (
        pd.to_datetime(ticks["time_utc"], utc=True)
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .to_numpy(dtype="datetime64[ns]")
        .astype("int64")
    )
    watch_ns = int(pd.Timedelta(minutes=watch_minutes).value)

    out: list[EntryCandidate] = []
    for i, trig in enumerate(trigger_list):
        trig_ns = int(t_ns[trig.trigger_idx])
        window_end_ns = trig_ns + watch_ns
        next_ns = int(t_ns[trigger_list[i + 1].trigger_idx]) if i + 1 < len(trigger_list) else 2**63 - 1

        # If another opposite trigger appears before watch completes, reset/skip.
        if next_ns <= window_end_ns:
            continue

        base_idx = int(np.searchsorted(t_ns, window_end_ns, side="left"))
        if base_idx >= len(t_ns):
            continue
        entry_idx = min(base_idx + max(0, entry_offset_ticks), len(t_ns) - 1)
        if entry_idx <= trig.trigger_idx:
            continue

        out.append(
            EntryCandidate(
                symbol=symbol,
                trigger_idx=trig.trigger_idx,
                trigger_time=trig.trigger_time,
                entry_idx=entry_idx,
                entry_time=pd.Timestamp(t_ns[entry_idx], tz="UTC").to_pydatetime(),
            )
        )
    return out
