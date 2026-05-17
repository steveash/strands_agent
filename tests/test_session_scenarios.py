from datetime import UTC, datetime, timedelta
from pathlib import Path

from strands_agent_tui.runtime import runtime_event
from strands_agent_tui.sessions import (
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionState,
    count_recent_sessions,
    list_recent_sessions,
)
from strands_agent_tui.sessions.picker import (
    APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
    _approval_restore_lane_age_seconds,
    _approval_restore_lanes,
    _summarize_lane_activity,
    _summarize_shell_lanes,
    _summarize_workspace_lanes,
)
from strands_agent_tui.testing import (
    seed_denied_approval_session,
    seed_approval_restore_focus_scenario,
    seed_approval_restore_overlap_session,
    seed_approval_restore_rollup_scenario,
    seed_denied_approval_rollup_scenario,
    seed_pending_approval_session,
    seed_pending_approval_rollup_scenario,
    seed_plain_session,
    seed_restore_state_session,
    seed_shell_failure_session,
    seed_shell_inspect_session,
    seed_shell_overlap_session,
    seed_shell_test_session,
    seed_stale_approval_filter_scenario,
    seed_stale_approval_rollup_scenario,
    seed_stale_approval_subfilter_scenario,
    seed_workspace_edit_session,
    seed_workspace_failure_session,
    seed_workspace_inspect_session,
    seed_workspace_overlap_session,
    set_session_artifact_mtime,
)


def _summary_by_id(root: Path, session_id: str, *, filter_mode: str = "all"):
    summaries = list_recent_sessions(
        root,
        filter_mode=filter_mode,
        limit=count_recent_sessions(root, filter_mode=filter_mode),
    )
    return next(summary for summary in summaries if summary.session_id == session_id)


def test_seed_plain_session_persists_single_turn_summary(tmp_path: Path) -> None:
    store = seed_plain_session(tmp_path)

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, store.session_id)

    assert len(turns) == 1
    assert turns[0].prompt == "inspect the plain artifact set"
    assert turns[0].response == "ok"
    assert summary.turn_count == 1
    assert summary.last_prompt_preview == "inspect the plain artifact set"
    assert "last prompt: inspect the plain artifact set" in summary.render_line(1)


def test_seed_workspace_inspect_session_persists_tool_metadata_and_summary(tmp_path: Path) -> None:
    store = seed_workspace_inspect_session(tmp_path)

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="workspace-inspect")

    assert len(turns) == 1
    assert len(turns[0].events) == 1
    event = turns[0].events[0]
    assert event.kind == "tool_finished"
    assert event.title == "list_files"
    assert event.detail == "Finished listing files"
    assert event.data["tool_name"] == "list_files"
    assert event.data["result_preview"] == ".: README.md"
    assert summary.has_workspace_inspect_activity is True
    assert summary.workspace_lane_badges == ["inspect"]
    assert "workspace lanes: inspect" in summary.render_line(1)


def test_seed_workspace_edit_session_persists_pending_edit_metadata_and_summary(tmp_path: Path) -> None:
    store = seed_workspace_edit_session(tmp_path)

    pending = store.load_pending_approvals()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="workspace-edit")

    assert len(pending) == 1
    assert pending[0].tool_name == "replace_text"
    assert pending[0].args == {
        "relative_path": "notes.txt",
        "old_text": "old",
        "new_text": "new",
    }
    assert summary.pending_approval_count == 1
    assert summary.pending_approval_tool == "replace_text"
    assert summary.has_workspace_edit_activity is True
    assert summary.workspace_lane_badges == ["edit"]
    assert "pending: replace_text" in summary.render_line(1)
    assert "workspace lanes: edit" in summary.render_line(1)


