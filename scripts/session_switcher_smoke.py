from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, SessionState, TurnArtifact


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

        first_app = StrandsAgentApp(
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

        async with first_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            switcher_output = first_app.query_one("#output").render()
            print("switcher_default_selection_is_current=", "> 2. session-older" in str(switcher_output))
            print("switcher_has_pending_marker=", "pending: run_shell_command" in str(switcher_output))
            print(
                "switcher_has_restore_badges=",
                "restore: filter=tool, replay 1/1, draft 15c" in str(switcher_output),
            )
            print("switcher_has_tool_preview=", "last tool: .: README.md" in str(switcher_output))
            print("switcher_has_event_preview=", "last event: tool_finished: list_files" in str(switcher_output))
            await pilot.press("p")
            await pilot.pause()
            pending_output = first_app.query_one("#output").render()
            pending_text = str(pending_output)
            print("switcher_pending_filter=", "Filter: pending | Sort: recent" in str(pending_output))
            print(
                "switcher_pending_filter_only_newer=",
                "session-newer | 1 turn(s)" in pending_text and "session-older | 1 turn(s)" not in pending_text,
            )
            await pilot.press("s")
            await pilot.pause()
            attention_output = first_app.query_one("#output").render()
            print("switcher_attention_sort=", "Filter: pending | Sort: attention" in str(attention_output))
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()

        restored_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-older",
            ),
            artifact_store=SessionArtifactStore(temp_dir, session_id="session-older"),
        )

        async with restored_app.run_test() as pilot:
            await pilot.pause()
            restored_output = restored_app.query_one("#output").render()
            selected_line = next(
                (line for line in str(restored_output).splitlines() if line.startswith("> ")),
                "",
            )
            print("switcher_restored=", "Session Switcher" in str(restored_output))
            print("switcher_restored_sort=", "Filter: all | Sort: attention" in str(restored_output))
            print("restored_selected_line=", selected_line)
            print("restored_selection_is_newer=", "session-newer" in selected_line)
            print("restored_latest_event=", restored_app.events[-1].kind if restored_app.events else None)
            await pilot.press("enter")
            await pilot.pause()
            print("active_session=", restored_app.artifact_store.session_id)
            print("history_latest=", restored_app.history[-1] if restored_app.history else None)
            print("latest_event=", restored_app.events[-1].kind if restored_app.events else None)


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
