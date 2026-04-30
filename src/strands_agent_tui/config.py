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
    session_id: str | None = None

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_root).expanduser().resolve()

    def merge(self, **overrides: str | None) -> "AppConfig":
        data = asdict(self)
        for key, value in overrides.items():
            if value is None:
                continue
            normalized = value.strip()
            if normalized:
                data[key] = normalized.lower() if key == "runtime_mode" else normalized
        return AppConfig(**data)


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
    )
