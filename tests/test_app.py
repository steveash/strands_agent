import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import Input

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.app import parse_args
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import MAX_RECENT_SESSIONS, SessionArtifactStore, SessionPickerState, TurnArtifact
from strands_agent_tui.sessions import SessionState
from strands_agent_tui.sessions import save_session_picker_state
from strands_agent_tui.testing import (
    seed_approval_restore_focus_scenario,
    seed_approval_restore_overlap_session,
    seed_approval_restore_rollup_scenario,
    seed_multi_approval_queue_session,
    seed_restore_state_session,
    seed_shell_inspect_session,
    seed_shell_overlap_session,
    seed_shell_test_session,
    seed_stale_approval_subfilter_scenario,
    seed_workspace_edit_session,
    seed_workspace_inspect_session,
    set_session_artifact_mtime,
)


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
        assert "(intervention) kind=steering_decision | fake-policy" in rendered_events
        assert "summary: tool list_files -> Deterministic fake tool event for workspace inspection." in rendered_events
        assert "(tool) kind=tool_started | list_files" in rendered_events
        assert "data: source='fake_runtime', tool_name='list_files'" in rendered_events
        assert "(tool) kind=tool_finished | list_files" in rendered_events
        assert "summary: tool list_files -> .: README.md" in rendered_events
        assert "summary: response fake-strands/fake | pending 0" in rendered_events
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
        [
            "strands-agent",
            "--runtime",
            "live",
            "--model",
            "gpt-4.1-mini",
            "--workspace",
            "/tmp/demo",
            "--stale-approval-days",
            "14",
        ],
    )

    config = parse_args()

    assert config.runtime_mode == "live"
    assert config.openai_model == "gpt-4.1-mini"
    assert config.workspace_root == "/tmp/demo"
    assert config.stale_approval_warning_days == 14


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

    save_session_picker_state(
        tmp_path,
        SessionPickerState(
            filter_mode="all",
            sort_mode="attention",
            page_index=1,
            selected_index=2,
            selected_session_id="session-plain",
        ),
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


def test_parse_args_pick_session_restores_prior_picker_state_when_no_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for index in range(MAX_RECENT_SESSIONS + 3):
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

    save_session_picker_state(
        tmp_path,
        SessionPickerState(
            filter_mode="all",
            sort_mode="recent",
            page_index=1,
            selected_index=1,
            selected_session_id="session-01",
        ),
    )

    monkeypatch.setattr(sys, "argv", ["strands-agent", "--pick-session"])
    monkeypatch.setenv("STRANDS_AGENT_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    config = parse_args()

    assert config.artifacts_root == str(tmp_path.resolve())
    assert config.session_id == "session-01"


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

        await pilot.press("f12")
        await pilot.pause()
        intervention_events = str(app.query_one("#events").render())
        assert "Filter: intervention (1/6 events)" in intervention_events
        assert "kind=steering_decision | fake-policy" in intervention_events
        assert "kind=artifact_saved" not in intervention_events

        await pilot.press("f5")
        await pilot.pause()
        persistence_events = str(app.query_one("#events").render())
        assert "Filter: persistence (1/6 events)" in persistence_events
        assert "kind=artifact_saved | Session artifact saved" in persistence_events

        await pilot.press("f1")
        await pilot.pause()
        assert app.event_filter == "all"


@pytest.mark.asyncio
async def test_timeline_toggle_shortcuts_hide_detail_and_raw_data_and_persist_state(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="timeline-toggle-session")
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
        await pilot.press("ctrl+t")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        events = str(app.query_one("#events").render())
        stored_state = SessionArtifactStore(tmp_path, session_id="timeline-toggle-session").load_session_state()

        assert "View: detail off | raw off" in events
        assert "summary: tool list_files -> .: README.md" in events
        assert "\n   Deterministic fake tool event for workspace inspection." not in events
        assert "data: result_preview='.: README.md'" not in events
        assert stored_state is not None
        assert stored_state.show_event_details is False
        assert stored_state.show_event_data is False


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
        assert "Approval: pending:write_file(1/1)" in rendered_status
        assert "Approval pending: write_file (approval-0001) | queue: 1/1" in rendered_approval
        assert "kind=steering_confirmation_required | write_file" in rendered_events
        assert "summary: approval pending edit via fake_runtime | queue 1/1 | path notes.txt" in rendered_events
        assert "approval_id='approval-0001'" in rendered_events
        assert "approval_queue_total=1" in rendered_events
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

        assert "Approval: pending:write_file(1/2)" in restored_status
        assert "Approval pending: write_file (approval-0001) | queue: 1/2 | next: replace_text" in restored_approval
        assert "kind=session_state_restored | Pending approvals restored" in restored_events

        await pilot.press("f9")
        await pilot.pause()

        resolved_output = str(second_app.query_one("#output").render())
        resolved_status = str(second_app.query_one("#status").render())
        resolved_approval = str(second_app.query_one("#approval").render())

        assert "User: Approve pending write_file (approval-0001)" in resolved_output
        assert "Next approval required: replace_text." in resolved_output
        assert "Approval: pending:replace_text(1/1)" in resolved_status
        assert "Approval pending: replace_text (approval-0002) | queue: 1/1" in resolved_approval

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
        assert "Approval pending: replace_text (approval-0002) | queue: 1/1" in third_approval


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
async def test_app_restores_timeline_detail_and_raw_view_from_session_state(tmp_path: Path) -> None:
    artifact_store = SessionArtifactStore(tmp_path, session_id="timeline-restore-session")
    for index in range(1, 3):
        artifact_store.append_turn(
            TurnArtifact(
                prompt=f"prompt {index}",
                response=f"response {index}",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "tool_finished",
                        "list_files",
                        f"listed files {index}",
                        data={"tool_name": "list_files", "result_preview": ".: README.md"},
                    )
                ],
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
            session_id="timeline-restore-session",
        ),
        artifact_store=artifact_store,
    )

    async with first_app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

    second_app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="timeline-restore-session",
        ),
        artifact_store=SessionArtifactStore(tmp_path, session_id="timeline-restore-session"),
    )

    async with second_app.run_test() as pilot:
        await pilot.pause()

        events = str(second_app.query_one("#events").render())

        assert second_app.show_event_details is False
        assert second_app.show_event_data is False
        assert "View: detail off | raw off" in events
        assert "summary: session view restored | filter all | detail off | raw off" in events
        assert "data: tool_name='list_files'" not in events


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
            "A all, P pending, D denied, R restore, V restored approvals, O stale approvals, Q stale pending, X stale denied, U stale restored, T tool, W workspace inspect, E workspace edits, G intervention, H shell, I inspect shell, Y shell tests, S sort, N new session, Esc/F11 cancel | stale cutoff: approvals >= 7d old"
        ) in output
        assert "Filter: all | Sort: recent" in output
        assert "View: session switcher" in status
        assert prompt.disabled is True


