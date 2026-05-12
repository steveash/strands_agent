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
from .summary_utils import (
    render_backlog_summary_line,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_lane_focus_suffix,
    render_lane_label_list,
    render_page_lane_summary_line,
    render_picker_empty_filter_adjust_guidance,
    render_picker_empty_filter_prompt,
    render_picker_empty_filter_visible_guidance,
    render_recent_session_empty_state_lines as render_recent_session_empty_state_lines_helper,
)
from ..runtime import ApprovalRequest
from ..tools.workspace import resolve_shell_command

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50
MAX_TOOL_PREVIEW = 72
MAX_TOOL_STREAK_PREVIEWS = 3
MAX_INTERVENTION_PREVIEWS = 3
MAX_INTERVENTION_ROLLUP_EVENTS = 6
MAX_SHELL_STREAK_PREVIEWS = 3
MAX_SHELL_ROLLUP_EVENTS = 6
MAX_FAILURE_ROLLUP_EVENTS = 6
STALE_SESSION_WARNING_SECONDS = 7 * 24 * 60 * 60
STALE_SESSION_DANGER_SECONDS = 30 * 24 * 60 * 60
STALE_APPROVAL_WARNING_SECONDS = STALE_SESSION_WARNING_SECONDS
APPROVAL_STATUS_DISPLAY_ORDER = ("pending", "approved", "denied", "blocked")
APPROVAL_TOOL_FAMILY_DISPLAY_ORDER = ("test", "edit", "shell", "tool")
APPROVAL_RESTORE_LANE_DISPLAY_ORDER = ("restore queue", "restored")
WORKSPACE_LANE_DISPLAY_ORDER = ("inspect", "edit")
SHELL_LANE_DISPLAY_ORDER = ("inspect", "test")
STALE_APPROVAL_LANE_DISPLAY_ORDER = ("pending", "denied", "restore queue", "restored")
STALE_APPROVAL_FILTER_LANES = {
    "approval-stale": frozenset(STALE_APPROVAL_LANE_DISPLAY_ORDER),
    "approval-stale-pending": frozenset({"pending"}),
    "approval-stale-denied": frozenset({"denied"}),
    "approval-stale-restored": frozenset({"restore queue", "restored"}),
}
STALE_APPROVAL_FILTER_SUMMARY_LABELS = {
    "approval-stale": "Stale approval backlog",
    "approval-stale-pending": "Stale pending backlog",
    "approval-stale-denied": "Stale denied backlog",
    "approval-stale-restored": "Stale restored backlog",
}
SESSION_SWITCHER_FILTER_MODES = {
    "all",
    "pending",
    "denied",
    "restore",
    "approval-restore",
    "approval-stale",
    "approval-stale-pending",
    "approval-stale-denied",
    "approval-stale-restored",
    "tool",
    "workspace-inspect",
    "workspace-edit",
    "intervention",
    "shell",
    "shell-inspect",
    "shell-test",
}
SESSION_SWITCHER_SORT_MODES = {"recent", "attention"}
WORKSPACE_INSPECT_TOOL_NAMES = frozenset({"summarize_workspace", "list_files", "read_file", "search_files"})
WORKSPACE_EDIT_TOOL_NAMES = frozenset({"write_file", "replace_text"})


