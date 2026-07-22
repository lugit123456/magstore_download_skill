from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4


SENSITIVE_KEYS = ("password", "token", "authorization", "cookie")


class ContextFilter(logging.Filter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = getattr(record, "run_id", self.run_id)
        record.magazine_id = getattr(record, "magazine_id", "-")
        record.phase = getattr(record, "phase", "-")
        record.msg = redact(str(record.msg))
        return True


def setup_logging(level: str, log_file: Path, max_bytes: int, backup_count: int) -> tuple[logging.Logger, str]:
    run_id = uuid4().hex[:12]
    logger = logging.getLogger("magstore_downloader")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s run=%(run_id)s magazine=%(magazine_id)s phase=%(phase)s %(message)s"
    )
    context_filter = ContextFilter(run_id)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    logger.addHandler(console)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    logger.addHandler(file_handler)
    return logger, run_id


def extra(magazine_id: str = "-", phase: str = "-") -> dict[str, str]:
    return {"magazine_id": magazine_id, "phase": phase}


def redact(value: str) -> str:
    redacted = value
    for key in SENSITIVE_KEYS:
        redacted = redacted.replace(key + "=", key + "=***")
    return redacted

