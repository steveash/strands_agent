from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from strands_agent_tui.app import StrandsAgentApp
from strands_agent_tui.config import AppConfig
from strands_agent_tui.runtime import FakeStrandsRuntime, runtime_event
from strands_agent_tui.sessions import SessionArtifactStore
from strands_agent_tui.testing import (
    emit_smoke_checks as real_emit_smoke_checks,
    matches_shell_filter_output,
    matches_workspace_filter_output,
    seed_approval_restore_focus_scenario,
    seed_pending_approval_session,
    seed_plain_session,
    seed_shell_failure_session,
    seed_shell_test_session,
    seed_workspace_edit_session,
    seed_workspace_failure_session,
    seed_workspace_inspect_session,
    set_session_artifact_mtime,
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load_script_module(name: str):
    spec = spec_from_file_location(f"tests.{name}", SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_smoke_main_emits_requested_live_contract(monkeypatch) -> None:
    live_smoke = _load_script_module("live_smoke")

    class _Runtime:
        def run(self, prompt: str):
            assert prompt == "Reply with exactly: live runtime ok"
            return SimpleNamespace(text="live runtime ok", provider="stub-provider", mode="live")

    monkeypatch.setattr(
        live_smoke,
        "load_config",
        lambda: SimpleNamespace(runtime_mode="live", openai_model="stub-model"),
    )
    monkeypatch.setattr(live_smoke, "build_runtime", lambda **_: _Runtime())

    output = StringIO()
    monkeypatch.setattr(
        live_smoke,
        "emit_smoke_checks",
        lambda checks: real_emit_smoke_checks(checks, stdout=output),
    )

    with redirect_stdout(output):
        exit_code = live_smoke.main()

    assert exit_code == 0
    assert output.getvalue().splitlines() == [
        "live runtime ok",
        "provider=stub-provider mode=live",
        "live_runtime_requested= True",
        "live_runtime_text= True",
        "live_runtime_provider_mode= True",
    ]


def test_smoke_matrix_defaults_to_local_bundle_sequence(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main([])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-local", "triage", "recovery"],
        "args": [(), (), ()],
    }


def test_smoke_matrix_all_uses_live_inclusive_standalone_bundle(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main(["all"])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-all", "triage", "recovery"],
        "args": [("all",), (), ()],
    }


def test_smoke_matrix_emits_bundle_timing_summary(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)

    perf_values = iter([0.0, 1.0, 1.3, 2.0, 2.6, 3.0, 3.9, 4.5])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main([])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        "[smoke-matrix] running standalone-local",
        "[smoke-matrix] standalone-local passed in 0.30s",
        "[smoke-matrix] running triage",
        "[smoke-matrix] triage passed in 0.60s",
        "[smoke-matrix] running recovery",
        "[smoke-matrix] recovery passed in 0.90s",
        "[smoke-matrix] summary: 3/3 bundles passed in 4.50s",
    ]


def test_smoke_matrix_emits_failed_bundle_summary_and_stops(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = []

    def _run_smoke_target(target, **_kwargs):
        seen.append(target.name)
        return 1 if target.name == "triage" else 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    perf_values = iter([0.0, 1.0, 1.2, 1.4, 1.9, 2.5])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main([])

    assert exit_code == 1
    assert seen == ["standalone-local", "triage"]
    assert stdout.getvalue().splitlines() == [
        "[smoke-matrix] running standalone-local",
        "[smoke-matrix] standalone-local passed in 0.20s",
        "[smoke-matrix] running triage",
    ]
    assert stderr.getvalue().splitlines() == [
        "[smoke-matrix] triage failed in 0.50s",
        "[smoke-matrix] summary: 1/3 bundles passed before failure in 2.50s",
    ]


async def _render_switcher_attention_workspace_shell_outputs(tmp_path: Path) -> dict[str, str]:
    current_store = seed_plain_session(
        tmp_path,
        session_id="session-older",
        prompt="inspect older session",
        response="older response",
    )
    seed_pending_approval_session(
        tmp_path,
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
    )

    aged_turn_time = datetime.now(UTC) - timedelta(days=10)
    seed_shell_test_session(
        tmp_path,
        session_id="session-aged",
        prompt="resume stale queue",
        response="stale response",
        request_id="approval-aged-switcher",
        approval_prompt="resume old tests",
        created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
        turn_created_at=aged_turn_time.isoformat(),
    )
    set_session_artifact_mtime(SessionArtifactStore(tmp_path, session_id="session-aged"), aged_turn_time)

    seed_workspace_edit_session(
        tmp_path,
        session_id="session-pending-edit",
        prompt="queue pending edit",
        response="queued edit response",
        request_id="approval-0004b",
        tool_name="write_file",
        args={"relative_path": "notes.txt", "overwrite": True},
        approval_prompt="queue edit",
    )
    seed_approval_restore_focus_scenario(tmp_path)
    seed_shell_failure_session(tmp_path, session_id="session-failed-test", prompt="run failing test")
    seed_workspace_failure_session(tmp_path, session_id="session-failed-tool", prompt="attempt failing edit")
    seed_workspace_inspect_session(tmp_path, session_id="session-tool", prompt="list files")

    app = StrandsAgentApp(
        runtime=FakeStrandsRuntime(),
        config=AppConfig(
            runtime_mode="fake",
            openai_model="gpt-4o-mini",
            workspace_root=".",
            artifacts_root=str(tmp_path),
            session_id="session-older",
        ),
        artifact_store=current_store,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f11")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        workspace_inspect_output = str(app.query_one("#output").render())
        await pilot.press("e")
        await pilot.pause()
        workspace_edit_output = str(app.query_one("#output").render())
        await pilot.press("h")
        await pilot.pause()
        shell_output = str(app.query_one("#output").render())
        await pilot.press("i")
        await pilot.pause()
        shell_inspect_output = str(app.query_one("#output").render())
        await pilot.press("y")
        await pilot.pause()
        shell_test_output = str(app.query_one("#output").render())

    return {
        "workspace_inspect": workspace_inspect_output,
        "workspace_edit": workspace_edit_output,
        "shell": shell_output,
        "shell_inspect": shell_inspect_output,
        "shell_test": shell_test_output,
    }


@pytest.mark.asyncio
async def test_session_switcher_attention_workspace_and_shell_filters_match_smoke_expectations(
    tmp_path: Path,
) -> None:
    outputs = await _render_switcher_attention_workspace_shell_outputs(tmp_path)

    assert matches_workspace_filter_output(
        outputs["workspace_inspect"],
        filter_mode="workspace-inspect",
        sort_mode="attention",
        backlog_line="Workspace backlog: 2 sessions | lanes: inspect 2, edit 1 | overlap: mixed 1 session",
        focus="inspect",
        required_session_ids=["session-tool", "session-newer"],
        excluded_session_ids=["session-failed-tool"],
        required=["workspace lanes: inspect"],
    )
    assert matches_workspace_filter_output(
        outputs["workspace_edit"],
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
    )
    assert matches_shell_filter_output(
        outputs["shell"],
        filter_mode="shell",
        sort_mode="attention",
        backlog_line="Shell backlog: 4 sessions | lanes: inspect 1, test 4 (oldest 45d @",
        focus="inspect, test",
        required_session_ids=[
            "session-newer",
            "session-aged",
            "session-failed-test",
            "session-restored-pending",
        ],
        excluded_session_ids=["session-tool"],
        required=["shell: inspect 1", "| overlap: mixed 1 session"],
    )
    assert matches_shell_filter_output(
        outputs["shell_inspect"],
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
    )
    assert "session-newer | 1 turn(s)" in outputs["shell_inspect"]
    assert "shell lanes: inspect, test" in outputs["shell_inspect"]
    assert matches_shell_filter_output(
        outputs["shell_test"],
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
    )
