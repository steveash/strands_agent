import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import (
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionPickerState,
    SessionState,
    TurnArtifact,
    count_recent_sessions,
    latest_session,
    list_recent_sessions,
    pick_session,
    render_session_picker,
    save_session_picker_state,
)


def _append_turn(store: SessionArtifactStore, prompt: str) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )


def _set_session_artifact_mtime(store: SessionArtifactStore, when: datetime) -> None:
    timestamp = when.timestamp()
    for path in [store.session_dir, *store.session_dir.iterdir()]:
        os.utime(path, (timestamp, timestamp))


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
    assert "approval restore age: 3d" in summaries[0].render_line(1)
    assert "- approval restore age: 3d" in "\n".join(
        summaries[0].render_preview(visible_index=1, overall_index=1, total_matches=1)
    )


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
    assert "approval restore age: 6h" in summaries[0].render_line(1)
    assert "- last restored age: 6h" in "\n".join(
        summaries[0].render_preview(visible_index=1, overall_index=1, total_matches=1)
    )


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
    stale_pending_store = SessionArtifactStore(tmp_path, session_id="session-stale-pending")
    _append_turn(stale_pending_store, "resume very old pending queue")
    stale_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
            )
        ]
    )

    stale_denied_store = SessionArtifactStore(tmp_path, session_id="session-stale-denied")
    stale_denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    stale_denied_event.timestamp = (datetime.now(UTC) - timedelta(days=9)).isoformat()
    stale_denied_store.append_turn(
        TurnArtifact(
            prompt="deny old test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[stale_denied_event],
            response_metadata={"mode": "fake"},
        )
    )

    stale_restored_store = SessionArtifactStore(tmp_path, session_id="session-stale-restored")
    _append_turn(stale_restored_store, "resume stale restored queue")
    stale_restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=8)).isoformat(),
            )
        ]
    )
    stale_restored_event = runtime_event(
        "steering_approved",
        "run_shell_command",
        "Approved in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-restored",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
            "command": "pytest -q",
        },
    )
    stale_restored_event.timestamp = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    stale_restored_store.append_turn(
        TurnArtifact(
            prompt="approve restored stale test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[stale_restored_event],
            response_metadata={"mode": "fake"},
        )
    )

    fresh_pending_store = SessionArtifactStore(tmp_path, session_id="session-fresh-pending")
    _append_turn(fresh_pending_store, "resume fresh queue")
    fresh_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-fresh-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            )
        ]
    )

    stale_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale")
    stale_by_id = {summary.session_id: summary for summary in stale_summaries}
    rendered = render_session_picker(tmp_path, filter_mode="approval-stale")

    assert set(stale_by_id) == {"session-stale-pending", "session-stale-denied", "session-stale-restored"}
    assert stale_by_id["session-stale-pending"].stale_approval_badges == ["pending 45d"]
    assert stale_by_id["session-stale-denied"].stale_approval_badges == ["denied 9d"]
    assert stale_by_id["session-stale-restored"].stale_approval_badges == ["restore queue 8d", "restored 10d"]
    assert "approval stale: pending 45d" in stale_by_id["session-stale-pending"].render_line(1)
    assert "stale focus: pending" in stale_by_id["session-stale-pending"].render_line(1, filter_mode="approval-stale")
    assert "approval stale: restore queue 8d, restored 10d" in stale_by_id["session-stale-restored"].render_line(1)
    stale_denied_preview = "\n".join(
        stale_by_id["session-stale-denied"].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=3,
            filter_mode="approval-stale",
        )
    )
    assert "- approval stale: denied 9d" in stale_denied_preview
    assert (
        "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
        in stale_denied_preview
    )
    stale_restored_preview = "\n".join(
        stale_by_id["session-stale-restored"].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=3,
            filter_mode="approval-stale",
        )
    )
    assert "- approval stale: restore queue 8d, restored 10d" in stale_restored_preview
    assert (
        "Stale approval backlog: 3 sessions | lanes: pending 1 (oldest 45d), denied 1 (oldest 9d), "
        "restore queue 1 (oldest 8d), restored 1 (oldest 10d)"
    ) in rendered
    assert (
        "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
        in rendered
    )


