from strands_agent_tui.sessions.summary_utils import (
    render_backlog_summary_line,
    render_badged_preview_line,
    render_badged_row_suffix,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_numbered_preview_section_lines,
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
    render_preview_badges_line,
    render_preview_detail_line,
    render_recent_session_empty_state_lines,
    render_recent_session_filter_jump_line,
    render_recent_session_list_row,
    render_recent_session_page_banner,
    render_recent_session_summary_line,
    render_row_badges_suffix,
    render_row_detail_suffix,
    render_selected_preview_section_lines,
    render_selected_session_preview_header_lines,
    render_selected_session_preview_lines,
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
        "summary_preview_sections=",
        render_numbered_preview_section_lines(
            "recent interventions",
            ["approve queued edit", "deny shell rerun"],
        )
        == [
            "- recent interventions (2):",
            "  1. approve queued edit",
            "  2. deny shell rerun",
        ]
        and render_numbered_preview_section_lines(
            "recent tools",
            ["inspect/e0 git status --short -> M README.md"],
        )
        == [
            "- recent tools (1):",
            "  1. inspect/e0 git status --short -> M README.md",
        ]
        and render_numbered_preview_section_lines(
            "recent workspace tools",
            ["inspect read README.md", "edit write report.md"],
        )
        == [
            "- recent workspace tools (2):",
            "  1. inspect read README.md",
            "  2. edit write report.md",
        ]
        and render_numbered_preview_section_lines(
            "recent shell outcomes",
            ["confirm/e1 pytest -q -> exit 1"],
        )
        == [
            "- recent shell outcomes (1):",
            "  1. confirm/e1 pytest -q -> exit 1",
        ]
        and render_numbered_preview_section_lines("recent tools", []) == [],
    )
    print(
        "summary_preview_section_groups=",
        render_selected_preview_section_lines(
            render_preview_detail_line("pending", "2 approvals | first: run_shell_command"),
            render_preview_detail_line("pending queue", "first test; rest edit 1"),
            render_preview_badges_line("pending tools", ["test", "edit"]),
            render_preview_detail_line("approval restore age", "3d"),
            ["- stale focus: pending", "- approval stale age: 45d"],
        )
        == [
            "- pending: 2 approvals | first: run_shell_command",
            "- pending queue: first test; rest edit 1",
            "- pending tools: test, edit",
            "- approval restore age: 3d",
            "- stale focus: pending",
            "- approval stale age: 45d",
        ]
        and render_selected_preview_section_lines(
            render_preview_badges_line("shell", ["inspect 1", "test 2"]),
            render_preview_badges_line("shell lanes", ["inspect", "test"]),
            render_preview_badges_line("failures", ["test 1"]),
            render_preview_detail_line("last shell", "confirm/e1 pytest -q -> exit 1"),
            render_numbered_preview_section_lines(
                "recent shell outcomes",
                ["confirm/e1 pytest -q -> exit 1"],
            ),
        )
        == [
            "- shell: inspect 1, test 2",
            "- shell lanes: inspect, test",
            "- failures: test 1",
            "- last shell: confirm/e1 pytest -q -> exit 1",
            "- recent shell outcomes (1):",
            "  1. confirm/e1 pytest -q -> exit 1",
        ],
    )
    print(
        "summary_preview_assembly=",
        render_selected_session_preview_lines(
            header_lines=[
                "Selected preview:",
                "- slot 2 on this page | overall 10 of 11 | session session-01",
                "- artifact dir: /tmp/sessions/session-01",
            ],
            status_lines=[
                "- stale lane focus: pending | cutoff: approvals >= 7d old",
                "- attention reason: pending test approval queue",
            ],
            approval_lines=[
                "- pending: run_shell_command",
                "- pending age: 45d",
                "- pending tools: test",
            ],
            intervention_lines=["- last intervention: approved queued edit"],
            session_lines=["- draft: rerun picker smoke"],
            tool_lines=[
                "- last tool: inspect/e0 git status --short -> M README.md",
                "- recent tools (1):",
                "  1. inspect/e0 git status --short -> M README.md",
            ],
            workspace_lines=["- workspace lanes: inspect"],
            shell_lines=["- last shell: inspect/e0 git status --short -> M README.md"],
            event_lines=["- last event: tool_finished: run_shell_command"],
        )
        == [
            "Selected preview:",
            "- slot 2 on this page | overall 10 of 11 | session session-01",
            "- artifact dir: /tmp/sessions/session-01",
            "- stale lane focus: pending | cutoff: approvals >= 7d old",
            "- attention reason: pending test approval queue",
            "- pending: run_shell_command",
            "- pending age: 45d",
            "- pending tools: test",
            "- last intervention: approved queued edit",
            "- draft: rerun picker smoke",
            "- last tool: inspect/e0 git status --short -> M README.md",
            "- recent tools (1):",
            "  1. inspect/e0 git status --short -> M README.md",
            "- workspace lanes: inspect",
            "- last shell: inspect/e0 git status --short -> M README.md",
            "- last event: tool_finished: run_shell_command",
        ],
    )
    print(
        "summary_preview_detail_lines=",
        render_preview_detail_line("pending queue", "first test; rest edit 1, tool 1")
        == ["- pending queue: first test; rest edit 1, tool 1"]
        and render_preview_detail_line("pending age", "45d") == ["- pending age: 45d"]
        and render_preview_detail_line("last denied age", "9h") == ["- last denied age: 9h"]
        and render_preview_detail_line("approval restore queue", "first test; rest edit 1, tool 1")
        == ["- approval restore queue: first test; rest edit 1, tool 1"]
        and render_preview_detail_line("last intervention", "approved queued edit")
        == ["- last intervention: approved queued edit"]
        and render_preview_detail_line("last prompt", "review demo") == ["- last prompt: review demo"]
        and render_preview_detail_line("last workspace tool", "inspect read README.md")
        == ["- last workspace tool: inspect read README.md"]
        and render_preview_detail_line("last shell", "inspect/e0 git status --short -> M README.md")
        == ["- last shell: inspect/e0 git status --short -> M README.md"]
        and render_preview_detail_line("last prompt", "") == [],
    )
    print(
        "summary_row_detail_suffixes=",
        render_row_detail_suffix("pending queue", "first test; rest edit 1, tool 1")
        == " | pending queue: first test; rest edit 1, tool 1"
        and render_row_detail_suffix("pending age", "45d") == " | pending age: 45d"
        and render_row_detail_suffix("last denied age", "9h") == " | last denied age: 9h"
        and render_row_detail_suffix("approval restore queue", "first test; rest edit 1, tool 1")
        == " | approval restore queue: first test; rest edit 1, tool 1"
        and render_row_detail_suffix("last intervention", "approved queued edit")
        == " | last intervention: approved queued edit"
        and render_row_detail_suffix("last prompt", "review demo") == " | last prompt: review demo"
        and render_row_detail_suffix("last workspace tool", "inspect read README.md")
        == " | last workspace tool: inspect read README.md"
        and render_row_detail_suffix("last shell", "inspect/e0 git status --short -> M README.md")
        == " | last shell: inspect/e0 git status --short -> M README.md"
        and render_row_detail_suffix("last prompt", "") == "",
    )
    print(
        "summary_preview_badged_lines=",
        render_preview_badges_line("pending tools", ["test", "edit"])
        == ["- pending tools: test, edit"]
        and render_preview_badges_line("approval focus", ["approved", "restored"], separator="/")
        == ["- approval focus: approved/restored"]
        and render_badged_preview_line(
            "last tool",
            "git status --short -> M README.md",
            ["inspect", "e0"],
        )
        == ["- last tool: inspect/e0 git status --short -> M README.md"]
        and render_badged_preview_line("last tool", "", ["inspect", "e0"]) == ["- last tool: inspect/e0"]
        and render_badged_preview_line("last tool", "git status --short", [])
        == ["- last tool: git status --short"]
        and render_badged_preview_line("last tool", "", []) == [],
    )
    print(
        "summary_row_badged_suffixes=",
        render_row_badges_suffix("pending tools", ["test", "edit"]) == " | pending tools: test, edit"
        and render_row_badges_suffix("approval focus", ["approved", "restored"], separator="/")
        == " | approval focus: approved/restored"
        and render_badged_row_suffix(
            "last tool",
            "git status --short -> M README.md",
            ["inspect", "e0"],
        )
        == " | last tool: inspect/e0 git status --short -> M README.md"
        and render_badged_row_suffix("last tool", "", ["inspect", "e0"]) == " | last tool: inspect/e0"
        and render_badged_row_suffix("last tool", "git status --short", [])
        == " | last tool: git status --short"
        and render_badged_row_suffix("last tool", "", []) == "",
    )
    print(
        "summary_row_assembly=",
        render_recent_session_summary_line(
            index=2,
            session_id="session-02",
            turn_count=3,
            updated_at="2026-05-13 08:00 UTC",
            suffixes=[
                " | pending: run_shell_command",
                "",
                " | last prompt: review demo",
                " | last tool: inspect/e0 git status --short -> M README.md",
            ],
        )
        == "2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC | pending: run_shell_command | last prompt: review demo | last tool: inspect/e0 git status --short -> M README.md"
        and render_recent_session_list_row(
            marker=">",
            summary_line="2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC | pending: run_shell_command | last prompt: review demo | last tool: inspect/e0 git status --short -> M README.md",
        )
        == "> 2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC | pending: run_shell_command | last prompt: review demo | last tool: inspect/e0 git status --short -> M README.md"
        and render_recent_session_list_row(
            marker=" ",
            summary_line="2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC | pending: run_shell_command | last prompt: review demo | last tool: inspect/e0 git status --short -> M README.md",
            is_current=True,
        )
        == "  2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC | pending: run_shell_command | last prompt: review demo | last tool: inspect/e0 git status --short -> M README.md (current)",
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
