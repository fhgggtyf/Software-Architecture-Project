"""Configure application logging using the Python standard library.

This module defines a function that sets up a root logger with both
console and rotating file handlers.  Logs are formatted as JSON for
structured logging and include useful context fields (timestamp,
level, message, module, request_id, user_id, and extra).  Only the
standard library is used.
"""

import json
import logging
import logging.handlers
import os
from datetime import datetime


class JsonFormatter(logging.Formatter):
    """Format log records as JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        # Basic fields
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        # Context fields expected in extra
        # These may be injected by the application when logging
        if hasattr(record, "request_id"):
            log_record["request_id"] = getattr(record, "request_id")
        if hasattr(record, "user_id"):
            log_record["user_id"] = getattr(record, "user_id")
        if hasattr(record, "extra"):
            # Merge extra dict into top‑level (avoid nested 'extra')
            try:
                extra = getattr(record, "extra")
                if isinstance(extra, dict):
                    log_record.update(extra)
            except Exception:
                pass
        return json.dumps(log_record)


def configure_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatting and rotating file handler.

    Args:
        log_dir: Directory where log files are written.  The directory
            will be created if it does not exist.
        level: Logging level for the root logger.
    """
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(level)
    # Remove any default handlers (e.g. from basicConfig)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    # JSON formatter
    formatter = JsonFormatter()
    # Console handler (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)
    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "retail_app.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB per log file
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)