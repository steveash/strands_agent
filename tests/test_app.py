import json
import sys
from pathlib import Path

import pytest
from textual.widgets import Input

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.app import parse_args
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import MAX_RECENT_SESSIONS, SessionArtifactStore, TurnArtifact
from strands_agent_tui.sessions import SessionState


class FailingRuntime:
    def run(self, prompt: str):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_app_renders_runtime_status() -> None:
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini", workspace_root="."),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status").render()
        workspace = app.query_one("#workspace").render()
        approval = app.query_one("#approval").render()
        events = app.query_one("#events").render()
        assert "FakeStrandsRuntime" in str(status)
        assert "Model: gpt-4o-mini" in str(status)
        assert "Overwrite: off" in str(status)
        assert "Approval: none" in str(status)
        assert "Workspace:" in str(workspace)
        assert "Approval: none pending" in str(approval)
        assert "Event Timeline" in str(events)


@pytest.mark.asyncio
async def test_submit_prompt_updates_history_output_and_event_timeline(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="test-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )
    async with app.run_test() as pilot:
        await pilot.press("l", "i", "s", "t", " ", "f", "i", "l", "e", "s", "enter")
        await pilot.pause()

        output = app.query_one("#output").render()
        status = app.query_one("#status").render()
        events = app.query_one("#events").render()

        rendered_output = str(output)
        rendered_status = str(status)
        rendered_events = str(events)

        assert "User: list files" in rendered_output
        assert "Agent: (fake-strands) Echo: list files" in rendered_output
        assert "Turns: 1" in rendered_status
        assert "Events: 6" in rendered_status
        assert "Approval: none" in rendered_status
        assert "Filter: all (6/6 events)" in rendered_events
        assert "(runtime) kind=steering_decision | fake-policy" in rendered_events
        assert "(tool) kind=tool_started | list_files" in rendered_events
        assert "data: source='fake_runtime', tool_name='list_files'" in rendered_events
        assert "(tool) kind=tool_finished | list_files" in rendered_events
        assert "(persistence) kind=artifact_saved | Session artifact saved" in rendered_events
        assert len(app.history) == 1
        assert len(app.events) == 6

        payload = json.loads((tmp_path / "test-session" / "turns.jsonl").read_text(encoding="utf-8").strip())
        assert payload["prompt"] == "list files"
        assert payload["provider"] == "fake-strands"
        assert payload["schema_version"] == "strands-agent/v1"
        assert payload["response_metadata"]["mode"] == "fake"
        assert payload["events"][0]["timestamp"]
        assert payload["events"][2]["data"]["tool_name"] == "list_files"
        transcript = (tmp_path / "test-session" / "transcript.md").read_text(encoding="utf-8")
        assert "# Session transcript: test-session" in transcript
        assert "**Response metadata**" in transcript
        assert "list_files" in transcript


@pytest.mark.asyncio
async def test_runtime_error_is_rendered_in_ui(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="error-session")
    app = StrandsAgentApp(
        runtime=FailingRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )
    async with app.run_test() as pilot:
        await pilot.press("x", "enter")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        events = str(app.query_one("#events").render())

        assert "User: x" in output
        assert "Agent: Error: boom" in output
        assert "Runtime error" in status
        assert "(failure) kind=runtime_error | Runtime error" in events
        assert "(persistence) kind=artifact_saved | Session artifact saved" in events

        payload = json.loads((tmp_path / "error-session" / "turns.jsonl").read_text(encoding="utf-8").strip())
        assert payload["error"] is True
        assert payload["provider"] == "runtime-error"
        assert payload["response_metadata"]["mode"] == "fake"


def test_parse_args_overrides_runtime_model_and_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["strands-agent", "--runtime", "live", "--model", "gpt-4.1-mini", "--workspace", "/tmp/demo"],
    )

    config = parse_args()

    assert config.runtime_mode == "live"
    assert config.openai_model == "gpt-4.1-mini"
    assert config.workspace_root == "/tmp/demo"


def test_parse_args_loads_existing_session_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session_dir = tmp_path / "session-123"
    session_dir.mkdir(parents=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["strands-agent", "--session-dir", str(session_dir)],
    )

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-123"