def format_stale_approval_cutoff(stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS) -> str:
    return f"approvals >= {_format_age_compact(max(stale_approval_warning_seconds, 1))} old"


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
    pending_approval_age_summary: str = ""
    pending_approval_badges: list[str] = field(default_factory=list)
    approval_status_badges: list[str] = field(default_factory=list)
    approval_focus_badges: list[str] = field(default_factory=list)
    last_approval_summary: str = ""
    denied_approval_count: int = 0
    denied_approval_badges: list[str] = field(default_factory=list)
    last_denied_approval_summary: str = ""
    last_denied_approval_age_summary: str = ""
    last_denied_approval_age_sort_key: int = 0
    restored_approval_count: int = 0
    restored_approval_badges: list[str] = field(default_factory=list)
    restored_approval_tool_badges: list[str] = field(default_factory=list)
    restored_pending_approval_queue_summary: str = ""
    restored_pending_approval_age_summary: str = ""
    restored_pending_approval_age_sort_key: int = 0
    last_restored_approval_summary: str = ""
    last_restored_approval_age_summary: str = ""
    last_restored_approval_age_sort_key: int = 0
    last_restored_outcome_summary: str = ""
    last_restored_outcome_age_summary: str = ""
    last_restored_outcome_age_sort_key: int = 0
    stale_approval_badges: list[str] = field(default_factory=list)
    intervention_badges: list[str] = field(default_factory=list)
    last_intervention_preview: str = ""
    recent_intervention_previews: list[str] = field(default_factory=list)
    has_intervention_activity: bool = False
    pending_approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    denied_approval_attention_sort_key: tuple[int, ...] = field(default_factory=tuple)
    attention_reason_summary: str = ""
    last_event_preview: str = ""
    last_tool_preview: str = ""
    last_tool_badges: list[str] = field(default_factory=list)
    recent_tool_previews: list[str] = field(default_factory=list)
    workspace_lane_badges: list[str] = field(default_factory=list)
    has_workspace_inspect_activity: bool = False
    has_workspace_edit_activity: bool = False
    last_workspace_preview: str = ""
    recent_workspace_previews: list[str] = field(default_factory=list)
    shell_activity_badges: list[str] = field(default_factory=list)
    shell_lane_badges: list[str] = field(default_factory=list)
    has_shell_inspect_activity: bool = False
    has_shell_test_activity: bool = False
    last_shell_preview: str = ""
    recent_shell_previews: list[str] = field(default_factory=list)
    failure_activity_badges: list[str] = field(default_factory=list)
    recent_failure_count: int = 0
    recent_shell_failure_count: int = 0
    recent_test_failure_count: int = 0
    recent_tool_failure_count: int = 0
    stale_session_badges: list[str] = field(default_factory=list)
    stale_session_summary: str = ""
    pending_approval_age_sort_key: int = 0
    stale_session_sort_key: int = 0
    restore_badges: list[str] = field(default_factory=list)
    draft_prompt_preview: str = ""

    def render_line(
        self,
        index: int,
        *,
        include_attention_reason: bool = False,
        filter_mode: str = "all",
    ) -> str:
        prompt_suffix = f" | last prompt: {self.last_prompt_preview}" if self.last_prompt_preview else ""
        pending_suffix = ""
        if self.pending_approval_count == 1 and self.pending_approval_tool:
            pending_suffix = f" | pending: {self.pending_approval_tool}"
        elif self.pending_approval_count > 1:
            tool_hint = f" ({self.pending_approval_queue_summary})" if self.pending_approval_queue_summary else ""
            pending_suffix = f" | pending: {self.pending_approval_count} approvals{tool_hint}"
        pending_age_suffix = f" | pending age: {self.pending_approval_age_summary}" if self.pending_approval_age_summary else ""
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
        denied_age_suffix = f" | denied age: {self.last_denied_approval_age_summary}" if self.last_denied_approval_age_summary else ""
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
        approval_restore_age_suffix, restore_focus_suffix, suppress_restored_outcome_age_suffix = (
            _render_approval_restore_row_age_suffixes(self, filter_mode)
        )
        restored_current_suffix, restored_outcome_suffix, restored_outcome_age_suffix = _render_restored_row_suffixes(
            self,
            filter_mode,
            suppress_outcome_age=suppress_restored_outcome_age_suffix,
        )
        stale_focus_lanes = _stale_approval_focus_lanes(self, filter_mode)
        stale_approval_suffix = _render_stale_approval_row_suffix(
            self,
            filter_mode,
            stale_focus_lanes=stale_focus_lanes,
        )
        stale_focus_suffix = render_lane_focus_suffix("stale focus", stale_focus_lanes)
        intervention_suffix = (
            f" | intervention: {', '.join(self.intervention_badges)}" if self.intervention_badges else ""
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
        workspace_lane_suffix = (
            f" | workspace lanes: {', '.join(self.workspace_lane_badges)}" if self.workspace_lane_badges else ""
        )
        shell_suffix = (
            f" | shell: {', '.join(self.shell_activity_badges)}" if self.shell_activity_badges else ""
        )
        shell_lane_suffix = (
            f" | shell lanes: {', '.join(self.shell_lane_badges)}" if self.shell_lane_badges else ""
        )
        failure_suffix = (
            f" | failures: {', '.join(self.failure_activity_badges)}" if self.failure_activity_badges else ""
        )
        attention_suffix = ""
        attention_badge = _attention_reason_badge(self) if include_attention_reason and self.attention_reason_summary else ""
        if attention_badge and not _is_redundant_attention_badge(self, attention_badge):
            attention_suffix = f" | attention: {attention_badge}"
        event_suffix = f" | last event: {self.last_event_preview}" if self.last_event_preview else ""
        stale_suffix = f" | stale: {', '.join(self.stale_session_badges)}" if self.stale_session_badges else ""
        restore_suffix = f" | restore: {', '.join(self.restore_badges)}" if self.restore_badges else ""
        return (
            f"{index}. {self.session_id} | {self.turn_count} turn(s) | "
            f"updated {self.updated_at}{pending_suffix}{pending_age_suffix}{pending_tool_suffix}{approval_suffix}{approval_focus_suffix}{denied_suffix}{denied_age_suffix}{approval_restore_suffix}{approval_restore_tool_suffix}{approval_restore_queue_suffix}{approval_restore_age_suffix}{restore_focus_suffix}{restored_current_suffix}{restored_outcome_suffix}{restored_outcome_age_suffix}{stale_approval_suffix}{stale_focus_suffix}{intervention_suffix}{attention_suffix}{stale_suffix}{restore_suffix}{prompt_suffix}{tool_hint}{tool_streak_suffix}{workspace_lane_suffix}{shell_suffix}{shell_lane_suffix}{failure_suffix}{event_suffix}"
        )

    def render_preview(
        self,
        *,
        visible_index: int,
        overall_index: int,
        total_matches: int,
        filter_mode: str = "all",
        stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
    ) -> list[str]:
        lines = [
            "Selected preview:",
            (
                f"- slot {visible_index} on this page | overall {overall_index} of {total_matches} | "
                f"session {self.session_id}"
            ),
            f"- artifact dir: {self.session_dir}",
        ]
        if _should_render_stale_cutoff_preview_line(filter_mode):
            lines.append(
                "- stale lane focus: "
                f"{_stale_approval_filter_focus_label(filter_mode)} | "
                f"cutoff: {format_stale_approval_cutoff(stale_approval_warning_seconds)}"
            )
        if self.attention_reason_summary:
            lines.append(f"- attention reason: {self.attention_reason_summary}")
        if self.pending_approval_count > 0:
            pending_line = self.pending_approval_summary or self.pending_approval_tool or "pending approval"
            if self.pending_approval_count > 1:
                pending_line = f"{self.pending_approval_count} approvals | first: {pending_line}"
            lines.append(f"- pending: {pending_line}")
        if self.pending_approval_queue_summary:
            lines.append(f"- pending queue: {self.pending_approval_queue_summary}")
        if self.pending_approval_age_summary:
            lines.append(f"- pending age: {self.pending_approval_age_summary}")
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
        if self.last_denied_approval_age_summary:
            lines.append(f"- last denied age: {self.last_denied_approval_age_summary}")
        if self.restored_approval_badges:
            lines.append(f"- approval restore: {', '.join(self.restored_approval_badges)}")
        if self.restored_approval_tool_badges:
            lines.append(f"- approval restore tools: {', '.join(self.restored_approval_tool_badges)}")
        if self.restored_pending_approval_queue_summary:
            lines.append(f"- approval restore queue: {self.restored_pending_approval_queue_summary}")
        approval_restore_preview_lines, suppress_restored_preview_age = _render_approval_restore_preview_lines(
            self,
            filter_mode,
        )
        lines.extend(approval_restore_preview_lines)
        if self.last_restored_outcome_summary and self.last_restored_outcome_summary != self.last_restored_approval_summary:
            lines.append(f"- restored current approval: {self.last_restored_approval_summary}")
        elif self.last_restored_approval_summary:
            lines.append(f"- last restored approval: {self.last_restored_approval_summary}")
        if self.last_restored_outcome_summary and self.last_restored_outcome_summary != self.last_restored_approval_summary:
            lines.append(f"- latest restored outcome: {self.last_restored_outcome_summary}")
        restored_outcome_age_summary = _restored_outcome_preview_age_summary(self)
        restored_outcome_age_label = _restored_outcome_preview_age_label(self)
        if not suppress_restored_preview_age and restored_outcome_age_summary and (
            not self.restored_pending_approval_age_summary
            or restored_outcome_age_summary != self.restored_pending_approval_age_summary
        ):
            lines.append(f"- {restored_outcome_age_label}: {restored_outcome_age_summary}")
        elif not suppress_restored_preview_age and self.last_restored_approval_age_summary and (
            not self.restored_pending_approval_age_summary
            or self.last_restored_approval_age_summary != self.restored_pending_approval_age_summary
        ):
            lines.append(f"- last restored age: {self.last_restored_approval_age_summary}")
        lines.extend(_render_stale_approval_preview_lines(self, filter_mode))
        if self.intervention_badges:
            lines.append(f"- intervention: {', '.join(self.intervention_badges)}")
        if self.last_intervention_preview:
            lines.append(f"- last intervention: {self.last_intervention_preview}")
        if self.recent_intervention_previews:
            lines.append(f"- recent interventions ({len(self.recent_intervention_previews)}):")
            lines.extend(
                f"  {index}. {preview}"
                for index, preview in enumerate(self.recent_intervention_previews, start=1)
            )
        if self.restore_badges:
            lines.append(f"- restore: {', '.join(self.restore_badges)}")
        if self.stale_session_summary:
            lines.append(f"- session age: {self.stale_session_summary}")
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
        if self.workspace_lane_badges:
            lines.append(f"- workspace lanes: {', '.join(self.workspace_lane_badges)}")
        if self.last_workspace_preview:
            lines.append(f"- last workspace tool: {self.last_workspace_preview}")
        if self.recent_workspace_previews:
            lines.append(f"- recent workspace tools ({len(self.recent_workspace_previews)}):")
            lines.extend(
                f"  {index}. {preview}" for index, preview in enumerate(self.recent_workspace_previews, start=1)
            )
        if self.shell_activity_badges:
            lines.append(f"- shell: {', '.join(self.shell_activity_badges)}")
        if self.shell_lane_badges:
            lines.append(f"- shell lanes: {', '.join(self.shell_lane_badges)}")
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
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
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
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )


def count_recent_sessions(
    root: str | Path,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> int:
    resolved_root = Path(root).expanduser().resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return 0

    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)
    return len(
        _ordered_recent_sessions(
            resolved_root,
            limit=None,
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            stale_approval_warning_seconds=stale_approval_warning_seconds,
        )
    )


