"""
logger.py — Simple console + daily-rotated file logger.

Adapted from uS30/src/logger.py. Trimmed TRADE/RISK levels since this repo
doesn't trade; kept the structure so it can be extended if we ever stand up
a live bot from this code.

Usage:
    from src.logger import Logger
    log = Logger("probe", "logs")
    log.info("hello")
"""

from __future__ import annotations

import copy
import logging
import os
import sys
from datetime import datetime, timezone


class PlainFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            fmt="[%(asctime)s] [%(levelname)-7s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[90m",
        logging.INFO: "\033[0m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
    }
    RESET = "\033[0m"

    def __init__(self):
        super().__init__(
            fmt="[%(asctime)s] [%(levelname)-7s] %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record):
        record_copy = copy.copy(record)
        color = self.COLORS.get(record_copy.levelno, self.RESET)
        record_copy.levelname = f"{color}{record_copy.levelname}{self.RESET}"
        return super().format(record_copy)


class Logger:
    """Console + daily-rotated file logger scoped by `name`."""

    def __init__(
        self,
        name: str,
        log_dir: str,
        level: str = "INFO",
        print_to_console: bool = True,
    ):
        self._name = name
        self._logger = logging.getLogger(f"deriv_research.{name}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._current_date: str | None = None
        self._file_handler: logging.FileHandler | None = None
        self._log_dir = log_dir
        os.makedirs(self._log_dir, exist_ok=True)

        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        self._min_level = level_map.get(level.upper(), logging.INFO)

        if print_to_console:
            console = logging.StreamHandler(sys.stdout)
            console.setLevel(self._min_level)
            console.setFormatter(ColorFormatter())
            self._logger.addHandler(console)

        self._ensure_file_handler()

    def _ensure_file_handler(self):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if self._current_date == today and self._file_handler:
            return
        if self._file_handler:
            self._logger.removeHandler(self._file_handler)
            self._file_handler.close()
        filepath = os.path.join(self._log_dir, f"{self._name}_{today}.log")
        self._file_handler = logging.FileHandler(filepath, encoding="utf-8")
        self._file_handler.setLevel(self._min_level)
        self._file_handler.setFormatter(PlainFormatter())
        self._logger.addHandler(self._file_handler)
        self._current_date = today

    def debug(self, msg: str):
        self._ensure_file_handler()
        self._logger.debug(msg)

    def info(self, msg: str):
        self._ensure_file_handler()
        self._logger.info(msg)

    def warning(self, msg: str):
        self._ensure_file_handler()
        self._logger.warning(msg)

    def error(self, msg: str):
        self._ensure_file_handler()
        self._logger.error(msg)

    def shutdown(self):
        if self._file_handler:
            self._file_handler.flush()
            self._file_handler.close()
