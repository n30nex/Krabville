from __future__ import annotations

import json
import logging

from krabville.observability import log_event


def test_structured_log_has_bounded_correlation_fields(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="krabville"):
        log_event(
            "engine",
            "tick_advanced",
            season=3,
            tick=1200,
            resident="maya-cardinal",
            job=41,
            sequence=901,
            elapsedMs=12,
        )
    payload = json.loads(caplog.records[-1].message)
    assert payload["service"] == "engine"
    assert payload["event"] == "tick_advanced"
    assert payload["season"] == 3
    assert payload["tick"] == 1200
    assert payload["resident"] == "maya-cardinal"
    assert payload["job"] == 41
    assert payload["sequence"] == 901
    assert payload["elapsedMs"] == 12
