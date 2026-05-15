from datetime import UTC, datetime, timedelta
from pathlib import Path

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import (
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionPickerState,
    SessionSummary,
    SessionState,
    TurnArtifact,
    count_recent_sessions,
    latest_session,
    list_recent_sessions,
    pick_session,
    render_session_picker,
    save_session_picker_state,
)
from strands_agent_tui.sessions.picker import (
    APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
    _approval_restore_lane_age_seconds,
    _approval_restore_lanes,
    _slice_visible_and_off_page_summaries,
    _summarize_lane_activity,
)
from strands_agent_tui.testing import (
    append_turn as _shared_append_turn,
    seed_approval_restore_overlap_session,
    seed_approval_restore_rollup_scenario,
    seed_denied_approval_rollup_scenario,
    seed_multi_approval_queue_session,
    seed_pending_approval_rollup_scenario,
    seed_stale_approval_filter_scenario,
    seed_stale_approval_rollup_scenario,
    seed_stale_approval_subfilter_scenario,
    set_session_artifact_mtime as _shared_set_session_artifact_mtime,
)


def _append_turn(store: SessionArtifactStore, prompt: str) -> None:
    _shared_append_turn(store, prompt, response="done")


def _set_session_artifact_mtime(store: SessionArtifactStore, when: datetime) -> None:
    _shared_set_session_artifact_mtime(store, when)


def _session_summary(session_id: str, **overrides: object):
    return SessionSummary(
        session_id=session_id,
        session_dir=Path(f"/tmp/{session_id}"),
        turn_count=1,
        updated_at="2026-05-14 04:00 UTC",
        **overrides,
    )


def test_summarize_lane_activity_shares_restore_counts_ages_and_overlap() -> None:
    mixed_summary = _session_summary(
        "session-mixed",
        restored_approval_badges=["pending 1", "approved 1"],
        restored_pending_approval_age_sort_key=int(timedelta(days=3).total_seconds()),
        last_restored_outcome_age_sort_key=int(timedelta(hours=6).total_seconds()),
    )
    restored_only_summary = _session_summary(
        "session-restored-only",
        restored_approval_badges=["approved 1"],
        last_restored_outcome_age_sort_key=int(timedelta(days=8).total_seconds()),
    )

    rollup = _summarize_lane_activity(
        [mixed_summary, restored_only_summary],
        display_order=APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
        lane_getter=_approval_restore_lanes,
        age_getter=_approval_restore_lane_age_seconds,
        include_mixed_count=True,
    )

    assert rollup.lane_counts == {"restore queue": 1, "restored": 2}
    assert rollup.lane_oldest_ages == {
        "restore queue": int(timedelta(days=3).total_seconds()),
        "restored": int(timedelta(days=8).total_seconds()),
    }
    assert rollup.mixed_count == 1


def test_slice_visible_and_off_page_summaries_clamps_page_index_and_preserves_order() -> None:
    summaries = [_session_summary(f"session-{index}") for index in range(5)]

    visible, off_page = _slice_visible_and_off_page_summaries(summaries, page_index=9, page_size=2)

    assert [summary.session_id for summary in visible] == ["session-4"]
    assert [summary.session_id for summary in off_page] == [
        "session-0",
        "session-1",
        "session-2",
        "session-3",
    ]


def test_list_recent_sessions_orders_by_latest_activity_and_includes_prompt_preview(tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    _append_turn(older_store, "inspect older repo state")

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="inspect newer repo state with a long prompt preview that should truncate cleanly",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    sessions = list_recent_sessions(tmp_path)

    assert [session.session_id for session in sessions[:2]] == ["session-newer", "session-older"]
    assert sessions[0].turn_count == 1
    assert sessions[0].last_prompt_preview.endswith("...")
    assert sessions[0].last_event_preview == "tool_finished: list_files"
    assert sessions[0].last_tool_preview == ".: README.md"
    assert "turn(s)" in sessions[0].render_line(1)
    assert "last tool: .: README.md" in sessions[0].render_line(1)
    assert "last event: tool_finished: list_files" in sessions[0].render_line(1)


def test_latest_session_returns_newest_summary(tmp_path: Path) -> None:
    first_store = SessionArtifactStore(tmp_path, session_id="session-a")
    _append_turn(first_store, "first")

    second_store = SessionArtifactStore(tmp_path, session_id="session-b")
    _append_turn(second_store, "second")

    summary = latest_session(tmp_path)

    assert summary is not None
    assert summary.session_id == "session-b"
    assert summary.session_dir == second_store.session_dir


def test_render_session_picker_lists_recent_sessions(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-demo")
    _append_turn(store, "review demo")

    rendered = render_session_picker(tmp_path)

    assert "Recent sessions under" in rendered
    assert "Filter: all | Sort: recent | Page: 1/1 | Showing: 1-1 of 1" in rendered
    assert "> 1. session-demo" in rendered
    assert "Selected preview:" in rendered
    assert "- slot 1 on this page | overall 1 of 1 | session session-demo" in rendered
    assert "- artifact dir:" in rendered
    assert "- last prompt: review demo" in rendered
    assert (
        "Picker controls: J/K preview, A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, [ prev page, ] next page, N new session"
        in rendered
    )
    assert "Press Enter to reopen the highlighted session." in rendered


def test_render_session_picker_supports_paged_views(tmp_path: Path) -> None:
    created_ids: list[str] = []
    for index in range(MAX_RECENT_SESSIONS + 2):
        session_id = f"session-{index:02d}"
        store = SessionArtifactStore(tmp_path, session_id=session_id)
        _append_turn(store, f"prompt {index}")
        created_ids.append(session_id)

    second_page = render_session_picker(tmp_path, page_index=1)

    assert "Page: 2/2 | Showing: 9-10 of 10" in second_page
    assert "> 1. session-01" in second_page
    assert "  2. session-00" in second_page
    assert "- slot 1 on this page | overall 9 of 10 | session session-01" in second_page
    assert "session-09" not in second_page


def test_pick_session_returns_selected_summary(tmp_path: Path) -> None:
    first_store = SessionArtifactStore(tmp_path, session_id="session-first")
    _append_turn(first_store, "first")

    second_store = SessionArtifactStore(tmp_path, session_id="session-second")
    _append_turn(second_store, "second")

    captured: list[str] = []
    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: "1",
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-second"
    assert any("Recent sessions under" in line for line in captured)


def test_pick_session_enter_reopens_highlighted_summary(tmp_path: Path) -> None:
    first_store = SessionArtifactStore(tmp_path, session_id="session-first")
    _append_turn(first_store, "first")

    second_store = SessionArtifactStore(tmp_path, session_id="session-second")
    _append_turn(second_store, "second")

    captured: list[str] = []
    inputs = iter(["j", ""])
    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: next(inputs),
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-first"
    assert any("> 2. session-first" in line for line in captured)


def test_pick_session_handles_empty_artifact_root(tmp_path: Path) -> None:
    captured: list[str] = []

    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: "",
        output_fn=captured.append,
    )

    assert summary is None
    assert captured[0].startswith("No saved sessions found under")
    assert captured[1] == "Starting a new session instead."


def test_render_session_picker_reports_no_matches_for_active_filter(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-demo")
    _append_turn(store, "review demo")

    rendered = render_session_picker(tmp_path, filter_mode="pending")

    assert "Filter: pending | Sort: recent" in rendered
    assert "No saved sessions match the active picker filter." in rendered
    assert "1 saved session still exists under this root." in rendered
    assert (
        "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage."
        in rendered
    )
    assert "Press Enter or N to start a fresh session while keeping this picker context for the next reopen." in rendered
    assert "1. session-demo" not in rendered


def test_render_session_picker_surfaces_workspace_rollups_and_overlap(tmp_path: Path) -> None:
    inspect_store = SessionArtifactStore(tmp_path, session_id="session-workspace-inspect")
    inspect_store.append_turn(
        TurnArtifact(
            prompt="inspect files",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    mixed_store = SessionArtifactStore(tmp_path, session_id="session-workspace-mixed")
    mixed_store.append_turn(
        TurnArtifact(
            prompt="inspect before editing",
            response="pending",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "read_file",
                    "Finished reading file",
                    data={"tool_name": "read_file", "result_preview": "README.md lines 1-20"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )
    mixed_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-workspace-mixed",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="apply the edit",
            )
        ]
    )

    edit_store = SessionArtifactStore(tmp_path, session_id="session-workspace-edit")
    _append_turn(edit_store, "queue edit")
    edit_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-workspace-edit",
                tool_name="replace_text",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "old_text": "old", "new_text": "new"},
                source="fake_runtime",
                prompt="queue replace_text",
            )
        ]
    )

    inspect_rendered = render_session_picker(tmp_path, filter_mode="workspace-inspect")
    edit_rendered = render_session_picker(tmp_path, filter_mode="workspace-edit")

    assert "Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session" in inspect_rendered
    assert "Workspace focus: inspect" in inspect_rendered
    assert "Workspace backlog: 2 sessions | lanes: inspect 1, edit 2 | overlap: mixed 1 session" in edit_rendered
    assert "Workspace focus: edit" in edit_rendered



def test_render_session_picker_surfaces_shell_rollups_and_overlap(tmp_path: Path) -> None:
    inspect_store = SessionArtifactStore(tmp_path, session_id="session-shell-inspect")
    inspect_store.append_turn(
        TurnArtifact(
            prompt="inspect shell state",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    mixed_store = SessionArtifactStore(tmp_path, session_id="session-shell-mixed-rollup")
    mixed_store.append_turn(
        TurnArtifact(
            prompt="inspect before rerunning tests",
            response="pending",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git diff --stat",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git diff --stat -> README.md | 2 +-",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )
    mixed_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-shell-mixed-rollup",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
            )
        ]
    )

    test_store = SessionArtifactStore(tmp_path, session_id="session-shell-test")
    _append_turn(test_store, "queue shell test")
    test_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-shell-test",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    shell_rendered = render_session_picker(tmp_path, filter_mode="shell")
    inspect_rendered = render_session_picker(tmp_path, filter_mode="shell-inspect")
    test_rendered = render_session_picker(tmp_path, filter_mode="shell-test")

    assert "Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session" in shell_rendered
    assert "Shell focus: inspect, test" in shell_rendered
    assert "Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session" in inspect_rendered
    assert "Shell focus: inspect" in inspect_rendered
    assert "Shell backlog: 2 sessions | lanes: inspect 1, test 2 | overlap: mixed 1 session" in test_rendered
    assert "Shell focus: test" in test_rendered


