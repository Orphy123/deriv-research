"""Synthetic spike backtest package."""

from .config import AppConfig, load_config
from .simulator import run_backtest

__all__ = ["AppConfig", "load_config", "run_backtest"]
