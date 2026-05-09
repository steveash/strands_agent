from __future__ import annotations

import os
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    runtime_mode: str = "fake"
    openai_model: str = "gpt-4o-mini"
    workspace_root: str = "."
    artifacts_root: str = "artifacts/sessions"
    allow_overwrite: bool = False
    stale_approval_warning_days: int = 7
    session_id: str | None = None

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_root).expanduser().resolve()

    @property
    def stale_approval_warning_seconds(self) -> int:
        return max(self.stale_approval_warning_days, 1) * 24 * 60 * 60

    def merge(self, **overrides: str | int | None) -> "AppConfig":
        data = asdict(self)
        for key, value in overrides.items():
            if value is None:
                continue
            if key == "stale_approval_warning_days":
                parsed = int(str(value).strip()) if isinstance(value, str) else int(value)
                if parsed < 1:
                    raise ValueError("stale_approval_warning_days must be >= 1")
                data[key] = parsed
                continue
            normalized = value.strip()
            if normalized:
                data[key] = normalized.lower() if key == "runtime_mode" else normalized
        return AppConfig(**data)


def _load_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed >= 1 else default


def load_config() -> AppConfig:
    workspace_root = os.getenv("STRANDS_AGENT_WORKSPACE_ROOT", os.getcwd()).strip() or os.getcwd()
    artifacts_root = os.getenv("STRANDS_AGENT_ARTIFACTS_ROOT", "").strip()
    if not artifacts_root:
        artifacts_root = str(Path(workspace_root).expanduser().resolve() / "artifacts" / "sessions")
    return AppConfig(
        runtime_mode=os.getenv("STRANDS_AGENT_RUNTIME", "fake").strip().lower() or "fake",
        openai_model=os.getenv("STRANDS_AGENT_OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        workspace_root=workspace_root,
        artifacts_root=artifacts_root,
        allow_overwrite=os.getenv("STRANDS_AGENT_ALLOW_OVERWRITE", "").strip().lower() in {"1", "true", "yes", "on"},
        stale_approval_warning_days=_load_positive_int_env("STRANDS_AGENT_STALE_APPROVAL_DAYS", 7),
    )