def _ordered_recent_sessions(
    resolved_root: Path,
    *,
    limit: int | None,
    filter_mode: str,
    sort_mode: str,
    offset: int = 0,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
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
            pending_approval_age_summary,
            denied_approval_count,
            denied_approval_badges,
            last_denied_approval_summary,
            last_denied_approval_age_summary,
            last_denied_approval_age_sort_key,
            restored_approval_count,
            restored_approval_badges,
            restored_approval_tool_badges,
            restored_pending_approval_age_summary,
            restored_pending_approval_age_sort_key,
            last_restored_approval_summary,
            last_restored_approval_age_summary,
            last_restored_approval_age_sort_key,
            last_restored_outcome_summary,
            last_restored_outcome_age_summary,
            last_restored_outcome_age_sort_key,
            stale_approval_badges,
            pending_approval_attention_sort_key,
            approval_attention_sort_key,
            denied_approval_attention_sort_key,
        ) = _approval_activity(
            turns,
            pending_approvals,
            stale_approval_warning_seconds=stale_approval_warning_seconds,
        )
        last_prompt_preview = ""
        if turns:
            last_prompt_preview = _truncate(turns[-1].prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
        draft_prompt_preview = ""
        if session_state.draft_prompt:
            draft_prompt_preview = _truncate(session_state.draft_prompt.replace("\n", " ").strip(), MAX_PROMPT_PREVIEW)
        activity_timestamp = _session_activity_timestamp(session_dir, turns)
        pending_approval_age_seconds = _pending_approval_age_seconds(pending_approvals)
        stale_session_summary, stale_session_badges, stale_session_sort_key = _stale_session_status(activity_timestamp)
        recent_failure_count = _recent_tool_failure_count(turns)
        recent_shell_failure_count = _recent_shell_failure_count(turns)
        recent_test_failure_count, recent_tool_failure_count = _recent_failure_activity_counts(turns)
        has_workspace_inspect_activity, has_workspace_edit_activity = _workspace_activity_presence(
            turns,
            pending_approvals,
        )
        has_shell_inspect_activity, has_shell_test_activity = _shell_activity_presence(turns, pending_approvals)
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
            pending_approval_age_summary=pending_approval_age_summary,
            pending_approval_badges=pending_approval_badges,
            approval_status_badges=approval_status_badges,
            approval_focus_badges=approval_focus_badges,
            last_approval_summary=last_approval_summary,
            denied_approval_count=denied_approval_count,
            denied_approval_badges=denied_approval_badges,
            last_denied_approval_summary=last_denied_approval_summary,
            last_denied_approval_age_summary=last_denied_approval_age_summary,
            last_denied_approval_age_sort_key=last_denied_approval_age_sort_key,
            restored_approval_count=restored_approval_count,
            restored_approval_badges=restored_approval_badges,
            restored_approval_tool_badges=restored_approval_tool_badges,
            restored_pending_approval_queue_summary=_restored_pending_approval_queue_summary(pending_approvals),
            restored_pending_approval_age_summary=restored_pending_approval_age_summary,
            restored_pending_approval_age_sort_key=restored_pending_approval_age_sort_key,
            last_restored_approval_summary=last_restored_approval_summary,
            last_restored_approval_age_summary=last_restored_approval_age_summary,
            last_restored_approval_age_sort_key=last_restored_approval_age_sort_key,
            last_restored_outcome_summary=last_restored_outcome_summary,
            last_restored_outcome_age_summary=last_restored_outcome_age_summary,
            last_restored_outcome_age_sort_key=last_restored_outcome_age_sort_key,
            stale_approval_badges=stale_approval_badges,
            intervention_badges=_intervention_activity_badges(turns, pending_approvals),
            last_intervention_preview=_latest_intervention_preview(turns, pending_approvals),
            recent_intervention_previews=_recent_intervention_previews(turns, pending_approvals),
            has_intervention_activity=_has_intervention_activity(turns, pending_approvals),
            pending_approval_attention_sort_key=pending_approval_attention_sort_key,
            approval_attention_sort_key=approval_attention_sort_key,
            denied_approval_attention_sort_key=denied_approval_attention_sort_key,
            last_event_preview=_latest_event_preview(turns),
            last_tool_preview=_latest_tool_preview(turns),
            last_tool_badges=_latest_tool_badges(turns),
            recent_tool_previews=_recent_tool_previews(turns),
            workspace_lane_badges=_workspace_lane_badges(
                has_workspace_inspect_activity,
                has_workspace_edit_activity,
            ),
            has_workspace_inspect_activity=has_workspace_inspect_activity,
            has_workspace_edit_activity=has_workspace_edit_activity,
            last_workspace_preview=_latest_workspace_preview(turns),
            recent_workspace_previews=_recent_workspace_previews(turns),
            shell_activity_badges=_shell_activity_badges(turns),
            shell_lane_badges=_shell_lane_badges(has_shell_inspect_activity, has_shell_test_activity),
            has_shell_inspect_activity=has_shell_inspect_activity,
            has_shell_test_activity=has_shell_test_activity,
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
            stale_session_badges=stale_session_badges,
            stale_session_summary=stale_session_summary,
            pending_approval_age_sort_key=int(pending_approval_age_seconds or 0),
            stale_session_sort_key=int(stale_session_sort_key),
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


def latest_session(
    root: str | Path,
    *,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> SessionSummary | None:
    sessions = list_recent_sessions(root, limit=1, stale_approval_warning_seconds=stale_approval_warning_seconds)
    return sessions[0] if sessions else None


def render_session_picker(
    root: str | Path,
    limit: int = MAX_RECENT_SESSIONS,
    *,
    filter_mode: str = "all",
    sort_mode: str = "recent",
    page_index: int = 0,
    selected_index: int = 0,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> str:
    filter_mode = sanitize_session_switcher_filter_mode(filter_mode)
    sort_mode = sanitize_session_switcher_sort_mode(sort_mode)
    resolved_root = Path(root).expanduser().resolve()
    available_count = count_recent_sessions(resolved_root, stale_approval_warning_seconds=stale_approval_warning_seconds)
    if not available_count:
        return f"No saved sessions found under {resolved_root}."

    total_matches = count_recent_sessions(
        resolved_root,
        filter_mode=filter_mode,
        sort_mode=sort_mode,
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )
    page_index = _normalize_picker_page_index(total_matches, limit, page_index)
    summaries = list_recent_sessions(
        root,
        limit=limit,
        filter_mode=filter_mode,
        sort_mode=sort_mode,
        offset=page_index * limit,
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )
    matching_summaries = (
        list_recent_sessions(
            resolved_root,
            limit=total_matches,
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            stale_approval_warning_seconds=stale_approval_warning_seconds,
        )
        if total_matches > 0
        else []
    )

    filter_summary_lines = render_recent_session_filter_summary_lines(
        matching_summaries,
        filter_mode=filter_mode,
        page_index=page_index,
        page_size=limit,
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )

    stale_cutoff_suffix = (
        f" | Stale cutoff: {format_stale_approval_cutoff(stale_approval_warning_seconds)}"
        if _is_stale_approval_filter_mode(filter_mode)
        else ""
    )

    lines = [
        f"Recent sessions under {resolved_root}:",
        (
            f"Filter: {filter_mode} | Sort: {sort_mode}{stale_cutoff_suffix} | "
            f"Page: {_picker_page_label(total_matches, limit, page_index)} | "
            f"Showing: {_picker_page_window_label(total_matches, limit, page_index, len(summaries))}"
        ),
        *filter_summary_lines,
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
                f"{marker} {summary.render_line(index, include_attention_reason=sort_mode == 'attention', filter_mode=filter_mode)}"
            )
        lines.extend(
            [
                "",
                *summaries[selected_index].render_preview(
                    visible_index=selected_index + 1,
                    overall_index=page_index * limit + selected_index + 1,
                    total_matches=total_matches,
                    filter_mode=filter_mode,
                    stale_approval_warning_seconds=stale_approval_warning_seconds,
                ),
            ]
        )
    lines.extend(
        [
            "",
            "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, [ prev page, ] next page, N new session",
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
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
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
    summaries = list_recent_sessions(
        resolved_root,
        limit=limit,
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )
    if not summaries:
        output_fn(
            render_session_picker(
                resolved_root,
                limit=limit,
                filter_mode=filter_mode,
                sort_mode=sort_mode,
                stale_approval_warning_seconds=stale_approval_warning_seconds,
            )
        )
        output_fn("Starting a new session instead.")
        return None

    while True:
        total_matches = count_recent_sessions(
            resolved_root,
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            stale_approval_warning_seconds=stale_approval_warning_seconds,
        )
        page_index = _normalize_picker_page_index(total_matches, limit, page_index)
        current_summaries = list_recent_sessions(
            resolved_root,
            limit=limit,
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            offset=page_index * limit,
            stale_approval_warning_seconds=stale_approval_warning_seconds,
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
                stale_approval_warning_seconds=stale_approval_warning_seconds,
            )
        )
        prompt = (
            "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to triage/page: "
            if current_summaries
            else render_picker_empty_filter_prompt()
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
        if normalized == "o":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "approval-stale")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "q":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "approval-stale-pending")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "x":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "approval-stale-denied")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "u":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "approval-stale-restored")
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
        if normalized == "w":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "workspace-inspect")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "e":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "workspace-edit")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "g":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "intervention")
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
        if normalized == "i":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "shell-inspect")
            page_index = 0
            selected_index = 0
            selected_session_id = ""
            continue
        if normalized == "y":
            filter_mode = _toggle_picker_filter_mode(filter_mode, "shell-test")
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
                output_fn(render_picker_empty_filter_visible_guidance())
            continue
        if current_summaries:
            output_fn(
                f"Invalid selection. Use 1-{limit}, J, K, A, P, D, R, V, O, Q, X, U, T, W, E, G, H, I, Y, S, [, ], Enter, or N."
            )
        else:
            output_fn(render_picker_empty_filter_adjust_guidance())


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


def _workspace_tool_lane(tool_name: str) -> str:
    if tool_name in WORKSPACE_INSPECT_TOOL_NAMES:
        return "inspect"
    if tool_name in WORKSPACE_EDIT_TOOL_NAMES:
        return "edit"
    return ""


