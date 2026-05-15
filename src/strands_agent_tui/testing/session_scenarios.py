from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from strands_agent_tui.runtime import ApprovalRequest, runtime_event
from strands_agent_tui.sessions import MAX_RECENT_SESSIONS, SessionArtifactStore, TurnArtifact


@dataclass(frozen=True)
class ApprovalRestoreFocusScenario:
    restored_pending_id: str = "session-restored-pending"
    restored_edit_pending_id: str = "session-restored-edit-pending"
    restored_outcome_id: str = "session-denied"


@dataclass(frozen=True)
class StaleApprovalFilterScenario:
    pending_id: str = "session-stale-pending"
    denied_id: str = "session-stale-denied"
    restored_id: str = "session-stale-restored"
    fresh_pending_id: str = "session-fresh-pending"


@dataclass(frozen=True)
class StaleApprovalSubfilterScenario:
    pending_id: str = "session-stale-pending"
    denied_id: str = "session-stale-denied"
    restored_queue_id: str = "session-stale-restored-queue"
    restored_mixed_id: str = "session-stale-restored"


@dataclass(frozen=True)
class StaleApprovalRollupScenario:
    pending_prefix: str = "session-stale-pending"
    denied_id: str = "session-stale-denied-page-2"
    restored_id: str = "session-stale-restored-page-2"


@dataclass(frozen=True)
class PendingApprovalRollupScenario:
    pending_prefix: str = "session-pending-page"
    restored_id: str = "session-pending-restored-page-2"
    multi_id: str = "session-pending-multi-page-2"


@dataclass(frozen=True)
class DeniedApprovalRollupScenario:
    denied_prefix: str = "session-denied-page"
    restored_id: str = "session-denied-restored-page-2"
    edit_id: str = "session-denied-edit-page-2"


@dataclass(frozen=True)
class ApprovalRestoreRollupScenario:
    queue_prefix: str = "session-restored-queue"
    restored_outcome_id: str = "session-restored-outcome-page-2"
    mixed_id: str = "session-restored-overlap-page-2"


def append_turn(
    store: SessionArtifactStore,
    prompt: str,
    response: str = "ok",
    *,
    created_at: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    store.append_turn(
        TurnArtifact(
            prompt=prompt,
            response=response,
            provider="fake-strands",
            mode="fake",
            events=events or [],
            response_metadata={"mode": "fake"},
            created_at=created_at,
        )
    )


def set_session_artifact_mtime(store: SessionArtifactStore, when: datetime) -> None:
    timestamp = when.timestamp()
    for path in [store.session_dir, *store.session_dir.iterdir()]:
        os.utime(path, (timestamp, timestamp))


def seed_workspace_inspect_session(
    root: Path | str,
    *,
    session_id: str = "session-workspace-inspect",
    prompt: str = "inspect files",
    tool_name: str = "list_files",
    event_message: str = "Finished listing files",
    result_preview: str = ".: README.md",
    response: str = "done",
) -> SessionArtifactStore:
    store = SessionArtifactStore(Path(root), session_id=session_id)
    append_turn(
        store,
        prompt,
        response=response,
        events=[
            runtime_event(
                "tool_finished",
                tool_name,
                event_message,
                data={"tool_name": tool_name, "result_preview": result_preview},
            )
        ],
    )
    return store


def seed_workspace_edit_session(
    root: Path | str,
    *,
    session_id: str = "session-workspace-edit",
    prompt: str = "queue edit",
    response: str = "ok",
    request_id: str = "approval-workspace-edit",
    tool_name: str = "replace_text",
    args: dict[str, Any] | None = None,
    approval_prompt: str = "queue replace_text",
    restored_from_session: bool = False,
    created_at: str | None = None,
) -> SessionArtifactStore:
    approval_args = args or {
        "relative_path": "notes.txt",
        "old_text": "old",
        "new_text": "new",
    }
    store = SessionArtifactStore(Path(root), session_id=session_id)
    append_turn(store, prompt, response=response)
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=request_id,
                tool_name=tool_name,
                reason="Needs confirmation",
                args=approval_args,
                source="fake_runtime",
                prompt=approval_prompt,
                restored_from_session=restored_from_session,
                created_at=created_at,
            )
        ]
    )
    return store