def test_parse_args_resume_last_loads_most_recent_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    older_store.append_turn(
        TurnArtifact(
            prompt="older",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="newer",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    monkeypatch.setattr(sys, "argv", ["strands-agent", "--resume-last"])
    monkeypatch.setenv("STRANDS_AGENT_ARTIFACTS_ROOT", str(tmp_path))

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-newer"


def test_parse_args_pick_session_loads_selected_recent_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_store = SessionArtifactStore(tmp_path, session_id="session-first")
    first_store.append_turn(
        TurnArtifact(
            prompt="first prompt",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    second_store = SessionArtifactStore(tmp_path, session_id="session-second")
    second_store.append_turn(
        TurnArtifact(
            prompt="second prompt",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    monkeypatch.setattr(sys, "argv", ["strands-agent", "--pick-session"])
    monkeypatch.setenv("STRANDS_AGENT_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-first"


def test_parse_args_pick_session_accepts_initial_filter_and_sort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plain_store = SessionArtifactStore(tmp_path, session_id="session-plain")
    plain_store.append_turn(
        TurnArtifact(
            prompt="plain prompt",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    pending_store.append_turn(
        TurnArtifact(
            prompt="pending prompt",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0013",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests",
            )
        ]
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["strands-agent", "--pick-session", "--pick-filter", "pending", "--pick-sort", "attention"],
    )
    monkeypatch.setenv("STRANDS_AGENT_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-pending"


def test_parse_args_pick_session_can_reach_older_sessions_beyond_first_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for index in range(MAX_RECENT_SESSIONS + 2):
        store = SessionArtifactStore(tmp_path, session_id=f"session-{index:02d}")
        store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response="done",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
            )
        )

    inputs = iter(["]", "2"])
    monkeypatch.setattr(sys, "argv", ["strands-agent", "--pick-session"])
    monkeypatch.setenv("STRANDS_AGENT_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-00"


def test_parse_args_rejects_picker_filter_without_pick_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["strands-agent", "--pick-filter", "pending"])

    with pytest.raises(SystemExit):
        parse_args()


@pytest.mark.asyncio
async def test_event_filter_shortcuts_limit_visible_categories(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="filter-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.press("l", "i", "s", "t", " ", "f", "i", "l", "e", "s", "enter")
        await pilot.pause()

        await pilot.press("f3")
        await pilot.pause()
        tool_events = str(app.query_one("#events").render())
        assert "Filter: tool (2/6 events)" in tool_events
        assert "kind=tool_started | list_files" in tool_events
        assert "kind=artifact_saved" not in tool_events

        await pilot.press("f5")
        await pilot.pause()
        persistence_events = str(app.query_one("#events").render())
        assert "Filter: persistence (1/6 events)" in persistence_events
        assert "kind=artifact_saved | Session artifact saved" in persistence_events

        await pilot.press("f1")
        await pilot.pause()
        assert app.event_filter == "all"


@pytest.mark.asyncio
async def test_app_renders_pending_approval_banner_for_risky_mutation(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="confirm-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.press(
            "o",
            "v",
            "e",
            "r",
            "w",
            "r",
            "i",
            "t",
            "e",
            " ",
            "f",
            "i",
            "l",
            "e",
            "enter",
        )
        await pilot.pause()

        rendered_output = str(app.query_one("#output").render())
        rendered_status = str(app.query_one("#status").render())
        rendered_approval = str(app.query_one("#approval").render())
        rendered_events = str(app.query_one("#events").render())

        assert "Approval required before continuing: write_file" in rendered_output
        assert "Approval: pending:write_file" in rendered_status
        assert "Approval pending: write_file" in rendered_approval
        assert "kind=steering_confirmation_required | write_file" in rendered_events
        assert "approval_id='approval-0001'" in rendered_events
        assert app.pending_approval is not None
        assert app.pending_approval.tool_name == "write_file"


@pytest.mark.asyncio
async def test_pending_approval_blocks_new_prompt_until_resolved(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="blocked-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.press("o", "v", "e", "r", "w", "r", "i", "t", "e", " ", "f", "i", "l", "e", "enter")
        await pilot.pause()
        await pilot.press("h", "e", "l", "l", "o", "enter")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        events = str(app.query_one("#events").render())

        assert len(app.history) == 1
        assert "User: hello" not in output
        assert "kind=approval_input_blocked | Resolve pending approval first" in events


@pytest.mark.asyncio
async def test_pending_approval_can_be_approved_from_tui_and_persisted(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="approve-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.press("o", "v", "e", "r", "w", "r", "i", "t", "e", " ", "f", "i", "l", "e", "enter")
        await pilot.pause()
        await pilot.press("f9")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        approval = str(app.query_one("#approval").render())
        events = str(app.query_one("#events").render())

        assert "User: Approve pending write_file (approval-0001)" in output
        assert "Agent: (fake-strands) Approved write_file." in output
        assert "Approval: none" in status
        assert "Approval: none pending" in approval
        assert "kind=steering_approved | write_file" in events
        assert "kind=tool_finished | write_file" in events
        assert app.pending_approval is None
        assert len(app.history) == 2

        jsonl_lines = [json.loads(line) for line in (tmp_path / "approve-session" / "turns.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(jsonl_lines) == 2
        assert jsonl_lines[1]["prompt"] == "Approve pending write_file (approval-0001)"
        assert jsonl_lines[1]["response_metadata"]["approval_action"] == "approved"


@pytest.mark.asyncio
async def test_app_restores_pending_approval_from_artifacts_after_restart(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="restart-approval-session")
    first_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="restart-approval-session",
        ),
        artifact_store=artifact_store,
    )

    async with first_app.run_test() as pilot:
        await pilot.press(
            "o",
            "v",
            "e",
            "r",
            "w",
            "r",
            "i",
            "t",
            "e",
            " ",
            "t",
            "h",
            "e",
            " ",
            "n",
            "o",
            "t",
            "e",
            "s",
            " ",
            "f",
            "i",
            "l",
            "e",
            " ",
            "a",
            "n",
            "d",
            " ",
            "r",
            "e",
            "p",
            "l",
            "a",
            "c",
            "e",
            " ",
            "a",
            "l",
            "l",
            " ",
            "s",
            "t",
            "a",
            "l",
            "e",
            " ",
            "v",
            "a",
            "l",
            "u",
            "e",
            "s",
            "enter",
        )
        await pilot.pause()

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="restart-approval-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="restart-approval-session"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        restored_status = str(second_app.query_one("#status").render())
        restored_approval = str(second_app.query_one("#approval").render())
        restored_events = str(second_app.query_one("#events").render())

        assert "Approval: pending:write_file" in restored_status
        assert "Approval pending: write_file (approval-0001)" in restored_approval
        assert "kind=session_state_restored | Pending approvals restored" in restored_events

        await pilot.press("f9")
        await pilot.pause()

        resolved_output = str(second_app.query_one("#output").render())
        resolved_status = str(second_app.query_one("#status").render())
        resolved_approval = str(second_app.query_one("#approval").render())

        assert "User: Approve pending write_file (approval-0001)" in resolved_output
        assert "Next approval required: replace_text." in resolved_output
        assert "Approval: pending:replace_text" in resolved_status
        assert "Approval pending: replace_text (approval-0002)" in resolved_approval

    third_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="restart-approval-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="restart-approval-session"),
    )

    async with third_app.run_test() as pilot:
        await pilot.pause()
        third_approval = str(third_app.query_one("#approval").render())
        assert "Approval pending: replace_text (approval-0002)" in third_approval


@pytest.mark.asyncio
async def test_app_loads_existing_session_artifacts_on_start(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="existing-session")
    artifact_store.append_turn(
        TurnArtifact(
            prompt="inspect repo",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="existing-session",
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        assert "User: inspect repo" in output
        assert "Agent: done" in output
        assert "Turns: 1" in status


@pytest.mark.asyncio
async def test_app_compacts_loaded_history_into_live_view(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="history-session")
    for index in range(1, 5):
        artifact_store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response=f"response {index}",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
            )
        )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="history-session",
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())

        assert "Showing turns 2-4 of 4" in output
        assert "Turn 1\nUser: prompt 1" not in output
        assert "Turn 4\nUser: prompt 4\nAgent: response 4" in output
        assert "View: live latest 2-4" in status


@pytest.mark.asyncio
async def test_history_navigation_shortcuts_browse_loaded_turns(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="browse-session")
    for index in range(1, 5):
        artifact_store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response=f"response {index}",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
            )
        )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="browse-session",
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("f6")
        await pilot.pause()
        replay_output = str(app.query_one("#output").render())
        replay_status = str(app.query_one("#status").render())
        assert "Viewing turn 3 of 4" in replay_output
        assert "Turn 3\nUser: prompt 3\nAgent: response 3" in replay_output
        assert "View: replay 3/4" in replay_status

        await pilot.press("f6")
        await pilot.pause()
        older_output = str(app.query_one("#output").render())
        assert "Viewing turn 2 of 4" in older_output
        assert "Turn 2\nUser: prompt 2\nAgent: response 2" in older_output

        await pilot.press("f7")
        await pilot.pause()
        newer_output = str(app.query_one("#output").render())
        assert "Viewing turn 3 of 4" in newer_output

        await pilot.press("f8")
        await pilot.pause()
        live_output = str(app.query_one("#output").render())
        live_status = str(app.query_one("#status").render())
        assert "Showing turns 2-4 of 4" in live_output
        assert "View: live latest 2-4" in live_status


@pytest.mark.asyncio
async def test_app_restores_event_filter_and_replay_focus_from_session_state(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="view-state-session")
    for index in range(1, 5):
        artifact_store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response=f"response {index}",
                provider="fake-strands",
                mode="fake",
                events=[runtime_event("tool_finished", "list_files", f"listed files {index}")],
                response_metadata={"mode": "fake"},
            )
        )

    first_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="view-state-session",
        ),
        artifact_store=artifact_store,
    )

    async with first_app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f3")
        await pilot.pause()
        await pilot.press("f6")
        await pilot.pause()

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="view-state-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="view-state-session"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        output = str(second_app.query_one("#output").render())
        status = str(second_app.query_one("#status").render())
        events = str(second_app.query_one("#events").render())

        assert "Viewing turn 3 of 4" in output
        assert "Turn 3\nUser: prompt 3\nAgent: response 3" in output
        assert "View: replay 3/4" in status
        assert "Filter: tool (4/5 events)" in events
        assert any(event.kind == "session_view_restored" for event in second_app.events)


@pytest.mark.asyncio
async def test_app_restores_draft_prompt_from_session_state_after_restart(tmp_path: Path) -> None:
    first_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="draft-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="draft-session"),
    )

    async with first_app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d", "r", "a", "f", "t", " ", "f", "o", "l", "l", "o", "w", "-", "u", "p")
        await pilot.pause()

        stored_state = SessionArtifactStore(tmp_path, session_id="draft-session").load_session_state()
        assert stored_state is not None
        assert stored_state.draft_prompt == "draft follow-up"

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="draft-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="draft-session"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        prompt = second_app.query_one("#prompt", Input)
        events = str(second_app.query_one("#events").render())

        assert prompt.value == "draft follow-up"
        assert second_app.draft_prompt == "draft follow-up"
        assert "Draft prompt restored" in events
        assert any(
            event.kind == "session_view_restored" and event.data.get("draft_prompt_length") == len("draft follow-up")
            for event in second_app.events
        )


@pytest.mark.asyncio
async def test_session_switcher_lists_recent_sessions_in_app(tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    older_store.append_turn(
        TurnArtifact(
            prompt="older prompt",
            response="older response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="newer prompt",
            response="newer response",
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
    newer_store.save_session_state(
        SessionState(
            event_filter="tool",
            history_focus_index=0,
            draft_prompt="draft next step",
        )
    )
    newer_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0004",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest"},
                source="fake_runtime",
                prompt="run pytest",
            )
        ]
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-older",
        ),
        artifact_store=older_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        prompt = app.query_one("#prompt", Input)

        assert "Session Switcher" in output
        assert "1. session-newer" in output
        assert "> 2. session-older" in output
        assert "pending: run_shell_command" in output
        assert "restore: filter=tool, replay 1/1, draft 15c" in output
        assert "last tool: .: README.md" in output
        assert "last event: tool_finished: list_files" in output
        assert "2. session-older" in output
        assert (
            "Keys: ↑/↓ or J/K move, PgUp/PgDn or bracket keys page, Enter switch, 1-8 quick switch, "
            "A all, P pending, R restore, T tool, S sort, N new session, Esc/F11 cancel"
        ) in output
        assert "Filter: all | Sort: recent" in output
        assert "View: session switcher" in status
        assert prompt.disabled is True


