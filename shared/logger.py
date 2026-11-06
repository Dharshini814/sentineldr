"""
SentinelDR - Structured JSON Logging & Secret Redaction
Standard library only (runtime-neutral for Laptop & Phone).
"""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Patterns to redact from logs
REDACTION_PATTERNS = [
    (re.compile(r"(?i)(sdr[_-]?hmac[_-]?secret\s*[:=]\s*)[^\s,]+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(sdr[_-]?admin[_-]?key\s*[:=]\s*)[^\s,]+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,]+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(x-sdr-signature:\s*)[a-fA-F0-9]{32,}"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(password\s*[:=]\s*['\"])[^'\"]+(['\"])"), r"\1***REDACTED***\2"),
    (re.compile(r"(?i)(postgres(?:ql)?://[a-zA-Z0-9_\-]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
]


def redact_sensitive_data(text: str) -> str:
    """Mask credentials and sensitive strings in log outputs."""
    if not isinstance(text, str):
        text = str(text)
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class StructuredJsonFormatter(logging.Formatter):
    """Custom logging formatter outputting clean JSON records with secret masking."""

    def __init__(self, node_id: str = "unknown", epoch: int = 0):
        super().__init__()
        self.node_id = node_id
        self.epoch = epoch

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
            "node_id": getattr(record, "node_id", self.node_id),
            "epoch": getattr(record, "epoch", self.epoch),
        }

        if record.exc_info:
            # Redact exception details
            exc_str = self.formatException(record.exc_info)
            log_obj["exception"] = redact_sensitive_data(exc_str)

        # Include custom extra attributes if present
        for key, val in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName", "node_id", "epoch"
            ):
                if isinstance(val, (str, int, float, bool, list, dict)) or val is None:
                    log_obj[key] = val

        return json.dumps(log_obj, ensure_ascii=False)


def setup_logger(
    name: str,
    node_id: str = "unknown",
    epoch: int = 0,
    level=logging.INFO,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Create and configure a structured JSON logger with optional log rotation."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if not logger.handlers:
        formatter = StructuredJsonFormatter(node_id=node_id, epoch=epoch)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    logger.propagate = False
    return logger
