from __future__ import annotations

import os
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    runtime_mode: str = "fake"
    openai_model: str = "gpt-4o-mini"
    workspace_root: str = "."
    artifacts_root: str = "artifacts/sessions"
    allow_overwrite: bool = False
    stale_approval_warning_days: int = 7
    session_id: str | None = None
    profile_name: str = "ad hoc"
    profile_path: str = ""
    config_sources: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in [
            "runtime_mode",
            "openai_model",
            "workspace_root",
            "artifacts_root",
            "allow_overwrite",
            "stale_approval_warning_days",
            "profile_name",
            "profile_path",
        ]:
            self.config_sources.setdefault(key, "default")

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_root).expanduser().resolve()

    @property
    def stale_approval_warning_seconds(self) -> int:
        return max(self.stale_approval_warning_days, 1) * 24 * 60 * 60

    def merge(self, *, source: str = "cli", **overrides: str | int | bool | None) -> "AppConfig":
        data = asdict(self)
        sources = dict(self.config_sources)
        for key, value in overrides.items():
            if value is None:
                continue
            if key == "allow_overwrite":
                data[key] = bool(value)
                sources[key] = source
                continue
            if key == "stale_approval_warning_days":
                parsed = int(str(value).strip()) if isinstance(value, str) else int(value)
                if parsed < 1:
                    raise ValueError("stale_approval_warning_days must be >= 1")
                data[key] = parsed
                sources[key] = source
                continue
            normalized = value.strip()
            if normalized:
                data[key] = normalized.lower() if key == "runtime_mode" else normalized
                sources[key] = source
        data["config_sources"] = sources
        return AppConfig(**data)

    def config_source_summary(self) -> str:
        labels = [
            ("runtime", "runtime_mode"),
            ("model", "openai_model"),
            ("workspace", "workspace_root"),
            ("artifacts", "artifacts_root"),
            ("overwrite", "allow_overwrite"),
            ("stale", "stale_approval_warning_days"),
        ]
        return ", ".join(
            f"{label}={self.config_sources.get(field_name, 'default')}"
            for label, field_name in labels
        )


def _load_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed >= 1 else default


def _env_is_set(name: str) -> bool:
    return os.getenv(name) is not None


def _load_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _profile_value(profile: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in profile and profile[name] not in (None, ""):
            return profile[name]
    return None


def _profile_source(profile: dict[str, Any], *names: str) -> str:
    return "profile" if _profile_value(profile, *names) is not None else "default"


def load_workspace_profile(profile_path: str | None = None) -> tuple[dict[str, Any], Path | None]:
    selected = (profile_path or os.getenv("STRANDS_AGENT_PROFILE", "")).strip()
    if not selected:
        return {}, None

    path = Path(selected).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Workspace profile must be a JSON object: {path}")
    return payload, path


def load_config(profile_path: str | None = None) -> AppConfig:
    profile, resolved_profile_path = load_workspace_profile(profile_path)
    profile_workspace = _profile_value(profile, "workspace_root", "workspace")
    workspace_default = str(profile_workspace) if profile_workspace is not None else os.getcwd()
    workspace_root = (
        os.getenv("STRANDS_AGENT_WORKSPACE_ROOT", workspace_default).strip()
        or workspace_default
    )
    artifacts_root = os.getenv("STRANDS_AGENT_ARTIFACTS_ROOT", "").strip()
    if not artifacts_root:
        profile_artifacts_root = _profile_value(profile, "artifacts_root", "artifacts")
        artifacts_root = (
            str(profile_artifacts_root)
            if profile_artifacts_root is not None
            else str(Path(workspace_root).expanduser().resolve() / "artifacts" / "sessions")
        )
    stale_default = _profile_value(profile, "stale_approval_warning_days", "stale_approval_days")
    stale_days = _coerce_positive_int(stale_default, default=7)
    profile_name = str(_profile_value(profile, "name", "profile_name") or "ad hoc")
    runtime_default = str(_profile_value(profile, "runtime_mode", "runtime") or "fake")
    model_default = str(_profile_value(profile, "openai_model", "model") or "gpt-4o-mini")
    allow_overwrite_default = _coerce_bool(_profile_value(profile, "allow_overwrite"), default=False)
    runtime_from_env = _env_is_set("STRANDS_AGENT_RUNTIME")
    model_from_env = _env_is_set("STRANDS_AGENT_OPENAI_MODEL")
    workspace_from_env = _env_is_set("STRANDS_AGENT_WORKSPACE_ROOT")
    artifacts_from_env = _env_is_set("STRANDS_AGENT_ARTIFACTS_ROOT")
    overwrite_from_env = _env_is_set("STRANDS_AGENT_ALLOW_OVERWRITE")
    stale_from_env = _env_is_set("STRANDS_AGENT_STALE_APPROVAL_DAYS")
    return AppConfig(
        runtime_mode=os.getenv("STRANDS_AGENT_RUNTIME", runtime_default).strip().lower() or runtime_default,
        openai_model=os.getenv("STRANDS_AGENT_OPENAI_MODEL", model_default).strip() or model_default,
        workspace_root=workspace_root,
        artifacts_root=artifacts_root,
        allow_overwrite=_load_bool_env("STRANDS_AGENT_ALLOW_OVERWRITE", allow_overwrite_default),
        stale_approval_warning_days=(
            _load_positive_int_env("STRANDS_AGENT_STALE_APPROVAL_DAYS", stale_days)
            if stale_from_env
            else stale_days
        ),
        profile_name=profile_name,
        profile_path=str(resolved_profile_path) if resolved_profile_path else "",
        config_sources={
            "runtime_mode": "env" if runtime_from_env else _profile_source(profile, "runtime_mode", "runtime"),
            "openai_model": "env" if model_from_env else _profile_source(profile, "openai_model", "model"),
            "workspace_root": "env" if workspace_from_env else _profile_source(profile, "workspace_root", "workspace"),
            "artifacts_root": "env" if artifacts_from_env else _profile_source(profile, "artifacts_root", "artifacts"),
            "allow_overwrite": "env" if overwrite_from_env else _profile_source(profile, "allow_overwrite"),
            "stale_approval_warning_days": (
                "env" if stale_from_env else _profile_source(profile, "stale_approval_warning_days", "stale_approval_days")
            ),
            "profile_name": "profile" if resolved_profile_path else "default",
            "profile_path": "profile" if resolved_profile_path else "default",
        },
    )
