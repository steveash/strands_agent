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
from ..runtime import ApprovalRequest
from ..tools.workspace import resolve_shell_command

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50
MAX_TOOL_PREVIEW = 72
MAX_TOOL_STREAK_PREVIEWS = 3
MAX_SHELL_STREAK_PREVIEWS = 3
MAX_SHELL_ROLLUP_EVENTS = 6
MAX_FAILURE_ROLLUP_EVENTS = 6
APPROVAL_STATUS_DISPLAY_ORDER = ("pending", "approved", "denied", "blocked")
APPROVAL_TOOL_FAMILY_DISPLAY_ORDER = ("test", "edit", "shell", "tool")
SESSION_SWITCHER_FILTER_MODES = {"all", "pending", "denied", "restore", "approval-restore", "tool", "shell"}
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
    pending_approval_queue_summary: str = ""
    pending_approval_badges: list[str] = field(default_factory=list)
    approval_status_badges: list[str] = field(default_factory=list)
    approval_focus_badges: list[str] = field(default_factory=list)
    last_approval_summary: str = ""
    denied_approval_count: int = 0
    denied_approval_badges: list[str] = field(default_factory=list)
    last_denied_approval_summary: str = ""
    restored_approval_count: int = 0
    restored_approval_badges: list[str] = field(default_factory=list)
    restored_approval_tool_badges: list[str] = field(default_factory=list)
    restored_pending_approval_queue_summary: str = ""
    last_restored_approval_summary: str = ""
    pending_approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    denied_approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    attention_reason_summary: str = ""
    last_event_preview: str = ""
    last_tool_preview: str = ""
    last_tool_badges: list[str] = field(default_factory=list)
    recent_tool_previews: list[str] = field(default_factory=list)
    shell_activity_badges: list[str] = field(default_factory=list)
    last_shell_preview: str = ""
    recent_shell_previews: list[str] = field(default_factory=list)
    failure_activity_badges: list[str] = field(default_factory=list)
    recent_failure_count: int = 0
    recent_shell_failure_count: int = 0
    recent_test_failure_count: int = 0
    recent_tool_failure_count: int = 0
    restore_badges: list[str] = field(default_factory=list)
    draft_prompt_preview: str = ""

    def render_line(self, index: int, *, include_attention_reason: bool = False) -> str:
        prompt_suffix = f" | last prompt: {self.last_prompt_preview}" if self.last_prompt_preview else ""
        pending_suffix = ""
        if self.pending_approval_count == 1 and self.pending_approval_tool:
            pending_suffix = f" | pending: {self.pending_approval_tool}"
        elif self.pending_approval_count > 1:
            tool_hint = f" ({self.pending_approval_queue_summary})" if self.pending_approval_queue_summary else ""
            pending_suffix = f" | pending: {self.pending_approval_count} approvals{tool_hint}"
        pending_tool_suffix = (
            f" | pending tools: {', '.join(self.pending_approval_badges)}" if self.pending_approval_badges else ""
        )
        approval_suffix = (
            f" | approvals: {', '.join(self.approval_status_badges)}" if self.approval_status_badges else ""
        )
        approval_focus_suffix = (
            f" | approval focus: {'/'.join(self.approval_focus_badges)}" if self.approval_focus_badges else ""
        )
        denied_suffix = f" | denied: {', '.join(self.denied_approval_badges)}" if self.denied_approval_badges else ""
        approval_restore_suffix = (
            f" | approval restore: {', '.join(self.restored_approval_badges)}"
            if self.restored_approval_badges
            else ""
        )
        approval_restore_tool_suffix = (
            f" | approval restore tools: {', '.join(self.restored_approval_tool_badges)}"
            if self.restored_approval_tool_badges
            else ""
        )
        approval_restore_queue_suffix = (
            f" | approval restore queue: {self.restored_pending_approval_queue_summary}"
            if self.restored_pending_approval_queue_summary
            else ""
        )
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
        shell_suffix = (
            f" | shell: {', '.join(self.shell_activity_badges)}" if self.shell_activity_badges else ""
        )
        failure_suffix = (
            f" | failures: {', '.join(self.failure_activity_badges)}" if self.failure_activity_badges else ""
        )
        attention_suffix = ""
        attention_badge = _attention_reason_badge(self) if include_attention_reason and self.attention_reason_summary else ""
        if attention_badge and not _is_redundant_attention_badge(self, attention_badge):
            attention_suffix = f" | attention: {attention_badge}"
        event_suffix = f" | last event: {self.last_event_preview}" if self.last_event_preview else ""
        restore_suffix = f" | restore: {', '.join(self.restore_badges)}" if self.restore_badges else ""
        return (
            f"{index}. {self.session_id} | {self.turn_count} turn(s) | "
            f"updated {self.updated_at}{pending_suffix}{pending_tool_suffix}{approval_suffix}{approval_focus_suffix}{denied_suffix}{approval_restore_suffix}{approval_restore_tool_suffix}{approval_restore_queue_suffix}{attention_suffix}{restore_suffix}{prompt_suffix}{tool_hint}{tool_streak_suffix}{shell_suffix}{failure_suffix}{event_suffix}"
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
        if self.attention_reason_summary:
            lines.append(f"- attention reason: {self.attention_reason_summary}")
        if self.pending_approval_count > 0:
            pending_line = self.pending_approval_summary or self.pending_approval_tool or "pending approval"
            if self.pending_approval_count > 1:
                pending_line = f"{self.pending_approval_count} approvals | first: {pending_line}"
            lines.append(f"- pending: {pending_line}")
        if self.pending_approval_queue_summary:
            lines.append(f"- pending queue: {self.pending_approval_queue_summary}")
        if self.pending_approval_badges:
            lines.append(f"- pending tools: {', '.join(self.pending_approval_badges)}")
        if self.approval_status_badges:
            lines.append(f"- approvals: {', '.join(self.approval_status_badges)}")
        if self.approval_focus_badges:
            lines.append(f"- approval focus: {'/'.join(self.approval_focus_badges)}")
        if self.last_approval_summary:
            lines.append(f"- last approval: {self.last_approval_summary}")
        if self.denied_approval_badges:
            lines.append(f"- denied: {', '.join(self.denied_approval_badges)}")
        if self.last_denied_approval_summary:
            lines.append(f"- last denied approval: {self.last_denied_approval_summary}")
        if self.restored_approval_badges:
            lines.append(f"- approval restore: {', '.join(self.restored_approval_badges)}")
        if self.restored_approval_tool_badges:
            lines.append(f"- approval restore tools: {', '.join(self.restored_approval_tool_badges)}")
        if self.restored_pending_approval_queue_summary:
            lines.append(f"- approval restore queue: {self.restored_pending_approval_queue_summary}")
        if self.last_restored_approval_summary:
            lines.append(f"- last restored approval: {self.last_restored_approval_summary}")
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
        if self.shell_activity_badges:
            lines.append(f"- shell: {', '.join(self.shell_activity_badges)}")
        if self.failure_activity_badges:
            lines.append(f"- failures: {', '.join(self.failure_activity_badges)}")
        if self.last_shell_preview:
            lines.append(f"- last shell: {self.last_shell_preview}")
        if self.recent_shell_previews:
            lines.append(f"- recent shell outcomes ({len(self.recent_shell_previews)}):")
            lines.extend(f"  {index}. {preview}" for index, preview in enumerate(self.recent_shell_previews, start=1))
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
        (
            pending_approval_badges,
            approval_status_badges,
            approval_focus_badges,
            last_approval_summary,
            denied_approval_count,
            denied_approval_badges,
            last_denied_approval_summary,
            restored_approval_count,
            restored_approval_badges,
            restored_approval_tool_badges,
            last_restored_approval_summary,
            pending_approval_attention_sort_key,
            approval_attention_sort_key,
            denied_approval_attention_sort_key,
        ) = _approval_activity(turns, pending_approvals)
        last_prompt_preview = ""
        if turns:
            last_prompt_preview = _truncate(turns[-1].prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
        draft_prompt_preview = ""
        if session_state.draft_prompt:
            draft_prompt_preview = _truncate(session_state.draft_prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
        activity_timestamp = _session_activity_timestamp(session_dir, turns)
        recent_failure_count = _recent_tool_failure_count(turns)
        recent_shell_failure_count = _recent_shell_failure_count(turns)
        recent_test_failure_count, recent_tool_failure_count = _recent_failure_activity_counts(turns)
        summary = SessionSummary(
            session_id=store.session_id,
            session_dir=store.session_dir,
            turn_count=len(turns),
            updated_at=_format_timestamp(activity_timestamp),
            last_prompt_preview=last_prompt_preview,
            pending_approval_count=len(pending_approvals),
            pending_approval_tool=pending_approvals[0].tool_name if pending_approvals else "",
            pending_approval_summary=pending_approvals[0].summary() if pending_approvals else "",
            pending_approval_queue_summary=_pending_approval_queue_summary(pending_approvals),
            pending_approval_badges=pending_approval_badges,
            approval_status_badges=approval_status_badges,
            approval_focus_badges=approval_focus_badges,
            last_approval_summary=last_approval_summary,
            denied_approval_count=denied_approval_count,
            denied_approval_badges=denied_approval_badges,
            last_denied_approval_summary=last_denied_approval_summary,
            restored_approval_count=restored_approval_count,
            restored_approval_badges=restored_approval_badges,
            restored_approval_tool_badges=restored_approval_tool_badges,
            restored_pending_approval_queue_summary=_restored_pending_approval_queue_summary(pending_approvals),
            last_restored_approval_summary=last_restored_approval_summary,
            pending_approval_attention_sort_key=pending_approval_attention_sort_key,
            approval_attention_sort_key=approval_attention_sort_key,
            denied_approval_attention_sort_key=denied_approval_attention_sort_key,
            last_event_preview=_latest_event_preview(turns),
            last_tool_preview=_latest_tool_preview(turns),
            last_tool_badges=_latest_tool_badges(turns),
            recent_tool_previews=_recent_tool_previews(turns),
            shell_activity_badges=_shell_activity_badges(turns),
            last_shell_preview=_latest_shell_preview(turns),
            recent_shell_previews=_recent_shell_previews(turns),
            failure_activity_badges=_failure_activity_badges(
                recent_test_failure_count,
                recent_tool_failure_count,
            ),
            recent_failure_count=recent_failure_count,
            recent_shell_failure_count=recent_shell_failure_count,
            recent_test_failure_count=recent_test_failure_count,
            recent_tool_failure_count=recent_tool_failure_count,
            restore_badges=_restore_badges(session_state, len(turns)),
            draft_prompt_preview=draft_prompt_preview,
        )
        summary.attention_reason_summary = _attention_reason_summary(summary)
        summaries_with_sort.append((activity_timestamp, store.session_id, summary))

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
        lines.extend(
            render_recent_session_empty_state_lines(
                available_count=available_count,
                filter_mode=filter_mode,
                surface="picker",
            )
        )
    else:
        selected_index = _normalize_visible_selected_index(len(summaries), selected_index)
        for index, summary in enumerate(summaries, start=1):
            marker = ">" if index - 1 == selected_index else " "
            lines.append(
                f"{marker} {summary.render_line(index, include_attention_reason=sort_mode == 'attention')}"
            )
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
            "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, T tool, H shell, S sort, [ prev page, ] next page, N new session",
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
        prompt = (
            "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/D/R/V/T/H/S/[ / ] to triage/page: "
            if current_summaries
            else "No sessions match this filter. Press Enter or N for a new session, or use A/P/D/R/V/T/H/S/[ / ] to change triage: "
        )
        selection = input_fn(prompt).strip()
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
        if normalized == "d":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "denied")
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
        if normalized == "v":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "approval-restore")
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
        if normalized == "h":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "shell")
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
                output_fn(
                    "No sessions are visible with the active filter. Press A to show all sessions, or P/D/R/V/T/H/S/[ / ] to keep triaging; Enter or N starts a new session."
                )
            continue
        if current_summaries:
            output_fn(f"Invalid selection. Use 1-{limit}, J, K, A, P, D, R, V, T, H, S, [, ], Enter, or N.")
        else:
            output_fn(
                "No sessions match the active filter. Use A/P/D/R/V/T/H/S/[ / ] to adjust triage, or press Enter/N to start a new session."
            )


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


