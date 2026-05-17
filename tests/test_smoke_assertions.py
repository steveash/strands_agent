from textwrap import dedent

from strands_agent_tui.testing import (
    matches_approval_restore_age_output,
    matches_approval_restore_badges_output,
    matches_approval_restore_focus_output,
    matches_approval_restore_overlap_output,
    matches_approval_restore_overlap_preview_split_output,
    matches_approval_restore_page_rollup_output,
    matches_approval_restore_preview_split_output,
    matches_approval_restore_tool_badges_output,
    matches_broad_approval_stale_output,
    matches_broad_stale_row_focus_suppression,
    matches_compact_stale_preview_output,
    matches_custom_stale_cutoff_output,
    matches_stale_backlog_output,
    matches_stale_cutoff_output,
    matches_stale_denied_subfilter_output,
    matches_stale_lane_focus_output,
    matches_stale_page_rollup_output,
    matches_stale_pending_subfilter_output,
    matches_stale_restored_subfilter_output,
    smoke_text_matches,
)


def test_smoke_text_matches_supports_required_and_excluded_snippets() -> None:
    assert smoke_text_matches("alpha beta gamma", required=["alpha", "gamma"], excluded=["delta"])
    assert not smoke_text_matches("alpha beta gamma", required=["alpha", "delta"])
    assert not smoke_text_matches("alpha beta gamma", excluded=["beta"])


def test_approval_restore_smoke_helpers_share_focus_age_and_preview_checks() -> None:
    text = dedent(
        """
        Filter: approval-restore | Sort: recent
        Approval restore backlog: 3 sessions | lanes: restore queue 2 (oldest 3d @ 2026-05-17 00:00 UTC), restored 1 (oldest 6h @ 2026-05-17 03:00 UTC)
        Restore lane focus: restore queue, restored
        > 1. session-restored-pending | 1 turn(s)
          2. session-restored-edit-pending | 1 turn(s)
          3. session-denied | 1 turn(s)
        | approval restore: pending 1 | approval restore: denied 1
        | approval restore tools: test 1 | approval restore tools: edit 1
        | approval restore age: restore queue 3d | approval restore age: restored 6h
        - restored current approval: pending run_shell_command via fake_runtime | queued 1
        - latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0
        """
    ).strip()

    assert matches_approval_restore_focus_output(
        text,
        required_session_ids=[
            "session-restored-pending",
            "session-restored-edit-pending",
            "session-denied",
        ],
        excluded_session_ids=["session-restore"],
    )
    assert matches_approval_restore_badges_output(text)
    assert matches_approval_restore_tool_badges_output(text)
    assert matches_approval_restore_age_output(text)
    assert matches_approval_restore_preview_split_output(text)


def test_approval_restore_overlap_and_rollup_helpers_share_timestamped_backlog_checks() -> None:
    overlap_text = dedent(
        """
        Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d @ 2026-05-17 00:00 UTC), restored 1 (oldest 6h @ 2026-05-17 03:00 UTC) | overlap: mixed 1 session
        Restore lane focus: restore queue, restored
        | approval restore ages: restore queue 3d; restored 6h
        restored current: pending run_shell_command via fake_runtime; queued 1
        restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0
        - restored current approval: pending run_shell_command via fake_runtime | queued 1
        - latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0
        """
    ).strip()
    first_page_text = dedent(
        """
        Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d @ 2026-05-01 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | overlap: mixed 1 session
        This page restore lanes: restore queue 8 (oldest 18d @ 2026-05-01 00:00 UTC) | more off-page: restore queue 1 (oldest 3d @ 2026-05-14 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | overlap here/off-page: none / mixed 1 session
        """
    ).strip()
    second_page_text = dedent(
        """
        This page restore lanes: restore queue 1 (oldest 3d @ 2026-05-14 00:00 UTC), restored 2 (oldest 8h @ 2026-05-17 01:00 UTC) | more off-page: restore queue 8 (oldest 18d @ 2026-05-01 00:00 UTC) | overlap here/off-page: mixed 1 session / none
        """
    ).strip()

    assert matches_approval_restore_overlap_output(overlap_text)
    assert matches_approval_restore_overlap_preview_split_output(overlap_text)
    assert matches_approval_restore_page_rollup_output(first_page_text, second_page_text)


