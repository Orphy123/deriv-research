"""
mt5_client.py — Minimal MT5 wrapper for research.

Adapted (slimmed) from uS30/src/services/mt5_client.py. Scope is
read-only research: connect, list symbols, pull ticks and rates, get
symbol metadata. No order-sending code lives here — this repo does
not trade.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, Optional

import MetaTrader5 as mt5_lib
import numpy as np
import pandas as pd


def _mask_login(login) -> str:
    s = str(login)
    if len(s) <= 4:
        return "****"
    return "*" * (len(s) - 4) + s[-4:]


class MT5Client:
    """Research-only MT5 wrapper. No order methods."""

    COPY_TICKS_ALL = mt5_lib.COPY_TICKS_ALL
    COPY_TICKS_INFO = mt5_lib.COPY_TICKS_INFO
    COPY_TICKS_TRADE = mt5_lib.COPY_TICKS_TRADE

    def __init__(self, account: str, password: str, server: str,
                 path: Optional[str] = None, logger=None):
        self._account = str(account)
        self._password = str(password)
        self._server = str(server)
        self._path = path
        self._log = logger
        self._connected = False

    def _say(self, level: str, msg: str):
        if self._log is None:
            print(f"[{level}] {msg}")
            return
        fn = getattr(self._log, level, None)
        if callable(fn):
            fn(msg)
        else:
            print(f"[{level}] {msg}")

    def connect(self) -> bool:
        kwargs: dict[str, Any] = {}
        if self._path:
            kwargs["path"] = self._path
        if not mt5_lib.initialize(**kwargs):
            err = mt5_lib.last_error()
            self._say("error", f"[MT5] initialize failed: {err}")
            return False

        authorized = mt5_lib.login(
            login=int(self._account),
            password=self._password,
            server=self._server,
        )
        if not authorized:
            err = mt5_lib.last_error()
            self._say("error", f"[MT5] login failed for {_mask_login(self._account)}: {err}")
            mt5_lib.shutdown()
            return False

        self._connected = True
        info = mt5_lib.account_info()
        if info:
            self._say(
                "info",
                f"[MT5] Connected | Account {_mask_login(info.login)} | "
                f"Server {info.server} | Balance ${info.balance:,.2f} | "
                f"Equity ${info.equity:,.2f} | Currency {info.currency}",
            )
        return True

    def disconnect(self):
        if self._connected:
            mt5_lib.shutdown()
            self._connected = False
            self._say("info", "[MT5] Disconnected")

    @contextlib.contextmanager
    def session(self):
        ok = self.connect()
        try:
            if not ok:
                raise RuntimeError("MT5 connection failed")
            yield self
        finally:
            self.disconnect()

    def account_info(self) -> Optional[dict]:
        info = mt5_lib.account_info()
        if info is None:
            return None
        return {
            "login": _mask_login(info.login),
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "currency": info.currency,
            "leverage": info.leverage,
            "margin": info.margin,
            "free_margin": info.margin_free,
        }

    def terminal_info(self) -> Optional[dict]:
        info = mt5_lib.terminal_info()
        if info is None:
            return None
        return {
            "connected": info.connected,
            "community_account": getattr(info, "community_account", None),
            "data_path": getattr(info, "data_path", None),
            "commondata_path": getattr(info, "commondata_path", None),
            "build": info.build,
            "name": info.name,
            "company": info.company,
        }

    def symbols_matching(self, patterns: list[str]) -> list[str]:
        """Return symbol names whose name contains any of the patterns
        (case-insensitive) or equals one of them."""
        all_syms = mt5_lib.symbols_get() or []
        out: list[str] = []
        patterns_lc = [p.lower() for p in patterns]
        for s in all_syms:
            name = s.name
            name_lc = name.lower()
            if any(p in name_lc for p in patterns_lc):
                out.append(name)
        return out

    def ensure_selected(self, symbol: str) -> bool:
        info = mt5_lib.symbol_info(symbol)
        if info is None:
            return False
        if not info.visible:
            if not mt5_lib.symbol_select(symbol, True):
                return False
        return True

    def symbol_info(self, symbol: str) -> Optional[dict]:
        info = mt5_lib.symbol_info(symbol)
        if info is None:
            return None
        return {
            "name": info.name,
            "description": info.description,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "tick_size": info.trade_tick_size,
            "tick_value": info.trade_tick_value,
            "contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_mode": info.trade_mode,
            "filling_mode": info.filling_mode,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
            "currency_margin": info.currency_margin,
            "visible": info.visible,
        }

    def symbol_info_tick(self, symbol: str) -> Optional[dict]:
        tick = mt5_lib.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
            "time_msc": tick.time_msc,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "flags": tick.flags,
        }

    def copy_ticks_range(
        self,
        symbol: str,
        date_from: datetime,
        date_to: datetime,
        flags: int | None = None,
    ) -> pd.DataFrame:
        """Pull ticks for [date_from, date_to]. Returns empty DataFrame on failure."""
        self.ensure_selected(symbol)
        flags = flags if flags is not None else self.COPY_TICKS_ALL
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)
        ticks = mt5_lib.copy_ticks_range(symbol, date_from, date_to, flags)
        if ticks is None or len(ticks) == 0:
            err = mt5_lib.last_error()
            self._say(
                "warning",
                f"[MT5] copy_ticks_range({symbol}, {date_from.isoformat()}, "
                f"{date_to.isoformat()}) returned no data: {err}",
            )
            return pd.DataFrame()
        df = pd.DataFrame(ticks)
        if "time_msc" in df.columns:
            df["time_utc"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True)
        else:
            df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def copy_ticks_from(
        self,
        symbol: str,
        date_from: datetime,
        count: int,
        flags: int | None = None,
    ) -> pd.DataFrame:
        self.ensure_selected(symbol)
        flags = flags if flags is not None else self.COPY_TICKS_ALL
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        ticks = mt5_lib.copy_ticks_from(symbol, date_from, count, flags)
        if ticks is None or len(ticks) == 0:
            err = mt5_lib.last_error()
            self._say(
                "warning",
                f"[MT5] copy_ticks_from({symbol}, {date_from.isoformat()}, "
                f"{count}) returned no data: {err}",
            )
            return pd.DataFrame()
        df = pd.DataFrame(ticks)
        if "time_msc" in df.columns:
            df["time_utc"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True)
        else:
            df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def last_error(self) -> tuple[int, str]:
        err = mt5_lib.last_error()
        if isinstance(err, tuple) and len(err) >= 2:
            return int(err[0]), str(err[1])
        return -1, str(err)