def seed_workspace_overlap_session(
    root: Path | str,
    *,
    session_id: str = "session-workspace-mixed",
    prompt: str = "inspect before editing",
    response: str = "pending",
    tool_name: str = "read_file",
    event_message: str = "Finished reading file",
    result_preview: str = "README.md lines 1-20",
    request_id: str = "approval-workspace-mixed",
    approval_prompt: str = "apply the edit",
) -> SessionArtifactStore:
    store = seed_workspace_inspect_session(
        root,
        session_id=session_id,
        prompt=prompt,
        tool_name=tool_name,
        event_message=event_message,
        result_preview=result_preview,
        response=response,
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=request_id,
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt=approval_prompt,
            )
        ]
    )
    return store


def seed_shell_inspect_session(
    root: Path | str,
    *,
    session_id: str = "session-shell-inspect",
    prompt: str = "inspect shell state",
    command: str = "git status --short",
    result_preview: str = "git status --short -> M README.md",
    response: str = "done",
) -> SessionArtifactStore:
    store = SessionArtifactStore(Path(root), session_id=session_id)
    append_turn(
        store,
        prompt,
        response=response,
        events=[
            runtime_event(
                "tool_finished",
                "run_shell_command",
                "Finished shell command",
                data={
                    "tool_name": "run_shell_command",
                    "command": command,
                    "shell_policy": "inspect",
                    "exit_code": 0,
                    "result_preview": result_preview,
                },
            )
        ],
    )
    return store


def seed_shell_test_session(
    root: Path | str,
    *,
    session_id: str = "session-shell-test",
    prompt: str = "queue shell test",
    response: str = "ok",
    request_id: str = "approval-shell-test",
    command: str = "pytest -q",
    approval_prompt: str = "run tests",
    restored_from_session: bool = False,
    created_at: str | None = None,
) -> SessionArtifactStore:
    store = SessionArtifactStore(Path(root), session_id=session_id)
    append_turn(store, prompt, response=response)
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=request_id,
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": command},
                source="fake_runtime",
                prompt=approval_prompt,
                restored_from_session=restored_from_session,
                created_at=created_at,
            )
        ]
    )
    return store


def seed_shell_overlap_session(
    root: Path | str,
    *,
    session_id: str = "session-shell-mixed-rollup",
    prompt: str = "inspect before rerunning tests",
    response: str = "pending",
    command: str = "git diff --stat",
    result_preview: str = "git diff --stat -> README.md | 2 +-",
    request_id: str = "approval-shell-mixed-rollup",
    approval_prompt: str = "rerun tests",
    pending_command: str = "pytest -q",
) -> SessionArtifactStore:
    store = seed_shell_inspect_session(
        root,
        session_id=session_id,
        prompt=prompt,
        command=command,
        result_preview=result_preview,
        response=response,
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=request_id,
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": pending_command},
                source="fake_runtime",
                prompt=approval_prompt,
            )
        ]
    )
    return store


def seed_multi_approval_queue_session(
    root: Path | str,
    *,
    session_id: str = "session-pending-mixed",
    prompt: str = "queue mixed approvals",
    response: str = "ok",
    restored_from_session: bool = False,
    request_id_prefix: str = "approval-mixed",
) -> SessionArtifactStore:
    store = SessionArtifactStore(Path(root), session_id=session_id)
    append_turn(store, prompt, response=response)
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=f"{request_id_prefix}-test",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="run tests" if not restored_from_session else "rerun restored tests",
                restored_from_session=restored_from_session,
            ),
            ApprovalRequest(
                request_id=f"{request_id_prefix}-edit",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="queue edit" if not restored_from_session else "resume restored edit",
                restored_from_session=restored_from_session,
            ),
            ApprovalRequest(
                request_id=f"{request_id_prefix}-tool",
                tool_name="list_files",
                reason="Needs confirmation",
                args={"relative_path": "."},
                source="fake_runtime",
                prompt="inspect tree" if not restored_from_session else "resume restored inspection",
                restored_from_session=restored_from_session,
            ),
        ]
    )
    return store


