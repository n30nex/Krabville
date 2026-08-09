from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _boolean(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secret(name: str, file_name: str, default: str) -> str:
    path = os.environ.get(file_name)
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get(name, default)


def _reasoning(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip().lower()
    return value if value in {"none", "minimal", "low", "medium", "high", "xhigh", "max"} else default


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    asset_dir: Path
    report_dir: Path
    frontend_dir: Path
    control_socket: Path
    bind_host: str
    port: int
    tick_seconds: float
    fake_provider: bool
    primary_model: str
    primary_reasoning: str
    fallback_model: str
    fallback_reasoning: str
    call_limit: int
    token_guard: int
    inference_timeout: int
    voter_secret: str
    public_origin: str
    season_limit: int = 20
    auto_continue: bool = True
    intermission_seconds: int = 600
    max_population: int = 32
    max_adults: int = 24

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.environ.get("KRABVILLE_DATA_DIR", "runtime")).resolve()
        package_root = Path(__file__).resolve().parents[2]
        return cls(
            data_dir=root,
            database_path=Path(
                os.environ.get("KRABVILLE_DATABASE", root / "krabville.db")
            ).resolve(),
            asset_dir=Path(
                os.environ.get(
                    "KRABVILLE_ASSET_DIR", package_root / "frontend" / "public" / "assets"
                )
            ).resolve(),
            report_dir=Path(
                os.environ.get("KRABVILLE_REPORT_DIR", root / "reports")
            ).resolve(),
            frontend_dir=Path(
                os.environ.get("KRABVILLE_FRONTEND_DIR", package_root / "frontend" / "dist")
            ).resolve(),
            control_socket=Path(
                os.environ.get("KRABVILLE_CONTROL_SOCKET", root / "control.sock")
            ),
            bind_host=os.environ.get("KRABVILLE_BIND", "127.0.0.1"),
            port=int(os.environ.get("KRABVILLE_PORT", "18889")),
            tick_seconds=max(0.01, float(os.environ.get("KRABVILLE_TICK_SECONDS", "12.5"))),
            fake_provider=_boolean("KRABVILLE_FAKE_PROVIDER", True),
            primary_model=os.environ.get("KRABVILLE_PRIMARY_MODEL", "gpt-5.3-codex-spark"),
            primary_reasoning=_reasoning("KRABVILLE_PRIMARY_REASONING", "low"),
            fallback_model=os.environ.get("KRABVILLE_FALLBACK_MODEL", "gpt-5.6-luna"),
            fallback_reasoning=_reasoning("KRABVILLE_FALLBACK_REASONING", "low"),
            call_limit=max(1, int(os.environ.get("KRABVILLE_CALL_LIMIT", "150"))),
            token_guard=max(8000, int(os.environ.get("KRABVILLE_TOKEN_GUARD", "1500000"))),
            inference_timeout=max(10, int(os.environ.get("KRABVILLE_INFERENCE_TIMEOUT", "180"))),
            voter_secret=_secret(
                "KRABVILLE_VOTER_SECRET",
                "KRABVILLE_VOTER_SECRET_FILE",
                "development-only-change-me",
            ),
            public_origin=os.environ.get("KRABVILLE_PUBLIC_ORIGIN", "https://krab.canadaverse.org"),
            season_limit=max(1, int(os.environ.get("KRABVILLE_SEASON_LIMIT", "20"))),
            auto_continue=_boolean("KRABVILLE_AUTO_CONTINUE", True),
            intermission_seconds=max(
                0, int(os.environ.get("KRABVILLE_INTERMISSION_SECONDS", "600"))
            ),
            max_population=max(12, int(os.environ.get("KRABVILLE_MAX_POPULATION", "32"))),
            max_adults=max(8, int(os.environ.get("KRABVILLE_MAX_ADULTS", "24"))),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.control_socket.parent.mkdir(parents=True, exist_ok=True)
