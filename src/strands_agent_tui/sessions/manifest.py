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


def list_session_manifest_summaries(
    sessions_root: str | Path,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    resolved = Path(sessions_root).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"Sessions root does not exist: {resolved}")

    summaries: list[dict[str, Any]] = []
    for child in resolved.iterdir():
        if not child.is_dir():
            continue
        try:
            manifest = load_or_refresh_session_manifest(child)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            continue
        summary = summarize_session_manifest(manifest)
        if summary.get("session_id"):
            summaries.append(summary)

    summaries.sort(key=_summary_sort_key, reverse=True)
    if limit is not None:
        return summaries[: max(0, limit)]
    return summaries


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


def summarize_session_manifest_collection(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    provider_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    workspace_roots: set[str] = set()
    sessions: list[dict[str, Any]] = []

    for summary in summaries:
        _increment_count(provider_counts, str(summary.get("provider") or "(unknown)"))
        _increment_count(mode_counts, str(summary.get("mode") or "(unknown)"))
        _increment_count(model_counts, str(summary.get("model") or "(model unknown)"))
        workspace_root = str(summary.get("workspace_root") or "")
        if workspace_root:
            workspace_roots.add(workspace_root)
        for name, count in summary.get("top_events") or []:
            _increment_count(event_counts, str(name), int(count))
        for name, count in summary.get("top_tools") or []:
            _increment_count(tool_counts, str(name), int(count))
        sessions.append(
            {
                "session_id": summary.get("session_id", ""),
                "session_dir": summary.get("session_dir", ""),
                "last_turn_at": summary.get("last_turn_at", ""),
                "updated_at": summary.get("updated_at", ""),
                "turn_count": summary.get("turn_count", 0),
                "error_count": summary.get("error_count", 0),
                "pending_approval_count": summary.get("pending_approval_count", 0),
                "runtime": (
                    f"{summary.get('provider') or '(unknown)'} / "
                    f"{summary.get('mode') or '(unknown)'} / "
                    f"{summary.get('model') or '(model unknown)'}"
                ),
                "workspace_root": workspace_root,
                "last_prompt_preview": summary.get("last_prompt_preview", ""),
            }
        )

    return {
        "session_count": len(summaries),
        "turn_count": sum(int(summary.get("turn_count") or 0) for summary in summaries),
        "error_count": sum(int(summary.get("error_count") or 0) for summary in summaries),
        "pending_approval_count": sum(
            int(summary.get("pending_approval_count") or 0) for summary in summaries
        ),
        "workspace_count": len(workspace_roots),
        "providers": _sorted_counts(provider_counts),
        "modes": _sorted_counts(mode_counts),
        "models": _sorted_counts(model_counts),
        "top_events": _sorted_counts(event_counts)[:5],
        "top_tools": _sorted_counts(tool_counts)[:5],
        "sessions": sessions,
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


def render_session_manifest_collection_summary(collection: dict[str, Any]) -> list[str]:
    lines = [
        (
            "sessions: "
            f"{collection.get('session_count', 0)} | turns: {collection.get('turn_count', 0)} | "
            f"errors: {collection.get('error_count', 0)} | "
            f"pending approvals: {collection.get('pending_approval_count', 0)} | "
            f"workspaces: {collection.get('workspace_count', 0)}"
        ),
        f"providers: {_format_named_counts(collection.get('providers'))}",
        f"modes: {_format_named_counts(collection.get('modes'))}",
        f"models: {_format_named_counts(collection.get('models'))}",
        f"top events: {_format_named_counts(collection.get('top_events'))}",
        f"top tools: {_format_named_counts(collection.get('top_tools'))}",
    ]
    sessions = list(collection.get("sessions") or [])
    if not sessions:
        lines.append("recent sessions: (none)")
        return lines

    lines.append("recent sessions:")
    for index, session in enumerate(sessions, start=1):
        last_turn = session.get("last_turn_at") or session.get("updated_at") or "(unknown)"
        counts = (
            f"turns={session.get('turn_count', 0)}, "
            f"errors={session.get('error_count', 0)}, "
            f"pending={session.get('pending_approval_count', 0)}"
        )
        lines.append(
            f"{index}. {session.get('session_id') or '(unknown)'} | {last_turn} | "
            f"{counts} | {session.get('runtime') or '(unknown runtime)'}"
        )
        prompt = session.get("last_prompt_preview")
        if prompt:
            lines.append(f"   last prompt: {prompt}")
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


def _increment_count(counts: dict[str, int], name: str, amount: int = 1) -> None:
    counts[name] = counts.get(name, 0) + amount


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


def _summary_sort_key(summary: dict[str, Any]) -> tuple[str, str]:
    timestamp = (
        str(summary.get("last_turn_at") or "")
        or str(summary.get("updated_at") or "")
        or str(summary.get("created_at") or "")
    )
    return (timestamp, str(summary.get("session_id") or ""))