def _iter_recent_workspace_tool_events(turns: list[TurnArtifact], *, lane: str | None = None):
    for event in _iter_recent_tool_events(turns):
        tool_name = str(event.data.get("tool_name", "") or event.title or "")
        tool_lane = _workspace_tool_lane(tool_name)
        if not tool_lane:
            continue
        if lane is not None and tool_lane != lane:
            continue
        yield event


def _latest_workspace_preview(turns: list[TurnArtifact], *, lane: str | None = None) -> str:
    event = next(_iter_recent_workspace_tool_events(turns, lane=lane), None)
    if event is None:
        return ""
    return _render_tool_event_summary(event)


def _recent_workspace_previews(turns: list[TurnArtifact], limit: int = MAX_TOOL_STREAK_PREVIEWS) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_workspace_tool_events(turns):
        rendered = _render_tool_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    return previews


def _latest_intervention_preview(turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest]) -> str:
    event = _latest_intervention_event(turns)
    if event is not None:
        return _render_intervention_event_summary(event)
    return _queued_intervention_preview(pending_approvals)


def _recent_intervention_previews(
    turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest], limit: int = MAX_INTERVENTION_PREVIEWS
) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_intervention_events(turns):
        rendered = _render_intervention_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    if previews:
        return previews
    for approval in pending_approvals[:limit]:
        preview = _queued_intervention_preview([approval])
        if preview:
            previews.append(preview)
    return previews


def _iter_recent_intervention_events(turns: list[TurnArtifact]):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            if _is_intervention_event(event):
                yield event


def _latest_intervention_event(turns: list[TurnArtifact]):
    return next(_iter_recent_intervention_events(turns), None)


def _intervention_activity_badges(
    turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest], count_window: int = MAX_INTERVENTION_ROLLUP_EVENTS
) -> list[str]:
    events = list(_bounded_recent_intervention_events(turns, limit=count_window))
    counts = {label: 0 for label in ("pending", "blocked", "approved", "denied")}
    restored_count = 0
    for event in events:
        label = _intervention_event_label(event)
        if label in counts:
            counts[label] += 1
        if bool(event.data.get("approval_restored", False)):
            restored_count += 1

    if pending_approvals:
        counts["pending"] = max(counts["pending"], len(pending_approvals))
        restored_count = max(
            restored_count,
            sum(1 for approval in pending_approvals if approval.restored_from_session),
        )

    if not any(counts.values()) and restored_count == 0:
        return []

    badges: list[str] = []
    for label in ("pending", "blocked", "approved", "denied"):
        count = counts.get(label, 0)
        if count:
            badges.append(f"{label} {count}")
    if restored_count:
        badges.append(f"restored {restored_count}")
    return badges


def _bounded_recent_intervention_events(turns: list[TurnArtifact], *, limit: int) -> list[object]:
    events = []
    for event in _iter_recent_intervention_events(turns):
        events.append(event)
        if len(events) >= limit:
            break
    return events


def _has_intervention_activity(turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest]) -> bool:
    if pending_approvals:
        return True
    return _latest_intervention_event(turns) is not None


def _is_intervention_event(event) -> bool:
    return event.kind in {
        "steering_confirmation_required",
        "steering_blocked",
        "steering_approved",
        "steering_denied",
        "approval_follow_up_prepared",
    }


def _intervention_event_label(event) -> str:
    if event.kind == "steering_confirmation_required":
        return "pending"
    if event.kind == "steering_blocked":
        return "blocked"
    if event.kind == "steering_approved":
        return "approved"
    if event.kind == "steering_denied":
        return "denied"
    if event.kind == "approval_follow_up_prepared":
        return "continued"
    return event.kind.replace("_", " ")


def _render_intervention_event_summary(event) -> str:
    label = _intervention_event_label(event)
    family = str(event.data.get("approval_tool_family", "") or "").strip()
    tool_name = str(event.data.get("tool_name", "") or event.title or "").strip()
    bits = [label]
    if bool(event.data.get("approval_restored", False)):
        bits.append("restored")
    if family:
        bits.append(family)
    if tool_name:
        bits.append(tool_name)
    preview = " ".join(bits).strip()
    tool_result = str(event.data.get("tool_result_preview", "") or "").strip()
    if tool_result:
        preview = f"{preview}: {tool_result}" if preview else tool_result
    return _truncate(preview or (event.title or event.kind), MAX_TOOL_PREVIEW)


def _queued_intervention_preview(pending_approvals: list[ApprovalRequest]) -> str:
    if not pending_approvals:
        return ""
    approval = pending_approvals[0]
    family = _approval_tool_family_for_values(
        tool_name=str(approval.tool_name or ""),
        command=_approval_command_from_args(approval.args),
        shell_command_family="",
    )
    bits = ["pending"]
    if approval.restored_from_session:
        bits.append("restored")
    if family:
        bits.append(family)
    if approval.tool_name:
        bits.append(approval.tool_name)
    return _truncate(" ".join(bits), MAX_TOOL_PREVIEW)


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


def _shell_lane_badges(has_inspect_activity: bool, has_test_activity: bool) -> list[str]:
    if has_inspect_activity and has_test_activity:
        return ["inspect", "test"]
    return []


def _workspace_lane_badges(has_inspect_activity: bool, has_edit_activity: bool) -> list[str]:
    badges: list[str] = []
    if has_inspect_activity:
        badges.append("inspect")
    if has_edit_activity:
        badges.append("edit")
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


def _shell_activity_presence(turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest]) -> tuple[bool, bool]:
    has_inspect_activity = False
    has_test_activity = False

    for event in _iter_recent_tool_events(turns, tool_name="run_shell_command"):
        if _is_test_shell_event(event):
            has_test_activity = True
        else:
            has_inspect_activity = True
        if has_inspect_activity and has_test_activity:
            return has_inspect_activity, has_test_activity

    if any(str(approval.tool_name or "") == "run_shell_command" for approval in pending_approvals):
        has_test_activity = True

    if has_test_activity:
        return has_inspect_activity, has_test_activity

    for turn in turns:
        for event in turn.events:
            if not str(event.data.get("approval_status", "") or "").strip():
                continue
            if str(event.data.get("tool_name", "") or event.title or "") == "run_shell_command":
                return has_inspect_activity, True

    return has_inspect_activity, has_test_activity


