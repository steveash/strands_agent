from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact


def append_turn(store: SessionArtifactStore, prompt: str, response: str) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response=response,
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )


async def run_smoke() -> None:
    with TemporaryDirectory() as temp_dir:
        older_store = SessionArtifactStore(temp_dir, session_id="session-older")
        append_turn(older_store, "inspect older session", "older response")

        newer_store = SessionArtifactStore(temp_dir, session_id="session-newer")
        append_turn(newer_store, "inspect newer session", "newer response")

        app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-older",
            ),
            artifact_store=older_store,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11", "1")
            await pilot.pause()
            print("active_session=", app.artifact_store.session_id)
            print("history_latest=", app.history[-1] if app.history else None)
            print("latest_event=", app.events[-1].kind if app.events else None)


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
