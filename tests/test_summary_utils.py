import pytest

from strands_agent_tui.sessions.summary_utils import (
    render_backlog_metric_summary_line,
    render_backlog_summary_line,
    render_badged_preview_line,
    render_badged_row_suffix,
    render_compact_badge_preview_lines,
    render_compact_badge_row_suffix,
    render_filter_focus_line,
    render_lane_focus_preview_lines,
    render_lane_focus_suffix,
    render_lane_label_list,
    render_numbered_preview_section_lines,
    render_page_label,
    render_page_metric_summary_line,
    render_page_lane_summary_line,
    render_page_window_label,
    render_recent_session_filter_summary_block_lines,
    render_recent_session_metric_summary_block_lines,
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


@pytest.mark.parametrize(
    ("lanes", "expected_suffix", "expected_preview"),
    [
        (
            ["restore queue", "restored"],
            " | restore focus: restore queue, restored",
            ["- restore focus: restore queue, restored"],
        ),
        ([], "", []),
    ],
)
def test_render_lane_focus_helpers_share_row_and_preview_wording(
    lanes: list[str],
    expected_suffix: str,
    expected_preview: list[str],
) -> None:
    assert render_lane_label_list(lanes) == ", ".join(lanes)
    assert render_lane_focus_suffix("restore focus", lanes) == expected_suffix
    assert render_lane_focus_preview_lines("restore focus", lanes) == expected_preview
    assert render_lane_focus_preview_lines("restore focus", lanes, include=False) == []


@pytest.mark.parametrize(
    ("count", "lane_rollup", "overlap_summary", "expected"),
    [
        (1, "", "", "Shell backlog: 1 session"),
        (
            10,
            "restore queue 9 (oldest 18d), restored 2 (oldest 8h)",
            "mixed 1 session",
            "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d), restored 2 "
            "(oldest 8h) | overlap: mixed 1 session",
        ),
    ],
)
def test_render_backlog_summary_line_handles_singular_plural_and_optional_segments(
    count: int,
    lane_rollup: str,
    overlap_summary: str,
    expected: str,
) -> None:
    assert render_backlog_summary_line(
        "Approval restore backlog" if count > 1 else "Shell backlog",
        count,
        lane_rollup=lane_rollup,
        overlap_summary=overlap_summary,
    ) == expected


@pytest.mark.parametrize(
    ("count", "metrics", "expected"),
    [
        (1, [], "Pending approval backlog: 1 session"),
        (
            3,
            ["approvals: 4", "families: test 2, edit 2", "restored queues: 1 session"],
            "Pending approval backlog: 3 sessions | approvals: 4 | families: test 2, edit 2 | restored queues: 1 session",
        ),
    ],
)
def test_render_backlog_metric_summary_line_handles_optional_metrics(
    count: int,
    metrics: list[str],
    expected: str,
) -> None:
    assert render_backlog_metric_summary_line("Pending approval backlog", count, metrics) == expected


def test_render_filter_focus_line_supports_cutoff_and_empty_lanes() -> None:
    assert render_filter_focus_line("Restore lane focus", ["restore queue", "restored"]) == (
        "Restore lane focus: restore queue, restored"
    )
    assert render_filter_focus_line(
        "Pending focus",
        ["fresh", "restored"],
        oldest="2d",
        oldest_at="2026-05-14 04:00 UTC",
    ) == "Pending focus: fresh, restored | oldest: 2d | oldest at: 2026-05-14 04:00 UTC"
    assert render_filter_focus_line(
        "Stale lane focus",
        ["pending", "denied"],
        cutoff="approvals >= 7d old",
    ) == "Stale lane focus: pending, denied | cutoff: approvals >= 7d old"
    assert render_filter_focus_line("Shell focus", []) == "Shell focus: none"


@pytest.mark.parametrize(
    ("off_page_rollup", "visible_overlap_summary", "off_page_overlap_summary", "expected"),
    [
        (
            "",
            "",
            "",
            "This page stale lanes: pending 2 (oldest 14d)",
        ),
        (
            "restore queue 1 (oldest 3d), restored 2 (oldest 8h)",
            "none",
            "mixed 1 session",
            "This page restore lanes: restore queue 8 (oldest 18d) | more off-page: restore queue 1 "
            "(oldest 3d), restored 2 (oldest 8h) | overlap here/off-page: none / mixed 1 session",
        ),
    ],
)
def test_render_page_lane_summary_line_handles_optional_rollups_and_overlap(
    off_page_rollup: str,
    visible_overlap_summary: str,
    off_page_overlap_summary: str,
    expected: str,
) -> None:
    assert render_page_lane_summary_line(
        "stale lanes" if not off_page_rollup else "restore lanes",
        "pending 2 (oldest 14d)" if not off_page_rollup else "restore queue 8 (oldest 18d)",
        off_page_rollup=off_page_rollup,
        visible_overlap_summary=visible_overlap_summary,
        off_page_overlap_summary=off_page_overlap_summary,
    ) == expected


def test_render_page_metric_summary_line_handles_visible_and_off_page_metrics() -> None:
    assert render_page_metric_summary_line(
        "pending queues",
        ["approvals: 8", "families: test 7, edit 1"],
        off_page_metrics=["approvals: 2", "families: edit 1, tool 1", "restored queues: 1 session"],
    ) == (
        "This page pending queues: approvals: 8 | families: test 7, edit 1 | more off-page: approvals: 2 | "
        "families: edit 1, tool 1 | restored queues: 1 session"
    )
    assert render_page_metric_summary_line("denied approvals", []) == "This page denied approvals: none"


def test_render_recent_session_metric_summary_block_lines_supports_oldest_timestamps() -> None:
    assert render_recent_session_metric_summary_block_lines(
        backlog_label="Pending approval backlog",
        count=2,
        backlog_metrics=["approvals: 3"],
        focus_label="Pending focus",
        focus_lanes=["fresh", "restored"],
        oldest="2d",
        oldest_at="2026-05-14 04:00 UTC",
    ) == [
        "Pending approval backlog: 2 sessions | approvals: 3",
        "Pending focus: fresh, restored | oldest: 2d | oldest at: 2026-05-14 04:00 UTC",
    ]


def test_render_recent_session_page_banner_helpers_share_page_math() -> None:
    assert render_page_label(10, 8, 1) == "2/2"
    assert render_page_label(0, 8, 0) == "0/0"
    assert render_page_window_label(10, 8, 1, 2) == "9-10 of 10"
    assert render_page_window_label(0, 8, 0, 0) == "0 of 0"
    assert render_recent_session_page_banner(
        filter_mode="approval-stale",
        sort_mode="attention",
        total_matches=10,
        page_size=8,
        page_index=1,
        visible_count=2,
        stale_cutoff_suffix=" | Stale cutoff: approvals >= 7d old",
    ) == (
        "Filter: approval-stale | Sort: attention | Stale cutoff: approvals >= 7d old | "
        "Page: 2/2 | Showing: 9-10 of 10"
    )


def test_render_selected_session_preview_header_lines_share_slot_and_artifact_copy() -> None:
    assert render_selected_session_preview_header_lines(
        visible_index=2,
        overall_index=10,
        total_matches=11,
        session_id="session-01",
        session_dir="/tmp/sessions/session-01",
    ) == [
        "Selected preview:",
        "- slot 2 on this page | overall 10 of 11 | session session-01",
        "- artifact dir: /tmp/sessions/session-01",
    ]


@pytest.mark.parametrize(
    (
        "kwargs",
        "expected",
    ),
    [
        (
            {
                "backlog_label": "Approval restore backlog",
                "count": 10,
                "focus_label": "Restore lane focus",
                "focus_lanes": ["restore queue", "restored"],
                "lane_rollup": "restore queue 9 (oldest 18d), restored 2 (oldest 8h)",
                "overlap_summary": "mixed 1 session",
                "page_lane_label": "restore lanes",
                "visible_rollup": "restore queue 8 (oldest 18d)",
                "off_page_rollup": "restore queue 1 (oldest 3d), restored 2 (oldest 8h)",
                "visible_overlap_summary": "none",
                "off_page_overlap_summary": "mixed 1 session",
            },
            [
                "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d), restored 2 (oldest 8h) | overlap: mixed 1 session",
                "Restore lane focus: restore queue, restored",
                "This page restore lanes: restore queue 8 (oldest 18d) | more off-page: restore queue 1 (oldest 3d), restored 2 (oldest 8h) | overlap here/off-page: none / mixed 1 session",
            ],
        ),
        (
            {
                "backlog_label": "Workspace backlog",
                "count": 2,
                "focus_label": "Workspace focus",
                "focus_lanes": ["inspect"],
                "lane_rollup": "inspect 2, edit 1",
                "overlap_summary": "mixed 1 session",
            },
            [
                "Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
                "Workspace focus: inspect",
            ],
        ),
        (
            {
                "backlog_label": "Shell backlog",
                "count": 3,
                "focus_label": "Shell focus",
                "focus_lanes": ["inspect", "test"],
                "lane_rollup": "inspect 2, test 2",
                "overlap_summary": "mixed 1 session",
                "page_lane_label": "shell lanes",
                "visible_rollup": "inspect 1, test 1",
                "off_page_rollup": "inspect 1, test 1",
                "visible_overlap_summary": "mixed 1 session",
                "off_page_overlap_summary": "none",
            },
            [
                "Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session",
                "Shell focus: inspect, test",
                "This page shell lanes: inspect 1, test 1 | more off-page: inspect 1, test 1 | overlap here/off-page: mixed 1 session / none",
            ],
        ),
        (
            {
                "backlog_label": "Stale denied backlog",
                "count": 4,
                "focus_label": "Stale lane focus",
                "focus_lanes": ["denied"],
                "lane_rollup": "denied 4 (oldest 12d)",
                "cutoff": "approvals >= 7d old",
                "page_lane_label": "stale lanes",
                "visible_rollup": "denied 2 (oldest 12d)",
                "off_page_rollup": "denied 2 (oldest 8d)",
            },
            [
                "Stale denied backlog: 4 sessions | lanes: denied 4 (oldest 12d)",
                "Stale lane focus: denied | cutoff: approvals >= 7d old",
                "This page stale lanes: denied 2 (oldest 12d) | more off-page: denied 2 (oldest 8d)",
            ],
        ),
    ],
)
def test_render_recent_session_filter_summary_block_lines_share_filter_backlog_copy(
    kwargs: dict[str, object],
    expected: list[str],
) -> None:
    assert render_recent_session_filter_summary_block_lines(**kwargs) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "backlog_label": "Pending approval backlog",
                "count": 3,
                "backlog_metrics": [
                    "approvals: 4",
                    "families: test 2, edit 2",
                    "multi-queue: 1 session",
                    "restored queues: 1 session",
                ],
                "focus_label": "Pending focus",
                "focus_lanes": ["fresh", "restored"],
                "oldest": "2d",
                "page_metric_label": "pending queues",
                "visible_metrics": [
                    "approvals: 3",
                    "families: test 2, edit 1",
                    "multi-queue: 1 session",
                ],
                "off_page_metrics": [
                    "approvals: 1",
                    "families: edit 1",
                    "restored queues: 1 session",
                ],
            },
            [
                "Pending approval backlog: 3 sessions | approvals: 4 | families: test 2, edit 2 | multi-queue: 1 session | restored queues: 1 session",
                "Pending focus: fresh, restored | oldest: 2d",
                "This page pending queues: approvals: 3 | families: test 2, edit 1 | multi-queue: 1 session | more off-page: approvals: 1 | families: edit 1 | restored queues: 1 session",
            ],
        ),
        (
            {
                "backlog_label": "Denied approval backlog",
                "count": 2,
                "backlog_metrics": ["approvals: 2", "families: test 1, edit 1"],
                "focus_label": "Denied focus",
                "focus_lanes": ["fresh"],
                "oldest": "9h",
            },
            [
                "Denied approval backlog: 2 sessions | approvals: 2 | families: test 1, edit 1",
                "Denied focus: fresh | oldest: 9h",
            ],
        ),
    ],
)
def test_render_recent_session_metric_summary_block_lines_share_metric_backlog_copy(
    kwargs: dict[str, object],
    expected: list[str],
) -> None:
    assert render_recent_session_metric_summary_block_lines(**kwargs) == expected


