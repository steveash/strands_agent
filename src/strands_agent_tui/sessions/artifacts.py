from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC, datetime
from pathlib import Path

from strands_agent_tui.runtime import RuntimeEvent


@dataclass(slots=True)
class TurnArtifact:
    prompt: str
    response: str
    provider: str
    mode: str
    events: list[RuntimeEvent]
    response_metadata: dict[str, object] = field(default_factory=dict)
    error: bool = False
    created_at: str | None = None
    schema_version: str = "strands-agent/v1"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at or datetime.now(UTC).isoformat()
        payload["events"] = [event.as_dict() for event in self.events]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TurnArtifact":
        events_payload = payload.get("events") or []
        events = [
            RuntimeEvent(
                kind=str(event.get("kind", "unknown")),
                title=str(event.get("title", "")),
                detail=str(event.get("detail", "")),
                timestamp=str(event.get("timestamp")) if event.get("timestamp") else None,
                data=dict(event.get("data") or {}),
            )
            for event in events_payload
            if isinstance(event, dict)
        ]
        return cls(
            prompt=str(payload.get("prompt", "")),
            response=str(payload.get("response", "")),
            provider=str(payload.get("provider", "unknown")),
            mode=str(payload.get("mode", "unknown")),
            events=events,
            response_metadata=dict(payload.get("response_metadata") or {}),
            error=bool(payload.get("error", False)),
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            schema_version=str(payload.get("schema_version", "strands-agent/v1")),
        )


class SessionArtifactStore:
    def __init__(self, root: str | Path, session_id: str | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or datetime.now(UTC).strftime("session-%Y%m%dT%H%M%SZ")
        self.session_dir = self.root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "turns.jsonl"
        self.markdown_path = self.session_dir / "transcript.md"

    def append_turn(self, turn: TurnArtifact) -> None:
        payload = turn.as_dict()
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        self._append_markdown(payload)

    def load_turns(self) -> list[TurnArtifact]:
        if not self.jsonl_path.exists():
            return []

        turns: list[TurnArtifact] = []
        with self.jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                turns.append(TurnArtifact.from_dict(json.loads(stripped)))
        return turns

    @classmethod
    def from_session_dir(cls, session_dir: str | Path) -> "SessionArtifactStore":
        resolved = Path(session_dir).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(f"Session directory does not exist: {resolved}")
        return cls(resolved.parent, session_id=resolved.name)

    def _append_markdown(self, payload: dict[str, object]) -> None:
        event_lines: list[str] = []
        for event in payload["events"]:
            summary_bits = []
            if event.get("timestamp"):
                summary_bits.append(event["timestamp"])
            if event.get("data"):
                compact_data = ", ".join(f"{key}={value!r}" for key, value in sorted(event["data"].items()))
                summary_bits.append(compact_data)
            suffix = f" ({' | '.join(summary_bits)})" if summary_bits else ""
            event_lines.append(f"- `{event['kind']}` {event['title']}: {event['detail']}{suffix}")
        events_block = "\n".join(event_lines) if event_lines else "- none"
        metadata = payload.get("response_metadata") or {}
        metadata_lines = [f"- {key}: `{value}`" for key, value in sorted(metadata.items())]
        metadata_block = "\n".join(metadata_lines) if metadata_lines else "- none"
        error_suffix = " (error)" if payload.get("error") else ""
        body = (
            f"## {payload['created_at']}{error_suffix}\n\n"
            f"**Prompt**\n\n```text\n{payload['prompt']}\n```\n\n"
            f"**Response**\n\n```text\n{payload['response']}\n```\n\n"
            f"**Runtime**\n\n- provider: `{payload['provider']}`\n- mode: `{payload['mode']}`\n- schema: `{payload['schema_version']}`\n\n"
            f"**Response metadata**\n\n{metadata_block}\n\n"
            f"**Events**\n\n{events_block}\n\n"
        )
        if not self.markdown_path.exists():
            header = f"# Session transcript: {self.session_id}\n\n"
            self.markdown_path.write_text(header + body, encoding="utf-8")
        else:
            with self.markdown_path.open("a", encoding="utf-8") as handle:
                handle.write(body)
