from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import MAX_RECENT_SESSIONS, SessionArtifactStore, SessionState, TurnArtifact


def append_turn(store: SessionArtifactStore, prompt: str, response: str) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response=response,
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


async def run_smoke() -> None:
    with TemporaryDirectory() as temp_dir:
        older_store = SessionArtifactStore(temp_dir, session_id="session-older")
        append_turn(older_store, "inspect older session", "older response")

        newer_store = SessionArtifactStore(temp_dir, session_id="session-newer")
        newer_store.append_turn(
            TurnArtifact(
                prompt="inspect newer session",
                response="newer response",
                provider="fake-strands",
                mode="fake",
                events=[
                    runtime_event(
                        "steering_approved",
                        "write_file",
                        "Approved in the TUI",
                        data={
                            "tool_name": "write_file",
                            "approval_id": "approval-0003",
                            "approval_status": "approved",
                            "approval_source": "fake_runtime",
                            "remaining_pending_count": 1,
                            "resumed_from_approval": True,
                        },
                    ),
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
        newer_store.save_session_state(
            SessionState(
                event_filter="tool",
                history_focus_index=0,
                draft_prompt="draft next step",
            )
        )
        newer_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0004",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest"},
                    source="fake_runtime",
                    prompt="run pytest",
                )
            ]
        )

        aged_store = SessionArtifactStore(temp_dir, session_id="session-aged")
        aged_turn_time = datetime.now(UTC) - timedelta(days=10)
        aged_store.append_turn(
            TurnArtifact(
                prompt="resume stale queue",
                response="stale response",
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
                    request_id="approval-aged-switcher",
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

        pending_edit_store = SessionArtifactStore(temp_dir, session_id="session-pending-edit")
        append_turn(pending_edit_store, "queue pending edit", "queued edit response")
        pending_edit_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0004b",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="queue edit",
                )
            ]
        )

        denied_store = SessionArtifactStore(temp_dir, session_id="session-denied")
        denied_event = runtime_event(
            "steering_denied",
            "replace_text",
            "Denied in the TUI",
            data={
                "tool_name": "replace_text",
                "approval_id": "approval-0005",
                "approval_status": "denied",
                "approval_source": "fake_runtime",
                "approval_restored": True,
                "remaining_pending_count": 0,
            },
        )
        denied_event.timestamp = (datetime.now(UTC) - timedelta(hours=6, minutes=5)).isoformat()
        denied_store.append_turn(
            TurnArtifact(
                prompt="deny risky edit",
                response="skipped",
                provider="fake-strands",
                mode="fake",
                events=[denied_event],
                response_metadata={"mode": "fake"},
            )
        )

        restored_pending_store = SessionArtifactStore(temp_dir, session_id="session-restored-pending")
        append_turn(restored_pending_store, "resume restored test queue", "restored pending response")
        restored_pending_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0006",
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
        append_turn(restored_edit_pending_store, "resume restored edit queue", "restored edit response")
        restored_edit_pending_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-0006b",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="resume edit",
                    restored_from_session=True,
                )
            ]
        )

        failed_test_store = SessionArtifactStore(temp_dir, session_id="session-failed-test")
        failed_test_store.append_turn(
            TurnArtifact(
                prompt="run failing test",
                response="done",
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
                prompt="attempt failing edit",
                response="done",
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
                response="done",
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

        first_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-older",
            ),
            artifact_store=older_store,
        )

        async with first_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            switcher_output = first_app.query_one("#output").render()
            selected_line = next(
                (line for line in str(switcher_output).splitlines() if line.startswith("> ")),
                "",
            )
            print("switcher_default_selection_is_most_recent=", "session-tool" in selected_line and "(current)" not in selected_line)
            print("switcher_has_pending_marker=", "pending: run_shell_command" in str(switcher_output))
            print("switcher_has_approval_rollup=", "approvals: pending 1, approved 1" in str(switcher_output))
            print(
                "switcher_has_restore_badges=",
                "restore: filter=tool, replay 1/1, draft 15c" in str(switcher_output),
            )
            print("switcher_has_tool_preview=", "last tool: inspect/e0 git status --short -> M README.md" in str(switcher_output))
            print("switcher_has_shell_rollup=", "shell: inspect 1" in str(switcher_output))
            print("switcher_has_event_preview=", "last event: tool_finished: run_shell_command" in str(switcher_output))
            for _ in range(7):
                await pilot.press("down")
                await pilot.pause()
            selected_preview_output = first_app.query_one("#output").render()
            print(
                "switcher_selected_preview=",
                "Selected preview:" in str(selected_preview_output)
                or "- artifact dir:" in str(selected_preview_output),
            )
            print(
                "switcher_last_approval_preview=",
                "last approval: pending run_shell_command via fake_runtime | queued 1" in str(selected_preview_output),
            )
            print(
                "switcher_shell_preview=",
                "- last shell: inspect/e0 git status --short -> M README.md" in str(selected_preview_output),
            )
            print("switcher_tool_streak_preview=", "recent tools (2)" in str(selected_preview_output))
            await pilot.press("p")
            await pilot.pause()
            pending_output = first_app.query_one("#output").render()
            pending_text = str(pending_output)
            print("switcher_pending_filter=", "Filter: pending | Sort: recent" in str(pending_output))
            print(
                "switcher_pending_filter_only_newer=",
                "session-newer | 1 turn(s)" in pending_text
                and "session-aged | 1 turn(s)" in pending_text
                and "session-pending-edit | 1 turn(s)" in pending_text
                and "session-older | 1 turn(s)" not in pending_text,
            )
            print(
                "switcher_pending_age_and_stale_cues=",
                "session-aged | 1 turn(s)" in pending_text
                and "pending age: 45d" in pending_text
                and "stale: warning 10d" in pending_text,
            )
            await pilot.press("d")
            await pilot.pause()
            denied_output = first_app.query_one("#output").render()
            denied_text = str(denied_output)
            print("switcher_denied_filter=", "Filter: denied | Sort: recent" in denied_text)
            print(
                "switcher_denied_filter_only_denied=",
                "session-denied | 1 turn(s)" in denied_text and "session-newer | 1 turn(s)" not in denied_text,
            )
            print(
                "switcher_denied_preview_origin=",
                "last denied approval: denied replace_text via fake_runtime | restored queue | remaining 0" in denied_text,
            )
            print(
                "switcher_denied_age=",
                "denied age: 6h" in denied_text and "- last denied age: 6h" in denied_text,
            )
            print("switcher_row_approval_focus=", "approval focus: denied/restored" in denied_text)
            print("switcher_denied_badges=", "denied: edit 1" in denied_text)
            print("switcher_restored_approval_badge=", "approval restore: denied 1" in denied_text)
            await pilot.press("v")
            await pilot.pause()
            approval_restore_output = first_app.query_one("#output").render()
            approval_restore_text = str(approval_restore_output)
            print("switcher_approval_restore_filter=", "Filter: approval-restore | Sort: recent" in approval_restore_text)
            print(
                "switcher_approval_restore_only_restored=",
                "session-denied | 1 turn(s)" in approval_restore_text
                and "session-restored-pending | 1 turn(s)" in approval_restore_text
                and "session-restored-edit-pending | 1 turn(s)" in approval_restore_text
                and "Approval restore backlog: 3 sessions | lanes: restore queue 2 (oldest 3d), restored 1 (oldest 6h)"
                in approval_restore_text
                and "Restore lane focus: restore queue, restored" in approval_restore_text
                and "session-newer | 1 turn(s)" not in approval_restore_text,
            )
            print(
                "switcher_restored_approval_tool_badges=",
                "approval restore tools: test 1" in approval_restore_text
                and "approval restore tools: edit 1" in approval_restore_text,
            )
            print(
                "switcher_restored_approval_age=",
                "approval restore age: 3d" in approval_restore_text
                and "approval restore age: 6h" in approval_restore_text,
            )
            print(
                "switcher_last_restored_approval_preview=",
                "last restored approval:" in approval_restore_text
                or "restored current approval:" in approval_restore_text,
            )
            print(
                "switcher_restored_approval_preview_split=",
                "- last restored approval:" in approval_restore_text
                or (
                    "- restored current approval: pending run_shell_command via fake_runtime | queued 1"
                    in approval_restore_text
                    and "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0"
                    in approval_restore_text
                ),
            )
            await pilot.press("s")
            await pilot.pause()
            attention_output = first_app.query_one("#output").render()
            print("switcher_attention_sort=", "Filter: approval-restore | Sort: attention" in str(attention_output))
            attention_text = str(attention_output)
            print(
                "switcher_approval_restore_attention_order=",
                attention_text.index("session-restored-pending | 1 turn(s)")
                < attention_text.index("session-restored-edit-pending | 1 turn(s)")
                < attention_text.index("session-denied | 1 turn(s)"),
            )
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            attention_preview_output = str(first_app.query_one("#output").render())
            print(
                "switcher_attention_reason=",
                "- attention reason: restored pending test approval queue; tests sort ahead of restored edits"
                in attention_preview_output,
            )
            print(
                "switcher_row_attention_reason=",
                "attention: restored test queue" in attention_text
                and "attention: restored edit queue" in attention_text
                and "attention: restored denied edit" in attention_text,
            )
            await pilot.press("a")
            await pilot.pause()
            all_attention_output = str(first_app.query_one("#output").render())
            print(
                "switcher_failure_badges=",
                "failures: test 1" in all_attention_output and "failures: tool 1" in all_attention_output,
            )
            print(
                "switcher_failure_attention_order=",
                all_attention_output.index("session-newer | 1 turn(s)")
                < all_attention_output.index("session-pending-edit | 1 turn(s)")
                < all_attention_output.index("session-denied | 1 turn(s)")
                < all_attention_output.index("session-failed-test | 1 turn(s)")
                < all_attention_output.index("session-failed-tool | 1 turn(s)"),
            )
            print(
                "switcher_compact_attention_hints=",
                "attention: test fail" in all_attention_output
                and "attention: tool fail" in all_attention_output
                and "attention: restore" in all_attention_output,
            )
            print(
                "switcher_pending_attention_hints=",
                "attention: pending test" in all_attention_output
                and "attention: pending edit" in all_attention_output
                and "pending tools: test 1" in all_attention_output
                and "pending tools: edit 1" in all_attention_output,
            )
            print(
                "switcher_suppressed_generic_attention_hints=",
                not any(
                    "attention: shell |" in line
                    or line.endswith("attention: shell")
                    or "attention: tool |" in line
                    or line.endswith("attention: tool")
                    for line in all_attention_output.splitlines()
                ),
            )
            await pilot.press("t")
            await pilot.pause()
            tool_output = str(first_app.query_one("#output").render())
            print("switcher_tool_filter=", "Filter: tool | Sort: attention" in tool_output)
            print(
                "switcher_tool_filter_only_tool=",
                "session-tool | 1 turn(s)" in tool_output
                and "session-newer | 1 turn(s)" in tool_output
                and "session-restore | 1 turn(s)" not in tool_output,
            )
            await pilot.press("w")
            await pilot.pause()
            workspace_inspect_output = str(first_app.query_one("#output").render())
            print(
                "switcher_workspace_inspect_filter=",
                "Filter: workspace-inspect | Sort: attention" in workspace_inspect_output
            )
            print(
                "switcher_workspace_inspect_only_workspace=",
                "session-tool | 1 turn(s)" in workspace_inspect_output
                and "workspace lanes: inspect" in workspace_inspect_output
                and "session-inspect | 1 turn(s)" not in workspace_inspect_output,
            )
            await pilot.press("e")
            await pilot.pause()
            workspace_edit_output = str(first_app.query_one("#output").render())
            print(
                "switcher_workspace_edit_filter=",
                "Filter: workspace-edit | Sort: attention" in workspace_edit_output
            )
            print(
                "switcher_workspace_edit_only_workspace=",
                "session-pending-edit | 1 turn(s)" in workspace_edit_output
                and "session-restored-edit-pending | 1 turn(s)" in workspace_edit_output
                and "session-denied | 1 turn(s)" in workspace_edit_output
                and "workspace lanes: edit" in workspace_edit_output
                and "session-inspect | 1 turn(s)" not in workspace_edit_output,
            )
            await pilot.press("h")
            await pilot.pause()
            shell_attention_output = str(first_app.query_one("#output").render())
            print("switcher_shell_filter=", "Filter: shell | Sort: attention" in shell_attention_output)
            print(
                "switcher_shell_filter_only_shell=",
                "session-newer | 1 turn(s)" in shell_attention_output
                and "session-failed-test | 1 turn(s)" in shell_attention_output
                and "session-tool | 1 turn(s)" not in shell_attention_output
                and "session-denied | 1 turn(s)" not in shell_attention_output,
            )
            await pilot.press("i")
            await pilot.pause()
            shell_inspect_output = str(first_app.query_one("#output").render())
            print("switcher_shell_inspect_filter=", "Filter: shell-inspect | Sort: attention" in shell_inspect_output)
            print(
                "switcher_shell_inspect_only_inspect=",
                "session-newer | 1 turn(s)" in shell_inspect_output
                and "session-failed-test | 1 turn(s)" not in shell_inspect_output
                and "session-restored-pending | 1 turn(s)" not in shell_inspect_output
                and "session-tool | 1 turn(s)" not in shell_inspect_output,
            )
            print(
                "switcher_shell_overlap_badge=",
                "session-newer | 1 turn(s)" in shell_inspect_output
                and "shell lanes: inspect, test" in shell_inspect_output,
            )
            await pilot.press("y")
            await pilot.pause()
            shell_test_output = str(first_app.query_one("#output").render())
            print("switcher_shell_test_filter=", "Filter: shell-test | Sort: attention" in shell_test_output)
            print(
                "switcher_shell_test_only_test=",
                "session-newer | 1 turn(s)" in shell_test_output
                and "session-aged | 1 turn(s)" in shell_test_output
                and "session-failed-test | 1 turn(s)" in shell_test_output
                and "session-restored-pending | 1 turn(s)" in shell_test_output
                and "session-tool | 1 turn(s)" not in shell_test_output,
            )
            await pilot.press("o")
            await pilot.pause()
            approval_stale_output = str(first_app.query_one("#output").render())
            print(
                "switcher_approval_stale_filter=",
                "Filter: approval-stale | Sort: attention" in approval_stale_output
                and "session-aged | 1 turn(s)" in approval_stale_output
                and "approval stale: pending 45d" in approval_stale_output
                and "session-newer | 1 turn(s)" not in approval_stale_output,
            )
            print(
                "switcher_approval_stale_backlog=",
                "Stale approval backlog: 1 session | lanes: pending 1 (oldest 45d)" in approval_stale_output,
            )
            print(
                "switcher_stale_cutoff_copy=",
                "Stale cutoff: approvals >= 7d old" in approval_stale_output,
            )
            print(
                "switcher_stale_lane_focus=",
                "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
                in approval_stale_output
                and "- stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 7d old"
                in approval_stale_output,
            )
            print(
                "switcher_stale_focus_rows=",
                "stale focus: pending" in approval_stale_output,
            )
            await pilot.press("up")
            await pilot.pause()

        restored_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-older",
            ),
            artifact_store=SessionArtifactStore(temp_dir, session_id="session-older"),
        )

        async with restored_app.run_test() as pilot:
            await pilot.pause()
            restored_output = restored_app.query_one("#output").render()
            selected_line = next(
                (line for line in str(restored_output).splitlines() if line.startswith("> ")),
                "",
            )
            print("switcher_restored=", "Session Switcher" in str(restored_output))
            print("switcher_restored_sort=", "Filter: approval-stale | Sort: attention" in str(restored_output))
            print("restored_selected_line=", selected_line)
            print("restored_selection_is_persisted=", "session-aged" in selected_line)
            print("restored_latest_event=", restored_app.events[-1].kind if restored_app.events else None)
            await pilot.press("enter")
            await pilot.pause()
            print("active_session=", restored_app.artifact_store.session_id)
            print("history_latest=", restored_app.history[-1] if restored_app.history else None)
            print("latest_event=", restored_app.events[-1].kind if restored_app.events else None)

        paged_current_store = SessionArtifactStore(temp_dir, session_id="session-page-current")
        append_turn(paged_current_store, "paged current prompt", "paged current response")
        for index in range(9):
            store = SessionArtifactStore(temp_dir, session_id=f"session-page-{index:02d}")
            append_turn(store, f"paged prompt {index}", f"paged response {index}")

        paged_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-page-current",
            ),
            artifact_store=paged_current_store,
        )

        async with paged_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("]")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            paged_output = str(paged_app.query_one("#output").render())
            stored_state = SessionArtifactStore(temp_dir, session_id="session-page-current").load_session_state()
            print("switcher_paged=", "Page: 2/3" in paged_output)
            print("switcher_paged_window=", "Showing: 9-16 of 20" in paged_output)
            print(
                "switcher_paged_state=",
                stored_state is not None
                and stored_state.session_switcher_page_index == 1
                and bool(stored_state.session_switcher_selected_session_id),
            )

        restored_paged_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=temp_dir,
                session_id="session-page-current",
            ),
            artifact_store=SessionArtifactStore(temp_dir, session_id="session-page-current"),
        )

        async with restored_paged_app.run_test() as pilot:
            await pilot.pause()
            restored_paged_output = str(restored_paged_app.query_one("#output").render())
            restored_paged_selected_line = next(
                (line for line in restored_paged_output.splitlines() if line.startswith("> ")),
                "",
            )
            restored_page_state = SessionArtifactStore(temp_dir, session_id="session-page-current").load_session_state()
            print("switcher_restored_page=", "Page: 2/3" in restored_paged_output)
            print(
                "switcher_restored_paged_selection=",
                restored_page_state is not None
                and restored_page_state.session_switcher_selected_session_id in restored_paged_selected_line,
            )

    with TemporaryDirectory() as stale_rollup_root:
        stale_current_store = SessionArtifactStore(stale_rollup_root, session_id="session-stale-current")
        append_turn(stale_current_store, "current stale rollup prompt", "current stale rollup response")
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

        stale_rollup_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=stale_rollup_root,
                session_id="session-stale-current",
            ),
            artifact_store=stale_current_store,
        )

        async with stale_rollup_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            stale_rollup_first_page = str(stale_rollup_app.query_one("#output").render())
            await pilot.press("]")
            await pilot.pause()
            stale_rollup_second_page = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_page_rollup=",
                "This page stale lanes: pending 8 (oldest 52d) | more off-page: denied 1 (oldest 14d), restore queue 1 (oldest 11d), restored 1 (oldest 10d)"
                in stale_rollup_first_page
                and "This page stale lanes: denied 1 (oldest 14d), restore queue 1 (oldest 11d), restored 1 (oldest 10d) | more off-page: pending 8 (oldest 52d)"
                in stale_rollup_second_page,
            )
            await pilot.press("q")
            await pilot.pause()
            stale_pending_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_pending_filter=",
                "Filter: approval-stale-pending | Sort: recent" in stale_pending_output
                and "Stale pending backlog: 8 sessions | lanes: pending 8 (oldest 52d)" in stale_pending_output
                and "Stale lane focus: pending | cutoff: approvals >= 7d old" in stale_pending_output
                and "| approval stale age: 45d | stale focus: pending" in stale_pending_output
                and "| approval stale: pending 45d | stale focus: pending" not in stale_pending_output
                and "- stale focus: pending" in stale_pending_output
                and "- approval stale age: 45d" in stale_pending_output
                and "- approval stale: pending 45d" not in stale_pending_output
                and "stale focus: pending" in stale_pending_output
                and "session-stale-pending-0" in stale_pending_output
                and "session-stale-denied-page-2" not in stale_pending_output,
            )
            await pilot.press("x")
            await pilot.pause()
            stale_denied_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_denied_filter=",
                "Filter: approval-stale-denied | Sort: recent" in stale_denied_output
                and "Stale denied backlog: 1 session | lanes: denied 1 (oldest 14d)" in stale_denied_output
                and "Stale lane focus: denied | cutoff: approvals >= 7d old" in stale_denied_output
                and "| approval stale age: 14d | stale focus: denied" in stale_denied_output
                and "| approval stale: denied 14d | stale focus: denied" not in stale_denied_output
                and "- stale focus: denied" in stale_denied_output
                and "- approval stale age: 14d" in stale_denied_output
                and "- approval stale: denied 14d" not in stale_denied_output
                and "stale focus: denied" in stale_denied_output
                and "session-stale-denied-page-2" in stale_denied_output
                and "session-stale-restored-page-2" not in stale_denied_output,
            )
            await pilot.press("u")
            await pilot.pause()
            stale_restored_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_restored_filter=",
                "Filter: approval-stale-restored | Sort: recent" in stale_restored_output
                and "Stale restored backlog: 1 session | lanes: restore queue 1 (oldest 11d), restored 1 (oldest 10d)" in stale_restored_output
                and "Stale lane focus: restore queue, restored | cutoff: approvals >= 7d old"
                in stale_restored_output
                and "| approval stale ages: restore queue 11d; restored 10d | stale focus: restore queue, restored"
                in stale_restored_output
                and "restored current: pending write_file via fake_runtime; queued 1" in stale_restored_output
                and "restored outcome: approved run_shell_command via fake_runtime; resumed; remaining 0"
                in stale_restored_output
                and "restored outcome age: 10d" in stale_restored_output
                and "| approval stale: restore queue 11d, restored 10d | stale focus: restore queue, restored" not in stale_restored_output
                and "- stale focus: restore queue, restored" in stale_restored_output
                and "- approval stale ages: restore queue 11d; restored 10d" in stale_restored_output
                and "- restored current approval: pending write_file via fake_runtime | queued 1"
                in stale_restored_output
                and "- latest restored outcome: approved run_shell_command via fake_runtime | resumed | remaining 0"
                in stale_restored_output
                and "- latest restored outcome age: 10d" in stale_restored_output
                and "- approval stale: restore queue 11d, restored 10d" not in stale_restored_output
                and "stale focus: restore queue" in stale_restored_output
                and "session-stale-restored-page-2" in stale_restored_output
                and "session-stale-denied-page-2" not in stale_restored_output,
            )

    with TemporaryDirectory() as custom_stale_root:
        custom_current_store = SessionArtifactStore(custom_stale_root, session_id="session-custom-current")
        append_turn(custom_current_store, "current prompt", "current response")

        custom_store = SessionArtifactStore(custom_stale_root, session_id="session-custom-threshold")
        append_turn(custom_store, "resume moderately old pending queue", "ok")
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

        custom_stale_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=custom_stale_root,
                stale_approval_warning_days=1,
                session_id="session-custom-current",
            ),
            artifact_store=custom_current_store,
        )

        async with custom_stale_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            custom_stale_output = str(custom_stale_app.query_one("#output").render())
            print(
                "switcher_custom_stale_threshold=",
                "Stale approval backlog: 1 session | lanes: pending 1 (oldest 2d)" in custom_stale_output
                and "session-custom-threshold" in custom_stale_output,
            )
            print(
                "switcher_custom_stale_cutoff_copy=",
                "Stale cutoff: approvals >= 1d old" in custom_stale_output,
            )
            print(
                "switcher_custom_stale_lane_focus=",
                "Stale lane focus: pending, denied, restore queue, restored | cutoff: approvals >= 1d old"
                in custom_stale_output,
            )

    with TemporaryDirectory() as empty_hint_root:
        empty_current_store = SessionArtifactStore(empty_hint_root, session_id="session-empty-current")
        append_turn(empty_current_store, "plain current session", "plain current response")

        empty_hint_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=empty_hint_root,
                session_id="session-empty-current",
            ),
            artifact_store=empty_current_store,
        )

        async with empty_hint_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            empty_hint_output = str(empty_hint_app.query_one("#output").render())
            print(
                "switcher_empty_hint=",
                "No saved sessions match the active switcher filter." in empty_hint_output
                and "1 saved session still exists under this root." in empty_hint_output
                and "Use N to start a fresh session, or Esc/F11 to return to the active session until a visible match exists." in empty_hint_output,
            )

    with TemporaryDirectory() as mixed_pending_root:
        mixed_current_store = SessionArtifactStore(mixed_pending_root, session_id="session-current")
        append_turn(mixed_current_store, "current prompt", "current response")

        mixed_pending_store = SessionArtifactStore(mixed_pending_root, session_id="session-pending-mixed")
        append_turn(mixed_pending_store, "queue mixed approvals", "mixed pending response")
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

        mixed_pending_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=mixed_pending_root,
                session_id="session-current",
            ),
            artifact_store=mixed_current_store,
        )

        async with mixed_pending_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            mixed_pending_output = str(mixed_pending_app.query_one("#output").render())
            print(
                "switcher_pending_queue_breakdown=",
                "pending: 3 approvals (first test; rest edit 1, tool 1)" in mixed_pending_output
                and "- pending queue: first test; rest edit 1, tool 1" in mixed_pending_output,
            )

    with TemporaryDirectory() as mixed_restored_root:
        mixed_current_store = SessionArtifactStore(mixed_restored_root, session_id="session-current")
        append_turn(mixed_current_store, "current prompt", "current response")

        mixed_restored_store = SessionArtifactStore(mixed_restored_root, session_id="session-restored-mixed")
        append_turn(mixed_restored_store, "resume mixed restored approvals", "restored mixed response")
        mixed_restored_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-restored-1",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="rerun restored tests",
                    restored_from_session=True,
                ),
                ApprovalRequest(
                    request_id="approval-restored-2",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="resume restored edit",
                    restored_from_session=True,
                ),
                ApprovalRequest(
                    request_id="approval-restored-3",
                    tool_name="list_files",
                    reason="Needs confirmation",
                    args={"relative_path": "."},
                    source="fake_runtime",
                    prompt="resume restored inspection",
                    restored_from_session=True,
                ),
            ]
        )

        mixed_restored_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=mixed_restored_root,
                session_id="session-current",
            ),
            artifact_store=mixed_current_store,
        )

        async with mixed_restored_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()
            mixed_restored_output = str(mixed_restored_app.query_one("#output").render())
            print(
                "switcher_restored_pending_queue_breakdown=",
                "approval restore queue: first test; rest edit 1, tool 1" in mixed_restored_output
                and "- approval restore queue: first test; rest edit 1, tool 1" in mixed_restored_output,
            )

        with TemporaryDirectory() as mixed_restore_overlap_root:
            mixed_current_store = SessionArtifactStore(mixed_restore_overlap_root, session_id="session-current")
            append_turn(mixed_current_store, "current prompt", "current response")

            mixed_overlap_store = SessionArtifactStore(
                mixed_restore_overlap_root,
                session_id="session-restored-overlap",
            )
            denied_event = runtime_event(
                "steering_denied",
                "replace_text",
                "Denied in the TUI",
                data={
                    "tool_name": "replace_text",
                    "approval_id": "approval-overlap-1",
                    "approval_status": "denied",
                    "approval_source": "fake_runtime",
                    "approval_restored": True,
                    "remaining_pending_count": 0,
                },
            )
            denied_event.timestamp = (datetime.now(UTC) - timedelta(hours=6, minutes=5)).isoformat()
            mixed_overlap_store.append_turn(
                TurnArtifact(
                    prompt="restore denied edit and pending test",
                    response="restored overlap response",
                    provider="fake-strands",
                    mode="fake",
                    events=[denied_event],
                    response_metadata={"mode": "fake"},
                )
            )
            mixed_overlap_store.save_pending_approvals(
                [
                    ApprovalRequest(
                        request_id="approval-overlap-2",
                        tool_name="run_shell_command",
                        reason="Needs confirmation",
                        args={"command": "pytest -q"},
                        source="fake_runtime",
                        prompt="rerun restored tests",
                        restored_from_session=True,
                        created_at=(datetime.now(UTC) - timedelta(days=3, hours=2)).isoformat(),
                    )
                ]
            )

            mixed_overlap_app = StrandsAgentApp(
                runtime=FakeStrandsRuntime(),
                config=AppConfig(
                    runtime_mode="fake",
                    openai_model="gpt-4o-mini",
                    workspace_root=".",
                    artifacts_root=mixed_restore_overlap_root,
                    session_id="session-current",
                ),
                artifact_store=mixed_current_store,
            )

            async with mixed_overlap_app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("f11")
                await pilot.pause()
                await pilot.press("v")
                await pilot.pause()
                mixed_overlap_output = str(mixed_overlap_app.query_one("#output").render())
                print(
                    "switcher_approval_restore_overlap_summary=",
                    "Approval restore backlog: 1 session | lanes: restore queue 1 (oldest 3d), restored 1 (oldest 6h) | overlap: mixed 1 session"
                    in mixed_overlap_output
                    and "Restore lane focus: restore queue, restored" in mixed_overlap_output,
                )
                print(
                    "switcher_approval_restore_overlap_preview_split=",
                    "restored current: pending run_shell_command via fake_runtime; queued 1"
                    in mixed_overlap_output
                    and "restored outcome: denied replace_text via fake_runtime; restored queue; remaining 0"
                    in mixed_overlap_output
                    and "- restored current approval: pending run_shell_command via fake_runtime | queued 1"
                    in mixed_overlap_output
                    and "- latest restored outcome: denied replace_text via fake_runtime | restored queue | remaining 0"
                    in mixed_overlap_output
                    and "- latest restored outcome age: 6h" in mixed_overlap_output,
                )


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