def test_render_numbered_preview_section_lines_share_recent_preview_section_copy() -> None:
    assert render_numbered_preview_section_lines(
        "recent interventions",
        ["approve queued edit", "deny shell rerun"],
    ) == [
        "- recent interventions (2):",
        "  1. approve queued edit",
        "  2. deny shell rerun",
    ]
    assert render_numbered_preview_section_lines(
        "recent tools",
        ["inspect/e0 git status --short -> M README.md"],
    ) == [
        "- recent tools (1):",
        "  1. inspect/e0 git status --short -> M README.md",
    ]
    assert render_numbered_preview_section_lines(
        "recent workspace tools",
        ["inspect read README.md", "edit write report.md"],
    ) == [
        "- recent workspace tools (2):",
        "  1. inspect read README.md",
        "  2. edit write report.md",
    ]
    assert render_numbered_preview_section_lines(
        "recent shell outcomes",
        ["confirm/e1 pytest -q -> exit 1"],
    ) == [
        "- recent shell outcomes (1):",
        "  1. confirm/e1 pytest -q -> exit 1",
    ]
    assert render_numbered_preview_section_lines("recent tools", []) == []


def test_render_selected_preview_section_lines_share_group_assembly_for_preview_subsections() -> None:
    assert render_selected_preview_section_lines(
        render_preview_detail_line("pending", "2 approvals | first: run_shell_command"),
        render_preview_detail_line("pending queue", "first test; rest edit 1"),
        render_preview_detail_line("pending age", "45d"),
        render_preview_badges_line("pending tools", ["test", "edit"]),
        render_preview_badges_line("approvals", ["pending 2", "approved 1"]),
        render_preview_detail_line("approval focus", "pending/restored"),
        render_preview_detail_line("last approval", "pending run_shell_command via fake_runtime | queued 2"),
        render_preview_badges_line("denied", ["edit 1"]),
        render_preview_detail_line("last denied approval", "denied replace_text via fake_runtime | fresh request"),
        render_preview_detail_line("last denied age", "9h"),
        render_preview_badges_line("approval restore", ["pending 1", "approved 1"]),
        render_preview_badges_line("approval restore tools", ["test 1", "edit 1"]),
        render_preview_detail_line("approval restore queue", "first test; rest edit 1"),
        ["- approval restore age: 3d"],
        render_preview_detail_line(
            "restored current approval",
            "pending run_shell_command via fake_runtime | queued 1",
        ),
        render_preview_detail_line(
            "latest restored outcome",
            "approved replace_text via fake_runtime | restored queue | queued 1",
        ),
        render_preview_detail_line("latest restored outcome age", "6h"),
        ["- stale focus: pending", "- approval stale age: 45d"],
    ) == [
        "- pending: 2 approvals | first: run_shell_command",
        "- pending queue: first test; rest edit 1",
        "- pending age: 45d",
        "- pending tools: test, edit",
        "- approvals: pending 2, approved 1",
        "- approval focus: pending/restored",
        "- last approval: pending run_shell_command via fake_runtime | queued 2",
        "- denied: edit 1",
        "- last denied approval: denied replace_text via fake_runtime | fresh request",
        "- last denied age: 9h",
        "- approval restore: pending 1, approved 1",
        "- approval restore tools: test 1, edit 1",
        "- approval restore queue: first test; rest edit 1",
        "- approval restore age: 3d",
        "- restored current approval: pending run_shell_command via fake_runtime | queued 1",
        "- latest restored outcome: approved replace_text via fake_runtime | restored queue | queued 1",
        "- latest restored outcome age: 6h",
        "- stale focus: pending",
        "- approval stale age: 45d",
    ]
    assert render_selected_preview_section_lines(
        render_preview_badges_line("intervention", ["pending 2", "restored 1"]),
        render_preview_detail_line("last intervention", "approved queued edit"),
        render_numbered_preview_section_lines(
            "recent interventions",
            ["approve queued edit", "deny shell rerun"],
        ),
    ) == [
        "- intervention: pending 2, restored 1",
        "- last intervention: approved queued edit",
        "- recent interventions (2):",
        "  1. approve queued edit",
        "  2. deny shell rerun",
    ]
    assert render_selected_preview_section_lines(
        render_badged_preview_line(
            "last tool",
            "git status --short -> M README.md",
            ["inspect", "e0"],
        ),
        render_numbered_preview_section_lines(
            "recent tools",
            ["inspect/e0 git status --short -> M README.md"],
        ),
    ) == [
        "- last tool: inspect/e0 git status --short -> M README.md",
        "- recent tools (1):",
        "  1. inspect/e0 git status --short -> M README.md",
    ]
    assert render_selected_preview_section_lines(
        render_preview_badges_line("workspace lanes", ["inspect", "edit"]),
        render_preview_detail_line("last workspace tool", "inspect read README.md"),
        render_numbered_preview_section_lines(
            "recent workspace tools",
            ["inspect read README.md", "edit write report.md"],
        ),
    ) == [
        "- workspace lanes: inspect, edit",
        "- last workspace tool: inspect read README.md",
        "- recent workspace tools (2):",
        "  1. inspect read README.md",
        "  2. edit write report.md",
    ]
    assert render_selected_preview_section_lines(
        render_preview_badges_line("shell", ["inspect 1", "test 2"]),
        render_preview_badges_line("shell lanes", ["inspect", "test"]),
        render_preview_badges_line("failures", ["test 1"]),
        render_preview_detail_line("last shell", "confirm/e1 pytest -q -> exit 1"),
        render_numbered_preview_section_lines(
            "recent shell outcomes",
            ["confirm/e1 pytest -q -> exit 1"],
        ),
    ) == [
        "- shell: inspect 1, test 2",
        "- shell lanes: inspect, test",
        "- failures: test 1",
        "- last shell: confirm/e1 pytest -q -> exit 1",
        "- recent shell outcomes (1):",
        "  1. confirm/e1 pytest -q -> exit 1",
    ]