def test_broad_stale_helpers_share_filter_backlog_cutoff_and_focus_checks() -> None:
    text = dedent(
        """
        Filter: approval-stale | Sort: attention
        Stale approval backlog: 1 session | lanes: pending 1 (oldest 45d @ 2026-04-02 00:00 UTC)
        Stale cutoff: approvals >= 7d old
        Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old
        > 1. session-aged | 1 turn(s) | approval stale age: pending 45d
        - approval stale age: pending 45d
        """
    ).strip()

    assert matches_broad_approval_stale_output(
        text,
        required_session_ids=["session-aged"],
        excluded_session_ids=["session-newer"],
        sort_mode="attention",
    )
    assert matches_stale_backlog_output(text)
    assert matches_stale_cutoff_output(text)
    assert matches_stale_lane_focus_output(text)
    assert matches_compact_stale_preview_output(text)
    assert matches_broad_stale_row_focus_suppression(text)


def test_stale_rollup_subfilter_and_custom_cutoff_helpers_share_smoke_copy() -> None:
    stale_first_page_text = dedent(
        """
        This page stale lanes: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC) | more off-page: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC)
        """
    ).strip()
    stale_second_page_text = dedent(
        """
        This page stale lanes: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC), restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC) | more off-page: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC)
        """
    ).strip()
    pending_text = dedent(
        """
        Filter: approval-stale-pending | Sort: recent
        Stale pending backlog: 8 sessions | lanes: pending 8 (oldest 52d @ 2026-03-26 00:00 UTC)
        Stale lane focus: pending | cutoff: approvals >= 7d old
        - stale lane focus: pending | cutoff: approvals >= 7d old
        > 1. session-stale-pending-0 | 1 turn(s) | approvals: pending 1 | approval focus: pending | approval stale age: 45d | stale focus: pending | intervention: pending 1
        - stale focus: pending
        - approvals: pending 1
        - approval focus: pending
        - approval stale age: 45d
        """
    ).strip()
    denied_text = dedent(
        """
        Filter: approval-stale-denied | Sort: recent
        Stale denied backlog: 1 session | lanes: denied 1 (oldest 14d @ 2026-05-03 00:00 UTC)
        Stale lane focus: denied | cutoff: approvals >= 7d old
        - stale lane focus: denied | cutoff: approvals >= 7d old
        > 1. session-stale-denied-page-2 | 1 turn(s) | approvals: denied 1 | approval focus: denied/fresh | denied age: 14d | approval stale age: 14d | stale focus: denied | intervention: denied 1
        - stale focus: denied
        - approvals: denied 1
        - approval focus: denied/fresh
        - approval stale age: 14d
        """
    ).strip()
    restored_text = dedent(
        """
        Filter: approval-stale-restored | Sort: recent
        Stale restored backlog: 1 session | lanes: restore queue 1 (oldest 11d @ 2026-05-06 00:00 UTC), restored 1 (oldest 10d @ 2026-05-07 00:00 UTC)
        Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old
        - stale lane focus: restore queue, restored | cutoff: approvals >= 7d old
        > 1. session-stale-restored-page-2 | 1 turn(s) | approvals: pending 1, approved 1 | approval focus: pending/restored | approval restore: pending 1, approved 1 | approval restore tools: test 1, edit 1 | approval restore age: 11d | approval stale ages: restore queue 11d; restored 10d | stale focus: restore queue, restored | intervention: pending 1, approved 1, restored 1
        restored current: pending write_file via fake_runtime; queued 1
        restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0
        restored outcome age: 10d
        - stale focus: restore queue, restored
        - approvals: pending 1, approved 1
        - approval focus: pending/restored
        - approval restore: pending 1, approved 1
        - approval restore age: 11d
        - approval stale ages: restore queue 11d; restored 10d
        - restored current approval: pending write_file via fake_runtime | queued 1
        - latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0
        - latest restored outcome age: 10d
        """
    ).strip()
    custom_cutoff_text = dedent(
        """
        Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d @ 2026-05-15 00:00 UTC)
        session-custom-threshold | 1 turn(s)
        Stale cutoff: approvals >= 1d old
        Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old
        """
    ).strip()

    assert matches_stale_page_rollup_output(stale_first_page_text, stale_second_page_text)
    assert matches_stale_pending_subfilter_output(
        pending_text,
        required_session_ids=["session-stale-pending-0"],
        excluded_session_ids=["session-stale-denied-page-2"],
    )
    assert matches_stale_denied_subfilter_output(
        denied_text,
        required_session_ids=["session-stale-denied-page-2"],
        excluded_session_ids=["session-stale-restored-page-2"],
    )
    assert matches_stale_restored_subfilter_output(
        restored_text,
        required_session_ids=["session-stale-restored-page-2"],
        excluded_session_ids=["session-stale-denied-page-2"],
    )
    assert matches_custom_stale_cutoff_output(custom_cutoff_text)
