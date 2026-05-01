from __future__ import annotations

from tempfile import TemporaryDirectory

from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact, latest_session, render_session_picker


def append_turn(store: SessionArtifactStore, prompt: str) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response="ok",
            provider="fake-strands",
            mode="fake",
            events=[],
            response_metadata={"mode": "fake"},
        )
    )


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        older_store = SessionArtifactStore(temp_dir, session_id="session-older")
        append_turn(older_store, "inspect the older artifact set")

        newer_store = SessionArtifactStore(temp_dir, session_id="session-newer")
        append_turn(newer_store, "inspect the newer artifact set with more context")

        print(render_session_picker(temp_dir))
        summary = latest_session(temp_dir)
        if summary is None:
            raise RuntimeError("expected a latest session summary")
        print(f"latest={summary.session_id}")


if __name__ == "__main__":
    main()