def seed_approval_restore_overlap_session(
    root: Path | str,
    *,
    now: datetime | None = None,
    session_id: str = "session-restored-overlap",
    prompt: str = "restore denied edit and pending test",
    response: str = "ok",
    pending_request_id: str = "approval-overlap-pending",
    outcome_request_id: str = "approval-overlap-outcome",
) -> SessionArtifactStore:
    base_time = now or datetime.now(UTC)
    store = SessionArtifactStore(Path(root), session_id=session_id)
    denied_event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": outcome_request_id,
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    denied_event.timestamp = (base_time - timedelta(hours=6, minutes=5)).isoformat()
    append_turn(
        store,
        prompt,
        response=response,
        events=[denied_event],
    )
    store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id=pending_request_id,
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun restored tests",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=3, hours=2)).isoformat(),
            )
        ]
    )
    return store


def seed_approval_restore_focus_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: ApprovalRestoreFocusScenario = ApprovalRestoreFocusScenario(),
) -> ApprovalRestoreFocusScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    restored_pending_store = SessionArtifactStore(root_path, session_id=scenario.restored_pending_id)
    append_turn(restored_pending_store, "resume the restored test queue")
    restored_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restore-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="resume tests",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=3, hours=2)).isoformat(),
            )
        ]
    )

    restored_edit_pending_store = SessionArtifactStore(root_path, session_id=scenario.restored_edit_pending_id)
    append_turn(restored_edit_pending_store, "resume the restored edit queue")
    restored_edit_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restore-edit-pending",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
            )
        ]
    )

    restored_outcome_store = SessionArtifactStore(root_path, session_id=scenario.restored_outcome_id)
    restored_outcome_event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-restore-outcome",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    restored_outcome_event.timestamp = (base_time - timedelta(hours=6, minutes=5)).isoformat()
    append_turn(
        restored_outcome_store,
        "deny restored edit",
        events=[restored_outcome_event],
    )

    return scenario


def seed_stale_approval_filter_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: StaleApprovalFilterScenario = StaleApprovalFilterScenario(),
) -> StaleApprovalFilterScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    stale_pending_store = SessionArtifactStore(root_path, session_id=scenario.pending_id)
    append_turn(stale_pending_store, "resume very old pending queue")
    stale_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(base_time - timedelta(days=45)).isoformat(),
            )
        ]
    )

    stale_denied_store = SessionArtifactStore(root_path, session_id=scenario.denied_id)
    stale_denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    stale_denied_event.timestamp = (base_time - timedelta(days=9)).isoformat()
    append_turn(
        stale_denied_store,
        "deny old test rerun",
        events=[stale_denied_event],
    )

    stale_restored_store = SessionArtifactStore(root_path, session_id=scenario.restored_id)
    append_turn(stale_restored_store, "resume stale restored queue")
    stale_restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=8)).isoformat(),
            )
        ]
    )
    stale_restored_event = runtime_event(
        "steering_approved",
        "run_shell_command",
        "Approved in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-restored",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
            "command": "pytest -q",
        },
    )
    stale_restored_event.timestamp = (base_time - timedelta(days=10)).isoformat()
    append_turn(
        stale_restored_store,
        "approve restored stale test rerun",
        events=[stale_restored_event],
    )

    fresh_pending_store = SessionArtifactStore(root_path, session_id=scenario.fresh_pending_id)
    append_turn(fresh_pending_store, "resume fresh queue")
    fresh_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-fresh-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(base_time - timedelta(days=2)).isoformat(),
            )
        ]
    )

    return scenario


