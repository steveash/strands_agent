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
from strands_agent_tui.sessions import SessionArtifactStore, render_session_picker
from strands_agent_tui.testing import (
    SESSION_RECOVERY_SMOKE_WRAPPER,
    SESSION_TRIAGE_SMOKE_WRAPPER,
    STANDALONE_SMOKE_WRAPPER,
    emit_smoke_checks as real_emit_smoke_checks,
    matches_shell_filter_output,
    matches_workspace_filter_output,
    seed_approval_restore_focus_scenario,
    seed_denied_approval_session,
    seed_pending_approval_session,
    seed_plain_session,
    seed_shell_failure_session,
    seed_shell_inspect_session,
    seed_shell_test_session,
    seed_workspace_edit_session,
    seed_workspace_failure_session,
    seed_workspace_inspect_session,
    set_session_artifact_mtime,
    summary_line_prefixes,
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load_script_module(name: str):
    spec = spec_from_file_location(f"tests.{name}", SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_mixed_smoke_result_contract(
    lines: list[str],
    *,
    detail_names: list[str],
    check_names: list[str],
) -> None:
    for name in detail_names:
        assert any(line.startswith(f"{name}: ") for line in lines)
        assert not any(line.startswith(f"{name}= ") for line in lines)
    for name in check_names:
        assert f"{name}= True" in lines or f"{name}= False" in lines
        assert not any(line.startswith(f"{name}: ") for line in lines)


def _format_script_help(name: str) -> str:
    module = _load_script_module(name)
    return module.build_parser().format_help()


def _normalize_help_text(text: str) -> str:
    return " ".join(text.split())


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


def test_approval_restart_smoke_emits_mixed_detail_and_boolean_lines(monkeypatch) -> None:
    approval_restart_smoke = _load_script_module("approval_restart_smoke")
    output = StringIO()
    real_emit_smoke_results = approval_restart_smoke.emit_smoke_results
    monkeypatch.setattr(
        approval_restart_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = approval_restart_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=["saved pending", "after restart approve text", "remaining pending"],
        check_names=[
            "approval_restart_saved_queue",
            "approval_restart_resumed_first_request",
            "approval_restart_remaining_queue",
        ],
    )


def test_session_state_smoke_emits_mixed_detail_and_boolean_lines(monkeypatch) -> None:
    session_state_smoke = _load_script_module("session_state_smoke")
    output = StringIO()
    real_emit_smoke_results = session_state_smoke.emit_smoke_results
    monkeypatch.setattr(
        session_state_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = session_state_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=["restored_event_filter", "restored_view", "restored_draft", "latest_visible_event"],
        check_names=[
            "session_state_restored_event_filter",
            "session_state_restored_view",
            "session_state_restored_draft",
            "session_state_latest_visible_event",
        ],
    )


def test_live_restore_smoke_wrapper_preserves_detail_lines_and_success_exit(monkeypatch) -> None:
    live_restore_smoke = _load_script_module("live_restore_smoke")
    output = StringIO()
    monkeypatch.setattr(
        live_restore_smoke,
        "run_live_restore_smoke",
        lambda: {
            "summary_value": "approved write_file via live_runtime | resumed | remaining 0",
            "live_restore_summary": True,
            "notes_text": "updated from restored approval",
            "live_restore_tool_event": True,
        },
    )
    real_emit_smoke_results = live_restore_smoke.emit_smoke_results
    monkeypatch.setattr(
        live_restore_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = live_restore_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    assert lines == [
        "summary_value: approved write_file via live_runtime | resumed | remaining 0",
        "live_restore_summary= True",
        "notes_text: updated from restored approval",
        "live_restore_tool_event= True",
    ]


def test_live_restore_denied_smoke_wrapper_preserves_detail_lines_and_failure_exit(monkeypatch) -> None:
    live_restore_denied_smoke = _load_script_module("live_restore_denied_smoke")
    output = StringIO()
    monkeypatch.setattr(
        live_restore_denied_smoke,
        "run_live_restore_denied_smoke",
        lambda: {
            "summary_value": "denied write_file via live_runtime | restored queue | remaining 0",
            "live_restore_denied_summary": True,
            "notes_text": "old",
            "live_restore_denied_no_tool_event": False,
        },
    )
    real_emit_smoke_results = live_restore_denied_smoke.emit_smoke_results
    monkeypatch.setattr(
        live_restore_denied_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = live_restore_denied_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 1
    assert lines == [
        "summary_value: denied write_file via live_runtime | restored queue | remaining 0",
        "live_restore_denied_summary= True",
        "notes_text: old",
        "live_restore_denied_no_tool_event= False",
    ]


@pytest.mark.parametrize(
    ("argv", "expected_names"),
    [
        ([], ["summary-utils", "shell-tool", "replay"]),
        (["local"], ["summary-utils", "shell-tool", "replay"]),
        (["all"], ["summary-utils", "shell-tool", "replay", "live"]),
        (["summary-utils"], ["summary-utils"]),
        (["live"], ["live"]),
    ],
)
def test_standalone_smoke_selects_expected_targets(monkeypatch, argv, expected_names) -> None:
    standalone_smoke = _load_script_module("standalone_smoke")

    seen = {}

    def _run_smoke_targets(targets, **_kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        return 0

    monkeypatch.setattr(standalone_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = standalone_smoke.main(argv)

    assert exit_code == 0
    assert seen == {
        "names": expected_names,
        "args": [() for _ in expected_names],
    }


@pytest.mark.parametrize(
    ("argv", "expected_names"),
    [
        ([], ["picker", "switcher"]),
        (["both"], ["picker", "switcher"]),
        (["all"], ["picker", "switcher"]),
        (["picker"], ["picker"]),
        (["switcher"], ["switcher"]),
    ],
)
def test_session_triage_smoke_selects_expected_targets(monkeypatch, argv, expected_names) -> None:
    session_triage_smoke = _load_script_module("session_triage_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        seen["summary_label"] = kwargs.get("summary_label")
        return 0

    monkeypatch.setattr(session_triage_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = session_triage_smoke.main(argv)

    assert exit_code == 0
    assert seen == {
        "names": expected_names,
        "args": [() for _ in expected_names],
        "summary_label": "session-triage-smoke",
    }


@pytest.mark.parametrize(
    ("argv", "expected_names"),
    [
        ([], ["approval", "approval-restart", "session-state", "live-restore", "live-restore-denied"]),
        (["all"], ["approval", "approval-restart", "session-state", "live-restore", "live-restore-denied"]),
        (["approval"], ["approval"]),
        (["live-restore-denied"], ["live-restore-denied"]),
    ],
)
def test_session_recovery_smoke_selects_expected_targets(monkeypatch, argv, expected_names) -> None:
    session_recovery_smoke = _load_script_module("session_recovery_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        seen["summary_label"] = kwargs.get("summary_label")
        return 0

    monkeypatch.setattr(session_recovery_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = session_recovery_smoke.main(argv)

    assert exit_code == 0
    assert seen == {
        "names": expected_names,
        "args": [() for _ in expected_names],
        "summary_label": "session-recovery-smoke",
    }


def test_standalone_smoke_passes_summary_label(monkeypatch) -> None:
    standalone_smoke = _load_script_module("standalone_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["summary_label"] = kwargs.get("summary_label")
        return 0

    monkeypatch.setattr(standalone_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = standalone_smoke.main(["summary-utils"])

    assert exit_code == 0
    assert seen == {
        "names": ["summary-utils"],
        "summary_label": "standalone-smoke",
    }


def test_smoke_wrapper_help_documents_aliases_and_single_target_examples() -> None:
    standalone_help = _normalize_help_text(_format_script_help("standalone_smoke"))
    assert "Alias details: local -> summary-utils, shell-tool, replay all -> summary-utils, shell-tool, replay, live" in standalone_help
    assert "default local alias -> summary-utils, shell-tool, replay" in standalone_help
    assert "standalone_smoke.py all # all alias -> summary-utils, shell-tool, replay, live" in standalone_help
    assert "standalone_smoke.py replay # single target" in standalone_help

    triage_help = _normalize_help_text(_format_script_help("session_triage_smoke"))
    assert "Alias details: both -> picker, switcher all -> picker, switcher" in triage_help
    assert "default both alias -> picker, switcher" in triage_help
    assert "session_triage_smoke.py all # all alias -> picker, switcher" in triage_help
    assert "session_triage_smoke.py picker # single target" in triage_help

    recovery_help = _normalize_help_text(_format_script_help("session_recovery_smoke"))
    assert "Alias details: all -> approval, approval-restart, session-state, live-restore, live-restore-denied" in recovery_help
    assert "default all alias -> approval, approval-restart, session-state, live-restore, live-restore-denied" in recovery_help
    assert "session_recovery_smoke.py live-restore # single target" in recovery_help
    assert "session_recovery_smoke.py approval # single target" in recovery_help


def test_smoke_matrix_help_documents_bundle_examples() -> None:
    help_text = _normalize_help_text(_format_script_help("smoke_matrix"))

    assert "Bundle aliases: local -> standalone-local, triage, recovery all -> standalone-all, triage, recovery" in help_text
    assert "default local alias -> standalone-local, triage, recovery" in help_text
    assert "smoke_matrix.py standalone # single bundle" in help_text
    assert "smoke_matrix.py triage # single bundle" in help_text
    assert "smoke_matrix.py recovery # single bundle" in help_text
    assert "smoke_matrix.py all # all alias -> standalone-all, triage, recovery" in help_text


def test_smoke_matrix_uses_shared_wrapper_summary_prefixes() -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    assert smoke_matrix.SUPPRESSED_NESTED_SUMMARY_PREFIXES == summary_line_prefixes(
        (
            STANDALONE_SMOKE_WRAPPER,
            SESSION_TRIAGE_SMOKE_WRAPPER,
            SESSION_RECOVERY_SMOKE_WRAPPER,
        )
    )


def test_smoke_matrix_hides_internal_bundle_names_from_cli_choices(capsys) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_matrix.main(["standalone-all"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    normalized_error = _normalize_help_text(captured.err)
    assert "invalid choice: 'standalone-all'" in normalized_error
    assert "{standalone,triage,recovery,local,all}" in normalized_error


@pytest.mark.parametrize(
    ("script_name", "invalid_target", "expected_choices"),
    [
        ("standalone_smoke", "standalone-local", "{summary-utils,shell-tool,replay,live,local,all}"),
        ("session_triage_smoke", "local", "{picker,switcher,both,all}"),
        (
            "session_recovery_smoke",
            "both",
            "{approval,approval-restart,session-state,live-restore,live-restore-denied,all}",
        ),
    ],
)
def test_smoke_wrapper_invalid_choice_errors_show_public_cli_choices(
    script_name: str,
    invalid_target: str,
    expected_choices: str,
    capsys,
) -> None:
    module = _load_script_module(script_name)

    with pytest.raises(SystemExit) as exc_info:
        module.main([invalid_target])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    normalized_error = _normalize_help_text(captured.err)
    assert f"invalid choice: '{invalid_target}'" in normalized_error
    assert expected_choices in normalized_error


@pytest.mark.parametrize(
    ("script_name", "required_snippets"),
    [
        (
            "standalone_smoke",
            [
                "Which standalone smoke surface to run.",
                "default local alias -> summary-utils, shell-tool, replay",
                "standalone_smoke.py replay # single target",
            ],
        ),
        (
            "session_triage_smoke",
            [
                "Which session-triage smoke surface to run.",
                "default both alias -> picker, switcher",
                "session_triage_smoke.py picker # single target",
            ],
        ),
        (
            "session_recovery_smoke",
            [
                "Which recovery smoke surface to run.",
                "default all alias -> approval, approval-restart, session-state, live-restore, live-restore-denied",
                "session_recovery_smoke.py live-restore # single target",
            ],
        ),
        (
            "smoke_matrix",
            [
                "Which smoke bundle or bundle matrix to run.",
                "default local alias -> standalone-local, triage, recovery",
                "smoke_matrix.py standalone # single bundle",
            ],
        ),
    ],
)
def test_smoke_script_main_help_exits_zero_and_prints_expected_text(script_name, required_snippets, capsys) -> None:
    module = _load_script_module(script_name)

    with pytest.raises(SystemExit) as exc_info:
        module.main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    normalized_help = _normalize_help_text(captured.out)
    for snippet in required_snippets:
        assert snippet in normalized_help


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


@pytest.mark.parametrize(
    ("argv", "expected_names", "expected_args"),
    [
        (["standalone"], ["standalone-local"], [()]),
        (["triage"], ["triage"], [()]),
        (["recovery"], ["recovery"], [()]),
    ],
)
def test_smoke_matrix_single_bundle_target_selection(monkeypatch, argv, expected_names, expected_args) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main(argv)

    assert exit_code == 0
    assert seen == {
        "names": expected_names,
        "args": expected_args,
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


def test_smoke_matrix_suppresses_nested_wrapper_summary_footers(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    nested_summary_lines = {
        "standalone-local": "[standalone-smoke] summary: 3/3 targets passed in 1.00s\n",
        "standalone-all": "[standalone-smoke] summary: 4/4 targets passed in 1.25s\n",
        "triage": "[session-triage-smoke] summary: 2/2 targets passed in 1.50s\n",
        "recovery": "[session-recovery-smoke] summary: 5/5 targets passed in 2.00s\n",
    }

    def _run_smoke_target(target, **kwargs):
        output_line_filter = kwargs["output_line_filter"]
        stdout = kwargs["stdout"]
        summary_line = nested_summary_lines[target.name]
        for line in (summary_line, f"{target.name}_check= True\n"):
            if output_line_filter is None or output_line_filter(line):
                print(line, end="", file=stdout)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.25, 2.0, 2.5, 3.0, 3.75, 4.0])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main([])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        "[smoke-matrix] running standalone-local",
        "standalone-local_check= True",
        "[smoke-matrix] standalone-local passed in 0.25s",
        "[smoke-matrix] running triage",
        "triage_check= True",
        "[smoke-matrix] triage passed in 0.50s",
        "[smoke-matrix] running recovery",
        "recovery_check= True",
        "[smoke-matrix] recovery passed in 0.75s",
        "[smoke-matrix] summary: 3/3 bundles passed in 4.00s",
    ]
    assert "[standalone-smoke] summary:" not in stdout.getvalue()
    assert "[session-triage-smoke] summary:" not in stdout.getvalue()
    assert "[session-recovery-smoke] summary:" not in stdout.getvalue()


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


def _render_picker_attention_workspace_shell_outputs(tmp_path: Path) -> dict[str, str]:
    seed_plain_session(tmp_path)
    seed_pending_approval_session(tmp_path)
    seed_workspace_edit_session(
        tmp_path,
        session_id="session-pending-edit",
        prompt="queue the risky edit",
        request_id="approval-0001b",
        tool_name="write_file",
        args={"relative_path": "notes.txt", "overwrite": True},
        approval_prompt="queue edit",
    )
    seed_denied_approval_session(
        tmp_path,
        session_id="session-denied-test",
        prompt="deny the risky test approval",
    )
    seed_approval_restore_focus_scenario(tmp_path)

    aged_turn_time = datetime.now(UTC) - timedelta(days=10)
    seed_shell_test_session(
        tmp_path,
        session_id="session-aged",
        prompt="resume the stale test queue",
        response="ok",
        request_id="approval-aged",
        approval_prompt="resume old tests",
        created_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
        turn_created_at=aged_turn_time.isoformat(),
    )
    set_session_artifact_mtime(SessionArtifactStore(tmp_path, session_id="session-aged"), aged_turn_time)

    seed_shell_failure_session(
        tmp_path,
        session_id="session-failed-test",
        prompt="run the failing test suite",
        response="ok",
    )
    seed_workspace_failure_session(
        tmp_path,
        session_id="session-failed-tool",
        prompt="attempt the failing edit",
        response="ok",
    )
    seed_workspace_inspect_session(tmp_path, session_id="session-tool", prompt="list files", response="ok")
    seed_shell_inspect_session(tmp_path, session_id="session-inspect", prompt="inspect repo", response="ok")

    return {
        "workspace_inspect": render_session_picker(
            tmp_path,
            filter_mode="workspace-inspect",
            sort_mode="attention",
        ),
        "workspace_edit": render_session_picker(
            tmp_path,
            filter_mode="workspace-edit",
            sort_mode="attention",
        ),
        "shell": render_session_picker(tmp_path, filter_mode="shell", sort_mode="attention"),
        "shell_inspect": render_session_picker(
            tmp_path,
            filter_mode="shell-inspect",
            sort_mode="attention",
        ),
        "shell_test": render_session_picker(
            tmp_path,
            filter_mode="shell-test",
            sort_mode="attention",
        ),
    }


def _ranked_session_ids(text: str) -> list[str]:
    session_ids: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip(" >")
        prefix, separator, remainder = stripped.partition(". ")
        if not separator or not prefix.isdigit() or not remainder.startswith("session-"):
            continue
        session_ids.append(remainder.split(" |", 1)[0])
    return session_ids


def test_session_picker_attention_workspace_and_shell_filters_match_smoke_expectations(tmp_path: Path) -> None:
    outputs = _render_picker_attention_workspace_shell_outputs(tmp_path)

    assert matches_workspace_filter_output(
        outputs["workspace_inspect"],
        filter_mode="workspace-inspect",
        sort_mode="attention",
        backlog_line="Workspace backlog: 1 session | lanes: inspect 1",
        focus="inspect",
        required_session_ids=["session-tool"],
        excluded_session_ids=["session-pending", "session-failed-tool"],
        required=["workspace lanes: inspect"],
    )
    assert _ranked_session_ids(outputs["workspace_inspect"]) == ["session-tool"]

    assert matches_workspace_filter_output(
        outputs["workspace_edit"],
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
    assert _ranked_session_ids(outputs["workspace_edit"])[:2] == [
        "session-restored-edit-pending",
        "session-pending",
    ]

    assert matches_shell_filter_output(
        outputs["shell"],
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
    assert _ranked_session_ids(outputs["shell"])[:3] == [
        "session-restored-pending",
        "session-aged",
        "session-pending",
    ]

    assert matches_shell_filter_output(
        outputs["shell_inspect"],
        filter_mode="shell-inspect",
        sort_mode="attention",
        backlog_line="Shell backlog: 2 sessions | lanes: inspect 2, test 1 | overlap: mixed 1 session",
        focus="inspect",
        required_session_ids=["session-pending", "session-inspect"],
        excluded_session_ids=["session-tool", "session-aged", "session-restored-pending"],
    )
    assert _ranked_session_ids(outputs["shell_inspect"]) == ["session-pending", "session-inspect"]
    assert "shell lanes: inspect, test" in outputs["shell_inspect"]

    assert matches_shell_filter_output(
        outputs["shell_test"],
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
    assert _ranked_session_ids(outputs["shell_test"])[:2] == [
        "session-restored-pending",
        "session-aged",
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
