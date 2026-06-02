from __future__ import annotations

from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from strands_agent_tui.runtime import ApprovalRequest
from strands_agent_tui.sessions import (
    SessionArtifactStore,
    latest_session,
    pick_session,
    render_session_picker,
)
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
    matches_intervention_filter_output,
    matches_pending_age_output,
    matches_pending_filter_output,
    matches_pending_page_rollup_output,
    matches_picker_default_output,
    matches_queue_breakdown_output,
    matches_shell_filter_output,
    matches_stale_backlog_output,
    matches_stale_cutoff_output,
    matches_stale_denied_subfilter_output,
    matches_stale_lane_focus_output,
    matches_stale_page_rollup_output,
    matches_stale_pending_subfilter_output,
    matches_stale_restored_subfilter_output,
    matches_tool_filter_output,
    matches_workspace_filter_output,
    seed_approval_restore_overlap_session,
    seed_approval_restore_rollup_scenario,
    seed_approval_restore_focus_scenario,
    seed_denied_approval_session,
    seed_denied_approval_rollup_scenario,
    seed_multi_approval_queue_session,
    seed_pending_approval_session,
    seed_pending_approval_rollup_scenario,
    seed_plain_session,
    seed_restore_state_session,
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


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        seed_plain_session(temp_dir)

        seed_pending_approval_session(temp_dir)

        pending_edit_store = seed_workspace_edit_session(
            temp_dir,
            session_id="session-pending-edit",
            prompt="queue the risky edit",
            request_id="approval-0001b",
            tool_name="write_file",
            args={"relative_path": "notes.txt", "overwrite": True},
            approval_prompt="queue edit",
        )

        seed_denied_approval_session(
            temp_dir,
            session_id="session-denied-test",
            prompt="deny the risky test approval",
        )

        seed_approval_restore_focus_scenario(temp_dir)

        seed_restore_state_session(
            temp_dir,
            session_id="session-restore",
            prompt="resume the saved triage flow",
            response="ok",
            draft_prompt="queued follow-up",
        )

        aged_turn_time = datetime.now(UTC) - timedelta(days=10)
        seed_shell_test_session(
            temp_dir,
            session_id="session-aged",
            prompt="resume the stale test queue",
            response="ok",
            request_id="approval-aged",
            approval_prompt="resume old tests",
            created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
            turn_created_at=aged_turn_time.isoformat(),
        )
        aged_store = SessionArtifactStore(temp_dir, session_id="session-aged")
        set_session_artifact_mtime(aged_store, aged_turn_time)

        seed_shell_failure_session(
            temp_dir,
            session_id="session-failed-test",
            prompt="run the failing test suite",
            response="ok",
        )

        seed_workspace_failure_session(
            temp_dir,
            session_id="session-failed-tool",
            prompt="attempt the failing edit",
            response="ok",
        )

        tool_store = seed_workspace_inspect_session(
            temp_dir,
            session_id="session-tool",
            prompt="list files",
            response="ok",
        )

        inspect_store = seed_shell_inspect_session(
            temp_dir,
            session_id="session-inspect",
            prompt="inspect repo",
            response="ok",
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
        tool_picker = render_session_picker(temp_dir, filter_mode="tool")
        workspace_inspect_picker = render_session_picker(temp_dir, filter_mode="workspace-inspect")
        workspace_inspect_attention_picker = render_session_picker(
            temp_dir,
            filter_mode="workspace-inspect",
            sort_mode="attention",
        )
        workspace_edit_picker = render_session_picker(temp_dir, filter_mode="workspace-edit")
        workspace_edit_pending_preview_picker = render_session_picker(
            temp_dir,
            filter_mode="workspace-edit",
            selected_index=2,
        )
        workspace_edit_attention_picker = render_session_picker(
            temp_dir,
            filter_mode="workspace-edit",
            sort_mode="attention",
        )
        shell_picker = render_session_picker(temp_dir, filter_mode="shell")
        shell_attention_picker = render_session_picker(temp_dir, filter_mode="shell", sort_mode="attention")
        intervention_picker = render_session_picker(temp_dir, filter_mode="intervention")
        shell_inspect_picker = render_session_picker(temp_dir, filter_mode="shell-inspect")
        shell_inspect_attention_picker = render_session_picker(
            temp_dir,
            filter_mode="shell-inspect",
            sort_mode="attention",
        )
        shell_test_picker = render_session_picker(temp_dir, filter_mode="shell-test")
        shell_test_pending_preview_picker = render_session_picker(
            temp_dir,
            filter_mode="shell-test",
            selected_index=1,
        )
        shell_test_attention_picker = render_session_picker(
            temp_dir,
            filter_mode="shell-test",
            sort_mode="attention",
        )
        attention_picker = render_session_picker(temp_dir, sort_mode="attention")
        attention_page_two_picker = render_session_picker(temp_dir, sort_mode="attention", page_index=1)
        approval_restore_attention_picker = render_session_picker(temp_dir, filter_mode="approval-restore", sort_mode="attention")

        with TemporaryDirectory() as empty_hint_root:
            seed_plain_session(
                empty_hint_root,
                session_id="session-empty",
                prompt="plain session for empty-filter hint",
            )
            empty_pending_picker = render_session_picker(empty_hint_root, filter_mode="pending")

        with TemporaryDirectory() as mixed_pending_root:
            seed_multi_approval_queue_session(
                mixed_pending_root,
                session_id="session-pending-mixed",
                prompt="queue mixed approvals",
                request_id_prefix="approval-mixed",
            )
            mixed_pending_picker = render_session_picker(mixed_pending_root, filter_mode="pending")

        with TemporaryDirectory() as queue_provenance_root:
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

            queue_workspace_fresh_picker = render_session_picker(
                queue_provenance_root,
                filter_mode="workspace-edit",
            )
            queue_workspace_alt_picker = render_session_picker(
                queue_provenance_root,
                filter_mode="workspace-edit",
                selected_index=1,
            )
            queue_shell_fresh_picker = render_session_picker(
                queue_provenance_root,
                filter_mode="shell-test",
            )
            queue_shell_alt_picker = render_session_picker(
                queue_provenance_root,
                filter_mode="shell-test",
                selected_index=1,
            )

        with TemporaryDirectory() as queue_breakdown_root:
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

            queue_breakdown_workspace_picker = render_session_picker(
                queue_breakdown_root,
                filter_mode="workspace-edit",
            )
            queue_breakdown_shell_picker = render_session_picker(
                queue_breakdown_root,
                filter_mode="shell-test",
            )

        with TemporaryDirectory() as pending_rollup_root:
            pending_rollup_now = datetime.now(UTC)
            seed_pending_approval_rollup_scenario(pending_rollup_root, now=pending_rollup_now)

            pending_rollup_picker = render_session_picker(pending_rollup_root, filter_mode="pending")
            pending_rollup_page_two_picker = render_session_picker(
                pending_rollup_root,
                filter_mode="pending",
                page_index=1,
            )

        with TemporaryDirectory() as mixed_restored_root:
            seed_multi_approval_queue_session(
                mixed_restored_root,
                session_id="session-restored-mixed",
                prompt="resume mixed restored approvals",
                restored_from_session=True,
                request_id_prefix="approval-0020",
            )
            mixed_restored_picker = render_session_picker(mixed_restored_root, filter_mode="approval-restore")

        with TemporaryDirectory() as mixed_restored_split_root:
            seed_approval_restore_overlap_session(
                mixed_restored_split_root,
                session_id="session-restored-overlap",
                pending_request_id="approval-overlap-2",
                outcome_request_id="approval-overlap-1",
            )
            mixed_restored_split_picker = render_session_picker(
                mixed_restored_split_root,
                filter_mode="approval-restore",
            )

        with TemporaryDirectory() as approval_restore_rollup_root:
            approval_restore_now = datetime.now(UTC)
            seed_approval_restore_rollup_scenario(approval_restore_rollup_root, now=approval_restore_now)

            approval_restore_rollup_picker = render_session_picker(
                approval_restore_rollup_root,
                filter_mode="approval-restore",
            )
            approval_restore_rollup_page_two_picker = render_session_picker(
                approval_restore_rollup_root,
                filter_mode="approval-restore",
                page_index=1,
            )

        with TemporaryDirectory() as workspace_overlap_root:
            seed_workspace_inspect_session(workspace_overlap_root)
            seed_workspace_overlap_session(workspace_overlap_root)
            seed_workspace_edit_session(workspace_overlap_root)
            workspace_overlap_inspect_picker = render_session_picker(
                workspace_overlap_root,
                filter_mode="workspace-inspect",
            )
            workspace_overlap_edit_picker = render_session_picker(
                workspace_overlap_root,
                filter_mode="workspace-edit",
            )

        with TemporaryDirectory() as shell_overlap_root:
            seed_shell_inspect_session(shell_overlap_root)
            seed_shell_overlap_session(shell_overlap_root)
            seed_shell_test_session(shell_overlap_root)
            shell_overlap_picker = render_session_picker(shell_overlap_root, filter_mode="shell")
            shell_overlap_inspect_picker = render_session_picker(
                shell_overlap_root,
                filter_mode="shell-inspect",
            )
            shell_overlap_test_picker = render_session_picker(
                shell_overlap_root,
                filter_mode="shell-test",
            )

        with TemporaryDirectory() as denied_rollup_root:
            denied_rollup_now = datetime.now(UTC)
            seed_denied_approval_rollup_scenario(denied_rollup_root, now=denied_rollup_now)

            denied_rollup_picker = render_session_picker(denied_rollup_root, filter_mode="denied")
            denied_rollup_page_two_picker = render_session_picker(
                denied_rollup_root,
                filter_mode="denied",
                page_index=1,
            )

        for index in range(8):
            seed_plain_session(temp_dir, session_id=f"session-page-{index}", prompt=f"page prompt {index}")

        paged_picker = render_session_picker(temp_dir, page_index=1)

        print("picker_default_surface=", matches_picker_default_output(default_picker))
        print("picker_pending_filter=", matches_pending_filter_output(pending_picker))
        print(
            "picker_pending_only_pending=",
            matches_pending_filter_output(
                pending_picker,
                required_session_ids=["session-pending", "session-pending-edit"],
                excluded_session_ids=["session-plain"],
            ),
        )
        print(
            "picker_denied_filter=",
            matches_denied_filter_output(
                denied_picker,
                required_session_ids=["session-denied"],
                excluded_session_ids=["session-plain"],
            ),
        )
        print(
            "picker_approval_restore_filter=",
            matches_approval_restore_focus_output(
                approval_restore_picker,
                required_session_ids=[
                    "session-restored-pending",
                    "session-restored-edit-pending",
                    "session-denied",
                ],
                excluded_session_ids=["session-restore"],
            ),
        )
        print(
            "picker_workspace_inspect_filter=",
            matches_workspace_filter_output(
                workspace_inspect_picker,
                filter_mode="workspace-inspect",
                backlog_line="Workspace backlog: 1 session | lanes: inspect 1",
                focus="inspect",
                required_session_ids=["session-tool"],
                excluded_session_ids=["session-inspect"],
                required=["workspace lanes: inspect"],
            ),
        )
        print(
            "picker_workspace_edit_filter=",
            matches_workspace_filter_output(
                workspace_edit_picker,
                filter_mode="workspace-edit",
                backlog_line="Workspace backlog: 5 sessions | lanes: edit 5",
                focus="edit",
                required_session_ids=[
                    "session-pending-edit",
                    "session-restored-edit-pending",
                    "session-denied",
                ],
                excluded_session_ids=["session-inspect"],
                required=["workspace lanes: edit"],
            ),
        )
        print(
            "picker_pending_only_preview_age_source=",
            "- workspace focus age source:" in workspace_edit_pending_preview_picker
            and "- shell focus age source:" in shell_test_pending_preview_picker,
        )
        print(
            "picker_pending_only_preview_queue_provenance=",
            any(
                "- workspace focus queue provenance: fresh approval queue" in output
                for output in [queue_workspace_fresh_picker, queue_workspace_alt_picker]
            )
            and any(
                "- workspace focus queue provenance: restored approval queue" in output
                for output in [queue_workspace_fresh_picker, queue_workspace_alt_picker]
            )
            and any(
                "- shell focus queue provenance: fresh approval queue" in output
                for output in [queue_shell_fresh_picker, queue_shell_alt_picker]
            )
            and any(
                "- shell focus queue provenance: restored approval queue" in output
                for output in [queue_shell_fresh_picker, queue_shell_alt_picker]
            ),
        )
        print(
            "picker_pending_only_preview_queue_breakdown=",
            "- workspace focus queue (2):" in queue_breakdown_workspace_picker
            and "1. fresh write_file | path notes.txt" in queue_breakdown_workspace_picker
            and "2. restored replace_text | path src/app.py" in queue_breakdown_workspace_picker
            and "- shell focus queue (2):" in queue_breakdown_shell_picker
            and "1. fresh run_shell_command | cmd pytest -q" in queue_breakdown_shell_picker
            and "2. restored run_shell_command | cmd python -m pytest -q" in queue_breakdown_shell_picker,
        )
        print(
            "picker_workspace_overlap_summary=",
            matches_workspace_filter_output(
                workspace_overlap_inspect_picker,
                filter_mode="workspace-inspect",
                backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
                focus="inspect",
                required=["workspace lanes: inspect, edit"],
            )
            and matches_workspace_filter_output(
                workspace_overlap_edit_picker,
                filter_mode="workspace-edit",
                backlog_line="Workspace backlog: 2 sessions | lanes: inspect 1, edit 2 | overlap: mixed 1 session",
                focus="edit",
            ),
        )
        print(
            "picker_shell_filter=",
            matches_shell_filter_output(
                shell_picker,
                filter_mode="shell",
                backlog_line="Shell backlog: 6 sessions | lanes: inspect 2, test 5 (oldest 45d @",
                focus="inspect, test",
                required_session_ids=["session-inspect", "session-pending"],
                excluded_session_ids=["session-tool"],
                required=["shell: inspect 1"],
            ),
        )
        print(
            "picker_tool_filter=",
            matches_tool_filter_output(
                tool_picker,
                failure_mix_line="Tool failure mix: failures: test 1, tool 1 | failing: 2 sessions",
            ),
        )
        print(
            "picker_intervention_surface=",
            matches_intervention_filter_output(
                intervention_picker,
                required_session_ids=["session-pending", "session-denied"],
                excluded_session_ids=["session-plain"],
                required=["intervention: pending 1"],
                require_preview=True,
            ),
        )
        print(
            "picker_shell_inspect_filter=",
            matches_shell_filter_output(
                shell_inspect_picker,
                filter_mode="shell-inspect",
                backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
                focus="inspect",
                required_session_ids=["session-inspect", "session-pending"],
                excluded_session_ids=["session-tool"],
            ),
        )
        print(
            "picker_shell_test_filter=",
            matches_shell_filter_output(
                shell_test_picker,
                filter_mode="shell-test",
                backlog_line="Shell backlog: 5 sessions | lanes: inspect 1, test 5 (oldest 45d @",
                focus="test",
                required_session_ids=["session-pending", "session-aged", "session-failed-test"],
                excluded_session_ids=["session-inspect"],
            ),
        )
        print(
            "picker_attention_workspace_inspect_filter=",
            matches_workspace_filter_output(
                workspace_inspect_attention_picker,
                filter_mode="workspace-inspect",
                sort_mode="attention",
                backlog_line="Workspace backlog: 1 session | lanes: inspect 1",
                focus="inspect",
                required_session_ids=["session-tool"],
                excluded_session_ids=["session-pending", "session-failed-tool"],
                required=["workspace lanes: inspect"],
            )
            and "> 1. session-tool | 1 turn(s)" in workspace_inspect_attention_picker,
        )
        print(
            "picker_attention_workspace_edit_filter=",
            matches_workspace_filter_output(
                workspace_edit_attention_picker,
                filter_mode="workspace-edit",
                sort_mode="attention",
                backlog_line="Workspace backlog: 5 sessions | lanes: edit 5 (oldest 6h @",
                focus="edit",
                required_session_ids=[
                    "session-restored-edit-pending",
                    "session-pending",
                    "session-pending-edit",
                    "session-denied",
                    "session-failed-tool",
                ],
                excluded_session_ids=["session-tool"],
                required=["workspace lanes: edit"],
            )
            and "> 1. session-restored-edit-pending" in workspace_edit_attention_picker
            and "  2. session-pending | 1 turn(s)" in workspace_edit_attention_picker,
        )
        print(
            "picker_attention_shell_filter=",
            matches_shell_filter_output(
                shell_attention_picker,
                filter_mode="shell",
                sort_mode="attention",
                backlog_line="Shell backlog: 6 sessions | lanes: inspect 2, test 5 (oldest 45d @",
                focus="inspect, test",
                required_session_ids=[
                    "session-restored-pending",
                    "session-aged",
                    "session-pending",
                    "session-denied-test",
                    "session-failed-test",
                    "session-inspect",
                ],
                excluded_session_ids=["session-tool"],
                required=["shell: inspect 1", "| overlap: mixed 1 session"],
            )
            and "> 1. session-restored-pending" in shell_attention_picker
            and "  2. session-aged | 1 turn(s)" in shell_attention_picker,
        )
        print(
            "picker_attention_shell_inspect_filter=",
            matches_shell_filter_output(
                shell_inspect_attention_picker,
                filter_mode="shell-inspect",
                sort_mode="attention",
                backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
                focus="inspect",
                required_session_ids=["session-pending", "session-inspect"],
                excluded_session_ids=["session-tool", "session-aged", "session-restored-pending"],
            )
            and "> 1. session-pending | 1 turn(s)" in shell_inspect_attention_picker
            and "  2. session-inspect | 1 turn(s)" in shell_inspect_attention_picker
            and "shell lanes: inspect, test" in shell_inspect_attention_picker,
        )
        print(
            "picker_attention_shell_test_filter=",
            matches_shell_filter_output(
                shell_test_attention_picker,
                filter_mode="shell-test",
                sort_mode="attention",
                backlog_line="Shell backlog: 5 sessions | lanes: inspect 1, test 5 (oldest 45d @",
                focus="test",
                required_session_ids=[
                    "session-restored-pending",
                    "session-aged",
                    "session-pending",
                    "session-denied-test",
                    "session-failed-test",
                ],
                excluded_session_ids=["session-tool", "session-inspect"],
                required=["| overlap: mixed 1 session"],
            )
            and "> 1. session-restored-pending" in shell_test_attention_picker
            and "  2. session-aged | 1 turn(s)" in shell_test_attention_picker,
        )
        print(
            "picker_shell_overlap_badge=",
            "session-pending | 1 turn(s)" in shell_inspect_picker
            and "shell lanes: inspect, test" in shell_inspect_picker
            and "shell lanes: inspect, test" in shell_test_picker,
        )
        print(
            "picker_shell_overlap_summary=",
            matches_shell_filter_output(
                shell_overlap_picker,
                filter_mode="shell",
                backlog_line="Shell backlog: 3 sessions | lanes: inspect 2, test 2 | overlap: mixed 1 session",
                focus="inspect, test",
            )
            and matches_shell_filter_output(
                shell_overlap_inspect_picker,
                filter_mode="shell-inspect",
                backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
                focus="inspect",
                required=["shell lanes: inspect, test"],
            )
            and matches_shell_filter_output(
                shell_overlap_test_picker,
                filter_mode="shell-test",
                backlog_line="Shell backlog: 2 sessions | lanes: inspect 1, test 2 | overlap: mixed 1 session",
                focus="test",
            ),
        )
        print(
            "picker_denied_preview_origin=",
            matches_denied_preview_output(denied_picker),
        )
        print(
            "picker_denied_age=",
            matches_denied_preview_output(denied_picker),
        )
        print(
            "picker_denied_badges=",
            matches_denied_preview_output(denied_picker, required_badges=["denied: edit 1"]),
        )
        print(
            "picker_denied_page_rollup=",
            matches_denied_page_rollup_output(denied_rollup_picker, denied_rollup_page_two_picker),
        )
        print(
            "picker_restored_approval_badge=",
            matches_approval_restore_badges_output(approval_restore_picker),
        )
        print(
            "picker_restored_approval_tool_badges=",
            matches_approval_restore_tool_badges_output(approval_restore_picker),
        )
        print(
            "picker_restored_approval_age=",
            matches_approval_restore_age_output(approval_restore_picker),
        )
        print(
            "picker_restored_approval_preview_split=",
            matches_approval_restore_preview_split_output(approval_restore_picker),
        )
        print(
            "picker_restore_preview_compact=",
            matches_approval_restore_age_output(approval_restore_picker),
        )
        print(
            "picker_approval_stale_filter=",
            matches_broad_approval_stale_output(
                approval_stale_picker,
                required_session_ids=["session-aged"],
                excluded_session_ids=["session-restored-pending"],
            ),
        )
        print(
            "picker_approval_stale_backlog=",
            matches_stale_backlog_output(approval_stale_picker),
        )
        print(
            "picker_stale_cutoff_copy=",
            matches_stale_cutoff_output(approval_stale_picker),
        )
        print(
            "picker_stale_lane_focus=",
            matches_stale_lane_focus_output(approval_stale_picker),
        )
        print(
            "picker_stale_preview_compact=",
            matches_compact_stale_preview_output(approval_stale_picker),
        )
        print(
            "picker_stale_focus_rows=",
            matches_broad_stale_row_focus_suppression(approval_stale_picker),
        )
        print("picker_approval_rollup=", "approvals: pending 1, approved 1" in pending_picker)
        print("picker_row_approval_focus=", "approval focus: denied/restored" in denied_picker and "approval focus: pending" in default_picker)
        print(
            "picker_empty_hint=",
            "Try A to show all sessions" in empty_pending_picker
            and "Press Enter or N to start a fresh session while keeping this picker context for the next reopen." in empty_pending_picker,
        )
        print("picker_tool_rollup_surface=", matches_picker_default_output(default_picker))
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
            matches_pending_filter_output(
                pending_attention_picker,
                required_session_ids=["session-aged"],
                sort_mode="attention",
            )
            and matches_pending_age_output(pending_attention_picker)
            and matches_pending_age_output(pending_attention_age_picker, session_idle_age="10d"),
        )
        print(
            "picker_pending_queue_breakdown=",
            matches_queue_breakdown_output(
                mixed_pending_picker,
                summary_line="pending: 3 approvals (first test; rest edit 1, tool 1)",
                preview_line="- pending queue: first test; rest edit 1, tool 1",
            ),
        )
        print(
            "picker_pending_page_rollup=",
            matches_pending_page_rollup_output(
                pending_rollup_picker,
                pending_rollup_page_two_picker,
            ),
        )
        print(
            "picker_restored_pending_queue_breakdown=",
            matches_queue_breakdown_output(
                mixed_restored_picker,
                summary_line="approval restore queue: first test; rest edit 1, tool 1",
                preview_line="- approval restore queue: first test; rest edit 1, tool 1",
            ),
        )
        print(
            "picker_approval_restore_overlap_summary=",
            matches_approval_restore_overlap_output(mixed_restored_split_picker),
        )
        print(
            "picker_approval_restore_overlap_preview_split=",
            matches_approval_restore_overlap_preview_split_output(mixed_restored_split_picker),
        )
        print(
            "picker_approval_restore_page_rollup=",
            matches_approval_restore_page_rollup_output(
                approval_restore_rollup_picker,
                approval_restore_rollup_page_two_picker,
            ),
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
            and "  6. session-denied" in paged_picker
            and "  8. session-restored-pending" in paged_picker
            and "session-page-7" not in paged_picker,
        )

        with TemporaryDirectory() as stale_rollup_root:
            seed_stale_approval_rollup_scenario(stale_rollup_root, include_restored_outcome=True)

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
                matches_stale_page_rollup_output(
                    stale_rollup_picker,
                    stale_rollup_page_two_picker,
                ),
            )
            print(
                "picker_approval_stale_pending_filter=",
                matches_stale_pending_subfilter_output(
                    stale_pending_picker,
                    required_session_ids=["session-stale-pending-0"],
                    excluded_session_ids=["session-stale-denied-page-2"],
                ),
            )
            print(
                "picker_approval_stale_denied_filter=",
                matches_stale_denied_subfilter_output(
                    stale_denied_picker,
                    required_session_ids=["session-stale-denied-page-2"],
                    excluded_session_ids=["session-stale-restored-page-2"],
                ),
            )
            print(
                "picker_approval_stale_restored_filter=",
                matches_stale_restored_subfilter_output(
                    stale_restored_picker,
                    required_session_ids=["session-stale-restored-page-2"],
                    excluded_session_ids=["session-stale-denied-page-2"],
                ),
            )

        with TemporaryDirectory() as custom_stale_root:
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
            custom_stale_picker = render_session_picker(
                custom_stale_root,
                filter_mode="approval-stale",
                stale_approval_warning_seconds=24 * 60 * 60,
            )
            print(
                "picker_custom_stale_threshold=",
                matches_custom_stale_cutoff_output(custom_stale_picker),
            )
            print(
                "picker_custom_stale_cutoff_copy=",
                matches_stale_cutoff_output(custom_stale_picker, days=1),
            )
            print(
                "picker_custom_stale_lane_focus=",
                matches_stale_lane_focus_output(custom_stale_picker, days=1),
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
