from strands_agent_tui.sessions.summary_utils import (
    render_backlog_summary_line,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_page_label,
    render_page_lane_summary_line,
    render_page_window_label,
    render_picker_controls_line,
    render_picker_empty_filter_adjust_guidance,
    render_picker_empty_filter_prompt,
    render_picker_empty_filter_visible_guidance,
    render_picker_invalid_key_guidance,
    render_picker_invalid_selection_message,
    render_picker_selection_prompt,
    render_recent_session_empty_state_lines,
    render_recent_session_filter_jump_line,
    render_recent_session_page_banner,
    render_selected_session_preview_header_lines,
    render_switcher_controls_line,
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
        "summary_page_banner=",
        render_page_label(10, 8, 1) == "2/2"
        and render_page_window_label(10, 8, 1, 2) == "9-10 of 10"
        and render_recent_session_page_banner(
            filter_mode="approval-stale",
            sort_mode="attention",
            total_matches=10,
            page_size=8,
            page_index=1,
            visible_count=2,
            stale_cutoff_suffix=" | Stale cutoff: approvals >= 7d old",
        )
        == "Filter: approval-stale | Sort: attention | Stale cutoff: approvals >= 7d old | Page: 2/2 | Showing: 9-10 of 10",
    )
    print(
        "summary_selected_preview_header=",
        render_selected_session_preview_header_lines(
            visible_index=2,
            overall_index=10,
            total_matches=11,
            session_id="session-01",
            session_dir="/tmp/sessions/session-01",
        )
        == [
            "Selected preview:",
            "- slot 2 on this page | overall 10 of 11 | session session-01",
            "- artifact dir: /tmp/sessions/session-01",
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
    print(
        "summary_control_legends=",
        render_picker_controls_line()
        == "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, [ prev page, ] next page, N new session"
        and render_switcher_controls_line()
        == "Keys: ↑/↓ or J/K move, PgUp/PgDn or bracket keys page, Enter switch, 1-8 quick switch, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, N new session, Esc/F11 cancel",
    )
    print(
        "summary_picker_selection_guidance=",
        render_picker_selection_prompt()
        == "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to triage/page: "
        and render_picker_invalid_selection_message("9", 3)
        == "Invalid selection: '9'. Choose 1-3 from the visible list, press Enter to reopen highlighted, or N for a new session."
        and render_picker_invalid_key_guidance(3)
        == "Invalid selection. Use 1-3, J, K, A, P, D, R, V, O, Q, X, U, T, W, E, G, H, I, Y, S, [, ], Enter, or N.",
    )


if __name__ == "__main__":
    main()
