from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .artifacts import SessionArtifactStore, SessionState, TurnArtifact

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50
MAX_TOOL_PREVIEW = 72
SESSION_SWITCHER_FILTER_MODES = {"all", "pending", "restore", "tool"}
SESSION_SWITCHER_SORT_MODES = {"recent", "attention"}


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
    last_tool_preview: str = ""
    last_tool_badges: list[str] = field(default_factory=list)
    restore_badges: list[str] = field(default_factory=list)

    def render_line(self, index: int) -> str:
        prompt_suffix = f" | last prompt: {self.last_prompt_preview}" if self.last_prompt_preview else ""
        pending_suffix = ""
        if self.pending_approval_count == 1 and self.pending_approval_tool:
            pending_suffix = f" | pending: {self.pending_approval_tool}"
        elif self.pending_approval_count > 1:
            tool_hint = f" ({self.pending_approval_tool} first)" if self.pending_approval_tool else ""
            pending_suffix = f" | pending: {self.pending_approval_count} approvals{tool_hint}"
        tool_hint = ""
        if self.last_tool_preview or self.last_tool_badges:
            badge_prefix = "/".join(self.last_tool_badges)
            if badge_prefix and self.last_tool_preview:
                tool_hint = f" | last tool: {badge_prefix} {self.last_tool_preview}"
            elif badge_prefix:
                tool_hint = f" | last tool: {badge_prefix}"
            else:
                tool_hint = f" | last tool: {self.last_tool_preview}"
        event_suffix = f" | last event: {self.last_event_preview}" if self.last_event_preview else ""
        restore_suffix = f" | restore: {', '.join(self.restore_badges)}" if self.restore_badges else ""
        return (
            f"{index}. {self.session_id} | {self.turn_count} turn(s) | "
            f"updated {self.updated_at}{pending_suffix}{restore_suffix}{prompt_suffix}{tool_hint}{event_suffix}"
        )


def list_recent_sessions(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
) -> list[SessionSummary]:
    resolved_root = Path(root).expanduser().resolve()
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if not resolved_root.exists() or not resolved_root.is_dir():
        return []

    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)

    session_dirs = [path for path in resolved_root.iterdir() if path.is_dir()]

    summaries_with_sort: list[tuple[float, str, SessionSummary]] = []
    for session_dir in session_dirs:
        store = SessionArtifactStore.from_session_dir(session_dir)
        turns = store.load_turns()
        session_state = store.load_session_state() or SessionState()
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
                    last_tool_preview=_latest_tool_preview(turns),
                    last_tool_badges=_latest_tool_badges(turns),
                    restore_badges=_restore_badges(session_state, len(turns)),
                ),
            )
        )

    filtered = [item for item in summaries_with_sort if _matches_filter(item[2], filter_mode)]
    ordered = sorted(filtered, key=lambda item: _sort_key(item, sort_mode), reverse=True)[:limit]
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


def _latest_tool_preview(turns: list[TurnArtifact]) -> str:
    event = _latest_tool_event(turns)
    if event is None:
        return ""
    preview = str(event.data.get("result_preview", "") or "").strip()
    if preview:
        return _truncate(preview, MAX_TOOL_PREVIEW)
    command = str(event.data.get("command", "") or "").strip()
    if event.title == "run_shell_command" and command:
        return _truncate(command, MAX_TOOL_PREVIEW)
    fallback = event.title or event.kind
    return _truncate(fallback, MAX_TOOL_PREVIEW)


def _latest_tool_badges(turns: list[TurnArtifact]) -> list[str]:
    event = _latest_tool_event(turns)
    if event is None:
        return []

    badges: list[str] = []
    shell_policy = str(event.data.get("shell_policy", "") or "").strip()
    if shell_policy:
        badges.append(shell_policy)

    exit_code = event.data.get("exit_code")
    if isinstance(exit_code, int):
        badges.append(f"e{exit_code}")
    elif event.kind == "tool_failed":
        badges.append("failed")

    return badges


def _latest_tool_event(turns: list[TurnArtifact]):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            if event.kind in {"tool_finished", "tool_failed"}:
                return event
    return None


def sanitize_session_switcher_filter_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_FILTER_MODES else "all"


def sanitize_session_switcher_sort_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_SORT_MODES else "recent"


def _matches_filter(summary: SessionSummary, filter_mode: str) -> bool:
    if filter_mode == "pending":
        return summary.pending_approval_count > 0
    if filter_mode == "restore":
        return bool(summary.restore_badges)
    if filter_mode == "tool":
        return bool(summary.last_tool_preview or summary.last_tool_badges)
    return True


def _sort_key(item: tuple[float, str, SessionSummary], sort_mode: str) -> tuple[object, ...]:
    activity_timestamp, session_id, summary = item
    if sort_mode == "attention":
        return (
            summary.pending_approval_count > 0,
            summary.pending_approval_count,
            bool(summary.restore_badges),
            bool(summary.last_tool_preview or summary.last_tool_badges),
            activity_timestamp,
            session_id,
        )
    return (activity_timestamp, session_id)


def _restore_badges(state: SessionState, turn_count: int) -> list[str]:
    badges: list[str] = []

    if state.event_filter != "all":
        badges.append(f"filter={state.event_filter}")

    if state.history_focus_index is not None:
        if turn_count > 0 and 0 <= state.history_focus_index < turn_count:
            badges.append(f"replay {state.history_focus_index + 1}/{turn_count}")
        else:
            badges.append("replay")

    if state.draft_prompt:
        badges.append(f"draft {len(state.draft_prompt)}c")

    if state.session_switcher_active:
        badges.append("chooser")

    return badges


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
