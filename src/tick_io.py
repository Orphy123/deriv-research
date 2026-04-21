"""
tick_io.py — Load and concatenate tick parquet chunks produced by
scripts/pull_history.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


def safe_symbol_dir(symbol: str) -> str:
    return symbol.replace(" ", "_").replace("/", "_").replace("\\", "_")


def load_symbol_ticks(
    symbol: str,
    data_root: str | Path | None = None,
    date_from: pd.Timestamp | None = None,
    date_to: pd.Timestamp | None = None,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Load all tick chunks for a symbol into a single DataFrame sorted by time.

    Optional date_from / date_to filter (inclusive) using the `time_utc` column.
    """
    if data_root is None:
        data_root = REPO_ROOT / "data"
    else:
        data_root = Path(data_root)
    sym_dir = data_root / "ticks" / safe_symbol_dir(symbol)
    if not sym_dir.exists():
        raise FileNotFoundError(f"No tick data dir: {sym_dir}")

    parts = sorted(sym_dir.glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No parquet chunks in {sym_dir}")

    frames = []
    for p in parts:
        df = pd.read_parquet(p, columns=list(columns) if columns else None)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    if "time_utc" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
        df = df.sort_values("time_utc").reset_index(drop=True)
        if date_from is not None:
            df = df[df["time_utc"] >= pd.Timestamp(date_from, tz="UTC")]
        if date_to is not None:
            df = df[df["time_utc"] <= pd.Timestamp(date_to, tz="UTC")]
        df = df.drop_duplicates(subset=["time_msc"] if "time_msc" in df.columns else ["time_utc"])
        df = df.reset_index(drop=True)
    return df


def load_manifest(symbol: str, data_root: str | Path | None = None) -> dict:
    if data_root is None:
        data_root = REPO_ROOT / "data"
    else:
        data_root = Path(data_root)
    sym_dir = data_root / "ticks" / safe_symbol_dir(symbol)
    idx_path = sym_dir / "_index.json"
    if not idx_path.exists():
        raise FileNotFoundError(idx_path)
    with open(idx_path, "r", encoding="utf-8") as f:
        return json.load(f)
