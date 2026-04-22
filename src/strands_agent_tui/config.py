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
    return AppConfig(
        runtime_mode=os.getenv("STRANDS_AGENT_RUNTIME", "fake").strip().lower() or "fake",
        openai_model=os.getenv("STRANDS_AGENT_OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        workspace_root=os.getenv("STRANDS_AGENT_WORKSPACE_ROOT", os.getcwd()).strip() or os.getcwd(),
    )
