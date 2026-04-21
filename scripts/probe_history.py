"""
probe_history.py — How much Boom 1000 / Crash 1000 tick history does
Deriv-Demo actually expose via MT5?

Run:
    cd C:\\Users\\Administrator\\Desktop\\deriv-research
    .\\venv\\Scripts\\Activate.ps1
    python -m scripts.probe_history

Outputs:
    - Console log
    - logs/probe_YYYYMMDD.log
    - data/probe_summary.json     (machine-readable results)
    - data/probe_ticks_<symbol>_<window>d.parquet  (sample dumps)

Decisions this script informs:
    1. Which exact symbol strings to use for Boom 1000 / Crash 1000.
    2. Whether we can backtest from existing history, or must log forward.
    3. The point value and tick_value we need for accurate P&L simulation.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config_loader import load_accounts, load_config
from src.logger import Logger
from src.mt5_client import MT5Client


def resolve_symbol(client: MT5Client, candidates: list[str], log: Logger) -> str | None:
    """Find the exact broker string for a candidate family (Boom/Crash)."""
    matches = client.symbols_matching(candidates)
    if not matches:
        log.warning(f"No symbols matched any of {candidates}")
        return None
    log.info(f"Candidates {candidates} matched: {matches}")
    for c in candidates:
        if c in matches:
            return c
    boom_crash_1000 = [m for m in matches if "1000" in m]
    if boom_crash_1000:
        return boom_crash_1000[0]
    return matches[0]


def probe_window(
    client: MT5Client,
    symbol: str,
    days_back: int,
    log: Logger,
) -> dict:
    """Probe a single window. Returns summary dict."""
    now = datetime.now(timezone.utc)
    date_from = now - timedelta(days=days_back)
    date_to = now

    log.info(f"[{symbol}] Probing {days_back}d window: {date_from.isoformat()} -> {date_to.isoformat()}")

    df = client.copy_ticks_range(symbol, date_from, date_to)
    result: dict = {
        "symbol": symbol,
        "window_days_requested": days_back,
        "requested_from": date_from.isoformat(),
        "requested_to": date_to.isoformat(),
        "rows": int(len(df)),
    }

    if df.empty:
        err_code, err_msg = client.last_error()
        result["error_code"] = err_code
        result["error_msg"] = err_msg
        log.warning(f"[{symbol}] {days_back}d: empty. last_error=({err_code}, {err_msg})")
        return result

    actual_from = df["time_utc"].min()
    actual_to = df["time_utc"].max()
    result["actual_from"] = actual_from.isoformat()
    result["actual_to"] = actual_to.isoformat()
    result["actual_span_hours"] = float((actual_to - actual_from).total_seconds() / 3600.0)

    price = df.get("bid")
    if price is None or price.isna().all():
        price = df.get("last")
    if price is not None and not price.isna().all():
        price = price.astype(float)
        dp = price.diff().dropna()
        dp_abs = dp.abs()
        sym_info = client.symbol_info(symbol)
        point = sym_info.get("point", 0.01) if sym_info else 0.01
        result["point"] = point
        result["tick_value"] = sym_info.get("tick_value") if sym_info else None
        result["contract_size"] = sym_info.get("contract_size") if sym_info else None
        result["volume_min"] = sym_info.get("volume_min") if sym_info else None
        result["volume_step"] = sym_info.get("volume_step") if sym_info else None

        dp_pts = dp_abs / point if point > 0 else dp_abs
        result["price_min"] = float(price.min())
        result["price_max"] = float(price.max())
        result["delta_pts_mean"] = float(dp_pts.mean())
        result["delta_pts_median"] = float(dp_pts.median())
        result["delta_pts_p95"] = float(dp_pts.quantile(0.95))
        result["delta_pts_p99"] = float(dp_pts.quantile(0.99))
        result["delta_pts_p999"] = float(dp_pts.quantile(0.999))
        result["delta_pts_max"] = float(dp_pts.max())

        for thr in (10_000, 20_000, 30_000, 50_000, 80_000):
            result[f"spikes_ge_{thr}"] = int((dp_pts >= thr).sum())

    if "time_msc" in df.columns:
        ts = df["time_msc"].astype("int64")
        gaps_ms = ts.diff().dropna()
        result["tick_interval_ms_median"] = float(gaps_ms.median())
        result["tick_interval_ms_mean"] = float(gaps_ms.mean())
        result["tick_interval_ms_p95"] = float(gaps_ms.quantile(0.95))
        result["tick_interval_ms_p99"] = float(gaps_ms.quantile(0.99))
        result["tick_interval_ms_max"] = float(gaps_ms.max())

    if "bid" in df.columns and "ask" in df.columns:
        sp = (df["ask"].astype(float) - df["bid"].astype(float))
        sym_info = client.symbol_info(symbol)
        point = sym_info.get("point", 0.01) if sym_info else 0.01
        sp_pts = sp / point if point > 0 else sp
        result["spread_pts_median"] = float(sp_pts.median())
        result["spread_pts_mean"] = float(sp_pts.mean())
        result["spread_pts_p95"] = float(sp_pts.quantile(0.95))

    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fname = data_dir / f"probe_ticks_{symbol.replace(' ', '_')}_{days_back}d.parquet"
    try:
        df.to_parquet(fname, index=False)
        result["sample_path"] = str(fname)
        log.info(f"[{symbol}] {days_back}d: {len(df):,} rows written to {fname.name}")
    except Exception as e:
        log.warning(f"[{symbol}] {days_back}d: failed to write parquet: {e}")

    return result


def summarize(result: dict) -> str:
    s = [
        f"  window={result['window_days_requested']}d | rows={result['rows']:,}",
    ]
    if result["rows"] > 0:
        s.append(
            f"  actual range: {result.get('actual_from', '?')} -> "
            f"{result.get('actual_to', '?')}  "
            f"({result.get('actual_span_hours', 0):.1f} hours)"
        )
        if "delta_pts_max" in result:
            s.append(
                f"  delta points: median={result['delta_pts_median']:.1f} "
                f"p95={result['delta_pts_p95']:.1f} "
                f"p99={result['delta_pts_p99']:.1f} "
                f"max={result['delta_pts_max']:.1f}"
            )
            s.append(
                f"  spikes: >=10k={result.get('spikes_ge_10000', 0)} "
                f">=30k={result.get('spikes_ge_30000', 0)} "
                f">=80k={result.get('spikes_ge_80000', 0)}"
            )
        if "tick_interval_ms_median" in result:
            s.append(
                f"  tick interval ms: median={result['tick_interval_ms_median']:.0f} "
                f"p95={result['tick_interval_ms_p95']:.0f} "
                f"p99={result['tick_interval_ms_p99']:.0f}"
            )
        if "spread_pts_median" in result:
            s.append(
                f"  spread points: median={result['spread_pts_median']:.1f} "
                f"p95={result['spread_pts_p95']:.1f}"
            )
    else:
        if "error_msg" in result:
            s.append(f"  error: ({result.get('error_code')}) {result['error_msg']}")
    return "\n".join(s)


def main() -> int:
    logs_dir = str(REPO_ROOT / "logs")
    log = Logger("probe", logs_dir, level="INFO", print_to_console=True)

    try:
        accounts = load_accounts()
        config = load_config()
    except Exception as e:
        log.error(f"Failed to load config: {e}")
        return 2

    deriv = accounts.get("deriv", {})
    required = ["mt5_account", "mt5_password", "mt5_server"]
    missing = [k for k in required if not deriv.get(k)]
    if missing:
        log.error(f"Missing required fields in accounts.yaml: {missing}")
        return 2

    client = MT5Client(
        account=deriv["mt5_account"],
        password=deriv["mt5_password"],
        server=deriv["mt5_server"],
        path=deriv.get("mt5_path"),
        logger=log,
    )

    if not client.connect():
        log.error("MT5 connection failed. Aborting.")
        return 1

    summary: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "account": client.account_info(),
        "terminal": client.terminal_info(),
        "symbols": {},
    }

    try:
        boom_sym = resolve_symbol(client, config["symbols"]["boom_candidates"], log)
        crash_sym = resolve_symbol(client, config["symbols"]["crash_candidates"], log)
        summary["resolved_boom"] = boom_sym
        summary["resolved_crash"] = crash_sym

        if boom_sym is None and crash_sym is None:
            log.error("Neither Boom nor Crash symbol resolved. Aborting probe.")
            all_syms = client.symbols_matching([""])
            log.info(f"Broker exposes {len(all_syms)} total symbols. First 20: {all_syms[:20]}")
            summary["broker_total_symbols"] = len(all_syms)
            summary["broker_symbol_sample"] = all_syms[:50]
            return 3

        for sym in [s for s in (boom_sym, crash_sym) if s]:
            if not client.ensure_selected(sym):
                log.warning(f"Could not enable {sym} in Market Watch; skipping.")
                continue
            info = client.symbol_info(sym)
            log.info(
                f"[{sym}] symbol_info: point={info.get('point')} digits={info.get('digits')} "
                f"tick_value={info.get('tick_value')} contract_size={info.get('contract_size')} "
                f"volume_min={info.get('volume_min')} volume_step={info.get('volume_step')}"
            )
            summary["symbols"][sym] = {"info": info, "windows": []}

            for days in config.get("probe_windows_days", [1, 7, 30, 90, 180]):
                try:
                    res = probe_window(client, sym, days, log)
                except Exception as e:
                    log.error(f"[{sym}] {days}d probe raised: {e}")
                    res = {
                        "symbol": sym,
                        "window_days_requested": days,
                        "rows": 0,
                        "error_msg": str(e),
                    }
                summary["symbols"][sym]["windows"].append(res)
                log.info("\n" + summarize(res))

    finally:
        client.disconnect()
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        data_dir = REPO_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        summary_path = data_dir / "probe_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        log.info(f"Wrote summary: {summary_path}")
        log.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
