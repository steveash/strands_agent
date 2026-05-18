from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact
from strands_agent_tui.testing import emit_smoke_checks


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = SessionArtifactStore(root, session_id="replay-smoke")
        for index in range(1, 5):
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

        app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=str(root),
                session_id="replay-smoke",
            ),
            artifact_store=store,
        )

        live_view = app.render_history()
        print("LIVE VIEW")
        print(live_view)

        app.history_focus_index = len(app.history) - 2
        replay_view = app.render_history()
        print("\nREPLAY VIEW")
        print(replay_view)

        return emit_smoke_checks(
            [
                (
                    "replay_live_view",
                    "live latest 2-4" in live_view
                    and "Showing turns 2-4 of 4" in live_view
                    and "Turn 4\nUser: prompt 4\nAgent: response 4" in live_view,
                ),
                (
                    "replay_replay_view",
                    "replay 3/4" in replay_view
                    and "Viewing turn 3 of 4" in replay_view
                    and "Older turns available: 1-2" in replay_view
                    and "Turn 3\nUser: prompt 3\nAgent: response 3" in replay_view,
                ),
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