def _workspace_activity_presence(turns: list[TurnArtifact], pending_approvals: list[ApprovalRequest]) -> tuple[bool, bool]:
    has_inspect_activity = False
    has_edit_activity = False

    for event in _iter_recent_workspace_tool_events(turns):
        tool_name = str(event.data.get("tool_name", "") or event.title or "")
        tool_lane = _workspace_tool_lane(tool_name)
        if tool_lane == "inspect":
            has_inspect_activity = True
        elif tool_lane == "edit":
            has_edit_activity = True
        if has_inspect_activity and has_edit_activity:
            return has_inspect_activity, has_edit_activity

    if any(str(approval.tool_name or "") in WORKSPACE_EDIT_TOOL_NAMES for approval in pending_approvals):
        has_edit_activity = True

    if has_edit_activity:
        return has_inspect_activity, has_edit_activity

    for turn in turns:
        for event in turn.events:
            tool_name = str(event.data.get("tool_name", "") or event.title or "")
            if tool_name in WORKSPACE_EDIT_TOOL_NAMES and (
                str(event.data.get("approval_status", "") or "").strip() or _is_intervention_event(event)
            ):
                return has_inspect_activity, True

    return has_inspect_activity, has_edit_activity


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
    *,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> tuple[
    list[str],
    list[str],
    list[str],
    str,
    str,
    int,
    list[str],
    str,
    str,
    int,
    int,
    list[str],
    list[str],
    str,
    str,
    str,
    int,
    str,
    str,
    int,
    list[str],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    latest_by_request_id: dict[str, dict[str, object]] = {}
    last_record: dict[str, object] | None = None
    last_denied_record: dict[str, object] | None = None
    last_restored_record: dict[str, object] | None = None
    last_restored_outcome_record: dict[str, object] | None = None
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
                "timestamp": event.timestamp,
                "order": order,
            }
            latest_by_request_id[approval_id] = record
            last_record = dict(record)
            if status == "denied":
                last_denied_record = dict(record)
            if bool(record.get("approval_restored", False)):
                last_restored_record = dict(record)
                if status != "pending":
                    last_restored_outcome_record = dict(record)

    for approval in pending_approvals:
        command = str(approval.args.get("command", "") or "").strip() if isinstance(approval.args, dict) else ""
        shell_command_family = ""
        if command:
            try:
                shell_command_family = resolve_shell_command(command).family
            except ValueError:
                shell_command_family = ""
        existing_record = latest_by_request_id.get(approval.request_id)
        if existing_record is not None and str(existing_record.get("status", "") or "") == "pending":
            if command and not str(existing_record.get("command", "") or "").strip():
                existing_record["command"] = command
            if shell_command_family and not str(existing_record.get("shell_command_family", "") or "").strip():
                existing_record["shell_command_family"] = shell_command_family
            if approval.tool_name and not str(existing_record.get("tool_name", "") or "").strip():
                existing_record["tool_name"] = approval.tool_name
            existing_record["pending_count"] = len(pending_approvals)
            if approval.created_at and not existing_record.get("timestamp"):
                existing_record["timestamp"] = approval.created_at
            if approval.restored_from_session:
                existing_record["approval_restored"] = True
            continue
        order += 1
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
            "timestamp": approval.created_at,
            "order": order,
        }
        record_key = approval.request_id
        if existing_record is not None:
            record_key = f"{approval.request_id}#pending"
        latest_by_request_id[record_key] = record
        if last_record is None:
            last_record = dict(record)

    if pending_approvals:
        preferred_pending = latest_by_request_id.get(pending_approvals[0].request_id)
        if preferred_pending is not None and str(preferred_pending.get("status", "") or "") != "pending":
            preferred_pending = latest_by_request_id.get(f"{pending_approvals[0].request_id}#pending")
        if preferred_pending is not None:
            last_record = dict(preferred_pending)
            if bool(preferred_pending.get("approval_restored", False)):
                last_restored_record = dict(preferred_pending)

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
                last_restored_record = dict(record)
            if status != "pending" and (
                last_restored_outcome_record is None
                or int(record.get("order", 0)) >= int(last_restored_outcome_record.get("order", 0))
            ):
                last_restored_outcome_record = dict(record)
        if status == "denied" and (
            last_denied_record is None or int(record.get("order", 0)) >= int(last_denied_record.get("order", 0))
        ):
            last_denied_record = dict(record)

    badges = _render_status_badges(status_counts)
    pending_badges = _render_tool_family_badges(fresh_pending_family_counts)
    denied_badges = _render_tool_family_badges(denied_family_counts)
    restored_badges = _render_status_badges(restored_status_counts)
    restored_tool_badges = _render_tool_family_badges(restored_family_counts)
    pending_approval_age_summary = _pending_approval_age_summary(pending_approvals)
    fresh_pending_approval_age_summary = _fresh_pending_approval_age_summary(pending_approvals)
    restored_pending_approval_age_summary = _restored_pending_approval_age_summary(pending_approvals)
    fresh_pending_approval_age_seconds = _fresh_pending_approval_age_seconds(pending_approvals)
    restored_pending_approval_age_seconds = _restored_pending_approval_age_seconds(pending_approvals)
    last_denied_approval_age_summary = _approval_record_age_summary(last_denied_record)
    last_denied_approval_age_sort_key = _approval_record_age_seconds(last_denied_record)
    last_restored_approval_age_summary = _approval_record_age_summary(last_restored_record)
    last_restored_approval_age_sort_key = _approval_record_age_seconds(last_restored_record)
    last_restored_outcome_age_summary = _approval_record_age_summary(last_restored_outcome_record)
    last_restored_outcome_age_sort_key = _approval_record_age_seconds(last_restored_outcome_record)
    stale_approval_badges = _stale_approval_badges(
        pending_approval_age_seconds=fresh_pending_approval_age_seconds,
        pending_approval_age_summary=fresh_pending_approval_age_summary,
        last_denied_approval_age_seconds=last_denied_approval_age_sort_key,
        last_denied_approval_age_summary=last_denied_approval_age_summary,
        restored_pending_approval_age_seconds=restored_pending_approval_age_seconds,
        restored_pending_approval_age_summary=restored_pending_approval_age_summary,
        last_restored_approval_age_seconds=last_restored_outcome_age_sort_key,
        last_restored_approval_age_summary=last_restored_outcome_age_summary,
        stale_approval_warning_seconds=stale_approval_warning_seconds,
    )
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
        pending_approval_age_summary,
        status_counts.get("denied", 0),
        denied_badges,
        _render_last_approval_summary(last_denied_record),
        last_denied_approval_age_summary,
        last_denied_approval_age_sort_key,
        sum(restored_status_counts.values()),
        restored_badges,
        restored_tool_badges,
        restored_pending_approval_age_summary,
        restored_pending_approval_age_seconds,
        _render_last_approval_summary(last_restored_record),
        last_restored_approval_age_summary,
        last_restored_approval_age_sort_key,
        _render_last_approval_summary(last_restored_outcome_record),
        last_restored_outcome_age_summary,
        last_restored_outcome_age_sort_key,
        stale_approval_badges,
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


def _fresh_pending_approval_age_summary(pending_approvals: list[ApprovalRequest]) -> str:
    fresh_pending = [approval for approval in pending_approvals if not approval.restored_from_session]
    return _pending_approval_age_summary(fresh_pending)


def _restored_pending_approval_age_summary(pending_approvals: list[ApprovalRequest]) -> str:
    restored_pending = [approval for approval in pending_approvals if approval.restored_from_session]
    return _pending_approval_age_summary(restored_pending)


def _fresh_pending_approval_age_seconds(pending_approvals: list[ApprovalRequest]) -> int:
    fresh_pending = [approval for approval in pending_approvals if not approval.restored_from_session]
    return _pending_approval_age_seconds(fresh_pending) or 0


def _restored_pending_approval_age_seconds(pending_approvals: list[ApprovalRequest]) -> int:
    restored_pending = [approval for approval in pending_approvals if approval.restored_from_session]
    return _pending_approval_age_seconds(restored_pending) or 0


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


