from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact, list_recent_sessions
from strands_agent_tui.testing import emit_smoke_results


async def run_smoke() -> int:
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
            await pilot.press("ctrl+t")
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            await pilot.press("ctrl+o")
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
            restored_event_filter = second_app.event_filter
            restored_view = second_app.history_view_label()
            restored_draft = second_app.query_one("#prompt").value
            restored_timeline_view = second_app.timeline_view_label()
            restored_focus = second_app._event_focus_restore_label()
            latest_visible_event = second_app.filtered_events()[-1].kind if second_app.filtered_events() else None
            summary = list_recent_sessions(temp_dir)[0]
            summary_line = summary.render_line(1)
            summary_preview = "\n".join(summary.render_preview(visible_index=1, overall_index=1, total_matches=1))
            return emit_smoke_results(
                [
                    ("restored_event_filter", restored_event_filter),
                    ("restored_view", restored_view),
                    ("restored_draft", restored_draft),
                    ("restored_timeline_view", restored_timeline_view),
                    ("restored_timeline_focus", restored_focus),
                    ("latest_visible_event", latest_visible_event),
                    ("recent_session_restore_line", summary_line),
                    ("recent_session_restore_preview", summary_preview),
                    ("session_state_restored_event_filter", restored_event_filter == "tool"),
                    ("session_state_restored_view", restored_view == "replay 3/4"),
                    ("session_state_restored_draft", restored_draft == "draft next step"),
                    ("session_state_restored_timeline_view", restored_timeline_view == "detail off / raw off"),
                    ("session_state_restored_timeline_focus", restored_focus == "event 4/4, spotlight"),
                    ("session_state_latest_visible_event", latest_visible_event == "tool_finished"),
                    (
                        "session_state_recent_session_restore_badges",
                        "restore: filter=tool, timeline compact, spotlight 4/4, replay 3/4, draft 15c" in summary_line,
                    ),
                    (
                        "session_state_recent_session_restore_preview",
                        "- timeline view: detail off / raw off" in summary_preview
                        and "- timeline focus: event 4/4 spotlight" in summary_preview,
                    ),
                ]
            )


def main() -> int:
    return asyncio.run(run_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
