from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
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
        newer_store.append_turn(
            TurnArtifact(
                prompt="inspect newer session",
                response="newer response",
                provider="fake-strands",
                mode="fake",
                events=[runtime_event("tool_finished", "list_files", "Finished listing files")],
                response_metadata={"mode": "fake"},
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
                artifacts_root=temp_dir,
                session_id="session-older",
            ),
            artifact_store=older_store,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            switcher_output = app.query_one("#output").render()
            print("switcher_has_pending_marker=", "pending: run_shell_command" in str(switcher_output))
            print("switcher_has_event_preview=", "last event: tool_finished: list_files" in str(switcher_output))
            await pilot.press("1")
            await pilot.pause()
            print("active_session=", app.artifact_store.session_id)
            print("history_latest=", app.history[-1] if app.history else None)
            print("latest_event=", app.events[-1].kind if app.events else None)


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
