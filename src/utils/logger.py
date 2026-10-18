"""Logging to ``logs/app.log`` and the terminal."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("naukri_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if getattr(logger, "_configured", False):
        return logger

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream)
    logger.propagate = False
    logger._configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"naukri_agent.{name}")
