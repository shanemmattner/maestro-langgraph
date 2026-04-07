"""Centralized logging setup for langgraph-maestro.

Configures Python logging with:
- Console handler: human-readable format
- File handler: JSON lines for machine parsing (RotatingFileHandler)
"""

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class JSONLineFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Include extra data if present (skip standard LogRecord attrs)
        standard_attrs = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "filename", "module", "pathname", "thread", "threadName",
            "process", "processName", "levelname", "levelno", "message",
            "msecs", "taskName",
        }
        data = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
        if data:
            entry["data"] = data
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(
    level: int = logging.INFO,
    log_dir: Optional[str] = None,
    workflow_name: str = "default",
) -> str:
    """Configure root logger with console and file handlers.

    Args:
        level: Logging level (e.g. logging.DEBUG)
        log_dir: Directory for log files. Default: ~/.cache/langgraph-maestro/logs/
        workflow_name: Name prefix for log files.

    Returns:
        Path to the log file.
    """
    if log_dir is None:
        log_dir = os.path.expanduser("~/.cache/langgraph-maestro/logs")

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"{workflow_name}-{timestamp}.jsonl")

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    # Console handler — human readable
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    )
    root.addHandler(console)

    # File handler — JSON lines, rotating 10MB x 5
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(JSONLineFormatter())
    root.addHandler(file_handler)

    logging.getLogger(__name__).info(
        "Logging initialized",
        extra={"log_file": log_file, "level": logging.getLevelName(level)},
    )

    return log_file


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper for logging.getLogger."""
    return logging.getLogger(name)
