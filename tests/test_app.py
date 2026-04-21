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
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini"),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status").render()
        assert "FakeStrandsRuntime" in str(status)
        assert "Model: gpt-4o-mini" in str(status)


@pytest.mark.asyncio
async def test_submit_prompt_updates_history_and_output() -> None:
    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini"),
    )
    async with app.run_test() as pilot:
        await pilot.press("h", "i", "enter")
        await pilot.pause()

        output = app.query_one("#output").render()
        status = app.query_one("#status").render()

        rendered_output = str(output)
        rendered_status = str(status)

        assert "User: hi" in rendered_output
        assert "Agent: (fake-strands) Echo: hi" in rendered_output
        assert "Turns: 1" in rendered_status
        assert "Model: gpt-4o-mini" in rendered_status
        assert len(app.history) == 1


@pytest.mark.asyncio
async def test_runtime_error_is_rendered_in_ui() -> None:
    app = StrandsAgentApp(
        runtime=FailingRuntime(),
        config=AppConfig(runtime_mode="fake", openai_model="gpt-4o-mini"),
    )
    async with app.run_test() as pilot:
        await pilot.press("x", "enter")
        await pilot.pause()

        output = str(app.query_one("#output").render())
        status = str(app.query_one("#status").render())

        assert "User: x" in output
        assert "Agent: Error: boom" in output
        assert "Runtime error" in status


def test_parse_args_overrides_runtime_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["strands-agent", "--runtime", "live", "--model", "gpt-4.1-mini"])

    config = parse_args()

    assert config.runtime_mode == "live"
    assert config.openai_model == "gpt-4.1-mini"
