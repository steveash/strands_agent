from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

from .artifacts import (
    SessionArtifactStore,
    SessionPickerState,
    SessionState,
    TurnArtifact,
    load_session_picker_state,
    save_session_picker_state,
)
from .summary_utils import (
    render_badged_preview_line,
    render_badged_row_suffix,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_lane_focus_suffix,
    render_lane_label_list,
    render_numbered_preview_section_lines,
    render_page_label,
    render_page_metric_summary_line,
    render_page_window_label,
    render_picker_controls_line,
    render_picker_empty_filter_adjust_guidance,
    render_picker_empty_filter_prompt,
    render_picker_empty_filter_visible_guidance,
    render_picker_invalid_key_guidance,
    render_picker_invalid_selection_message,
    render_picker_selection_prompt,
    render_preview_badges_line,
    render_preview_detail_line,
    render_recent_session_filter_summary_block_lines,
    render_recent_session_metric_summary_block_lines,
    render_recent_session_list_row,
    render_recent_session_summary_line,
    render_row_badges_suffix,
    render_row_detail_suffix,
    render_recent_session_empty_state_lines as render_recent_session_empty_state_lines_helper,
    render_recent_session_page_banner,
    render_selected_preview_section_lines,
    render_selected_session_preview_header_lines,
    render_selected_session_preview_lines,
)
from ..timeline import summarize_event
from ..runtime import ApprovalRequest
from ..tools.workspace import resolve_shell_command