def seed_stale_approval_subfilter_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: StaleApprovalSubfilterScenario = StaleApprovalSubfilterScenario(),
) -> StaleApprovalSubfilterScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    stale_pending_store = SessionArtifactStore(root_path, session_id=scenario.pending_id)
    append_turn(stale_pending_store, "resume very old pending queue")
    stale_pending_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun tests",
                created_at=(base_time - timedelta(days=45)).isoformat(),
            )
        ]
    )

    stale_denied_store = SessionArtifactStore(root_path, session_id=scenario.denied_id)
    stale_denied_event = runtime_event(
        "steering_denied",
        "run_shell_command",
        "Denied in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-denied",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
            "command": "pytest -q",
        },
    )
    stale_denied_event.timestamp = (base_time - timedelta(days=9)).isoformat()
    append_turn(stale_denied_store, "deny old test rerun", events=[stale_denied_event])

    stale_restored_queue_store = SessionArtifactStore(root_path, session_id=scenario.restored_queue_id)
    append_turn(stale_restored_queue_store, "resume stale restored queue")
    stale_restored_queue_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-queue",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=11)).isoformat(),
            )
        ]
    )

    stale_restored_store = SessionArtifactStore(root_path, session_id=scenario.restored_mixed_id)
    append_turn(stale_restored_store, "resume mixed stale restored queue")
    stale_restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-stale-restored-pending",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume edit",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=10)).isoformat(),
            )
        ]
    )
    stale_restored_event = runtime_event(
        "steering_approved",
        "run_shell_command",
        "Approved in the TUI",
        data={
            "tool_name": "run_shell_command",
            "approval_id": "approval-stale-restored",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
            "command": "pytest -q",
        },
    )
    stale_restored_event.timestamp = (base_time - timedelta(days=9)).isoformat()
    append_turn(
        stale_restored_store,
        "approve restored old test rerun",
        events=[stale_restored_event],
    )

    return scenario


def seed_stale_approval_rollup_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: StaleApprovalRollupScenario = StaleApprovalRollupScenario(),
    include_restored_outcome: bool = False,
    pending_count: int = MAX_RECENT_SESSIONS,
) -> StaleApprovalRollupScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    for index in range(pending_count):
        store = SessionArtifactStore(root_path, session_id=f"{scenario.pending_prefix}-{index}")
        activity_time = base_time - timedelta(minutes=index)
        append_turn(
            store,
            f"resume stale pending queue {index}",
            created_at=activity_time.isoformat(),
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
                    created_at=(base_time - timedelta(days=45 + index)).isoformat(),
                )
            ]
        )
        set_session_artifact_mtime(store, activity_time)

    denied_store = SessionArtifactStore(root_path, session_id=scenario.denied_id)
    denied_activity_time = base_time - timedelta(minutes=100)
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
    denied_event.timestamp = (base_time - timedelta(days=14)).isoformat()
    append_turn(
        denied_store,
        "deny stale page-two test rerun",
        created_at=denied_activity_time.isoformat(),
        events=[denied_event],
    )
    set_session_artifact_mtime(denied_store, denied_activity_time)

    restored_store = SessionArtifactStore(root_path, session_id=scenario.restored_id)
    restored_activity_time = base_time - timedelta(minutes=101)
    append_turn(
        restored_store,
        "resume stale restored page-two queue",
        created_at=restored_activity_time.isoformat(),
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
                created_at=(base_time - timedelta(days=11)).isoformat(),
            )
        ]
    )
    if include_restored_outcome:
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
        restored_event.timestamp = (base_time - timedelta(days=10)).isoformat()
        append_turn(
            restored_store,
            "approve stale restored page-two test rerun",
            created_at=restored_activity_time.isoformat(),
            events=[restored_event],
        )
    set_session_artifact_mtime(restored_store, restored_activity_time)

    return scenario