@pytest.mark.asyncio
async def test_session_switcher_surfaces_approval_rollups_in_summary_and_preview(tmp_path: Path) -> None:
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

    rollup_store = SessionArtifactStore(tmp_path, session_id="session-rollup")
    rollup_store.append_turn(
        TurnArtifact(
            prompt="resume guarded changes",
            response="approval summary",
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
    rollup_store.save_pending_approvals(
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

        output = str(app.query_one("#output").render())
        assert "session-rollup | 1 turn(s)" in output
        assert "approvals: pending 1, approved 1" in output
        assert "approval focus: pending" in output

        await pilot.press("up")
        await pilot.pause()

        selected_output = str(app.query_one("#output").render())
        assert "- approvals: pending 1, approved 1" in selected_output


@pytest.mark.asyncio
async def test_session_switcher_surfaces_pending_backlog_rollups(tmp_path: Path) -> None:
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

    fresh_store = SessionArtifactStore(tmp_path, session_id="session-pending-fresh")
    fresh_store.append_turn(
        TurnArtifact(
            prompt="queue fresh test approval",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    fresh_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-switcher-pending-fresh",
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
    restored_store.append_turn(
        TurnArtifact(
            prompt="resume restored edit approval",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-switcher-pending-restored",
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
    multi_store.append_turn(
        TurnArtifact(
            prompt="queue multiple pending approvals",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    multi_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-switcher-pending-multi-1",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="queue test",
                created_at=(datetime.now(UTC) - timedelta(hours=12)).isoformat(),
            ),
            ApprovalRequest(
                request_id="approval-switcher-pending-multi-2",
                tool_name="replace_text",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "old_text": "old", "new_text": "new"},
                source="fake_runtime",
                prompt="queue edit",
                created_at=(datetime.now(UTC) - timedelta(hours=11)).isoformat(),
            ),
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
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert (
            "Pending approval backlog: 3 sessions | approvals: 4 | families: test 2, edit 2 | multi-queue: 1 session | restored queues: 1 session"
            in output
        )
        assert "Pending focus: fresh, restored | oldest: 2d" in output


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
        assert "- shell: inspect 1" in output
        assert "- last shell: inspect/e0 git status --short -> M README.md" in output
        assert "- recent tools (2):" in output
        assert "- recent shell outcomes (1):" in output
        assert "  1. inspect/e0 git status --short -> M README.md" in output
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

    seed_shell_overlap_session(
        tmp_path,
        session_id="session-pending",
        prompt="pending prompt",
        response="pending response",
        command="git status --short",
        result_preview="git status --short -> M README.md",
        request_id="approval-0012",
        approval_prompt="run tests",
    )

    seed_workspace_edit_session(
        tmp_path,
        session_id="session-pending-edit",
        prompt="pending edit prompt",
        response="pending edit response",
        request_id="approval-0012aa",
        tool_name="write_file",
        args={"relative_path": "notes.txt", "overwrite": True},
        approval_prompt="queue edit",
    )

    seed_approval_restore_focus_scenario(tmp_path)

    aged_turn_time = datetime.now(UTC) - timedelta(days=10)
    seed_shell_test_session(
        tmp_path,
        session_id="session-aged",
        prompt="resume stale test queue",
        response="stale response",
        request_id="approval-aged",
        approval_prompt="resume old tests",
        created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
        turn_created_at=aged_turn_time.isoformat(),
    )
    aged_store = SessionArtifactStore(tmp_path, session_id="session-aged")
    set_session_artifact_mtime(aged_store, aged_turn_time)

    seed_restore_state_session(
        tmp_path,
        session_id="session-restore",
        prompt="restore prompt",
        response="restore response",
        draft_prompt="draft restore",
    )

    seed_workspace_inspect_session(
        tmp_path,
        session_id="session-tool",
        prompt="inspect workspace tool state",
        response="tool response",
    )

    seed_shell_inspect_session(
        tmp_path,
        session_id="session-shell",
        prompt="inspect shell-only repo state",
        response="shell response",
        command="pwd",
        result_preview="pwd -> /workspace/demo",
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
        await pilot.press("f11")
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()
        pending_output = str(app.query_one("#output").render())
        assert "Filter: pending | Sort: recent" in pending_output
        assert "session-pending" in pending_output
        assert "session-pending-edit" in pending_output
        assert "session-current | 1 turn(s)" not in pending_output
        assert "session-restore | 1 turn(s)" not in pending_output

        await pilot.press("d")
        await pilot.pause()
        denied_output = str(app.query_one("#output").render())
        assert "Filter: denied | Sort: recent" in denied_output
        assert "session-denied" in denied_output
        assert "session-pending | 1 turn(s)" not in denied_output
        assert "session-restore | 1 turn(s)" not in denied_output
        assert "approval focus: denied/restored" in denied_output
        assert "denied: edit 1" in denied_output
        assert "last denied approval: denied replace_text via fake_runtime | restored queue | remaining 0" in denied_output
        assert "approval restore: denied 1" in denied_output

        await pilot.press("v")
        await pilot.pause()
        approval_restore_output = str(app.query_one("#output").render())
        assert "Filter: approval-restore | Sort: recent" in approval_restore_output
        assert "session-restored-pending" in approval_restore_output
        assert "session-restored-edit-pending" in approval_restore_output
        assert "session-denied" in approval_restore_output
        assert "session-restore | 1 turn(s)" not in approval_restore_output
        assert "session-pending | 1 turn(s)" not in approval_restore_output
        assert "Approval restore backlog: 3 sessions | lanes:" in approval_restore_output
        assert "restore queue 2 (oldest 3d @" in approval_restore_output
        assert "restored 1 (oldest 6h @" in approval_restore_output
        assert "Restore lane focus: restore queue, restored" in approval_restore_output
        assert "approval restore tools: test 1" in approval_restore_output
        assert "approval restore tools: edit 1" in approval_restore_output
        assert "restore focus: restore queue" not in approval_restore_output
        assert "restore focus: restored" not in approval_restore_output
        assert "- restore focus: restore queue" not in approval_restore_output
        assert "- restore focus: restored" not in approval_restore_output
        assert "last restored approval:" in approval_restore_output or "restored current approval:" in approval_restore_output
        assert "attention:" not in approval_restore_output

        await pilot.press("o")
        await pilot.pause()
        approval_stale_output = str(app.query_one("#output").render())
        assert "Filter: approval-stale | Sort: recent" in approval_stale_output
        assert "Stale cutoff: approvals >= 7d old" in approval_stale_output
        assert "Stale approval backlog: 1 session | lanes: pending 1 (oldest 45d @" in approval_stale_output
        assert (
            "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
            in approval_stale_output
        )
        assert "session-aged" in approval_stale_output
        assert "approval stale age: pending 45d" in approval_stale_output
        assert "approval stale: pending 45d" not in approval_stale_output
        assert "stale focus: pending" not in approval_stale_output
        assert (
            "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
            not in approval_stale_output
        )
        assert "session-pending | 1 turn(s)" not in approval_stale_output
        assert "session-restored-pending | 1 turn(s)" not in approval_stale_output

        await pilot.press("v")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        attention_output = str(app.query_one("#output").render())
        assert "Filter: approval-restore | Sort: attention" in attention_output
        assert "attention: restored test queue" in attention_output
        assert "attention: restored edit queue" in attention_output
        assert "attention: restored denied edit" in attention_output
        assert attention_output.index("session-restored-pending | 1 turn(s)") < attention_output.index(
            "session-restored-edit-pending | 1 turn(s)"
        )
        assert attention_output.index("session-restored-edit-pending | 1 turn(s)") < attention_output.index(
            "session-denied | 1 turn(s)"
        )

        await pilot.press("up")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        attention_preview_output = str(app.query_one("#output").render())
        assert (
            "- attention reason: restored pending test approval queue; tests sort ahead of restored edits"
            in attention_preview_output
        )

        await pilot.press("r")
        await pilot.pause()
        restore_output = str(app.query_one("#output").render())
        assert "Filter: restore | Sort: attention" in restore_output
        assert "session-restore" in restore_output
        assert "attention: restore" in restore_output
        assert "session-pending | 1 turn(s)" not in restore_output

        await pilot.press("g")
        await pilot.pause()
        intervention_output = str(app.query_one("#output").render())
        assert "Filter: intervention | Sort: attention" in intervention_output
        assert "Intervention backlog: 6 sessions" in intervention_output
        assert "pending 5 (oldest 45d @" in intervention_output
        assert "overlap: mixed 3 sessions" in intervention_output
        assert "Intervention focus: pending, blocked, approved, denied, restored" in intervention_output
        assert "Intervention mix: requests: 6 | families: test 3, edit 3" in intervention_output
        assert "session-pending | 1 turn(s)" in intervention_output
        assert "session-denied | 1 turn(s)" in intervention_output
        assert "intervention: pending 1" in intervention_output
        assert "intervention: denied 1, restored 1" in intervention_output
        assert "session-shell | 1 turn(s)" not in intervention_output

        await pilot.press("t")
        await pilot.pause()
        tool_output = str(app.query_one("#output").render())
        assert "Filter: tool | Sort: attention" in tool_output
        assert "Tool backlog: 3 sessions | lanes: workspace 1, shell 2" in tool_output
        assert "Tool focus: workspace, shell, other" in tool_output
        assert "Tool failure mix: failures: none" in tool_output
        assert "session-tool | 1 turn(s)" in tool_output
        assert "session-shell | 1 turn(s)" in tool_output
        assert "session-restore | 1 turn(s)" not in tool_output

        await pilot.press("w")
        await pilot.pause()
        workspace_inspect_output = str(app.query_one("#output").render())
        assert "Filter: workspace-inspect | Sort: attention" in workspace_inspect_output
        assert "Workspace backlog: 1 session | lanes: inspect 1" in workspace_inspect_output
        assert "Workspace focus: inspect" in workspace_inspect_output
        assert "session-tool | 1 turn(s)" in workspace_inspect_output
        assert "workspace lanes: inspect" in workspace_inspect_output
        assert "session-shell | 1 turn(s)" not in workspace_inspect_output

        await pilot.press("e")
        await pilot.pause()
        workspace_edit_output = str(app.query_one("#output").render())
        assert "Filter: workspace-edit | Sort: attention" in workspace_edit_output
        assert "Workspace backlog: 3 sessions | lanes: edit 3" in workspace_edit_output
        assert "Workspace focus: edit" in workspace_edit_output
        assert "session-pending-edit | 1 turn(s)" in workspace_edit_output
        assert "session-restored-edit-pending | 1 turn(s)" in workspace_edit_output
        assert "session-denied | 1 turn(s)" in workspace_edit_output
        assert "workspace lanes: edit" in workspace_edit_output
        assert "workspace focus: pending only" in workspace_edit_output
        assert "Workspace edit queue mix: pending-only: 2 sessions | restored pending-only: 1 session" in workspace_edit_output
        assert "session-shell | 1 turn(s)" not in workspace_edit_output

        await pilot.press("h")
        await pilot.pause()
        shell_output = str(app.query_one("#output").render())
        assert "Filter: shell | Sort: attention" in shell_output
        assert "Shell backlog: 4 sessions | lanes: inspect 2, test 3 (oldest 45d @" in shell_output
        assert "| overlap: mixed 1 session" in shell_output
        assert "Shell focus: inspect, test" in shell_output
        assert "session-shell | 1 turn(s)" in shell_output
        assert "session-pending | 1 turn(s)" in shell_output
        assert "session-restore | 1 turn(s)" not in shell_output
        assert "shell: inspect 1" in shell_output

        await pilot.press("i")
        await pilot.pause()
        shell_inspect_output = str(app.query_one("#output").render())
        assert "Filter: shell-inspect | Sort: attention" in shell_inspect_output
        assert "Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session" in shell_inspect_output
        assert "Shell focus: inspect" in shell_inspect_output
        assert "session-shell | 1 turn(s)" in shell_inspect_output
        assert "session-pending | 1 turn(s)" in shell_inspect_output
        assert "shell lanes: inspect, test" in shell_inspect_output
        assert "session-restored-pending | 1 turn(s)" not in shell_inspect_output
        assert "session-failed-test | 1 turn(s)" not in shell_inspect_output

        await pilot.press("y")
        await pilot.pause()
        shell_test_output = str(app.query_one("#output").render())
        assert "Filter: shell-test | Sort: attention" in shell_test_output
        assert "Shell backlog: 3 sessions | lanes: inspect 1, test 3 (oldest 45d @" in shell_test_output
        assert "| overlap: mixed 1 session" in shell_test_output
        assert "Shell focus: test" in shell_test_output
        assert "session-pending | 1 turn(s)" in shell_test_output
        assert "session-restored-pending | 1 turn(s)" in shell_test_output
        assert "shell lanes: inspect, test" in shell_test_output
        assert "shell focus: pending only" in shell_test_output
        assert "Shell test queue mix: pending-only: 3 sessions | restored pending-only: 1 session" in shell_test_output
        assert "session-shell | 1 turn(s)" not in shell_test_output
        assert "session-tool | 1 turn(s)" not in shell_test_output

        await pilot.press("a")
        await pilot.pause()
        all_output = str(app.query_one("#output").render())
        assert "Filter: all | Sort: attention" in all_output
        assert "session-current" in all_output
        assert "session-pending" in all_output
        assert "session-pending-edit" in all_output
        assert "session-restore" in all_output
        assert "attention: pending test" in all_output
        assert "attention: pending edit" in all_output
        assert "pending tools: test 1" in all_output
        assert "pending tools: edit 1" in all_output
        assert all_output.index("session-pending | 1 turn(s)") < all_output.index("session-pending-edit | 1 turn(s)")
        assert "attention: restore" in all_output
        assert "shell: inspect 1" in all_output


@pytest.mark.asyncio
async def test_session_switcher_supports_stale_pending_denied_and_restored_subfilters(tmp_path: Path) -> None:
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

    scenario = seed_stale_approval_subfilter_scenario(tmp_path)

    mtime = datetime.now(UTC)
    for store in [
        current_store,
        SessionArtifactStore(tmp_path, session_id=scenario.pending_id),
        SessionArtifactStore(tmp_path, session_id=scenario.denied_id),
        SessionArtifactStore(tmp_path, session_id=scenario.restored_queue_id),
        SessionArtifactStore(tmp_path, session_id=scenario.restored_mixed_id),
    ]:
        set_session_artifact_mtime(store, mtime)

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

        await pilot.press("q")
        await pilot.pause()
        stale_pending_output = str(app.query_one("#output").render())
        assert "Filter: approval-stale-pending | Sort: recent" in stale_pending_output
        assert "Stale pending backlog: 1 session | lanes: pending 1 (oldest 45d @" in stale_pending_output
        assert "Stale lane focus: pending | cutoff: approvals >= 7d old" in stale_pending_output
        assert "| approval stale age: 45d | stale focus: pending" in stale_pending_output
        assert "| approval stale: pending 45d | stale focus: pending" not in stale_pending_output
        assert "- stale focus: pending" in stale_pending_output
        assert "- approval stale age: 45d" in stale_pending_output
        assert "- approval stale: pending 45d" not in stale_pending_output
        assert "stale focus: pending" in stale_pending_output
        assert "session-stale-pending" in stale_pending_output
        assert "session-stale-denied | 1 turn(s)" not in stale_pending_output
        assert "session-stale-restored-queue | 1 turn(s)" not in stale_pending_output

        await pilot.press("x")
        await pilot.pause()
        stale_denied_output = str(app.query_one("#output").render())
        assert "Filter: approval-stale-denied | Sort: recent" in stale_denied_output
        assert "Stale denied backlog: 1 session | lanes: denied 1 (oldest 9d @" in stale_denied_output
        assert "Stale lane focus: denied | cutoff: approvals >= 7d old" in stale_denied_output
        assert "| approval stale age: 9d | stale focus: denied" in stale_denied_output
        assert "| approval stale: denied 9d | stale focus: denied" not in stale_denied_output
        assert "- stale focus: denied" in stale_denied_output
        assert "- approval stale age: 9d" in stale_denied_output
        assert "- approval stale: denied 9d" not in stale_denied_output
        assert "stale focus: denied" in stale_denied_output
        assert "session-stale-denied" in stale_denied_output
        assert "session-stale-pending | 1 turn(s)" not in stale_denied_output
        assert "session-stale-restored-queue | 1 turn(s)" not in stale_denied_output

        await pilot.press("u")
        await pilot.pause()
        stale_restored_output = str(app.query_one("#output").render())
        assert "Filter: approval-stale-restored | Sort: recent" in stale_restored_output
        assert "Stale restored backlog: 2 sessions | lanes:" in stale_restored_output
        assert "restore queue 2 (oldest 11d @" in stale_restored_output
        assert "restored 1 (oldest 9d @" in stale_restored_output
        assert "Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old" in stale_restored_output
        assert "| approval stale age: 11d | stale focus: restore queue" in stale_restored_output
        assert (
            "| approval stale ages: restore queue 10d; restored 9d | stale focus: restore queue, restored"
            in stale_restored_output
        )
        assert "restored current: pending write_file via fake_runtime; queued 1" in stale_restored_output
        assert (
            "restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0"
            in stale_restored_output
        )
        assert "restored outcome age: 9d" in stale_restored_output
        assert "| approval stale: restore queue 11d | stale focus: restore queue" not in stale_restored_output
        assert "| approval stale: restore queue 10d, restored 9d | stale focus: restore queue, restored" not in stale_restored_output
        assert "- stale focus: restore queue" in stale_restored_output
        assert "- approval stale age: 11d" in stale_restored_output
        assert "- approval stale: restore queue 11d" not in stale_restored_output
        assert "stale focus: restore queue" in stale_restored_output
        assert "session-stale-restored-queue" in stale_restored_output
        assert "session-stale-restored" in stale_restored_output
        assert "session-stale-pending | 1 turn(s)" not in stale_restored_output
        assert "session-stale-denied | 1 turn(s)" not in stale_restored_output

        await pilot.press("down")
        await pilot.pause()
        mixed_stale_restored_output = str(app.query_one("#output").render())
        assert "- stale focus: restore queue, restored" in mixed_stale_restored_output
        assert "- approval stale ages: restore queue 10d; restored 9d" in mixed_stale_restored_output
        assert "- restored current approval: pending write_file via fake_runtime | queued 1" in mixed_stale_restored_output
        assert (
            "- latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0"
            in mixed_stale_restored_output
        )
        assert "- latest restored outcome age: 9d" in mixed_stale_restored_output
        assert "- approval stale: restore queue 10d, restored 9d" not in mixed_stale_restored_output


@pytest.mark.asyncio
async def test_session_switcher_respects_custom_stale_threshold(tmp_path: Path) -> None:
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

    custom_store = SessionArtifactStore(tmp_path, session_id="session-custom-threshold")
    custom_store.append_turn(
        TurnArtifact(
            prompt="resume moderately old pending queue",
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )
    custom_store.save_pending_approvals(
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

    timestamp = datetime.now(UTC).timestamp()
    for store in [current_store, custom_store]:
        for path in [store.session_dir, *store.session_dir.iterdir()]:
            os.utime(path, (timestamp, timestamp))

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            stale_approval_warning_days=1,
            session_id="session-current",
        ),
        artifact_store=current_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert "Filter: approval-stale | Sort: recent" in output
        assert "Stale cutoff: approvals >= 1d old" in output
        assert "Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d @" in output
        assert (
            "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old"
            in output
        )
        assert "session-custom-threshold" in output


@pytest.mark.asyncio
async def test_session_switcher_surfaces_pending_queue_breakdown_for_multi_approval_session(tmp_path: Path) -> None:
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

    seed_multi_approval_queue_session(
        tmp_path,
        session_id="session-pending-mixed",
        prompt="mixed pending prompt",
        response="mixed pending response",
        request_id_prefix="approval-0090",
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
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert "session-pending-mixed" in output
        assert "pending: 3 approvals (first test; rest edit 1, tool 1)" in output
        assert "- pending queue: first test; rest edit 1, tool 1" in output
        assert "- pending tools: test 1, edit 1, tool 1" in output


@pytest.mark.asyncio
async def test_session_switcher_surfaces_restored_pending_queue_breakdown_for_multi_approval_session(
    tmp_path: Path,
) -> None:
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

    seed_multi_approval_queue_session(
        tmp_path,
        session_id="session-restored-mixed",
        prompt="restored pending prompt",
        response="restored pending response",
        restored_from_session=True,
        request_id_prefix="approval-0091",
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
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert "session-restored-mixed" in output
        assert "pending: 3 approvals (first test; rest edit 1, tool 1)" in output
        assert "approval restore queue: first test; rest edit 1, tool 1" in output
        assert "- approval restore queue: first test; rest edit 1, tool 1" in output
        assert "- approval restore tools: test 1, edit 1, tool 1" in output


@pytest.mark.asyncio
async def test_session_switcher_surfaces_mixed_restore_overlap_summary_and_preview_split(
    tmp_path: Path,
) -> None:
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

    seed_approval_restore_overlap_session(
        tmp_path,
        session_id="session-restored-overlap",
        response="restored overlap response",
        pending_request_id="approval-overlap-2",
        outcome_request_id="approval-overlap-1",
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
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()

        output = str(app.query_one("#output").render())

        assert "Approval restore backlog: 1 session | lanes:" in output
        assert "restore queue 1 (oldest 3d @" in output
        assert "restored 1 (oldest 6h @" in output
        assert "overlap: mixed 1 session" in output
        assert "Restore lane focus: restore queue, restored" in output
        assert "approval restore ages: restore queue 3d; restored 6h" in output
        assert "restore focus: restore queue, restored" not in output
        assert "restored current: pending run_shell_command via fake_runtime; queued 1" in output
        assert "restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0" in output
        assert "- restored current approval: pending run_shell_command via fake_runtime | queued 1" in output
        assert "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0" in output
        assert "- latest restored outcome age: 6h" not in output


@pytest.mark.asyncio
async def test_session_switcher_reports_approval_restore_page_rollups_when_backlog_spans_pages(
    tmp_path: Path,
) -> None:
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

    seed_approval_restore_rollup_scenario(tmp_path, now=datetime.now(UTC))

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
        await pilot.press("v")
        await pilot.pause()

        first_page_output = str(app.query_one("#output").render())

        await pilot.press("]")
        await pilot.pause()
        second_page_output = str(app.query_one("#output").render())

        assert "Approval restore backlog: 10 sessions | lanes:" in first_page_output
        assert "restore queue 9 (oldest 18d @" in first_page_output
        assert "restored 2 (oldest 8h @" in first_page_output
        assert "overlap: mixed 1 session" in first_page_output
        assert "Restore lane focus: restore queue, restored" in first_page_output
        assert "This page restore lanes: restore queue 8 (oldest 18d @" in first_page_output
        assert "more off-page: restore queue 1 (oldest 3d @" in first_page_output
        assert "restored 2 (oldest 8h @" in first_page_output
        assert "overlap here/off-page: none / mixed 1 session" in first_page_output
        assert "Page: 2/2 | Showing: 9-10 of 10" in second_page_output
        assert "This page restore lanes: restore queue 1 (oldest 3d @" in second_page_output
        assert "restored 2 (oldest 8h @" in second_page_output
        assert "more off-page: restore queue 8 (oldest 18d @" in second_page_output
        assert "overlap here/off-page: mixed 1 session / none" in second_page_output


@pytest.mark.asyncio
async def test_session_switcher_reports_empty_filter_triage_guidance(tmp_path: Path) -> None:
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

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())
        prompt = app.query_one("#prompt", Input)

        assert "Filter: pending | Sort: recent" in output
        assert "No saved sessions match the active switcher filter." in output
        assert "1 saved session still exists under this root." in output
        assert (
            "Try A to show all sessions, or P/D/R/V/O/Q/X/U/T/W/E/G/H/I/Y to jump between pending, denied, restore, restored-approval, stale-approval, stale-pending, stale-denied, stale-restored, tool, workspace-inspect, workspace-edit, intervention, shell, shell-inspect, and shell-test triage."
            in output
        )
        assert "Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists." in output
        assert "Enter switches the highlighted session once a visible row exists again." in output
        assert "session-current | 1 turn(s)" not in output
        assert "View: session switcher" in status
        assert prompt.disabled is True


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

        assert "Approval pending: run_shell_command (approval-0007) | queue: 1/1" in approval
        assert "Approval: pending:run_shell_command(1/1)" in status
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