def test_render_session_picker_surfaces_pending_approval_backlog_summary(tmp_path: Path) -> None:
    fresh_store = SessionArtifactStore(tmp_path, session_id="session-pending-fresh")
    _append_turn(fresh_store, "rerun tests later")
    fresh_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-pending-fresh",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            )
        ]
    )

    restored_store = SessionArtifactStore(tmp_path, session_id="session-pending-restored")
    _append_turn(restored_store, "resume restored edit")
    restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-pending-restored",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
            )
        ]
    )

    multi_store = SessionArtifactStore(tmp_path, session_id="session-pending-multi")
    _append_turn(multi_store, "queue multiple follow-ups")
    multi_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-pending-multi-1",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="queue test",
                created_at=(datetime.now(UTC) - timedelta(hours=12)).isoformat(),
            ),
            ApprovalRequest(
                request_id="approval-pending-multi-2",
                tool_name="replace_text",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "old_text": "old", "new_text": "new"},
                source="fake_runtime",
                prompt="queue edit",
                created_at=(datetime.now(UTC) - timedelta(hours=11)).isoformat(),
            ),
        ]
    )

    rendered = render_session_picker(tmp_path, filter_mode="pending")

    assert (
        "Pending approval backlog: 3 sessions | approvals: 4 | families: test 2, edit 2 | multi-queue: 1 session | restored queues: 1 session"
        in rendered
    )
    assert "Pending focus: fresh, restored | oldest: 2d" in rendered