def _iter_recent_tool_events(turns: list[TurnArtifact], *, tool_name: str | None = None):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            if event.kind in {"tool_finished", "tool_failed"}:
                if tool_name is not None and str(event.data.get("tool_name", "") or event.title or "") != tool_name:
                    continue
                yield event


def _latest_tool_event(turns: list[TurnArtifact]):
    return next(_iter_recent_tool_events(turns), None)


def _latest_shell_preview(turns: list[TurnArtifact]) -> str:
    event = next(_iter_recent_tool_events(turns, tool_name="run_shell_command"), None)
    if event is None:
        return ""
    return _render_tool_event_summary(event)


def _recent_shell_previews(turns: list[TurnArtifact], limit: int = MAX_SHELL_STREAK_PREVIEWS) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_tool_events(turns, tool_name="run_shell_command"):
        rendered = _render_tool_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    return previews


def _shell_activity_badges(turns: list[TurnArtifact], count_window: int = MAX_SHELL_ROLLUP_EVENTS) -> list[str]:
    events = list(_bounded_recent_tool_events(turns, tool_name="run_shell_command", limit=count_window))
    if not events:
        return []

    inspect_count = 0
    test_count = 0
    failure_count = 0
    for event in events:
        if _is_test_shell_event(event):
            test_count += 1
        else:
            inspect_count += 1
        if _is_tool_failure_event(event):
            failure_count += 1

    badges: list[str] = []
    if inspect_count:
        badges.append(f"inspect {inspect_count}")
    if test_count:
        badges.append(f"test {test_count}")
    if failure_count:
        badges.append(f"fail {failure_count}")
    return badges


