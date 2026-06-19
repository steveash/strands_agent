from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import SessionArtifactStore


def load_session_manifest(session_dir: str | Path) -> dict[str, Any]:
    resolved = Path(session_dir).expanduser().resolve()
    manifest_path = resolved / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Session manifest does not exist: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Session manifest must be a JSON object: {manifest_path}")
    return payload


def load_or_refresh_session_manifest(session_dir: str | Path) -> dict[str, Any]:
    try:
        return load_session_manifest(session_dir)
    except FileNotFoundError:
        store = SessionArtifactStore.from_session_dir(session_dir)
        return store.refresh_manifest()


def summarize_session_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    config_sources = dict(manifest.get("config_sources") or {})
    event_counts = _sorted_counts(manifest.get("event_counts"))
    tool_counts = _sorted_counts(manifest.get("tool_counts"))
    artifacts = dict(manifest.get("artifacts") or {})
    return {
        "session_id": str(manifest.get("session_id", "") or ""),
        "session_dir": str(manifest.get("session_dir", "") or ""),
        "created_at": str(manifest.get("created_at", "") or ""),
        "last_turn_at": str(manifest.get("last_turn_at", "") or ""),
        "updated_at": str(manifest.get("updated_at", "") or ""),
        "turn_count": int(manifest.get("turn_count") or 0),
        "error_count": int(manifest.get("error_count") or 0),
        "pending_approval_count": int(manifest.get("pending_approval_count") or 0),
        "provider": str(manifest.get("provider", "") or ""),
        "mode": str(manifest.get("mode", "") or ""),
        "model": str(manifest.get("model", "") or ""),
        "workspace_root": str(manifest.get("workspace_root", "") or ""),
        "profile_name": str(manifest.get("profile_name", "") or ""),
        "profile_path": str(manifest.get("profile_path", "") or ""),
        "config_sources": config_sources,
        "source_summary": _format_config_sources(config_sources),
        "last_prompt_preview": str(manifest.get("last_prompt_preview", "") or ""),
        "last_response_preview": str(manifest.get("last_response_preview", "") or ""),
        "top_events": event_counts[:5],
        "top_tools": tool_counts[:5],
        "artifacts": artifacts,
        "warnings": _manifest_warnings(manifest, artifacts),
    }


def render_session_manifest_summary(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"session: {summary.get('session_id') or '(unknown)'}",
        f"path: {summary.get('session_dir') or '(unknown)'}",
        (
            "turns: "
            f"{summary.get('turn_count', 0)} | errors: {summary.get('error_count', 0)} | "
            f"pending approvals: {summary.get('pending_approval_count', 0)}"
        ),
        (
            "runtime: "
            f"{summary.get('provider') or '(unknown)'} / {summary.get('mode') or '(unknown)'} / "
            f"{summary.get('model') or '(model unknown)'}"
        ),
        f"workspace: {summary.get('workspace_root') or '(unknown)'}",
        f"profile: {summary.get('profile_name') or '(none)'}",
        f"profile path: {summary.get('profile_path') or '(none)'}",
        f"sources: {summary.get('source_summary') or '(none)'}",
        f"created: {summary.get('created_at') or '(unknown)'}",
        f"last turn: {summary.get('last_turn_at') or '(unknown)'}",
        f"last prompt: {summary.get('last_prompt_preview') or '(none)'}",
        f"last response: {summary.get('last_response_preview') or '(none)'}",
        f"top events: {_format_named_counts(summary.get('top_events'))}",
        f"top tools: {_format_named_counts(summary.get('top_tools'))}",
    ]
    artifacts = dict(summary.get("artifacts") or {})
    for key in ["turns", "transcript", "session_state"]:
        lines.append(f"artifact {key}: {artifacts.get(key) or '(missing)'}")
    for warning in summary.get("warnings") or []:
        lines.append(f"warning: {warning}")
    return lines


def _sorted_counts(value: object) -> list[tuple[str, int]]:
    if not isinstance(value, dict):
        return []
    counts: list[tuple[str, int]] = []
    for name, count in value.items():
        try:
            parsed = int(count)
        except (TypeError, ValueError):
            continue
        counts.append((str(name), parsed))
    return sorted(counts, key=lambda item: (-item[1], item[0]))


def _format_named_counts(value: object) -> str:
    if not value:
        return "(none)"
    return ", ".join(f"{name}={count}" for name, count in value)


def _format_config_sources(sources: dict[str, object]) -> str:
    if not sources:
        return ""
    labels = [
        ("runtime", "runtime_mode"),
        ("model", "openai_model"),
        ("workspace", "workspace_root"),
        ("artifacts", "artifacts_root"),
        ("overwrite", "allow_overwrite"),
        ("stale", "stale_approval_warning_days"),
    ]
    rendered = [
        f"{label}={sources[field_name]}"
        for label, field_name in labels
        if field_name in sources
    ]
    extra = [
        f"{key}={sources[key]}"
        for key in sorted(set(sources) - {field_name for _label, field_name in labels})
    ]
    return ", ".join(rendered + extra)


def _manifest_warnings(manifest: dict[str, Any], artifacts: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if not manifest.get("session_id"):
        warnings.append("Manifest is missing session_id.")
    if not manifest.get("turn_count"):
        warnings.append("Manifest has no saved turns.")
    if not manifest.get("workspace_root"):
        warnings.append("Manifest is missing workspace_root metadata.")
    for key in ["turns", "transcript", "session_state"]:
        if key not in artifacts:
            warnings.append(f"Manifest is missing artifact path: {key}.")
    return warnings
