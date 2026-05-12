from strands_agent_tui.sessions.summary_utils import (
    render_backlog_summary_line,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_page_lane_summary_line,
    render_picker_empty_filter_adjust_guidance,
    render_picker_empty_filter_prompt,
    render_picker_empty_filter_visible_guidance,
    render_recent_session_empty_state_lines,
    render_recent_session_filter_jump_line,
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
    print(
        "summary_empty_state=",
        render_recent_session_empty_state_lines(
            available_count=1,
            filter_mode="pending",
            surface="picker",
        )
        == [
            "No saved sessions match the active picker filter.",
            "1 saved session still exists under this root.",
            "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage.",
            "Press Enter or N to start a fresh session while keeping this picker context for the next reopen.",
        ]
        and render_recent_session_empty_state_lines(
            available_count=2,
            filter_mode="pending",
            surface="switcher",
        )
        == [
            "No saved sessions match the active switcher filter.",
            "2 saved sessions still exist under this root.",
            "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage.",
            "Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists.",
            "Enter switches the highlighted session once a visible row exists again.",
        ],
    )
    print(
        "summary_filter_guidance=",
        render_recent_session_filter_jump_line()
        == "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage."
        and render_picker_empty_filter_prompt()
        == "No sessions match this filter. Press Enter or N for a new session, or use A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to change triage: "
        and render_picker_empty_filter_visible_guidance()
        == "No sessions are visible with the active filter. Press A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to keep triaging; Enter or N starts a new session."
        and render_picker_empty_filter_adjust_guidance()
        == "No sessions match the active filter. Use A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to adjust triage, or press Enter/N to start a new session.",
    )


if __name__ == "__main__":
    main()