def _bounded_recent_tool_events(
    turns: list[TurnArtifact],
    *,
    tool_name: str | None = None,
    limit: int,
) -> list[object]:
    events = []
    for event in _iter_recent_tool_events(turns, tool_name=tool_name):
        events.append(event)
        if len(events) >= limit:
            break
    return events


def _recent_tool_failure_count(turns: list[TurnArtifact], count_window: int = MAX_FAILURE_ROLLUP_EVENTS) -> int:
    return sum(1 for event in _bounded_recent_tool_events(turns, limit=count_window) if _is_tool_failure_event(event))


def _recent_shell_failure_count(turns: list[TurnArtifact], count_window: int = MAX_FAILURE_ROLLUP_EVENTS) -> int:
    return sum(
        1
        for event in _bounded_recent_tool_events(turns, tool_name="run_shell_command", limit=count_window)
        if _is_tool_failure_event(event)
    )


def _recent_failure_activity_counts(
    turns: list[TurnArtifact],
    count_window: int = MAX_FAILURE_ROLLUP_EVENTS,
) -> tuple[int, int]:
    test_failure_count = 0
    tool_failure_count = 0
    for event in _bounded_recent_tool_events(turns, limit=count_window):
        if not _is_tool_failure_event(event):
            continue
        if _is_test_shell_event(event):
            test_failure_count += 1
        else:
            tool_failure_count += 1
    return test_failure_count, tool_failure_count


