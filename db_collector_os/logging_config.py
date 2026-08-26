"""Logging setup: separate rotating files for app/scheduler/worker/job/fetch-error streams.

Never logs secrets, cookies, or Authorization headers -- callers must pass
already-sanitized messages.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED_LOGGERS: set[str] = set()

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Fields that must never be logged. Defensive: strip common secret-ish keys
# if a caller accidentally passes a dict/string containing them.
_REDACT_KEYS = ("cookie", "authorization", "api_key", "apikey", "password", "secret", "token")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        lowered = msg.lower()
        for key in _REDACT_KEYS:
            if key in lowered:
                record.msg = "[redacted: message contained a sensitive-looking field]"
                record.args = ()
                break
        return True


def get_logger(name: str, log_dir: str | Path = "./var/logs", level: str = "INFO") -> logging.Logger:
    """Return a logger writing to var/logs/<name>.log plus stderr, once configured."""
    logger = logging.getLogger(name)
    if name in _CONFIGURED_LOGGERS:
        return logger

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT)
    redactor = RedactingFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{name}.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redactor)
    logger.addHandler(stream_handler)

    _CONFIGURED_LOGGERS.add(name)
    return logger
