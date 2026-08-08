from __future__ import annotations

from pathlib import Path

import pytest

from krabville.config import Settings


@pytest.fixture
def settings_factory(tmp_path: Path):
    def make(**overrides) -> Settings:
        data_dir = tmp_path / str(overrides.pop("name", "runtime"))
        values = {
            "data_dir": data_dir,
            "database_path": data_dir / "krabville.db",
            "asset_dir": tmp_path / "assets",
            "report_dir": data_dir / "reports",
            "frontend_dir": tmp_path / "frontend",
            "control_socket": data_dir / "control.sock",
            "bind_host": "127.0.0.1",
            "port": 18890,
            "tick_seconds": 0.01,
            "fake_provider": True,
            "primary_model": "gpt-5.3-codex-spark",
            "fallback_model": "gpt-5.6-luna",
            "call_limit": 150,
            "token_guard": 500_000,
            "inference_timeout": 10,
            "voter_secret": "test-secret-with-enough-entropy",
            "public_origin": "http://testserver",
        }
        values.update(overrides)
        return Settings(**values)

    return make