def test_seed_shell_inspect_session_persists_shell_metadata_and_summary(tmp_path: Path) -> None:
    store = seed_shell_inspect_session(tmp_path)

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="shell-inspect")

    assert len(turns) == 1
    assert len(turns[0].events) == 1
    event = turns[0].events[0]
    assert event.kind == "tool_finished"
    assert event.title == "run_shell_command"
    assert event.detail == "Finished shell command"
    assert event.data["command"] == "git status --short"
    assert event.data["shell_policy"] == "inspect"
    assert event.data["result_preview"] == "git status --short -> M README.md"
    assert summary.has_shell_inspect_activity is True
    assert summary.shell_activity_badges == ["inspect 1"]
    assert summary.shell_lane_badges == []
    assert "shell: inspect 1" in summary.render_line(1)
    assert "last tool: inspect/e0 git status --short -> M README.md" in summary.render_line(1)


def test_seed_pending_approval_session_persists_pending_intervention_and_restore_summary(tmp_path: Path) -> None:
    state = SessionState(event_filter="tool", history_focus_index=0, draft_prompt="draft next step")
    store = seed_pending_approval_session(
        tmp_path,
        extra_events=[
            runtime_event(
                "tool_finished",
                "list_files",
                "Finished listing files",
                data={"tool_name": "list_files", "result_preview": ".: README.md"},
            )
        ],
        session_state=state,
    )

    turns = store.load_turns()
    pending = store.load_pending_approvals()
    restored_state = store.load_session_state()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="pending")

    assert len(turns) == 1
    assert len(turns[0].events) == 4
    assert len(pending) == 1
    assert pending[0].tool_name == "run_shell_command"
    assert pending[0].args == {"command": "pytest -q"}
    assert restored_state is not None
    assert restored_state.event_filter == state.event_filter
    assert restored_state.history_focus_index == state.history_focus_index
    assert restored_state.draft_prompt == state.draft_prompt
    assert len(restored_state.pending_approvals) == 1
    assert restored_state.pending_approvals[0].request_id == pending[0].request_id
    assert summary.pending_approval_count == 1
    assert summary.pending_approval_tool == "run_shell_command"
    assert summary.approval_status_badges == ["pending 1", "approved 1"]
    assert summary.intervention_badges == ["pending 1", "approved 1"]
    assert summary.has_intervention_activity is True
    assert summary.has_shell_inspect_activity is True
    assert summary.restore_badges == ["filter=tool", "replay 1/1", "draft 15c"]
    rendered = summary.render_line(1)
    assert "pending: run_shell_command" in rendered
    assert "pending tools: test 1" in rendered
    assert "approvals: pending 1, approved 1" in rendered
    assert "approval focus: pending" in rendered
    assert "shell: inspect 1" in rendered
    assert "shell lanes: inspect, test" in rendered
    assert "restore: filter=tool, replay 1/1, draft 15c" in rendered


def test_seed_denied_approval_session_persists_denied_intervention_summary(tmp_path: Path) -> None:
    store = seed_denied_approval_session(tmp_path)

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="denied")

    assert len(turns) == 1
    assert len(turns[0].events) == 1
    event = turns[0].events[0]
    assert event.kind == "steering_denied"
    assert event.title == "run_shell_command"
    assert event.detail == "Denied in the TUI"
    assert event.data["approval_id"] == "approval-0008"
    assert event.data["approval_status"] == "denied"
    assert event.data["approval_source"] == "fake_runtime"
    assert event.data["command"] == "pytest -q"
    assert summary.denied_approval_count == 1
    assert summary.denied_approval_badges == ["test 1"]
    assert summary.intervention_badges == ["denied 1"]
    assert summary.has_intervention_activity is True
    rendered = summary.render_line(1)
    assert "denied: test 1" in rendered
    assert "intervention: denied 1" in rendered


