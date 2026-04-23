import sys

import pytest

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.app import parse_args
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime


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
        assert "Workspace:" in str(workspace)
        assert "Event Timeline" in str(events)


@pytest.mark.asyncio
async def test_submit_prompt_updates_history_output_and_event_timeline() -> None:
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini", workspace_root="."),
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
        assert "Events: 4" in rendered_status
        assert "kind=tool_started | list_files" in rendered_events
        assert "kind=tool_finished | list_files" in rendered_events
        assert len(app.history) == 1
        assert len(app.events) == 4


@pytest.mark.asyncio
async def test_runtime_error_is_rendered_in_ui() -> None:
    app = StrandsAgentApp(
        runtime=FailingRuntime(),
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini", workspace_root="."),
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
        assert "kind=runtime_error | Runtime error" in events


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
