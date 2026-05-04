from pathlib import Path

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import (
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionState,
    TurnArtifact,
    count_recent_sessions,
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
    assert "Picker controls: J/K preview, A all, P pending, R restore, T tool, S sort, [ prev page, ] next page" in rendered
    assert "Press Enter to start a new session." in rendered


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
    assert "1. session-demo" not in rendered


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
    inputs = iter(["p", "s", "j", "k", "1"])
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

    assert summary.last_tool_preview == "git status --short -> M README.md"
    assert summary.last_tool_badges == ["inspect", "e0"]
    assert "last tool: inspect/e0 git status --short -> M README.md" in summary.render_line(1)


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


def test_list_recent_sessions_can_filter_to_pending_restore_or_tool_triage(tmp_path: Path) -> None:
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

    restore_store = SessionArtifactStore(tmp_path, session_id="session-restore")
    _append_turn(restore_store, "resume triage")
    restore_store.save_session_state(SessionState(draft_prompt="queued follow-up"))

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

    pending_sessions = list_recent_sessions(tmp_path, filter_mode="pending")
    restore_sessions = list_recent_sessions(tmp_path, filter_mode="restore")
    tool_sessions = list_recent_sessions(tmp_path, filter_mode="tool")

    assert [session.session_id for session in pending_sessions] == ["session-pending"]
    assert [session.session_id for session in restore_sessions] == ["session-restore"]
    assert [session.session_id for session in tool_sessions] == ["session-tool"]


def test_list_recent_sessions_attention_sort_prioritizes_pending_and_restore_state(tmp_path: Path) -> None:
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
                request_id="approval-0011",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    ordered = list_recent_sessions(tmp_path, sort_mode="attention")

    assert [session.session_id for session in ordered[:3]] == [
        "session-pending",
        "session-restore",
        "session-plain",
    ]