def test_seed_pending_approval_session_supports_minimal_custom_stale_bootstrap(tmp_path: Path) -> None:
    pending_created_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    store = seed_pending_approval_session(
        tmp_path,
        session_id="session-custom-threshold",
        prompt="resume moderately old pending queue",
        pending_request_id="approval-custom-threshold",
        pending_created_at=pending_created_at,
        approved_request_id=None,
        include_confirmation_event=False,
        shell_command=None,
    )

    turns = store.load_turns()
    pending = store.load_pending_approvals()
    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="pending")

    assert len(turns) == 1
    assert turns[0].events == []
    assert len(pending) == 1
    assert pending[0].request_id == "approval-custom-threshold"
    assert pending[0].created_at == pending_created_at
    assert summary.pending_approval_count == 1
    assert summary.pending_approval_tool == "run_shell_command"
    assert summary.has_shell_inspect_activity is False
    assert summary.intervention_badges == ["pending 1"]
    rendered = summary.render_line(1)
    assert "pending: run_shell_command" in rendered
    assert "pending age: 2d" in rendered
    assert "approvals: pending 1" in rendered
    assert "approval focus: pending" in rendered
    assert "intervention: pending 1" in rendered
    assert "shell:" not in rendered


def test_seed_restore_state_session_persists_restore_state_and_summary(tmp_path: Path) -> None:
    draft_prompt = "draft restore"
    store = seed_restore_state_session(
        tmp_path,
        session_id="session-restore",
        prompt="restore prompt",
        response="restore response",
        draft_prompt=draft_prompt,
    )

    turns = store.load_turns()
    state = store.load_session_state()
    summary = _summary_by_id(tmp_path, "session-restore")

    assert len(turns) == 1
    assert turns[0].prompt == "restore prompt"
    assert turns[0].response == "restore response"
    assert state is not None
    assert state.draft_prompt == draft_prompt
    assert state.pending_approvals == []
    assert summary.restore_badges == [f"draft {len(draft_prompt)}c"]
    assert summary.draft_prompt_preview == draft_prompt
    assert f"restore: draft {len(draft_prompt)}c" in summary.render_line(1)


def test_seed_shell_failure_session_persists_shell_failure_metadata_and_summary(tmp_path: Path) -> None:
    store = seed_shell_failure_session(
        tmp_path,
        session_id="session-shell-fail",
        prompt="run failing test",
        response="done",
        command="pytest -q",
        shell_policy="confirm",
        exit_code=1,
        result_preview="pytest -q -> exit 1",
        event_message="Shell test failed",
    )

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, "session-shell-fail")

    assert len(turns) == 1
    assert len(turns[0].events) == 1
    event = turns[0].events[0]
    assert event.kind == "tool_failed"
    assert event.title == "run_shell_command"
    assert event.detail == "Shell test failed"
    assert event.data["command"] == "pytest -q"
    assert event.data["shell_policy"] == "confirm"
    assert event.data["exit_code"] == 1
    assert event.data["result_preview"] == "pytest -q -> exit 1"
    assert summary.failure_activity_badges == ["test 1"]
    rendered = summary.render_line(1, include_attention_reason=True)
    assert "attention: test fail" in rendered
    assert "last tool: confirm/e1 pytest -q -> exit 1" in rendered
    assert "shell: test 1, fail 1" in rendered
    assert "failures: test 1" in rendered


def test_seed_workspace_failure_session_persists_workspace_failure_metadata_and_summary(tmp_path: Path) -> None:
    store = seed_workspace_failure_session(
        tmp_path,
        session_id="session-workspace-fail",
        prompt="attempt failing edit",
        response="done",
        tool_name="replace_text",
        event_message="Edit failed",
        result_preview="replace_text notes.txt (2 occurrences)",
    )

    turns = store.load_turns()
    summary = _summary_by_id(tmp_path, "session-workspace-fail")

    assert len(turns) == 1
    assert len(turns[0].events) == 1
    event = turns[0].events[0]
    assert event.kind == "tool_failed"
    assert event.title == "replace_text"
    assert event.detail == "Edit failed"
    assert event.data["tool_name"] == "replace_text"
    assert event.data["result_preview"] == "replace_text notes.txt (2 occurrences)"
    assert summary.failure_activity_badges == ["tool 1"]
    rendered = summary.render_line(1, include_attention_reason=True)
    assert "attention: tool fail" in rendered
    assert "last tool: failed replace_text notes.txt (2 occurrences)" in rendered
    assert "workspace lanes: edit" in rendered
    assert "failures: tool 1" in rendered


