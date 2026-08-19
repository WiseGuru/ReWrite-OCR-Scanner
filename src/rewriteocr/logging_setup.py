"""Rotating file logging. The log file feeds the diagnostics dialog."""

from __future__ import annotations

import logging
import logging.handlers

from rewriteocr.config import logs_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger("rewriteocr")
    if root.handlers:
        return root
    root.setLevel(level)
    handler = logging.handlers.RotatingFileHandler(
        logs_dir() / "rewriteocr.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    return root