def test_render_selected_session_preview_lines_share_composite_preview_assembly() -> None:
    assert render_selected_session_preview_lines(
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
    ) == [
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
    ]


def test_render_preview_detail_helpers_share_single_line_selected_preview_copy() -> None:
    assert render_preview_detail_line("pending queue", "first test; rest edit 1, tool 1") == [
        "- pending queue: first test; rest edit 1, tool 1"
    ]
    assert render_preview_detail_line("pending age", "45d") == ["- pending age: 45d"]
    assert render_preview_detail_line("last denied age", "9h") == ["- last denied age: 9h"]
    assert render_preview_detail_line("approval restore queue", "first test; rest edit 1, tool 1") == [
        "- approval restore queue: first test; rest edit 1, tool 1"
    ]
    assert render_preview_detail_line("last intervention", "approved queued edit") == [
        "- last intervention: approved queued edit"
    ]
    assert render_preview_detail_line("last prompt", "review demo") == ["- last prompt: review demo"]
    assert render_preview_detail_line("last workspace tool", "inspect read README.md") == [
        "- last workspace tool: inspect read README.md"
    ]
    assert render_preview_detail_line("last shell", "inspect/e0 git status --short -> M README.md") == [
        "- last shell: inspect/e0 git status --short -> M README.md"
    ]
    assert render_preview_detail_line("last prompt", "") == []


