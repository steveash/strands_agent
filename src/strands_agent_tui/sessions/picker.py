from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .artifacts import (
    SessionArtifactStore,
    SessionPickerState,
    SessionState,
    TurnArtifact,
    load_session_picker_state,
    save_session_picker_state,
)

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50
MAX_TOOL_PREVIEW = 72
MAX_TOOL_STREAK_PREVIEWS = 3
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
    pending_approval_summary: str = ""
    last_event_preview: str = ""
    last_tool_preview: str = ""
    last_tool_badges: list[str] = field(default_factory=list)
    recent_tool_previews: list[str] = field(default_factory=list)
    restore_badges: list[str] = field(default_factory=list)
    draft_prompt_preview: str = ""

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
        tool_streak_suffix = ""
        if len(self.recent_tool_previews) > 1:
            tool_streak_suffix = f" | tool streak: {len(self.recent_tool_previews)} recent"
        event_suffix = f" | last event: {self.last_event_preview}" if self.last_event_preview else ""
        restore_suffix = f" | restore: {', '.join(self.restore_badges)}" if self.restore_badges else ""
        return (
            f"{index}. {self.session_id} | {self.turn_count} turn(s) | "
            f"updated {self.updated_at}{pending_suffix}{restore_suffix}{prompt_suffix}{tool_hint}{tool_streak_suffix}{event_suffix}"
        )

    def render_preview(self, *, visible_index: int, overall_index: int, total_matches: int) -> list[str]:
        lines = [
            "Selected preview:",
            (
                f"- slot {visible_index} on this page | overall {overall_index} of {total_matches} | "
                f"session {self.session_id}"
            ),
            f"- artifact dir: {self.session_dir}",
        ]
        if self.pending_approval_count > 0:
            pending_line = self.pending_approval_summary or self.pending_approval_tool or "pending approval"
            if self.pending_approval_count > 1:
                pending_line = f"{self.pending_approval_count} approvals | first: {pending_line}"
            lines.append(f"- pending: {pending_line}")
        if self.restore_badges:
            lines.append(f"- restore: {', '.join(self.restore_badges)}")
        if self.draft_prompt_preview:
            lines.append(f"- draft: {self.draft_prompt_preview}")
        if self.last_prompt_preview:
            lines.append(f"- last prompt: {self.last_prompt_preview}")
        if self.last_tool_preview or self.last_tool_badges:
            badge_prefix = "/".join(self.last_tool_badges)
            if badge_prefix and self.last_tool_preview:
                lines.append(f"- last tool: {badge_prefix} {self.last_tool_preview}")
            elif badge_prefix:
                lines.append(f"- last tool: {badge_prefix}")
            else:
                lines.append(f"- last tool: {self.last_tool_preview}")
        if self.recent_tool_previews:
            lines.append(f"- recent tools ({len(self.recent_tool_previews)}):")
            lines.extend(f"  {index}. {preview}" for index, preview in enumerate(self.recent_tool_previews, start=1))
        if self.last_event_preview:
            lines.append(f"- last event: {self.last_event_preview}")
        return lines


def list_recent_sessions(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
    offset: int = 0,
) -> list[SessionSummary]:
    resolved_root = Path(root).expanduser().resolve()
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not resolved_root.exists() or not resolved_root.is_dir():
        return []

    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)

    return _ordered_recent_sessions(
        resolved_root,
        limit=limit,
        filter_mode=filter_mode,
        sort_mode=sort_mode,
        offset=offset,
    )


def count_recent_sessions(
    root: str | Path,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
) -> int:
    resolved_root = Path(root).expanduser().resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return 0

    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)
    return len(_ordered_recent_sessions(resolved_root, limit=None, filter_mode=filter_mode, sort_mode=sort_mode))


