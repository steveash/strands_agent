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