def test_seed_shell_test_session_and_artifact_mtime_support_stale_turn_scenarios(tmp_path: Path) -> None:
    approval_created_at = datetime.now(UTC) - timedelta(days=45)
    turn_created_at = datetime.now(UTC) - timedelta(days=10)
    store = seed_shell_test_session(
        tmp_path,
        session_id="session-stale",
        prompt="queue shell test",
        response="ok",
        request_id="approval-stale",
        approval_prompt="rerun old tests",
        created_at=approval_created_at.isoformat(),
        turn_created_at=turn_created_at.isoformat(),
    )
    set_session_artifact_mtime(store, turn_created_at)

    turns = store.load_turns()
    pending = store.load_pending_approvals()
    summary = _summary_by_id(tmp_path, "session-stale")

    assert len(turns) == 1
    assert turns[0].created_at == turn_created_at.isoformat()
    assert len(pending) == 1
    assert pending[0].created_at == approval_created_at.isoformat()
    touched_paths = [store.session_dir, *store.session_dir.iterdir()]
    expected_mtime = int(turn_created_at.timestamp())
    assert all(int(path.stat().st_mtime) == expected_mtime for path in touched_paths)
    assert summary.pending_approval_age_summary == "45d"
    assert summary.stale_session_summary == "idle 10d since last artifact activity"
    rendered = summary.render_line(1, include_attention_reason=True)
    assert "pending age: 45d" in rendered
    assert "approval stale: pending 45d" in rendered
    assert "stale: warning 10d" in rendered
    assert "attention: pending test" in rendered


def test_seed_approval_restore_overlap_session_persists_lane_counts_and_age_rollups(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = seed_approval_restore_overlap_session(tmp_path, now=now)

    summary = _summary_by_id(tmp_path, store.session_id, filter_mode="approval-restore")
    rollup = _summarize_lane_activity(
        [summary],
        display_order=APPROVAL_RESTORE_LANE_DISPLAY_ORDER,
        lane_getter=_approval_restore_lanes,
        age_getter=_approval_restore_lane_age_seconds,
        include_mixed_count=True,
    )

    assert len(store.load_pending_approvals()) == 1
    assert store.load_pending_approvals()[0].restored_from_session is True
    assert len(store.load_turns()[-1].events) == 1
    assert store.load_turns()[-1].events[0].data["approval_restored"] is True
    assert summary.restored_pending_approval_age_summary == "3d"
    assert summary.last_restored_outcome_age_summary == "6h"
    assert summary.restored_approval_badges == ["pending 1", "denied 1"]
    assert summary.restored_approval_tool_badges == ["test 1", "edit 1"]
    assert rollup.lane_counts == {"restore queue": 1, "restored": 1}
    assert rollup.lane_oldest_ages == {
        "restore queue": int(timedelta(days=3, hours=2).total_seconds()),
        "restored": int(timedelta(hours=6, minutes=5).total_seconds()),
    }
    assert rollup.mixed_count == 1
    assert "approval restore ages: restore queue 3d; restored 6h" in summary.render_line(
        1, filter_mode="approval-restore"
    )


def test_seed_workspace_overlap_session_persists_workspace_lane_overlap_rollups(tmp_path: Path) -> None:
    seed_workspace_inspect_session(tmp_path)
    overlap_store = seed_workspace_overlap_session(tmp_path)
    seed_workspace_edit_session(tmp_path)

    inspect_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="workspace-inspect",
        limit=count_recent_sessions(tmp_path, filter_mode="workspace-inspect"),
    )
    edit_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="workspace-edit",
        limit=count_recent_sessions(tmp_path, filter_mode="workspace-edit"),
    )
    overlap_summary = _summary_by_id(tmp_path, overlap_store.session_id, filter_mode="workspace-inspect")

    assert {summary.session_id for summary in inspect_summaries} == {
        overlap_store.session_id,
        "session-workspace-inspect",
    }
    assert {summary.session_id for summary in edit_summaries} == {
        overlap_store.session_id,
        "session-workspace-edit",
    }
    assert _summarize_workspace_lanes(inspect_summaries) == ({"inspect": 2, "edit": 1}, 1)
    assert _summarize_workspace_lanes(edit_summaries) == ({"inspect": 1, "edit": 2}, 1)
    assert overlap_summary.has_workspace_inspect_activity is True
    assert overlap_summary.has_workspace_edit_activity is True
    assert "workspace lanes: inspect, edit" in overlap_summary.render_line(1)