def _ordered_recent_sessions(
    resolved_root: Path,
    *,
    limit: int | None,
    filter_mode: str,
    sort_mode: str,
    offset: int = 0,
) -> list[SessionSummary]:
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
        draft_prompt_preview = ""
        if session_state.draft_prompt:
            draft_prompt_preview = _truncate(session_state.draft_prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
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
                    pending_approval_summary=pending_approvals[0].summary() if pending_approvals else "",
                    last_event_preview=_latest_event_preview(turns),
                    last_tool_preview=_latest_tool_preview(turns),
                    last_tool_badges=_latest_tool_badges(turns),
                    recent_tool_previews=_recent_tool_previews(turns),
                    restore_badges=_restore_badges(session_state, len(turns)),
                    draft_prompt_preview=draft_prompt_preview,
                ),
            )
        )

    filtered = [item for item in summaries_with_sort if _matches_filter(item[2], filter_mode)]
    ordered = sorted(filtered, key=lambda item: _sort_key(item, sort_mode), reverse=True)
    if offset:
        ordered = ordered[offset:]
    if limit is not None:
        ordered = ordered[:limit]
    return [summary for _, _, summary in ordered]


def latest_session(root: str | Path) -> SessionSummary | None:
    sessions = list_recent_sessions(root, limit=1)
    return sessions[0] if sessions else None


def render_session_picker(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
    page_index: int = 0,
    selected_index: int = 0,
) -> str:
    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)
    resolved_root = Path(root).expanduser().resolve()
    available_count = count_recent_sessions(resolved_root)
    if not available_count:
        return f"No saved sessions found under {resolved_root}."

    total_matches = count_recent_sessions(resolved_root, filter_mode=filter_mode, sort_mode=sort_mode)
    page_index = _normalize_picker_page_index(total_matches, limit, page_index)
    summaries = list_recent_sessions(
        root,
        limit=limit,
        filter_mode=filter_mode,
        sort_mode=sort_mode,
        offset=page_index * limit,
    )

    lines = [
        f"Recent sessions under {resolved_root}:",
        (
            f"Filter: {filter_mode} | Sort: {sort_mode} | "
            f"Page: {_picker_page_label(total_matches, limit, page_index)} | "
            f"Showing: {_picker_page_window_label(total_matches, limit, page_index, len(summaries))}"
        ),
        "",
    ]
    if not summaries:
        lines.append("No saved sessions match the active picker filter.")
    else:
        selected_index = _normalize_visible_selected_index(len(summaries), selected_index)
        for index, summary in enumerate(summaries, start=1):
            marker = ">" if index - 1 == selected_index else " "
            lines.append(f"{marker} {summary.render_line(index)}")
        lines.extend(
            [
                "",
                *summaries[selected_index].render_preview(
                    visible_index=selected_index + 1,
                    overall_index=page_index * limit + selected_index + 1,
                    total_matches=total_matches,
                ),
            ]
        )
    lines.extend(
        [
            "",
            "Picker controls: J/K preview, A all, P pending, R restore, T tool, S sort, [ prev page, ] next page, N new session",
            "Press Enter to reopen the highlighted session.",
        ]
    )
    return "\n".join(lines)


