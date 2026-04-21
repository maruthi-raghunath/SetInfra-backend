import json
import logging
from datetime import datetime, timezone

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            payload["trace_id"] = record.trace_id
        if hasattr(record, "event_action"):
            payload["event_action"] = record.event_action
        if hasattr(record, "model_version"):
            payload["model_version"] = record.model_version
        if hasattr(record, "metadata"):
            payload["metadata"] = record.metadata
        return json.dumps(payload)


def configure_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.LOG_LEVEL.upper())

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