def test_seed_shell_overlap_session_persists_shell_lane_overlap_rollups(tmp_path: Path) -> None:
    seed_shell_inspect_session(tmp_path)
    overlap_store = seed_shell_overlap_session(tmp_path)
    seed_shell_test_session(tmp_path)

    shell_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="shell",
        limit=count_recent_sessions(tmp_path, filter_mode="shell"),
    )
    inspect_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="shell-inspect",
        limit=count_recent_sessions(tmp_path, filter_mode="shell-inspect"),
    )
    test_summaries = list_recent_sessions(
        tmp_path,
        filter_mode="shell-test",
        limit=count_recent_sessions(tmp_path, filter_mode="shell-test"),
    )
    overlap_summary = _summary_by_id(tmp_path, overlap_store.session_id, filter_mode="shell")

    assert {summary.session_id for summary in shell_summaries} == {
        overlap_store.session_id,
        "session-shell-test",
        "session-shell-inspect",
    }
    assert {summary.session_id for summary in inspect_summaries} == {
        overlap_store.session_id,
        "session-shell-inspect",
    }
    assert {summary.session_id for summary in test_summaries} == {
        overlap_store.session_id,
        "session-shell-test",
    }
    assert _summarize_shell_lanes(shell_summaries) == ({"inspect": 2, "test": 2}, 1)
    assert _summarize_shell_lanes(inspect_summaries) == ({"inspect": 2, "test": 1}, 1)
    assert _summarize_shell_lanes(test_summaries) == ({"inspect": 1, "test": 2}, 1)
    assert overlap_summary.has_shell_inspect_activity is True
    assert overlap_summary.has_shell_test_activity is True
    assert "shell lanes: inspect, test" in overlap_summary.render_line(1)


def test_seed_approval_restore_focus_scenario_persists_queue_and_outcome_lane_metadata(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_approval_restore_focus_scenario(tmp_path, now=now)

    total = count_recent_sessions(tmp_path, filter_mode="approval-restore")
    summaries = list_recent_sessions(
        tmp_path,
        filter_mode="approval-restore",
        limit=total,
    )
    restored_pending_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_pending_id)
    restored_edit_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_edit_pending_id)
    restored_outcome_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_outcome_id)
    restored_pending_summary = _summary_by_id(tmp_path, scenario.restored_pending_id, filter_mode="approval-restore")
    restored_edit_summary = _summary_by_id(tmp_path, scenario.restored_edit_pending_id, filter_mode="approval-restore")
    restored_outcome_summary = _summary_by_id(tmp_path, scenario.restored_outcome_id, filter_mode="approval-restore")

    assert total == 3
    assert {summary.session_id for summary in summaries} == {
        scenario.restored_pending_id,
        scenario.restored_edit_pending_id,
        scenario.restored_outcome_id,
    }
    assert restored_pending_store.load_pending_approvals()[0].restored_from_session is True
    assert restored_pending_summary.restored_pending_approval_age_summary == "3d"
    assert not restored_pending_summary.last_restored_outcome_age_summary
    assert restored_pending_summary.restored_approval_badges == ["pending 1"]
    assert restored_pending_summary.restored_approval_tool_badges == ["test 1"]
    assert "approval restore age: restore queue 3d" in restored_pending_summary.render_line(
        1,
        filter_mode="approval-restore",
    )
    assert restored_edit_store.load_pending_approvals()[0].restored_from_session is True
    assert not restored_edit_summary.restored_pending_approval_age_summary
    assert restored_edit_summary.restored_approval_badges == ["pending 1"]
    assert restored_edit_summary.restored_approval_tool_badges == ["edit 1"]
    assert restored_outcome_store.load_turns()[-1].events[0].data["approval_restored"] is True
    assert not restored_outcome_summary.restored_pending_approval_age_summary
    assert restored_outcome_summary.last_restored_outcome_age_summary == "6h"
    assert restored_outcome_summary.restored_approval_badges == ["denied 1"]
    assert restored_outcome_summary.restored_approval_tool_badges == ["edit 1"]
    assert "approval restore age: restored 6h" in restored_outcome_summary.render_line(
        1,
        filter_mode="approval-restore",
    )



