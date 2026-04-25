from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
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
    error: bool = False
    created_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at or datetime.now(UTC).isoformat()
        return payload


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

    def _append_markdown(self, payload: dict[str, object]) -> None:
        event_lines: list[str] = []
        for event in payload["events"]:
            event_lines.append(f"- `{event['kind']}` {event['title']}: {event['detail']}")
        events_block = "\n".join(event_lines) if event_lines else "- none"
        error_suffix = " (error)" if payload.get("error") else ""
        body = (
            f"## {payload['created_at']}{error_suffix}\n\n"
            f"**Prompt**\n\n```text\n{payload['prompt']}\n```\n\n"
            f"**Response**\n\n```text\n{payload['response']}\n```\n\n"
            f"**Runtime**\n\n- provider: `{payload['provider']}`\n- mode: `{payload['mode']}`\n\n"
            f"**Events**\n\n{events_block}\n\n"
        )
        if not self.markdown_path.exists():
            header = f"# Session transcript: {self.session_id}\n\n"
            self.markdown_path.write_text(header + body, encoding="utf-8")
        else:
            with self.markdown_path.open("a", encoding="utf-8") as handle:
                handle.write(body)
