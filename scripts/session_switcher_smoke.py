from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import ApprovalRequest, FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore, SessionState
from strands_agent_tui.testing import (
    matches_approval_restore_age_output,
    matches_approval_restore_badges_output,
    matches_approval_restore_focus_output,
    matches_approval_restore_overlap_output,
    matches_approval_restore_overlap_preview_split_output,
    matches_approval_restore_page_rollup_output,
    matches_approval_restore_preview_split_output,
    matches_approval_restore_tool_badges_output,
    matches_broad_approval_stale_output,
    matches_broad_stale_row_focus_suppression,
    matches_compact_stale_preview_output,
    matches_custom_stale_cutoff_output,
    matches_denied_filter_output,
    matches_denied_page_rollup_output,
    matches_denied_preview_output,
    matches_pending_age_output,
    matches_pending_filter_output,
    matches_pending_page_rollup_output,
    matches_queue_breakdown_output,
    matches_shell_filter_output,
    matches_stale_backlog_output,
    matches_stale_cutoff_output,
    matches_stale_denied_subfilter_output,
    matches_stale_lane_focus_output,
    matches_stale_page_rollup_output,
    matches_stale_pending_subfilter_output,
    matches_stale_restored_subfilter_output,
    matches_switcher_default_output,
    matches_switcher_selected_preview_output,
    matches_tool_filter_output,
    matches_workspace_filter_output,
    seed_approval_restore_overlap_session,
    seed_approval_restore_rollup_scenario,
    seed_approval_restore_focus_scenario,
    seed_denied_approval_rollup_scenario,
    seed_multi_approval_queue_session,
    seed_pending_approval_session,
    seed_pending_approval_rollup_scenario,
    seed_plain_session,
    seed_shell_failure_session,
    seed_shell_inspect_session,
    seed_shell_overlap_session,
    seed_shell_test_session,
    seed_stale_approval_rollup_scenario,
    seed_workspace_edit_session,
    seed_workspace_failure_session,
    seed_workspace_inspect_session,
    seed_workspace_overlap_session,
    set_session_artifact_mtime as _shared_set_session_artifact_mtime,
)


def set_session_artifact_mtime(store: SessionArtifactStore, when: datetime) -> None:
    _shared_set_session_artifact_mtime(store, when)


