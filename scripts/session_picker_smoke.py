from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import (
    MAX_RECENT_SESSIONS,
    SessionArtifactStore,
    SessionState,
    TurnArtifact,
    latest_session,
    pick_session,
    render_session_picker,
)


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


def set_session_artifact_mtime(store: SessionArtifactStore, when: datetime) -> None:
    timestamp = when.timestamp()
    for path in [store.session_dir, *store.session_dir.iterdir()]:
        os.utime(path, (timestamp, timestamp))


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
        denied_event = runtime_event(
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
        denied_event.timestamp = (datetime.now(UTC) - timedelta(hours=6, minutes=5)).isoformat()
        denied_store.append_turn(
            TurnArtifact(
                prompt="deny the risky edit",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[denied_event],
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
                    created_at=(datetime.now(UTC) - timedelta(days=3, hours=2)).isoformat(),
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

        aged_store = SessionArtifactStore(temp_dir, session_id="session-aged")
        aged_turn_time = datetime.now(UTC) - timedelta(days=10)
        aged_store.append_turn(
            TurnArtifact(
                prompt="resume the stale test queue",
                response="ok",
                provider="fake-strands",
                mode="fake",
                events=[],
                response_metadata={"mode": "fake"},
                created_at=aged_turn_time.isoformat(),
            )
        )
        aged_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-aged",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="resume old tests",
                    created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
                )
            ]
        )
        set_session_artifact_mtime(aged_store, aged_turn_time)

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
        pending_attention_picker = render_session_picker(temp_dir, filter_mode="pending", sort_mode="attention")
        pending_attention_age_picker = render_session_picker(
            temp_dir,
            filter_mode="pending",
            sort_mode="attention",
            selected_index=2,
        )
        denied_picker = render_session_picker(temp_dir, filter_mode="denied")
        approval_restore_picker = render_session_picker(temp_dir, filter_mode="approval-restore")
        approval_stale_picker = render_session_picker(temp_dir, filter_mode="approval-stale")
        shell_picker = render_session_picker(temp_dir, filter_mode="shell")
        intervention_picker = render_session_picker(temp_dir, filter_mode="intervention")
        shell_inspect_picker = render_session_picker(temp_dir, filter_mode="shell-inspect")
        shell_test_picker = render_session_picker(temp_dir, filter_mode="shell-test")
        attention_picker = render_session_picker(temp_dir, sort_mode="attention")
        attention_page_two_picker = render_session_picker(temp_dir, sort_mode="attention", page_index=1)
        approval_restore_attention_picker = render_session_picker(temp_dir, filter_mode="approval-restore", sort_mode="attention")

        with TemporaryDirectory() as empty_hint_root:
            empty_store = SessionArtifactStore(empty_hint_root, session_id="session-empty")
            append_turn(empty_store, "plain session for empty-filter hint")
            empty_pending_picker = render_session_picker(empty_hint_root, filter_mode="pending")

        with TemporaryDirectory() as mixed_pending_root:
            mixed_pending_store = SessionArtifactStore(mixed_pending_root, session_id="session-pending-mixed")
            append_turn(mixed_pending_store, "queue mixed approvals")
            mixed_pending_store.save_pending_approvals(
                [
                    ApprovalRequest(
                        request_id="approval-mixed-1",
                        tool_name="run_shell_command",
                        reason="Needs confirmation",
                        args={"command": "pytest -q"},
                        source="fake_runtime",
                        prompt="run tests",
                    ),
                    ApprovalRequest(
                        request_id="approval-mixed-2",
                        tool_name="write_file",
                        reason="Needs confirmation",
                        args={"relative_path": "notes.txt", "overwrite": True},
                        source="fake_runtime",
                        prompt="queue edit",
                    ),
                    ApprovalRequest(
                        request_id="approval-mixed-3",
                        tool_name="list_files",
                        reason="Needs confirmation",
                        args={"relative_path": "."},
                        source="fake_runtime",
                        prompt="inspect tree",
                    ),
                ]
            )
            mixed_pending_picker = render_session_picker(mixed_pending_root, filter_mode="pending")

        with TemporaryDirectory() as mixed_restored_root:
            mixed_restored_store = SessionArtifactStore(mixed_restored_root, session_id="session-restored-mixed")
            append_turn(mixed_restored_store, "resume mixed restored approvals")
            mixed_restored_store.save_pending_approvals(
                [
                    ApprovalRequest(
                        request_id="approval-0020a",
                        tool_name="run_shell_command",
                        reason="Needs confirmation",
                        args={"command": "pytest -q"},
                        source="fake_runtime",
                        prompt="rerun restored tests",
                        restored_from_session=True,
                    ),
                    ApprovalRequest(
                        request_id="approval-0020b",
                        tool_name="write_file",
                        reason="Needs confirmation",
                        args={"relative_path": "notes.txt", "overwrite": True},
                        source="fake_runtime",
                        prompt="resume restored edit",
                        restored_from_session=True,
                    ),
                    ApprovalRequest(
                        request_id="approval-0020c",
                        tool_name="list_files",
                        reason="Needs confirmation",
                        args={"relative_path": "."},
                        source="fake_runtime",
                        prompt="resume restored inspection",
                        restored_from_session=True,
                    ),
                ]
            )
            mixed_restored_picker = render_session_picker(mixed_restored_root, filter_mode="approval-restore")

        for index in range(8):
            store = SessionArtifactStore(temp_dir, session_id=f"session-page-{index}")
            append_turn(store, f"page prompt {index}")

        paged_picker = render_session_picker(temp_dir, page_index=1)

        print("picker_default_banner=", "Filter: all | Sort: recent | Page: 1/2 | Showing: 1-8 of 13" in default_picker)
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
            "picker_shell_filter=",
            "Filter: shell | Sort: recent" in shell_picker
            and "session-inspect | 1 turn(s)" in shell_picker
            and "session-pending | 1 turn(s)" in shell_picker
            and "shell: inspect 1" in shell_picker
            and "session-tool | 1 turn(s)" not in shell_picker,
        )
        print(
            "picker_intervention_filter=",
            "Filter: intervention | Sort: recent" in intervention_picker
            and "session-pending | 1 turn(s)" in intervention_picker
            and "session-denied | 1 turn(s)" in intervention_picker
            and "intervention: pending 1" in intervention_picker
            and "session-plain | 1 turn(s)" not in intervention_picker,
        )
        print(
            "picker_intervention_preview=",
            "- last intervention:" in intervention_picker
            and "- recent interventions (" in intervention_picker,
        )
        print(
            "picker_shell_inspect_filter=",
            "Filter: shell-inspect | Sort: recent" in shell_inspect_picker
            and "session-inspect | 1 turn(s)" in shell_inspect_picker
            and "session-pending | 1 turn(s)" in shell_inspect_picker
            and "session-tool | 1 turn(s)" not in shell_inspect_picker,
        )
        print(
            "picker_shell_test_filter=",
            "Filter: shell-test | Sort: recent" in shell_test_picker
            and "session-pending | 1 turn(s)" in shell_test_picker
            and "session-aged | 1 turn(s)" in shell_test_picker
            and "session-failed-test | 1 turn(s)" in shell_test_picker
            and "session-inspect | 1 turn(s)" not in shell_test_picker,
        )
        print(
            "picker_shell_overlap_badge=",
            "session-pending | 1 turn(s)" in shell_inspect_picker
            and "shell lanes: inspect, test" in shell_inspect_picker
            and "shell lanes: inspect, test" in shell_test_picker,
        )
        print(
            "picker_denied_preview_origin=",
            "last denied approval: denied replace_text via fake_runtime | restored queue | remaining 0" in denied_picker,
        )
        print(
            "picker_denied_age=",
            "denied age: 6h" in denied_picker and "- last denied age: 6h" in denied_picker,
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
        print(
            "picker_restored_approval_age=",
            "approval restore age: 3d" in approval_restore_picker and "approval restore age: 6h" in approval_restore_picker,
        )
        print(
            "picker_restored_approval_preview_split=",
            "- last restored approval:" in approval_restore_picker
            or (
                "- restored current approval: pending run_shell_command via fake_runtime | queued 1"
                in approval_restore_picker
                and "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0"
                in approval_restore_picker
            ),
        )
        print(
            "picker_approval_stale_filter=",
            "Filter: approval-stale | Sort: recent" in approval_stale_picker
            and "session-aged | 1 turn(s)" in approval_stale_picker
            and "approval stale: pending 45d" in approval_stale_picker
            and "session-restored-pending | 1 turn(s)" not in approval_stale_picker,
        )
        print(
            "picker_approval_stale_backlog=",
            "Stale approval backlog: 1 session | lanes: pending 1 (oldest 45d)" in approval_stale_picker,
        )
        print(
            "picker_stale_cutoff_copy=",
            "Stale cutoff: approvals >= 7d old" in approval_stale_picker,
        )
        print(
            "picker_stale_lane_focus=",
            "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
            in approval_stale_picker
            and "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
            in approval_stale_picker,
        )
        print(
            "picker_stale_focus_rows=",
            "stale focus: pending" in approval_stale_picker,
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
            if line.startswith(("> 1. ", "  2. ", "  3. ", "  4. ", "  5. ", "  6. ", "  7. ", "  8. "))
        ]
        print(
            "picker_attention_sort=",
            len(attention_lines) >= 8
            and attention_lines[0].startswith("> 1. session-restored-pending")
            and attention_lines[1].startswith("  2. session-restored-edit-pending")
            and attention_lines[2].startswith("  3. session-aged")
            and attention_lines[3].startswith("  4. session-pending")
            and attention_lines[4].startswith("  5. session-pending-edit")
            and attention_lines[5].startswith("  6. session-denied-test")
            and attention_lines[6].startswith("  7. session-denied")
            and attention_lines[7].startswith("  8. session-failed-test"),
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
            "picker_pending_age_and_stale_cues=",
            "session-aged" in pending_attention_picker
            and "pending age: 45d" in pending_attention_picker
            and "stale: warning 10d" in pending_attention_picker
            and "- session age: idle 10d since last artifact activity" in pending_attention_age_picker,
        )
        print(
            "picker_pending_queue_breakdown=",
            "pending: 3 approvals (first test; rest edit 1, tool 1)" in mixed_pending_picker
            and "- pending queue: first test; rest edit 1, tool 1" in mixed_pending_picker,
        )
        print(
            "picker_restored_pending_queue_breakdown=",
            "approval restore queue: first test; rest edit 1, tool 1" in mixed_restored_picker
            and "- approval restore queue: first test; rest edit 1, tool 1" in mixed_restored_picker,
        )
        print(
            "picker_denied_test_attention=",
            "attention: denied test" in attention_picker
            and "denied: test 1" in attention_picker,
        )
        print(
            "picker_compact_attention_hints=",
            "attention: test fail" in attention_picker
            and "attention: tool fail" in attention_page_two_picker
            and "attention: restore" in attention_page_two_picker,
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
        print("picker_paged_banner=", "Page: 2/3 | Showing: 9-16 of 21" in paged_picker)
        print(
            "picker_paged_window=",
            "> 1. session-inspect" in paged_picker
            and "  2. session-tool" in paged_picker
            and "  8. session-denied" in paged_picker
            and "session-page-7" not in paged_picker,
        )

        with TemporaryDirectory() as stale_rollup_root:
            rollup_now = datetime.now(UTC)
            for index in range(MAX_RECENT_SESSIONS):
                store = SessionArtifactStore(stale_rollup_root, session_id=f"session-stale-pending-{index}")
                activity_time = rollup_now - timedelta(minutes=index)
                store.append_turn(
                    TurnArtifact(
                        prompt=f"resume stale pending queue {index}",
                        response="ok",
                        provider="fake-strands",
                        mode="fake",
                        events=[],
                        response_metadata={"mode": "fake"},
                        created_at=activity_time.isoformat(),
                    )
                )
                store.save_pending_approvals(
                    [
                        ApprovalRequest(
                            request_id=f"approval-stale-pending-{index}",
                            tool_name="run_shell_command",
                            reason="Needs confirmation",
                            args={"command": "pytest -q"},
                            source="fake_runtime",
                            prompt="rerun tests",
                            created_at=(rollup_now - timedelta(days=45 + index)).isoformat(),
                        )
                    ]
                )
                set_session_artifact_mtime(store, activity_time)

            denied_store = SessionArtifactStore(stale_rollup_root, session_id="session-stale-denied-page-2")
            denied_activity_time = rollup_now - timedelta(minutes=100)
            denied_event = runtime_event(
                "steering_denied",
                "run_shell_command",
                "Denied in the TUI",
                data={
                    "tool_name": "run_shell_command",
                    "approval_id": "approval-stale-denied-page-2",
                    "approval_status": "denied",
                    "approval_source": "fake_runtime",
                    "remaining_pending_count": 0,
                    "command": "pytest -q",
                },
            )
            denied_event.timestamp = (rollup_now - timedelta(days=14)).isoformat()
            denied_store.append_turn(
                TurnArtifact(
                    prompt="deny stale page-two test rerun",
                    response="ok",
                    provider="fake-strands",
                    mode="fake",
                    events=[denied_event],
                    response_metadata={"mode": "fake"},
                    created_at=denied_activity_time.isoformat(),
                )
            )
            set_session_artifact_mtime(denied_store, denied_activity_time)

            restored_store = SessionArtifactStore(stale_rollup_root, session_id="session-stale-restored-page-2")
            restored_activity_time = rollup_now - timedelta(minutes=101)
            restored_store.append_turn(
                TurnArtifact(
                    prompt="resume stale restored page-two queue",
                    response="ok",
                    provider="fake-strands",
                    mode="fake",
                    events=[],
                    response_metadata={"mode": "fake"},
                    created_at=restored_activity_time.isoformat(),
                )
            )
            restored_store.save_pending_approvals(
                [
                    ApprovalRequest(
                        request_id="approval-stale-restored-page-2",
                        tool_name="write_file",
                        reason="Needs confirmation",
                        args={"relative_path": "notes.txt", "overwrite": True},
                        source="fake_runtime",
                        prompt="resume edit",
                        restored_from_session=True,
                        created_at=(rollup_now - timedelta(days=11)).isoformat(),
                    )
                ]
            )
            restored_event = runtime_event(
                "steering_approved",
                "run_shell_command",
                "Approved in the TUI",
                data={
                    "tool_name": "run_shell_command",
                    "approval_id": "approval-stale-restored-page-2-approved",
                    "approval_status": "approved",
                    "approval_source": "fake_runtime",
                    "approval_restored": True,
                    "remaining_pending_count": 0,
                    "resumed_from_approval": True,
                    "command": "pytest -q",
                },
            )
            restored_event.timestamp = (rollup_now - timedelta(days=10)).isoformat()
            restored_store.append_turn(
                TurnArtifact(
                    prompt="approve stale restored page-two test rerun",
                    response="ok",
                    provider="fake-strands",
                    mode="fake",
                    events=[restored_event],
                    response_metadata={"mode": "fake"},
                    created_at=restored_activity_time.isoformat(),
                )
            )
            set_session_artifact_mtime(restored_store, restored_activity_time)

            stale_rollup_picker = render_session_picker(stale_rollup_root, filter_mode="approval-stale")
            stale_pending_picker = render_session_picker(stale_rollup_root, filter_mode="approval-stale-pending")
            stale_denied_picker = render_session_picker(stale_rollup_root, filter_mode="approval-stale-denied")
            stale_restored_picker = render_session_picker(stale_rollup_root, filter_mode="approval-stale-restored")
            stale_rollup_page_two_picker = render_session_picker(
                stale_rollup_root,
                filter_mode="approval-stale",
                page_index=1,
            )
            print(
                "picker_approval_stale_page_rollup=",
                "This page stale lanes: pending 8 (oldest 52d) | more off-page: denied 1 (oldest 14d), restore queue 1 (oldest 11d), restored 1 (oldest 10d)"
                in stale_rollup_picker
                and "This page stale lanes: denied 1 (oldest 14d), restore queue 1 (oldest 11d), restored 1 (oldest 10d) | more off-page: pending 8 (oldest 52d)"
                in stale_rollup_page_two_picker,
            )
            print(
                "picker_approval_stale_pending_filter=",
                "Filter: approval-stale-pending | Sort: recent" in stale_pending_picker
                and "Stale pending backlog: 8 sessions | lanes: pending 8 (oldest 52d)" in stale_pending_picker
                and "Stale lane focus: pending | cutoff: approvals >= 7d old" in stale_pending_picker
                and "| approval stale age: 45d | stale focus: pending" in stale_pending_picker
                and "| approval stale: pending 45d | stale focus: pending" not in stale_pending_picker
                and "- stale focus: pending" in stale_pending_picker
                and "- approval stale age: 45d" in stale_pending_picker
                and "- approval stale: pending 45d" not in stale_pending_picker
                and "stale focus: pending" in stale_pending_picker
                and "session-stale-pending-0" in stale_pending_picker
                and "session-stale-denied-page-2" not in stale_pending_picker,
            )
            print(
                "picker_approval_stale_denied_filter=",
                "Filter: approval-stale-denied | Sort: recent" in stale_denied_picker
                and "Stale denied backlog: 1 session | lanes: denied 1 (oldest 14d)" in stale_denied_picker
                and "Stale lane focus: denied | cutoff: approvals >= 7d old" in stale_denied_picker
                and "| approval stale age: 14d | stale focus: denied" in stale_denied_picker
                and "| approval stale: denied 14d | stale focus: denied" not in stale_denied_picker
                and "- stale focus: denied" in stale_denied_picker
                and "- approval stale age: 14d" in stale_denied_picker
                and "- approval stale: denied 14d" not in stale_denied_picker
                and "stale focus: denied" in stale_denied_picker
                and "session-stale-denied-page-2" in stale_denied_picker
                and "session-stale-restored-page-2" not in stale_denied_picker,
            )
            print(
                "picker_approval_stale_restored_filter=",
                "Filter: approval-stale-restored | Sort: recent" in stale_restored_picker
                and "Stale restored backlog: 1 session | lanes: restore queue 1 (oldest 11d), restored 1 (oldest 10d)" in stale_restored_picker
                and "Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old"
                in stale_restored_picker
                and "| approval stale ages: restore queue 11d; restored 10d | stale focus: restore queue, restored"
                in stale_restored_picker
                and "restored current: pending write_file via fake_runtime; queued 1" in stale_restored_picker
                and "restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0"
                in stale_restored_picker
                and "restored outcome age: 10d" in stale_restored_picker
                and "| approval stale: restore queue 11d, restored 10d | stale focus: restore queue, restored" not in stale_restored_picker
                and "- stale focus: restore queue, restored" in stale_restored_picker
                and "- approval stale ages: restore queue 11d; restored 10d" in stale_restored_picker
                and "- restored current approval: pending write_file via fake_runtime | queued 1" in stale_restored_picker
                and "- latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0"
                in stale_restored_picker
                and "- latest restored outcome age: 10d" in stale_restored_picker
                and "- approval stale: restore queue 11d, restored 10d" not in stale_restored_picker
                and "stale focus: restore queue" in stale_restored_picker
                and "session-stale-restored-page-2" in stale_restored_picker
                and "session-stale-denied-page-2" not in stale_restored_picker,
            )

        with TemporaryDirectory() as custom_stale_root:
            custom_store = SessionArtifactStore(custom_stale_root, session_id="session-custom-threshold")
            append_turn(custom_store, "resume moderately old pending queue")
            custom_store.save_pending_approvals(
                [
                    ApprovalRequest(
                        request_id="approval-custom-threshold",
                        tool_name="run_shell_command",
                        reason="Needs confirmation",
                        args={"command": "pytest -q"},
                        source="fake_runtime",
                        prompt="rerun tests",
                        created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
                    )
                ]
            )
            custom_stale_picker = render_session_picker(
                custom_stale_root,
                filter_mode="approval-stale",
                stale_approval_warning_seconds=24 * 60 * 60,
            )
            print(
                "picker_custom_stale_threshold=",
                "Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d)" in custom_stale_picker
                and "session-custom-threshold" in custom_stale_picker,
            )
            print(
                "picker_custom_stale_cutoff_copy=",
                "Stale cutoff: approvals >= 1d old" in custom_stale_picker,
            )
            print(
                "picker_custom_stale_lane_focus=",
                "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old"
                in custom_stale_picker,
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
            any("Page: 2/3 | Showing: 9-16 of 21" in line for line in paged_captured),
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
            any("Page: 2/3 | Showing: 9-16 of 21" in line for line in restored_captured),
        )
        print(
            "picker_restored_preview=",
            any(
                "- slot 2 on this page | overall 10 of 21 | session session-tool" in line
                for line in restored_captured
            ),
        )

        latest = latest_session(temp_dir)
        if latest is None:
            raise RuntimeError("expected a latest session summary")
        print(f"latest={latest.session_id}")


if __name__ == "__main__":
    main()