def pick_session(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    filter_mode: str | None = None,
    sort_mode: str | None = None,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> SessionSummary | None:
    input_fn = input_fn or input
    output_fn = output_fn or print
    resolved_root = Path(root).expanduser().resolve()
    persisted_state = load_session_picker_state(resolved_root)
    filter_mode, sort_mode, page_index, selected_index, selected_session_id = _initial_picker_state(
        persisted_state,
        filter_mode=filter_mode,
        sort_mode=sort_mode,
    )
    summaries = list_recent_sessions(resolved_root, limit=limit)
    if not summaries:
        output_fn(render_session_picker(resolved_root, limit=limit, filter_mode=filter_mode, sort_mode=sort_mode))
        output_fn("Starting a new session instead.")
        return None

    while True:
        total_matches = count_recent_sessions(resolved_root, filter_mode=filter_mode, sort_mode=sort_mode)
        page_index = _normalize_picker_page_index(total_matches, limit, page_index)
        current_summaries = list_recent_sessions(
            resolved_root,
            limit=limit,
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            offset=page_index * limit,
        )
        selected_index = _picker_selected_index_for_visible_page(
            current_summaries,
            selected_session_id,
            selected_index,
        )
        output_fn(
            render_session_picker(
                resolved_root,
                limit=limit,
                filter_mode=filter_mode,
                sort_mode=sort_mode,
                page_index=page_index,
                selected_index=selected_index,
            )
        )
        selection = input_fn(
            "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/R/T/S/[ / ] to triage/page: "
        ).strip()
        if not selection:
            if current_summaries:
                selected_index = _normalize_visible_selected_index(len(current_summaries), selected_index)
                selected_session_id = current_summaries[selected_index].session_id
                _persist_picker_state(
                    resolved_root,
                    filter_mode=filter_mode,
                    sort_mode=sort_mode,
                    page_index=page_index,
                    selected_index=selected_index,
                    summaries=current_summaries,
                )
                return current_summaries[selected_index]
            _persist_picker_state(
                resolved_root,
                filter_mode=filter_mode,
                sort_mode=sort_mode,
                page_index=page_index,
                selected_index=selected_index,
                summaries=current_summaries,
            )
            return None
        normalized = selection.lower()
        if normalized == "n":
            _persist_picker_state(
                resolved_root,
                filter_mode=filter_mode,
                sort_mode=sort_mode,
                page_index=page_index,
                selected_index=selected_index,
                summaries=current_summaries,
            )
            return None
        if normalized == "j":
            if current_summaries:
                selected_index = min(selected_index + 1, len(current_summaries) - 1)
                selected_session_id = current_summaries[selected_index].session_id
            continue
        if normalized == "k":
            if current_summaries:
                selected_index = max(selected_index - 1, 0)
                selected_session_id = current_summaries[selected_index].session_id
            continue
        if normalized == "a":
            filter_mode = "all"
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "p":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "pending")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "r":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "restore")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "t":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "tool")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "s":
            sort_mode = _cycle_picker_sort_mode(sort_mode)
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "[":
            if page_index == 0:
                output_fn("Already on the first picker page.")
            else:
                page_index -= 1
                selected_index = 0
                selected_session_id = ""
            continue
        if normalized == "]":
            if (page_index + 1) * limit >= total_matches:
                output_fn("Already on the last picker page.")
            else:
                page_index += 1
                selected_index = 0
                selected_session_id = ""
            continue
        if selection.isdigit():
            index = int(selection)
            if 1 <= index <= len(current_summaries):
                selected_index = index - 1
                selected_session_id = current_summaries[selected_index].session_id
                _persist_picker_state(
                    resolved_root,
                    filter_mode=filter_mode,
                    sort_mode=sort_mode,
                    page_index=page_index,
                    selected_index=selected_index,
                    summaries=current_summaries,
                )
                return current_summaries[selected_index]
            if current_summaries:
                output_fn(
                    f"Invalid selection: {selection!r}. Choose 1-{len(current_summaries)} from the visible list, press Enter to reopen highlighted, or N for a new session."
                )
            else:
                output_fn("No sessions are visible with the active filter. Use A, P, R, T, S, [, ], N, or press Enter to start a new session.")
            continue
        output_fn(f"Invalid selection. Use 1-{limit}, J, K, A, P, R, T, S, [, ], Enter, or N.")


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
    return _tool_event_preview(event)


def _latest_tool_badges(turns: list[TurnArtifact]) -> list[str]:
    event = _latest_tool_event(turns)
    if event is None:
        return []
    return _tool_event_badges(event)


def _recent_tool_previews(turns: list[TurnArtifact], limit: int = MAX_TOOL_STREAK_PREVIEWS) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_tool_events(turns):
        rendered = _render_tool_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    return previews


def _iter_recent_tool_events(turns: list[TurnArtifact]):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            if event.kind in {"tool_finished", "tool_failed"}:
                yield event


def _latest_tool_event(turns: list[TurnArtifact]):
    return next(_iter_recent_tool_events(turns), None)


def _tool_event_preview(event) -> str:
    preview = str(event.data.get("result_preview", "") or "").strip()
    if preview:
        return _truncate(preview, MAX_TOOL_PREVIEW)
    command = str(event.data.get("command", "") or "").strip()
    if event.title == "run_shell_command" and command:
        return _truncate(command, MAX_TOOL_PREVIEW)
    fallback = event.title or event.kind
    return _truncate(fallback, MAX_TOOL_PREVIEW)


