from __future__ import annotations

from collections.abc import Iterable


RESTORE_FOCUS_LINE = "Restore lane focus: restore queue, restored"
STALE_FOCUS_LINE = "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= {days}d old"


def _session_lines(session_ids: Iterable[str]) -> list[str]:
    return [f"{session_id} |" for session_id in session_ids]


def smoke_text_matches(
    text: str,
    *,
    required: Iterable[str] = (),
    excluded: Iterable[str] = (),
) -> bool:
    return all(snippet in text for snippet in required) and all(snippet not in text for snippet in excluded)


def matches_approval_restore_focus_output(
    text: str,
    *,
    required_session_ids: Iterable[str] = (),
    excluded_session_ids: Iterable[str] = (),
    sort_mode: str = "recent",
) -> bool:
    return smoke_text_matches(
        text,
        required=[
            f"Filter: approval-restore | Sort: {sort_mode}",
            * _session_lines(required_session_ids),
            "Approval restore backlog: 3 sessions | lanes: restore queue 2 (oldest 3d @",
            "restored 1 (oldest 6h @",
            RESTORE_FOCUS_LINE,
        ],
        excluded=_session_lines(excluded_session_ids),
    )


def matches_approval_restore_badges_output(text: str) -> bool:
    return smoke_text_matches(
        text,
        required=["approval restore: pending 1", "approval restore: denied 1"],
    )


def matches_approval_restore_tool_badges_output(text: str) -> bool:
    return smoke_text_matches(
        text,
        required=["approval restore tools: test 1", "approval restore tools: edit 1"],
    )


def matches_approval_restore_age_output(text: str) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "approval restore age: restore queue 3d",
            "approval restore age: restored 6h",
        ],
        excluded=[
            "restore focus: restore queue",
            "restore focus: restored",
        ],
    )


def matches_approval_restore_preview_split_output(text: str) -> bool:
    return (
        "- last restored approval:" in text
        or smoke_text_matches(
            text,
            required=[
                "- restored current approval: pending run_shell_command via fake_runtime | queued 1",
                "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0",
            ],
        )
    )


def matches_approval_restore_overlap_output(text: str) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d @",
            "restored 1 (oldest 6h @",
            "| overlap: mixed 1 session",
            RESTORE_FOCUS_LINE,
        ],
    )


def matches_approval_restore_overlap_preview_split_output(text: str) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "approval restore ages: restore queue 3d; restored 6h",
            "restored current: pending run_shell_command via fake_runtime; queued 1",
            "restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0",
            "- restored current approval: pending run_shell_command via fake_runtime | queued 1",
            "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0",
        ],
        excluded=[
            "restore focus: restore queue, restored",
            "- latest restored outcome age: 6h",
        ],
    )


def matches_approval_restore_page_rollup_output(first_page_text: str, second_page_text: str) -> bool:
    return smoke_text_matches(
        first_page_text,
        required=[
            "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d @",
            "restored 2 (oldest 8h @",
            "| overlap: mixed 1 session",
            "This page restore lanes: restore queue 8 (oldest 18d @",
            "more off-page: restore queue 1 (oldest 3d @",
            "overlap here/off-page: none / mixed 1 session",
        ],
    ) and smoke_text_matches(
        second_page_text,
        required=[
            "This page restore lanes: restore queue 1 (oldest 3d @",
            "restored 2 (oldest 8h @",
            "more off-page: restore queue 8 (oldest 18d @",
            "overlap here/off-page: mixed 1 session / none",
        ],
    )


def matches_broad_approval_stale_output(
    text: str,
    *,
    required_session_ids: Iterable[str] = (),
    excluded_session_ids: Iterable[str] = (),
    sort_mode: str = "recent",
) -> bool:
    return smoke_text_matches(
        text,
        required=[
            f"Filter: approval-stale | Sort: {sort_mode}",
            * _session_lines(required_session_ids),
            "| approval stale age: pending 45d",
            "- approval stale age: pending 45d",
        ],
        excluded=[
            * _session_lines(excluded_session_ids),
            "| approval stale age: 45d | stale focus: pending",
            "approval stale: pending 45d",
            "- stale focus: pending",
        ],
    )


def matches_stale_backlog_output(text: str, *, oldest_age: str = "45d") -> bool:
    return smoke_text_matches(
        text,
        required=[f"Stale approval backlog: 1 session | lanes: pending 1 (oldest {oldest_age} @"],
    )


def matches_stale_cutoff_output(text: str, *, days: int = 7) -> bool:
    return smoke_text_matches(
        text,
        required=[f"Stale cutoff: approvals >= {days}d old"],
    )


def matches_stale_lane_focus_output(text: str, *, days: int = 7) -> bool:
    return smoke_text_matches(
        text,
        required=[STALE_FOCUS_LINE.format(days=days)],
    )


def matches_compact_stale_preview_output(text: str, *, days: int = 7) -> bool:
    return smoke_text_matches(
        text,
        excluded=[
            f"- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= {days}d old",
            "- stale focus: pending",
        ],
    )


