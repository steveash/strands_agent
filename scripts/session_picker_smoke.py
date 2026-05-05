from __future__ import annotations

from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, SessionState, TurnArtifact, latest_session, pick_session, render_session_picker


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
        plain_store = SessionArtifactStore(temp_dir, session_id="session-plain")
        append_turn(plain_store, "inspect the plain artifact set")

        pending_store = SessionArtifactStore(temp_dir, session_id="session-pending")
        pending_store.append_turn(
            TurnArtifact(
                prompt="run the gated test suite",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "steering_approved",
                        "write_file",
                        "Approved in the TUI",
                        data={
                            "tool_name": "write_file",
                            "approval_id": "approval-0000",
                            "approval_status": "approved",
                            "approval_source": "fake_runtime",
                            "remaining_pending_count": 1,
                            "resumed_from_approval": True,
                        },
                    ),
                    runtime_event(
                        "steering_confirmation_required",
                        "run_shell_command",
                        "Needs confirmation",
                        data={
                            "tool_name": "run_shell_command",
                            "approval_id": "approval-0001",
                            "approval_status": "pending",
                            "approval_source": "fake_runtime",
                            "pending_count": 1,
                        },
                    ),
                ],
                response_metadata={"mode": "fake"},
            )
        )
        pending_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0001",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="run tests",
                )
            ]
        )

        restore_store = SessionArtifactStore(temp_dir, session_id="session-restore")
        append_turn(restore_store, "resume the saved triage flow")
        restore_store.save_session_state(SessionState(draft_prompt="queued follow-up"))

        tool_store = SessionArtifactStore(temp_dir, session_id="session-tool")
        tool_store.append_turn(
            TurnArtifact(
                prompt="inspect repo",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "tool_finished",
                        "list_files",
                        "Finished listing files",
                        data={"tool_name": "list_files", "result_preview": ".: README.md"},
                    ),
                    runtime_event(
                        "tool_finished",
                        "run_shell_command",
                        "Finished shell command",
                        data={
                            "tool_name": "run_shell_command",
                            "command": "git status --short",
                            "shell_policy": "inspect",
                            "exit_code": 0,
                            "result_preview": "git status --short -> M README.md",
                        },
                    ),
                ],
                response_metadata={"mode": "fake"},
            )
        )

        default_picker = render_session_picker(temp_dir)
        pending_picker = render_session_picker(temp_dir, filter_mode="pending")
        attention_picker = render_session_picker(temp_dir, sort_mode="attention")

        with TemporaryDirectory() as empty_hint_root:
            empty_store = SessionArtifactStore(empty_hint_root, session_id="session-empty")
            append_turn(empty_store, "plain session for empty-filter hint")
            empty_pending_picker = render_session_picker(empty_hint_root, filter_mode="pending")

        for index in range(8):
            store = SessionArtifactStore(temp_dir, session_id=f"session-page-{index}")
            append_turn(store, f"page prompt {index}")

        paged_picker = render_session_picker(temp_dir, page_index=1)

        print("picker_default_banner=", "Filter: all | Sort: recent | Page: 1/1 | Showing: 1-4 of 4" in default_picker)
        print("picker_default_preview=", "Selected preview:" in default_picker and "- artifact dir:" in default_picker)
        print("picker_pending_filter=", "Filter: pending | Sort: recent" in pending_picker)
        print("picker_pending_only_pending=", "session-pending" in pending_picker and "session-plain" not in pending_picker)
        print("picker_approval_rollup=", "approvals: pending 1, approved 1" in default_picker)
        print(
            "picker_empty_hint=",
            "Try A to show all sessions" in empty_pending_picker
            and "Press Enter or N to start a fresh session while keeping this picker context for the next reopen." in empty_pending_picker,
        )
        print("picker_tool_streak_preview=", "- recent tools (2):" in default_picker and "inspect/e0 git status --short -> M README.md" in default_picker)
        attention_lines = [line for line in attention_picker.splitlines() if line.startswith(("> 1. ", "  2. ", "  3. "))]
        print("picker_attention_sort=", bool(attention_lines) and attention_lines[0].startswith("> 1. session-pending"))
        print("picker_paged_banner=", "Page: 2/2 | Showing: 9-12 of 12" in paged_picker)
        print(
            "picker_paged_window=",
            "> 1. session-tool" in paged_picker and "  4. session-plain" in paged_picker and "session-page-07" not in paged_picker,
        )

        captured: list[str] = []
        inputs = iter(["p", "s", "j", "k", ""])
        summary = pick_session(
            temp_dir,
            input_fn=lambda _prompt: next(inputs),
            output_fn=captured.append,
        )
        if summary is None:
            raise RuntimeError("expected an interactive picker selection")
        print("picker_interactive_selected=", summary.session_id)
        print(
            "picker_interactive_toggled=",
            any("Filter: pending | Sort: attention" in line for line in captured),
        )
        print(
            "picker_interactive_preview=",
            any("Selected preview:" in line and "command='pytest -q'" in line for line in captured),
        )

        paged_captured: list[str] = []
        paged_inputs = iter(["]", "4"])
        paged_summary = pick_session(
            temp_dir,
            filter_mode="all",
            sort_mode="recent",
            input_fn=lambda _prompt: next(paged_inputs),
            output_fn=paged_captured.append,
        )
        if paged_summary is None:
            raise RuntimeError("expected a paged interactive picker selection")
        print("picker_interactive_paged_selected=", paged_summary.session_id)
        print(
            "picker_interactive_paged_banner=",
            any("Page: 2/2 | Showing: 9-12 of 12" in line for line in paged_captured),
        )

        aborted_inputs = iter(["]", "j", "n"])
        aborted_summary = pick_session(
            temp_dir,
            filter_mode="all",
            sort_mode="recent",
            input_fn=lambda _prompt: next(aborted_inputs),
            output_fn=lambda _line: None,
        )
        if aborted_summary is not None:
            raise RuntimeError("expected the aborted picker run to start a new session")

        restored_captured: list[str] = []
        restored_inputs = iter([""])
        restored_summary = pick_session(
            temp_dir,
            input_fn=lambda _prompt: next(restored_inputs),
            output_fn=restored_captured.append,
        )
        if restored_summary is None:
            raise RuntimeError("expected a restored picker selection")
        print("picker_restored_selected=", restored_summary.session_id)
        print(
            "picker_restored_page=",
            any("Page: 2/2 | Showing: 9-12 of 12" in line for line in restored_captured),
        )
        print(
            "picker_restored_preview=",
            any(
                "- slot 2 on this page | overall 10 of 12 | session session-restore" in line
                for line in restored_captured
            ),
        )

        latest = latest_session(temp_dir)
        if latest is None:
            raise RuntimeError("expected a latest session summary")
        print(f"latest={latest.session_id}")


if __name__ == "__main__":
    main()