def test_seed_pending_approval_rollup_scenario_persists_page_two_queue_counts_and_ages(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_pending_approval_rollup_scenario(tmp_path, now=now)

    total = count_recent_sessions(tmp_path, filter_mode="pending")
    page_two = list_recent_sessions(
        tmp_path,
        filter_mode="pending",
        limit=MAX_RECENT_SESSIONS,
        offset=MAX_RECENT_SESSIONS,
    )
    restored_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_id)
    multi_store = SessionArtifactStore(tmp_path, session_id=scenario.multi_id)
    restored_summary = _summary_by_id(tmp_path, scenario.restored_id, filter_mode="pending")
    multi_summary = _summary_by_id(tmp_path, scenario.multi_id, filter_mode="pending")

    assert total == MAX_RECENT_SESSIONS + 2
    assert [summary.session_id for summary in page_two] == [scenario.restored_id, scenario.multi_id]
    assert len(restored_store.load_pending_approvals()) == 1
    assert restored_store.load_pending_approvals()[0].restored_from_session is True
    assert restored_summary.pending_approval_count == 1
    assert restored_summary.pending_approval_age_summary == "3d"
    assert restored_summary.restored_pending_approval_age_summary == "3d"
    assert restored_summary.restored_approval_badges == ["pending 1"]
    assert len(multi_store.load_pending_approvals()) == 2
    assert multi_summary.pending_approval_count == 2
    assert multi_summary.pending_approval_age_summary == "oldest 2d"
    assert multi_summary.pending_approval_queue_summary == "first test; rest edit 1"
    assert "pending: 2 approvals (first test; rest edit 1)" in multi_summary.render_line(1)


def test_seed_denied_approval_rollup_scenario_persists_page_two_denial_counts_and_ages(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_denied_approval_rollup_scenario(tmp_path, now=now)

    total = count_recent_sessions(tmp_path, filter_mode="denied")
    page_two = list_recent_sessions(
        tmp_path,
        filter_mode="denied",
        limit=MAX_RECENT_SESSIONS,
        offset=MAX_RECENT_SESSIONS,
    )
    restored_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_id)
    edit_store = SessionArtifactStore(tmp_path, session_id=scenario.edit_id)
    restored_summary = _summary_by_id(tmp_path, scenario.restored_id, filter_mode="denied")
    edit_summary = _summary_by_id(tmp_path, scenario.edit_id, filter_mode="denied")

    assert total == MAX_RECENT_SESSIONS + 2
    assert [summary.session_id for summary in page_two] == [scenario.restored_id, scenario.edit_id]
    assert restored_store.load_turns()[-1].events[0].data["approval_restored"] is True
    assert restored_summary.last_denied_approval_age_summary == "3d"
    assert restored_summary.last_restored_outcome_age_summary == "3d"
    assert restored_summary.restored_approval_badges == ["denied 1"]
    assert edit_store.load_turns()[-1].events[0].data.get("approval_restored") is not True
    assert edit_summary.last_denied_approval_age_summary == "2d"
    assert "denied: edit 1" in edit_summary.render_line(1)


