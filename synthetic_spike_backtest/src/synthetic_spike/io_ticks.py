from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd


def safe_symbol_dir(symbol: str) -> str:
    return symbol.replace(" ", "_").replace("/", "_").replace("\\", "_")


def load_manifest(symbol: str, data_root: str | Path) -> dict:
    base = Path(data_root)
    idx_path = base / "ticks" / safe_symbol_dir(symbol) / "_index.json"
    if not idx_path.exists():
        raise FileNotFoundError(idx_path)
    with open(idx_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_symbol_ticks(
    symbol: str,
    data_root: str | Path,
    columns: Iterable[str] | None = None,
    date_from: pd.Timestamp | None = None,
    date_to: pd.Timestamp | None = None,
) -> pd.DataFrame:
    base = Path(data_root)
    sym_dir = base / "ticks" / safe_symbol_dir(symbol)
    if not sym_dir.exists():
        raise FileNotFoundError(f"No tick data dir: {sym_dir}")

    parts = sorted(sym_dir.glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No parquet chunks in {sym_dir}")

    frames: list[pd.DataFrame] = []
    read_cols = list(columns) if columns else None
    for p in parts:
        frames.append(pd.read_parquet(p, columns=read_cols))

    df = pd.concat(frames, ignore_index=True)
    if "time_utc" in df.columns:
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
        df = df.sort_values("time_utc").reset_index(drop=True)
        if date_from is not None:
            df = df[df["time_utc"] >= pd.Timestamp(date_from, tz="UTC")]
        if date_to is not None:
            df = df[df["time_utc"] <= pd.Timestamp(date_to, tz="UTC")]
        key = ["time_msc"] if "time_msc" in df.columns else ["time_utc"]
        df = df.drop_duplicates(subset=key).reset_index(drop=True)

    needed = {"time_utc", "bid"}
    missing = needed.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns {missing} for {symbol}")

    if "ask" not in df.columns:
        df["ask"] = pd.NA
    # Keep memory footprint lower on large tick datasets.
    df["bid"] = pd.to_numeric(df["bid"], errors="coerce").astype("float32")
    df["ask"] = pd.to_numeric(df["ask"], errors="coerce").astype("float32")
    return df


def build_m5_bars(ticks: pd.DataFrame, price_col: str = "bid") -> pd.DataFrame:
    if ticks.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    bars = (
        ticks.set_index("time_utc")[price_col]
        .astype(float)
        .resample("5min")
        .ohlc()
        .dropna()
    )
    return bars
