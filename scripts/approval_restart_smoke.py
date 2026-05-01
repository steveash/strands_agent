from __future__ import annotations

from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import FakeStrandsRuntime
from strands_agent_tui.sessions import SessionArtifactStore


def main() -> None:
    with TemporaryDirectory() as tmp:
        store = SessionArtifactStore(tmp, session_id="approval-restart-smoke")
        first_runtime = FakeStrandsRuntime()
        first = first_runtime.run("overwrite the notes file and replace all stale values")
        store.save_pending_approvals(first_runtime.pending_approvals())
        print("saved pending=", [approval.summary() for approval in store.load_pending_approvals()])

        restored_runtime = FakeStrandsRuntime()
        restored_runtime.restore_pending_approvals(store.load_pending_approvals())
        approved = restored_runtime.resolve_pending_approval("approval-0001", approve=True)
        store.save_pending_approvals(restored_runtime.pending_approvals())
        print("after restart approve text=", approved.text)
        print("remaining pending=", [approval.summary() for approval in store.load_pending_approvals()])


if __name__ == "__main__":
    main()