def seed_pending_approval_rollup_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: PendingApprovalRollupScenario = PendingApprovalRollupScenario(),
    pending_count: int = MAX_RECENT_SESSIONS,
) -> PendingApprovalRollupScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    for index in range(pending_count):
        store = SessionArtifactStore(root_path, session_id=f"{scenario.pending_prefix}-{index}")
        activity_time = base_time - timedelta(hours=index + 1)
        append_turn(
            store,
            f"queue fresh pending approval {index}",
            created_at=activity_time.isoformat(),
        )
        store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id=f"approval-pending-page-{index}",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt=f"rerun fresh pending test {index}",
                    created_at=(base_time - timedelta(days=11 + index)).isoformat(),
                )
            ]
        )
        set_session_artifact_mtime(store, activity_time)

    restored_store = SessionArtifactStore(root_path, session_id=scenario.restored_id)
    restored_activity_time = base_time - timedelta(hours=9)
    append_turn(
        restored_store,
        "resume restored pending edit",
        created_at=restored_activity_time.isoformat(),
    )
    restored_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-pending-restored-page-2",
                tool_name="write_file",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "overwrite": True},
                source="fake_runtime",
                prompt="resume restored edit",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=3)).isoformat(),
            )
        ]
    )
    set_session_artifact_mtime(restored_store, restored_activity_time)

    multi_store = SessionArtifactStore(root_path, session_id=scenario.multi_id)
    multi_activity_time = base_time - timedelta(hours=10)
    append_turn(
        multi_store,
        "queue mixed pending follow-ups",
        created_at=multi_activity_time.isoformat(),
    )
    multi_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-pending-multi-page-2-a",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun mixed pending test",
                created_at=(base_time - timedelta(days=2)).isoformat(),
            ),
            ApprovalRequest(
                request_id="approval-pending-multi-page-2-b",
                tool_name="replace_text",
                reason="Needs confirmation",
                args={"relative_path": "notes.txt", "old_text": "old", "new_text": "new"},
                source="fake_runtime",
                prompt="queue mixed pending edit",
                created_at=(base_time - timedelta(days=1)).isoformat(),
            ),
        ]
    )
    set_session_artifact_mtime(multi_store, multi_activity_time)

    return scenario


