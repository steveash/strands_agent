from __future__ import annotations

from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore
from strands_agent_tui.testing import emit_smoke_results


def main() -> int:
    with TemporaryDirectory() as tmp:
        store = SessionArtifactStore(tmp, session_id="approval-restart-smoke")
        first_runtime = FakeStrandsRuntime()
        first = first_runtime.run("overwrite the notes file and replace all stale values")
        store.save_pending_approvals(first_runtime.pending_approvals())
        saved_pending = store.load_pending_approvals()

        restored_runtime = FakeStrandsRuntime()
        restored_runtime.restore_pending_approvals(saved_pending)
        approved = restored_runtime.resolve_pending_approval("approval-0001", approve=True)
        store.save_pending_approvals(restored_runtime.pending_approvals())
        remaining_pending = store.load_pending_approvals()

        return emit_smoke_results(
            [
                ("saved pending", [approval.summary() for approval in saved_pending]),
                (
                    "approval_restart_saved_queue",
                    len(saved_pending) == 2
                    and [approval.tool_name for approval in saved_pending] == ["write_file", "replace_text"],
                ),
                ("after restart approve text", approved.text),
                ("remaining pending", [approval.summary() for approval in remaining_pending]),
                (
                    "approval_restart_resumed_first_request",
                    first.pending_approval is not None
                    and approved.text.startswith("(fake-strands) Approved write_file.")
                    and approved.pending_approval is not None
                    and approved.pending_approval.request_id == "approval-0002",
                ),
                (
                    "approval_restart_remaining_queue",
                    len(remaining_pending) == 1
                    and remaining_pending[0].request_id == "approval-0002"
                    and remaining_pending[0].tool_name == "replace_text",
                ),
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