def test_stale_approval_filter_summarizes_current_page_and_off_page_lanes(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    for index in range(MAX_RECENT_SESSIONS):
        store = SessionArtifactStore(tmp_path, session_id=f"session-stale-pending-{index}")
        activity_time = now - timedelta(minutes=index)
        store.append_turn(
            TurnArtifact(
                prompt=f"resume stale pending queue {index}",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
                created_at=activity_time.isoformat(),
            )
        )
        store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id=f"approval-stale-pending-{index}",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="rerun tests",
                    created_at=(now - timedelta(days=45 + index)).isoformat(),
                )
            ]
        )
        _set_session_artifact_mtime(store, activity_time)

    denied_store = SessionArtifactStore(tmp_path, session_id="session-stale-denied-page-2")
    denied_activity_time = now - timedelta(minutes=100)
    denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied-page-2",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    denied_event.timestamp = (now - timedelta(days=14)).isoformat()
    denied_store.append_turn(
        TurnArtifact(
            prompt="deny stale page-two test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[denied_event],
            response_metadata={"mode": "fake"},
            created_at=denied_activity_time.isoformat(),
        )
    )
    _set_session_artifact_mtime(denied_store, denied_activity_time)

    restored_store = SessionArtifactStore(tmp_path, session_id="session-stale-restored-page-2")
    restored_activity_time = now - timedelta(minutes=101)
    restored_store.append_turn(
        TurnArtifact(
            prompt="resume stale restored page-two queue",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
            created_at=restored_activity_time.isoformat(),
        )
    )
    restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-page-2",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(now - timedelta(days=11)).isoformat(),
            )
        ]
    )
    _set_session_artifact_mtime(restored_store, restored_activity_time)

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
    stale_pending_store = SessionArtifactStore(tmp_path, session_id="session-stale-pending")
    _append_turn(stale_pending_store, "resume very old pending queue")
    stale_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
            )
        ]
    )

    stale_denied_store = SessionArtifactStore(tmp_path, session_id="session-stale-denied")
    stale_denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    stale_denied_event.timestamp = (datetime.now(UTC) - timedelta(days=9)).isoformat()
    stale_denied_store.append_turn(
        TurnArtifact(
            prompt="deny old test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[stale_denied_event],
            response_metadata={"mode": "fake"},
        )
    )

    stale_restored_queue_store = SessionArtifactStore(tmp_path, session_id="session-stale-restored-queue")
    _append_turn(stale_restored_queue_store, "resume stale restored queue")
    stale_restored_queue_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-queue",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=11)).isoformat(),
            )
        ]
    )

    stale_restored_store = SessionArtifactStore(tmp_path, session_id="session-stale-restored")
    _append_turn(stale_restored_store, "resume mixed stale restored queue")
    stale_restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-pending",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=10)).isoformat(),
            )
        ]
    )
    stale_restored_event = runtime_event(
        "steering_approved",
        "run_shell_command",
        "Approved in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-restored",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
            "command": "pytest -q",
        },
    )
    stale_restored_event.timestamp = (datetime.now(UTC) - timedelta(days=9)).isoformat()
    stale_restored_store.append_turn(
        TurnArtifact(
            prompt="approve restored old test rerun",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[stale_restored_event],
            response_metadata={"mode": "fake"},
        )
    )

    stale_pending_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-pending")
    stale_denied_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-denied")
    stale_restored_summaries = list_recent_sessions(tmp_path, filter_mode="approval-stale-restored")
    stale_restored_by_id = {summary.session_id: summary for summary in stale_restored_summaries}
    stale_pending_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-pending")
    stale_denied_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-denied")
    stale_restored_rendered = render_session_picker(tmp_path, filter_mode="approval-stale-restored")

    assert [summary.session_id for summary in stale_pending_summaries] == ["session-stale-pending"]
    assert [summary.session_id for summary in stale_denied_summaries] == ["session-stale-denied"]
    assert {summary.session_id for summary in stale_restored_summaries} == {
        "session-stale-restored-queue",
        "session-stale-restored",
    }
    mixed_stale_restored_preview = "\n".join(
        stale_restored_by_id["session-stale-restored"].render_preview(
            visible_index=1,
            overall_index=1,
            total_matches=2,
            filter_mode="approval-stale-restored",
        )
    )
    queue_stale_restored_preview = "\n".join(
        stale_restored_by_id["session-stale-restored-queue"].render_preview(
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
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

    assert summary.pending_approval_age_summary == "45d"
    assert summary.stale_session_badges == ["warning 10d"]
    assert summary.stale_session_summary == "idle 10d since last artifact activity"
    assert "pending age: 45d" in summary.render_line(1)
    assert "stale: warning 10d" in summary.render_line(1)
    assert "- pending age: 45d" in preview
    assert "- session age: idle 10d since last artifact activity" in preview


def test_list_recent_sessions_surfaces_pending_queue_first_vs_rest_breakdown(tmp_path: Path) -> None:
    store = SessionArtifactStore(tmp_path, session_id="session-pending-mixed")
    _append_turn(store, "queue mixed approvals")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0007a",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run pytest",
            ),
            ApprovalRequest(
                request_id="approval-0007b",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="queue edit",
            ),
            ApprovalRequest(
                request_id="approval-0007c",
                tool_name="list_files",
                reason="Needs confirmation",
                args={"relative_path": "."},
                source="fake_runtime",
                prompt="inspect tree",
            ),
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

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
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))

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
    store = SessionArtifactStore(tmp_path, session_id="session-restored-breakdown")
    denied_event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-9300",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "relative_path": "notes.txt",
        },
    )
    denied_event.timestamp = (datetime.now(UTC) - timedelta(hours=6, minutes=5)).isoformat()
    store.append_turn(
        TurnArtifact(
            prompt="restore denied edit and pending test",
            response="triaged restored approvals",
            provider="fake-strands",
            mode="fake",
            events=[denied_event],
            response_metadata={"mode": "fake"},
        )
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-9301",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun restored tests",
                restored_from_session=True,
                created_at=(datetime.now(UTC) - timedelta(days=3, hours=2)).isoformat(),
            )
        ]
    )

    summary = list_recent_sessions(tmp_path)[0]
    preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))
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
    assert "restored current: pending run_shell_command via fake_runtime; queued 1" in restored_line
    assert "restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0" in restored_line
    assert "- attention reason: restored pending test approval queue; tests sort ahead of restored edits" in preview
    assert "- approval restore: pending 1, denied 1" in preview
    assert "- approval restore tools: test 1, edit 1" in preview
    assert "- restored current approval: pending run_shell_command via fake_runtime | queued 1" in preview
    assert "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0" in preview
    assert "- latest restored outcome age: 6h" in preview
    assert (
        "Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d), restored 1 (oldest 6h) | overlap: mixed 1 session"
        in rendered
    )
    assert "Restore lane focus: restore queue, restored" in rendered


