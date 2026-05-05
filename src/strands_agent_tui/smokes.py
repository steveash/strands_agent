from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import StrandsSDKRuntime, build_workspace_tools
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact, list_recent_sessions


class _StubLiveRestoreRuntime(StrandsSDKRuntime):
    def _build_agent(self, api_key: str, event_sink=None):
        tools = build_workspace_tools(
            self.workspace_root,
            event_sink=event_sink,
            approval_queue=self._approval_queue,
            approval_source="live_runtime",
            prompt_provider=lambda: self._active_prompt,
        )
        tool_map = {tool.tool_name: tool for tool in tools}

        def agent(prompt: str) -> str:
            if prompt.startswith("User approved pending tool `write_file`"):
                return f"continued: {prompt.splitlines()[0]}"
            return tool_map["write_file"](
                relative_path="notes.txt",
                content="updated from restored approval\n",
                overwrite=True,
            )

        return agent, len(tools)


def _append_response(store: SessionArtifactStore, prompt: str, response) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response=response.text,
            provider=response.provider,
            mode=response.mode,
            events=response.events,
            response_metadata=response.metadata,
        )
    )


def run_live_restore_smoke() -> dict[str, object]:
    with TemporaryDirectory() as workspace_tmp, TemporaryDirectory() as artifacts_tmp:
        workspace_root = Path(workspace_tmp)
        artifacts_root = Path(artifacts_tmp)
        (workspace_root / "notes.txt").write_text("old\n", encoding="utf-8")
        store = SessionArtifactStore(artifacts_root, session_id="live-restore-smoke")

        previous_api_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = previous_api_key or "test-key"
        try:
            first_runtime = _StubLiveRestoreRuntime(workspace_root=workspace_root)
            first_prompt = "overwrite the notes file"
            first = first_runtime.run(first_prompt)
            _append_response(store, first_prompt, first)
            store.save_pending_approvals(first_runtime.pending_approvals())

            restored_pending = store.load_pending_approvals()
            restored_runtime = _StubLiveRestoreRuntime(workspace_root=workspace_root)
            restored_runtime.restore_pending_approvals(restored_pending)
            restored_queue = restored_runtime.pending_approvals()
            approved = restored_runtime.resolve_pending_approval("approval-0001", approve=True)
            _append_response(store, "approve restored write", approved)
            store.save_pending_approvals(restored_runtime.pending_approvals())
        finally:
            if previous_api_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_api_key

        summary = list_recent_sessions(artifacts_root)[0]
        initial_pending_event = next((event for event in first.events if event.kind == "steering_confirmation_required"), None)
        approved_event = next((event for event in approved.events if event.kind == "steering_approved"), None)
        finished_event = next((event for event in approved.events if event.kind == "tool_finished"), None)

        return {
            "live_restore_initial_pending": first.pending_approval is not None
            and initial_pending_event is not None
            and initial_pending_event.data.get("approval_status") == "pending"
            and initial_pending_event.data.get("approval_source") == "live_runtime"
            and initial_pending_event.data.get("pending_count") == 1,
            "live_restore_saved_pending": len(restored_pending) == 1
            and restored_pending[0].request_id == "approval-0001"
            and restored_pending[0].source == "live_runtime",
            "live_restore_restored_queue": len(restored_queue) == 1
            and restored_queue[0].request_id == "approval-0001",
            "live_restore_approved_event": approved_event is not None
            and approved_event.data.get("approval_status") == "approved"
            and approved_event.data.get("approval_source") == "live_runtime"
            and approved_event.data.get("resumed_from_approval") is True,
            "live_restore_tool_event": finished_event is not None
            and finished_event.data.get("approval_status") == "approved"
            and finished_event.data.get("approval_source") == "live_runtime"
            and finished_event.data.get("remaining_pending_count") == 0
            and finished_event.data.get("resumed_from_approval") is True,
            "live_restore_summary": summary.last_approval_summary
            == "approved write_file via live_runtime | resumed | remaining 0"
            and summary.approval_status_badges == ["approved 1"],
            "summary_value": summary.last_approval_summary,
            "notes_text": (workspace_root / "notes.txt").read_text(encoding="utf-8").strip(),
        }