def test_render_session_picker_surfaces_denied_approval_backlog_summary(tmp_path: Path) -> None:
    fresh_store = SessionArtifactStore(tmp_path, session_id="session-denied-fresh")
    fresh_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-denied-fresh",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    fresh_event.timestamp = (datetime.now(UTC) - timedelta(hours=9)).isoformat()
    fresh_store.append_turn(
        TurnArtifact(
            prompt="deny fresh test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[fresh_event],
            response_metadata={"mode": "fake"},
        )
    )

    restored_store = SessionArtifactStore(tmp_path, session_id="session-denied-restored")
    restored_event = runtime_event(
        "steering_denied",
        "write_file",
        "Denied in the TUI",
        data={
            "tool_name": "write_file",
            "approval_id": "approval-denied-restored",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    restored_event.timestamp = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    restored_store.append_turn(
        TurnArtifact(
            prompt="deny restored edit",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[restored_event],
            response_metadata={"mode": "fake"},
        )
    )

    rendered = render_session_picker(tmp_path, filter_mode="denied")

    assert (
        "Denied approval backlog: 2 sessions | approvals: 2 | families: test 1, edit 1 | restored denied: 1 session"
        in rendered
    )
    assert "Denied focus: fresh, restored | oldest: 9h" in rendered


def test_render_session_picker_reports_pending_approval_page_rollups_when_backlog_spans_pages(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)

    seed_pending_approval_rollup_scenario(tmp_path, now=now)

    first_page = render_session_picker(tmp_path, filter_mode="pending")
    second_page = render_session_picker(tmp_path, filter_mode="pending", page_index=1)

    assert (
        "Pending approval backlog: 10 sessions | approvals: 11 | families: test 9, edit 2 | multi-queue: 1 session | restored queues: 1 session"
        in first_page
    )
    assert "Pending focus: fresh, restored | oldest: 18d" in first_page
    assert (
        "This page pending queues: approvals: 8 | families: test 8 | more off-page: approvals: 3 | families: test 1, edit 2 | multi-queue: 1 session | restored queues: 1 session"
        in first_page
    )
    assert "Page: 2/2 | Showing: 9-10 of 10" in second_page
    assert (
        "This page pending queues: approvals: 3 | families: test 1, edit 2 | multi-queue: 1 session | restored queues: 1 session | more off-page: approvals: 8 | families: test 8"
        in second_page
    )


def test_render_session_picker_reports_denied_approval_page_rollups_when_backlog_spans_pages(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)

    seed_denied_approval_rollup_scenario(tmp_path, now=now)

    first_page = render_session_picker(tmp_path, filter_mode="denied")
    second_page = render_session_picker(tmp_path, filter_mode="denied", page_index=1)

    assert (
        "Denied approval backlog: 10 sessions | approvals: 10 | families: test 8, edit 2 | restored denied: 1 session"
        in first_page
    )
    assert "Denied focus: fresh, restored | oldest: 3d" in first_page
    assert (
        "This page denied approvals: approvals: 8 | families: test 8 | more off-page: approvals: 2 | families: edit 2 | restored denied: 1 session"
        in first_page
    )
    assert "Page: 2/2 | Showing: 9-10 of 10" in second_page
    assert (
        "This page denied approvals: approvals: 2 | families: edit 2 | restored denied: 1 session | more off-page: approvals: 8 | families: test 8"
        in second_page
    )


def test_pick_session_empty_filter_prompt_highlights_triage_and_new_session_paths(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-demo")
    _append_turn(store, "review demo")

    prompts: list[str] = []
    captured: list[str] = []

    summary = pick_session(
        tmp_path,
        filter_mode="pending",
        input_fn=lambda prompt: prompts.append(prompt) or "",
        output_fn=captured.append,
    )

    assert summary is None
    assert prompts == [
        "No sessions match this filter. Press Enter or N for a new session, or use A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to change triage: "
    ]
    assert any("No saved sessions match the active picker filter." in line for line in captured)
    assert any("Try A to show all sessions" in line for line in captured)
    assert any("Press Enter or N to start a fresh session" in line for line in captured)


def test_pick_session_invalid_key_guidance_uses_visible_row_count(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-demo")
    _append_turn(store, "review demo")

    responses = iter(["z", "n"])
    prompts: list[str] = []
    captured: list[str] = []

    summary = pick_session(
        tmp_path,
        input_fn=lambda prompt: prompts.append(prompt) or next(responses),
        output_fn=captured.append,
    )

    assert summary is None
    assert prompts[0] == (
        "Select visible session number, press Enter to reopen highlighted, N for new session, or use J/K/A/P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y/S/[ / ] to triage/page: "
    )
    assert "Invalid selection. Use 1-1, J, K, A, P, D, R, V, O, Q, X, U, T, W, E, G, H, I, Y, S, [, ], Enter, or N." in captured
    assert not any("Invalid selection. Use 1-8" in line for line in captured)


def test_intervention_filter_surfaces_policy_and_approval_activity(tmp_path: Path) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    _append_turn(plain_store, "plain work")

    blocked_store = SessionArtifactStore(tmp_path, session_id="session-blocked")
    blocked_store.append_turn(
        TurnArtifact(
            prompt="touch protected file",
            response="blocked",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_blocked",
                    "write_file",
                    "Protected file mutations are blocked.",
                    data={
                        "tool_name": "write_file",
                        "approval_tool_family": "edit",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    approved_store = SessionArtifactStore(tmp_path, session_id="session-approved")
    approved_store.append_turn(
        TurnArtifact(
            prompt="approve the queued edit",
            response="approved",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_approved",
                    "write_file",
                    "Approved in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0001",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "approval_tool_family": "edit",
                    },
                ),
                runtime_event(
                    "approval_follow_up_prepared",
                    "write_file",
                    "Prepared continuation prompt.",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0001",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "approval_tool_family": "edit",
                        "tool_result_preview": "Simulated overwrite of notes.txt.",
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )

    intervention_summaries = list_recent_sessions(tmp_path, filter_mode="intervention")
    intervention_by_id = {summary.session_id: summary for summary in intervention_summaries}
    rendered = render_session_picker(tmp_path, filter_mode="intervention")

    assert set(intervention_by_id) == {"session-blocked", "session-approved"}
    assert intervention_by_id["session-blocked"].intervention_badges == ["blocked 1"]
    assert intervention_by_id["session-approved"].intervention_badges == ["approved 1"]
    assert intervention_by_id["session-approved"].last_intervention_preview == "continued edit write_file: Simulated overwrite of notes.txt."
    assert "Filter: intervention | Sort: recent" in rendered
    assert "intervention: blocked 1" in rendered
    assert "intervention: approved 1" in rendered
    assert "session-plain" not in rendered


def test_render_session_picker_surfaces_tool_backlog_rollups(tmp_path: Path) -> None:
    workspace_store = SessionArtifactStore(tmp_path, session_id="session-workspace-tool")
    workspace_store.append_turn(
        TurnArtifact(
            prompt="inspect workspace",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: src/"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    shell_store = SessionArtifactStore(tmp_path, session_id="session-shell-tool")
    shell_store.append_turn(
        TurnArtifact(
            prompt="inspect shell",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "pwd",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "pwd -> /workspace/demo",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    mixed_store = SessionArtifactStore(tmp_path, session_id="session-mixed-tool")
    mixed_store.append_turn(
        TurnArtifact(
            prompt="inspect both",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                ),
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )

    other_store = SessionArtifactStore(tmp_path, session_id="session-other-tool")
    other_store.append_turn(
        TurnArtifact(
            prompt="custom tool",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "custom_tool",
                    "Finished custom tool",
                    data={"tool_name": "custom_tool", "result_preview": "custom tool output"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    rendered = render_session_picker(tmp_path, filter_mode="tool")

    assert "Filter: tool | Sort: recent" in rendered
    assert (
        "Tool backlog: 4 sessions | lanes: workspace 2, shell 2, other 1 | overlap: mixed 1 session"
        in rendered
    )
    assert "Tool focus: workspace, shell, other" in rendered
    assert "session-workspace-tool" in rendered
    assert "session-shell-tool" in rendered
    assert "session-mixed-tool" in rendered
    assert "session-other-tool" in rendered


def test_render_session_picker_surfaces_intervention_backlog_rollups(tmp_path: Path) -> None:
    pending_store = SessionArtifactStore(tmp_path, session_id="session-intervention-pending")
    _append_turn(pending_store, "queue restored test")
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-intervention-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            )
        ]
    )

    blocked_store = SessionArtifactStore(tmp_path, session_id="session-intervention-blocked")
    blocked_store.append_turn(
        TurnArtifact(
            prompt="edit protected file",
            response="blocked",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_blocked",
                    "write_file",
                    "Protected file mutations are blocked.",
                    data={"tool_name": "write_file", "approval_tool_family": "edit"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    approved_store = SessionArtifactStore(tmp_path, session_id="session-intervention-approved")
    approved_store.append_turn(
        TurnArtifact(
            prompt="approve edit",
            response="approved",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_approved",
                    "write_file",
                    "Approved in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-intervention-approved",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "approval_tool_family": "edit",
                    },
                ),
                runtime_event(
                    "approval_follow_up_prepared",
                    "write_file",
                    "Prepared continuation prompt.",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-intervention-approved",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "approval_tool_family": "edit",
                        "tool_result_preview": "Simulated overwrite of notes.txt.",
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )

    denied_store = SessionArtifactStore(tmp_path, session_id="session-intervention-denied")
    denied_event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-intervention-denied",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "approval_tool_family": "edit",
            "remaining_pending_count": 0,
        },
    )
    denied_event.timestamp = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    denied_store.append_turn(
        TurnArtifact(
            prompt="deny restored edit",
            response="denied",
            provider="fake-strands",
            mode="fake",
            events=[denied_event],
            response_metadata={"mode": "fake"},
        )
    )

    rendered = render_session_picker(tmp_path, filter_mode="intervention")

    assert "Filter: intervention | Sort: recent" in rendered
    assert (
        "Intervention backlog: 4 sessions | lanes: pending 1 (oldest 2d), blocked 1, approved 1, denied 1 (oldest 6h), restored 2 (oldest 2d) | overlap: mixed 2 sessions"
        in rendered
    )
    assert "Intervention focus: pending, blocked, approved, denied, restored" in rendered
    assert "session-intervention-pending" in rendered
    assert "session-intervention-blocked" in rendered
    assert "session-intervention-approved" in rendered
    assert "session-intervention-denied" in rendered


def test_restored_pending_approval_sessions_surface_restore_queue_age_cues(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-restored-aged")
    _append_turn(store, "resume restored queue")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restored-aged",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="resume tests",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=3, hours=2)).isoformat(),
            )
        ]
    )

    summaries = list_recent_sessions(tmp_path, filter_mode="approval-restore")

    assert len(summaries) == 1
    assert summaries[0].restored_pending_approval_age_summary == "3d"
    assert summaries[0].restored_pending_approval_age_sort_key >= 3 * 24 * 60 * 60
    restored_line = summaries[0].render_line(1, filter_mode="approval-restore")
    assert "approval restore age: restore queue 3d" in restored_line
    assert "restore focus:" not in restored_line
    preview = "\n".join(
        summaries[0].render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )
    assert "- restore focus:" not in preview
    assert "- approval restore age: restore queue 3d" in preview


def test_restored_denied_approval_sessions_surface_last_restored_age_cues(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-restored-denied-aged")
    event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-restored-denied-aged",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    event.timestamp = (datetime.now(UTC) - timedelta(hours=6, minutes=5)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="deny restored edit",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[event],
            response_metadata={"mode": "fake"},
        )
    )

    summaries = list_recent_sessions(tmp_path, filter_mode="approval-restore")

    assert len(summaries) == 1
    assert summaries[0].restored_pending_approval_age_summary == ""
    assert summaries[0].last_restored_approval_age_summary == "6h"
    assert summaries[0].last_restored_approval_age_sort_key >= 6 * 60 * 60
    restored_line = summaries[0].render_line(1, filter_mode="approval-restore")
    assert "approval restore age: restored 6h" in restored_line
    assert "restore focus:" not in restored_line
    preview = "\n".join(
        summaries[0].render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )
    assert "- restore focus:" not in preview
    assert "- approval restore age: restored 6h" in preview
    assert "- last restored age: 6h" not in preview


def test_denied_approval_sessions_surface_last_denied_age_cues(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-denied-aged")
    event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-denied-aged",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    event.timestamp = (datetime.now(UTC) - timedelta(hours=9, minutes=10)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="deny rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[event],
            response_metadata={"mode": "fake"},
        )
    )

    summaries = list_recent_sessions(tmp_path, filter_mode="denied")
    preview = "\n".join(summaries[0].render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert len(summaries) == 1
    assert summaries[0].last_denied_approval_age_summary == "9h"
    assert summaries[0].last_denied_approval_age_sort_key >= 9 * 60 * 60
    assert "denied age: 9h" in summaries[0].render_line(1)
    assert "- last denied age: 9h" in preview


def test_stale_approval_filter_surfaces_old_pending_denied_and_restored_approvals(tmp_path: Path) -> None:
    scenario = seed_stale_approval_filter_scenario(tmp_path)

    stale_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale")
    stale_by_id = {summary.session_id: summary for summary in stale_summaries}
    rendered = render_session_picker(tmp_path, filter_mode="approval-stale")

    assert set(stale_by_id) == {scenario.pending_id, scenario.denied_id, scenario.restored_id}
    assert stale_by_id[scenario.pending_id].stale_approval_badges == ["pending 45d"]
    assert stale_by_id[scenario.denied_id].stale_approval_badges == ["denied 9d"]
    assert stale_by_id[scenario.restored_id].stale_approval_badges == ["restore queue 8d", "restored 10d"]
    assert "approval stale: pending 45d" in stale_by_id[scenario.pending_id].render_line(1)
    stale_pending_line = stale_by_id[scenario.pending_id].render_line(1, filter_mode="approval-stale")
    assert "approval stale age: pending 45d" in stale_pending_line
    assert "stale focus:" not in stale_pending_line
    assert "approval stale: restore queue 8d, restored 10d" in stale_by_id[scenario.restored_id].render_line(1)
    stale_restored_line = stale_by_id[scenario.restored_id].render_line(1, filter_mode="approval-stale")
    assert "approval stale ages: restore queue 8d; restored 10d" in stale_restored_line
    assert "stale focus:" not in stale_restored_line
    stale_denied_preview = "\n".join(
        stale_by_id[scenario.denied_id].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=3,
            filter_mode="approval-stale",
        )
    )
    assert "- stale focus:" not in stale_denied_preview
    assert "- approval stale age: denied 9d" in stale_denied_preview
    assert "- approval stale: denied 9d" not in stale_denied_preview
    assert "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old" not in stale_denied_preview
    stale_restored_preview = "\n".join(
        stale_by_id[scenario.restored_id].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=3,
            filter_mode="approval-stale",
        )
    )
    assert "- stale focus:" not in stale_restored_preview
    assert "- approval stale ages: restore queue 8d; restored 10d" in stale_restored_preview
    assert "- approval stale: restore queue 8d, restored 10d" not in stale_restored_preview
    assert (
        "Stale approval backlog: 3 sessions | lanes: pending 1 (oldest 45d), denied 1 (oldest 9d), "
        "restore queue 1 (oldest 8d), restored 1 (oldest 10d)"
    ) in rendered
    assert (
        "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
        in rendered
    )
    assert "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old" not in rendered


def test_stale_approval_filter_summarizes_current_page_and_off_page_lanes(tmp_path: Path) -> None:
    seed_stale_approval_rollup_scenario(tmp_path)

    first_page = render_session_picker(tmp_path, filter_mode="approval-stale")
    second_page = render_session_picker(tmp_path, filter_mode="approval-stale", page_index=1)

    assert (
        "Stale approval backlog: 10 sessions | lanes: pending 8 (oldest 52d), denied 1 (oldest 14d), "
        "restore queue 1 (oldest 11d)"
    ) in first_page
    assert (
        "This page stale lanes: pending 8 (oldest 52d) | more off-page: denied 1 (oldest 14d), "
        "restore queue 1 (oldest 11d)"
    ) in first_page
    assert "Page: 2/2 | Showing: 9-10 of 10" in second_page
    assert (
        "This page stale lanes: denied 1 (oldest 14d), restore queue 1 (oldest 11d) | more off-page: "
        "pending 8 (oldest 52d)"
    ) in second_page
    assert "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old" in first_page
    assert "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old" in second_page


def test_stale_approval_filter_variants_isolate_pending_denied_and_restored_lanes(tmp_path: Path) -> None:
    scenario = seed_stale_approval_subfilter_scenario(tmp_path)

    stale_pending_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-pending")
    stale_denied_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-denied")
    stale_restored_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-restored")
    stale_restored_by_id = {summary.session_id: summary for summary in stale_restored_summaries}
    stale_pending_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-pending")
    stale_denied_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-denied")
    stale_restored_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-restored")

    assert [summary.session_id for summary in stale_pending_summaries] == [scenario.pending_id]
    assert [summary.session_id for summary in stale_denied_summaries] == [scenario.denied_id]
    assert {summary.session_id for summary in stale_restored_summaries} == {
        scenario.restored_queue_id,
        scenario.restored_mixed_id,
    }
    mixed_stale_restored_preview = "\n".join(
        stale_restored_by_id[scenario.restored_mixed_id].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=2,
            filter_mode="approval-stale-restored",
        )
    )
    queue_stale_restored_preview = "\n".join(
        stale_restored_by_id[scenario.restored_queue_id].render_preview(
            visible_index=2,
            overall_index=2,
            total_matches=2,
            filter_mode="approval-stale-restored",
        )
    )
    assert "session-stale-denied" not in stale_pending_rendered
    assert "session-stale-restored-queue" not in stale_pending_rendered
    assert "Stale pending backlog: 1 session | lanes: pending 1 (oldest 45d)" in stale_pending_rendered
    assert "Stale lane focus: pending | cutoff: approvals >= 7d old" in stale_pending_rendered
    assert "- stale lane focus: pending | cutoff: approvals >= 7d old" in stale_pending_rendered
    assert "| approval stale age: 45d | stale focus: pending" in stale_pending_rendered
    assert "| approval stale: pending 45d | stale focus: pending" not in stale_pending_rendered
    assert "- stale focus: pending" in stale_pending_rendered
    assert "- approval stale age: 45d" in stale_pending_rendered
    assert "- approval stale: pending 45d" not in stale_pending_rendered
    assert "stale focus: pending" in stale_pending_rendered
    assert "session-stale-pending" not in stale_denied_rendered
    assert "session-stale-pending" not in stale_restored_rendered
    assert "Stale denied backlog: 1 session | lanes: denied 1 (oldest 9d)" in stale_denied_rendered
    assert "Stale lane focus: denied | cutoff: approvals >= 7d old" in stale_denied_rendered
    assert "- stale lane focus: denied | cutoff: approvals >= 7d old" in stale_denied_rendered
    assert "| approval stale age: 9d | stale focus: denied" in stale_denied_rendered
    assert "| approval stale: denied 9d | stale focus: denied" not in stale_denied_rendered
    assert "- stale focus: denied" in stale_denied_rendered
    assert "- approval stale age: 9d" in stale_denied_rendered
    assert "- approval stale: denied 9d" not in stale_denied_rendered
    assert "stale focus: denied" in stale_denied_rendered
    assert (
        "Stale restored backlog: 2 sessions | lanes: restore queue 2 (oldest 11d), restored 1 (oldest 9d)"
    ) in stale_restored_rendered
    assert (
        "Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old"
        in stale_restored_rendered
    )
    assert "- stale lane focus: restore queue, restored | cutoff: approvals >= 7d old" in stale_restored_rendered
    assert "| approval stale age: 11d | stale focus: restore queue" in stale_restored_rendered
    assert (
        "| approval stale ages: restore queue 10d; restored 9d | stale focus: restore queue, restored"
        in stale_restored_rendered
    )
    assert (
        "restored current: pending write_file via fake_runtime; queued 1" in stale_restored_rendered
    )
    assert (
        "restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0"
        in stale_restored_rendered
    )
    assert "restored outcome age: 9d" in stale_restored_rendered
    assert "| approval stale: restore queue 11d | stale focus: restore queue" not in stale_restored_rendered
    assert "| approval stale: restore queue 10d, restored 9d | stale focus: restore queue, restored" not in stale_restored_rendered
    assert "stale focus: restore queue" in stale_restored_rendered
    assert "- stale focus: restore queue" in queue_stale_restored_preview
    assert "- approval stale age: 11d" in queue_stale_restored_preview
    assert "- approval stale: restore queue 11d" not in queue_stale_restored_preview
    assert "- stale focus: restore queue, restored" in mixed_stale_restored_preview
    assert "- approval stale ages: restore queue 10d; restored 9d" in mixed_stale_restored_preview
    assert "- restored current approval: pending write_file via fake_runtime | queued 1" in mixed_stale_restored_preview
    assert (
        "- latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0"
        in mixed_stale_restored_preview
    )
    assert "- latest restored outcome age: 9d" in mixed_stale_restored_preview
    assert "- approval stale: restore queue 10d, restored 9d" not in mixed_stale_restored_preview


def test_stale_approval_filter_respects_custom_warning_threshold(tmp_path: Path) -> None:
    custom_threshold_store = SessionArtifactStore(tmp_path, session_id="session-custom-threshold")
    _append_turn(custom_threshold_store, "resume moderately old pending queue")
    custom_threshold_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-custom-threshold",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            )
        ]
    )

    default_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale")
    default_rendered = render_session_picker(tmp_path, filter_mode="approval-stale")
    custom_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="approval-stale",
        stale_approval_warning_seconds=24 * 60 * 60,
    )
    custom_rendered = render_session_picker(
        tmp_path,
        filter_mode="approval-stale",
        stale_approval_warning_seconds=24 * 60 * 60,
    )

    assert default_summaries == []
    assert "Stale cutoff: approvals >= 7d old" in default_rendered
    assert [summary.session_id for summary in custom_summaries] == ["session-custom-threshold"]
    assert custom_summaries[0].stale_approval_badges == ["pending 2d"]
    assert "Stale cutoff: approvals >= 1d old" in custom_rendered
    assert "Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d)" in custom_rendered
    assert "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old" in custom_rendered
    assert "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old" not in custom_rendered



def test_pick_session_supports_filter_sort_and_preview_navigation_commands(tmp_path: Path) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    _append_turn(plain_store, "plain")

    restore_store = SessionArtifactStore(tmp_path, session_id="session-restore")
    _append_turn(restore_store, "restore")
    restore_store.save_session_state(SessionState(draft_prompt="draft"))

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    _append_turn(pending_store, "pending")
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0012",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    captured: list[str] = []
    inputs = iter(["p", "s", "j", "k", ""])
    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: next(inputs),
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-pending"
    assert any("Filter: pending | Sort: recent" in line for line in captured)
    assert any("Filter: pending | Sort: attention" in line for line in captured)
    assert any("Selected preview:" in line for line in captured)
    assert any("- pending: run_shell_command [approval-0012] | Needs confirmation | command='pytest -q'" in line for line in captured)


def test_pick_session_supports_paged_navigation_to_older_sessions(tmp_path: Path) -> None:
    for index in range(MAX_RECENT_SESSIONS + 3):
        store = SessionArtifactStore(tmp_path, session_id=f"session-{index:02d}")
        _append_turn(store, f"prompt {index}")

    captured: list[str] = []
    inputs = iter(["]", "3"])
    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: next(inputs),
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-00"
    assert any("Page: 2/2 | Showing: 9-11 of 11" in line for line in captured)
    assert any("- slot 1 on this page | overall 9 of 11 | session session-02" in line for line in captured)


def test_pick_session_restores_prior_page_and_selection_after_fresh_session_escape(tmp_path: Path) -> None:
    for index in range(MAX_RECENT_SESSIONS + 3):
        store = SessionArtifactStore(tmp_path, session_id=f"session-{index:02d}")
        _append_turn(store, f"prompt {index}")

    first_inputs = iter(["]", "j", "n"])
    assert (
        pick_session(
            tmp_path,
            input_fn=lambda _prompt: next(first_inputs),
            output_fn=lambda _line: None,
        )
        is None
    )

    captured: list[str] = []
    second_inputs = iter([""])
    summary = pick_session(
        tmp_path,
        input_fn=lambda _prompt: next(second_inputs),
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-01"
    assert any("Page: 2/2 | Showing: 9-11 of 11" in line for line in captured)
    assert any("> 2. session-01" in line for line in captured)
    assert any("- slot 2 on this page | overall 10 of 11 | session session-01" in line for line in captured)


def test_pick_session_explicit_overrides_ignore_persisted_picker_state(tmp_path: Path) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    _append_turn(plain_store, "plain")

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    _append_turn(pending_store, "pending")
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0014",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    save_session_picker_state(
        tmp_path,
        SessionPickerState(
            filter_mode="tool",
            sort_mode="attention",
            page_index=1,
            selected_index=3,
            selected_session_id="session-plain",
        ),
    )

    captured: list[str] = []
    summary = pick_session(
        tmp_path,
        filter_mode="pending",
        sort_mode="recent",
        input_fn=lambda _prompt: "1",
        output_fn=captured.append,
    )

    assert summary is not None
    assert summary.session_id == "session-pending"
    assert any("Filter: pending | Sort: recent | Page: 1/1 | Showing: 1-1 of 1" in line for line in captured)


def test_session_artifact_store_persists_and_clears_pending_approvals(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-approval")
    approvals = [
        ApprovalRequest(
            request_id="approval-0001",
            tool_name="write_file",
            reason="Needs confirmation",
            args={"relative_path": "notes.txt", "overwrite": True},
            source="fake_runtime",
            prompt="overwrite notes",
        ),
        ApprovalRequest(
            request_id="approval-0002",
            tool_name="replace_text",
            reason="Broad edit needs confirmation",
            args={"relative_path": "notes.txt", "expected_occurrences": 2},
            source="fake_runtime",
            prompt="replace all notes",
        ),
    ]

    store.save_pending_approvals(approvals)

    loaded = store.load_pending_approvals()

    assert [approval.request_id for approval in loaded] == ["approval-0001", "approval-0002"]
    assert loaded[0].tool_name == "write_file"
    assert loaded[1].args["expected_occurrences"] == 2
    assert store.clear_pending_approvals() is True
    assert store.load_pending_approvals() == []


def test_session_artifact_store_persists_restart_safe_view_state_alongside_pending_approvals(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-state")
    store.save_session_state(
        SessionState(
            pending_approvals=[
                ApprovalRequest(
                    request_id="approval-0009",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="overwrite notes",
                )
            ],
            event_filter="tool",
            history_focus_index=2,
            draft_prompt="summarize the failing test output",
            session_switcher_active=True,
            session_switcher_selected_session_id="session-target",
            session_switcher_filter_mode="pending",
            session_switcher_sort_mode="attention",
            session_switcher_page_index=1,
        )
    )

    restored = store.load_session_state()

    assert restored is not None
    assert restored.event_filter == "tool"
    assert restored.history_focus_index == 2
    assert restored.draft_prompt == "summarize the failing test output"
    assert restored.session_switcher_active is True
    assert restored.session_switcher_selected_session_id == "session-target"
    assert restored.session_switcher_filter_mode == "pending"
    assert restored.session_switcher_sort_mode == "attention"
    assert restored.session_switcher_page_index == 1
    assert restored.pending_approvals[0].request_id == "approval-0009"
    assert store.pending_approvals_path.exists()

    assert store.clear_pending_approvals() is True

    preserved_view_state = store.load_session_state()
    assert preserved_view_state is not None
    assert preserved_view_state.pending_approvals == []
    assert preserved_view_state.event_filter == "tool"
    assert preserved_view_state.history_focus_index == 2
    assert preserved_view_state.draft_prompt == "summarize the failing test output"
    assert preserved_view_state.session_switcher_active is True
    assert preserved_view_state.session_switcher_selected_session_id == "session-target"
    assert preserved_view_state.session_switcher_filter_mode == "pending"
    assert preserved_view_state.session_switcher_sort_mode == "attention"
    assert preserved_view_state.session_switcher_page_index == 1


def test_list_recent_sessions_surfaces_pending_approval_metadata(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-pending")
    _append_turn(store, "run pytest")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0007",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest"},
                source="fake_runtime",
                prompt="run pytest",
            )
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]

    assert summary.pending_approval_count == 1
    assert summary.pending_approval_tool == "run_shell_command"
    assert "pending: run_shell_command" in summary.render_line(1)


def test_list_recent_sessions_surfaces_pending_approval_age_and_stale_session_cues(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    stale_turn_time = now - timedelta(days=10)
    old_approval_time = now - timedelta(days=45)

    store = SessionArtifactStore(tmp_path, session_id="session-aged")
    store.append_turn(
        TurnArtifact(
            prompt="resume old test queue",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
            created_at=stale_turn_time.isoformat(),
        )
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-aged-1",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
                created_at=old_approval_time.isoformat(),
            )
        ]
    )
    _set_session_artifact_mtime(store, stale_turn_time)

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )

    assert summary.pending_approval_age_summary == "45d"
    assert summary.stale_session_badges == ["warning 10d"]
    assert summary.stale_session_summary == "idle 10d since last artifact activity"
    assert "pending age: 45d" in summary.render_line(1)
    assert "stale: warning 10d" in summary.render_line(1)
    assert "- pending age: 45d" in preview
    assert "- session age: idle 10d since last artifact activity" in preview


def test_list_recent_sessions_surfaces_pending_queue_first_vs_rest_breakdown(tmp_path: Path) -> None:
    seed_multi_approval_queue_session(
        tmp_path,
        session_id="session-pending-mixed",
        prompt="queue mixed approvals",
        request_id_prefix="approval-0007",
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )

    assert summary.pending_approval_count == 3
    assert summary.pending_approval_queue_summary == "first test; rest edit 1, tool 1"
    assert "pending: 3 approvals (first test; rest edit 1, tool 1)" in summary.render_line(1)
    assert "pending tools: test 1, edit 1, tool 1" in summary.render_line(1)
    assert "- pending queue: first test; rest edit 1, tool 1" in preview
    assert "- last approval: pending run_shell_command via fake_runtime | queued 3" in preview


def test_list_recent_sessions_surfaces_approval_rollup_and_last_summary(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-approval-rollup")
    store.append_turn(
        TurnArtifact(
            prompt="run the guarded write flow",
            response="approval state updated",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_confirmation_required",
                    "write_file",
                    "Needs confirmation",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0001",
                        "approval_status": "pending",
                        "approval_source": "fake_runtime",
                        "pending_count": 1,
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )
    store.append_turn(
        TurnArtifact(
            prompt="approve the write and queue tests",
            response="approval state updated again",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_approved",
                    "write_file",
                    "Approved in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0001",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 1,
                        "resumed_from_approval": True,
                    },
                ),
                runtime_event(
                    "tool_finished",
                    "write_file",
                    "Finished write",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0001",
                        "approval_status": "approved",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 1,
                        "resumed_from_approval": True,
                        "result_preview": "wrote: notes.txt",
                    },
                ),
                runtime_event(
                    "steering_confirmation_required",
                    "run_shell_command",
                    "Needs confirmation",
                    data={
                        "tool_name": "run_shell_command",
                        "approval_id": "approval-0002",
                        "approval_status": "pending",
                        "approval_source": "fake_runtime",
                        "pending_count": 1,
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0002",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )

    assert summary.approval_status_badges == ["pending 1", "approved 1"]
    assert summary.last_approval_summary == "pending run_shell_command via fake_runtime | queued 1"
    assert "approvals: pending 1, approved 1" in summary.render_line(1)
    assert "approval focus: pending" in summary.render_line(1)
    assert "- approvals: pending 1, approved 1" in preview
    assert "- approval focus: pending" in preview
    assert "- last approval: pending run_shell_command via fake_runtime | queued 1" in preview


def test_list_recent_sessions_surfaces_last_denied_approval_summary(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-denied")
    store.append_turn(
        TurnArtifact(
            prompt="deny risky write",
            response="skipped write",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_denied",
                    "write_file",
                    "Denied in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-9000",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 0,
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.denied_approval_count == 1
    assert summary.denied_approval_badges == ["edit 1"]
    assert summary.last_denied_approval_summary == "denied write_file via fake_runtime | fresh request | remaining 0"
    assert summary.approval_status_badges == ["denied 1"]
    assert summary.restored_approval_badges == []
    assert "approval focus: denied/fresh" in summary.render_line(1)
    assert "denied: edit 1" in summary.render_line(1)
    assert "- approval focus: denied/fresh" in preview
    assert "- denied: edit 1" in preview
    assert "- last denied approval: denied write_file via fake_runtime | fresh request | remaining 0" in preview


def test_list_recent_sessions_surfaces_denied_approval_tool_family_breakdown(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-denied-breakdown")
    store.append_turn(
        TurnArtifact(
            prompt="deny risky actions",
            response="skipped actions",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_denied",
                    "replace_text",
                    "Denied in the TUI",
                    data={
                        "tool_name": "replace_text",
                        "approval_id": "approval-9100",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 1,
                        "relative_path": "notes.txt",
                    },
                ),
                runtime_event(
                    "steering_denied",
                    "run_shell_command",
                    "Denied in the TUI",
                    data={
                        "tool_name": "run_shell_command",
                        "approval_id": "approval-9101",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 0,
                        "command": "pytest -q",
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.denied_approval_count == 2
    assert summary.denied_approval_badges == ["test 1", "edit 1"]
    assert summary.last_denied_approval_summary == "denied run_shell_command via fake_runtime | fresh request | remaining 0"
    assert "denied: test 1, edit 1" in summary.render_line(1)
    assert "- denied: test 1, edit 1" in preview
    assert "- last denied approval: denied run_shell_command via fake_runtime | fresh request | remaining 0" in preview


def test_list_recent_sessions_surfaces_live_runtime_restored_approval_summary(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-live-approved")
    store.append_turn(
        TurnArtifact(
            prompt="request overwrite",
            response="approval required",
            provider="strands-openai",
            mode="live",
            events=[
                runtime_event(
                    "steering_confirmation_required",
                    "write_file",
                    "Needs confirmation",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0042",
                        "approval_status": "pending",
                        "approval_source": "live_runtime",
                        "pending_count": 1,
                    },
                )
            ],
            response_metadata={"mode": "live"},
        )
    )
    store.append_turn(
        TurnArtifact(
            prompt="approve overwrite",
            response="continued after approval",
            provider="strands-openai",
            mode="live",
            events=[
                runtime_event(
                    "steering_approved",
                    "write_file",
                    "Approved in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0042",
                        "approval_status": "approved",
                        "approval_source": "live_runtime",
                        "approval_restored": True,
                        "remaining_pending_count": 0,
                        "resumed_from_approval": True,
                    },
                ),
                runtime_event(
                    "tool_finished",
                    "write_file",
                    "Finished write",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0042",
                        "approval_status": "approved",
                        "approval_source": "live_runtime",
                        "approval_restored": True,
                        "remaining_pending_count": 0,
                        "resumed_from_approval": True,
                        "result_preview": "updated: notes.txt",
                    },
                ),
            ],
            response_metadata={"mode": "live"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.approval_status_badges == ["approved 1"]
    assert summary.last_approval_summary == "approved write_file via live_runtime | resumed | remaining 0"
    assert summary.restored_approval_badges == ["approved 1"]
    assert summary.restored_approval_tool_badges == ["edit 1"]
    assert summary.last_restored_approval_summary == "approved write_file via live_runtime | resumed | remaining 0"
    assert "approval focus: approved/restored/resumed" in summary.render_line(1)
    assert "approval restore: approved 1" in summary.render_line(1)
    assert "approval restore tools: edit 1" in summary.render_line(1)
    assert "- approvals: approved 1" in preview
    assert "- approval focus: approved/restored/resumed" in preview
    assert "- approval restore: approved 1" in preview
    assert "- approval restore tools: edit 1" in preview
    assert "- last approval: approved write_file via live_runtime | resumed | remaining 0" in preview
    assert "- last restored approval: approved write_file via live_runtime | resumed | remaining 0" in preview


def test_list_recent_sessions_surfaces_live_runtime_restored_denied_approval_summary(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-live-denied")
    store.append_turn(
        TurnArtifact(
            prompt="request overwrite",
            response="approval required",
            provider="strands-openai",
            mode="live",
            events=[
                runtime_event(
                    "steering_confirmation_required",
                    "write_file",
                    "Needs confirmation",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0043",
                        "approval_status": "pending",
                        "approval_source": "live_runtime",
                        "pending_count": 1,
                    },
                )
            ],
            response_metadata={"mode": "live"},
        )
    )
    store.append_turn(
        TurnArtifact(
            prompt="deny overwrite",
            response="continued after denial",
            provider="strands-openai",
            mode="live",
            events=[
                runtime_event(
                    "steering_denied",
                    "write_file",
                    "Denied in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0043",
                        "approval_status": "denied",
                        "approval_source": "live_runtime",
                        "approval_restored": True,
                        "remaining_pending_count": 0,
                        "resumed_from_approval": False,
                    },
                )
            ],
            response_metadata={"mode": "live"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.approval_status_badges == ["denied 1"]
    assert summary.denied_approval_badges == ["edit 1"]
    assert summary.last_approval_summary == "denied write_file via live_runtime | restored queue | remaining 0"
    assert summary.last_denied_approval_summary == "denied write_file via live_runtime | restored queue | remaining 0"
    assert summary.restored_approval_badges == ["denied 1"]
    assert summary.restored_approval_tool_badges == ["edit 1"]
    assert summary.last_restored_approval_summary == "denied write_file via live_runtime | restored queue | remaining 0"
    assert "approval focus: denied/restored" in summary.render_line(1)
    assert "denied: edit 1" in summary.render_line(1)
    assert "approval restore: denied 1" in summary.render_line(1)
    assert "approval restore tools: edit 1" in summary.render_line(1)
    assert "- approvals: denied 1" in preview
    assert "- approval focus: denied/restored" in preview
    assert "- denied: edit 1" in preview
    assert "- approval restore: denied 1" in preview
    assert "- approval restore tools: edit 1" in preview
    assert "- last approval: denied write_file via live_runtime | restored queue | remaining 0" in preview
    assert "- last denied approval: denied write_file via live_runtime | restored queue | remaining 0" in preview
    assert "- last restored approval: denied write_file via live_runtime | restored queue | remaining 0" in preview


def test_list_recent_sessions_surfaces_restored_approval_tool_family_breakdown(tmp_path: Path) -> None:
    seed_approval_restore_overlap_session(
        tmp_path,
        session_id="session-restored-breakdown",
        response="triaged restored approvals",
        pending_request_id="approval-9301",
        outcome_request_id="approval-9300",
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )
    rendered = render_session_picker(tmp_path, filter_mode="approval-restore")

    assert summary.restored_approval_count == 2
    assert summary.restored_approval_badges == ["pending 1", "denied 1"]
    assert summary.restored_approval_tool_badges == ["test 1", "edit 1"]
    assert summary.last_restored_approval_summary == "pending run_shell_command via fake_runtime | queued 1"
    assert summary.last_restored_outcome_summary == "denied replace_text via fake_runtime | restored queue | remaining 0"
    assert summary.restored_pending_approval_age_summary == "3d"
    assert summary.last_restored_outcome_age_summary == "6h"
    assert (
        summary.attention_reason_summary
        == "restored pending test approval queue; tests sort ahead of restored edits"
    )
    restored_line = summary.render_line(1, filter_mode="approval-restore")
    assert "approval restore tools: test 1, edit 1" in restored_line
    assert "approval restore ages: restore queue 3d; restored 6h" in restored_line
    assert "restore focus: restore queue, restored" not in restored_line
    assert "restored current: pending run_shell_command via fake_runtime; queued 1" in restored_line
    assert "restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0" in restored_line
    assert "restored outcome age: 6h" not in restored_line
    assert "- attention reason: restored pending test approval queue; tests sort ahead of restored edits" in preview
    assert "- approval restore: pending 1, denied 1" in preview
    assert "- approval restore tools: test 1, edit 1" in preview
    assert "- restore focus: restore queue, restored" not in preview
    assert "- approval restore ages: restore queue 3d; restored 6h" in preview
    assert "- restored current approval: pending run_shell_command via fake_runtime | queued 1" in preview
    assert "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0" in preview
    assert "- latest restored outcome age: 6h" not in preview
    assert (
        "Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d), restored 1 (oldest 6h) | overlap: mixed 1 session"
        in rendered
    )
    assert "Restore lane focus: restore queue, restored" in rendered


def test_render_session_picker_reports_approval_restore_page_rollups_when_backlog_spans_pages(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    seed_approval_restore_rollup_scenario(tmp_path, now=now)

    first_page = render_session_picker(tmp_path, filter_mode="approval-restore")
    second_page = render_session_picker(tmp_path, filter_mode="approval-restore", page_index=1)

    assert (
        "Approval restore backlog: 10 sessions | lanes: restore queue 9 (oldest 18d), restored 2 (oldest 8h) | overlap: mixed 1 session"
        in first_page
    )
    assert "Restore lane focus: restore queue, restored" in first_page
    assert (
        "This page restore lanes: restore queue 8 (oldest 18d) | more off-page: restore queue 1 (oldest 3d), restored 2 (oldest 8h) | overlap here/off-page: none / mixed 1 session"
        in first_page
    )
    assert "Page: 2/2 | Showing: 9-10 of 10" in second_page
    assert (
        "This page restore lanes: restore queue 1 (oldest 3d), restored 2 (oldest 8h) | more off-page: restore queue 8 (oldest 18d) | overlap here/off-page: mixed 1 session / none"
        in second_page
    )


def test_list_recent_sessions_surfaces_restored_pending_queue_breakdown(tmp_path: Path) -> None:
    seed_multi_approval_queue_session(
        tmp_path,
        session_id="session-restored-pending-mixed",
        prompt="reopen restored approval queue",
        restored_from_session=True,
        request_id_prefix="approval-931",
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.pending_approval_queue_summary == "first test; rest edit 1, tool 1"
    assert summary.restored_pending_approval_queue_summary == "first test; rest edit 1, tool 1"
    assert "pending: 3 approvals (first test; rest edit 1, tool 1)" in summary.render_line(1)
    assert "approval restore queue: first test; rest edit 1, tool 1" in summary.render_line(1)
    assert "- pending queue: first test; rest edit 1, tool 1" in preview
    assert "- approval restore queue: first test; rest edit 1, tool 1" in preview


def test_list_recent_sessions_surfaces_restore_badges_from_session_state(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-restore")
    _append_turn(store, "inspect repo")
    _append_turn(store, "review latest diff")
    store.save_session_state(
        SessionState(
            event_filter="tool",
            history_focus_index=1,
            draft_prompt="draft follow-up",
            session_switcher_active=True,
            session_switcher_page_index=1,
        )
    )

    summary = list_recent_sessions(tmp_path)[0]

    assert summary.restore_badges == ["filter=tool", "replay 2/2", "draft 15c", "chooser p2"]
    assert summary.draft_prompt_preview == "draft follow-up"
    assert "restore: filter=tool, replay 2/2, draft 15c, chooser p2" in summary.render_line(1)


def test_list_recent_sessions_supports_offset_for_paged_switcher_views(tmp_path: Path) -> None:
    created_ids: list[str] = []
    for index in range(MAX_RECENT_SESSIONS + 2):
        session_id = f"session-{index:02d}"
        store = SessionArtifactStore(tmp_path, session_id=session_id)
        _append_turn(store, f"prompt {index}")
        created_ids.append(session_id)

    ordered_ids = list(reversed(created_ids))
    all_sessions = list_recent_sessions(tmp_path, limit=count_recent_sessions(tmp_path))
    first_page = list_recent_sessions(tmp_path, limit=MAX_RECENT_SESSIONS)
    second_page = list_recent_sessions(tmp_path, limit=MAX_RECENT_SESSIONS, offset=MAX_RECENT_SESSIONS)

    assert len(first_page) == MAX_RECENT_SESSIONS
    assert len(second_page) == 2
    assert [session.session_id for session in all_sessions] == ordered_ids
    assert [session.session_id for session in first_page] == ordered_ids[:MAX_RECENT_SESSIONS]
    assert [session.session_id for session in second_page] == ordered_ids[MAX_RECENT_SESSIONS:]


def test_list_recent_sessions_surfaces_shell_tool_preview_and_exit_badges(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-shell")
    store.append_turn(
        TurnArtifact(
            prompt="check git status",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Simulated read-only shell inspection.",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.last_tool_preview == "git status --short -> M README.md"
    assert summary.last_tool_badges == ["inspect", "e0"]
    assert summary.shell_activity_badges == ["inspect 1"]
    assert summary.last_shell_preview == "inspect/e0 git status --short -> M README.md"
    assert summary.recent_shell_previews == ["inspect/e0 git status --short -> M README.md"]
    assert "last tool: inspect/e0 git status --short -> M README.md" in summary.render_line(1)
    assert "shell: inspect 1" in summary.render_line(1)
    assert "- shell: inspect 1" in preview
    assert "- last shell: inspect/e0 git status --short -> M README.md" in preview


def test_list_recent_sessions_surfaces_shell_test_rollup_and_failures(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-shell-rollup")
    store.append_turn(
        TurnArtifact(
            prompt="inspect and test",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                ),
                runtime_event(
                    "tool_failed",
                    "run_shell_command",
                    "Shell test failed",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "pytest -q",
                        "shell_policy": "confirm",
                        "exit_code": 1,
                        "result_preview": "pytest -q -> exit 1",
                    },
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.shell_activity_badges == ["inspect 1", "test 1", "fail 1"]
    assert summary.shell_lane_badges == ["inspect", "test"]
    assert summary.has_shell_inspect_activity is True
    assert summary.has_shell_test_activity is True
    assert summary.failure_activity_badges == ["test 1"]
    assert summary.last_shell_preview == "confirm/e1 pytest -q -> exit 1"
    assert summary.recent_shell_previews == [
        "confirm/e1 pytest -q -> exit 1",
        "inspect/e0 git status --short -> M README.md",
    ]
    assert summary.recent_failure_count == 1
    assert summary.recent_shell_failure_count == 1
    assert summary.recent_test_failure_count == 1
    assert summary.recent_tool_failure_count == 0
    assert "shell: inspect 1, test 1, fail 1" in summary.render_line(1)
    assert "shell lanes: inspect, test" in summary.render_line(1)
    assert "failures: test 1" in summary.render_line(1)
    assert "- shell lanes: inspect, test" in preview
    assert "- failures: test 1" in preview
    assert "- recent shell outcomes (2):" in preview
    assert "  1. confirm/e1 pytest -q -> exit 1" in preview
    assert "  2. inspect/e0 git status --short -> M README.md" in preview


def test_list_recent_sessions_marks_mixed_shell_lane_overlap_when_session_matches_both_shell_filters(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-shell-mixed")
    store.append_turn(
        TurnArtifact(
            prompt="inspect before rerunning tests",
            response="pending",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-mixed-shell",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
            )
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.has_shell_inspect_activity is True
    assert summary.has_shell_test_activity is True
    assert summary.shell_lane_badges == ["inspect", "test"]
    assert "shell lanes: inspect, test" in summary.render_line(1)
    assert "- shell lanes: inspect, test" in preview
    assert [session.session_id for session in list_recent_sessions(tmp_path, filter_mode="shell-inspect")] == [
        "session-shell-mixed"
    ]
    assert [session.session_id for session in list_recent_sessions(tmp_path, filter_mode="shell-test")] == [
        "session-shell-mixed"
    ]


def test_list_recent_sessions_surfaces_non_shell_failure_rollup(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-tool-failure-rollup")
    store.append_turn(
        TurnArtifact(
            prompt="attempt edit",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_failed",
                    "replace_text",
                    "Edit failed",
                    data={
                        "tool_name": "replace_text",
                        "result_preview": "replace_text notes.txt (2 occurrences)",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.failure_activity_badges == ["tool 1"]
    assert summary.recent_failure_count == 1
    assert summary.recent_shell_failure_count == 0
    assert summary.recent_test_failure_count == 0
    assert summary.recent_tool_failure_count == 1
    assert "failures: tool 1" in summary.render_line(1)
    assert "- failures: tool 1" in preview


def test_list_recent_sessions_surfaces_recent_tool_streak_preview(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-tool-streak")
    store.append_turn(
        TurnArtifact(
            prompt="inspect repo layout",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: src/"},
                ),
                runtime_event(
                    "tool_finished",
                    "read_file",
                    "Finished reading file",
                    data={"tool_name": "read_file", "result_preview": "README.md lines 1-20"},
                ),
            ],
            response_metadata={"mode": "fake"},
        )
    )
    store.append_turn(
        TurnArtifact(
            prompt="attempt broad edit",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_failed",
                    "replace_text",
                    "Edit failed",
                    data={"tool_name": "replace_text", "result_preview": "replace_text notes.txt (2 occurrences)"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.recent_tool_previews == [
        "failed replace_text notes.txt (2 occurrences)",
        "README.md lines 1-20",
        ".: src/",
    ]
    assert "tool streak: 3 recent" in summary.render_line(1)
    assert "- recent tools (3):" in preview
    assert "  1. failed replace_text notes.txt (2 occurrences)" in preview
    assert "  2. README.md lines 1-20" in preview
    assert "  3. .: src/" in preview


def test_list_recent_sessions_can_filter_to_pending_denied_restore_approval_restore_tool_and_workspace_triage(tmp_path: Path) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    _append_turn(plain_store, "plain")

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    _append_turn(pending_store, "run pytest")
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0010",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    denied_store = SessionArtifactStore(tmp_path, session_id="session-denied")
    denied_store.append_turn(
        TurnArtifact(
            prompt="deny risky edit",
            response="skipped",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_denied",
                    "replace_text",
                    "Denied in the TUI",
                    data={
                        "tool_name": "replace_text",
                        "approval_id": "approval-0010b",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "approval_restored": True,
                        "remaining_pending_count": 0,
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    restore_store = SessionArtifactStore(tmp_path, session_id="session-restore")
    _append_turn(restore_store, "resume triage")
    restore_store.save_session_state(SessionState(draft_prompt="queued follow-up"))

    pending_edit_store = SessionArtifactStore(tmp_path, session_id="session-pending-edit")
    _append_turn(pending_edit_store, "queue edit")
    pending_edit_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0010c",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="queue edit",
            )
        ]
    )

    tool_store = SessionArtifactStore(tmp_path, session_id="session-tool")
    tool_store.append_turn(
        TurnArtifact(
            prompt="inspect repo",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    shell_store = SessionArtifactStore(tmp_path, session_id="session-shell")
    shell_store.append_turn(
        TurnArtifact(
            prompt="inspect git status",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    pending_sessions = list_recent_sessions(tmp_path, filter_mode="pending")
    denied_sessions = list_recent_sessions(tmp_path, filter_mode="denied")
    restore_sessions = list_recent_sessions(tmp_path, filter_mode="restore")
    approval_restore_sessions = list_recent_sessions(tmp_path, filter_mode="approval-restore")
    approval_stale_sessions = list_recent_sessions(tmp_path, filter_mode="approval-stale")
    approval_stale_pending_sessions = list_recent_sessions(tmp_path, filter_mode="approval-stale-pending")
    approval_stale_denied_sessions = list_recent_sessions(tmp_path, filter_mode="approval-stale-denied")
    approval_stale_restored_sessions = list_recent_sessions(tmp_path, filter_mode="approval-stale-restored")
    tool_sessions = list_recent_sessions(tmp_path, filter_mode="tool")
    workspace_inspect_sessions = list_recent_sessions(tmp_path, filter_mode="workspace-inspect")
    workspace_edit_sessions = list_recent_sessions(tmp_path, filter_mode="workspace-edit")
    shell_sessions = list_recent_sessions(tmp_path, filter_mode="shell")
    shell_inspect_sessions = list_recent_sessions(tmp_path, filter_mode="shell-inspect")
    shell_test_sessions = list_recent_sessions(tmp_path, filter_mode="shell-test")

    assert [session.session_id for session in pending_sessions] == ["session-pending-edit", "session-pending"]
    assert [session.session_id for session in denied_sessions] == ["session-denied"]
    assert [session.session_id for session in restore_sessions] == ["session-restore"]
    assert [session.session_id for session in approval_restore_sessions] == ["session-denied"]
    assert approval_stale_sessions == []
    assert approval_stale_pending_sessions == []
    assert approval_stale_denied_sessions == []
    assert approval_stale_restored_sessions == []
    assert [session.session_id for session in tool_sessions] == ["session-shell", "session-tool"]
    assert [session.session_id for session in workspace_inspect_sessions] == ["session-tool"]
    assert [session.session_id for session in workspace_edit_sessions] == ["session-pending-edit", "session-denied"]
    assert "workspace lanes: inspect" in workspace_inspect_sessions[0].render_line(1)
    assert "workspace lanes: edit" in workspace_edit_sessions[0].render_line(1)
    assert [session.session_id for session in shell_sessions] == ["session-shell", "session-pending"]
    assert [session.session_id for session in shell_inspect_sessions] == ["session-shell"]
    assert [session.session_id for session in shell_test_sessions] == ["session-pending"]


def test_list_recent_sessions_attention_sort_prioritizes_denied_test_approvals_before_other_failures(tmp_path: Path) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    _append_turn(plain_store, "plain")

    restored_test_pending_store = SessionArtifactStore(tmp_path, session_id="session-restored-pending-test")
    _append_turn(restored_test_pending_store, "resume restored tests")
    restored_test_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0011a",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="resume tests",
                restored_from_session=True,
            )
        ]
    )

    restored_edit_pending_store = SessionArtifactStore(tmp_path, session_id="session-restored-pending-edit")
    _append_turn(restored_edit_pending_store, "resume restored edit")
    restored_edit_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0011b",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
            )
        ]
    )

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    _append_turn(pending_store, "pending")
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0011",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    pending_edit_store = SessionArtifactStore(tmp_path, session_id="session-pending-edit")
    _append_turn(pending_edit_store, "pending edit")
    pending_edit_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0011c",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="write notes",
            )
        ]
    )

    denied_test_store = SessionArtifactStore(tmp_path, session_id="session-denied-test")
    denied_test_store.append_turn(
        TurnArtifact(
            prompt="deny risky test run",
            response="skipped",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_denied",
                    "run_shell_command",
                    "Denied in the TUI",
                    data={
                        "tool_name": "run_shell_command",
                        "approval_id": "approval-0010b",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "remaining_pending_count": 0,
                        "command": "pytest -q",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    denied_store = SessionArtifactStore(tmp_path, session_id="session-denied")
    denied_store.append_turn(
        TurnArtifact(
            prompt="deny risky write",
            response="skipped",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "steering_denied",
                    "write_file",
                    "Denied in the TUI",
                    data={
                        "tool_name": "write_file",
                        "approval_id": "approval-0010c",
                        "approval_status": "denied",
                        "approval_source": "fake_runtime",
                        "approval_restored": True,
                        "remaining_pending_count": 0,
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    failed_test_store = SessionArtifactStore(tmp_path, session_id="session-failed-test")
    failed_test_store.append_turn(
        TurnArtifact(
            prompt="run failing test",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_failed",
                    "run_shell_command",
                    "Shell test failed",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "pytest -q",
                        "shell_policy": "confirm",
                        "exit_code": 1,
                        "result_preview": "pytest -q -> exit 1",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    failed_tool_store = SessionArtifactStore(tmp_path, session_id="session-failed-tool")
    failed_tool_store.append_turn(
        TurnArtifact(
            prompt="attempt failing edit",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_failed",
                    "replace_text",
                    "Edit failed",
                    data={
                        "tool_name": "replace_text",
                        "result_preview": "replace_text notes.txt (2 occurrences)",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    restore_store = SessionArtifactStore(tmp_path, session_id="session-restore")
    _append_turn(restore_store, "restore")
    restore_store.save_session_state(SessionState(draft_prompt="draft"))

    inspect_store = SessionArtifactStore(tmp_path, session_id="session-inspect")
    inspect_store.append_turn(
        TurnArtifact(
            prompt="inspect repo",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "run_shell_command",
                    "Finished shell command",
                    data={
                        "tool_name": "run_shell_command",
                        "command": "git status --short",
                        "shell_policy": "inspect",
                        "exit_code": 0,
                        "result_preview": "git status --short -> M README.md",
                    },
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    tool_store = SessionArtifactStore(tmp_path, session_id="session-tool")
    tool_store.append_turn(
        TurnArtifact(
            prompt="list files",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                )
            ],
            response_metadata={"mode": "fake"},
        )
    )

    ordered = list_recent_sessions(tmp_path, sort_mode="attention", limit=count_recent_sessions(tmp_path))

    assert [session.session_id for session in ordered[:12]] == [
        "session-restored-pending-test",
        "session-restored-pending-edit",
        "session-pending",
        "session-pending-edit",
        "session-denied-test",
        "session-denied",
        "session-failed-test",
        "session-failed-tool",
        "session-restore",
        "session-inspect",
        "session-tool",
        "session-plain",
    ]
    assert ordered[0].attention_reason_summary == "restored pending test approval queue; tests sort ahead of restored edits"
    assert (
        ordered[1].attention_reason_summary
        == "restored pending edit approval queue; restored tests sort ahead of this queue"
    )
    assert ordered[2].attention_reason_summary == "pending test approval queue"
    assert ordered[3].attention_reason_summary == "pending edit approval queue; tests sort ahead of edits"
    assert ordered[4].attention_reason_summary == "denied test approval"
    assert ordered[5].attention_reason_summary == "restored denied edit approval"
    assert ordered[6].attention_reason_summary == "recent shell test failure"
    assert "attention: restored test queue" in ordered[0].render_line(1, include_attention_reason=True)
    assert "attention: restored edit queue" in ordered[1].render_line(2, include_attention_reason=True)
    assert "pending tools: test 1" in ordered[2].render_line(3, include_attention_reason=True)
    assert "attention: pending test" in ordered[2].render_line(3, include_attention_reason=True)
    assert "pending tools: edit 1" in ordered[3].render_line(4, include_attention_reason=True)
    assert "attention: pending edit" in ordered[3].render_line(4, include_attention_reason=True)
    assert "attention: denied test" in ordered[4].render_line(5, include_attention_reason=True)
    assert "attention: restored denied edit" in ordered[5].render_line(6, include_attention_reason=True)
    assert "attention: test fail" in ordered[6].render_line(7, include_attention_reason=True)
    assert "attention: tool fail" in ordered[7].render_line(8, include_attention_reason=True)
    assert "attention: restore" in ordered[8].render_line(9, include_attention_reason=True)
    assert ordered[9].attention_reason_summary == "recent shell activity"
    shell_line = ordered[9].render_line(10, include_attention_reason=True)
    assert "attention:" not in shell_line
    assert "shell: inspect 1" in shell_line
    shell_preview = "\n".join(ordered[9].render_preview(visible_index=10, overall_index=10, total_matches=len(ordered)))
    assert "- attention reason: recent shell activity" in shell_preview
    pending_preview = "\n".join(ordered[3].render_preview(visible_index=4, overall_index=4, total_matches=len(ordered)))
    assert "- pending tools: edit 1" in pending_preview
    assert "- attention reason: pending edit approval queue; tests sort ahead of edits" in pending_preview
    assert ordered[10].attention_reason_summary == "recent tool activity"
    tool_line = ordered[10].render_line(11, include_attention_reason=True)
    assert "attention:" not in tool_line
    assert "last tool: .: README.md" in tool_line
    tool_preview = "\n".join(ordered[10].render_preview(visible_index=11, overall_index=11, total_matches=len(ordered)))
    assert "- attention reason: recent tool activity" in tool_preview
    assert "attention:" not in ordered[0].render_line(1)

    approval_restore_ordered = list_recent_sessions(tmp_path, sort_mode="attention", filter_mode="approval-restore")
    assert [session.session_id for session in approval_restore_ordered] == [
        "session-restored-pending-test",
        "session-restored-pending-edit",
        "session-denied",
    ]


def test_list_recent_sessions_attention_sort_prefers_older_pending_approval_with_same_family(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    newer_pending_store = SessionArtifactStore(tmp_path, session_id="session-pending-newer")
    _append_turn(newer_pending_store, "newer pending")
    newer_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-age-newer",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
                created_at=(now - timedelta(days=3)).isoformat(),
            )
        ]
    )

    older_pending_store = SessionArtifactStore(tmp_path, session_id="session-pending-older")
    _append_turn(older_pending_store, "older pending")
    older_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-age-older",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
                created_at=(now - timedelta(days=14)).isoformat(),
            )
        ]
    )

    ordered = list_recent_sessions(tmp_path, sort_mode="attention", limit=count_recent_sessions(tmp_path))

    assert [summary.session_id for summary in ordered[:2]] == ["session-pending-older", "session-pending-newer"]
    assert ordered[0].pending_approval_age_summary == "14d"
    assert ordered[1].pending_approval_age_summary == "3d"


def test_list_recent_sessions_attention_sort_prefers_older_denied_approval_with_same_family(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    newer_denied_store = SessionArtifactStore(tmp_path, session_id="session-denied-newer")
    newer_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-denied-newer",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    newer_event.timestamp = (now - timedelta(hours=2)).isoformat()
    newer_denied_store.append_turn(
        TurnArtifact(
            prompt="deny newer test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[newer_event],
            response_metadata={"mode": "fake"},
        )
    )

    older_denied_store = SessionArtifactStore(tmp_path, session_id="session-denied-older")
    older_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-denied-older",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    older_event.timestamp = (now - timedelta(hours=11)).isoformat()
    older_denied_store.append_turn(
        TurnArtifact(
            prompt="deny older test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[older_event],
            response_metadata={"mode": "fake"},
        )
    )

    ordered = list_recent_sessions(
        tmp_path,
        sort_mode="attention",
        filter_mode="denied",
        limit=count_recent_sessions(tmp_path, filter_mode="denied", sort_mode="attention"),
    )

    assert [summary.session_id for summary in ordered[:2]] == ["session-denied-older", "session-denied-newer"]
    assert ordered[0].last_denied_approval_age_summary == "11h"
    assert ordered[1].last_denied_approval_age_summary == "2h"


def test_list_recent_sessions_broad_restore_filter_keeps_single_restore_queue_lane_in_age_copy(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-restored-queue-only")
    _append_turn(store, "resume restored queue")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restore-queue-only",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun restored tests",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
            )
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]
    restored_line = summary.render_line(1, filter_mode="approval-restore")
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )

    assert "approval restore age: restore queue 3d" in restored_line
    assert "restore focus:" not in restored_line
    assert "- approval restore age: restore queue 3d" in preview
    assert "- restore focus:" not in preview


def test_list_recent_sessions_broad_restore_filter_keeps_single_restored_lane_in_age_copy(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-restored-outcome-only")
    approved_event = runtime_event(
        "steering_approved",
        "replace_text",
        "Approved in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-restore-outcome-only",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
        },
    )
    approved_event.timestamp = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="review restored outcome",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[approved_event],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path)[0]
    restored_line = summary.render_line(1, filter_mode="approval-restore")
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-restore")
    )

    assert "approval restore age: restored 6h" in restored_line
    assert "restore focus:" not in restored_line
    assert "- approval restore age: restored 6h" in preview
    assert "- restore focus:" not in preview


def test_list_recent_sessions_broad_stale_filter_keeps_single_pending_lane_in_age_copy(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-stale-pending-only")
    _append_turn(store, "resume stale pending queue")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-pending-only",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun stale tests",
                created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
            )
        ]
    )

    summary = list_recent_sessions(tmp_path, filter_mode="approval-stale")[0]
    stale_line = summary.render_line(1, filter_mode="approval-stale")
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-stale")
    )

    assert "approval stale age: pending 45d" in stale_line
    assert "stale focus:" not in stale_line
    assert "approval stale age: 45d" not in stale_line
    assert "- approval stale age: pending 45d" in preview
    assert "- stale focus:" not in preview


def test_list_recent_sessions_broad_stale_filter_keeps_single_denied_lane_in_age_copy(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-stale-denied-only")
    denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied-only",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    denied_event.timestamp = (datetime.now(UTC) - timedelta(days=14)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="deny stale test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[denied_event],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path, filter_mode="approval-stale")[0]
    stale_line = summary.render_line(1, filter_mode="approval-stale")
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-stale")
    )

    assert "approval stale age: denied 14d" in stale_line
    assert "stale focus:" not in stale_line
    assert "approval stale age: 14d" not in stale_line
    assert "- approval stale age: denied 14d" in preview
    assert "- stale focus:" not in preview


def test_list_recent_sessions_broad_stale_filter_keeps_mixed_restored_lanes_in_age_copy(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-stale-restored-mixed")
    _append_turn(store, "resume stale restored queue")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-queue-only",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume stale edit",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=11)).isoformat(),
            )
        ]
    )
    approved_event = runtime_event(
        "steering_approved",
        "run_shell_command",
        "Approved in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-restored-outcome-only",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
            "command": "pytest -q",
        },
    )
    approved_event.timestamp = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="approve stale restored test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[approved_event],
            response_metadata={"mode": "fake"},
        )
    )

    summary = list_recent_sessions(tmp_path, filter_mode="approval-stale")[0]
    stale_line = summary.render_line(1, filter_mode="approval-stale")
    preview = "\n".join(
        summary.render_preview(visible_index=1, overall_index=1, total_matches=1, filter_mode="approval-stale")
    )

    assert "approval stale ages: restore queue 11d; restored 10d" in stale_line
    assert "stale focus:" not in stale_line
    assert "- approval stale ages: restore queue 11d; restored 10d" in preview
    assert "- stale focus:" not in preview
