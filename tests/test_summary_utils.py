from strands_agent_tui.sessions.summary_utils import (
    render_backlog_summary_line,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_lane_focus_preview_lines,
    render_lane_focus_suffix,
    render_page_lane_summary_line,
)


def test_render_lane_focus_helpers_share_row_and_preview_wording() -> None:
    lanes = ["restore queue", "restored"]

    assert render_lane_focus_suffix("restore focus", lanes) == " | restore focus: restore queue, restored"
    assert render_lane_focus_preview_lines("restore focus", lanes) == [
        "- restore focus: restore queue, restored"
    ]


def test_render_backlog_summary_helpers_share_lane_rollup_and_focus_wording() -> None:
    assert render_backlog_summary_line(
        "Approval restore backlog",
        10,
        lane_rollup="restore queue 9 (oldest 18d), restored 2 (oldest 8h)",
        overlap_summary="mixed 1 session",
    ) == (
        "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d), restored 2 "
        "(oldest 8h) | overlap: mixed 1 session"
    )
    assert render_filter_focus_line("Restore lane focus", ["restore queue", "restored"]) == (
        "Restore lane focus: restore queue, restored"
    )
    assert render_filter_focus_line(
        "Stale lane focus",
        ["pending", "denied"],
        cutoff="approvals >= 7d old",
    ) == "Stale lane focus: pending, denied | cutoff: approvals >= 7d old"
    assert render_page_lane_summary_line(
        "restore lanes",
        "restore queue 8 (oldest 18d)",
        off_page_rollup="restore queue 1 (oldest 3d), restored 2 (oldest 8h)",
        visible_overlap_summary="none",
        off_page_overlap_summary="mixed 1 session",
    ) == (
        "This page restore lanes: restore queue 8 (oldest 18d) | more off-page: restore queue 1 "
        "(oldest 3d), restored 2 (oldest 8h) | overlap here/off-page: none / mixed 1 session"
    )


def test_render_compact_badge_helpers_render_single_focus_badge_consistently() -> None:
    transform = lambda badge: badge.removeprefix("restore queue ")

    assert render_compact_badge_row_suffix(
        default_suffix=" | approval restore age: 3d",
        focused_badges=["restore queue 3d"],
        singular_label="approval restore age",
        plural_label="approval restore ages",
        singular_value_transform=transform,
    ) == " | approval restore age: 3d"
    assert render_compact_badge_preview_lines(
        default_lines=["- approval restore age: 3d"],
        focused_badges=["restore queue 3d"],
        focus_lanes=["restore queue"],
        focus_label="restore focus",
        include_focus_line=False,
        singular_label="approval restore age",
        plural_label="approval restore ages",
        singular_value_transform=transform,
    ) == ["- approval restore age: 3d"]


def test_render_compact_badge_helpers_render_multiple_focus_badges_consistently() -> None:
    badges = ["restore queue 3d", "restored 6h"]

    assert render_compact_badge_row_suffix(
        default_suffix=" | approval restore age: 3d",
        focused_badges=badges,
        singular_label="approval restore age",
        plural_label="approval restore ages",
    ) == " | approval restore ages: restore queue 3d; restored 6h"
    assert render_compact_badge_preview_lines(
        default_lines=["- approval restore age: 3d"],
        focused_badges=badges,
        focus_lanes=["restore queue", "restored"],
        focus_label="restore focus",
        include_focus_line=True,
        singular_label="approval restore age",
        plural_label="approval restore ages",
    ) == [
        "- restore focus: restore queue, restored",
        "- approval restore ages: restore queue 3d; restored 6h",
    ]


def test_render_compact_badge_preview_lines_falls_back_to_default_when_unfocused() -> None:
    assert render_compact_badge_preview_lines(
        default_lines=["- approval stale: pending 45d"],
        focused_badges=[],
        focus_lanes=["pending"],
        focus_label="stale focus",
        include_focus_line=True,
        singular_label="approval stale age",
        plural_label="approval stale ages",
        singular_value_transform=lambda badge: badge.removeprefix("pending "),
    ) == [
        "- stale focus: pending",
        "- approval stale: pending 45d",
    ]
