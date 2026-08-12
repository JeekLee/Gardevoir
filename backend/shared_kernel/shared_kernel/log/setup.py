"""Logging configuration.

Idempotent: calling it twice must not double every log line. Tests and reload
paths call it more than once.

Note for tests: this replaces every root handler, which includes pytest's log
capture handler. A test that calls it must save and restore the root handlers
or later tests lose caplog.
"""

import logging
import sys

import orjson

from shared_kernel.config.settings import LogSettings
from shared_kernel.log.context import get_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return orjson.dumps(payload).decode()


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = get_request_id() or "-"
        line = f"{record.levelname:<8} [{rid}] {record.name}: {record.getMessage()}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(settings: LogSettings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.json_output else TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.level.upper())