async def run_smoke() -> None:
    with TemporaryDirectory() as temp_dir:
        older_store = seed_plain_session(
            temp_dir,
            session_id="session-older",
            prompt="inspect older session",
            response="older response",
        )

        newer_store = seed_pending_approval_session(
            temp_dir,
            session_id="session-newer",
            prompt="inspect newer session",
            response="newer response",
            pending_request_id="approval-0004",
            pending_args={"command": "pytest"},
            pending_prompt="run pytest",
            approved_request_id="approval-0003",
            include_confirmation_event=False,
            extra_events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files", "result_preview": ".: README.md"},
                )
            ],
            session_state=SessionState(
                event_filter="tool",
                history_focus_index=0,
                draft_prompt="draft next step",
            ),
        )

        aged_turn_time = datetime.now(UTC) - timedelta(days=10)
        seed_shell_test_session(
            temp_dir,
            session_id="session-aged",
            prompt="resume stale queue",
            response="stale response",
            request_id="approval-aged-switcher",
            approval_prompt="resume old tests",
            created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
            turn_created_at=aged_turn_time.isoformat(),
        )
        aged_store = SessionArtifactStore(temp_dir, session_id="session-aged")
        set_session_artifact_mtime(aged_store, aged_turn_time)

        pending_edit_store = seed_workspace_edit_session(
            temp_dir,
            session_id="session-pending-edit",
            prompt="queue pending edit",
            response="queued edit response",
            request_id="approval-0004b",
            tool_name="write_file",
            args={"relative_path": "notes.txt", "overwrite": True},
            approval_prompt="queue edit",
        )

        seed_approval_restore_focus_scenario(temp_dir)

        seed_shell_failure_session(
            temp_dir,
            session_id="session-failed-test",
            prompt="run failing test",
        )

        seed_workspace_failure_session(
            temp_dir,
            session_id="session-failed-tool",
            prompt="attempt failing edit",
        )

        tool_store = seed_workspace_inspect_session(
            temp_dir,
            session_id="session-tool",
            prompt="list files",
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
            print("switcher_default_surface=", matches_switcher_default_output(str(switcher_output)))
            for _ in range(7):
                await pilot.press("down")
                await pilot.pause()
            selected_preview_output = first_app.query_one("#output").render()
            print(
                "switcher_selected_preview_surface=",
                matches_switcher_selected_preview_output(str(selected_preview_output)),
            )
            await pilot.press("p")
            await pilot.pause()
            pending_output = first_app.query_one("#output").render()
            pending_text = str(pending_output)
            print("switcher_pending_filter=", matches_pending_filter_output(pending_text))
            print(
                "switcher_pending_filter_only_newer=",
                matches_pending_filter_output(
                    pending_text,
                    required_session_ids=["session-newer", "session-aged", "session-pending-edit"],
                    excluded_session_ids=["session-older"],
                ),
            )
            print(
                "switcher_pending_age_and_stale_cues=",
                matches_pending_filter_output(pending_text, required_session_ids=["session-aged"])
                and matches_pending_age_output(pending_text),
            )
            await pilot.press("d")
            await pilot.pause()
            denied_output = first_app.query_one("#output").render()
            denied_text = str(denied_output)
            print("switcher_denied_filter=", matches_denied_filter_output(denied_text))
            print(
                "switcher_denied_filter_only_denied=",
                matches_denied_filter_output(
                    denied_text,
                    required_session_ids=["session-denied"],
                    excluded_session_ids=["session-newer"],
                ),
            )
            print(
                "switcher_denied_preview_origin=",
                matches_denied_preview_output(denied_text),
            )
            print(
                "switcher_denied_age=",
                matches_denied_preview_output(denied_text),
            )
            print("switcher_row_approval_focus=", "approval focus: denied/restored" in denied_text)
            print(
                "switcher_denied_badges=",
                matches_denied_preview_output(denied_text, required_badges=["denied: edit 1"]),
            )
            print(
                "switcher_restored_approval_badge=",
                matches_denied_preview_output(denied_text, require_restore_badge=True),
            )
            await pilot.press("v")
            await pilot.pause()
            approval_restore_output = first_app.query_one("#output").render()
            approval_restore_text = str(approval_restore_output)
            print("switcher_approval_restore_filter=", "Filter: approval-restore | Sort: recent" in approval_restore_text)
            print(
                "switcher_approval_restore_only_restored=",
                matches_approval_restore_focus_output(
                    approval_restore_text,
                    required_session_ids=[
                        "session-denied",
                        "session-restored-pending",
                        "session-restored-edit-pending",
                    ],
                    excluded_session_ids=["session-newer"],
                ),
            )
            print(
                "switcher_restored_approval_tool_badges=",
                matches_approval_restore_tool_badges_output(approval_restore_text),
            )
            print(
                "switcher_restored_approval_age=",
                matches_approval_restore_age_output(approval_restore_text),
            )
            print(
                "switcher_last_restored_approval_preview=",
                "last restored approval:" in approval_restore_text
                or "restored current approval:" in approval_restore_text,
            )
            print(
                "switcher_restored_approval_preview_split=",
                matches_approval_restore_preview_split_output(approval_restore_text),
            )
            print(
                "switcher_restore_preview_compact=",
                matches_approval_restore_age_output(approval_restore_text),
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
            print(
                "switcher_tool_filter=",
                matches_tool_filter_output(
                    tool_output,
                    sort_mode="attention",
                    required_session_ids=["session-tool", "session-newer"],
                    excluded_session_ids=["session-restore"],
                ),
            )
            await pilot.press("w")
            await pilot.pause()
            workspace_inspect_output = str(first_app.query_one("#output").render())
            print(
                "switcher_workspace_inspect_filter=",
                matches_workspace_filter_output(
                    workspace_inspect_output,
                    filter_mode="workspace-inspect",
                    sort_mode="attention",
                    backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
                    focus="inspect",
                )
            )
            print(
                "switcher_workspace_inspect_only_workspace=",
                matches_workspace_filter_output(
                    workspace_inspect_output,
                    filter_mode="workspace-inspect",
                    sort_mode="attention",
                    backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
                    focus="inspect",
                    required_session_ids=["session-tool", "session-newer"],
                    excluded_session_ids=["session-failed-tool"],
                    required=["workspace lanes: inspect"],
                ),
            )
            await pilot.press("e")
            await pilot.pause()
            for _ in range(8):
                await pilot.press("up")
                await pilot.pause()
            workspace_edit_output = str(first_app.query_one("#output").render())
            print(
                "switcher_workspace_edit_filter=",
                matches_workspace_filter_output(
                    workspace_edit_output,
                    filter_mode="workspace-edit",
                    sort_mode="attention",
                    backlog_line="Workspace backlog: 5 sessions | lanes: inspect 1, edit 5 (oldest 6h @",
                    focus="edit",
                    required=["| overlap: mixed 1 session"],
                )
            )
            print(
                "switcher_workspace_edit_only_workspace=",
                matches_workspace_filter_output(
                    workspace_edit_output,
                    filter_mode="workspace-edit",
                    sort_mode="attention",
                    backlog_line="Workspace backlog: 5 sessions | lanes: inspect 1, edit 5 (oldest 6h @",
                    focus="edit",
                    required_session_ids=[
                        "session-newer",
                        "session-pending-edit",
                        "session-restored-edit-pending",
                        "session-denied",
                    ],
                    excluded_session_ids=["session-tool"],
                    required=["workspace lanes: edit", "| overlap: mixed 1 session"],
                ),
            )
            print(
                "switcher_pending_only_preview_age_source=",
                "- workspace focus age source:" in workspace_edit_output,
            )
            await pilot.press("h")
            await pilot.pause()
            shell_attention_output = str(first_app.query_one("#output").render())
            print(
                "switcher_shell_filter=",
                matches_shell_filter_output(
                    shell_attention_output,
                    filter_mode="shell",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 4 sessions | lanes: inspect 1, test 4 (oldest 45d @",
                    focus="inspect, test",
                    required=["| overlap: mixed 1 session"],
                )
            )
            print(
                "switcher_shell_filter_only_shell=",
                matches_shell_filter_output(
                    shell_attention_output,
                    filter_mode="shell",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 4 sessions | lanes: inspect 1, test 4 (oldest 45d @",
                    focus="inspect, test",
                    required_session_ids=["session-newer", "session-aged", "session-failed-test", "session-restored-pending"],
                    excluded_session_ids=["session-tool"],
                    required=["shell: inspect 1", "| overlap: mixed 1 session"],
                ),
            )
            await pilot.press("i")
            await pilot.pause()
            shell_inspect_output = str(first_app.query_one("#output").render())
            print(
                "switcher_shell_inspect_filter=",
                matches_shell_filter_output(
                    shell_inspect_output,
                    filter_mode="shell-inspect",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 1 session | lanes: inspect 1, test 1 | overlap: mixed 1 session",
                    focus="inspect",
                )
            )
            print(
                "switcher_shell_inspect_only_inspect=",
                matches_shell_filter_output(
                    shell_inspect_output,
                    filter_mode="shell-inspect",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 1 session | lanes: inspect 1, test 1 | overlap: mixed 1 session",
                    focus="inspect",
                    required_session_ids=["session-newer"],
                    excluded_session_ids=[
                        "session-aged",
                        "session-failed-test",
                        "session-restored-pending",
                        "session-tool",
                    ],
                ),
            )
            print(
                "switcher_shell_overlap_badge=",
                "session-newer | 1 turn(s)" in shell_inspect_output
                and "shell lanes: inspect, test" in shell_inspect_output,
            )
            await pilot.press("y")
            await pilot.pause()
            for _ in range(8):
                await pilot.press("up")
                await pilot.pause()
            shell_test_output = str(first_app.query_one("#output").render())
            print(
                "switcher_shell_test_filter=",
                matches_shell_filter_output(
                    shell_test_output,
                    filter_mode="shell-test",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 4 sessions | lanes: inspect 1, test 4 (oldest 45d @",
                    focus="test",
                    required=["| overlap: mixed 1 session"],
                )
            )
            print(
                "switcher_shell_test_only_test=",
                matches_shell_filter_output(
                    shell_test_output,
                    filter_mode="shell-test",
                    sort_mode="attention",
                    backlog_line="Shell backlog: 4 sessions | lanes: inspect 1, test 4 (oldest 45d @",
                    focus="test",
                    required_session_ids=[
                        "session-newer",
                        "session-aged",
                        "session-failed-test",
                        "session-restored-pending",
                    ],
                    excluded_session_ids=["session-tool"],
                    required=["| overlap: mixed 1 session"],
                ),
            )
            print(
                "switcher_shell_test_preview_age_source=",
                "- shell focus age source:" in shell_test_output,
            )
            await pilot.press("o")
            await pilot.pause()
            approval_stale_output = str(first_app.query_one("#output").render())
            print(
                "switcher_approval_stale_filter=",
                matches_broad_approval_stale_output(
                    approval_stale_output,
                    required_session_ids=["session-aged"],
                    excluded_session_ids=["session-newer"],
                    sort_mode="attention",
                ),
            )
            print(
                "switcher_approval_stale_backlog=",
                matches_stale_backlog_output(approval_stale_output),
            )
            print(
                "switcher_stale_cutoff_copy=",
                matches_stale_cutoff_output(approval_stale_output),
            )
            print(
                "switcher_stale_lane_focus=",
                matches_stale_lane_focus_output(approval_stale_output),
            )
            print(
                "switcher_stale_preview_compact=",
                matches_compact_stale_preview_output(approval_stale_output),
            )
            print(
                "switcher_stale_focus_rows=",
                matches_broad_stale_row_focus_suppression(approval_stale_output),
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

        paged_current_store = seed_plain_session(
            temp_dir,
            session_id="session-page-current",
            prompt="paged current prompt",
            response="paged current response",
        )
        for index in range(9):
            seed_plain_session(
                temp_dir,
                session_id=f"session-page-{index:02d}",
                prompt=f"paged prompt {index}",
                response=f"paged response {index}",
            )

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

    with TemporaryDirectory() as pending_rollup_root:
        pending_rollup_current_store = seed_plain_session(
            pending_rollup_root,
            session_id="session-current",
            prompt="current pending rollup prompt",
            response="current pending rollup response",
        )

        pending_rollup_now = datetime.now(UTC)
        seed_pending_approval_rollup_scenario(pending_rollup_root, now=pending_rollup_now)

        pending_rollup_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=pending_rollup_root,
                session_id="session-current",
            ),
            artifact_store=pending_rollup_current_store,
        )

        async with pending_rollup_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            pending_rollup_first_page = str(pending_rollup_app.query_one("#output").render())
            await pilot.press("]")
            await pilot.pause()
            pending_rollup_second_page = str(pending_rollup_app.query_one("#output").render())
            print(
                "switcher_pending_page_rollup=",
                matches_pending_page_rollup_output(
                    pending_rollup_first_page,
                    pending_rollup_second_page,
                ),
            )

    with TemporaryDirectory() as denied_rollup_root:
        denied_rollup_current_store = seed_plain_session(
            denied_rollup_root,
            session_id="session-current",
            prompt="current denied rollup prompt",
            response="current denied rollup response",
        )

        denied_rollup_now = datetime.now(UTC)
        seed_denied_approval_rollup_scenario(denied_rollup_root, now=denied_rollup_now)

        denied_rollup_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=denied_rollup_root,
                session_id="session-current",
            ),
            artifact_store=denied_rollup_current_store,
        )

        async with denied_rollup_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            denied_rollup_first_page = str(denied_rollup_app.query_one("#output").render())
            await pilot.press("]")
            await pilot.pause()
            denied_rollup_second_page = str(denied_rollup_app.query_one("#output").render())
            print(
                "switcher_denied_page_rollup=",
                matches_denied_page_rollup_output(
                    denied_rollup_first_page,
                    denied_rollup_second_page,
                ),
            )

    with TemporaryDirectory() as stale_rollup_root:
        stale_current_store = seed_plain_session(
            stale_rollup_root,
            session_id="session-stale-current",
            prompt="current stale rollup prompt",
            response="current stale rollup response",
        )
        seed_stale_approval_rollup_scenario(stale_rollup_root, include_restored_outcome=True)

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
                matches_stale_page_rollup_output(
                    stale_rollup_first_page,
                    stale_rollup_second_page,
                ),
            )
            await pilot.press("q")
            await pilot.pause()
            stale_pending_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_pending_filter=",
                matches_stale_pending_subfilter_output(
                    stale_pending_output,
                    required_session_ids=["session-stale-pending-0"],
                    excluded_session_ids=["session-stale-denied-page-2"],
                ),
            )
            await pilot.press("x")
            await pilot.pause()
            stale_denied_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_denied_filter=",
                matches_stale_denied_subfilter_output(
                    stale_denied_output,
                    required_session_ids=["session-stale-denied-page-2"],
                    excluded_session_ids=["session-stale-restored-page-2"],
                ),
            )
            await pilot.press("u")
            await pilot.pause()
            stale_restored_output = str(stale_rollup_app.query_one("#output").render())
            print(
                "switcher_approval_stale_restored_filter=",
                matches_stale_restored_subfilter_output(
                    stale_restored_output,
                    required_session_ids=["session-stale-restored-page-2"],
                    excluded_session_ids=["session-stale-denied-page-2"],
                ),
            )

    with TemporaryDirectory() as custom_stale_root:
        custom_current_store = seed_plain_session(
            custom_stale_root,
            session_id="session-custom-current",
            prompt="current prompt",
            response="current response",
        )

        seed_pending_approval_session(
            custom_stale_root,
            session_id="session-custom-threshold",
            prompt="resume moderately old pending queue",
            pending_request_id="approval-custom-threshold",
            pending_created_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
            approved_request_id=None,
            include_confirmation_event=False,
            shell_command=None,
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
                matches_custom_stale_cutoff_output(custom_stale_output),
            )
            print(
                "switcher_custom_stale_cutoff_copy=",
                matches_stale_cutoff_output(custom_stale_output, days=1),
            )
            print(
                "switcher_custom_stale_lane_focus=",
                matches_stale_lane_focus_output(custom_stale_output, days=1),
            )

    with TemporaryDirectory() as empty_hint_root:
        empty_current_store = seed_plain_session(
            empty_hint_root,
            session_id="session-empty-current",
            prompt="plain current session",
            response="plain current response",
        )

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
        mixed_current_store = seed_plain_session(
            mixed_pending_root,
            session_id="session-current",
            prompt="current prompt",
            response="current response",
        )

        seed_multi_approval_queue_session(
            mixed_pending_root,
            session_id="session-pending-mixed",
            prompt="queue mixed approvals",
            response="mixed pending response",
            request_id_prefix="approval-mixed",
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
                matches_queue_breakdown_output(
                    mixed_pending_output,
                    summary_line="pending: 3 approvals (first test; rest edit 1, tool 1)",
                    preview_line="- pending queue: first test; rest edit 1, tool 1",
                ),
            )

    with TemporaryDirectory() as mixed_restored_root:
        mixed_current_store = seed_plain_session(
            mixed_restored_root,
            session_id="session-current",
            prompt="current prompt",
            response="current response",
        )

        seed_multi_approval_queue_session(
            mixed_restored_root,
            session_id="session-restored-mixed",
            prompt="resume mixed restored approvals",
            response="restored mixed response",
            restored_from_session=True,
            request_id_prefix="approval-restored",
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
                matches_queue_breakdown_output(
                    mixed_restored_output,
                    summary_line="approval restore queue: first test; rest edit 1, tool 1",
                    preview_line="- approval restore queue: first test; rest edit 1, tool 1",
                ),
            )

        with TemporaryDirectory() as mixed_restore_overlap_root:
            mixed_current_store = seed_plain_session(
                mixed_restore_overlap_root,
                session_id="session-current",
                prompt="current prompt",
                response="current response",
            )

            seed_approval_restore_overlap_session(
                mixed_restore_overlap_root,
                session_id="session-restored-overlap",
                response="restored overlap response",
                pending_request_id="approval-overlap-2",
                outcome_request_id="approval-overlap-1",
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
                    matches_approval_restore_overlap_output(mixed_overlap_output),
                )
                print(
                    "switcher_approval_restore_overlap_preview_split=",
                    matches_approval_restore_overlap_preview_split_output(mixed_overlap_output),
                )

        with TemporaryDirectory() as approval_restore_rollup_root:
            rollup_current_store = seed_plain_session(
                approval_restore_rollup_root,
                session_id="session-current",
                prompt="current prompt",
                response="current response",
            )

            approval_restore_now = datetime.now(UTC)
            seed_approval_restore_rollup_scenario(approval_restore_rollup_root, now=approval_restore_now)

            approval_restore_rollup_app = StrandsAgentApp(
                runtime=FakeStrandsRuntime(),
                config=AppConfig(
                    runtime_mode="fake",
                    openai_model="gpt-4o-mini",
                    workspace_root=".",
                    artifacts_root=approval_restore_rollup_root,
                    session_id="session-current",
                ),
                artifact_store=rollup_current_store,
            )

            async with approval_restore_rollup_app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("f11")
                await pilot.pause()
                await pilot.press("v")
                await pilot.pause()
                approval_restore_rollup_first_page = str(approval_restore_rollup_app.query_one("#output").render())
                await pilot.press("]")
                await pilot.pause()
                approval_restore_rollup_second_page = str(approval_restore_rollup_app.query_one("#output").render())
                print(
                    "switcher_approval_restore_page_rollup=",
                    matches_approval_restore_page_rollup_output(
                        approval_restore_rollup_first_page,
                        approval_restore_rollup_second_page,
                    ),
                )

    with TemporaryDirectory() as workspace_shell_overlap_root:
        overlap_current_store = seed_plain_session(
            workspace_shell_overlap_root,
            session_id="session-current",
            prompt="current prompt",
            response="current response",
        )

        seed_workspace_inspect_session(workspace_shell_overlap_root)
        seed_workspace_overlap_session(workspace_shell_overlap_root)
        seed_workspace_edit_session(workspace_shell_overlap_root)
        seed_shell_inspect_session(workspace_shell_overlap_root)
        seed_shell_overlap_session(workspace_shell_overlap_root)
        seed_shell_test_session(workspace_shell_overlap_root)

        overlap_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=workspace_shell_overlap_root,
                session_id="session-current",
            ),
            artifact_store=overlap_current_store,
        )

        async with overlap_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            workspace_inspect_output = str(overlap_app.query_one("#output").render())
            await pilot.press("e")
            await pilot.pause()
            workspace_edit_output = str(overlap_app.query_one("#output").render())
            await pilot.press("h")
            await pilot.pause()
            shell_output = str(overlap_app.query_one("#output").render())
            await pilot.press("i")
            await pilot.pause()
            shell_inspect_output = str(overlap_app.query_one("#output").render())
            await pilot.press("y")
            await pilot.pause()
            shell_test_output = str(overlap_app.query_one("#output").render())
            print(
                "switcher_workspace_overlap_summary=",
                matches_workspace_filter_output(
                    workspace_inspect_output,
                    filter_mode="workspace-inspect",
                    sort_mode="recent",
                    backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
                    focus="inspect",
                    required=["workspace lanes: inspect, edit"],
                )
                and matches_workspace_filter_output(
                    workspace_edit_output,
                    filter_mode="workspace-edit",
                    sort_mode="recent",
                    backlog_line="Workspace backlog: 2 sessions | lanes: inspect 1, edit 2 | overlap: mixed 1 session",
                    focus="edit",
                ),
            )
            print(
                "switcher_shell_overlap_summary=",
                matches_shell_filter_output(
                    shell_output,
                    filter_mode="shell",
                    sort_mode="recent",
                    backlog_line="Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session",
                    focus="inspect, test",
                )
                and matches_shell_filter_output(
                    shell_inspect_output,
                    filter_mode="shell-inspect",
                    sort_mode="recent",
                    backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
                    focus="inspect",
                    required=["shell lanes: inspect, test"],
                )
                and matches_shell_filter_output(
                    shell_test_output,
                    filter_mode="shell-test",
                    sort_mode="recent",
                    backlog_line="Shell backlog: 2 sessions | lanes: inspect 1, test 2 | overlap: mixed 1 session",
                    focus="test",
                ),
            )

    with TemporaryDirectory() as queue_provenance_root:
        current_store = seed_plain_session(
            queue_provenance_root,
            session_id="session-current",
            prompt="current session",
            response="current response",
        )
        queue_now = datetime.now(UTC)
        queue_workspace_fresh_store = seed_workspace_edit_session(
            queue_provenance_root,
            session_id="session-edit-fresh",
            created_at=(queue_now - timedelta(days=2)).isoformat(),
        )
        queue_workspace_restored_store = seed_workspace_edit_session(
            queue_provenance_root,
            session_id="session-edit-restored",
            restored_from_session=True,
            created_at=(queue_now - timedelta(days=6)).isoformat(),
        )
        queue_shell_fresh_store = seed_shell_test_session(
            queue_provenance_root,
            session_id="session-test-fresh",
            created_at=(queue_now - timedelta(days=3)).isoformat(),
        )
        queue_shell_restored_store = seed_shell_test_session(
            queue_provenance_root,
            session_id="session-test-restored",
            restored_from_session=True,
            created_at=(queue_now - timedelta(days=7)).isoformat(),
        )
        set_session_artifact_mtime(queue_workspace_fresh_store, queue_now - timedelta(days=2))
        set_session_artifact_mtime(queue_workspace_restored_store, queue_now - timedelta(days=6))
        set_session_artifact_mtime(queue_shell_fresh_store, queue_now - timedelta(days=3))
        set_session_artifact_mtime(queue_shell_restored_store, queue_now - timedelta(days=7))

        provenance_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=queue_provenance_root,
                session_id="session-current",
            ),
            artifact_store=current_store,
        )

        async with provenance_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            workspace_fresh_output = str(provenance_app.query_one("#output").render())
            await pilot.press("down")
            await pilot.pause()
            workspace_alt_output = str(provenance_app.query_one("#output").render())
            await pilot.press("y")
            await pilot.pause()
            shell_fresh_output = str(provenance_app.query_one("#output").render())
            await pilot.press("down")
            await pilot.pause()
            shell_alt_output = str(provenance_app.query_one("#output").render())
            print(
                "switcher_pending_only_preview_queue_provenance=",
                any(
                    "- workspace focus queue provenance: fresh approval queue" in output
                    for output in [workspace_fresh_output, workspace_alt_output]
                )
                and any(
                    "- workspace focus queue provenance: restored approval queue" in output
                    for output in [workspace_fresh_output, workspace_alt_output]
                )
                and any(
                    "- shell focus queue provenance: fresh approval queue" in output
                    for output in [shell_fresh_output, shell_alt_output]
                )
                and any(
                    "- shell focus queue provenance: restored approval queue" in output
                    for output in [shell_fresh_output, shell_alt_output]
                ),
            )

    with TemporaryDirectory() as queue_breakdown_root:
        current_store = seed_plain_session(
            queue_breakdown_root,
            session_id="session-current",
            prompt="current session",
            response="current response",
        )
        queue_breakdown_now = datetime.now(UTC)

        workspace_multi_store = seed_plain_session(
            queue_breakdown_root,
            session_id="session-edit-multi",
            prompt="queue multiple edits",
            response="queued",
        )
        workspace_multi_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-workspace-fresh",
                    tool_name="write_file",
                    reason="Needs confirmation",
                    args={"relative_path": "notes.txt", "overwrite": True},
                    source="fake_runtime",
                    prompt="queue write",
                    created_at=(queue_breakdown_now - timedelta(days=2)).isoformat(),
                ),
                ApprovalRequest(
                    request_id="approval-workspace-restored",
                    tool_name="replace_text",
                    reason="Needs confirmation",
                    args={"relative_path": "src/app.py", "expected_occurrences": 2},
                    source="fake_runtime",
                    prompt="queue replace",
                    restored_from_session=True,
                    created_at=(queue_breakdown_now - timedelta(days=6)).isoformat(),
                ),
            ]
        )
        set_session_artifact_mtime(workspace_multi_store, queue_breakdown_now - timedelta(minutes=2))

        shell_multi_store = seed_plain_session(
            queue_breakdown_root,
            session_id="session-test-multi",
            prompt="queue multiple tests",
            response="queued",
        )
        shell_multi_store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id="approval-shell-fresh",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt="run pytest",
                    created_at=(queue_breakdown_now - timedelta(days=3)).isoformat(),
                ),
                ApprovalRequest(
                    request_id="approval-shell-restored",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "python -m pytest -q"},
                    source="fake_runtime",
                    prompt="rerun restored tests",
                    restored_from_session=True,
                    created_at=(queue_breakdown_now - timedelta(days=7)).isoformat(),
                ),
            ]
        )
        set_session_artifact_mtime(shell_multi_store, queue_breakdown_now - timedelta(minutes=1))

        queue_breakdown_app = StrandsAgentApp(
            runtime=FakeStrandsRuntime(),
            config=AppConfig(
                runtime_mode="fake",
                openai_model="gpt-4o-mini",
                workspace_root=".",
                artifacts_root=queue_breakdown_root,
                session_id="session-current",
            ),
            artifact_store=current_store,
        )

        async with queue_breakdown_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            workspace_breakdown_output = str(queue_breakdown_app.query_one("#output").render())
            await pilot.press("y")
            await pilot.pause()
            shell_breakdown_output = str(queue_breakdown_app.query_one("#output").render())
            print(
                "switcher_pending_only_preview_queue_breakdown=",
                "- workspace focus queue (2):" in workspace_breakdown_output
                and "1. fresh write_file | path notes.txt" in workspace_breakdown_output
                and "2. restored replace_text | path src/app.py" in workspace_breakdown_output
                and "- shell focus queue (2):" in shell_breakdown_output
                and "1. fresh run_shell_command | cmd pytest -q" in shell_breakdown_output
                and "2. restored run_shell_command | cmd python -m pytest -q" in shell_breakdown_output,
            )


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