def _tool_event_badges(event) -> list[str]:
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


def _render_tool_event_summary(event) -> str:
    preview = _tool_event_preview(event)
    badges = _tool_event_badges(event)
    badge_prefix = "/".join(badges)
    if badge_prefix and preview:
        return _truncate(f"{badge_prefix} {preview}", MAX_TOOL_PREVIEW)
    if badge_prefix:
        return _truncate(badge_prefix, MAX_TOOL_PREVIEW)
    return preview


def sanitize_session_switcher_filter_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_FILTER_MODES else "all"


def sanitize_session_switcher_sort_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_SORT_MODES else "recent"


def _toggle_picker_filter_mode(current_filter_mode: str, next_filter_mode: str) -> str:
    if current_filter_mode == next_filter_mode:
        return "all"
    return sanitize_session_switcher_filter_mode(next_filter_mode)


def _cycle_picker_sort_mode(current_sort_mode: str) -> str:
    if current_sort_mode == "recent":
        return "attention"
    return "recent"


def _normalize_visible_selected_index(visible_count: int, selected_index: int) -> int:
    if visible_count <= 0:
        return 0
    return max(0, min(selected_index, visible_count - 1))


def _normalize_picker_page_index(total_matches: int, limit: int, page_index: int) -> int:
    if total_matches <= 0:
        return 0
    max_page_index = (total_matches - 1) // limit
    return max(0, min(page_index, max_page_index))


def _picker_page_label(total_matches: int, limit: int, page_index: int) -> str:
    if total_matches <= 0:
        return "0/0"
    total_pages = ((total_matches - 1) // limit) + 1
    return f"{page_index + 1}/{total_pages}"


def _picker_page_window_label(total_matches: int, limit: int, page_index: int, visible_count: int) -> str:
    if total_matches <= 0 or visible_count <= 0:
        return "0 of 0"
    start = page_index * limit + 1
    end = start + visible_count - 1
    return f"{start}-{end} of {total_matches}"


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
        chooser_badge = "chooser"
        if state.session_switcher_page_index > 0:
            chooser_badge = f"chooser p{state.session_switcher_page_index + 1}"
        badges.append(chooser_badge)

    return badges


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _initial_picker_state(
    persisted_state: SessionPickerState | None,
    *,
    filter_mode: str | None,
    sort_mode: str | None,
) -> tuple[str, str, int, int, str]:
    state = persisted_state or SessionPickerState()
    selected_session_id = state.selected_session_id
    page_index = state.page_index
    selected_index = state.selected_index
    effective_filter = sanitize_session_switcher_filter_mode(state.filter_mode)
    effective_sort = sanitize_session_switcher_sort_mode(state.sort_mode)
    if filter_mode is not None:
        effective_filter = sanitize_session_switcher_filter_mode(filter_mode)
        page_index = 0
        selected_index = 0
        selected_session_id = ""
    if sort_mode is not None:
        effective_sort = sanitize_session_switcher_sort_mode(sort_mode)
        page_index = 0
        selected_index = 0
        selected_session_id = ""
    return effective_filter, effective_sort, page_index, selected_index, selected_session_id


def _picker_selected_index_for_visible_page(
    summaries: list[SessionSummary],
    selected_session_id: str,
    fallback_index: int,
) -> int:
    if not summaries:
        return 0
    if selected_session_id:
        for index, summary in enumerate(summaries):
            if summary.session_id == selected_session_id:
                return index
    return _normalize_visible_selected_index(len(summaries), fallback_index)


def _persist_picker_state(
    root: Path,
    *,
    filter_mode: str,
    sort_mode: str,
    page_index: int,
    selected_index: int,
    summaries: list[SessionSummary],
) -> None:
    selected_index = _normalize_visible_selected_index(len(summaries), selected_index)
    selected_session_id = summaries[selected_index].session_id if summaries else ""
    save_session_picker_state(
        root,
        SessionPickerState(
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            page_index=page_index,
            selected_index=selected_index,
            selected_session_id=selected_session_id,
        ),
    )