def seed_denied_approval_rollup_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: DeniedApprovalRollupScenario = DeniedApprovalRollupScenario(),
    denied_count: int = MAX_RECENT_SESSIONS,
) -> DeniedApprovalRollupScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    for index in range(denied_count):
        store = SessionArtifactStore(root_path, session_id=f"{scenario.denied_prefix}-{index}")
        activity_time = base_time - timedelta(hours=index + 1)
        denied_event = runtime_event(
            "steering_denied",
            "run_shell_command",
            "Denied in the TUI",
            data={
                "tool_name": "run_shell_command",
                "approval_id": f"approval-denied-page-{index}",
                "approval_status": "denied",
                "approval_source": "fake_runtime",
                "remaining_pending_count": 0,
                "command": "pytest -q",
            },
        )
        denied_event.timestamp = (base_time - timedelta(hours=11 + index)).isoformat()
        append_turn(
            store,
            f"deny fresh test rerun {index}",
            created_at=activity_time.isoformat(),
            events=[denied_event],
        )
        set_session_artifact_mtime(store, activity_time)

    restored_store = SessionArtifactStore(root_path, session_id=scenario.restored_id)
    restored_activity_time = base_time - timedelta(hours=9)
    restored_event = runtime_event(
        "steering_denied",
        "write_file",
        "Denied in the TUI",
        data={
            "tool_name": "write_file",
            "approval_id": "approval-denied-restored-page-2",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    restored_event.timestamp = (base_time - timedelta(days=3)).isoformat()
    append_turn(
        restored_store,
        "deny restored edit",
        created_at=restored_activity_time.isoformat(),
        events=[restored_event],
    )
    set_session_artifact_mtime(restored_store, restored_activity_time)

    edit_store = SessionArtifactStore(root_path, session_id=scenario.edit_id)
    edit_activity_time = base_time - timedelta(hours=10)
    edit_event = runtime_event(
        "steering_denied",
        "replace_text",
        "Denied in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-denied-edit-page-2",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "remaining_pending_count": 0,
        },
    )
    edit_event.timestamp = (base_time - timedelta(days=2)).isoformat()
    append_turn(
        edit_store,
        "deny fresh edit",
        created_at=edit_activity_time.isoformat(),
        events=[edit_event],
    )
    set_session_artifact_mtime(edit_store, edit_activity_time)

    return scenario


def seed_approval_restore_rollup_scenario(
    root: Path | str,
    *,
    now: datetime | None = None,
    scenario: ApprovalRestoreRollupScenario = ApprovalRestoreRollupScenario(),
    queue_count: int = MAX_RECENT_SESSIONS,
) -> ApprovalRestoreRollupScenario:
    base_time = now or datetime.now(UTC)
    root_path = Path(root)

    for index in range(queue_count):
        store = SessionArtifactStore(root_path, session_id=f"{scenario.queue_prefix}-{index}")
        activity_time = base_time - timedelta(hours=index + 1)
        append_turn(
            store,
            f"resume restored queue {index}",
            created_at=activity_time.isoformat(),
        )
        store.save_pending_approvals(
            [
                ApprovalRequest(
                    request_id=f"approval-restored-queue-{index}",
                    tool_name="run_shell_command",
                    reason="Needs confirmation",
                    args={"command": "pytest -q"},
                    source="fake_runtime",
                    prompt=f"rerun restored queue {index}",
                    restored_from_session=True,
                    created_at=(base_time - timedelta(days=11 + index)).isoformat(),
                )
            ]
        )
        set_session_artifact_mtime(store, activity_time)

    restored_outcome_store = SessionArtifactStore(root_path, session_id=scenario.restored_outcome_id)
    restored_outcome_activity_time = base_time - timedelta(hours=10)
    restored_outcome_event = runtime_event(
        "steering_approved",
        "replace_text",
        "Approved in the TUI",
        data={
            "tool_name": "replace_text",
            "approval_id": "approval-restored-outcome-page-2",
            "approval_status": "approved",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
            "resumed_from_approval": True,
        },
    )
    restored_outcome_event.timestamp = (base_time - timedelta(hours=8)).isoformat()
    append_turn(
        restored_outcome_store,
        "review restored outcome only",
        created_at=restored_outcome_activity_time.isoformat(),
        events=[restored_outcome_event],
    )
    set_session_artifact_mtime(restored_outcome_store, restored_outcome_activity_time)

    mixed_store = SessionArtifactStore(root_path, session_id=scenario.mixed_id)
    mixed_activity_time = base_time - timedelta(hours=11)
    mixed_event = runtime_event(
        "steering_denied",
        "write_file",
        "Denied in the TUI",
        data={
            "tool_name": "write_file",
            "approval_id": "approval-restored-overlap-page-2-outcome",
            "approval_status": "denied",
            "approval_source": "fake_runtime",
            "approval_restored": True,
            "remaining_pending_count": 0,
        },
    )
    mixed_event.timestamp = (base_time - timedelta(hours=6)).isoformat()
    append_turn(
        mixed_store,
        "review mixed restored overlap",
        created_at=mixed_activity_time.isoformat(),
        events=[mixed_event],
    )
    mixed_store.save_pending_approvals(
        [
            ApprovalRequest(
                request_id="approval-restored-overlap-page-2-pending",
                tool_name="run_shell_command",
                reason="Needs confirmation",
                args={"command": "pytest -q"},
                source="fake_runtime",
                prompt="rerun mixed restored tests",
                restored_from_session=True,
                created_at=(base_time - timedelta(days=3)).isoformat(),
            )
        ]
    )
    set_session_artifact_mtime(mixed_store, mixed_activity_time)

    return scenario