def render_recent_session_filter_summary_lines(
    summaries: list[SessionSummary],
    *,
    filter_mode: str,
    page_index: int = 0,
    page_size: int = MAX_RECENT_SESSIONS,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> list[str]:
    if filter_mode == "approval-restore" and summaries:
        lane_counts, lane_oldest_ages, mixed_count = _summarize_approval_restore_lanes(summaries)
        lane_rollup = _format_approval_restore_lane_rollup(lane_counts, lane_oldest_ages)
        lines = [
            render_backlog_summary_line(
                "Approval restore backlog",
                len(summaries),
                lane_rollup=lane_rollup,
                overlap_summary=_format_mixed_overlap_count(mixed_count) if mixed_count > 0 else "",
            ),
            render_filter_focus_line("Restore lane focus", APPROVAL_RESTORE_LANE_DISPLAY_ORDER),
        ]
        if len(summaries) <= page_size:
            return lines

        page_index = _normalize_picker_page_index(len(summaries), page_size, page_index)
        start = page_index * page_size
        end = start + page_size
        visible_summaries = summaries[start:end]
        off_page_summaries = summaries[:start] + summaries[end:]

        visible_lane_counts, visible_lane_oldest_ages, visible_mixed_count = _summarize_approval_restore_lanes(
            visible_summaries
        )
        visible_rollup = _format_approval_restore_lane_rollup(visible_lane_counts, visible_lane_oldest_ages)
        if not visible_rollup:
            return lines

        off_page_lane_counts, off_page_lane_oldest_ages, off_page_mixed_count = _summarize_approval_restore_lanes(
            off_page_summaries
        )
        off_page_rollup = _format_approval_restore_lane_rollup(off_page_lane_counts, off_page_lane_oldest_ages)
        lines.append(
            render_page_lane_summary_line(
                "restore lanes",
                visible_rollup,
                off_page_rollup=off_page_rollup,
                visible_overlap_summary=(
                    _format_mixed_overlap_count(visible_mixed_count) if visible_mixed_count > 0 else ""
                ),
                off_page_overlap_summary=(
                    _format_mixed_overlap_count(off_page_mixed_count) if off_page_mixed_count > 0 else ""
                ),
            )
        )
        return lines

    if filter_mode in {"workspace-inspect", "workspace-edit"} and summaries:
        lane_counts, mixed_count = _summarize_workspace_lanes(summaries)
        lane_rollup = _format_simple_lane_rollup(lane_counts, WORKSPACE_LANE_DISPLAY_ORDER)
        lines = [
            render_backlog_summary_line(
                "Workspace backlog",
                len(summaries),
                lane_rollup=lane_rollup,
                overlap_summary=_format_mixed_overlap_count(mixed_count) if mixed_count > 0 else "",
            ),
            render_filter_focus_line(
                "Workspace focus",
                ["edit"] if filter_mode == "workspace-edit" else ["inspect"],
            ),
        ]
        if len(summaries) <= page_size:
            return lines

        page_index = _normalize_picker_page_index(len(summaries), page_size, page_index)
        start = page_index * page_size
        end = start + page_size
        visible_summaries = summaries[start:end]
        off_page_summaries = summaries[:start] + summaries[end:]
        visible_lane_counts, visible_mixed_count = _summarize_workspace_lanes(visible_summaries)
        visible_rollup = _format_simple_lane_rollup(visible_lane_counts, WORKSPACE_LANE_DISPLAY_ORDER)
        if not visible_rollup:
            return lines

        off_page_lane_counts, off_page_mixed_count = _summarize_workspace_lanes(off_page_summaries)
        off_page_rollup = _format_simple_lane_rollup(off_page_lane_counts, WORKSPACE_LANE_DISPLAY_ORDER)
        lines.append(
            render_page_lane_summary_line(
                "workspace lanes",
                visible_rollup,
                off_page_rollup=off_page_rollup,
                visible_overlap_summary=(
                    _format_mixed_overlap_count(visible_mixed_count) if visible_mixed_count > 0 else ""
                ),
                off_page_overlap_summary=(
                    _format_mixed_overlap_count(off_page_mixed_count) if off_page_mixed_count > 0 else ""
                ),
            )
        )
        return lines

    if filter_mode in {"shell", "shell-inspect", "shell-test"} and summaries:
        lane_counts, mixed_count = _summarize_shell_lanes(summaries)
        lane_rollup = _format_simple_lane_rollup(lane_counts, SHELL_LANE_DISPLAY_ORDER)
        shell_focus_lanes = (
            ["inspect"]
            if filter_mode == "shell-inspect"
            else ["test"] if filter_mode == "shell-test" else list(SHELL_LANE_DISPLAY_ORDER)
        )
        lines = [
            render_backlog_summary_line(
                "Shell backlog",
                len(summaries),
                lane_rollup=lane_rollup,
                overlap_summary=_format_mixed_overlap_count(mixed_count) if mixed_count > 0 else "",
            ),
            render_filter_focus_line("Shell focus", shell_focus_lanes),
        ]
        if len(summaries) <= page_size:
            return lines

        page_index = _normalize_picker_page_index(len(summaries), page_size, page_index)
        start = page_index * page_size
        end = start + page_size
        visible_summaries = summaries[start:end]
        off_page_summaries = summaries[:start] + summaries[end:]
        visible_lane_counts, visible_mixed_count = _summarize_shell_lanes(visible_summaries)
        visible_rollup = _format_simple_lane_rollup(visible_lane_counts, SHELL_LANE_DISPLAY_ORDER)
        if not visible_rollup:
            return lines

        off_page_lane_counts, off_page_mixed_count = _summarize_shell_lanes(off_page_summaries)
        off_page_rollup = _format_simple_lane_rollup(off_page_lane_counts, SHELL_LANE_DISPLAY_ORDER)
        lines.append(
            render_page_lane_summary_line(
                "shell lanes",
                visible_rollup,
                off_page_rollup=off_page_rollup,
                visible_overlap_summary=(
                    _format_mixed_overlap_count(visible_mixed_count) if visible_mixed_count > 0 else ""
                ),
                off_page_overlap_summary=(
                    _format_mixed_overlap_count(off_page_mixed_count) if off_page_mixed_count > 0 else ""
                ),
            )
        )
        return lines

    stale_filter_lanes = _stale_approval_filter_lanes(filter_mode)
    if stale_filter_lanes is None or not summaries:
        return []

    lane_counts, lane_oldest_ages = _summarize_stale_approval_lanes(summaries, lanes=stale_filter_lanes)
    lane_rollup = _format_stale_approval_lane_rollup(lane_counts, lane_oldest_ages)
    stale_focus_lanes = [lane for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER if lane in stale_filter_lanes]
    lines = [
        render_backlog_summary_line(
            _stale_approval_summary_label(filter_mode),
            len(summaries),
            lane_rollup=lane_rollup,
        ),
        render_filter_focus_line(
            "Stale lane focus",
            stale_focus_lanes,
            cutoff=format_stale_approval_cutoff(stale_approval_warning_seconds),
        ),
    ]
    if len(summaries) <= page_size:
        return lines

    page_index = _normalize_picker_page_index(len(summaries), page_size, page_index)
    start = page_index * page_size
    end = start + page_size
    visible_summaries = summaries[start:end]
    off_page_summaries = summaries[:start] + summaries[end:]
    visible_rollup = _format_stale_approval_lane_rollup(
        *_summarize_stale_approval_lanes(visible_summaries, lanes=stale_filter_lanes)
    )
    if not visible_rollup:
        return lines

    off_page_rollup = _format_stale_approval_lane_rollup(
        *_summarize_stale_approval_lanes(off_page_summaries, lanes=stale_filter_lanes)
    )
    lines.append(
        render_page_lane_summary_line(
            "stale lanes",
            visible_rollup,
            off_page_rollup=off_page_rollup,
        )
    )
    return lines


def render_recent_session_empty_state_lines(
    *,
    available_count: int,
    filter_mode: str,
    surface: str = "picker",
) -> list[str]:
    return render_recent_session_empty_state_lines_helper(
        available_count=available_count,
        filter_mode=filter_mode,
        surface=surface,
    )


def _is_stale_approval_filter_mode(filter_mode: str) -> bool:
    return filter_mode in STALE_APPROVAL_FILTER_LANES


def _workspace_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    if summary.has_workspace_inspect_activity:
        lanes.add("inspect")
    if summary.has_workspace_edit_activity:
        lanes.add("edit")
    return lanes


def _workspace_filter_focus_label(filter_mode: str) -> str:
    if filter_mode == "workspace-edit":
        return "edit"
    return "inspect"


def _summarize_workspace_lanes(summaries: list[SessionSummary]) -> tuple[dict[str, int], int]:
    lane_counts = {lane: 0 for lane in WORKSPACE_LANE_DISPLAY_ORDER}
    mixed_count = 0
    for summary in summaries:
        lanes = _workspace_lanes(summary)
        if len(lanes) > 1:
            mixed_count += 1
        for lane in lanes:
            lane_counts[lane] += 1
    return lane_counts, mixed_count


def _shell_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    if summary.has_shell_inspect_activity:
        lanes.add("inspect")
    if summary.has_shell_test_activity:
        lanes.add("test")
    return lanes


def _shell_filter_focus_label(filter_mode: str) -> str:
    if filter_mode == "shell-inspect":
        return "inspect"
    if filter_mode == "shell-test":
        return "test"
    return "inspect, test"


def _summarize_shell_lanes(summaries: list[SessionSummary]) -> tuple[dict[str, int], int]:
    lane_counts = {lane: 0 for lane in SHELL_LANE_DISPLAY_ORDER}
    mixed_count = 0
    for summary in summaries:
        lanes = _shell_lanes(summary)
        if len(lanes) > 1:
            mixed_count += 1
        for lane in lanes:
            lane_counts[lane] += 1
    return lane_counts, mixed_count


def _format_simple_lane_rollup(lane_counts: dict[str, int], display_order: tuple[str, ...]) -> str:
    return ", ".join(f"{lane} {lane_counts[lane]}" for lane in display_order if lane_counts.get(lane, 0) > 0)


def _should_render_stale_cutoff_preview_line(filter_mode: str) -> bool:
    return _is_stale_approval_filter_mode(filter_mode) and filter_mode != "approval-stale"


def _stale_approval_filter_lanes(filter_mode: str) -> frozenset[str] | None:
    return STALE_APPROVAL_FILTER_LANES.get(filter_mode)


def _approval_restore_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    for badge in summary.restored_approval_badges:
        if badge.startswith("pending "):
            lanes.add("restore queue")
        elif badge:
            lanes.add("restored")
    return lanes


def _approval_restore_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    lanes = _approval_restore_lanes(summary)
    lane_ages: dict[str, int] = {}
    if "restore queue" in lanes and summary.restored_pending_approval_age_sort_key > 0:
        lane_ages["restore queue"] = summary.restored_pending_approval_age_sort_key
    if "restored" in lanes:
        restored_age_seconds = summary.last_restored_outcome_age_sort_key
        if restored_age_seconds <= 0 and "restore queue" not in lanes:
            restored_age_seconds = summary.last_restored_approval_age_sort_key
        if restored_age_seconds > 0:
            lane_ages["restored"] = restored_age_seconds
    return lane_ages


def _summarize_approval_restore_lanes(
    summaries: list[SessionSummary],
) -> tuple[dict[str, int], dict[str, int], int]:
    lane_counts = {lane: 0 for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER}
    lane_oldest_ages = {lane: 0 for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER}
    mixed_count = 0
    for summary in summaries:
        lanes = _approval_restore_lanes(summary)
        if len(lanes) > 1:
            mixed_count += 1
        for lane in lanes:
            lane_counts[lane] += 1
        for lane, age_seconds in _approval_restore_lane_age_seconds(summary).items():
            lane_oldest_ages[lane] = max(lane_oldest_ages[lane], age_seconds)
    return lane_counts, lane_oldest_ages, mixed_count


def _format_approval_restore_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
) -> str:
    lane_parts: list[str] = []
    for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age > 0:
            part += f" (oldest {_format_age_compact(oldest_age)})"
        lane_parts.append(part)
    return ", ".join(lane_parts)


