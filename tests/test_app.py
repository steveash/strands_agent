import pytest

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.runtime import FakeStrandsRuntime


@pytest.mark.asyncio
async def test_app_renders_runtime_status() -> None:
    app = StrandsAgentApp(runtime=FakeStrandsRuntime())
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status").render()
        assert "FakeStrandsRuntime" in str(status)


@pytest.mark.asyncio
async def test_submit_prompt_updates_history_and_output() -> None:
    app = StrandsAgentApp(runtime=FakeStrandsRuntime())
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
        assert len(app.history) == 1
