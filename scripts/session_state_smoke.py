from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact


async def run_smoke() -> None:
    with TemporaryDirectory() as temp_dir:
        store = SessionArtifactStore(temp_dir, session_id="session-view-state")
        for index in range(1, 5):
            store.append_turn(
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
                artifacts_root=temp_dir,
                session_id="session-view-state",
            ),
            artifact_store=store,
        )

        async with first_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f3")
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("d", "r", "a", "f", "t", " ", "n", "e", "x", "t", " ", "s", "t", "e", "p")
            await pilot.pause()

        second_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-view-state",
            ),
            artifact_store=SessionArtifactStore(temp_dir, session_id="session-view-state"),
        )

        async with second_app.run_test() as pilot:
            await pilot.pause()
            print("restored_event_filter=", second_app.event_filter)
            print("restored_view=", second_app.history_view_label())
            print("restored_draft=", second_app.query_one("#prompt").value)
            print("latest_visible_event=", second_app.filtered_events()[-1].kind if second_app.filtered_events() else None)


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