def matches_broad_stale_row_focus_suppression(text: str) -> bool:
    return "stale focus: pending" not in text


def matches_stale_pending_subfilter_output(
    text: str,
    *,
    required_session_ids: Iterable[str] = (),
    excluded_session_ids: Iterable[str] = (),
) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "Filter: approval-stale-pending | Sort: recent",
            "Stale pending backlog: 8 sessions | lanes: pending 8 (oldest 52d @",
            "Stale lane focus: pending | cutoff: approvals >= 7d old",
            "- stale lane focus: pending | cutoff: approvals >= 7d old",
            * _session_lines(required_session_ids),
            "| approvals: pending 1 | approval focus: pending",
            "| approval stale age: 45d | stale focus: pending",
            "| intervention: pending 1",
            "- stale focus: pending",
            "- approvals: pending 1",
            "- approval focus: pending",
            "- approval stale age: 45d",
        ],
        excluded=[
            * _session_lines(excluded_session_ids),
            "| approval stale: pending 45d | stale focus: pending",
            "- approval stale: pending 45d",
        ],
    )


def matches_stale_denied_subfilter_output(
    text: str,
    *,
    required_session_ids: Iterable[str] = (),
    excluded_session_ids: Iterable[str] = (),
) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "Filter: approval-stale-denied | Sort: recent",
            "Stale denied backlog: 1 session | lanes: denied 1 (oldest 14d @",
            "Stale lane focus: denied | cutoff: approvals >= 7d old",
            "- stale lane focus: denied | cutoff: approvals >= 7d old",
            * _session_lines(required_session_ids),
            "| approvals: denied 1 | approval focus: denied/fresh",
            "| denied age: 14d | approval stale age: 14d | stale focus: denied",
            "| intervention: denied 1",
            "- stale focus: denied",
            "- approvals: denied 1",
            "- approval focus: denied/fresh",
            "- approval stale age: 14d",
        ],
        excluded=[
            * _session_lines(excluded_session_ids),
            "| approval stale: denied 14d | stale focus: denied",
            "- approval stale: denied 14d",
        ],
    )


def matches_stale_restored_subfilter_output(
    text: str,
    *,
    required_session_ids: Iterable[str] = (),
    excluded_session_ids: Iterable[str] = (),
) -> bool:
    return smoke_text_matches(
        text,
        required=[
            "Filter: approval-stale-restored | Sort: recent",
            "Stale restored backlog: 1 session | lanes: restore queue 1 (oldest 11d @",
            "restored 1 (oldest 10d @",
            "Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old",
            "- stale lane focus: restore queue, restored | cutoff: approvals >= 7d old",
            * _session_lines(required_session_ids),
            "| approvals: pending 1, approved 1 | approval focus: pending/restored",
            "| approval restore: pending 1, approved 1 | approval restore tools: test 1, edit 1",
            "| approval restore age: 11d",
            "| approval stale ages: restore queue 11d; restored 10d | stale focus: restore queue, restored",
            "| intervention: pending 1, approved 1, restored 1",
            "restored current: pending write_file via fake_runtime; queued 1",
            "restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0",
            "restored outcome age: 10d",
            "- stale focus: restore queue, restored",
            "- approvals: pending 1, approved 1",
            "- approval focus: pending/restored",
            "- approval restore: pending 1, approved 1",
            "- approval restore age: 11d",
            "- approval stale ages: restore queue 11d; restored 10d",
            "- restored current approval: pending write_file via fake_runtime | queued 1",
            "- latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0",
            "- latest restored outcome age: 10d",
        ],
        excluded=[
            * _session_lines(excluded_session_ids),
            "| approval stale: restore queue 11d, restored 10d | stale focus: restore queue, restored",
            "- approval stale: restore queue 11d, restored 10d",
        ],
    )


def matches_stale_page_rollup_output(first_page_text: str, second_page_text: str) -> bool:
    return smoke_text_matches(
        first_page_text,
        required=[
            "This page stale lanes: pending 8 (oldest 52d @",
            "more off-page: denied 1 (oldest 14d @",
            "restore queue 1 (oldest 11d @",
            "restored 1 (oldest 10d @",
        ],
    ) and smoke_text_matches(
        second_page_text,
        required=[
            "This page stale lanes: denied 1 (oldest 14d @",
            "restore queue 1 (oldest 11d @",
            "restored 1 (oldest 10d @",
            "more off-page: pending 8 (oldest 52d @",
        ],
    )


def matches_custom_stale_cutoff_output(text: str, *, days: int = 1, oldest_age: str = "2d") -> bool:
    return smoke_text_matches(
        text,
        required=[
            f"Stale approval backlog: 1 session | lanes: pending 1 (oldest {oldest_age} @",
            "session-custom-threshold",
            f"Stale cutoff: approvals >= {days}d old",
            STALE_FOCUS_LINE.format(days=days),
        ],
    )
