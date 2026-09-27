# src/jev_eval/logging_setup.py
"""JSONL audit log with rotation. One line per invocation; never breaks the decision."""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path

_LOGGER_NAME = "jev_eval.audit"

def build_audit_logger(log_file: Path) -> logging.Logger:
    log_file = Path(log_file).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger

def audit(logger: logging.Logger | None, **fields: object) -> None:
    if logger is None:
        return
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
              + f".{int(time.time() * 1000) % 1000:03d}Z", **fields}
    try:
        logger.info(json.dumps(record, ensure_ascii=True))
    except Exception:
        pass  # logging must never break the decision
