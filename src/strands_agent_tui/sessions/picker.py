from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .artifacts import SessionArtifactStore, TurnArtifact

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    session_dir: Path
    turn_count: int
    updated_at: str
    last_prompt_preview: str = ""
    pending_approval_count: int = 0
    pending_approval_tool: str = ""
    last_event_preview: str = ""

    def render_line(self, index: int) -> str:
        prompt_suffix = f" | last prompt: {self.last_prompt_preview}" if self.last_prompt_preview else ""
        pending_suffix = ""
        if self.pending_approval_count == 1 and self.pending_approval_tool:
            pending_suffix = f" | pending: {self.pending_approval_tool}"
        elif self.pending_approval_count > 1:
            tool_hint = f" ({self.pending_approval_tool} first)" if self.pending_approval_tool else ""
            pending_suffix = f" | pending: {self.pending_approval_count} approvals{tool_hint}"
        event_suffix = f" | last event: {self.last_event_preview}" if self.last_event_preview else ""
        return (
            f"{index}. {self.session_id} | {self.turn_count} turn(s) | "
            f"updated {self.updated_at}{pending_suffix}{prompt_suffix}{event_suffix}"
        )


def list_recent_sessions(root: str | Path, limit: int = MAX_RECENT_SESSIONS) -> list[SessionSummary]:
    resolved_root = Path(root).expanduser().resolve()
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if not resolved_root.exists() or not resolved_root.is_dir():
        return []

    session_dirs = [path for path in resolved_root.iterdir() if path.is_dir()]

    summaries_with_sort: list[tuple[float, str, SessionSummary]] = []
    for session_dir in session_dirs:
        store = SessionArtifactStore.from_session_dir(session_dir)
        turns = store.load_turns()
        pending_approvals = store.load_pending_approvals()
        last_prompt_preview = ""
        if turns:
            last_prompt_preview = _truncate(turns[-1].prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
        activity_timestamp = _session_activity_timestamp(session_dir, turns)
        summaries_with_sort.append(
            (
                activity_timestamp,
                store.session_id,
                SessionSummary(
                    session_id=store.session_id,
                    session_dir=store.session_dir,
                    turn_count=len(turns),
                    updated_at=_format_timestamp(activity_timestamp),
                    last_prompt_preview=last_prompt_preview,
                    pending_approval_count=len(pending_approvals),
                    pending_approval_tool=pending_approvals[0].tool_name if pending_approvals else "",
                    last_event_preview=_latest_event_preview(turns),
                ),
            )
        )

    ordered = sorted(summaries_with_sort, key=lambda item: (item[0], item[1]), reverse=True)[:limit]
    return [summary for _, _, summary in ordered]


def latest_session(root: str | Path) -> SessionSummary | None:
    sessions = list_recent_sessions(root, limit=1)
    return sessions[0] if sessions else None


def render_session_picker(root: str | Path, limit: int = MAX_RECENT_SESSIONS) -> str:
    summaries = list_recent_sessions(root, limit=limit)
    resolved_root = Path(root).expanduser().resolve()
    if not summaries:
        return f"No saved sessions found under {resolved_root}."

    lines = [f"Recent sessions under {resolved_root}:", ""]
    lines.extend(summary.render_line(index) for index, summary in enumerate(summaries, start=1))
    lines.extend(["", "Press Enter to start a new session."])
    return "\n".join(lines)


def pick_session(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> SessionSummary | None:
    input_fn = input_fn or input
    output_fn = output_fn or print
    summaries = list_recent_sessions(root, limit=limit)
    if not summaries:
        output_fn(render_session_picker(root, limit=limit))
        output_fn("Starting a new session instead.")
        return None

    output_fn(render_session_picker(root, limit=limit))
    while True:
        selection = input_fn("Select session number to resume, or press Enter for a new session: ").strip()
        if not selection:
            return None
        if selection.isdigit():
            index = int(selection)
            if 1 <= index <= len(summaries):
                return summaries[index - 1]
        output_fn(f"Invalid selection: {selection!r}. Choose 1-{len(summaries)} or press Enter.")


def _session_activity_timestamp(session_dir: Path, turns: list[TurnArtifact] | None = None) -> float:
    timestamps = [session_dir.stat().st_mtime]
    for path in session_dir.iterdir():
        try:
            timestamps.append(path.stat().st_mtime)
        except FileNotFoundError:
            continue
    if turns:
        last_turn_timestamp = _turn_timestamp(turns[-1])
        if last_turn_timestamp is not None:
            timestamps.append(last_turn_timestamp)
    return max(timestamps)


def _turn_timestamp(turn: TurnArtifact) -> float | None:
    if not turn.created_at:
        return None
    return datetime.fromisoformat(turn.created_at).timestamp()


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _latest_event_preview(turns: list[TurnArtifact]) -> str:
    for turn in reversed(turns):
        for event in reversed(turn.events):
            preview = f"{event.kind}: {event.title}" if event.title else event.kind
            return _truncate(preview.replace("\n", " ").strip(), MAX_EVENT_PREVIEW)
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