def _format_mixed_overlap_count(mixed_count: int) -> str:
    mixed_label = "session" if mixed_count == 1 else "sessions"
    return f"mixed {mixed_count} {mixed_label}"


def _stale_approval_summary_label(filter_mode: str) -> str:
    return STALE_APPROVAL_FILTER_SUMMARY_LABELS.get(filter_mode, "Stale approval backlog")


def _stale_approval_filter_focus_label(filter_mode: str) -> str:
    lanes = _stale_approval_filter_lanes(filter_mode)
    if not lanes:
        return "none"
    ordered_lanes = [lane for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER if lane in lanes]
    return render_lane_label_list(ordered_lanes)


def _summarize_stale_approval_lanes(
    summaries: list[SessionSummary],
    *,
    lanes: frozenset[str] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    lane_counts = {lane: 0 for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER}
    lane_oldest_ages = {lane: 0 for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER}
    for summary in summaries:
        for lane in _stale_approval_lanes(summary):
            if lanes is not None and lane not in lanes:
                continue
            lane_counts[lane] += 1
        for lane, age_seconds in _stale_approval_lane_age_seconds(summary).items():
            if lanes is not None and lane not in lanes:
                continue
            lane_oldest_ages[lane] = max(lane_oldest_ages[lane], age_seconds)
    return lane_counts, lane_oldest_ages


def _format_stale_approval_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
) -> str:
    lane_parts: list[str] = []
    for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age > 0:
            part += f" (oldest {_format_age_compact(oldest_age)})"
        lane_parts.append(part)
    return ", ".join(lane_parts)


def _stale_approval_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    for badge in summary.stale_approval_badges:
        if badge.startswith("restore queue "):
            lanes.add("restore queue")
        elif badge.startswith("restored "):
            lanes.add("restored")
        elif badge.startswith("pending "):
            lanes.add("pending")
        elif badge.startswith("denied "):
            lanes.add("denied")
    return lanes


def _stale_approval_badge_lane(badge: str) -> str:
    for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER:
        prefix = f"{lane} "
        if badge.startswith(prefix):
            return lane
    return ""


def _stale_approval_badge_age_label(badge: str) -> str:
    lane = _stale_approval_badge_lane(badge)
    if not lane:
        return ""
    return badge.removeprefix(f"{lane} ").strip()


def _stale_approval_badge_age_seconds(badge: str) -> int:
    age_label = _stale_approval_badge_age_label(badge)
    if not age_label:
        return 0
    unit = age_label[-1]
    value = age_label[:-1]
    if not value.isdigit():
        return 0
    amount = int(value)
    if unit == "d":
        return amount * 24 * 60 * 60
    if unit == "h":
        return amount * 60 * 60
    if unit == "m":
        return amount * 60
    if unit == "s":
        return amount
    return 0


def _stale_approval_focus_badges(summary: SessionSummary, focus_lane: str) -> list[str]:
    return [
        badge
        for badge in summary.stale_approval_badges
        if _stale_approval_badge_lane(badge) == focus_lane
    ]


def _inline_approval_summary(summary: str) -> str:
    return summary.replace(" | ", "; ")


def _approval_restore_focus_lanes(summary: SessionSummary, filter_mode: str) -> list[str]:
    if filter_mode != "approval-restore":
        return []
    lanes = _approval_restore_lanes(summary)
    return [lane for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER if lane in lanes]


def _approval_restore_age_label(badge: str) -> str:
    for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER:
        prefix = f"{lane} "
        if badge.startswith(prefix):
            return badge.removeprefix(prefix).strip()
    return badge


def _approval_restore_restored_age_summary(summary: SessionSummary) -> str:
    return _restored_outcome_preview_age_summary(summary) or summary.last_restored_approval_age_summary


def _approval_restore_age_badges(
    summary: SessionSummary,
    filter_mode: str,
    *,
    focus_lanes: list[str] | None = None,
) -> list[str]:
    if filter_mode != "approval-restore":
        return []

    lanes = focus_lanes if focus_lanes is not None else _approval_restore_focus_lanes(summary, filter_mode)
    badges: list[str] = []
    if "restore queue" in lanes and summary.restored_pending_approval_age_summary:
        badges.append(f"restore queue {summary.restored_pending_approval_age_summary}")
    if "restored" in lanes:
        restored_age_summary = _approval_restore_restored_age_summary(summary)
        if restored_age_summary:
            badges.append(f"restored {restored_age_summary}")
    return badges


def _render_approval_restore_row_age_suffixes(
    summary: SessionSummary,
    filter_mode: str,
) -> tuple[str, str, bool]:
    default_age_suffix = ""
    if summary.restored_pending_approval_age_summary:
        default_age_suffix = f" | approval restore age: {summary.restored_pending_approval_age_summary}"
    elif summary.last_restored_approval_age_summary:
        default_age_suffix = f" | approval restore age: {summary.last_restored_approval_age_summary}"

    focus_lanes = _approval_restore_focus_lanes(summary, filter_mode)
    focus_suffix = render_lane_focus_suffix("restore focus", focus_lanes)
    age_badges = _approval_restore_age_badges(summary, filter_mode, focus_lanes=focus_lanes)
    age_suffix = render_compact_badge_row_suffix(
        default_suffix=default_age_suffix,
        focused_badges=age_badges,
        singular_label="approval restore age",
        plural_label="approval restore ages",
        singular_value_transform=_approval_restore_age_label,
    )
    return age_suffix, focus_suffix, "restored" in focus_lanes


def _should_render_approval_restore_focus_preview_line(filter_mode: str) -> bool:
    return filter_mode != "approval-restore"


def _render_approval_restore_preview_lines(
    summary: SessionSummary,
    filter_mode: str,
) -> tuple[list[str], bool]:
    default_lines: list[str] = []
    if summary.restored_pending_approval_age_summary:
        default_lines.append(f"- approval restore age: {summary.restored_pending_approval_age_summary}")
    elif summary.last_restored_approval_age_summary:
        default_lines.append(f"- approval restore age: {summary.last_restored_approval_age_summary}")

    focus_lanes = _approval_restore_focus_lanes(summary, filter_mode)
    age_badges = _approval_restore_age_badges(summary, filter_mode, focus_lanes=focus_lanes)
    lines = render_compact_badge_preview_lines(
        default_lines=default_lines,
        focused_badges=age_badges,
        focus_lanes=focus_lanes,
        focus_label="restore focus",
        include_focus_line=_should_render_approval_restore_focus_preview_line(filter_mode),
        singular_label="approval restore age",
        plural_label="approval restore ages",
        singular_value_transform=_approval_restore_age_label,
    )
    return lines, "restored" in focus_lanes


def _render_restored_row_suffixes(
    summary: SessionSummary,
    filter_mode: str,
    *,
    suppress_outcome_age: bool = False,
) -> tuple[str, str, str]:
    if filter_mode not in {"approval-restore", "approval-stale-restored"}:
        return "", "", ""

    has_separate_outcome = bool(
        summary.last_restored_outcome_summary
        and summary.last_restored_outcome_summary != summary.last_restored_approval_summary
    )
    if not summary.restored_pending_approval_queue_summary and not has_separate_outcome:
        return "", "", ""

    current_suffix = ""
    if summary.last_restored_approval_summary:
        current_suffix = f" | restored current: {_inline_approval_summary(summary.last_restored_approval_summary)}"

    outcome_suffix = ""
    outcome_age_suffix = ""
    if has_separate_outcome:
        outcome_suffix = f" | restored outcome: {_inline_approval_summary(summary.last_restored_outcome_summary)}"
        if not suppress_outcome_age and summary.last_restored_outcome_age_summary and (
            not summary.restored_pending_approval_age_summary
            or summary.last_restored_outcome_age_summary != summary.restored_pending_approval_age_summary
        ):
            outcome_age_suffix = f" | restored outcome age: {summary.last_restored_outcome_age_summary}"

    return current_suffix, outcome_suffix, outcome_age_suffix


