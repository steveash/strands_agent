from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class AppConfig:
    runtime_mode: str = "fake"
    openai_model: str = "gpt-4o-mini"


def load_config() -> AppConfig:
    return AppConfig(
        runtime_mode=os.getenv("STRANDS_AGENT_RUNTIME", "fake").strip().lower() or "fake",
        openai_model=os.getenv("STRANDS_AGENT_OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
    )
