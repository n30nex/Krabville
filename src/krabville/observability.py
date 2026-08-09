from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any


LOGGER = logging.getLogger("krabville")


def configure_logging() -> None:
    level = getattr(logging, os.environ.get("KRABVILLE_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")


def log_event(service: str, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level).lower(),
        "service": service,
        "event": event,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    LOGGER.log(level, json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str))
