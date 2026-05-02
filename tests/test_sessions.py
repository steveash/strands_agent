from pathlib import Path

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import (
    SessionArtifactStore,
    SessionState,
    TurnArtifact,
    latest_session,
    list_recent_sessions,
    pick_session,
    render_session_picker,
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
            events=[runtime_event("tool_finished", "list_files", "Finished listing files")],
            response_metadata={"mode": "fake"},
        )
    )

    sessions = list_recent_sessions(tmp_path)

    assert [session.session_id for session in sessions[:2]] == ["session-newer", "session-older"]
    assert sessions[0].turn_count == 1
    assert sessions[0].last_prompt_preview.endswith("...")
    assert sessions[0].last_event_preview == "tool_finished: list_files"
    assert "turn(s)" in sessions[0].render_line(1)
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
    assert "1. session-demo" in rendered
    assert "Press Enter to start a new session." in rendered


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
        )
    )

    restored = store.load_session_state()

    assert restored is not None
    assert restored.event_filter == "tool"
    assert restored.history_focus_index == 2
    assert restored.draft_prompt == "summarize the failing test output"
    assert restored.session_switcher_active is True
    assert restored.session_switcher_selected_session_id == "session-target"
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