def test_render_session_picker_reports_approval_restore_page_rollups_when_backlog_spans_pages(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    for index in range(MAX_RECENT_SESSIONS):
        store = SessionArtifactStore(tmp_path, session_id=f"session-restored-queue-{index}")
        activity_time = now - timedelta(hours=index + 1)
        store.append_turn(
            TurnArtifact(
                prompt=f"resume restored queue {index}",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
                created_at=activity_time.isoformat(),
            )
        )
        store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id=f"approval-restored-queue-{index}",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt=f"rerun restored queue {index}",
                    restored_from_session=True,
                    created_at=(now - timedelta(days=11 + index)).isoformat(),
                )
            ]
        )
        _set_session_artifact_mtime(store, activity_time)

    restored_only_store = SessionArtifactStore(tmp_path, session_id="session-restored-outcome-page-2")
    restored_only_activity_time = now - timedelta(hours=10)
    restored_only_event = runtime_event(
        "steering_approved",
        "replace_text",
        "Approved in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-restored-outcome-page-2",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
        },
    )
    restored_only_event.timestamp = (now - timedelta(hours=8)).isoformat()
    restored_only_store.append_turn(
        TurnArtifact(
            prompt="review restored outcome only",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[restored_only_event],
            response_metadata={"mode": "fake"},
            created_at=restored_only_activity_time.isoformat(),
        )
    )
    _set_session_artifact_mtime(restored_only_store, restored_only_activity_time)

    mixed_store = SessionArtifactStore(tmp_path, session_id="session-restored-overlap-page-2")
    mixed_activity_time = now - timedelta(hours=11)
    mixed_event = runtime_event(
        "steering_denied",
        "write_file",
        "Denied in the TUI",
        data={
            "tool_name": "write_file",
            "approval_id": "approval-restored-overlap-page-2-outcome",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    mixed_event.timestamp = (now - timedelta(hours=6)).isoformat()
    mixed_store.append_turn(
        TurnArtifact(
            prompt="review mixed restored overlap",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[mixed_event],
            response_metadata={"mode": "fake"},
            created_at=mixed_activity_time.isoformat(),
        )
    )
    mixed_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restored-overlap-page-2-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun mixed restored tests",
                restored_from_session=True,
                created_at=(now - timedelta(days=3)).isoformat(),
            )
        ]
    )
    _set_session_artifact_mtime(mixed_store, mixed_activity_time)

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
    store = SessionArtifactStore(tmp_path, session_id="session-restored-pending-mixed")
    _append_turn(store, "reopen restored approval queue")
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-9310",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun restored tests",
                restored_from_session=True,
            ),
            ApprovalRequest(
                request_id="approval-9311",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume restored edit",
                restored_from_session=True,
            ),
            ApprovalRequest(
                request_id="approval-9312",
                tool_name="list_files",
                reason="Needs confirmation",
                args={"relative_path": "."},
                source="fake_runtime",
                prompt="resume restored inspection",
                restored_from_session=True,
            ),
        ]
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