@pytest.mark.asyncio
async def test_session_switcher_shows_selected_preview_with_recent_tool_streak(tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    older_store.append_turn(
        TurnArtifact(
            prompt="older prompt",
            response="older response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="inspect workspace",
            response="workspace summary",
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

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-older",
        ),
        artifact_store=older_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert "Selected preview:" in output
        assert "- slot 1 on this page | overall 1 of 2 | session session-newer" in output
        assert "- last tool: inspect/e0 git status --short -> M README.md" in output
        assert "- recent tools (2):" in output
        assert "  1. inspect/e0 git status --short -> M README.md" in output
        assert "  2. .: README.md" in output


@pytest.mark.asyncio
async def test_session_switcher_supports_filter_and_sort_shortcuts(tmp_path: Path) -> None:
    current_store = SessionArtifactStore(tmp_path, session_id="session-current")
    current_store.append_turn(
        TurnArtifact(
            prompt="current prompt",
            response="current response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    pending_store.append_turn(
        TurnArtifact(
            prompt="pending prompt",
            response="pending response",
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

    restore_store = SessionArtifactStore(tmp_path, session_id="session-restore")
    restore_store.append_turn(
        TurnArtifact(
            prompt="restore prompt",
            response="restore response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    restore_store.save_session_state(SessionState(draft_prompt="draft restore"))

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=current_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()
        pending_output = str(app.query_one("#output").render())
        assert "Filter: pending | Sort: recent" in pending_output
        assert "session-pending" in pending_output
        assert "session-current | 1 turn(s)" not in pending_output
        assert "session-restore | 1 turn(s)" not in pending_output

        await pilot.press("s")
        await pilot.pause()
        attention_output = str(app.query_one("#output").render())
        assert "Filter: pending | Sort: attention" in attention_output

        await pilot.press("r")
        await pilot.pause()
        restore_output = str(app.query_one("#output").render())
        assert "Filter: restore | Sort: attention" in restore_output
        assert "session-restore" in restore_output
        assert "session-pending | 1 turn(s)" not in restore_output

        await pilot.press("a")
        await pilot.pause()
        all_output = str(app.query_one("#output").render())
        assert "Filter: all | Sort: attention" in all_output
        assert "session-current" in all_output
        assert "session-pending" in all_output
        assert "session-restore" in all_output


@pytest.mark.asyncio
async def test_session_switcher_can_switch_to_selected_recent_session(tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    older_store.append_turn(
        TurnArtifact(
            prompt="inspect older session",
            response="older response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="inspect newer session",
            response="newer response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-older",
        ),
        artifact_store=older_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11", "1")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        workspace = str(app.query_one("#workspace").render())
        events = str(app.query_one("#events").render())
        prompt = app.query_one("#prompt", Input)

        assert "inspect newer session" in output
        assert "newer response" in output
        assert "inspect older session" not in output
        assert "Turns: 1" in status
        assert "Session: session-newer" in workspace
        assert "kind=session_switched | Session switched" in events
        assert prompt.disabled is False


@pytest.mark.asyncio
async def test_session_switcher_supports_arrow_navigation_and_enter_selection(tmp_path: Path) -> None:
    older_store = SessionArtifactStore(tmp_path, session_id="session-older")
    older_store.append_turn(
        TurnArtifact(
            prompt="inspect older session",
            response="older response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newer_store = SessionArtifactStore(tmp_path, session_id="session-newer")
    newer_store.append_turn(
        TurnArtifact(
            prompt="inspect newer session",
            response="newer response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-older",
        ),
        artifact_store=older_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()

        switcher_output = str(app.query_one("#output").render())
        assert "> 2. session-older" in switcher_output

        await pilot.press("up")
        await pilot.pause()
        moved_output = str(app.query_one("#output").render())
        assert "> 1. session-newer" in moved_output

        await pilot.press("enter")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        prompt = app.query_one("#prompt", Input)

        assert "inspect newer session" in output
        assert "Turns: 1" in status
        assert "View: live latest 1-1" in status
        assert prompt.disabled is False


@pytest.mark.asyncio
async def test_session_switcher_can_start_new_session(tmp_path: Path) -> None:
    existing_store = SessionArtifactStore(tmp_path, session_id="session-existing")
    existing_store.append_turn(
        TurnArtifact(
            prompt="existing prompt",
            response="existing response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-existing",
        ),
        artifact_store=existing_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11", "n")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        workspace = str(app.query_one("#workspace").render())
        events = str(app.query_one("#events").render())

        assert "Phase 1 proves the basic TUI-to-agent loop." in output
        assert "Turns: 0" in status
        assert "Session: session-existing" not in workspace
        assert "kind=session_started | New session started" in events
        assert app.artifact_store.session_id != "session-existing"


@pytest.mark.asyncio
async def test_session_switcher_is_restored_after_restart_with_selected_session(tmp_path: Path) -> None:
    current_store = SessionArtifactStore(tmp_path, session_id="session-current")
    current_store.append_turn(
        TurnArtifact(
            prompt="current prompt",
            response="current response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    middle_store = SessionArtifactStore(tmp_path, session_id="session-middle")
    middle_store.append_turn(
        TurnArtifact(
            prompt="middle prompt",
            response="middle response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    newest_store = SessionArtifactStore(tmp_path, session_id="session-newest")
    newest_store.append_turn(
        TurnArtifact(
            prompt="newest prompt",
            response="newest response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    first_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=current_store,
    )

    async with first_app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        stored_state = SessionArtifactStore(tmp_path, session_id="session-current").load_session_state()
        assert stored_state is not None
        assert stored_state.session_switcher_active is True
        assert stored_state.session_switcher_selected_session_id == "session-middle"
        assert stored_state.session_switcher_sort_mode == "attention"

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="session-current"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        output = str(second_app.query_one("#output").render())
        status = str(second_app.query_one("#status").render())
        events = str(second_app.query_one("#events").render())
        prompt = second_app.query_one("#prompt", Input)

        assert "Session Switcher" in output
        assert any(
            line.startswith("> ") and "session-middle" in line
            for line in output.splitlines()
        )
        assert "Filter: all | Sort: attention" in output
        assert "View: session switcher" in status
        assert "kind=session_switcher_restored | Session switcher restored" in events
        assert prompt.disabled is True


@pytest.mark.asyncio
async def test_session_switcher_restores_deeper_paged_selection_after_restart(tmp_path: Path) -> None:
    current_store = SessionArtifactStore(tmp_path, session_id="session-current")
    current_store.append_turn(
        TurnArtifact(
            prompt="current prompt",
            response="current response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    for index in range(9):
        store = SessionArtifactStore(tmp_path, session_id=f"session-{index:02d}")
        store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response=f"response {index}",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
            )
        )

    first_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=current_store,
    )

    async with first_app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("]")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()

        stored_state = SessionArtifactStore(tmp_path, session_id="session-current").load_session_state()
        assert stored_state is not None
        assert stored_state.session_switcher_active is True
        assert stored_state.session_switcher_page_index == 1
        assert stored_state.session_switcher_selected_session_id

        output = str(first_app.query_one("#output").render())
        assert "Page: 2/2" in output

    restored_selected_session_id = stored_state.session_switcher_selected_session_id

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="session-current"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        output = str(second_app.query_one("#output").render())
        events = str(second_app.query_one("#events").render())

        assert "Session Switcher" in output
        assert "Page: 2/2" in output
        assert any(
            line.startswith("> ") and restored_selected_session_id in line
            for line in output.splitlines()
        )
        assert "kind=session_switcher_restored | Session switcher restored" in events


@pytest.mark.asyncio
async def test_session_switcher_restores_pending_approval_from_selected_session(tmp_path: Path) -> None:
    current_store = SessionArtifactStore(tmp_path, session_id="session-current")
    current_store.append_turn(
        TurnArtifact(
            prompt="current prompt",
            response="current response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )

    pending_store = SessionArtifactStore(tmp_path, session_id="session-pending")
    pending_store.append_turn(
        TurnArtifact(
            prompt="pending prompt",
            response="pending response",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-0007",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pwd", "relative_path": ".", "timeout_seconds": 5},
                source="fake_runtime",
                prompt="run pwd",
            )
        ]
    )

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-current",
        ),
        artifact_store=current_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11", "1")
        await pilot.pause()

        approval = str(app.query_one("#approval").render())
        status = str(app.query_one("#status").render())
        events = str(app.query_one("#events").render())

        assert "Approval pending: run_shell_command (approval-0007)" in approval
        assert "Approval: pending:run_shell_command" in status
        assert "kind=session_state_restored | Pending approvals restored" in events


@pytest.mark.asyncio
async def test_session_switcher_is_blocked_while_approval_is_pending(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="blocked-switch-session")
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="blocked-switch-session",
        ),
        artifact_store=artifact_store,
    )

    async with app.run_test() as pilot:
        await pilot.press("o", "v", "e", "r", "w", "r", "i", "t", "e", " ", "f", "i", "l", "e", "enter")
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        events = str(app.query_one("#events").render())
        prompt = app.query_one("#prompt", Input)

        assert "Session Switcher" not in output
        assert "kind=session_switch_blocked | Session switch blocked" in events
        assert prompt.disabled is False