MAX_RECENT_SESSIONS = 8
MAX_PROMPT_PREVIEW = 60
MAX_EVENT_PREVIEW = 50
MAX_TOOL_PREVIEW = 72
MAX_INTERVENTION_PREVIEW = 160
MAX_TOOL_STREAK_PREVIEWS = 3
MAX_INTERVENTION_PREVIEWS = 3
MAX_INTERVENTION_ROLLUP_EVENTS = 6
MAX_SHELL_STREAK_PREVIEWS = 3
MAX_SHELL_ROLLUP_EVENTS = 6
MAX_FAILURE_ROLLUP_EVENTS = 6
MIN_LANE_ROLLUP_AGE_SECONDS = 60
MetricRollupT = TypeVar("MetricRollupT")
STALE_SESSION_WARNING_SECONDS = 7 * 24 * 60 * 60
STALE_SESSION_DANGER_SECONDS = 30 * 24 * 60 * 60
STALE_APPROVAL_WARNING_SECONDS = STALE_SESSION_WARNING_SECONDS
APPROVAL_STATUS_DISPLAY_ORDER = ("pending", "approved", "denied", "blocked")
APPROVAL_TOOL_FAMILY_DISPLAY_ORDER = ("test", "edit", "shell", "tool")
INTERVENTION_TARGET_KIND_DISPLAY_ORDER = ("path", "command")
APPROVAL_RESTORE_LANE_DISPLAY_ORDER = ("restore queue", "restored")
TOOL_LANE_DISPLAY_ORDER = ("workspace", "shell", "other")
INTERVENTION_LANE_DISPLAY_ORDER = ("pending", "blocked", "approved", "denied", "restored")
INTERVENTION_FOLLOW_UP_DISPLAY_ORDER = ("approved result", "denied request")
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
    pending_approval_oldest_at: str = ""
    pending_approval_badges: list[str] = field(default_factory=list)
    approval_status_badges: list[str] = field(default_factory=list)
    approval_focus_badges: list[str] = field(default_factory=list)
    last_approval_summary: str = ""
    denied_approval_count: int = 0
    denied_approval_badges: list[str] = field(default_factory=list)
    last_denied_approval_summary: str = ""
    last_denied_approval_age_summary: str = ""
    last_denied_approval_at: str = ""
    last_denied_approval_age_sort_key: int = 0
    restored_approval_count: int = 0
    restored_approval_badges: list[str] = field(default_factory=list)
    restored_approval_tool_badges: list[str] = field(default_factory=list)
    restored_pending_approval_queue_summary: str = ""
    restored_pending_approval_age_summary: str = ""
    restored_pending_approval_oldest_at: str = ""
    restored_pending_approval_age_sort_key: int = 0
    last_restored_approval_summary: str = ""
    last_restored_approval_age_summary: str = ""
    last_restored_approval_at: str = ""
    last_restored_approval_age_sort_key: int = 0
    last_restored_outcome_summary: str = ""
    last_restored_outcome_age_summary: str = ""
    last_restored_outcome_at: str = ""
    last_restored_outcome_age_sort_key: int = 0
    stale_approval_badges: list[str] = field(default_factory=list)
    intervention_badges: list[str] = field(default_factory=list)
    intervention_family_counts: dict[str, int] = field(default_factory=dict)
    intervention_target_kind_counts: dict[str, int] = field(default_factory=dict)
    intervention_follow_up_counts: dict[str, int] = field(default_factory=dict)
    intervention_unique_count: int = 0
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
    tool_lane_age_sort_keys: dict[str, int] = field(default_factory=dict)
    tool_lane_timestamps: dict[str, str] = field(default_factory=dict)
    workspace_lane_badges: list[str] = field(default_factory=list)
    has_workspace_inspect_activity: bool = False
    has_workspace_edit_activity: bool = False
    has_pending_workspace_edit_approval: bool = False
    has_fresh_pending_workspace_edit_approval: bool = False
    has_restored_pending_workspace_edit_approval: bool = False
    pending_workspace_edit_queue_previews: list[str] = field(default_factory=list)
    pending_workspace_edit_age_sort_key: int = 0
    pending_workspace_edit_oldest_at: str = ""
    restored_pending_workspace_edit_age_sort_key: int = 0
    restored_pending_workspace_edit_oldest_at: str = ""
    last_workspace_preview: str = ""
    recent_workspace_previews: list[str] = field(default_factory=list)
    last_workspace_inspect_preview: str = ""
    recent_workspace_inspect_previews: list[str] = field(default_factory=list)
    last_workspace_edit_preview: str = ""
    recent_workspace_edit_previews: list[str] = field(default_factory=list)
    workspace_lane_age_sort_keys: dict[str, int] = field(default_factory=dict)
    workspace_lane_timestamps: dict[str, str] = field(default_factory=dict)
    shell_activity_badges: list[str] = field(default_factory=list)
    shell_lane_badges: list[str] = field(default_factory=list)
    has_shell_inspect_activity: bool = False
    has_shell_test_activity: bool = False
    has_pending_shell_test_approval: bool = False
    has_fresh_pending_shell_test_approval: bool = False
    has_restored_pending_shell_test_approval: bool = False
    pending_shell_test_queue_previews: list[str] = field(default_factory=list)
    pending_shell_test_age_sort_key: int = 0
    pending_shell_test_oldest_at: str = ""
    restored_pending_shell_test_age_sort_key: int = 0
    restored_pending_shell_test_oldest_at: str = ""
    last_shell_preview: str = ""
    recent_shell_previews: list[str] = field(default_factory=list)
    last_shell_inspect_preview: str = ""
    recent_shell_inspect_previews: list[str] = field(default_factory=list)
    last_shell_test_preview: str = ""
    recent_shell_test_previews: list[str] = field(default_factory=list)
    shell_lane_age_sort_keys: dict[str, int] = field(default_factory=dict)
    shell_lane_timestamps: dict[str, str] = field(default_factory=dict)
    failure_activity_badges: list[str] = field(default_factory=list)
    recent_failure_count: int = 0
    recent_shell_failure_count: int = 0
    recent_test_failure_count: int = 0
    recent_tool_failure_count: int = 0
    stale_session_badges: list[str] = field(default_factory=list)
    stale_session_summary: str = ""
    pending_approval_age_sort_key: int = 0
    session_activity_age_sort_key: int = 0
    stale_session_sort_key: int = 0
    restore_badges: list[str] = field(default_factory=list)
    draft_prompt_preview: str = ""

    def _focused_workspace_preview_context(self, filter_mode: str) -> tuple[str, list[str]]:
        if filter_mode == "workspace-inspect":
            return self.last_workspace_inspect_preview, self.recent_workspace_inspect_previews
        if filter_mode == "workspace-edit":
            return self.last_workspace_edit_preview, self.recent_workspace_edit_previews
        return self.last_workspace_preview, self.recent_workspace_previews

    def _focused_shell_preview_context(self, filter_mode: str) -> tuple[str, list[str]]:
        if filter_mode == "shell-inspect":
            return self.last_shell_inspect_preview, self.recent_shell_inspect_previews
        if filter_mode == "shell-test":
            return self.last_shell_test_preview, self.recent_shell_test_previews
        return self.last_shell_preview, self.recent_shell_previews

    def _focused_tool_preview_context(self, filter_mode: str) -> tuple[str, list[str], bool]:
        if filter_mode in {"workspace-inspect", "workspace-edit"}:
            preview, recent = self._focused_workspace_preview_context(filter_mode)
            return preview, recent, True
        if filter_mode in {"shell-inspect", "shell-test"}:
            preview, recent = self._focused_shell_preview_context(filter_mode)
            return preview, recent, True
        return self.last_tool_preview, self.recent_tool_previews, False

    def _focused_lane_pending_only_state(self, filter_mode: str) -> tuple[str, str]:
        if (
            filter_mode == "workspace-edit"
            and self.has_pending_workspace_edit_approval
            and not self.last_workspace_edit_preview
            and not self.recent_workspace_edit_previews
        ):
            return "workspace focus", "pending only"
        if (
            filter_mode == "shell-test"
            and self.has_pending_shell_test_approval
            and not self.last_shell_test_preview
            and not self.recent_shell_test_previews
        ):
            return "shell focus", "pending only"
        return "", ""

    def _focused_lane_pending_only_preview_value(self, filter_mode: str) -> str:
        if filter_mode == "workspace-edit":
            return "pending only until an edit executes"
        if filter_mode == "shell-test":
            return "pending only until a test executes"
        return ""

    def _focused_lane_pending_only_queue_previews(self, filter_mode: str) -> list[str]:
        if not self.has_pending_only_lane_match(filter_mode):
            return []
        if filter_mode == "workspace-edit":
            return self.pending_workspace_edit_queue_previews
        if filter_mode == "shell-test":
            return self.pending_shell_test_queue_previews
        return []

    def _focused_lane_pending_only_queue_provenance(self, filter_mode: str) -> str:
        if not self.has_pending_only_lane_match(filter_mode):
            return ""
        if filter_mode == "workspace-edit":
            has_fresh = self.has_fresh_pending_workspace_edit_approval
            has_restored = self.has_restored_pending_workspace_edit_approval
        elif filter_mode == "shell-test":
            has_fresh = self.has_fresh_pending_shell_test_approval
            has_restored = self.has_restored_pending_shell_test_approval
        else:
            return ""
        if has_fresh and has_restored:
            return "fresh + restored approval queue"
        if has_restored:
            return "restored approval queue"
        if has_fresh:
            return "fresh approval queue"
        return "approval queue"

    def _focused_lane_pending_only_age_source(self, filter_mode: str) -> tuple[str, str, str]:
        focused_lane_label, focused_lane_value = self._focused_lane_pending_only_state(filter_mode)
        if not focused_lane_label or not focused_lane_value:
            return "", "", ""
        age_seconds, timestamp, used_activity_fallback = self.pending_only_lane_oldest_age_and_timestamp_source(
            filter_mode
        )
        age_summary = _format_age_compact(age_seconds) if age_seconds > 0 else ""
        age_source = "activity fallback" if used_activity_fallback else "approval created_at"
        return age_summary, timestamp, age_source

    def has_pending_only_lane_match(self, filter_mode: str) -> bool:
        return bool(self._focused_lane_pending_only_state(filter_mode)[1])

    def has_restored_pending_only_lane_match(self, filter_mode: str) -> bool:
        if not self.has_pending_only_lane_match(filter_mode):
            return False
        if filter_mode == "workspace-edit":
            return self.has_restored_pending_workspace_edit_approval
        if filter_mode == "shell-test":
            return self.has_restored_pending_shell_test_approval
        return False

    def _pending_only_lane_age_and_timestamp_with_activity_fallback(
        self,
        age_seconds: int,
        timestamp: str,
        *,
        has_pending_match: bool,
    ) -> tuple[int, str, bool]:
        if age_seconds > 0 or timestamp:
            return age_seconds, timestamp, False
        if not has_pending_match or self.session_activity_age_sort_key <= 0:
            return 0, "", False
        return self.session_activity_age_sort_key, self.updated_at, True

    def pending_only_lane_oldest_age_and_timestamp(self, filter_mode: str) -> tuple[int, str]:
        age_seconds, timestamp, _used_activity_fallback = self.pending_only_lane_oldest_age_and_timestamp_source(
            filter_mode
        )
        return age_seconds, timestamp

    def pending_only_lane_oldest_age_and_timestamp_source(self, filter_mode: str) -> tuple[int, str, bool]:
        if filter_mode == "workspace-edit":
            return self._pending_only_lane_age_and_timestamp_with_activity_fallback(
                self.pending_workspace_edit_age_sort_key,
                self.pending_workspace_edit_oldest_at,
                has_pending_match=self.has_pending_workspace_edit_approval,
            )
        if filter_mode == "shell-test":
            return self._pending_only_lane_age_and_timestamp_with_activity_fallback(
                self.pending_shell_test_age_sort_key,
                self.pending_shell_test_oldest_at,
                has_pending_match=self.has_pending_shell_test_approval,
            )
        return 0, "", False

    def restored_pending_only_lane_oldest_age_and_timestamp(self, filter_mode: str) -> tuple[int, str]:
        age_seconds, timestamp, _used_activity_fallback = self.restored_pending_only_lane_oldest_age_and_timestamp_source(
            filter_mode
        )
        return age_seconds, timestamp

    def restored_pending_only_lane_oldest_age_and_timestamp_source(self, filter_mode: str) -> tuple[int, str, bool]:
        if filter_mode == "workspace-edit":
            return self._pending_only_lane_age_and_timestamp_with_activity_fallback(
                self.restored_pending_workspace_edit_age_sort_key,
                self.restored_pending_workspace_edit_oldest_at,
                has_pending_match=self.has_restored_pending_workspace_edit_approval,
            )
        if filter_mode == "shell-test":
            return self._pending_only_lane_age_and_timestamp_with_activity_fallback(
                self.restored_pending_shell_test_age_sort_key,
                self.restored_pending_shell_test_oldest_at,
                has_pending_match=self.has_restored_pending_shell_test_approval,
            )
        return 0, "", False

    def render_line(
        self,
        index: int,
        *,
        include_attention_reason: bool = False,
        filter_mode: str = "all",
    ) -> str:
        prompt_suffix = render_row_detail_suffix("last prompt", self.last_prompt_preview)
        pending_value = ""
        if self.pending_approval_count == 1 and self.pending_approval_tool:
            pending_value = self.pending_approval_tool
        elif self.pending_approval_count > 1:
            tool_hint = f" ({self.pending_approval_queue_summary})" if self.pending_approval_queue_summary else ""
            pending_value = f"{self.pending_approval_count} approvals{tool_hint}"
        pending_suffix = render_row_detail_suffix("pending", pending_value)
        pending_age_suffix = render_row_detail_suffix("pending age", self.pending_approval_age_summary)
        pending_tool_suffix = render_row_badges_suffix("pending tools", self.pending_approval_badges)
        approval_suffix = render_row_badges_suffix("approvals", self.approval_status_badges)
        approval_focus_suffix = render_row_badges_suffix(
            "approval focus",
            self.approval_focus_badges,
            separator="/",
        )
        denied_suffix = render_row_badges_suffix("denied", self.denied_approval_badges)
        denied_age_suffix = render_row_detail_suffix("denied age", self.last_denied_approval_age_summary)
        approval_restore_suffix = render_row_badges_suffix("approval restore", self.restored_approval_badges)
        approval_restore_tool_suffix = render_row_badges_suffix(
            "approval restore tools",
            self.restored_approval_tool_badges,
        )
        approval_restore_queue_suffix = render_row_detail_suffix(
            "approval restore queue",
            self.restored_pending_approval_queue_summary,
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
        stale_focus_suffix = _render_stale_approval_focus_suffix(filter_mode, stale_focus_lanes)
        intervention_suffix = render_row_badges_suffix("intervention", self.intervention_badges)
        focused_tool_preview, focused_recent_tool_previews, focused_tool_filter = self._focused_tool_preview_context(
            filter_mode
        )
        if focused_tool_filter:
            tool_hint = render_row_detail_suffix("last tool", focused_tool_preview)
        else:
            tool_hint = render_badged_row_suffix("last tool", self.last_tool_preview, self.last_tool_badges)
        tool_streak_suffix = render_row_detail_suffix(
            "tool streak",
            f"{len(focused_recent_tool_previews)} recent" if len(focused_recent_tool_previews) > 1 else "",
        )
        focused_lane_label, focused_lane_value = self._focused_lane_pending_only_state(filter_mode)
        focused_lane_pending_only_suffix = render_row_detail_suffix(focused_lane_label, focused_lane_value)
        workspace_lane_suffix = render_row_badges_suffix("workspace lanes", self.workspace_lane_badges)
        shell_suffix = render_row_badges_suffix("shell", self.shell_activity_badges)
        shell_lane_suffix = render_row_badges_suffix("shell lanes", self.shell_lane_badges)
        failure_suffix = render_row_badges_suffix("failures", self.failure_activity_badges)
        attention_suffix = ""
        attention_badge = _attention_reason_badge(self) if include_attention_reason and self.attention_reason_summary else ""
        if attention_badge and not _is_redundant_attention_badge(self, attention_badge):
            attention_suffix = render_row_detail_suffix("attention", attention_badge)
        event_suffix = render_row_detail_suffix("last event", self.last_event_preview)
        stale_suffix = render_row_badges_suffix("stale", self.stale_session_badges)
        restore_suffix = render_row_badges_suffix("restore", self.restore_badges)
        return render_recent_session_summary_line(
            index=index,
            session_id=self.session_id,
            turn_count=self.turn_count,
            updated_at=self.updated_at,
            suffixes=[
                pending_suffix,
                pending_age_suffix,
                pending_tool_suffix,
                approval_suffix,
                approval_focus_suffix,
                denied_suffix,
                denied_age_suffix,
                approval_restore_suffix,
                approval_restore_tool_suffix,
                approval_restore_queue_suffix,
                approval_restore_age_suffix,
                restore_focus_suffix,
                restored_current_suffix,
                restored_outcome_suffix,
                restored_outcome_age_suffix,
                stale_approval_suffix,
                stale_focus_suffix,
                intervention_suffix,
                attention_suffix,
                stale_suffix,
                restore_suffix,
                prompt_suffix,
                tool_hint,
                tool_streak_suffix,
                focused_lane_pending_only_suffix,
                workspace_lane_suffix,
                shell_suffix,
                shell_lane_suffix,
                failure_suffix,
                event_suffix,
            ],
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
        header_lines = render_selected_session_preview_header_lines(
            visible_index=visible_index,
            overall_index=overall_index,
            total_matches=total_matches,
            session_id=self.session_id,
            session_dir=self.session_dir,
        )

        stale_cutoff_lines: list[str] = []
        if _should_render_stale_cutoff_preview_line(filter_mode):
            stale_cutoff_lines = render_preview_detail_line(
                "stale lane focus",
                f"{_stale_approval_filter_focus_label(filter_mode)} | "
                f"cutoff: {format_stale_approval_cutoff(stale_approval_warning_seconds)}",
            )
        status_lines = render_selected_preview_section_lines(
            stale_cutoff_lines,
            render_preview_detail_line("attention reason", self.attention_reason_summary),
        )

        pending_lines: list[str] = []
        if self.pending_approval_count > 0:
            pending_line = self.pending_approval_summary or self.pending_approval_tool or "pending approval"
            if self.pending_approval_count > 1:
                pending_line = f"{self.pending_approval_count} approvals | first: {pending_line}"
            pending_lines = render_preview_detail_line("pending", pending_line)
        approval_restore_preview_lines, suppress_restored_preview_age = _render_approval_restore_preview_lines(
            self,
            filter_mode,
        )
        restored_current_lines: list[str]
        restored_outcome_lines: list[str] = []
        if self.last_restored_outcome_summary and self.last_restored_outcome_summary != self.last_restored_approval_summary:
            restored_current_lines = render_preview_detail_line(
                "restored current approval",
                self.last_restored_approval_summary,
            )
            restored_outcome_lines = render_preview_detail_line(
                "latest restored outcome",
                self.last_restored_outcome_summary,
            )
        else:
            restored_current_lines = render_preview_detail_line(
                "last restored approval",
                self.last_restored_approval_summary,
            )
        restored_outcome_age_summary = _restored_outcome_preview_age_summary(self)
        restored_outcome_age_label = _restored_outcome_preview_age_label(self)
        restored_outcome_age_lines: list[str] = []
        if not suppress_restored_preview_age and restored_outcome_age_summary and (
            not self.restored_pending_approval_age_summary
            or restored_outcome_age_summary != self.restored_pending_approval_age_summary
        ):
            restored_outcome_age_lines = render_preview_detail_line(
                restored_outcome_age_label,
                restored_outcome_age_summary,
            )
        elif not suppress_restored_preview_age and self.last_restored_approval_age_summary and (
            not self.restored_pending_approval_age_summary
            or self.last_restored_approval_age_summary != self.restored_pending_approval_age_summary
        ):
            restored_outcome_age_lines = render_preview_detail_line(
                "last restored age",
                self.last_restored_approval_age_summary,
            )
        approval_lines = render_selected_preview_section_lines(
            pending_lines,
            render_preview_detail_line("pending queue", self.pending_approval_queue_summary),
            render_preview_detail_line("pending age", self.pending_approval_age_summary),
            render_preview_detail_line("pending at", self.pending_approval_oldest_at),
            render_preview_badges_line("pending tools", self.pending_approval_badges),
            render_preview_badges_line("approvals", self.approval_status_badges),
            render_preview_detail_line("approval focus", "/".join(self.approval_focus_badges)),
            render_preview_detail_line("last approval", self.last_approval_summary),
            render_preview_badges_line("denied", self.denied_approval_badges),
            render_preview_detail_line("last denied approval", self.last_denied_approval_summary),
            render_preview_detail_line("last denied age", self.last_denied_approval_age_summary),
            render_preview_detail_line("last denied at", self.last_denied_approval_at),
            render_preview_badges_line("approval restore", self.restored_approval_badges),
            render_preview_badges_line("approval restore tools", self.restored_approval_tool_badges),
            render_preview_detail_line("approval restore queue", self.restored_pending_approval_queue_summary),
            approval_restore_preview_lines,
            render_preview_detail_line("approval restore at", self.restored_pending_approval_oldest_at),
            restored_current_lines,
            render_preview_detail_line("last restored at", self.last_restored_approval_at),
            restored_outcome_lines,
            restored_outcome_age_lines,
            render_preview_detail_line("latest restored outcome at", self.last_restored_outcome_at),
            _render_stale_approval_preview_lines(self, filter_mode),
        )

        intervention_lines = render_selected_preview_section_lines(
            render_preview_badges_line("intervention", self.intervention_badges),
            render_preview_detail_line("last intervention", self.last_intervention_preview),
            render_numbered_preview_section_lines("recent interventions", self.recent_intervention_previews),
        )

        session_lines = render_selected_preview_section_lines(
            render_preview_badges_line("restore", self.restore_badges),
            render_preview_detail_line("session age", self.stale_session_summary),
            render_preview_detail_line("draft", self.draft_prompt_preview),
            render_preview_detail_line("last prompt", self.last_prompt_preview),
        )

        focused_workspace_preview, focused_workspace_previews = self._focused_workspace_preview_context(filter_mode)
        focused_shell_preview, focused_shell_previews = self._focused_shell_preview_context(filter_mode)
        focused_tool_preview, focused_recent_tool_previews, focused_tool_filter = self._focused_tool_preview_context(
            filter_mode
        )
        focused_lane_label, focused_lane_value = self._focused_lane_pending_only_state(filter_mode)
        focused_lane_preview_lines = render_preview_detail_line(
            focused_lane_label,
            self._focused_lane_pending_only_preview_value(filter_mode) if focused_lane_value else "",
        )
        focused_lane_age_summary, focused_lane_timestamp, focused_lane_age_source = (
            self._focused_lane_pending_only_age_source(filter_mode)
        )
        focused_lane_age_lines = render_preview_detail_line(
            f"{focused_lane_label} age",
            focused_lane_age_summary,
        )
        focused_lane_timestamp_lines = render_preview_detail_line(
            f"{focused_lane_label} at",
            focused_lane_timestamp,
        )
        focused_lane_age_source_lines = render_preview_detail_line(
            f"{focused_lane_label} age source",
            focused_lane_age_source,
        )
        focused_lane_queue_provenance_lines = render_preview_detail_line(
            f"{focused_lane_label} queue provenance",
            self._focused_lane_pending_only_queue_provenance(filter_mode),
        )
        focused_lane_queue_preview_lines = render_numbered_preview_section_lines(
            f"{focused_lane_label} queue",
            self._focused_lane_pending_only_queue_previews(filter_mode),
        )

        tool_lines = []
        if not focused_tool_filter:
            tool_lines = render_selected_preview_section_lines(
                render_badged_preview_line("last tool", self.last_tool_preview, self.last_tool_badges),
                render_numbered_preview_section_lines("recent tools", self.recent_tool_previews),
            )

        workspace_lines = render_selected_preview_section_lines(
            focused_lane_preview_lines if filter_mode == "workspace-edit" else [],
            focused_lane_queue_provenance_lines if filter_mode == "workspace-edit" else [],
            focused_lane_queue_preview_lines if filter_mode == "workspace-edit" else [],
            focused_lane_age_lines if filter_mode == "workspace-edit" else [],
            focused_lane_timestamp_lines if filter_mode == "workspace-edit" else [],
            focused_lane_age_source_lines if filter_mode == "workspace-edit" else [],
            render_preview_badges_line("workspace lanes", self.workspace_lane_badges),
            render_preview_detail_line("last workspace tool", focused_workspace_preview),
            render_numbered_preview_section_lines("recent workspace tools", focused_workspace_previews),
        )

        shell_lines = render_selected_preview_section_lines(
            focused_lane_preview_lines if filter_mode == "shell-test" else [],
            focused_lane_queue_provenance_lines if filter_mode == "shell-test" else [],
            focused_lane_queue_preview_lines if filter_mode == "shell-test" else [],
            focused_lane_age_lines if filter_mode == "shell-test" else [],
            focused_lane_timestamp_lines if filter_mode == "shell-test" else [],
            focused_lane_age_source_lines if filter_mode == "shell-test" else [],
            render_preview_badges_line("shell", self.shell_activity_badges),
            render_preview_badges_line("shell lanes", self.shell_lane_badges),
            render_preview_badges_line("failures", self.failure_activity_badges),
            render_preview_detail_line("last shell", focused_shell_preview),
            render_numbered_preview_section_lines("recent shell outcomes", focused_shell_previews),
        )

        event_lines = render_selected_preview_section_lines(
            render_preview_detail_line("last event", self.last_event_preview),
        )

        return render_selected_session_preview_lines(
            header_lines=header_lines,
            status_lines=status_lines,
            approval_lines=approval_lines,
            intervention_lines=intervention_lines,
            session_lines=session_lines,
            tool_lines=tool_lines,
            workspace_lines=workspace_lines,
            shell_lines=shell_lines,
            event_lines=event_lines,
        )


@dataclass(slots=True)
class LaneActivityRollup:
    lane_counts: dict[str, int]
    lane_oldest_ages: dict[str, int] = field(default_factory=dict)
    lane_oldest_timestamps: dict[str, str] = field(default_factory=dict)
    mixed_count: int = 0


@dataclass(slots=True)
class PendingApprovalFilterMetrics:
    total_approvals: int
    family_counts: dict[str, int]
    fresh_queue_sessions: int
    restored_queue_sessions: int
    multi_queue_sessions: int
    oldest_age_seconds: int
    oldest_at: str = ""


@dataclass(slots=True)
class DeniedApprovalFilterMetrics:
    total_denied: int
    family_counts: dict[str, int]
    fresh_denied_sessions: int
    restored_denied_sessions: int
    oldest_age_seconds: int
    oldest_at: str = ""


@dataclass(slots=True)
class ToolFilterMetrics:
    total_test_failures: int
    total_tool_failures: int
    failing_sessions: int


@dataclass(slots=True)
class PendingOnlyLaneMetrics:
    pending_only_sessions: int
    restored_pending_only_sessions: int
    oldest_age_seconds: int
    oldest_at: str = ""
    oldest_uses_activity_fallback: bool = False
    restored_oldest_age_seconds: int = 0
    restored_oldest_at: str = ""
    restored_oldest_uses_activity_fallback: bool = False


@dataclass(slots=True)
class InterventionActivitySummary:
    family_counts: dict[str, int]
    target_kind_counts: dict[str, int]
    follow_up_counts: dict[str, int]
    unique_count: int


@dataclass(slots=True)
class InterventionFilterMetrics:
    total_requests: int
    family_counts: dict[str, int]
    target_kind_counts: dict[str, int]
    follow_up_counts: dict[str, int]


@dataclass(slots=True)
class ApprovalActivitySummary:
    pending_approval_badges: list[str]
    approval_status_badges: list[str]
    approval_focus_badges: list[str]
    last_approval_summary: str
    pending_approval_age_summary: str
    pending_approval_oldest_at: str
    denied_approval_count: int
    denied_approval_badges: list[str]
    last_denied_approval_summary: str
    last_denied_approval_age_summary: str
    last_denied_approval_at: str
    last_denied_approval_age_sort_key: int
    restored_approval_count: int
    restored_approval_badges: list[str]
    restored_approval_tool_badges: list[str]
    restored_pending_approval_age_summary: str
    restored_pending_approval_oldest_at: str
    restored_pending_approval_age_sort_key: int
    last_restored_approval_summary: str
    last_restored_approval_age_summary: str
    last_restored_approval_at: str
    last_restored_approval_age_sort_key: int
    last_restored_outcome_summary: str
    last_restored_outcome_age_summary: str
    last_restored_outcome_at: str
    last_restored_outcome_age_sort_key: int
    stale_approval_badges: list[str]
    pending_approval_attention_sort_key: tuple[int, ...]
    approval_attention_sort_key: tuple[int, ...]
    denied_approval_attention_sort_key: tuple[int, ...]


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
        approval_activity = _approval_activity(
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
        activity_timestamp_display = _format_timestamp(activity_timestamp)
        session_activity_age_sort_key = max(int(datetime.now(UTC).timestamp() - activity_timestamp), 0)
        pending_approval_age_seconds = _pending_approval_age_seconds(pending_approvals)
        stale_session_summary, stale_session_badges, stale_session_sort_key = _stale_session_status(activity_timestamp)
        recent_failure_count = _recent_tool_failure_count(turns)
        recent_shell_failure_count = _recent_shell_failure_count(turns)
        recent_test_failure_count, recent_tool_failure_count = _recent_failure_activity_counts(turns)
        tool_lane_age_sort_keys, tool_lane_timestamps = _tool_lane_activity_maps(
            turns,
            pending_approvals,
        )
        workspace_lane_age_sort_keys, workspace_lane_timestamps = _workspace_lane_activity_maps(
            turns,
            pending_approvals,
        )
        shell_lane_age_sort_keys, shell_lane_timestamps = _shell_lane_activity_maps(turns, pending_approvals)
        has_workspace_inspect_activity, has_workspace_edit_activity = _workspace_activity_presence(
            turns,
            pending_approvals,
        )
        has_shell_inspect_activity, has_shell_test_activity = _shell_activity_presence(turns, pending_approvals)
        intervention_activity = _summarize_intervention_activity(turns, pending_approvals)
        pending_workspace_edit_approvals = _pending_approvals_for_filter_mode(pending_approvals, "workspace-edit")
        fresh_pending_workspace_edit_approvals = _pending_approvals_for_filter_mode(
            pending_approvals,
            "workspace-edit",
            restored_only=False,
        )
        restored_pending_workspace_edit_approvals = _pending_approvals_for_filter_mode(
            pending_approvals,
            "workspace-edit",
            restored_only=True,
        )
        pending_shell_test_approvals = _pending_approvals_for_filter_mode(pending_approvals, "shell-test")
        fresh_pending_shell_test_approvals = _pending_approvals_for_filter_mode(
            pending_approvals,
            "shell-test",
            restored_only=False,
        )
        restored_pending_shell_test_approvals = _pending_approvals_for_filter_mode(
            pending_approvals,
            "shell-test",
            restored_only=True,
        )

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
            pending_approval_age_summary=approval_activity.pending_approval_age_summary,
            pending_approval_oldest_at=approval_activity.pending_approval_oldest_at,
            pending_approval_badges=approval_activity.pending_approval_badges,
            approval_status_badges=approval_activity.approval_status_badges,
            approval_focus_badges=approval_activity.approval_focus_badges,
            last_approval_summary=approval_activity.last_approval_summary,
            denied_approval_count=approval_activity.denied_approval_count,
            denied_approval_badges=approval_activity.denied_approval_badges,
            last_denied_approval_summary=approval_activity.last_denied_approval_summary,
            last_denied_approval_age_summary=approval_activity.last_denied_approval_age_summary,
            last_denied_approval_at=approval_activity.last_denied_approval_at,
            last_denied_approval_age_sort_key=approval_activity.last_denied_approval_age_sort_key,
            restored_approval_count=approval_activity.restored_approval_count,
            restored_approval_badges=approval_activity.restored_approval_badges,
            restored_approval_tool_badges=approval_activity.restored_approval_tool_badges,
            restored_pending_approval_queue_summary=_restored_pending_approval_queue_summary(pending_approvals),
            restored_pending_approval_age_summary=approval_activity.restored_pending_approval_age_summary,
            restored_pending_approval_oldest_at=approval_activity.restored_pending_approval_oldest_at,
            restored_pending_approval_age_sort_key=approval_activity.restored_pending_approval_age_sort_key,
            last_restored_approval_summary=approval_activity.last_restored_approval_summary,
            last_restored_approval_age_summary=approval_activity.last_restored_approval_age_summary,
            last_restored_approval_at=approval_activity.last_restored_approval_at,
            last_restored_approval_age_sort_key=approval_activity.last_restored_approval_age_sort_key,
            last_restored_outcome_summary=approval_activity.last_restored_outcome_summary,
            last_restored_outcome_age_summary=approval_activity.last_restored_outcome_age_summary,
            last_restored_outcome_at=approval_activity.last_restored_outcome_at,
            last_restored_outcome_age_sort_key=approval_activity.last_restored_outcome_age_sort_key,
            stale_approval_badges=approval_activity.stale_approval_badges,
            intervention_badges=_intervention_activity_badges(turns, pending_approvals),
            intervention_family_counts=intervention_activity.family_counts,
            intervention_target_kind_counts=intervention_activity.target_kind_counts,
            intervention_follow_up_counts=intervention_activity.follow_up_counts,
            intervention_unique_count=intervention_activity.unique_count,
            last_intervention_preview=_latest_intervention_preview(turns, pending_approvals),
            recent_intervention_previews=_recent_intervention_previews(turns, pending_approvals),
            has_intervention_activity=_has_intervention_activity(turns, pending_approvals),
            pending_approval_attention_sort_key=approval_activity.pending_approval_attention_sort_key,
            approval_attention_sort_key=approval_activity.approval_attention_sort_key,
            denied_approval_attention_sort_key=approval_activity.denied_approval_attention_sort_key,
            last_event_preview=_latest_event_preview(turns),
            last_tool_preview=_latest_tool_preview(turns),
            last_tool_badges=_latest_tool_badges(turns),
            recent_tool_previews=_recent_tool_previews(turns),
            tool_lane_age_sort_keys=tool_lane_age_sort_keys,
            tool_lane_timestamps=tool_lane_timestamps,
            workspace_lane_badges=_workspace_lane_badges(
                has_workspace_inspect_activity,
                has_workspace_edit_activity,
            ),
            has_workspace_inspect_activity=has_workspace_inspect_activity,
            has_workspace_edit_activity=has_workspace_edit_activity,
            has_pending_workspace_edit_approval=bool(pending_workspace_edit_approvals),
            has_fresh_pending_workspace_edit_approval=bool(fresh_pending_workspace_edit_approvals),
            has_restored_pending_workspace_edit_approval=bool(restored_pending_workspace_edit_approvals),
            pending_workspace_edit_queue_previews=_pending_lane_queue_preview_items(
                pending_workspace_edit_approvals,
                fallback_age_seconds=session_activity_age_sort_key,
                fallback_timestamp=activity_timestamp_display,
            ),
            pending_workspace_edit_age_sort_key=_pending_approval_age_seconds(pending_workspace_edit_approvals) or 0,
            pending_workspace_edit_oldest_at=_oldest_approval_timestamp_display(pending_workspace_edit_approvals),
            restored_pending_workspace_edit_age_sort_key=(
                _pending_approval_age_seconds(restored_pending_workspace_edit_approvals) or 0
            ),
            restored_pending_workspace_edit_oldest_at=_oldest_approval_timestamp_display(
                restored_pending_workspace_edit_approvals
            ),
            last_workspace_preview=_latest_workspace_preview(turns),
            recent_workspace_previews=_recent_workspace_previews(turns),
            last_workspace_inspect_preview=_latest_workspace_preview(turns, lane="inspect"),
            recent_workspace_inspect_previews=_recent_workspace_previews(turns, lane="inspect"),
            last_workspace_edit_preview=_latest_workspace_preview(turns, lane="edit"),
            recent_workspace_edit_previews=_recent_workspace_previews(turns, lane="edit"),
            workspace_lane_age_sort_keys=workspace_lane_age_sort_keys,
            workspace_lane_timestamps=workspace_lane_timestamps,
            shell_activity_badges=_shell_activity_badges(turns),
            shell_lane_badges=_shell_lane_badges(has_shell_inspect_activity, has_shell_test_activity),
            has_shell_inspect_activity=has_shell_inspect_activity,
            has_shell_test_activity=has_shell_test_activity,
            has_pending_shell_test_approval=bool(pending_shell_test_approvals),
            has_fresh_pending_shell_test_approval=bool(fresh_pending_shell_test_approvals),
            has_restored_pending_shell_test_approval=bool(restored_pending_shell_test_approvals),
            pending_shell_test_queue_previews=_pending_lane_queue_preview_items(
                pending_shell_test_approvals,
                fallback_age_seconds=session_activity_age_sort_key,
                fallback_timestamp=activity_timestamp_display,
            ),
            pending_shell_test_age_sort_key=_pending_approval_age_seconds(pending_shell_test_approvals) or 0,
            pending_shell_test_oldest_at=_oldest_approval_timestamp_display(pending_shell_test_approvals),
            restored_pending_shell_test_age_sort_key=(
                _pending_approval_age_seconds(restored_pending_shell_test_approvals) or 0
            ),
            restored_pending_shell_test_oldest_at=_oldest_approval_timestamp_display(
                restored_pending_shell_test_approvals
            ),
            last_shell_preview=_latest_shell_preview(turns),
            recent_shell_previews=_recent_shell_previews(turns),
            last_shell_inspect_preview=_latest_shell_preview(turns, lane="inspect"),
            recent_shell_inspect_previews=_recent_shell_previews(turns, lane="inspect"),
            last_shell_test_preview=_latest_shell_preview(turns, lane="test"),
            recent_shell_test_previews=_recent_shell_previews(turns, lane="test"),
            shell_lane_age_sort_keys=shell_lane_age_sort_keys,
            shell_lane_timestamps=shell_lane_timestamps,
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
            session_activity_age_sort_key=session_activity_age_sort_key,
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

    stale_cutoff = format_stale_approval_cutoff(stale_approval_warning_seconds)

    lines = [
        f"Recent sessions under {resolved_root}:",
        render_recent_session_page_banner(
            filter_mode=filter_mode,
            sort_mode=sort_mode,
            total_matches=total_matches,
            page_size=limit,
            page_index=page_index,
            visible_count=len(summaries),
            stale_cutoff_suffix=stale_cutoff_suffix,
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
                stale_cutoff=stale_cutoff,
            )
        )
    else:
        selected_index = _normalize_visible_selected_index(len(summaries), selected_index)
        for index, summary in enumerate(summaries, start=1):
            marker = ">" if index - 1 == selected_index else " "
            lines.append(
                render_recent_session_list_row(
                    marker=marker,
                    summary_line=summary.render_line(
                        index,
                        include_attention_reason=sort_mode == 'attention',
                        filter_mode=filter_mode,
                    ),
                )
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
            render_picker_controls_line(stale_cutoff=stale_cutoff),
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
        stale_cutoff = format_stale_approval_cutoff(stale_approval_warning_seconds)
        prompt = (
            render_picker_selection_prompt(stale_cutoff=stale_cutoff)
            if current_summaries
            else render_picker_empty_filter_prompt(stale_cutoff=stale_cutoff)
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
                output_fn(render_picker_invalid_selection_message(selection, len(current_summaries)))
            else:
                output_fn(
                    render_picker_empty_filter_visible_guidance(
                        stale_cutoff=format_stale_approval_cutoff(stale_approval_warning_seconds)
                    )
                )
            continue
        if current_summaries:
            output_fn(render_picker_invalid_key_guidance(len(current_summaries)))
        else:
            output_fn(
                render_picker_empty_filter_adjust_guidance(
                    stale_cutoff=format_stale_approval_cutoff(stale_approval_warning_seconds)
                )
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


def _tool_lane_for_event(event) -> str:
    tool_name = str(event.data.get("tool_name", "") or event.title or "").strip()
    if not tool_name:
        return ""
    if _is_shell_tool_event(event):
        return "shell"
    if tool_name in WORKSPACE_INSPECT_TOOL_NAMES or tool_name in WORKSPACE_EDIT_TOOL_NAMES:
        return "workspace"
    return "other"


def _lane_activity_maps(candidates: Sequence[tuple[str, str | None]]) -> tuple[dict[str, int], dict[str, str]]:
    latest_by_lane: dict[str, datetime] = {}
    for lane, raw_timestamp in candidates:
        if not lane:
            continue
        parsed = _parse_iso_timestamp(raw_timestamp)
        if parsed is None:
            continue
        previous = latest_by_lane.get(lane)
        if previous is None or parsed > previous:
            latest_by_lane[lane] = parsed

    now = datetime.now(UTC)
    lane_ages: dict[str, int] = {}
    lane_timestamps: dict[str, str] = {}
    for lane, parsed in latest_by_lane.items():
        lane_ages[lane] = max(int((now - parsed).total_seconds()), 0)
        lane_timestamps[lane] = _format_timestamp(parsed.timestamp())
    return lane_ages, lane_timestamps


def _tool_lane_activity_maps(
    turns: list[TurnArtifact],
    pending_approvals: list[ApprovalRequest],
) -> tuple[dict[str, int], dict[str, str]]:
    candidates = [(_tool_lane_for_event(event), str(event.timestamp or "").strip()) for event in _iter_recent_tool_events(turns)]
    candidates.extend(
        ("workspace", approval.created_at)
        for approval in pending_approvals
        if str(approval.tool_name or "").strip() in WORKSPACE_EDIT_TOOL_NAMES
    )
    candidates.extend(
        ("shell", approval.created_at)
        for approval in pending_approvals
        if str(approval.tool_name or "").strip() == "run_shell_command"
        and _is_test_shell_command_data(
            shell_policy="",
            shell_command_family="",
            command=_approval_command_from_args(approval.args),
        )
    )
    return _lane_activity_maps(candidates)


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


def _recent_workspace_previews(
    turns: list[TurnArtifact],
    limit: int = MAX_TOOL_STREAK_PREVIEWS,
    *,
    lane: str | None = None,
) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_workspace_tool_events(turns, lane=lane):
        rendered = _render_tool_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    return previews


def _iter_recent_workspace_edit_activity_events(turns: list[TurnArtifact]):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            tool_name = str(event.data.get("tool_name", "") or event.title or "").strip()
            if tool_name not in WORKSPACE_EDIT_TOOL_NAMES:
                continue
            if not (str(event.data.get("approval_status", "") or "").strip() or _is_intervention_event(event)):
                continue
            yield event


def _workspace_lane_activity_maps(
    turns: list[TurnArtifact],
    pending_approvals: list[ApprovalRequest],
) -> tuple[dict[str, int], dict[str, str]]:
    candidates: list[tuple[str, str | None]] = [
        (
            _workspace_tool_lane(str(event.data.get("tool_name", "") or event.title or "")),
            str(event.timestamp or "").strip(),
        )
        for event in _iter_recent_workspace_tool_events(turns)
    ]
    candidates.extend(("edit", str(event.timestamp or "").strip()) for event in _iter_recent_workspace_edit_activity_events(turns))
    candidates.extend(
        ("edit", approval.created_at)
        for approval in pending_approvals
        if str(approval.tool_name or "").strip() in WORKSPACE_EDIT_TOOL_NAMES
    )
    return _lane_activity_maps(candidates)


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
    for approval in pending_approvals:
        if len(previews) >= limit:
            break
        preview = _queued_intervention_preview([approval])
        if preview and preview not in previews:
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


def _intervention_activity_key_for_event(event) -> str:
    approval_id = str(event.data.get("approval_id", "") or "").strip()
    if approval_id:
        return f"approval:{approval_id}"
    tool_name = str(event.data.get("tool_name", "") or event.title or "").strip()
    command = str(event.data.get("command", "") or "").strip()
    timestamp = str(event.timestamp or "").strip()
    detail = str(event.detail or "").strip()
    return f"event:{event.kind}:{tool_name}:{command}:{timestamp}:{detail}"


def _intervention_event_family(event) -> str:
    family = str(event.data.get("approval_tool_family", "") or "").strip()
    if family:
        return family
    return _approval_tool_family_for_values(
        tool_name=str(event.data.get("tool_name", "") or event.title or "").strip(),
        command=str(event.data.get("command", "") or "").strip(),
        shell_command_family=str(event.data.get("shell_command_family", "") or "").strip(),
    )



def _summarize_intervention_activity(
    turns: list[TurnArtifact],
    pending_approvals: list[ApprovalRequest],
    count_window: int = MAX_INTERVENTION_ROLLUP_EVENTS,
) -> InterventionActivitySummary:
    family_counts: dict[str, int] = {}
    target_kind_counts: dict[str, int] = {}
    follow_up_counts: dict[str, int] = {}
    counted_keys: set[str] = set()
    unique_count = 0

    for event in _bounded_recent_intervention_events(turns, limit=count_window):
        key = _intervention_activity_key_for_event(event)
        if key in counted_keys:
            continue
        counted_keys.add(key)
        family = _intervention_event_family(event)
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
        target_kind = _intervention_event_target_kind(event)
        if target_kind:
            target_kind_counts[target_kind] = target_kind_counts.get(target_kind, 0) + 1
        follow_up_label = _intervention_follow_up_label(str(event.data.get("follow_up_mode", "") or "").strip())
        if follow_up_label:
            follow_up_counts[follow_up_label] = follow_up_counts.get(follow_up_label, 0) + 1
        unique_count += 1

    for approval in pending_approvals:
        key = f"approval:{approval.request_id}"
        if key in counted_keys:
            continue
        counted_keys.add(key)
        family = _approval_tool_family_for_values(
            tool_name=str(approval.tool_name or "").strip(),
            command=_approval_command_from_args(approval.args),
            shell_command_family="",
        )
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
        target_kind = _approval_target_kind(approval)
        if target_kind:
            target_kind_counts[target_kind] = target_kind_counts.get(target_kind, 0) + 1
        unique_count += 1

    return InterventionActivitySummary(
        family_counts=family_counts,
        target_kind_counts=target_kind_counts,
        follow_up_counts=follow_up_counts,
        unique_count=unique_count,
    )


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
    preview = summarize_event(event) or event.title or event.kind
    return _truncate(preview, MAX_INTERVENTION_PREVIEW)


def _queued_intervention_preview(pending_approvals: list[ApprovalRequest]) -> str:
    if not pending_approvals:
        return ""
    approval = pending_approvals[0]
    family = _approval_tool_family_for_values(
        tool_name=str(approval.tool_name or ""),
        command=_approval_command_from_args(approval.args),
        shell_command_family="",
    )
    bits = ["approval pending"]
    if family:
        bits[0] += f" {family}"
    if approval.source:
        bits[0] += f" via {approval.source}"
    bits.append(f"queue 1/{len(pending_approvals)}")
    target_preview = _approval_target_preview(approval)
    if target_preview:
        bits.append(target_preview)
    if len(pending_approvals) > 1:
        bits.append(f"next {pending_approvals[1].tool_name}")
    age_summary = _approval_preview_age_and_timestamp(approval)[0]
    if age_summary:
        bits.append(f"age {age_summary}")
    if approval.restored_from_session:
        bits.append("restored")
    return _truncate(" | ".join(bit for bit in bits if bit), MAX_INTERVENTION_PREVIEW)


def _iter_recent_shell_tool_events(turns: list[TurnArtifact], *, lane: str | None = None):
    for event in _iter_recent_tool_events(turns, tool_name="run_shell_command"):
        event_lane = "test" if _is_test_shell_event(event) else "inspect"
        if lane is not None and event_lane != lane:
            continue
        yield event


def _latest_shell_preview(turns: list[TurnArtifact], *, lane: str | None = None) -> str:
    event = next(_iter_recent_shell_tool_events(turns, lane=lane), None)
    if event is None:
        return ""
    return _render_tool_event_summary(event)


def _recent_shell_previews(
    turns: list[TurnArtifact],
    limit: int = MAX_SHELL_STREAK_PREVIEWS,
    *,
    lane: str | None = None,
) -> list[str]:
    previews: list[str] = []
    for event in _iter_recent_shell_tool_events(turns, lane=lane):
        rendered = _render_tool_event_summary(event)
        if rendered:
            previews.append(rendered)
        if len(previews) >= limit:
            break
    return previews


def _iter_recent_shell_test_activity_events(turns: list[TurnArtifact]):
    for turn in reversed(turns):
        for event in reversed(turn.events):
            if not _is_shell_tool_event(event):
                continue
            if not (str(event.data.get("approval_status", "") or "").strip() or _is_intervention_event(event)):
                continue
            if _is_test_shell_event(event):
                yield event


def _shell_lane_activity_maps(
    turns: list[TurnArtifact],
    pending_approvals: list[ApprovalRequest],
) -> tuple[dict[str, int], dict[str, str]]:
    candidates: list[tuple[str, str | None]] = [
        (
            "test" if _is_test_shell_event(event) else "inspect",
            str(event.timestamp or "").strip(),
        )
        for event in _iter_recent_tool_events(turns, tool_name="run_shell_command")
    ]
    candidates.extend(("test", str(event.timestamp or "").strip()) for event in _iter_recent_shell_test_activity_events(turns))
    candidates.extend(
        ("test", approval.created_at)
        for approval in pending_approvals
        if str(approval.tool_name or "").strip() == "run_shell_command"
        and _is_test_shell_command_data(
            shell_policy="",
            shell_command_family="",
            command=_approval_command_from_args(approval.args),
        )
    )
    return _lane_activity_maps(candidates)


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
    return _is_test_shell_command_data(
        shell_policy=str(event.data.get("shell_policy", "") or "").strip(),
        shell_command_family=str(event.data.get("shell_command_family", "") or "").strip(),
        command=str(event.data.get("command", "") or "").strip(),
    )


def _is_test_shell_command_data(
    *,
    shell_policy: str,
    shell_command_family: str,
    command: str,
) -> bool:
    if shell_policy:
        return shell_policy != "inspect"
    if shell_command_family:
        return shell_command_family.startswith("pytest")
    if command:
        try:
            return resolve_shell_command(command).family.startswith("pytest")
        except ValueError:
            return False
    return False


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
) -> ApprovalActivitySummary:
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

    return ApprovalActivitySummary(
        pending_approval_badges=pending_badges,
        approval_status_badges=badges,
        approval_focus_badges=_render_approval_focus_badges(last_record),
        last_approval_summary=_render_last_approval_summary(last_record),
        pending_approval_age_summary=pending_approval_age_summary,
        pending_approval_oldest_at=_oldest_approval_timestamp_display(pending_approvals),
        denied_approval_count=status_counts.get("denied", 0),
        denied_approval_badges=denied_badges,
        last_denied_approval_summary=_render_last_approval_summary(last_denied_record),
        last_denied_approval_age_summary=last_denied_approval_age_summary,
        last_denied_approval_at=_approval_record_timestamp_display(last_denied_record),
        last_denied_approval_age_sort_key=last_denied_approval_age_sort_key,
        restored_approval_count=sum(restored_status_counts.values()),
        restored_approval_badges=restored_badges,
        restored_approval_tool_badges=restored_tool_badges,
        restored_pending_approval_age_summary=restored_pending_approval_age_summary,
        restored_pending_approval_oldest_at=_oldest_approval_timestamp_display(
            [approval for approval in pending_approvals if approval.restored_from_session]
        ),
        restored_pending_approval_age_sort_key=restored_pending_approval_age_seconds,
        last_restored_approval_summary=_render_last_approval_summary(last_restored_record),
        last_restored_approval_age_summary=last_restored_approval_age_summary,
        last_restored_approval_at=_approval_record_timestamp_display(last_restored_record),
        last_restored_approval_age_sort_key=last_restored_approval_age_sort_key,
        last_restored_outcome_summary=_render_last_approval_summary(last_restored_outcome_record),
        last_restored_outcome_age_summary=last_restored_outcome_age_summary,
        last_restored_outcome_at=_approval_record_timestamp_display(last_restored_outcome_record),
        last_restored_outcome_age_sort_key=last_restored_outcome_age_sort_key,
        stale_approval_badges=stale_approval_badges,
        pending_approval_attention_sort_key=pending_approval_attention_sort_key,
        approval_attention_sort_key=approval_attention_sort_key,
        denied_approval_attention_sort_key=denied_approval_attention_sort_key,
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


def _pending_approvals_for_filter_mode(
    pending_approvals: Sequence[ApprovalRequest],
    filter_mode: str,
    *,
    restored_only: bool | None = None,
) -> list[ApprovalRequest]:
    approvals = [
        approval
        for approval in pending_approvals
        if restored_only is None or approval.restored_from_session is restored_only
    ]
    if filter_mode == "workspace-edit":
        return [approval for approval in approvals if str(approval.tool_name or "").strip() in WORKSPACE_EDIT_TOOL_NAMES]
    if filter_mode == "shell-test":
        return [
            approval
            for approval in approvals
            if str(approval.tool_name or "").strip() == "run_shell_command"
            and _is_test_shell_command_data(
                shell_policy="",
                shell_command_family="",
                command=_approval_command_from_args(approval.args),
            )
        ]
    return []


def _pending_lane_queue_preview_items(
    approvals: Sequence[ApprovalRequest],
    *,
    fallback_age_seconds: int = 0,
    fallback_timestamp: str = "",
) -> list[str]:
    if len(approvals) <= 1:
        return []
    return [
        _format_pending_lane_queue_preview_item(
            approval,
            fallback_age_seconds=fallback_age_seconds,
            fallback_timestamp=fallback_timestamp,
        )
        for approval in approvals
    ]


def _format_pending_lane_queue_preview_item(
    approval: ApprovalRequest,
    *,
    fallback_age_seconds: int = 0,
    fallback_timestamp: str = "",
) -> str:
    origin = "restored" if approval.restored_from_session else "fresh"
    tool_name = str(approval.tool_name or "tool").strip() or "tool"
    bits = [f"{origin} {tool_name}"]

    target_preview = _approval_target_preview(approval)
    if target_preview:
        bits.append(target_preview)

    age_summary, timestamp, age_source = _approval_preview_age_and_timestamp(
        approval,
        fallback_age_seconds=fallback_age_seconds,
        fallback_timestamp=fallback_timestamp,
    )
    if age_summary:
        bits.append(f"age {age_summary}")
    if timestamp:
        bits.append(f"at {timestamp}")
    if age_source:
        bits.append(age_source)
    return " | ".join(bits)


def _approval_target_preview(approval: ApprovalRequest) -> str:
    command = _approval_command_from_args(approval.args)
    if command:
        return f"cmd {command}"

    if isinstance(approval.args, dict):
        relative_path = str(approval.args.get("relative_path", "") or "").strip()
        if relative_path:
            return f"path {relative_path}"

        expected_occurrences = approval.args.get("expected_occurrences")
        if isinstance(expected_occurrences, int) and expected_occurrences > 1:
            return f"occurrences {expected_occurrences}"

    return ""


def _approval_target_kind(approval: ApprovalRequest) -> str:
    command = _approval_command_from_args(approval.args)
    if command:
        return "command"

    if isinstance(approval.args, dict):
        relative_path = str(approval.args.get("relative_path", "") or "").strip()
        if relative_path:
            return "path"

    return ""


def _intervention_event_target_kind(event) -> str:
    target_kind = str(event.data.get("approval_target_kind", "") or "").strip()
    if target_kind:
        return target_kind
    if str(event.data.get("command", "") or "").strip():
        return "command"
    if str(event.data.get("relative_path", "") or "").strip():
        return "path"
    return ""


def _intervention_follow_up_label(mode: str) -> str:
    if mode == "approved_tool_result":
        return "approved result"
    if mode == "denied_tool_request":
        return "denied request"
    return mode


def _approval_preview_age_and_timestamp(
    approval: ApprovalRequest,
    *,
    fallback_age_seconds: int = 0,
    fallback_timestamp: str = "",
) -> tuple[str, str, str]:
    age_seconds = approval.age_seconds()
    timestamp = _format_iso_timestamp(approval.created_at)
    if age_seconds is not None:
        return (
            _format_age_compact(age_seconds) if age_seconds > 0 else "",
            timestamp,
            "approval created_at",
        )

    if fallback_age_seconds > 0 or fallback_timestamp:
        return (
            _format_age_compact(fallback_age_seconds) if fallback_age_seconds > 0 else "",
            fallback_timestamp,
            "activity fallback",
        )

    return "", "", ""


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
    if filter_mode == "pending" and summaries:
        return _render_pending_approval_filter_summary_lines(
            summaries,
            page_index=page_index,
            page_size=page_size,
        )

    if filter_mode == "denied" and summaries:
        return _render_denied_approval_filter_summary_lines(
            summaries,
            page_index=page_index,
            page_size=page_size,
        )

    if filter_mode == "approval-restore" and summaries:
        return _render_lane_filter_summary_lines(
            summaries,
            backlog_label="Approval restore backlog",
            focus_label="Restore lane focus",
            focus_lanes=APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
            page_lane_label="restore lanes",
            page_index=page_index,
            page_size=page_size,
            rollup_formatter=_format_approval_restore_lane_rollup,
            lane_getter=_approval_restore_lanes,
            age_getter=_approval_restore_lane_age_seconds,
            timestamp_getter=_approval_restore_lane_timestamps,
            display_order=APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
            include_overlap_summary=True,
        )

    if filter_mode == "tool" and summaries:
        lines = _render_lane_filter_summary_lines(
            summaries,
            backlog_label="Tool backlog",
            focus_label="Tool focus",
            focus_lanes=TOOL_LANE_DISPLAY_ORDER,
            page_lane_label="tool lanes",
            page_index=page_index,
            page_size=page_size,
            rollup_formatter=_format_recent_lane_rollup_for_display_order(TOOL_LANE_DISPLAY_ORDER),
            lane_getter=_tool_lanes,
            age_getter=_tool_lane_age_seconds,
            timestamp_getter=_tool_lane_timestamps,
            display_order=TOOL_LANE_DISPLAY_ORDER,
            include_overlap_summary=True,
        )
        return _append_metric_detail_lines(
            lines,
            summaries,
            detail_label="Tool failure mix",
            page_metric_label="tool failure mix",
            page_index=page_index,
            page_size=page_size,
            summarize_metrics=_summarize_tool_filter_metrics,
            format_metrics=_format_tool_filter_metrics,
        )

    if filter_mode == "intervention" and summaries:
        lines = _render_lane_filter_summary_lines(
            summaries,
            backlog_label="Intervention backlog",
            focus_label="Intervention focus",
            focus_lanes=INTERVENTION_LANE_DISPLAY_ORDER,
            page_lane_label="intervention lanes",
            page_index=page_index,
            page_size=page_size,
            rollup_formatter=_format_intervention_lane_rollup,
            lane_getter=_intervention_lanes,
            age_getter=_intervention_lane_age_seconds,
            timestamp_getter=_intervention_lane_timestamps,
            display_order=INTERVENTION_LANE_DISPLAY_ORDER,
            include_overlap_summary=True,
        )
        return _append_metric_detail_lines(
            lines,
            summaries,
            detail_label="Intervention mix",
            page_metric_label="intervention mix",
            page_index=page_index,
            page_size=page_size,
            summarize_metrics=_summarize_intervention_filter_metrics,
            format_metrics=_format_intervention_filter_metrics,
        )

    if filter_mode in {"workspace-inspect", "workspace-edit"} and summaries:
        focus_lanes = ["edit"] if filter_mode == "workspace-edit" else ["inspect"]
        lines = _render_lane_filter_summary_lines(
            summaries,
            backlog_label="Workspace backlog",
            focus_label="Workspace focus",
            focus_lanes=focus_lanes,
            page_lane_label="workspace lanes",
            page_index=page_index,
            page_size=page_size,
            rollup_formatter=_format_recent_lane_rollup_for_display_order(WORKSPACE_LANE_DISPLAY_ORDER),
            lane_getter=_workspace_lanes,
            age_getter=_workspace_lane_age_seconds,
            timestamp_getter=_workspace_lane_timestamps,
            display_order=WORKSPACE_LANE_DISPLAY_ORDER,
            include_overlap_summary=True,
        )
        if filter_mode == "workspace-edit":
            return _append_metric_detail_lines(
                lines,
                summaries,
                detail_label="Workspace edit queue mix",
                page_metric_label="workspace edit queue mix",
                page_index=page_index,
                page_size=page_size,
                summarize_metrics=_summarize_workspace_edit_pending_only_metrics,
                format_metrics=_format_pending_only_lane_metrics,
            )
        return lines

    if filter_mode in {"shell", "shell-inspect", "shell-test"} and summaries:
        shell_focus_lanes = (
            ["inspect"]
            if filter_mode == "shell-inspect"
            else ["test"] if filter_mode == "shell-test" else list(SHELL_LANE_DISPLAY_ORDER)
        )
        lines = _render_lane_filter_summary_lines(
            summaries,
            backlog_label="Shell backlog",
            focus_label="Shell focus",
            focus_lanes=shell_focus_lanes,
            page_lane_label="shell lanes",
            page_index=page_index,
            page_size=page_size,
            rollup_formatter=_format_recent_lane_rollup_for_display_order(SHELL_LANE_DISPLAY_ORDER),
            lane_getter=_shell_lanes,
            age_getter=_shell_lane_age_seconds,
            timestamp_getter=_shell_lane_timestamps,
            display_order=SHELL_LANE_DISPLAY_ORDER,
            include_overlap_summary=True,
        )
        if filter_mode == "shell-test":
            return _append_metric_detail_lines(
                lines,
                summaries,
                detail_label="Shell test queue mix",
                page_metric_label="shell test queue mix",
                page_index=page_index,
                page_size=page_size,
                summarize_metrics=_summarize_shell_test_pending_only_metrics,
                format_metrics=_format_pending_only_lane_metrics,
            )
        return lines

    stale_filter_lanes = _stale_approval_filter_lanes(filter_mode)
    if stale_filter_lanes is None or not summaries:
        return []

    stale_focus_lanes = [lane for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER if lane in stale_filter_lanes]
    return _render_lane_filter_summary_lines(
        summaries,
        backlog_label=_stale_approval_summary_label(filter_mode),
        focus_label="Stale lane focus",
        focus_lanes=stale_focus_lanes,
        cutoff=format_stale_approval_cutoff(stale_approval_warning_seconds),
        page_lane_label="stale lanes",
        page_index=page_index,
        page_size=page_size,
        rollup_formatter=_format_stale_approval_lane_rollup,
        lane_getter=_stale_approval_lanes,
        age_getter=_stale_approval_lane_age_seconds,
        timestamp_getter=_stale_approval_lane_timestamps,
        display_order=STALE_APPROVAL_LANE_DISPLAY_ORDER,
        allowed_lanes=stale_filter_lanes,
    )


def render_recent_session_empty_state_lines(
    *,
    available_count: int,
    filter_mode: str,
    surface: str = "picker",
    stale_cutoff: str = "",
) -> list[str]:
    return render_recent_session_empty_state_lines_helper(
        available_count=available_count,
        filter_mode=filter_mode,
        surface=surface,
        stale_cutoff=stale_cutoff,
    )


def _render_lane_filter_summary_lines(
    summaries: list[SessionSummary],
    *,
    backlog_label: str,
    focus_label: str,
    focus_lanes: Sequence[str],
    page_lane_label: str,
    page_index: int,
    page_size: int,
    rollup_formatter: Callable[[dict[str, int], dict[str, int], dict[str, str]], str],
    lane_getter: Callable[[SessionSummary], set[str]],
    display_order: Sequence[str],
    age_getter: Callable[[SessionSummary], dict[str, int]] | None = None,
    timestamp_getter: Callable[[SessionSummary], dict[str, str]] | None = None,
    allowed_lanes: frozenset[str] | None = None,
    include_overlap_summary: bool = False,
    cutoff: str = "",
) -> list[str]:
    full_rollup = _summarize_lane_activity(
        summaries,
        display_order=display_order,
        lane_getter=lane_getter,
        age_getter=age_getter,
        timestamp_getter=timestamp_getter,
        allowed_lanes=allowed_lanes,
        include_mixed_count=include_overlap_summary,
    )
    lane_rollup = rollup_formatter(
        full_rollup.lane_counts,
        full_rollup.lane_oldest_ages,
        full_rollup.lane_oldest_timestamps,
    )
    overlap_summary = (
        _format_mixed_overlap_count(full_rollup.mixed_count)
        if include_overlap_summary and full_rollup.mixed_count > 0
        else ""
    )
    lines = render_recent_session_filter_summary_block_lines(
        backlog_label=backlog_label,
        count=len(summaries),
        focus_label=focus_label,
        focus_lanes=focus_lanes,
        lane_rollup=lane_rollup,
        overlap_summary=overlap_summary,
        cutoff=cutoff,
    )
    if len(summaries) <= page_size:
        return lines

    visible_summaries, off_page_summaries = _slice_visible_and_off_page_summaries(
        summaries,
        page_index=page_index,
        page_size=page_size,
    )
    visible_rollup_data = _summarize_lane_activity(
        visible_summaries,
        display_order=display_order,
        lane_getter=lane_getter,
        age_getter=age_getter,
        timestamp_getter=timestamp_getter,
        allowed_lanes=allowed_lanes,
        include_mixed_count=include_overlap_summary,
    )
    visible_rollup = rollup_formatter(
        visible_rollup_data.lane_counts,
        visible_rollup_data.lane_oldest_ages,
        visible_rollup_data.lane_oldest_timestamps,
    )
    if not visible_rollup:
        return lines

    off_page_rollup_data = _summarize_lane_activity(
        off_page_summaries,
        display_order=display_order,
        lane_getter=lane_getter,
        age_getter=age_getter,
        timestamp_getter=timestamp_getter,
        allowed_lanes=allowed_lanes,
        include_mixed_count=include_overlap_summary,
    )
    return render_recent_session_filter_summary_block_lines(
        backlog_label=backlog_label,
        count=len(summaries),
        focus_label=focus_label,
        focus_lanes=focus_lanes,
        lane_rollup=lane_rollup,
        overlap_summary=overlap_summary,
        cutoff=cutoff,
        page_lane_label=page_lane_label,
        visible_rollup=visible_rollup,
        off_page_rollup=rollup_formatter(
            off_page_rollup_data.lane_counts,
            off_page_rollup_data.lane_oldest_ages,
            off_page_rollup_data.lane_oldest_timestamps,
        ),
        visible_overlap_summary=(
            _format_mixed_overlap_count(visible_rollup_data.mixed_count)
            if include_overlap_summary and visible_rollup_data.mixed_count > 0
            else ""
        ),
        off_page_overlap_summary=(
            _format_mixed_overlap_count(off_page_rollup_data.mixed_count)
            if include_overlap_summary and off_page_rollup_data.mixed_count > 0
            else ""
        ),
    )


def _slice_visible_and_off_page_summaries(
    summaries: Sequence[SessionSummary],
    *,
    page_index: int,
    page_size: int,
) -> tuple[list[SessionSummary], list[SessionSummary]]:
    normalized_page_index = _normalize_picker_page_index(len(summaries), page_size, page_index)
    start = normalized_page_index * page_size
    end = start + page_size
    visible_summaries = list(summaries[start:end])
    off_page_summaries = [*summaries[:start], *summaries[end:]]
    return visible_summaries, off_page_summaries


def _summarize_lane_activity(
    summaries: Sequence[SessionSummary],
    *,
    display_order: Sequence[str],
    lane_getter: Callable[[SessionSummary], set[str]],
    age_getter: Callable[[SessionSummary], dict[str, int]] | None = None,
    timestamp_getter: Callable[[SessionSummary], dict[str, str]] | None = None,
    allowed_lanes: frozenset[str] | None = None,
    include_mixed_count: bool = False,
) -> LaneActivityRollup:
    lane_counts = {lane: 0 for lane in display_order}
    lane_oldest_ages = {lane: 0 for lane in display_order}
    lane_oldest_timestamps = {lane: "" for lane in display_order}
    mixed_count = 0

    for summary in summaries:
        lanes = {
            lane
            for lane in lane_getter(summary)
            if allowed_lanes is None or lane in allowed_lanes
        }
        if include_mixed_count and len(lanes) > 1:
            mixed_count += 1
        for lane in lanes:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
        if age_getter is None:
            continue
        lane_timestamps = timestamp_getter(summary) if timestamp_getter is not None else {}
        for lane, age_seconds in age_getter(summary).items():
            if allowed_lanes is not None and lane not in allowed_lanes:
                continue
            previous_age = lane_oldest_ages.get(lane, 0)
            previous_timestamp = lane_oldest_timestamps.get(lane, "")
            next_age, next_timestamp = _update_oldest_age_and_timestamp(
                previous_age,
                previous_timestamp,
                age_seconds,
                lane_timestamps.get(lane, ""),
            )
            lane_oldest_ages[lane] = next_age
            lane_oldest_timestamps[lane] = next_timestamp

    return LaneActivityRollup(
        lane_counts=lane_counts,
        lane_oldest_ages=lane_oldest_ages,
        lane_oldest_timestamps=lane_oldest_timestamps,
        mixed_count=mixed_count,
    )


def _format_simple_lane_rollup_for_display_order(
    display_order: tuple[str, ...],
) -> Callable[[dict[str, int], dict[str, int], dict[str, str]], str]:
    return lambda lane_counts, _lane_oldest_ages, _lane_oldest_timestamps: _format_simple_lane_rollup(
        lane_counts,
        display_order,
    )


def _format_recent_lane_rollup_for_display_order(
    display_order: tuple[str, ...],
) -> Callable[[dict[str, int], dict[str, int], dict[str, str]], str]:
    return lambda lane_counts, lane_oldest_ages, lane_oldest_timestamps: _format_recent_lane_rollup(
        lane_counts,
        lane_oldest_ages,
        lane_oldest_timestamps,
        display_order,
    )


def _render_approval_volume_metric(total: int) -> str:
    approval_label = "approval" if total == 1 else "approvals"
    return f"{approval_label}: {total}"


def _render_approval_family_metric(family_counts: dict[str, int]) -> str:
    badges = _render_tool_family_badges(family_counts)
    if not badges:
        return ""
    return f"families: {', '.join(badges)}"


def _render_intervention_target_metric(target_kind_counts: dict[str, int]) -> str:
    badges: list[str] = []
    for target_kind in INTERVENTION_TARGET_KIND_DISPLAY_ORDER:
        count = target_kind_counts.get(target_kind, 0)
        if count:
            badges.append(f"{target_kind} {count}")
    for target_kind in sorted(target_kind_counts):
        if target_kind in INTERVENTION_TARGET_KIND_DISPLAY_ORDER:
            continue
        count = target_kind_counts[target_kind]
        if count:
            badges.append(f"{target_kind} {count}")
    if not badges:
        return ""
    return f"targets: {', '.join(badges)}"


def _render_intervention_follow_up_metric(follow_up_counts: dict[str, int]) -> str:
    badges: list[str] = []
    for label in INTERVENTION_FOLLOW_UP_DISPLAY_ORDER:
        count = follow_up_counts.get(label, 0)
        if count:
            badges.append(f"{label} {count}")
    for label in sorted(follow_up_counts):
        if label in INTERVENTION_FOLLOW_UP_DISPLAY_ORDER:
            continue
        count = follow_up_counts[label]
        if count:
            badges.append(f"{label} {count}")
    if not badges:
        return ""
    return f"continuations: {', '.join(badges)}"


def _render_tool_failure_metric(test_failure_count: int, tool_failure_count: int) -> str:
    parts: list[str] = []
    if test_failure_count > 0:
        parts.append(f"test {test_failure_count}")
    if tool_failure_count > 0:
        parts.append(f"tool {tool_failure_count}")
    if not parts:
        return "failures: none"
    return f"failures: {', '.join(parts)}"



def _render_intervention_request_metric(total_requests: int) -> str:
    request_label = "request" if total_requests == 1 else "requests"
    return f"{request_label}: {total_requests}"



def _render_session_count_metric(label: str, count: int) -> str:
    if count <= 0:
        return ""
    session_label = "session" if count == 1 else "sessions"
    return f"{label}: {count} {session_label}"


def _update_oldest_age_and_timestamp(
    current_age: int,
    current_timestamp: str,
    candidate_age: int,
    candidate_timestamp: str,
) -> tuple[int, str]:
    if candidate_age > current_age:
        return candidate_age, candidate_timestamp
    if candidate_age == current_age and candidate_age > 0 and not current_timestamp and candidate_timestamp:
        return candidate_age, candidate_timestamp
    return current_age, current_timestamp


def _format_oldest_age_clause(age_seconds: int, timestamp: str = "") -> str:
    if age_seconds <= 0:
        return ""
    clause = f"oldest {_format_age_compact(age_seconds)}"
    if timestamp:
        clause += f" @ {timestamp}"
    return f" ({clause})"


def _render_age_timestamp_metric(
    label: str,
    age_seconds: int,
    timestamp: str = "",
    *,
    activity_fallback: bool = False,
) -> str:
    if age_seconds <= 0:
        return ""
    metric = f"{label}: {_format_age_compact(age_seconds)}"
    if timestamp:
        metric += f" @ {timestamp}"
    if activity_fallback:
        metric += " (activity fallback)"
    return metric


def _intervention_restored_age_and_timestamp(summary: SessionSummary) -> tuple[int, str]:
    candidates = [
        (summary.restored_pending_approval_age_sort_key, summary.restored_pending_approval_oldest_at),
        (summary.last_restored_outcome_age_sort_key, summary.last_restored_outcome_at),
        (summary.last_restored_approval_age_sort_key, summary.last_restored_approval_at),
    ]
    best_age = 0
    best_timestamp = ""
    for age_seconds, timestamp in candidates:
        best_age, best_timestamp = _update_oldest_age_and_timestamp(
            best_age,
            best_timestamp,
            age_seconds,
            timestamp,
        )
    return best_age, best_timestamp


def _approval_restore_restored_age_and_timestamp(summary: SessionSummary) -> tuple[int, str]:
    if summary.last_restored_outcome_age_sort_key > 0:
        return summary.last_restored_outcome_age_sort_key, summary.last_restored_outcome_at
    if summary.restored_pending_approval_age_sort_key <= 0 and summary.last_restored_approval_age_sort_key > 0:
        return summary.last_restored_approval_age_sort_key, summary.last_restored_approval_at
    return 0, ""


def _restored_reference_age_and_timestamp(summary: SessionSummary) -> tuple[int, str]:
    return _approval_restore_restored_age_and_timestamp(summary)


def _add_family_counts(target: dict[str, int], counts: tuple[int, ...]) -> None:
    for family, count in zip(APPROVAL_TOOL_FAMILY_DISPLAY_ORDER, counts, strict=False):
        if count > 0:
            target[family] = target.get(family, 0) + count


def _pending_filter_focus_lanes(fresh_queue_sessions: int, restored_queue_sessions: int) -> list[str]:
    focus_lanes: list[str] = []
    if fresh_queue_sessions > 0:
        focus_lanes.append("fresh")
    if restored_queue_sessions > 0:
        focus_lanes.append("restored")
    return focus_lanes or ["pending"]


def _format_pending_approval_filter_metrics(metrics: PendingApprovalFilterMetrics) -> list[str]:
    return [
        _render_approval_volume_metric(metrics.total_approvals),
        _render_approval_family_metric(metrics.family_counts),
        _render_session_count_metric("multi-queue", metrics.multi_queue_sessions),
        _render_session_count_metric("restored queues", metrics.restored_queue_sessions),
    ]


def _pending_approval_filter_focus_lanes(metrics: PendingApprovalFilterMetrics) -> list[str]:
    return _pending_filter_focus_lanes(metrics.fresh_queue_sessions, metrics.restored_queue_sessions)


def _format_denied_approval_filter_metrics(metrics: DeniedApprovalFilterMetrics) -> list[str]:
    return [
        _render_approval_volume_metric(metrics.total_denied),
        _render_approval_family_metric(metrics.family_counts),
        _render_session_count_metric("restored denied", metrics.restored_denied_sessions),
    ]


def _denied_approval_filter_focus_lanes(metrics: DeniedApprovalFilterMetrics) -> list[str]:
    return _pending_filter_focus_lanes(metrics.fresh_denied_sessions, metrics.restored_denied_sessions)


def _render_metric_filter_summary_lines(
    summaries: list[SessionSummary],
    *,
    backlog_label: str,
    focus_label: str,
    page_metric_label: str,
    page_index: int,
    page_size: int,
    summarize_metrics: Callable[[list[SessionSummary]], MetricRollupT],
    format_metrics: Callable[[MetricRollupT], list[str]],
    focus_lanes_getter: Callable[[MetricRollupT], list[str]],
    oldest_age_seconds_getter: Callable[[MetricRollupT], int],
) -> list[str]:
    full_metrics = summarize_metrics(summaries)
    oldest_age_seconds = oldest_age_seconds_getter(full_metrics)
    lines = render_recent_session_metric_summary_block_lines(
        backlog_label=backlog_label,
        count=len(summaries),
        backlog_metrics=format_metrics(full_metrics),
        focus_label=focus_label,
        focus_lanes=focus_lanes_getter(full_metrics),
        oldest=_format_age_compact(oldest_age_seconds) if oldest_age_seconds > 0 else "",
        oldest_at=getattr(full_metrics, "oldest_at", ""),
    )
    if len(summaries) <= page_size:
        return lines

    visible_summaries, off_page_summaries = _slice_visible_and_off_page_summaries(
        summaries,
        page_index=page_index,
        page_size=page_size,
    )
    visible_metrics = summarize_metrics(visible_summaries)
    return render_recent_session_metric_summary_block_lines(
        backlog_label=backlog_label,
        count=len(summaries),
        backlog_metrics=format_metrics(full_metrics),
        focus_label=focus_label,
        focus_lanes=focus_lanes_getter(full_metrics),
        oldest=_format_age_compact(oldest_age_seconds) if oldest_age_seconds > 0 else "",
        oldest_at=getattr(full_metrics, "oldest_at", ""),
        page_metric_label=page_metric_label,
        visible_metrics=format_metrics(visible_metrics),
        off_page_metrics=format_metrics(summarize_metrics(off_page_summaries)),
    )


def _render_metric_detail_line(label: str, metrics: Sequence[str]) -> str:
    filtered_metrics = [metric for metric in metrics if metric]
    if not filtered_metrics:
        return ""
    return f"{label}: {' | '.join(filtered_metrics)}"



def _append_metric_detail_lines(
    lines: list[str],
    summaries: list[SessionSummary],
    *,
    detail_label: str,
    page_metric_label: str,
    page_index: int,
    page_size: int,
    summarize_metrics: Callable[[list[SessionSummary]], MetricRollupT],
    format_metrics: Callable[[MetricRollupT], list[str]],
) -> list[str]:
    metrics = summarize_metrics(summaries)
    detail_line = _render_metric_detail_line(detail_label, format_metrics(metrics))
    if detail_line:
        lines.append(detail_line)
    if len(summaries) <= page_size:
        return lines

    visible_summaries, off_page_summaries = _slice_visible_and_off_page_summaries(
        summaries,
        page_index=page_index,
        page_size=page_size,
    )
    lines.append(
        render_page_metric_summary_line(
            page_metric_label,
            format_metrics(summarize_metrics(visible_summaries)),
            off_page_metrics=format_metrics(summarize_metrics(off_page_summaries)),
        )
    )
    return lines



def _summarize_pending_approval_filter_metrics(
    summaries: list[SessionSummary],
) -> PendingApprovalFilterMetrics:
    total_approvals = 0
    family_counts: dict[str, int] = {}
    fresh_queue_sessions = 0
    restored_queue_sessions = 0
    multi_queue_sessions = 0
    oldest_age_seconds = 0
    oldest_at = ""

    for summary in summaries:
        total_approvals += summary.pending_approval_count
        if summary.pending_approval_count > 1:
            multi_queue_sessions += 1
        restored_pending_key, _, _, _, _ = _approval_attention_family_keys(summary)
        if any(summary.pending_approval_attention_sort_key):
            fresh_queue_sessions += 1
            _add_family_counts(family_counts, summary.pending_approval_attention_sort_key)
        if any(restored_pending_key):
            restored_queue_sessions += 1
            _add_family_counts(family_counts, restored_pending_key)
        oldest_age_seconds, oldest_at = _update_oldest_age_and_timestamp(
            oldest_age_seconds,
            oldest_at,
            summary.pending_approval_age_sort_key,
            summary.pending_approval_oldest_at,
        )

    return PendingApprovalFilterMetrics(
        total_approvals=total_approvals,
        family_counts=family_counts,
        fresh_queue_sessions=fresh_queue_sessions,
        restored_queue_sessions=restored_queue_sessions,
        multi_queue_sessions=multi_queue_sessions,
        oldest_age_seconds=oldest_age_seconds,
        oldest_at=oldest_at,
    )


def _render_pending_approval_filter_summary_lines(
    summaries: list[SessionSummary],
    *,
    page_index: int,
    page_size: int,
) -> list[str]:
    return _render_metric_filter_summary_lines(
        summaries,
        backlog_label="Pending approval backlog",
        focus_label="Pending focus",
        page_metric_label="pending queues",
        page_index=page_index,
        page_size=page_size,
        summarize_metrics=_summarize_pending_approval_filter_metrics,
        format_metrics=_format_pending_approval_filter_metrics,
        focus_lanes_getter=_pending_approval_filter_focus_lanes,
        oldest_age_seconds_getter=lambda metrics: metrics.oldest_age_seconds,
    )


def _summarize_tool_filter_metrics(
    summaries: list[SessionSummary],
) -> ToolFilterMetrics:
    total_test_failures = 0
    total_tool_failures = 0
    failing_sessions = 0

    for summary in summaries:
        total_test_failures += summary.recent_test_failure_count
        total_tool_failures += summary.recent_tool_failure_count
        if summary.recent_test_failure_count > 0 or summary.recent_tool_failure_count > 0:
            failing_sessions += 1

    return ToolFilterMetrics(
        total_test_failures=total_test_failures,
        total_tool_failures=total_tool_failures,
        failing_sessions=failing_sessions,
    )



def _format_tool_filter_metrics(metrics: ToolFilterMetrics) -> list[str]:
    return [
        _render_tool_failure_metric(metrics.total_test_failures, metrics.total_tool_failures),
        _render_session_count_metric("failing", metrics.failing_sessions),
    ]


def _summarize_pending_only_lane_metrics(
    summaries: list[SessionSummary],
    *,
    filter_mode: str,
) -> PendingOnlyLaneMetrics:
    pending_only_sessions = 0
    restored_pending_only_sessions = 0
    oldest_age_seconds = 0
    oldest_at = ""
    oldest_uses_activity_fallback = False
    restored_oldest_age_seconds = 0
    restored_oldest_at = ""
    restored_oldest_uses_activity_fallback = False

    for summary in summaries:
        if not summary.has_pending_only_lane_match(filter_mode):
            continue
        pending_only_sessions += 1
        lane_age_seconds, lane_timestamp, lane_used_activity_fallback = (
            summary.pending_only_lane_oldest_age_and_timestamp_source(filter_mode)
        )
        previous_oldest_age = oldest_age_seconds
        previous_oldest_timestamp = oldest_at
        oldest_age_seconds, oldest_at = _update_oldest_age_and_timestamp(
            oldest_age_seconds,
            oldest_at,
            lane_age_seconds,
            lane_timestamp,
        )
        if (oldest_age_seconds, oldest_at) != (previous_oldest_age, previous_oldest_timestamp):
            oldest_uses_activity_fallback = lane_used_activity_fallback
        if summary.has_restored_pending_only_lane_match(filter_mode):
            restored_pending_only_sessions += 1
            restored_age_seconds, restored_timestamp, restored_used_activity_fallback = (
                summary.restored_pending_only_lane_oldest_age_and_timestamp_source(filter_mode)
            )
            previous_restored_age = restored_oldest_age_seconds
            previous_restored_timestamp = restored_oldest_at
            restored_oldest_age_seconds, restored_oldest_at = _update_oldest_age_and_timestamp(
                restored_oldest_age_seconds,
                restored_oldest_at,
                restored_age_seconds,
                restored_timestamp,
            )
            if (restored_oldest_age_seconds, restored_oldest_at) != (
                previous_restored_age,
                previous_restored_timestamp,
            ):
                restored_oldest_uses_activity_fallback = restored_used_activity_fallback

    return PendingOnlyLaneMetrics(
        pending_only_sessions=pending_only_sessions,
        restored_pending_only_sessions=restored_pending_only_sessions,
        oldest_age_seconds=oldest_age_seconds,
        oldest_at=oldest_at,
        oldest_uses_activity_fallback=oldest_uses_activity_fallback,
        restored_oldest_age_seconds=restored_oldest_age_seconds,
        restored_oldest_at=restored_oldest_at,
        restored_oldest_uses_activity_fallback=restored_oldest_uses_activity_fallback,
    )


def _summarize_workspace_edit_pending_only_metrics(
    summaries: list[SessionSummary],
) -> PendingOnlyLaneMetrics:
    return _summarize_pending_only_lane_metrics(summaries, filter_mode="workspace-edit")


def _summarize_shell_test_pending_only_metrics(
    summaries: list[SessionSummary],
) -> PendingOnlyLaneMetrics:
    return _summarize_pending_only_lane_metrics(summaries, filter_mode="shell-test")


def _format_pending_only_lane_metrics(metrics: PendingOnlyLaneMetrics) -> list[str]:
    return [
        _render_session_count_metric("pending-only", metrics.pending_only_sessions),
        _render_session_count_metric("restored pending-only", metrics.restored_pending_only_sessions),
        _render_age_timestamp_metric(
            "oldest pending-only",
            metrics.oldest_age_seconds,
            metrics.oldest_at,
            activity_fallback=metrics.oldest_uses_activity_fallback,
        ),
        _render_age_timestamp_metric(
            "oldest restored pending-only",
            metrics.restored_oldest_age_seconds,
            metrics.restored_oldest_at,
            activity_fallback=metrics.restored_oldest_uses_activity_fallback,
        ),
    ]



def _summarize_intervention_filter_metrics(
    summaries: list[SessionSummary],
) -> InterventionFilterMetrics:
    total_requests = 0
    family_counts: dict[str, int] = {}
    target_kind_counts: dict[str, int] = {}
    follow_up_counts: dict[str, int] = {}

    for summary in summaries:
        total_requests += summary.intervention_unique_count
        for family, count in summary.intervention_family_counts.items():
            if count > 0:
                family_counts[family] = family_counts.get(family, 0) + count
        for target_kind, count in summary.intervention_target_kind_counts.items():
            if count > 0:
                target_kind_counts[target_kind] = target_kind_counts.get(target_kind, 0) + count
        for follow_up_label, count in summary.intervention_follow_up_counts.items():
            if count > 0:
                follow_up_counts[follow_up_label] = follow_up_counts.get(follow_up_label, 0) + count

    return InterventionFilterMetrics(
        total_requests=total_requests,
        family_counts=family_counts,
        target_kind_counts=target_kind_counts,
        follow_up_counts=follow_up_counts,
    )



def _format_intervention_filter_metrics(metrics: InterventionFilterMetrics) -> list[str]:
    family_metric = _render_approval_family_metric(metrics.family_counts) or "families: none"
    target_metric = _render_intervention_target_metric(metrics.target_kind_counts) or "targets: none"
    follow_up_metric = _render_intervention_follow_up_metric(metrics.follow_up_counts)
    return [
        _render_intervention_request_metric(metrics.total_requests),
        family_metric,
        target_metric,
        follow_up_metric,
    ]



def _summarize_denied_approval_filter_metrics(
    summaries: list[SessionSummary],
) -> DeniedApprovalFilterMetrics:
    total_denied = 0
    family_counts: dict[str, int] = {}
    fresh_denied_sessions = 0
    restored_denied_sessions = 0
    oldest_age_seconds = 0
    oldest_at = ""

    for summary in summaries:
        total_denied += summary.denied_approval_count
        _, restored_denied_key, _, denied_key, fresh_denied_key = _approval_attention_family_keys(summary)
        _add_family_counts(family_counts, denied_key)
        if any(fresh_denied_key):
            fresh_denied_sessions += 1
        if any(restored_denied_key):
            restored_denied_sessions += 1
        oldest_age_seconds, oldest_at = _update_oldest_age_and_timestamp(
            oldest_age_seconds,
            oldest_at,
            summary.last_denied_approval_age_sort_key,
            summary.last_denied_approval_at,
        )

    return DeniedApprovalFilterMetrics(
        total_denied=total_denied,
        family_counts=family_counts,
        fresh_denied_sessions=fresh_denied_sessions,
        restored_denied_sessions=restored_denied_sessions,
        oldest_age_seconds=oldest_age_seconds,
        oldest_at=oldest_at,
    )


def _render_denied_approval_filter_summary_lines(
    summaries: list[SessionSummary],
    *,
    page_index: int,
    page_size: int,
) -> list[str]:
    return _render_metric_filter_summary_lines(
        summaries,
        backlog_label="Denied approval backlog",
        focus_label="Denied focus",
        page_metric_label="denied approvals",
        page_index=page_index,
        page_size=page_size,
        summarize_metrics=_summarize_denied_approval_filter_metrics,
        format_metrics=_format_denied_approval_filter_metrics,
        focus_lanes_getter=_denied_approval_filter_focus_lanes,
        oldest_age_seconds_getter=lambda metrics: metrics.oldest_age_seconds,
    )


def _is_stale_approval_filter_mode(filter_mode: str) -> bool:
    return filter_mode in STALE_APPROVAL_FILTER_LANES


def _tool_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    if summary.has_workspace_inspect_activity or summary.has_workspace_edit_activity:
        lanes.add("workspace")
    if summary.has_shell_inspect_activity or summary.has_shell_test_activity:
        lanes.add("shell")
    if (summary.last_tool_preview or summary.last_tool_badges or summary.recent_tool_previews) and not lanes:
        lanes.add("other")
    return lanes


def _tool_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    return dict(summary.tool_lane_age_sort_keys)


def _tool_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    return dict(summary.tool_lane_timestamps)


def _workspace_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    if summary.has_workspace_inspect_activity:
        lanes.add("inspect")
    if summary.has_workspace_edit_activity:
        lanes.add("edit")
    return lanes


def _workspace_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    return dict(summary.workspace_lane_age_sort_keys)


def _workspace_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    return dict(summary.workspace_lane_timestamps)


def _workspace_filter_focus_label(filter_mode: str) -> str:
    if filter_mode == "workspace-edit":
        return "edit"
    return "inspect"


def _summarize_workspace_lanes(summaries: list[SessionSummary]) -> tuple[dict[str, int], int]:
    rollup = _summarize_lane_activity(
        summaries,
        display_order=WORKSPACE_LANE_DISPLAY_ORDER,
        lane_getter=_workspace_lanes,
        include_mixed_count=True,
    )
    return rollup.lane_counts, rollup.mixed_count


def _shell_lanes(summary: SessionSummary) -> set[str]:
    lanes: set[str] = set()
    if summary.has_shell_inspect_activity:
        lanes.add("inspect")
    if summary.has_shell_test_activity:
        lanes.add("test")
    return lanes


def _shell_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    return dict(summary.shell_lane_age_sort_keys)


def _shell_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    return dict(summary.shell_lane_timestamps)


def _shell_filter_focus_label(filter_mode: str) -> str:
    if filter_mode == "shell-inspect":
        return "inspect"
    if filter_mode == "shell-test":
        return "test"
    return "inspect, test"


def _summarize_shell_lanes(summaries: list[SessionSummary]) -> tuple[dict[str, int], int]:
    rollup = _summarize_lane_activity(
        summaries,
        display_order=SHELL_LANE_DISPLAY_ORDER,
        lane_getter=_shell_lanes,
        include_mixed_count=True,
    )
    return rollup.lane_counts, rollup.mixed_count


def _format_simple_lane_rollup(lane_counts: dict[str, int], display_order: tuple[str, ...]) -> str:
    return ", ".join(f"{lane} {lane_counts[lane]}" for lane in display_order if lane_counts.get(lane, 0) > 0)


def _format_recent_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
    lane_oldest_timestamps: dict[str, str],
    display_order: tuple[str, ...],
) -> str:
    lane_parts: list[str] = []
    for lane in display_order:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age >= MIN_LANE_ROLLUP_AGE_SECONDS:
            part += _format_oldest_age_clause(oldest_age, lane_oldest_timestamps.get(lane, ""))
        lane_parts.append(part)
    return ", ".join(lane_parts)


def _intervention_preview_matches(summary: SessionSummary, label: str) -> bool:
    label_prefix = f"{label} "
    approval_prefix = f"approval {label}"
    approval_label_prefix = f"{approval_prefix} "
    for preview in [summary.last_intervention_preview, *summary.recent_intervention_previews]:
        if (
            preview == label
            or preview.startswith(label_prefix)
            or preview == approval_prefix
            or preview.startswith(approval_label_prefix)
        ):
            return True
    return False


def _intervention_preview_is_restored(summary: SessionSummary) -> bool:
    for preview in [summary.last_intervention_preview, *summary.recent_intervention_previews]:
        if " restored " in f" {preview} ":
            return True
    return False


def _intervention_lanes(summary: SessionSummary) -> set[str]:
    badges = summary.intervention_badges
    lanes: set[str] = set()
    if (
        summary.pending_approval_count > 0
        or any(badge.startswith("pending ") for badge in badges)
        or _intervention_preview_matches(summary, "pending")
    ):
        lanes.add("pending")
    if any(badge.startswith("blocked ") for badge in badges) or _intervention_preview_matches(summary, "blocked"):
        lanes.add("blocked")
    if (
        any(badge.startswith("approved ") for badge in badges)
        or _intervention_preview_matches(summary, "approved")
        or _intervention_preview_matches(summary, "continued")
    ):
        lanes.add("approved")
    if (
        summary.denied_approval_count > 0
        or any(badge.startswith("denied ") for badge in badges)
        or _intervention_preview_matches(summary, "denied")
    ):
        lanes.add("denied")
    if (
        summary.restored_approval_count > 0
        or any(badge.startswith("restored ") for badge in badges)
        or _intervention_preview_is_restored(summary)
    ):
        lanes.add("restored")
    return lanes


def _intervention_lane_age_seconds(summary: SessionSummary) -> dict[str, int]:
    lanes = _intervention_lanes(summary)
    lane_ages: dict[str, int] = {}
    if "pending" in lanes and summary.pending_approval_age_sort_key > 0:
        lane_ages["pending"] = summary.pending_approval_age_sort_key
    if "denied" in lanes and summary.last_denied_approval_age_sort_key > 0:
        lane_ages["denied"] = summary.last_denied_approval_age_sort_key
    if "restored" in lanes:
        restored_age_seconds = max(
            summary.restored_pending_approval_age_sort_key,
            summary.last_restored_outcome_age_sort_key,
            summary.last_restored_approval_age_sort_key,
        )
        if restored_age_seconds > 0:
            lane_ages["restored"] = restored_age_seconds
    return lane_ages


def _intervention_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    lanes = _intervention_lanes(summary)
    lane_timestamps: dict[str, str] = {}
    if "pending" in lanes and summary.pending_approval_oldest_at:
        lane_timestamps["pending"] = summary.pending_approval_oldest_at
    if "denied" in lanes and summary.last_denied_approval_at:
        lane_timestamps["denied"] = summary.last_denied_approval_at
    if "restored" in lanes:
        _, restored_timestamp = _intervention_restored_age_and_timestamp(summary)
        if restored_timestamp:
            lane_timestamps["restored"] = restored_timestamp
    return lane_timestamps


def _format_intervention_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
    lane_oldest_timestamps: dict[str, str],
) -> str:
    lane_parts: list[str] = []
    for lane in INTERVENTION_LANE_DISPLAY_ORDER:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age > 0:
            part += _format_oldest_age_clause(oldest_age, lane_oldest_timestamps.get(lane, ""))
        lane_parts.append(part)
    return ", ".join(lane_parts)


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


def _approval_restore_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    lanes = _approval_restore_lanes(summary)
    lane_timestamps: dict[str, str] = {}
    if "restore queue" in lanes and summary.restored_pending_approval_oldest_at:
        lane_timestamps["restore queue"] = summary.restored_pending_approval_oldest_at
    if "restored" in lanes:
        _, restored_timestamp = _restored_reference_age_and_timestamp(summary)
        if restored_timestamp:
            lane_timestamps["restored"] = restored_timestamp
    return lane_timestamps


def _summarize_approval_restore_lanes(
    summaries: list[SessionSummary],
) -> tuple[dict[str, int], dict[str, int], int]:
    rollup = _summarize_lane_activity(
        summaries,
        display_order=APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
        lane_getter=_approval_restore_lanes,
        age_getter=_approval_restore_lane_age_seconds,
        include_mixed_count=True,
    )
    return rollup.lane_counts, rollup.lane_oldest_ages, rollup.mixed_count


def _format_approval_restore_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
    lane_oldest_timestamps: dict[str, str],
) -> str:
    lane_parts: list[str] = []
    for lane in APPROVAL_RESTORE_LANE_DISPLAY_ORDER:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age > 0:
            part += _format_oldest_age_clause(oldest_age, lane_oldest_timestamps.get(lane, ""))
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
    rollup = _summarize_lane_activity(
        summaries,
        display_order=STALE_APPROVAL_LANE_DISPLAY_ORDER,
        lane_getter=_stale_approval_lanes,
        age_getter=_stale_approval_lane_age_seconds,
        allowed_lanes=lanes,
    )
    return rollup.lane_counts, rollup.lane_oldest_ages


def _format_stale_approval_lane_rollup(
    lane_counts: dict[str, int],
    lane_oldest_ages: dict[str, int],
    lane_oldest_timestamps: dict[str, str],
) -> str:
    lane_parts: list[str] = []
    for lane in STALE_APPROVAL_LANE_DISPLAY_ORDER:
        count = lane_counts.get(lane, 0)
        if count <= 0:
            continue
        part = f"{lane} {count}"
        oldest_age = lane_oldest_ages.get(lane, 0)
        if oldest_age > 0:
            part += _format_oldest_age_clause(oldest_age, lane_oldest_timestamps.get(lane, ""))
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


def _approval_restore_single_age_transform(filter_mode: str) -> Callable[[str], str] | None:
    if filter_mode == "approval-restore":
        return None
    return _approval_restore_age_label


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
    age_badges = _approval_restore_age_badges(summary, filter_mode, focus_lanes=focus_lanes)
    age_suffix = render_compact_badge_row_suffix(
        default_suffix=default_age_suffix,
        focused_badges=age_badges,
        singular_label="approval restore age",
        plural_label="approval restore ages",
        singular_value_transform=_approval_restore_single_age_transform(filter_mode),
    )
    focus_suffix = "" if filter_mode == "approval-restore" else render_lane_focus_suffix("restore focus", focus_lanes)
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
        singular_value_transform=_approval_restore_single_age_transform(filter_mode),
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


def _stale_approval_single_age_transform(filter_mode: str) -> Callable[[str], str] | None:
    if filter_mode == "approval-stale":
        return None
    return _stale_approval_badge_age_label


def _render_stale_approval_focus_suffix(filter_mode: str, focus_lanes: Sequence[str]) -> str:
    if filter_mode == "approval-stale":
        return ""
    return render_lane_focus_suffix("stale focus", focus_lanes)


def _should_render_stale_focus_preview_line(filter_mode: str) -> bool:
    return filter_mode != "approval-stale"


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
        singular_value_transform=_stale_approval_single_age_transform(filter_mode),
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
        include_focus_line=_should_render_stale_focus_preview_line(filter_mode),
        singular_label="approval stale age",
        plural_label="approval stale ages",
        singular_value_transform=_stale_approval_single_age_transform(filter_mode),
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


def _stale_approval_lane_timestamps(summary: SessionSummary) -> dict[str, str]:
    lane_timestamps: dict[str, str] = {}
    for lane in _stale_approval_lanes(summary):
        if lane == "pending" and summary.pending_approval_oldest_at:
            lane_timestamps[lane] = summary.pending_approval_oldest_at
        elif lane == "denied" and summary.last_denied_approval_at:
            lane_timestamps[lane] = summary.last_denied_approval_at
        elif lane == "restore queue" and summary.restored_pending_approval_oldest_at:
            lane_timestamps[lane] = summary.restored_pending_approval_oldest_at
        elif lane == "restored":
            _, restored_timestamp = _restored_reference_age_and_timestamp(summary)
            if restored_timestamp:
                lane_timestamps[lane] = restored_timestamp
    return lane_timestamps


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
    return render_page_label(total_matches, limit, page_index)


def _picker_page_window_label(total_matches: int, limit: int, page_index: int, visible_count: int) -> str:
    return render_page_window_label(total_matches, limit, page_index, visible_count)


def _has_tool_filter_match(summary: SessionSummary) -> bool:
    return bool(
        summary.last_tool_preview
        or summary.last_tool_badges
        or summary.has_pending_workspace_edit_approval
        or summary.has_pending_shell_test_approval
    )



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
        return _has_tool_filter_match(summary)
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


def _format_iso_timestamp(value: str | None) -> str:
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return ""
    return _format_timestamp(parsed.timestamp())


def _oldest_approval_timestamp_display(approvals: Sequence[ApprovalRequest]) -> str:
    parsed_timestamps = [
        parsed
        for parsed in (_parse_iso_timestamp(approval.created_at) for approval in approvals)
        if parsed is not None
    ]
    if not parsed_timestamps:
        return ""
    oldest = min(parsed_timestamps)
    return _format_timestamp(oldest.timestamp())


def _approval_record_timestamp_display(record: dict[str, object] | None) -> str:
    if record is None:
        return ""
    return _format_iso_timestamp(str(record.get("timestamp")) if record.get("timestamp") else None)


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
