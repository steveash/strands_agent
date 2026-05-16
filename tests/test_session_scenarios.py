from datetime import UTC, datetime, timedelta
from pathlib import Path

from strands_agent_tui.sessions import SessionArtifactStore, list_recent_sessions
from strands_agent_tui.testing import (
    seed_restore_state_session,
    seed_shell_failure_session,
    seed_shell_test_session,
    seed_workspace_failure_session,
    set_session_artifact_mtime,
)


def _summary_by_id(root: Path, session_id: str):
    return next(summary for summary in list_recent_sessions(root) if summary.session_id == session_id)


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