def test_seed_approval_restore_rollup_scenario_persists_page_two_restore_counts_and_ages(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_approval_restore_rollup_scenario(tmp_path, now=now)

    total = count_recent_sessions(tmp_path, filter_mode="approval-restore")
    page_two = list_recent_sessions(
        tmp_path,
        filter_mode="approval-restore",
        limit=MAX_RECENT_SESSIONS,
        offset=MAX_RECENT_SESSIONS,
    )
    outcome_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_outcome_id)
    mixed_store = SessionArtifactStore(tmp_path, session_id=scenario.mixed_id)
    queue_tail_summary = _summary_by_id(tmp_path, f"{scenario.queue_prefix}-7", filter_mode="approval-restore")
    outcome_summary = _summary_by_id(tmp_path, scenario.restored_outcome_id, filter_mode="approval-restore")
    mixed_summary = _summary_by_id(tmp_path, scenario.mixed_id, filter_mode="approval-restore")

    assert total == MAX_RECENT_SESSIONS + 2
    assert [summary.session_id for summary in page_two] == [scenario.restored_outcome_id, scenario.mixed_id]
    assert len(outcome_store.load_turns()[-1].events) == 1
    assert outcome_summary.last_restored_outcome_age_summary == "8h"
    assert outcome_summary.restored_approval_badges == ["approved 1"]
    assert queue_tail_summary.restored_pending_approval_age_summary == "18d"
    assert len(mixed_store.load_pending_approvals()) == 1
    assert mixed_store.load_pending_approvals()[0].restored_from_session is True
    assert mixed_summary.restored_pending_approval_age_summary == "3d"
    assert mixed_summary.last_restored_outcome_age_summary == "6h"
    assert mixed_summary.restored_approval_badges == ["pending 1", "denied 1"]
    assert mixed_summary.restored_approval_tool_badges == ["test 1", "edit 1"]
    assert "approval restore ages: restore queue 3d; restored 6h" in mixed_summary.render_line(1, filter_mode="approval-restore")