def test_render_row_detail_helpers_share_single_line_recent_session_row_copy() -> None:
    assert render_row_detail_suffix("pending queue", "first test; rest edit 1, tool 1") == (
        " | pending queue: first test; rest edit 1, tool 1"
    )
    assert render_row_detail_suffix("pending age", "45d") == " | pending age: 45d"
    assert render_row_detail_suffix("last denied age", "9h") == " | last denied age: 9h"
    assert render_row_detail_suffix("approval restore queue", "first test; rest edit 1, tool 1") == (
        " | approval restore queue: first test; rest edit 1, tool 1"
    )
    assert render_row_detail_suffix("last intervention", "approved queued edit") == (
        " | last intervention: approved queued edit"
    )
    assert render_row_detail_suffix("last prompt", "review demo") == " | last prompt: review demo"
    assert render_row_detail_suffix("last workspace tool", "inspect read README.md") == (
        " | last workspace tool: inspect read README.md"
    )
    assert render_row_detail_suffix("last shell", "inspect/e0 git status --short -> M README.md") == (
        " | last shell: inspect/e0 git status --short -> M README.md"
    )
    assert render_row_detail_suffix("last prompt", "") == ""


def test_render_preview_badges_and_badged_value_helpers_share_single_line_preview_copy() -> None:
    assert render_preview_badges_line("pending tools", ["test", "edit"]) == ["- pending tools: test, edit"]
    assert render_preview_badges_line("approval focus", ["approved", "restored"], separator="/") == [
        "- approval focus: approved/restored"
    ]
    assert render_badged_preview_line(
        "last tool",
        "git status --short -> M README.md",
        ["inspect", "e0"],
    ) == ["- last tool: inspect/e0 git status --short -> M README.md"]
    assert render_badged_preview_line("last tool", "", ["inspect", "e0"]) == [
        "- last tool: inspect/e0"
    ]
    assert render_badged_preview_line("last tool", "git status --short", []) == [
        "- last tool: git status --short"
    ]
    assert render_badged_preview_line("last tool", "", []) == []


