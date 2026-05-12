from strands_agent_tui.sessions.summary_utils import (
    render_backlog_summary_line,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_page_lane_summary_line,
)


def main() -> None:
    print(
        "summary_backlog_counts=",
        render_backlog_summary_line("Shell backlog", 1) == "Shell backlog: 1 session"
        and render_backlog_summary_line(
            "Approval restore backlog",
            10,
            lane_rollup="restore queue 9 (oldest 18d), restored 2 (oldest 8h)",
            overlap_summary="mixed 1 session",
        )
        == "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d), restored 2 (oldest 8h) | overlap: mixed 1 session",
    )
    print(
        "summary_filter_focus=",
        render_filter_focus_line("Shell focus", []) == "Shell focus: none"
        and render_filter_focus_line(
            "Stale lane focus",
            ["pending", "denied"],
            cutoff="approvals >= 7d old",
        )
        == "Stale lane focus: pending, denied | cutoff: approvals >= 7d old",
    )
    print(
        "summary_page_rollup_overlap=",
        render_page_lane_summary_line(
            "restore lanes",
            "restore queue 8 (oldest 18d)",
            off_page_rollup="restore queue 1 (oldest 3d), restored 2 (oldest 8h)",
            visible_overlap_summary="none",
            off_page_overlap_summary="mixed 1 session",
        )
        == "This page restore lanes: restore queue 8 (oldest 18d) | more off-page: restore queue 1 (oldest 3d), restored 2 (oldest 8h) | overlap here/off-page: none / mixed 1 session"
        and render_page_lane_summary_line("stale lanes", "pending 2 (oldest 14d)")
        == "This page stale lanes: pending 2 (oldest 14d)",
    )
    print(
        "summary_compact_badges=",
        render_compact_badge_row_suffix(
            default_suffix=" | approval restore age: 3d",
            focused_badges=["restore queue 3d", "restored 6h"],
            singular_label="approval restore age",
            plural_label="approval restore ages",
        )
        == " | approval restore ages: restore queue 3d; restored 6h"
        and render_compact_badge_preview_lines(
            default_lines=["- approval restore age: 3d"],
            focused_badges=["restore queue 3d", "restored 6h"],
            focus_lanes=["restore queue", "restored"],
            focus_label="restore focus",
            include_focus_line=True,
            singular_label="approval restore age",
            plural_label="approval restore ages",
        )
        == [
            "- restore focus: restore queue, restored",
            "- approval restore ages: restore queue 3d; restored 6h",
        ],
    )


if __name__ == "__main__":
    main()
