import json
import sys
from pathlib import Path

import pytest

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.app import parse_args
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact


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
        events = app.query_one("#events").render()
        assert "FakeStrandsRuntime" in str(status)
        assert "Model: gpt-4o-mini" in str(status)
        assert "Overwrite: off" in str(status)
        assert "Workspace:" in str(workspace)
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
async def test_app_renders_confirmation_required_events_in_timeline(tmp_path: Path) -> None:
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

        rendered_events = str(app.query_one("#events").render())

        assert "kind=steering_confirmation_required | write_file" in rendered_events
        assert "requires_confirmation=True" in rendered_events


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