def _restored_outcome_preview_age_summary(summary: SessionSummary) -> str:
    if summary.last_restored_outcome_summary and summary.last_restored_outcome_summary != summary.last_restored_approval_summary:
        return summary.last_restored_outcome_age_summary
    return ""


def _restored_outcome_preview_age_label(summary: SessionSummary) -> str:
    if summary.last_restored_outcome_summary and summary.last_restored_outcome_summary != summary.last_restored_approval_summary:
        return "latest restored outcome age"
    return "last restored age"


def _render_stale_approval_row_suffix(
    summary: SessionSummary,
    filter_mode: str,
    *,
    stale_focus_lanes: list[str] | None = None,
) -> str:
    default_suffix = _default_stale_approval_row_suffix(summary)
    focus_badges = _focused_stale_approval_badges(summary, filter_mode, stale_focus_lanes=stale_focus_lanes)
    return render_compact_badge_row_suffix(
        default_suffix=default_suffix,
        focused_badges=focus_badges,
        singular_label="approval stale age",
        plural_label="approval stale ages",
        singular_value_transform=_stale_approval_badge_age_label,
    )


def _render_stale_approval_preview_lines(summary: SessionSummary, filter_mode: str) -> list[str]:
    default_line = _default_stale_approval_preview_line(summary)
    if not default_line:
        return []

    focus_lanes = _stale_approval_focus_lanes(summary, filter_mode)
    focus_badges = _focused_stale_approval_badges(summary, filter_mode, stale_focus_lanes=focus_lanes)
    return render_compact_badge_preview_lines(
        default_lines=[default_line],
        focused_badges=focus_badges,
        focus_lanes=focus_lanes,
        focus_label="stale focus",
        include_focus_line=True,
        singular_label="approval stale age",
        plural_label="approval stale ages",
        singular_value_transform=_stale_approval_badge_age_label,
    )


def _default_stale_approval_row_suffix(summary: SessionSummary) -> str:
    if not summary.stale_approval_badges:
        return ""
    return f" | approval stale: {', '.join(summary.stale_approval_badges)}"


def _default_stale_approval_preview_line(summary: SessionSummary) -> str:
    if not summary.stale_approval_badges:
        return ""
    return f"- approval stale: {', '.join(summary.stale_approval_badges)}"


def _focused_stale_approval_badges(
    summary: SessionSummary,
    filter_mode: str,
    *,
    stale_focus_lanes: list[str] | None = None,
) -> list[str]:
    if not summary.stale_approval_badges:
        return []
    focus_lanes = stale_focus_lanes if stale_focus_lanes is not None else _stale_approval_focus_lanes(summary, filter_mode)
    if not focus_lanes:
        return []

    focus_badges: list[str] = []
    for lane in focus_lanes:
        focus_badges.extend(_stale_approval_focus_badges(summary, lane))
    return focus_badges


def _stale_approval_focus_lanes(summary: SessionSummary, filter_mode: str) -> list[str]:
    lanes = _stale_approval_filter_lanes(filter_mode)
    if not lanes:
        return []
    summary_lanes = _stale_approval_lanes(summary)
    return [lane for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER if lane in lanes and lane in summary_lanes]


def _stale_approval_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    lane_ages: dict[str, int] = {}
    for badge in summary.stale_approval_badges:
        lane = _stale_approval_badge_lane(badge)
        if not lane:
            continue
        lane_ages[lane] = max(lane_ages.get(lane, 0), _stale_approval_badge_age_seconds(badge))
    return lane_ages


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
    stale_filter_lanes = _stale_approval_filter_lanes(filter_mode)
    if stale_filter_lanes is not None:
        return bool(_stale_approval_lanes(summary) & stale_filter_lanes)
    if filter_mode == "tool":
        return bool(summary.last_tool_preview or summary.last_tool_badges)
    if filter_mode == "workspace-inspect":
        return summary.has_workspace_inspect_activity
    if filter_mode == "workspace-edit":
        return summary.has_workspace_edit_activity
    if filter_mode == "intervention":
        return summary.has_intervention_activity
    if filter_mode == "shell":
        return summary.has_shell_inspect_activity or summary.has_shell_test_activity
    if filter_mode == "shell-inspect":
        return summary.has_shell_inspect_activity
    if filter_mode == "shell-test":
        return summary.has_shell_test_activity
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
            summary.pending_approval_age_sort_key,
            summary.denied_approval_count > 0,
            denied_key,
            fresh_denied_key,
            summary.last_denied_approval_age_sort_key,
            restored_denied_key,
            summary.last_restored_approval_age_sort_key,
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
            summary.stale_session_sort_key,
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


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds_from_timestamp(value: str | None) -> int | None:
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return None
    age_seconds = int((datetime.now(UTC) - parsed).total_seconds())
    return max(age_seconds, 0)


def _format_age_compact(age_seconds: int) -> str:
    if age_seconds >= 24 * 60 * 60:
        return f"{age_seconds // (24 * 60 * 60)}d"
    if age_seconds >= 60 * 60:
        return f"{age_seconds // (60 * 60)}h"
    if age_seconds >= 60:
        return f"{age_seconds // 60}m"
    return f"{age_seconds}s"


def _pending_approval_age_seconds(pending_approvals: list[ApprovalRequest]) -> int | None:
    ages = [age for age in (_age_seconds_from_timestamp(approval.created_at) for approval in pending_approvals) if age is not None]
    if not ages:
        return None
    return max(ages)


def _pending_approval_age_summary(pending_approvals: list[ApprovalRequest]) -> str:
    oldest_age_seconds = _pending_approval_age_seconds(pending_approvals)
    if oldest_age_seconds is None:
        return ""
    label = _format_age_compact(oldest_age_seconds)
    if len(pending_approvals) <= 1:
        return label
    return f"oldest {label}"


def _approval_record_age_seconds(record: dict[str, object] | None) -> int:
    if record is None:
        return 0
    age_seconds = _age_seconds_from_timestamp(str(record.get("timestamp")) if record.get("timestamp") else None)
    if age_seconds is None:
        return 0
    return age_seconds


def _approval_record_age_summary(record: dict[str, object] | None) -> str:
    age_seconds = _approval_record_age_seconds(record)
    if age_seconds <= 0:
        return ""
    return _format_age_compact(age_seconds)


def _stale_approval_badges(
    *,
    pending_approval_age_seconds: int,
    pending_approval_age_summary: str,
    last_denied_approval_age_seconds: int,
    last_denied_approval_age_summary: str,
    restored_pending_approval_age_seconds: int,
    restored_pending_approval_age_summary: str,
    last_restored_approval_age_seconds: int,
    last_restored_approval_age_summary: str,
    stale_approval_warning_seconds: int = STALE_APPROVAL_WARNING_SECONDS,
) -> list[str]:
    badges: list[str] = []
    if pending_approval_age_seconds >= stale_approval_warning_seconds and pending_approval_age_summary:
        badges.append(f"pending {pending_approval_age_summary}")
    if (
        restored_pending_approval_age_seconds >= stale_approval_warning_seconds
        and restored_pending_approval_age_summary
    ):
        badges.append(f"restore queue {restored_pending_approval_age_summary}")
    if (
        last_restored_approval_age_seconds >= stale_approval_warning_seconds and last_restored_approval_age_summary
    ):
        badges.append(f"restored {last_restored_approval_age_summary}")
    if last_denied_approval_age_seconds >= stale_approval_warning_seconds and last_denied_approval_age_summary:
        badges.append(f"denied {last_denied_approval_age_summary}")
    return badges


def _stale_session_status(activity_timestamp: float) -> tuple[str, list[str], int]:
    age_seconds = max(int(datetime.now(UTC).timestamp() - activity_timestamp), 0)
    if age_seconds < STALE_SESSION_WARNING_SECONDS:
        return "", [], 0
    badge_level = "warning"
    if age_seconds >= STALE_SESSION_DANGER_SECONDS:
        badge_level = "danger"
    age_label = _format_age_compact(age_seconds)
    return f"idle {age_label} since last artifact activity", [f"{badge_level} {age_label}"], age_seconds


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
