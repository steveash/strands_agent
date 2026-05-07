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

        pending_edit_store = SessionArtifactStore(temp_dir, session_id="session-pending-edit")
        append_turn(pending_edit_store, "queue the risky edit")
        pending_edit_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0001b",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="queue edit",
                )
            ]
        )

        denied_test_store = SessionArtifactStore(temp_dir, session_id="session-denied-test")
        denied_test_store.append_turn(
            TurnArtifact(
                prompt="deny the risky test approval",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "steering_denied",
                        "run_shell_command",
                        "Denied in the TUI",
                        data={
                            "tool_name": "run_shell_command",
                            "approval_id": "approval-0008",
                            "approval_status": "denied",
                            "approval_source": "fake_runtime",
                            "remaining_pending_count": 0,
                            "command": "pytest -q",
                        },
                    )
                ],
                response_metadata={"mode": "fake"},
            )
        )

        denied_store = SessionArtifactStore(temp_dir, session_id="session-denied")
        denied_store.append_turn(
            TurnArtifact(
                prompt="deny the risky edit",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "steering_denied",
                        "replace_text",
                        "Denied in the TUI",
                        data={
                            "tool_name": "replace_text",
                            "approval_id": "approval-0009",
                            "approval_status": "denied",
                            "approval_source": "fake_runtime",
                            "approval_restored": True,
                            "remaining_pending_count": 0,
                        },
                    )
                ],
                response_metadata={"mode": "fake"},
            )
        )

        restored_pending_store = SessionArtifactStore(temp_dir, session_id="session-restored-pending")
        append_turn(restored_pending_store, "resume the restored test queue")
        restored_pending_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0011",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="resume tests",
                    restored_from_session=True,
                )
            ]
        )

        restored_edit_pending_store = SessionArtifactStore(temp_dir, session_id="session-restored-edit-pending")
        append_turn(restored_edit_pending_store, "resume the restored edit queue")
        restored_edit_pending_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0012",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="resume edit",
                    restored_from_session=True,
                )
            ]
        )

        restore_store = SessionArtifactStore(temp_dir, session_id="session-restore")
        append_turn(restore_store, "resume the saved triage flow")
        restore_store.save_session_state(SessionState(draft_prompt="queued follow-up"))

        failed_test_store = SessionArtifactStore(temp_dir, session_id="session-failed-test")
        failed_test_store.append_turn(
            TurnArtifact(
                prompt="run the failing test suite",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "tool_failed",
                        "run_shell_command",
                        "Shell test failed",
                        data={
                            "tool_name": "run_shell_command",
                            "command": "pytest -q",
                            "shell_policy": "confirm",
                            "exit_code": 1,
                            "result_preview": "pytest -q -> exit 1",
                        },
                    )
                ],
                response_metadata={"mode": "fake"},
            )
        )

        failed_tool_store = SessionArtifactStore(temp_dir, session_id="session-failed-tool")
        failed_tool_store.append_turn(
            TurnArtifact(
                prompt="attempt the failing edit",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "tool_failed",
                        "replace_text",
                        "Edit failed",
                        data={
                            "tool_name": "replace_text",
                            "result_preview": "replace_text notes.txt (2 occurrences)",
                        },
                    )
                ],
                response_metadata={"mode": "fake"},
            )
        )

        tool_store = SessionArtifactStore(temp_dir, session_id="session-tool")
        tool_store.append_turn(
            TurnArtifact(
                prompt="list files",
                response="ok",
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

        inspect_store = SessionArtifactStore(temp_dir, session_id="session-inspect")
        inspect_store.append_turn(
            TurnArtifact(
                prompt="inspect repo",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[
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
        denied_picker = render_session_picker(temp_dir, filter_mode="denied")
        approval_restore_picker = render_session_picker(temp_dir, filter_mode="approval-restore")
        attention_picker = render_session_picker(temp_dir, sort_mode="attention")
        attention_page_two_picker = render_session_picker(temp_dir, sort_mode="attention", page_index=1)
        approval_restore_attention_picker = render_session_picker(temp_dir, filter_mode="approval-restore", sort_mode="attention")

        with TemporaryDirectory() as empty_hint_root:
            empty_store = SessionArtifactStore(empty_hint_root, session_id="session-empty")
            append_turn(empty_store, "plain session for empty-filter hint")
            empty_pending_picker = render_session_picker(empty_hint_root, filter_mode="pending")

        for index in range(8):
            store = SessionArtifactStore(temp_dir, session_id=f"session-page-{index}")
            append_turn(store, f"page prompt {index}")

        paged_picker = render_session_picker(temp_dir, page_index=1)

        print("picker_default_banner=", "Filter: all | Sort: recent | Page: 1/2 | Showing: 1-8 of 12" in default_picker)
        print("picker_default_preview=", "Selected preview:" in default_picker and "- artifact dir:" in default_picker)
        print("picker_pending_filter=", "Filter: pending | Sort: recent" in pending_picker)
        print(
            "picker_pending_only_pending=",
            "session-pending" in pending_picker
            and "session-pending-edit" in pending_picker
            and "session-plain" not in pending_picker,
        )
        print(
            "picker_denied_filter=",
            "Filter: denied | Sort: recent" in denied_picker and "session-denied" in denied_picker and "session-plain" not in denied_picker,
        )
        print(
            "picker_approval_restore_filter=",
            "Filter: approval-restore | Sort: recent" in approval_restore_picker
            and "session-restored-pending" in approval_restore_picker
            and "session-restored-edit-pending" in approval_restore_picker
            and "session-denied" in approval_restore_picker
            and "session-restore | 1 turn(s)" not in approval_restore_picker,
        )
        print(
            "picker_denied_preview_origin=",
            "last denied approval: denied replace_text via fake_runtime | restored queue | remaining 0" in denied_picker,
        )
        print(
            "picker_denied_badges=",
            "denied: edit 1" in denied_picker,
        )
        print(
            "picker_restored_approval_badge=",
            "approval restore: pending 1" in approval_restore_picker and "approval restore: denied 1" in approval_restore_picker,
        )
        print(
            "picker_restored_approval_tool_badges=",
            "approval restore tools: test 1" in approval_restore_picker and "approval restore tools: edit 1" in approval_restore_picker,
        )
        print("picker_approval_rollup=", "approvals: pending 1, approved 1" in pending_picker)
        print("picker_row_approval_focus=", "approval focus: denied/restored" in denied_picker and "approval focus: pending" in default_picker)
        print(
            "picker_empty_hint=",
            "Try A to show all sessions" in empty_pending_picker
            and "Press Enter or N to start a fresh session while keeping this picker context for the next reopen." in empty_pending_picker,
        )
        print(
            "picker_shell_rollup=",
            "shell: inspect 1" in default_picker
            and "- last shell: inspect/e0 git status --short -> M README.md" in default_picker,
        )
        print(
            "picker_tool_streak_preview=",
            "- recent tools (1):" in default_picker and "inspect/e0 git status --short -> M README.md" in default_picker,
        )
        print(
            "picker_failure_badges=",
            "failures: test 1" in default_picker and "failures: tool 1" in default_picker,
        )
        attention_lines = [
            line
            for line in attention_picker.splitlines()
            if line.startswith(("> 1. ", "  2. ", "  3. ", "  4. ", "  5. ", "  6. "))
        ]
        print(
            "picker_attention_sort=",
            len(attention_lines) >= 6
            and attention_lines[0].startswith("> 1. session-restored-pending")
            and attention_lines[1].startswith("  2. session-restored-edit-pending")
            and attention_lines[2].startswith("  3. session-pending")
            and attention_lines[3].startswith("  4. session-pending-edit")
            and attention_lines[4].startswith("  5. session-denied-test")
            and attention_lines[5].startswith("  6. session-denied"),
        )
        approval_restore_attention_lines = [
            line
            for line in approval_restore_attention_picker.splitlines()
            if line.startswith(("> 1. ", "  2. ", "  3. "))
        ]
        print(
            "picker_approval_restore_attention_order=",
            len(approval_restore_attention_lines) >= 3
            and approval_restore_attention_lines[0].startswith("> 1. session-restored-pending")
            and approval_restore_attention_lines[1].startswith("  2. session-restored-edit-pending")
            and approval_restore_attention_lines[2].startswith("  3. session-denied"),
        )
        print(
            "picker_attention_reason=",
            "- attention reason: restored pending test approval queue; tests sort ahead of restored edits"
            in approval_restore_attention_picker,
        )
        print(
            "picker_row_attention_reason=",
            "attention: restored test queue" in approval_restore_attention_picker
            and "attention: restored edit queue" in approval_restore_attention_picker
            and "attention: restored denied edit" in approval_restore_attention_picker,
        )
        print(
            "picker_pending_attention_reason=",
            "attention: pending test" in attention_picker
            and "attention: pending edit" in attention_picker
            and "pending tools: test 1" in attention_picker
            and "pending tools: edit 1" in attention_picker,
        )
        print(
            "picker_denied_test_attention=",
            "attention: denied test" in attention_picker
            and "denied: test 1" in attention_picker,
        )
        print(
            "picker_compact_attention_hints=",
            "attention: test fail" in attention_picker
            and "attention: tool fail" in attention_picker
            and "attention: restore" in attention_picker,
        )
        print(
            "picker_suppressed_generic_attention_hints=",
            not any(
                "attention: shell |" in line
                or line.endswith("attention: shell")
                or "attention: tool |" in line
                or line.endswith("attention: tool")
                for line in attention_page_two_picker.splitlines()
            )
            and "session-inspect | 1 turn(s)" in attention_page_two_picker
            and "session-tool | 1 turn(s)" in attention_page_two_picker,
        )
        print("picker_paged_banner=", "Page: 2/3 | Showing: 9-16 of 20" in paged_picker)
        print(
            "picker_paged_window=",
            "> 1. session-inspect" in paged_picker
            and "  2. session-tool" in paged_picker
            and "  8. session-denied" in paged_picker
            and "session-page-7" not in paged_picker,
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
        print(
            "picker_interactive_pending_badges=",
            any("pending tools: test 1" in line for line in captured),
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
            any("Page: 2/3 | Showing: 9-16 of 20" in line for line in paged_captured),
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
            any("Page: 2/3 | Showing: 9-16 of 20" in line for line in restored_captured),
        )
        print(
            "picker_restored_preview=",
            any(
                "- slot 2 on this page | overall 10 of 20 | session session-tool" in line
                for line in restored_captured
            ),
        )

        latest = latest_session(temp_dir)
        if latest is None:
            raise RuntimeError("expected a latest session summary")
        print(f"latest={latest.session_id}")


if __name__ == "__main__":
    main()