def test_render_row_badges_and_badged_value_helpers_share_single_line_row_copy() -> None:
    assert render_row_badges_suffix("pending tools", ["test", "edit"]) == " | pending tools: test, edit"
    assert render_row_badges_suffix("approval focus", ["approved", "restored"], separator="/") == (
        " | approval focus: approved/restored"
    )
    assert render_badged_row_suffix(
        "last tool",
        "git status --short -> M README.md",
        ["inspect", "e0"],
    ) == " | last tool: inspect/e0 git status --short -> M README.md"
    assert render_badged_row_suffix("last tool", "", ["inspect", "e0"]) == " | last tool: inspect/e0"
    assert render_badged_row_suffix("last tool", "git status --short", []) == " | last tool: git status --short"
    assert render_badged_row_suffix("last tool", "", []) == ""


def test_render_recent_session_row_helpers_share_composite_row_assembly() -> None:
    summary_line = render_recent_session_summary_line(
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
    assert summary_line == (
        "2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC"
        " | pending: run_shell_command"
        " | last prompt: review demo"
        " | last tool: inspect/e0 git status --short -> M README.md"
    )
    assert render_recent_session_list_row(marker=">", summary_line=summary_line) == (
        "> 2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC"
        " | pending: run_shell_command"
        " | last prompt: review demo"
        " | last tool: inspect/e0 git status --short -> M README.md"
    )
    assert render_recent_session_list_row(marker=" ", summary_line=summary_line, is_current=True) == (
        "  2. session-02 | 3 turn(s) | updated 2026-05-13 08:00 UTC"
        " | pending: run_shell_command"
        " | last prompt: review demo"
        " | last tool: inspect/e0 git status --short -> M README.md (current)"
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


def test_render_compact_badge_preview_lines_fall_back_to_default_when_unfocused() -> None:
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


def test_render_compact_badge_row_suffix_falls_back_to_default_when_unfocused() -> None:
    assert render_compact_badge_row_suffix(
        default_suffix=" | approval stale age: 45d",
        focused_badges=[],
        singular_label="approval stale age",
        plural_label="approval stale ages",
        singular_value_transform=lambda badge: badge,
    ) == " | approval stale age: 45d"


@pytest.mark.parametrize(
    ("surface", "filter_mode", "available_count", "expected"),
    [
        (
            "picker",
            "pending",
            1,
            [
                "No saved sessions match the active picker filter.",
                "1 saved session still exists under this root.",
                "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage.",
                "Press Enter or N to start a fresh session while keeping this picker context for the next reopen.",
            ],
        ),
        (
            "switcher",
            "pending",
            2,
            [
                "No saved sessions match the active switcher filter.",
                "2 saved sessions still exist under this root.",
                "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage.",
                "Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists.",
                "Enter switches the highlighted session once a visible row exists again.",
            ],
        ),
        (
            "picker",
            "all",
            0,
            [
                "No saved sessions match the active picker filter.",
                "0 saved sessions still exist under this root.",
                "Press Enter or N to start a fresh session while keeping this picker context for the next reopen.",
            ],
        ),
    ],
)
def test_render_recent_session_empty_state_lines_share_picker_and_switcher_guidance(
    surface: str,
    filter_mode: str,
    available_count: int,
    expected: list[str],
) -> None:
    assert render_recent_session_empty_state_lines(
        available_count=available_count,
        filter_mode=filter_mode,
        surface=surface,
    ) == expected


def test_render_picker_empty_filter_guidance_helpers_share_key_hints() -> None:
    assert render_recent_session_filter_jump_line() == (
        "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage."
    )
    assert render_picker_empty_filter_prompt() == (
        "No sessions match this filter. Press Enter or N for a new session, or use A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to change triage: "
    )
    assert render_picker_empty_filter_visible_guidance() == (
        "No sessions are visible with the active filter. Press A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to keep triaging; Enter or N starts a new session."
    )
    assert render_picker_empty_filter_adjust_guidance() == (
        "No sessions match the active filter. Use A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to adjust triage, or press Enter/N to start a new session."
    )


def test_render_recent_session_control_legend_helpers_share_picker_and_switcher_key_maps() -> None:
    assert render_picker_controls_line() == (
        "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, [ prev page, ] next page, N new session"
    )
    assert render_switcher_controls_line() == (
        "Keys: ↑/↓ or J/K move, PgUp/PgDn or bracket keys page, Enter switch, 1-8 quick switch, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, N new session, Esc/F11 cancel"
    )


def test_render_picker_selection_and_invalid_guidance_helpers_share_visible_range() -> None:
    assert render_picker_selection_prompt() == (
        "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to triage/page: "
    )
    assert render_picker_invalid_selection_message("9", 3) == (
        "Invalid selection: '9'. Choose 1-3 from the visible list, press Enter to reopen highlighted, or N for a new session."
    )
    assert render_picker_invalid_key_guidance(3) == (
        "Invalid selection. Use 1-3, J, K, A, P, D, R, V, O, Q, X, U, T, W, E, G, H, I, Y, S, [, ], Enter, or N."
    )
