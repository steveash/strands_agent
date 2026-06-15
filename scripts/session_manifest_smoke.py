from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, SessionState, TurnArtifact
from strands_agent_tui.testing import emit_smoke_checks


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = SessionArtifactStore(root, session_id="manifest-smoke")
        store.append_turn(
            TurnArtifact(
                prompt="inspect workspace",
                response="done",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event("prompt_received", "Prompt accepted", "inspect workspace"),
                    runtime_event(
                        "tool_finished",
                        "list_files",
                        "Finished listing files",
                        data={"tool_name": "list_files", "result_preview": ".: README.md"},
                    ),
                ],
                response_metadata={
                    "mode": "fake",
                    "model": "gpt-4o-mini",
                    "workspace_root": str(root),
                },
            )
        )
        initial_manifest = store.load_manifest() or {}
        store.save_session_state(
            SessionState(
                pending_approvals=[
                    ApprovalRequest(
                        request_id="approval-0001",
                        tool_name="write_file",
                        reason="Overwrite requires confirmation",
                        args={"relative_path": "README.md"},
                    )
                ]
            )
        )
        pending_manifest = store.load_manifest() or {}
        store.clear_session_state()
        cleared_manifest = store.load_manifest() or {}

        print(f"manifest_path: {store.manifest_path}")
        print(f"manifest_turn_count: {initial_manifest.get('turn_count')}")
        print(f"manifest_tools: {initial_manifest.get('tool_counts')}")
        print(f"manifest_pending_after_save: {pending_manifest.get('pending_approval_count')}")
        print(f"manifest_pending_after_clear: {cleared_manifest.get('pending_approval_count')}")

        return emit_smoke_checks(
            [
                (
                    "session_manifest_written",
                    store.manifest_path.exists()
                    and initial_manifest.get("session_id") == "manifest-smoke"
                    and initial_manifest.get("turn_count") == 1,
                ),
                (
                    "session_manifest_metadata",
                    initial_manifest.get("model") == "gpt-4o-mini"
                    and initial_manifest.get("workspace_root") == str(root)
                    and initial_manifest.get("provider") == "fake-strands",
                ),
                (
                    "session_manifest_tool_counts",
                    initial_manifest.get("event_counts", {}).get("tool_finished") == 1
                    and initial_manifest.get("tool_counts", {}).get("list_files") == 1,
                ),
                (
                    "session_manifest_pending_state",
                    pending_manifest.get("pending_approval_count") == 1
                    and cleared_manifest.get("pending_approval_count") == 0,
                ),
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
