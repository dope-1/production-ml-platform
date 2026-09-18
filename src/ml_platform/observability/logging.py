import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "ml-api",
            "event": record.getMessage(),
        }
        for key in ("request_id", "endpoint", "latency_ms", "status", "error_type"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        # Do not serialize exception messages, URLs, request bodies, or credentials.
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("ml_platform")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
