"""
pull_history.py — Chunked historical tick download for Deriv synthetic indices.

The MT5 Python bridge returns IPC recv failed (-10002) when a single
copy_ticks_range call asks for more ticks than the IPC buffer can hold.
Empirically, 30d / ~2.5M ticks works; 90d fails immediately. This script
chunks requests into small windows, retries on transient failure, and
concatenates the results into a single parquet file per symbol.

Run:
    python -m scripts.pull_history --symbol "Boom 1000 Index" --days 180
    python -m scripts.pull_history --symbol "Crash 1000 Index" --days 180
    python -m scripts.pull_history --days 7   # both symbols, 7 days

Output:
    data/ticks/<symbol>/<symbol>_YYYYMMDD_YYYYMMDD.parquet   (one per chunk)
    data/ticks/<symbol>/_index.json                          (chunk manifest)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config_loader import load_accounts, load_config
from src.logger import Logger
from src.mt5_client import MT5Client


def _safe_symbol_dir(symbol: str) -> str:
    return symbol.replace(" ", "_").replace("/", "_").replace("\\", "_")


def pull_chunk(
    client: MT5Client,
    symbol: str,
    chunk_from: datetime,
    chunk_to: datetime,
    out_dir: Path,
    log: Logger,
    max_retries: int = 3,
) -> dict:
    """Pull one chunk. Returns {path, rows, from, to, error}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp_from = chunk_from.strftime("%Y%m%d")
    stamp_to = chunk_to.strftime("%Y%m%d")
    fname = out_dir / f"{_safe_symbol_dir(symbol)}_{stamp_from}_{stamp_to}.parquet"

    if fname.exists():
        try:
            existing = pd.read_parquet(fname)
            return {
                "path": str(fname),
                "rows": int(len(existing)),
                "from": chunk_from.isoformat(),
                "to": chunk_to.isoformat(),
                "cached": True,
            }
        except Exception:
            pass

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            df = client.copy_ticks_range(symbol, chunk_from, chunk_to)
            if df.empty:
                code, msg = client.last_error()
                last_err = f"({code}) {msg}"
                log.warning(f"[{symbol}] chunk {stamp_from}->{stamp_to} attempt {attempt}: {last_err}")
                time.sleep(1.5 * attempt)
                continue
            df.to_parquet(fname, index=False)
            return {
                "path": str(fname),
                "rows": int(len(df)),
                "from": chunk_from.isoformat(),
                "to": chunk_to.isoformat(),
                "actual_from": str(df["time_utc"].min()),
                "actual_to": str(df["time_utc"].max()),
            }
        except Exception as e:
            last_err = str(e)
            log.warning(f"[{symbol}] chunk {stamp_from}->{stamp_to} exception attempt {attempt}: {e}")
            time.sleep(1.5 * attempt)

    return {
        "path": str(fname),
        "rows": 0,
        "from": chunk_from.isoformat(),
        "to": chunk_to.isoformat(),
        "error": last_err or "unknown",
    }


def pull_symbol(
    client: MT5Client,
    symbol: str,
    total_days: int,
    chunk_days: int,
    data_root: Path,
    log: Logger,
) -> dict:
    symbol_dir = data_root / "ticks" / _safe_symbol_dir(symbol)
    symbol_dir.mkdir(parents=True, exist_ok=True)

    if not client.ensure_selected(symbol):
        log.error(f"[{symbol}] could not enable in Market Watch")
        return {"symbol": symbol, "error": "symbol_select failed"}

    info = client.symbol_info(symbol)
    log.info(
        f"[{symbol}] info: point={info.get('point')} tick_value={info.get('tick_value')} "
        f"contract_size={info.get('contract_size')} volume_min={info.get('volume_min')}"
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    start_total = now - timedelta(days=total_days)
    cursor = start_total
    chunks = []
    total_rows = 0

    chunk_delta = timedelta(days=chunk_days)
    while cursor < now:
        chunk_end = min(cursor + chunk_delta, now)
        log.info(
            f"[{symbol}] pulling {cursor.isoformat()} -> {chunk_end.isoformat()} "
            f"({(chunk_end - cursor).total_seconds() / 3600:.1f}h)"
        )
        res = pull_chunk(client, symbol, cursor, chunk_end, symbol_dir, log)
        chunks.append(res)
        total_rows += res["rows"]
        if res.get("error"):
            log.warning(f"[{symbol}] chunk failed, continuing: {res.get('error')}")
        else:
            cached = " (cached)" if res.get("cached") else ""
            log.info(f"[{symbol}]   -> {res['rows']:,} rows{cached}")
        cursor = chunk_end

    index_path = symbol_dir / "_index.json"
    manifest = {
        "symbol": symbol,
        "info": info,
        "total_days_requested": total_days,
        "chunk_days": chunk_days,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": total_rows,
        "chunks": chunks,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    log.info(f"[{symbol}] manifest written: {index_path} | total_rows={total_rows:,}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbol",
        help="Exact broker symbol. If omitted, pulls both Boom 1000 and Crash 1000.",
    )
    parser.add_argument("--days", type=int, default=180, help="Days of history to pull")
    parser.add_argument("--chunk-days", type=int, default=7, help="Chunk size in days")
    args = parser.parse_args()

    logs_dir = str(REPO_ROOT / "logs")
    log = Logger("pull_history", logs_dir, level="INFO", print_to_console=True)

    accounts = load_accounts()
    config = load_config()
    deriv = accounts["deriv"]
    client = MT5Client(
        account=deriv["mt5_account"],
        password=deriv["mt5_password"],
        server=deriv["mt5_server"],
        path=deriv.get("mt5_path"),
        logger=log,
    )

    if not client.connect():
        log.error("MT5 connection failed")
        return 1

    data_root = REPO_ROOT / "data"
    results = {}
    try:
        if args.symbol:
            targets = [args.symbol]
        else:
            boom = client.symbols_matching(config["symbols"]["boom_candidates"])
            crash = client.symbols_matching(config["symbols"]["crash_candidates"])
            targets = []
            if boom:
                targets.append(boom[0])
            if crash:
                targets.append(crash[0])
            log.info(f"Resolved targets: {targets}")

        for sym in targets:
            results[sym] = pull_symbol(
                client, sym, args.days, args.chunk_days, data_root, log
            )

    finally:
        client.disconnect()
        summary_path = data_root / "pull_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        log.info(f"Summary written: {summary_path}")
        log.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