def test_seed_stale_approval_filter_scenario_persists_broad_stale_lane_metadata(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_stale_approval_filter_scenario(tmp_path, now=now)

    stale_total = count_recent_sessions(tmp_path, filter_mode="approval-stale")
    stale_ids = {
        summary.session_id
        for summary in list_recent_sessions(
            tmp_path,
            filter_mode="approval-stale",
            limit=stale_total,
        )
    }
    pending_summary = _summary_by_id(tmp_path, scenario.pending_id, filter_mode="approval-stale")
    denied_summary = _summary_by_id(tmp_path, scenario.denied_id, filter_mode="approval-stale")
    restored_summary = _summary_by_id(tmp_path, scenario.restored_id, filter_mode="approval-stale")

    assert stale_total == 3
    assert stale_ids == {scenario.pending_id, scenario.denied_id, scenario.restored_id}
    assert scenario.fresh_pending_id not in stale_ids
    assert pending_summary.pending_approval_age_summary == "45d"
    assert denied_summary.last_denied_approval_age_summary == "9d"
    assert restored_summary.restored_pending_approval_age_summary == "8d"
    assert restored_summary.last_restored_outcome_age_summary == "10d"
    assert restored_summary.restored_approval_badges == ["pending 1", "approved 1"]
    assert "approval stale age: pending 45d" in pending_summary.render_line(1, filter_mode="approval-stale")
    assert "approval stale age: denied 9d" in denied_summary.render_line(1, filter_mode="approval-stale")
    assert "approval stale ages: restore queue 8d; restored 10d" in restored_summary.render_line(
        1, filter_mode="approval-stale"
    )



def test_seed_stale_approval_subfilter_scenario_persists_focused_stale_lane_metadata(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_stale_approval_subfilter_scenario(tmp_path, now=now)

    pending_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-pending")
    denied_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-denied")
    restored_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-restored")
    pending_summary = _summary_by_id(tmp_path, scenario.pending_id, filter_mode="approval-stale-pending")
    denied_summary = _summary_by_id(tmp_path, scenario.denied_id, filter_mode="approval-stale-denied")
    restored_queue_summary = _summary_by_id(
        tmp_path,
        scenario.restored_queue_id,
        filter_mode="approval-stale-restored",
    )
    restored_mixed_summary = _summary_by_id(
        tmp_path,
        scenario.restored_mixed_id,
        filter_mode="approval-stale-restored",
    )

    assert pending_total == 1
    assert denied_total == 1
    assert restored_total == 2
    assert pending_summary.pending_approval_age_summary == "45d"
    assert denied_summary.last_denied_approval_age_summary == "9d"
    assert restored_queue_summary.restored_pending_approval_age_summary == "11d"
    assert not restored_queue_summary.last_restored_outcome_age_summary
    assert restored_mixed_summary.restored_pending_approval_age_summary == "10d"
    assert restored_mixed_summary.last_restored_outcome_age_summary == "9d"
    assert "approval stale age: 45d" in pending_summary.render_line(1, filter_mode="approval-stale-pending")
    assert "stale focus: pending" in pending_summary.render_line(1, filter_mode="approval-stale-pending")
    assert "approval stale age: 9d" in denied_summary.render_line(1, filter_mode="approval-stale-denied")
    assert "stale focus: denied" in denied_summary.render_line(1, filter_mode="approval-stale-denied")
    assert "approval stale age: 11d" in restored_queue_summary.render_line(1, filter_mode="approval-stale-restored")
    assert "stale focus: restore queue" in restored_queue_summary.render_line(1, filter_mode="approval-stale-restored")
    assert "approval stale ages: restore queue 10d; restored 9d" in restored_mixed_summary.render_line(
        1, filter_mode="approval-stale-restored"
    )
    assert "stale focus: restore queue, restored" in restored_mixed_summary.render_line(
        1, filter_mode="approval-stale-restored"
    )



def test_seed_stale_approval_rollup_scenario_persists_page_two_stale_counts_and_ages(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    scenario = seed_stale_approval_rollup_scenario(tmp_path, now=now, include_restored_outcome=True)

    stale_total = count_recent_sessions(tmp_path, filter_mode="approval-stale")
    pending_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-pending")
    denied_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-denied")
    restored_total = count_recent_sessions(tmp_path, filter_mode="approval-stale-restored")
    page_two = list_recent_sessions(
        tmp_path,
        filter_mode="approval-stale",
        limit=MAX_RECENT_SESSIONS,
        offset=MAX_RECENT_SESSIONS,
    )
    denied_store = SessionArtifactStore(tmp_path, session_id=scenario.denied_id)
    restored_store = SessionArtifactStore(tmp_path, session_id=scenario.restored_id)
    newest_pending_summary = _summary_by_id(tmp_path, f"{scenario.pending_prefix}-0", filter_mode="approval-stale")
    oldest_pending_summary = _summary_by_id(tmp_path, f"{scenario.pending_prefix}-7", filter_mode="approval-stale")
    denied_summary = _summary_by_id(tmp_path, scenario.denied_id, filter_mode="approval-stale")
    restored_summary = _summary_by_id(tmp_path, scenario.restored_id, filter_mode="approval-stale")

    assert stale_total == MAX_RECENT_SESSIONS + 2
    assert pending_total == MAX_RECENT_SESSIONS
    assert denied_total == 1
    assert restored_total == 1
    assert [summary.session_id for summary in page_two] == [scenario.denied_id, scenario.restored_id]
    assert len(denied_store.load_turns()[-1].events) == 1
    assert len(restored_store.load_pending_approvals()) == 1
    assert restored_store.load_pending_approvals()[0].restored_from_session is True
    assert len(restored_store.load_turns()[-1].events) == 1
    assert newest_pending_summary.pending_approval_age_summary == "45d"
    assert oldest_pending_summary.pending_approval_age_summary == "52d"
    assert denied_summary.last_denied_approval_age_summary == "14d"
    assert restored_summary.pending_approval_age_summary == "11d"
    assert restored_summary.restored_pending_approval_age_summary == "11d"
    assert restored_summary.last_restored_outcome_age_summary == "10d"
    assert restored_summary.restored_approval_badges == ["pending 1", "approved 1"]
    assert "approval stale age: denied 14d" in denied_summary.render_line(1, filter_mode="approval-stale")
    assert "approval stale ages: restore queue 11d; restored 10d" in restored_summary.render_line(
        1, filter_mode="approval-stale"
    )