def _failure_activity_badges(test_failure_count: int, tool_failure_count: int) -> list[str]:
    badges: list[str] = []
    if test_failure_count:
        badges.append(f"test {test_failure_count}")
    if tool_failure_count:
        badges.append(f"tool {tool_failure_count}")
    return badges


def _is_tool_failure_event(event) -> bool:
    if event.kind == "tool_failed":
        return True
    exit_code = event.data.get("exit_code")
    return isinstance(exit_code, int) and exit_code != 0


def _is_shell_tool_event(event) -> bool:
    return str(event.data.get("tool_name", "") or event.title or "") == "run_shell_command"


def _is_test_shell_event(event) -> bool:
    if not _is_shell_tool_event(event):
        return False
    shell_policy = str(event.data.get("shell_policy", "") or "").strip()
    if shell_policy:
        return shell_policy != "inspect"
    shell_family = str(event.data.get("shell_command_family", "") or "").strip()
    return shell_family.startswith("pytest")


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


def _approval_activity(
    turns: list[TurnArtifact],
    pending_approvals,
) -> tuple[
    list[str],
    list[str],
    list[str],
    str,
    int,
    list[str],
    str,
    int,
    list[str],
    list[str],
    str,
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    latest_by_request_id: dict[str, dict[str, object]] = {}
    last_record: dict[str, object] | None = None
    last_denied_record: dict[str, object] | None = None
    last_restored_record: dict[str, object] | None = None
    order = 0

    for turn in turns:
        for event in turn.events:
            approval_id = str(event.data.get("approval_id", "") or "").strip()
            status = str(event.data.get("approval_status", "") or "").strip()
            if not approval_id or not status:
                continue
            order += 1
            record = {
                "approval_id": approval_id,
                "status": status,
                "tool_name": str(event.data.get("tool_name", "") or event.title or "").strip(),
                "source": str(event.data.get("approval_source", "") or event.data.get("source", "") or "runtime").strip(),
                "command": str(event.data.get("command", "") or "").strip(),
                "shell_command_family": str(event.data.get("shell_command_family", "") or "").strip(),
                "pending_count": event.data.get("pending_count"),
                "remaining_pending_count": event.data.get("remaining_pending_count"),
                "resumed_from_approval": bool(event.data.get("resumed_from_approval", False)),
                "approval_restored": bool(event.data.get("approval_restored", False)),
                "order": order,
            }
            latest_by_request_id[approval_id] = record
            last_record = record
            if status == "denied":
                last_denied_record = record
            if bool(record.get("approval_restored", False)):
                last_restored_record = record

    for approval in pending_approvals:
        command = str(approval.args.get("command", "") or "").strip() if isinstance(approval.args, dict) else ""
        shell_command_family = ""
        if command:
            try:
                shell_command_family = resolve_shell_command(command).family
            except ValueError:
                shell_command_family = ""
        existing_record = latest_by_request_id.get(approval.request_id)
        if existing_record is not None:
            if command and not str(existing_record.get("command", "") or "").strip():
                existing_record["command"] = command
            if shell_command_family and not str(existing_record.get("shell_command_family", "") or "").strip():
                existing_record["shell_command_family"] = shell_command_family
            if approval.tool_name and not str(existing_record.get("tool_name", "") or "").strip():
                existing_record["tool_name"] = approval.tool_name
            existing_record["pending_count"] = len(pending_approvals)
            if approval.restored_from_session:
                existing_record["approval_restored"] = True
            continue
        record = {
            "approval_id": approval.request_id,
            "status": "pending",
            "tool_name": approval.tool_name,
            "source": approval.source,
            "command": command,
            "shell_command_family": shell_command_family,
            "pending_count": len(pending_approvals),
            "remaining_pending_count": None,
            "resumed_from_approval": False,
            "approval_restored": approval.restored_from_session,
            "order": order,
        }
        latest_by_request_id[approval.request_id] = record
        if last_record is None:
            last_record = record

    if pending_approvals:
        preferred_pending = latest_by_request_id.get(pending_approvals[0].request_id)
        if preferred_pending is not None:
            last_record = preferred_pending
            if bool(preferred_pending.get("approval_restored", False)):
                last_restored_record = preferred_pending

    status_counts: dict[str, int] = {}
    fresh_pending_family_counts: dict[str, int] = {}
    denied_family_counts: dict[str, int] = {}
    restored_status_counts: dict[str, int] = {}
    restored_pending_family_counts: dict[str, int] = {}
    restored_denied_family_counts: dict[str, int] = {}
    restored_family_counts: dict[str, int] = {}
    for record in latest_by_request_id.values():
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        family = _approval_tool_family(record)
        if status == "pending" and not bool(record.get("approval_restored", False)):
            fresh_pending_family_counts[family] = fresh_pending_family_counts.get(family, 0) + 1
        if status == "denied":
            denied_family_counts[family] = denied_family_counts.get(family, 0) + 1
        if bool(record.get("approval_restored", False)):
            restored_status_counts[status] = restored_status_counts.get(status, 0) + 1
            restored_family_counts[family] = restored_family_counts.get(family, 0) + 1
            if status == "pending":
                restored_pending_family_counts[family] = restored_pending_family_counts.get(family, 0) + 1
            elif status == "denied":
                restored_denied_family_counts[family] = restored_denied_family_counts.get(family, 0) + 1
            if last_restored_record is None or int(record.get("order", 0)) >= int(last_restored_record.get("order", 0)):
                last_restored_record = record
        if status == "denied" and (
            last_denied_record is None or int(record.get("order", 0)) >= int(last_denied_record.get("order", 0))
        ):
            last_denied_record = record

    badges = _render_status_badges(status_counts)
    pending_badges = _render_tool_family_badges(fresh_pending_family_counts)
    denied_badges = _render_tool_family_badges(denied_family_counts)
    restored_badges = _render_status_badges(restored_status_counts)
    restored_tool_badges = _render_tool_family_badges(restored_family_counts)
    pending_approval_attention_sort_key = _tool_family_attention_sort_key(fresh_pending_family_counts)
    approval_attention_sort_key = _approval_attention_sort_key(
        restored_pending_family_counts,
        restored_denied_family_counts,
        restored_family_counts,
    )
    denied_approval_attention_sort_key = _tool_family_attention_sort_key(denied_family_counts)

    return (
        pending_badges,
        badges,
        _render_approval_focus_badges(last_record),
        _render_last_approval_summary(last_record),
        status_counts.get("denied", 0),
        denied_badges,
        _render_last_approval_summary(last_denied_record),
        sum(restored_status_counts.values()),
        restored_badges,
        restored_tool_badges,
        _render_last_approval_summary(last_restored_record),
        pending_approval_attention_sort_key,
        approval_attention_sort_key,
        denied_approval_attention_sort_key,
    )


def _render_status_badges(status_counts: dict[str, int]) -> list[str]:
    badges: list[str] = []
    for status in APPROVAL_STATUS_DISPLAY_ORDER:
        count = status_counts.get(status, 0)
        if count:
            badges.append(f"{status} {count}")
    for status in sorted(status_counts):
        if status in APPROVAL_STATUS_DISPLAY_ORDER:
            continue
        badges.append(f"{status} {status_counts[status]}")
    return badges


def _render_tool_family_badges(tool_family_counts: dict[str, int]) -> list[str]:
    badges: list[str] = []
    for family in APPROVAL_TOOL_FAMILY_DISPLAY_ORDER:
        count = tool_family_counts.get(family, 0)
        if count:
            badges.append(f"{family} {count}")
    for family in sorted(tool_family_counts):
        if family in APPROVAL_TOOL_FAMILY_DISPLAY_ORDER:
            continue
        badges.append(f"{family} {tool_family_counts[family]}")
    return badges


def _approval_queue_summary(approvals: list[ApprovalRequest]) -> str:
    if len(approvals) <= 1:
        return ""

    first_approval = approvals[0]
    first_family = _approval_tool_family_for_values(
        tool_name=str(first_approval.tool_name or ""),
        command=_approval_command_from_args(first_approval.args),
        shell_command_family="",
    ) or str(first_approval.tool_name or "approval")

    remaining_family_counts: dict[str, int] = {}
    for approval in approvals[1:]:
        family = _approval_tool_family_for_values(
            tool_name=str(approval.tool_name or ""),
            command=_approval_command_from_args(approval.args),
            shell_command_family="",
        )
        remaining_family_counts[family] = remaining_family_counts.get(family, 0) + 1

    remaining_badges = _render_tool_family_badges(remaining_family_counts)
    if remaining_badges:
        return f"first {first_family}; rest {', '.join(remaining_badges)}"
    return f"first {first_family}"


def _pending_approval_queue_summary(pending_approvals: list[ApprovalRequest]) -> str:
    return _approval_queue_summary(pending_approvals)


def _restored_pending_approval_queue_summary(pending_approvals: list[ApprovalRequest]) -> str:
    restored_pending = [approval for approval in pending_approvals if approval.restored_from_session]
    return _approval_queue_summary(restored_pending)


def _approval_command_from_args(args: object) -> str:
    if not isinstance(args, dict):
        return ""
    return str(args.get("command", "") or "").strip()


def _tool_family_attention_sort_key(tool_family_counts: dict[str, int]) -> tuple[int, ...]:
    families = (*APPROVAL_TOOL_FAMILY_DISPLAY_ORDER,)
    return tuple(tool_family_counts.get(family, 0) for family in families)


def _approval_attention_sort_key(
    restored_pending_family_counts: dict[str, int],
    restored_denied_family_counts: dict[str, int],
    restored_family_counts: dict[str, int],
) -> tuple[int, ...]:
    return (
        *_tool_family_attention_sort_key(restored_pending_family_counts),
        *_tool_family_attention_sort_key(restored_denied_family_counts),
        *_tool_family_attention_sort_key(restored_family_counts),
    )


def _approval_attention_family_keys(
    summary: SessionSummary,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    family_count = len(APPROVAL_TOOL_FAMILY_DISPLAY_ORDER)
    approval_attention_sort_key = summary.approval_attention_sort_key or (0,) * (family_count * 3)
    restored_pending_key = approval_attention_sort_key[:family_count]
    restored_denied_key = approval_attention_sort_key[family_count : family_count * 2]
    restored_family_key = approval_attention_sort_key[family_count * 2 : family_count * 3]
    denied_key = summary.denied_approval_attention_sort_key or (0,) * family_count
    fresh_denied_key = tuple(
        max(denied_count - restored_count, 0)
        for denied_count, restored_count in zip(denied_key, restored_denied_key, strict=False)
    )
    return restored_pending_key, restored_denied_key, restored_family_key, denied_key, fresh_denied_key


def _attention_reason_summary(summary: SessionSummary) -> str:
    restored_pending_key, restored_denied_key, restored_family_key, denied_key, fresh_denied_key = (
        _approval_attention_family_keys(summary)
    )

    restored_pending_family = _first_attention_family(restored_pending_key)
    if restored_pending_family:
        if restored_pending_family == "test":
            return "restored pending test approval queue; tests sort ahead of restored edits"
        if restored_pending_family == "edit":
            return "restored pending edit approval queue; restored tests sort ahead of this queue"
        return f"restored pending {restored_pending_family} approval queue"

    pending_family = _first_attention_family(summary.pending_approval_attention_sort_key)
    if pending_family:
        if pending_family == "test":
            return "pending test approval queue"
        if pending_family == "edit":
            return "pending edit approval queue; tests sort ahead of edits"
        return f"pending {pending_family} approval queue"

    if summary.pending_approval_count > 0:
        return "pending approval queue"

    denied_family = _first_attention_family(denied_key)
    if denied_family:
        denied_family_index = APPROVAL_TOOL_FAMILY_DISPLAY_ORDER.index(denied_family)
        if fresh_denied_key[denied_family_index] > 0:
            return f"denied {denied_family} approval"
        if restored_denied_key[denied_family_index] > 0:
            return f"restored denied {denied_family} approval"

    if summary.denied_approval_count > 0:
        return "denied approval"

    if summary.recent_test_failure_count > 0:
        return "recent shell test failure"

    if summary.recent_tool_failure_count > 0:
        return "recent tool failure"

    if summary.recent_failure_count > 0:
        return "recent failure activity"

    restored_family = _first_attention_family(restored_family_key)
    if restored_family:
        return f"restored {restored_family} approval activity"

    if summary.restore_badges:
        return "saved restore context"

    if summary.last_shell_preview or summary.shell_activity_badges:
        return "recent shell activity"

    if summary.last_tool_preview or summary.last_tool_badges:
        return "recent tool activity"

    return ""


def _attention_reason_badge(summary: SessionSummary) -> str:
    restored_pending_key, restored_denied_key, restored_family_key, denied_key, fresh_denied_key = (
        _approval_attention_family_keys(summary)
    )

    restored_pending_family = _first_attention_family(restored_pending_key)
    if restored_pending_family:
        return f"restored {restored_pending_family} queue"

    pending_family = _first_attention_family(summary.pending_approval_attention_sort_key)
    if pending_family:
        return f"pending {pending_family}"

    if summary.pending_approval_count > 0:
        return "pending queue"

    denied_family = _first_attention_family(denied_key)
    if denied_family:
        denied_family_index = APPROVAL_TOOL_FAMILY_DISPLAY_ORDER.index(denied_family)
        if fresh_denied_key[denied_family_index] > 0:
            return f"denied {denied_family}"
        if restored_denied_key[denied_family_index] > 0:
            return f"restored denied {denied_family}"

    if summary.denied_approval_count > 0:
        return "denied"

    if summary.recent_test_failure_count > 0:
        return "test fail"

    if summary.recent_tool_failure_count > 0:
        return "tool fail"

    if summary.recent_failure_count > 0:
        return "failures"

    restored_family = _first_attention_family(restored_family_key)
    if restored_family:
        return f"restored {restored_family}"

    if summary.restore_badges:
        return "restore"

    if summary.last_shell_preview or summary.shell_activity_badges:
        return "shell"

    if summary.last_tool_preview or summary.last_tool_badges:
        return "tool"

    return ""


def _is_redundant_attention_badge(summary: SessionSummary, attention_badge: str) -> bool:
    if attention_badge == "shell":
        return bool(summary.last_shell_preview or summary.shell_activity_badges)
    if attention_badge == "tool":
        return bool(summary.last_tool_preview or summary.last_tool_badges)
    return False


def _first_attention_family(counts: tuple[int, ...]) -> str:
    for family, count in zip(APPROVAL_TOOL_FAMILY_DISPLAY_ORDER, counts, strict=False):
        if count > 0:
            return family
    return ""


def _approval_tool_family(record: dict[str, object]) -> str:
    return _approval_tool_family_for_values(
        tool_name=str(record.get("tool_name", "") or "").strip(),
        command=str(record.get("command", "") or "").strip(),
        shell_command_family=str(record.get("shell_command_family", "") or "").strip(),
    )


def _approval_tool_family_for_values(*, tool_name: str, command: str, shell_command_family: str) -> str:
    if tool_name == "run_shell_command":
        if shell_command_family.startswith("pytest"):
            return "test"
        if command:
            try:
                profile = resolve_shell_command(command)
            except ValueError:
                return "shell"
            return "test" if profile.family.startswith("pytest") else "shell"
        return "shell"
    if tool_name in {"write_file", "replace_text"}:
        return "edit"
    if tool_name:
        return "tool"
    return "tool"


def _render_approval_focus_badges(record: dict[str, object] | None) -> list[str]:
    if record is None:
        return []

    badges = [str(record.get("status", "") or "pending")]
    if bool(record.get("approval_restored", False)):
        badges.append("restored")
    elif badges[0] == "denied":
        badges.append("fresh")

    if bool(record.get("resumed_from_approval", False)):
        badges.append("resumed")
    return badges


def _render_last_approval_summary(record: dict[str, object] | None) -> str:
    if record is None:
        return ""

    status = str(record.get("status", "") or "pending")
    tool_name = str(record.get("tool_name", "") or "tool")
    source = str(record.get("source", "") or "runtime")
    bits = [f"{status} {tool_name} via {source}"]

    if bool(record.get("approval_restored", False)) and status == "denied":
        bits.append("restored queue")
    elif status == "denied":
        bits.append("fresh request")

    if bool(record.get("resumed_from_approval", False)):
        bits.append("resumed")

    pending_count = record.get("pending_count")
    remaining_pending_count = record.get("remaining_pending_count")
    if isinstance(pending_count, int):
        bits.append(f"queued {pending_count}")
    elif isinstance(remaining_pending_count, int):
        bits.append(f"remaining {remaining_pending_count}")

    return " | ".join(bits)


def sanitize_session_switcher_filter_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_FILTER_MODES else "all"


def sanitize_session_switcher_sort_mode(value: str) -> str:
    return value if value in SESSION_SWITCHER_SORT_MODES else "recent"


def render_recent_session_empty_state_lines(
    *,
    available_count: int,
    filter_mode: str,
    surface: str = "picker",
) -> list[str]:
    surface = "switcher" if surface == "switcher" else "picker"
    lines = [f"No saved sessions match the active {surface} filter."]
    session_label = "session" if available_count == 1 else "sessions"
    verb = "exists" if available_count == 1 else "exist"
    lines.append(f"{available_count} saved {session_label} still {verb} under this root.")
    if filter_mode != "all":
        lines.append(
            "Try A to show all sessions, or P/D/R/V/T/H to jump between pending, denied, restore, restored-approval, tool, and shell triage."
        )
    if surface == "picker":
        lines.append("Press Enter or N to start a fresh session while keeping this picker context for the next reopen.")
    else:
        lines.append("Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists.")
        lines.append("Enter switches the highlighted session once a visible row exists again.")
    return lines


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
    if filter_mode == "denied":
        return summary.denied_approval_count > 0
    if filter_mode == "restore":
        return bool(summary.restore_badges)
    if filter_mode == "approval-restore":
        return summary.restored_approval_count > 0
    if filter_mode == "tool":
        return bool(summary.last_tool_preview or summary.last_tool_badges)
    if filter_mode == "shell":
        return bool(summary.last_shell_preview or summary.shell_activity_badges)
    return True


def _sort_key(item: tuple[float, str, SessionSummary], sort_mode: str) -> tuple[object, ...]:
    activity_timestamp, session_id, summary = item
    if sort_mode == "attention":
        restored_pending_key, restored_denied_key, restored_family_key, denied_key, fresh_denied_key = (
            _approval_attention_family_keys(summary)
        )
        pending_approval_attention_sort_key = summary.pending_approval_attention_sort_key or (0,) * len(
            APPROVAL_TOOL_FAMILY_DISPLAY_ORDER
        )
        return (
            summary.pending_approval_count > 0,
            any(restored_pending_key),
            restored_pending_key,
            any(pending_approval_attention_sort_key),
            pending_approval_attention_sort_key,
            summary.pending_approval_count,
            summary.denied_approval_count > 0,
            denied_key,
            fresh_denied_key,
            restored_denied_key,
            summary.denied_approval_count,
            summary.recent_test_failure_count > 0,
            summary.recent_test_failure_count,
            summary.recent_tool_failure_count > 0,
            summary.recent_tool_failure_count,
            summary.recent_failure_count > 0,
            summary.recent_failure_count,
            summary.restored_approval_count > 0,
            restored_family_key,
            bool(summary.restore_badges),
            bool(summary.shell_activity_badges or summary.last_shell_preview),
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
