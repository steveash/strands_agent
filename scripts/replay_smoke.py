from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact


def main() -> None:
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

        print("LIVE VIEW")
        print(app.render_history())
        app.history_focus_index = len(app.history) - 2
        print("\nREPLAY VIEW")
        print(app.render_history())


if __name__ == "__main__":
    main()
