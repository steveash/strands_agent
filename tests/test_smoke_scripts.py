from __future__ import annotations

import hashlib
import json
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
from strands_agent_tui.sessions import SessionArtifactStore, TurnArtifact, render_session_picker
from strands_agent_tui.testing import (
    DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS,
    NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES,
    SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME,
    SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME,
    SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME,
    SESSION_RECOVERY_SMOKE_SELECTION_CASES,
    SESSION_RECOVERY_SMOKE_WRAPPER,
    SESSION_TRIAGE_SMOKE_SELECTION_CASES,
    SESSION_TRIAGE_SMOKE_WRAPPER,
    SMOKE_CLI_DOC_SPECS,
    SMOKE_MATRIX_SELECTION_CASES,
    SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_FIXTURE,
    SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
    SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS,
    SMOKE_MATRIX_WRAPPER,
    SMOKE_SCRIPT_CONTRACT_CASES,
    SMOKE_WRAPPER_CLI_SPECS,
    SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME,
    STANDALONE_DOCS_PARITY_FOLLOW_UP,
    STANDALONE_DOCS_REVIEW_FOLLOW_UP,
    STANDALONE_SMOKE_SELECTION_CASES,
    STANDALONE_SMOKE_WRAPPER,
    SmokeScriptContractCase,
    SmokeWrapperSelectionCase,
    StandaloneFollowUpFailureFixture,
    StandaloneSmokeFailureCase,
    assert_smoke_script_output_matches_contract,
    assert_smoke_script_results_match_contract,
    build_standalone_follow_up_failure_run_smoke_target,
    build_smoke_matrix_review_artifact_location_lines,
    build_smoke_matrix_review_artifact_location_messages,
    build_smoke_matrix_review_metadata_line,
    build_smoke_matrix_review_metadata_payload,
    build_smoke_matrix_public_label_fail_fast_fixture,
    build_smoke_cli_doc_drift_report_payload,
    build_smoke_cli_doc_render_manifest_payload,
    build_smoke_cli_doc_repair_report_payload,
    build_standalone_docs_contract_failure_cases,
    build_standalone_docs_parity_follow_up_failure_cases,
    build_standalone_docs_review_follow_up_failure_cases,
    build_standalone_malformed_contract_failure_cases,
    build_timed_standalone_smoke_failure_pytest_params,
    collect_smoke_cli_readme_diffs,
    diff_bundle_sha256,
    emit_smoke_checks as real_emit_smoke_checks,
    matches_markdown_section,
    matches_public_cli_help,
    matches_public_cli_invalid_choice,
    matches_smoke_cli_doc_parity,
    matches_smoke_cli_help_for_script,
    matches_shell_filter_output,
    matches_workspace_filter_output,
    replace_markdown_section,
    render_smoke_cli_readme_section,
    render_smoke_cli_readme_sections,
    rendered_bundle_sha256,
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
    smoke_cli_doc_spec,
    smoke_cli_doc_spec_id,
    smoke_cli_doc_parser_spec,
    smoke_cli_docs_parity_rerun_hint,
    smoke_script_contract_case_id,
    smoke_wrapper_selection_case_id,
    sha256_text,
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"
README_TEXT = README_PATH.read_text(encoding="utf-8")
ALL_SMOKE_CLI_DOC_SCRIPT_NAMES = tuple(spec.script_name for spec in SMOKE_CLI_DOC_SPECS)


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



def _observe_standalone_smoke_failure(
    monkeypatch,
    *,
    argv: list[str],
    fixture: StandaloneFollowUpFailureFixture,
    elapsed_seconds: float,
    stderr_message: str | None = None,
    exit_code: int = 1,
    output_line_filter=None,
) -> tuple[int, list[str], list[str]]:
    standalone_smoke = _load_script_module("standalone_smoke")

    _run_smoke_target = build_standalone_follow_up_failure_run_smoke_target(
        fixture,
        stderr_message=stderr_message,
        exit_code=exit_code,
        output_line_filter=output_line_filter,
    )

    monkeypatch.setattr("strands_agent_tui.testing.smoke_runner.run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, elapsed_seconds])
    monkeypatch.setattr("strands_agent_tui.testing.smoke_runner.perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    real_run_smoke_targets = standalone_smoke.run_smoke_targets
    monkeypatch.setattr(
        standalone_smoke,
        "run_smoke_targets",
        lambda targets, **kwargs: real_run_smoke_targets(targets, stdout=stdout, stderr=stderr, **kwargs),
    )

    observed_exit_code = standalone_smoke.main(argv)
    return observed_exit_code, stdout.getvalue().splitlines(), stderr.getvalue().splitlines()



def _assert_standalone_smoke_failure(
    monkeypatch,
    *,
    argv: list[str],
    failed_target_name: str,
    stdout_lines: tuple[str, ...] | list[str],
    failed_line: str,
    expected_hint: str,
    passed_count: int,
    total_count: int,
    elapsed_seconds: float,
) -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name=failed_target_name,
        stdout_lines=tuple(stdout_lines),
    )
    assert fixture.failed_line == failed_line

    exit_code, observed_stdout_lines, observed_stderr_lines = _observe_standalone_smoke_failure(
        monkeypatch,
        argv=argv,
        fixture=fixture,
        elapsed_seconds=elapsed_seconds,
    )

    assert exit_code == 1
    assert observed_stdout_lines == list(stdout_lines)
    assert observed_stderr_lines == [
        fixture.failed_fast_message(),
        f"[standalone-smoke] {expected_hint}",
        STANDALONE_SMOKE_WRAPPER.failure_summary_line(
            passed_count=passed_count,
            total_count=total_count,
            elapsed_seconds=elapsed_seconds,
        ),
    ]


def _selected_smoke_cli_doc_script_names(requested_target_name: str | None) -> tuple[str, ...]:
    if requested_target_name in (None, "all"):
        return ALL_SMOKE_CLI_DOC_SCRIPT_NAMES
    return (requested_target_name,)



def _assert_smoke_cli_doc_render_manifest_payload(
    payload: dict[str, object],
    *,
    requested_target_name: str | None,
    markdown: str,
    readme_path: Path,
    output_dir: Path | None,
    manifest_path: Path,
    diff_path: Path | None,
    written_paths: tuple[Path, ...],
    body_only: bool = False,
) -> None:
    diff_sections = collect_smoke_cli_readme_diffs(
        markdown,
        requested_target_name=requested_target_name,
    )
    rendered_sections = tuple(
        (script_name, render_smoke_cli_readme_section(script_name, body_only=body_only))
        for script_name, _diff_lines in diff_sections
    )
    assert payload == build_smoke_cli_doc_render_manifest_payload(
        body_only=body_only,
        requested_target_name=requested_target_name,
        selected_script_names=_selected_smoke_cli_doc_script_names(requested_target_name),
        rendered_sections=rendered_sections,
        written_paths=written_paths,
        readme_path=readme_path,
        output_dir=output_dir,
        manifest_output=manifest_path,
        diff_output=diff_path,
        diff_sections=diff_sections,
    )



def _assert_smoke_cli_doc_drift_report_payload(
    payload: dict[str, object],
    *,
    requested_target_name: str | None,
    markdown: str,
    readme_path: Path,
    include_diff_lines: bool,
    check: bool,
    drifted_readme_path: Path | None = None,
    render_output_dir: Path | None = None,
    render_manifest_path: Path | None = None,
    render_diff_path: Path | None = None,
    bundle_index_path: Path | None = None,
) -> None:
    diff_sections = collect_smoke_cli_readme_diffs(
        markdown,
        requested_target_name=requested_target_name,
    )
    rendered_sections = tuple(
        (script_name, render_smoke_cli_readme_section(script_name))
        for script_name, _diff_lines in diff_sections
    )
    assert payload == build_smoke_cli_doc_drift_report_payload(
        readme_path=readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=_selected_smoke_cli_doc_script_names(requested_target_name),
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        include_diff_lines=include_diff_lines,
        check=check,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )



def _assert_smoke_cli_doc_repair_report_payload(
    payload: dict[str, object],
    *,
    requested_target_name: str | None,
    original_markdown: str,
    repaired_markdown: str,
    readme_path: Path,
    stdout: bool,
    drifted_readme_path: Path | None = None,
    render_output_dir: Path | None = None,
    render_manifest_path: Path | None = None,
    render_diff_path: Path | None = None,
    bundle_index_path: Path | None = None,
) -> None:
    diff_sections = collect_smoke_cli_readme_diffs(
        original_markdown,
        requested_target_name=requested_target_name,
    )
    repaired_script_names = tuple(script_name for script_name, _diff_lines in diff_sections)
    rendered_sections = tuple(
        (script_name, render_smoke_cli_readme_section(script_name))
        for script_name in repaired_script_names
    )
    assert payload == build_smoke_cli_doc_repair_report_payload(
        readme_path=readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=_selected_smoke_cli_doc_script_names(requested_target_name),
        repaired_script_names=repaired_script_names,
        original_markdown=original_markdown,
        repaired_markdown=repaired_markdown,
        rendered_sections=rendered_sections,
        diff_sections=diff_sections,
        stdout=stdout,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )


def _assert_script_help_contains(script_name: str, required_snippets: list[str] | None = None) -> None:
    help_text = _format_script_help(script_name)
    if required_snippets is None:
        assert matches_smoke_cli_help_for_script(help_text, script_name=script_name)
        return
    assert matches_public_cli_help(help_text, required_snippets=required_snippets)


def _assert_script_parser_help_matches_shared_expectations(script_name: str) -> None:
    module = _load_script_module(script_name)
    help_text = " ".join(module.build_parser().format_help().split())

    for snippet in SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME[script_name]:
        assert snippet in help_text


def test_smoke_cli_docs_scripts_build_parsers_from_public_parser_spec_registry() -> None:
    for script_name, parser_spec in SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME.items():
        module = _load_script_module(script_name)
        kwargs = {"readme_path": module.README_PATH} if hasattr(module, "README_PATH") else {}

        assert smoke_cli_doc_parser_spec(script_name) is parser_spec
        assert module.build_parser().format_help() == parser_spec.build_parser(**kwargs).format_help()


def test_smoke_cli_docs_scripts_reject_unknown_public_parser_spec_names() -> None:
    for script_name in SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME:
        module = _load_script_module(script_name)
        unknown_script_name = f"{script_name}_missing"

        assert module.smoke_cli_doc_parser_spec is smoke_cli_doc_parser_spec
        with pytest.raises(
            ValueError,
            match=f"unknown smoke cli doc parser spec {unknown_script_name!r}",
        ):
            module.smoke_cli_doc_parser_spec(unknown_script_name)


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


def test_live_smoke_main_emits_clean_runtime_error_summary_without_traceback(monkeypatch) -> None:
    live_smoke = _load_script_module("live_smoke")

    class _Runtime:
        def run(self, prompt: str):
            assert prompt == "Reply with exactly: live runtime ok"
            raise RuntimeError("OPENAI_API_KEY is required for live runtime mode")

    monkeypatch.setattr(
        live_smoke,
        "load_config",
        lambda: SimpleNamespace(runtime_mode="live", openai_model="stub-model"),
    )
    monkeypatch.setattr(live_smoke, "build_runtime", lambda **_: _Runtime())

    output = StringIO()
    real_emit_smoke_results = live_smoke.emit_smoke_results
    monkeypatch.setattr(
        live_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    with redirect_stdout(output):
        exit_code = live_smoke.main()

    assert exit_code == 1
    assert "Traceback" not in output.getvalue()
    assert output.getvalue().splitlines() == [
        "live_runtime_error: RuntimeError: OPENAI_API_KEY is required for live runtime mode",
        "live_runtime_requested= True",
    ]


def test_profile_config_smoke_reports_effective_profile_summary(monkeypatch) -> None:
    profile_config_smoke = _load_script_module("profile_config_smoke")

    output = StringIO()
    monkeypatch.setattr(
        profile_config_smoke,
        "emit_smoke_checks",
        lambda checks: real_emit_smoke_checks(checks, stdout=output),
    )
    with redirect_stdout(output):
        exit_code = profile_config_smoke.main()

    lines = output.getvalue().splitlines()
    assert exit_code == 0
    assert any(line.startswith("profile: profile smoke") for line in lines)
    assert "runtime_mode: live (cli)" in lines
    assert "openai_model: env-model (env)" in lines
    assert "stale_approval_warning_days: 9 (cli)" in lines
    assert "warning: Unknown profile field ignored: ignored_future_field" in lines
    assert "profile_config_sources= True" in lines
    assert "env_config_sources= True" in lines
    assert "cli_config_sources= True" in lines
    assert "profile_summary_effective_values= True" in lines
    assert "profile_summary_unknown_fields= True" in lines


def test_approval_smoke_emits_timeline_summary_checks(monkeypatch) -> None:
    approval_smoke = _load_script_module("approval_smoke")
    output = StringIO()
    real_emit_smoke_results = approval_smoke.emit_smoke_results
    monkeypatch.setattr(
        approval_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = approval_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=[
            "initial text",
            "initial pending",
            "initial events",
            "initial intervention summaries",
            "after approve text",
            "next pending",
            "after approve events",
            "after approve intervention summaries",
            "after deny text",
            "final pending",
            "after deny events",
            "after deny intervention summaries",
        ],
        check_names=[
            "initial approval schema",
            "initial queue schema",
            "initial target schema",
            "timeline_pending_summary",
            "approved execution schema",
            "approved queue schema",
            "timeline_approved_summary",
            "denied schema",
            "denied queue schema",
            "timeline_denied_summary",
        ],
    )
    assert any(
        "approval pending edit via fake_runtime | queue 1/2 | path notes.txt | next replace_text" in line
        for line in lines
        if line.startswith("initial intervention summaries:")
    )
    assert "initial target schema= True" in lines
    assert "timeline_pending_summary= True" in lines
    assert "timeline_approved_summary= True" in lines
    assert "timeline_denied_summary= True" in lines


def test_timeline_smoke_emits_runtime_and_persistence_summary_checks(monkeypatch) -> None:
    timeline_smoke = _load_script_module("timeline_smoke")
    output = StringIO()
    real_emit_smoke_results = timeline_smoke.emit_smoke_results
    monkeypatch.setattr(
        timeline_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = timeline_smoke.main()
    text = output.getvalue()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=[
            "runtime_timeline_view",
            "persistence_timeline_view",
            "compact_timeline_view",
            "spotlight_timeline_view",
            "latest_timeline_view",
        ],
        check_names=[
            "timeline_runtime_summary",
            "timeline_persistence_summary",
            "timeline_filter_counts",
            "timeline_compact_toggle",
            "timeline_spotlight_focus",
            "timeline_latest_shortcut",
        ],
    )
    assert "timeline_runtime_summary= True" in lines
    assert "timeline_persistence_summary= True" in lines
    assert "timeline_filter_counts= True" in lines
    assert "timeline_compact_toggle= True" in lines
    assert "timeline_spotlight_focus= True" in lines
    assert "timeline_latest_shortcut= True" in lines
    assert "runtime_timeline_view: Event Timeline" in text
    assert "summary: response fake-strands/fake | pending 0" in text
    assert "persistence_timeline_view: Event Timeline" in text
    assert "summary: session state saved | pending 0 | filter runtime | draft 14c" in text
    assert "compact_timeline_view: Event Timeline" in text
    assert "View: detail off | raw off" in text
    assert "spotlight_timeline_view: Event Timeline" in text
    assert "Focus: event 2/4 | spotlight on" in text


def test_session_manifest_smoke_emits_artifact_contract_checks(monkeypatch) -> None:
    session_manifest_smoke = _load_script_module("session_manifest_smoke")
    output = StringIO()
    real_emit_smoke_checks = session_manifest_smoke.emit_smoke_checks
    monkeypatch.setattr(
        session_manifest_smoke,
        "emit_smoke_checks",
        lambda checks: real_emit_smoke_checks(checks, stdout=output),
    )

    with redirect_stdout(output):
        exit_code = session_manifest_smoke.main()
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=[
            "manifest_path",
            "manifest_turn_count",
            "manifest_tools",
            "manifest_pending_after_save",
            "manifest_pending_after_clear",
        ],
        check_names=[
            "session_manifest_written",
            "session_manifest_metadata",
            "session_manifest_tool_counts",
            "session_manifest_pending_state",
        ],
    )
    assert any(line.endswith("manifest.json") for line in lines if line.startswith("manifest_path: "))
    assert "manifest_turn_count: 1" in lines
    assert "manifest_pending_after_save: 1" in lines
    assert "manifest_pending_after_clear: 0" in lines
    assert "session_manifest_written= True" in lines
    assert "session_manifest_metadata= True" in lines
    assert "session_manifest_tool_counts= True" in lines
    assert "session_manifest_pending_state= True" in lines


def test_session_manifest_summary_script_renders_text_and_json(tmp_path: Path) -> None:
    session_manifest_summary = _load_script_module("session_manifest_summary")
    store = SessionArtifactStore(tmp_path, session_id="summary-script-session")
    store.append_turn(
        TurnArtifact(
            prompt="inspect summary script",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event("prompt_received", "Prompt accepted", "inspect summary script"),
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files"},
                ),
            ],
            response_metadata={
                "model": "gpt-4o-mini",
                "workspace_root": str(tmp_path),
                "config_sources": {
                    "runtime_mode": "default",
                    "openai_model": "default",
                    "workspace_root": "cli",
                },
            },
        )
    )
    store.manifest_path.unlink()

    text_output = StringIO()
    with redirect_stdout(text_output):
        text_exit_code = session_manifest_summary.main([str(store.session_dir)])

    json_output = StringIO()
    with redirect_stdout(json_output):
        json_exit_code = session_manifest_summary.main([str(store.session_dir), "--json"])

    assert text_exit_code == 0
    assert json_exit_code == 0
    assert store.manifest_path.exists()
    text_lines = text_output.getvalue().splitlines()
    payload = json.loads(json_output.getvalue())

    assert "session: summary-script-session" in text_lines
    assert "top tools: list_files=1" in text_lines
    assert "sources: runtime=default, model=default, workspace=cli" in text_lines
    assert payload["session_id"] == "summary-script-session"
    assert payload["top_tools"] == [["list_files", 1]]


def test_session_manifest_summary_script_renders_recent_collection(tmp_path: Path) -> None:
    session_manifest_summary = _load_script_module("session_manifest_summary")
    first_store = SessionArtifactStore(tmp_path, session_id="summary-recent-a")
    first_store.append_turn(
        TurnArtifact(
            prompt="first saved task",
            response="done",
            provider="fake-strands",
            mode="fake",
            events=[
                runtime_event(
                    "tool_finished",
                    "list_files",
                    "Finished listing files",
                    data={"tool_name": "list_files"},
                ),
            ],
            response_metadata={"model": "gpt-4o-mini", "workspace_root": str(tmp_path)},
            created_at="2026-06-19T10:00:00+00:00",
        )
    )
    latest_store = SessionArtifactStore(tmp_path, session_id="summary-recent-b")
    latest_store.append_turn(
        TurnArtifact(
            prompt="latest saved task",
            response="done",
            provider="strands",
            mode="live",
            events=[
                runtime_event(
                    "tool_finished",
                    "read_file",
                    "Finished reading file",
                    data={"tool_name": "read_file"},
                ),
            ],
            response_metadata={"model": "gpt-4.1-mini", "workspace_root": str(tmp_path)},
            created_at="2026-06-20T10:00:00+00:00",
        )
    )

    text_output = StringIO()
    with redirect_stdout(text_output):
        text_exit_code = session_manifest_summary.main([str(tmp_path), "--recent", "2"])

    json_output = StringIO()
    with redirect_stdout(json_output):
        json_exit_code = session_manifest_summary.main([str(tmp_path), "--recent", "1", "--json"])

    assert text_exit_code == 0
    assert json_exit_code == 0
    text_lines = text_output.getvalue().splitlines()
    payload = json.loads(json_output.getvalue())

    assert "sessions: 2 | turns: 2 | errors: 0 | pending approvals: 0 | workspaces: 1" in text_lines
    assert "top tools: list_files=1, read_file=1" in text_lines
    assert any(line.startswith("1. summary-recent-b | 2026-06-20T10:00:00+00:00") for line in text_lines)
    assert any(line.startswith("2. summary-recent-a | 2026-06-19T10:00:00+00:00") for line in text_lines)
    assert payload["session_count"] == 1
    assert payload["sessions"][0]["session_id"] == "summary-recent-b"


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
        detail_names=[
            "restored_event_filter",
            "restored_view",
            "restored_draft",
            "restored_timeline_view",
            "restored_timeline_focus",
            "latest_visible_event",
            "recent_session_restore_line",
            "recent_session_restore_preview",
        ],
        check_names=[
            "session_state_restored_event_filter",
            "session_state_restored_view",
            "session_state_restored_draft",
            "session_state_restored_timeline_view",
            "session_state_restored_timeline_focus",
            "session_state_latest_visible_event",
            "session_state_recent_session_restore_badges",
            "session_state_recent_session_restore_preview",
        ],
    )
    assert "restored_timeline_view: detail off / raw off" in lines
    assert "session_state_restored_timeline_view= True" in lines
    assert "restored_timeline_focus: event 4/4, spotlight" in lines
    assert "session_state_recent_session_restore_badges= True" in lines


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
    "case",
    STANDALONE_SMOKE_SELECTION_CASES,
    ids=smoke_wrapper_selection_case_id,
)
def test_standalone_smoke_selects_expected_targets(
    monkeypatch, case: SmokeWrapperSelectionCase
) -> None:
    standalone_smoke = _load_script_module("standalone_smoke")

    seen = {}

    def _run_smoke_targets(targets, **_kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        return 0

    monkeypatch.setattr(standalone_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = standalone_smoke.main(list(case.argv))

    assert exit_code == 0
    assert seen == {
        "names": list(case.expected_target_names),
        "args": [() for _ in case.expected_target_names],
    }


@pytest.mark.parametrize(
    ("script_name", "runner_name"),
    [
        (case.script_name, case.runner_name)
        for case in DOCS_REVIEW_MATRIX_SMOKE_SCRIPT_CONTRACTS
    ],
)
def test_docs_review_matrix_smokes_reject_invalid_output_stream(script_name: str, runner_name: str) -> None:
    module = _load_script_module(script_name)

    with pytest.raises(ValueError, match="output_stream must be 'stdout' or 'stderr', got 'invalid'"):
        getattr(module, runner_name)(output_stream="invalid")


def test_docs_review_matrix_smokes_import_shared_failure_defaults() -> None:
    order_smoke = _load_script_module("smoke_matrix_all_review_order_smoke")
    missing_api_key_smoke = _load_script_module("smoke_matrix_all_review_missing_api_key_smoke")
    docs_review_hint_smoke = _load_script_module("smoke_matrix_docs_review_hint_smoke")

    assert (
        order_smoke.SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS
        is SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS
    )
    assert (
        missing_api_key_smoke.SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS
        is SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS
    )
    assert (
        docs_review_hint_smoke.SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS
        is SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS
    )


@pytest.mark.parametrize(
    "case",
    SMOKE_SCRIPT_CONTRACT_CASES,
    ids=smoke_script_contract_case_id,
)
def test_smoke_scripts_emit_expected_contracts(
    case: SmokeScriptContractCase,
    capsys,
) -> None:
    smoke_script = _load_script_module(case.script_name)

    exit_code = smoke_script.main([])

    assert exit_code == 0
    lines = capsys.readouterr().out.splitlines()
    assert_smoke_script_output_matches_contract(lines, case)


@pytest.mark.parametrize(
    "case",
    SMOKE_SCRIPT_CONTRACT_CASES,
    ids=smoke_script_contract_case_id,
)
def test_smoke_script_runner_functions_return_expected_contract_results(
    case: SmokeScriptContractCase,
) -> None:
    smoke_script = _load_script_module(case.script_name)

    results = getattr(smoke_script, case.runner_name)()

    assert_smoke_script_results_match_contract(results, case)


@pytest.mark.parametrize(
    "case",
    SESSION_TRIAGE_SMOKE_SELECTION_CASES,
    ids=smoke_wrapper_selection_case_id,
)
def test_session_triage_smoke_selects_expected_targets(
    monkeypatch, case: SmokeWrapperSelectionCase
) -> None:
    session_triage_smoke = _load_script_module("session_triage_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        seen["wrapper_metadata"] = kwargs.get("wrapper_metadata")
        return 0

    monkeypatch.setattr(session_triage_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = session_triage_smoke.main(list(case.argv))

    assert exit_code == 0
    assert seen == {
        "names": list(case.expected_target_names),
        "args": [() for _ in case.expected_target_names],
        "wrapper_metadata": SESSION_TRIAGE_SMOKE_WRAPPER,
    }


@pytest.mark.parametrize(
    "case",
    SESSION_RECOVERY_SMOKE_SELECTION_CASES,
    ids=smoke_wrapper_selection_case_id,
)
def test_session_recovery_smoke_selects_expected_targets(
    monkeypatch, case: SmokeWrapperSelectionCase
) -> None:
    session_recovery_smoke = _load_script_module("session_recovery_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["args"] = [target.args for target in targets]
        seen["wrapper_metadata"] = kwargs.get("wrapper_metadata")
        return 0

    monkeypatch.setattr(session_recovery_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = session_recovery_smoke.main(list(case.argv))

    assert exit_code == 0
    assert seen == {
        "names": list(case.expected_target_names),
        "args": [() for _ in case.expected_target_names],
        "wrapper_metadata": SESSION_RECOVERY_SMOKE_WRAPPER,
    }


def test_standalone_smoke_passes_shared_wrapper_metadata(monkeypatch) -> None:
    standalone_smoke = _load_script_module("standalone_smoke")

    seen = {}

    def _run_smoke_targets(targets, **kwargs):
        seen["names"] = [target.name for target in targets]
        seen["wrapper_metadata"] = kwargs.get("wrapper_metadata")
        return 0

    monkeypatch.setattr(standalone_smoke, "run_smoke_targets", _run_smoke_targets)

    exit_code = standalone_smoke.main(["summary-utils"])

    assert exit_code == 0
    assert seen == {
        "names": ["summary-utils"],
        "wrapper_metadata": STANDALONE_SMOKE_WRAPPER,
    }


def test_standalone_smoke_all_failure_emits_live_runtime_export_hint(monkeypatch) -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="live",
        stdout_lines=(
            "provider=fake-strands mode=fake",
            "live_runtime_requested= False",
        ),
    )

    exit_code, observed_stdout_lines, observed_stderr_lines = _observe_standalone_smoke_failure(
        monkeypatch,
        argv=["all"],
        fixture=fixture,
        elapsed_seconds=2.4,
        output_line_filter=lambda _line: False,
    )

    assert exit_code == 1
    assert observed_stdout_lines == []
    assert observed_stderr_lines == [
        fixture.failed_fast_message(),
        (
            "[standalone-smoke] hint: `standalone_smoke.py all` includes the live smoke target; "
            "export `STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
            "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
        ),
        STANDALONE_SMOKE_WRAPPER.failure_summary_line(passed_count=6, total_count=7, elapsed_seconds=2.4),
    ]



def test_standalone_smoke_live_failure_emits_missing_api_key_hint(monkeypatch) -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="live",
        stdout_lines=(
            "live_runtime_error: RuntimeError: OPENAI_API_KEY is required for live runtime mode",
            "live_runtime_requested= True",
        ),
    )

    exit_code, observed_stdout_lines, observed_stderr_lines = _observe_standalone_smoke_failure(
        monkeypatch,
        argv=["live"],
        fixture=fixture,
        elapsed_seconds=1.5,
        stderr_message=fixture.exited_with_status_message(1),
    )

    assert exit_code == 1
    assert observed_stdout_lines == [
        "live_runtime_error: RuntimeError: OPENAI_API_KEY is required for live runtime mode",
        "live_runtime_requested= True",
    ]
    assert observed_stderr_lines == [
        fixture.exited_with_status_message(1),
        (
            "[standalone-smoke] hint: `standalone_smoke.py live` reached the live runtime, but "
            "`OPENAI_API_KEY` was missing; export `OPENAI_API_KEY` "
            "(and optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
        ),
        STANDALONE_SMOKE_WRAPPER.failure_summary_line(passed_count=0, total_count=1, elapsed_seconds=1.5),
    ]


@pytest.mark.parametrize(
    ("failure_case", "elapsed_seconds"),
    build_timed_standalone_smoke_failure_pytest_params(
        build_standalone_docs_parity_follow_up_failure_cases(
            requested_target_names=STANDALONE_DOCS_PARITY_FOLLOW_UP.default_requested_target_names,
        ),
        first_elapsed_seconds=1.6,
        requested_target_name_id_prefix="default-",
    ),
)
def test_standalone_smoke_default_local_docs_parity_failure_emits_docs_parity_only_hint(
    monkeypatch,
    failure_case: StandaloneSmokeFailureCase,
    elapsed_seconds: float,
) -> None:
    _assert_standalone_smoke_failure(
        monkeypatch,
        argv=[],
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
        failed_line=failure_case.failed_line,
        expected_hint=failure_case.expected_hint,
        passed_count=failure_case.passed_count,
        total_count=failure_case.total_count,
        elapsed_seconds=elapsed_seconds,
    )


@pytest.mark.parametrize(
    ("failure_case", "elapsed_seconds"),
    build_timed_standalone_smoke_failure_pytest_params(
        build_standalone_docs_parity_follow_up_failure_cases(
            requested_target_names=STANDALONE_DOCS_PARITY_FOLLOW_UP.docs_review_requested_target_names,
        ),
        first_elapsed_seconds=1.6,
    ),
)
def test_standalone_smoke_docs_focused_docs_parity_failure_emits_docs_parity_only_hint(
    monkeypatch,
    failure_case: StandaloneSmokeFailureCase,
    elapsed_seconds: float,
) -> None:
    _assert_standalone_smoke_failure(
        monkeypatch,
        argv=[failure_case.requested_target_name],
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
        failed_line=failure_case.failed_line,
        expected_hint=failure_case.expected_hint,
        passed_count=failure_case.passed_count,
        total_count=failure_case.total_count,
        elapsed_seconds=elapsed_seconds,
    )


@pytest.mark.parametrize(
    ("failure_case", "elapsed_seconds"),
    build_timed_standalone_smoke_failure_pytest_params(
        build_standalone_malformed_contract_failure_cases(
            requested_target_name="contract-negative",
        ),
        first_elapsed_seconds=1.4,
        elapsed_step_seconds=1.2,
        include_requested_target_name_in_id=False,
    ),
)
def test_standalone_smoke_contract_negative_failure_emits_targeted_follow_up_hint(
    monkeypatch,
    failure_case: StandaloneSmokeFailureCase,
    elapsed_seconds: float,
) -> None:
    _assert_standalone_smoke_failure(
        monkeypatch,
        argv=[failure_case.requested_target_name],
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
        failed_line=failure_case.failed_line,
        expected_hint=failure_case.expected_hint,
        passed_count=failure_case.passed_count,
        total_count=failure_case.total_count,
        elapsed_seconds=elapsed_seconds,
    )


@pytest.mark.parametrize(
    ("failure_case", "elapsed_seconds"),
    build_timed_standalone_smoke_failure_pytest_params(
        build_standalone_docs_contract_failure_cases(),
        first_elapsed_seconds=1.8,
        include_requested_target_name_in_id=False,
    ),
)
def test_standalone_smoke_docs_contract_failure_emits_expected_follow_up_hint(
    monkeypatch,
    failure_case: StandaloneSmokeFailureCase,
    elapsed_seconds: float,
) -> None:
    _assert_standalone_smoke_failure(
        monkeypatch,
        argv=[failure_case.requested_target_name],
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
        failed_line=failure_case.failed_line,
        expected_hint=failure_case.expected_hint,
        passed_count=failure_case.passed_count,
        total_count=failure_case.total_count,
        elapsed_seconds=elapsed_seconds,
    )


@pytest.mark.parametrize(
    ("failure_case", "elapsed_seconds"),
    build_timed_standalone_smoke_failure_pytest_params(
        build_standalone_docs_review_follow_up_failure_cases(
            requested_target_names=STANDALONE_DOCS_REVIEW_FOLLOW_UP.alias_requested_target_names
        ),
        first_elapsed_seconds=2.5,
    ),
)
def test_standalone_smoke_docs_review_alias_failure_emits_docs_review_only_hint(
    monkeypatch,
    failure_case,
    elapsed_seconds: float,
) -> None:
    _assert_standalone_smoke_failure(
        monkeypatch,
        argv=[failure_case.requested_target_name],
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
        failed_line=failure_case.failed_line,
        expected_hint=failure_case.expected_hint,
        passed_count=failure_case.passed_count,
        total_count=failure_case.total_count,
        elapsed_seconds=elapsed_seconds,
    )


def test_smoke_cli_docs_artifacts_smoke_build_parser_lists_public_targets_and_output_dir() -> None:
    _assert_script_parser_help_matches_shared_expectations("smoke_cli_docs_artifacts_smoke")



def test_smoke_cli_docs_artifacts_smoke_reports_expected_contract_lines(monkeypatch) -> None:
    smoke_cli_docs_artifacts_smoke = _load_script_module("smoke_cli_docs_artifacts_smoke")
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_artifacts_smoke.emit_smoke_results
    monkeypatch.setattr(
        smoke_cli_docs_artifacts_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = smoke_cli_docs_artifacts_smoke.main([])

    assert exit_code == 0
    lines = output.getvalue().splitlines()
    _assert_mixed_smoke_result_contract(
        lines,
        detail_names=[
            "requested_target",
            "selected_targets",
            "artifact_root",
            "source_readme_path",
            "drifted_readme_path",
            "render_output_dir",
            "render_manifest_path",
            "render_diff_path",
            "fix_check_json_path",
            "fix_repair_json_path",
            "fix_post_check_json_path",
            "bundle_index_path",
            "render_stdout",
            "render_manifest_drift_count",
            "render_manifest_summary",
            "render_manifest_diff_stats",
            "fix_check_stdout",
            "fix_repair_stdout",
            "fix_post_check_stdout",
        ],
        check_names=[
            "render_exit",
            "render_manifest_payload",
            "render_outputs_written",
            "fix_check_exit",
            "fix_check_payload",
            "fix_repair_exit",
            "fix_repair_payload",
            "fix_repair_applied",
            "fix_post_check_exit",
            "fix_post_check_payload",
            "bundle_index_written",
            "bundle_index_payload",
        ],
    )
    assert "requested_target: standalone_smoke" in lines
    assert "selected_targets: standalone_smoke" in lines
    assert any(line.startswith("artifact_root: ") for line in lines)
    assert any(line.startswith("source_readme_path: ") for line in lines)
    assert any(line.startswith("drifted_readme_path: ") for line in lines)
    assert any(line.startswith("render_output_dir: ") for line in lines)
    assert any(line.startswith("render_manifest_path: ") for line in lines)
    assert any(line.startswith("render_diff_path: ") for line in lines)
    assert any(line.startswith("fix_check_json_path: ") for line in lines)
    assert any(line.startswith("fix_repair_json_path: ") for line in lines)
    assert any(line.startswith("fix_post_check_json_path: ") for line in lines)
    assert any(line.startswith("bundle_index_path: ") for line in lines)
    assert "render_manifest_drift_count: 1" in lines
    assert "render_manifest_summary: ### Standalone local smoke bundle" in lines
    assert any(line.startswith("render_manifest_diff_stats: {'added_line_count': ") for line in lines)
    assert any("smoke README drift detected in 1 section(s)" in line for line in lines if line.startswith("fix_check_stdout: "))
    assert any(line.startswith("fix_repair_stdout: repaired 1 smoke README section(s) in ") for line in lines)
    assert any(line.startswith("fix_post_check_stdout: smoke README already up to date: ") for line in lines)



def test_smoke_cli_docs_artifacts_smoke_supports_nondefault_target_and_persisted_output_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    smoke_cli_docs_artifacts_smoke = _load_script_module("smoke_cli_docs_artifacts_smoke")
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_artifacts_smoke.emit_smoke_results
    monkeypatch.setattr(
        smoke_cli_docs_artifacts_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    artifact_root = tmp_path / "artifacts"
    exit_code = smoke_cli_docs_artifacts_smoke.main(["smoke_matrix", "--output-dir", str(artifact_root)])

    assert exit_code == 0
    lines = output.getvalue().splitlines()
    assert "requested_target: smoke_matrix" in lines
    assert "selected_targets: smoke_matrix" in lines
    assert f"artifact_root: {artifact_root}" in lines
    assert "render_manifest_drift_count: 1" in lines
    assert "render_manifest_summary: ### Full local smoke matrix" in lines
    assert (artifact_root / "README-drifted.md").exists()
    assert (artifact_root / "rendered" / "smoke_matrix.md").exists()
    assert (artifact_root / "render-manifest.json").exists()
    assert (artifact_root / "render-review.patch").exists()
    assert (artifact_root / "fix-check.json").exists()
    assert (artifact_root / "fix-repair.json").exists()
    assert (artifact_root / "fix-post-check.json").exists()
    bundle_index_path = artifact_root / "bundle-index.json"
    assert bundle_index_path.exists()
    bundle_index_payload = json.loads(bundle_index_path.read_text(encoding="utf-8"))
    assert bundle_index_payload["requested_target_name"] == "smoke_matrix"
    assert bundle_index_payload["selected_script_names"] == ["smoke_matrix"]
    assert bundle_index_payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()
    assert bundle_index_payload["artifact_paths"]["bundle_index_path"] == str(bundle_index_path)
    assert bundle_index_payload["checks"]["render_exit"] is True
    assert bundle_index_payload["details"]["bundle_index_path"] == str(bundle_index_path)
    fix_check_payload = json.loads((artifact_root / "fix-check.json").read_text(encoding="utf-8"))
    fix_repair_payload = json.loads((artifact_root / "fix-repair.json").read_text(encoding="utf-8"))
    fix_post_check_payload = json.loads((artifact_root / "fix-post-check.json").read_text(encoding="utf-8"))
    for payload in (fix_check_payload, fix_repair_payload, fix_post_check_payload):
        assert payload["render_output_dir"] == str(artifact_root / "rendered")
        assert payload["render_manifest_path"] == str(artifact_root / "render-manifest.json")
        assert payload["render_diff_path"] == str(artifact_root / "render-review.patch")


def test_smoke_cli_docs_artifacts_smoke_supports_custom_readme_and_explicit_artifact_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    smoke_cli_docs_artifacts_smoke = _load_script_module("smoke_cli_docs_artifacts_smoke")
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_artifacts_smoke.emit_smoke_results
    monkeypatch.setattr(
        smoke_cli_docs_artifacts_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    readme_path = tmp_path / "custom" / "README-copy.md"
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(README_TEXT, encoding="utf-8")

    output_root = tmp_path / "bundle"
    drifted_readme_path = output_root / "fixtures" / "README-contract.md"
    render_output_dir = output_root / "rendered-sections"
    render_manifest_path = output_root / "review" / "manifest.json"
    render_diff_path = output_root / "review" / "diff.patch"
    fix_check_json_path = output_root / "review" / "fix-check.json"
    fix_repair_json_path = output_root / "review" / "fix-repair.json"
    fix_post_check_json_path = output_root / "review" / "fix-post-check.json"
    bundle_index_path = output_root / "review" / "bundle-index.json"

    exit_code = smoke_cli_docs_artifacts_smoke.main(
        [
            "session_triage_smoke",
            "--readme-path",
            str(readme_path),
            "--output-dir",
            str(output_root),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
            "--fix-check-json-path",
            str(fix_check_json_path),
            "--fix-repair-json-path",
            str(fix_repair_json_path),
            "--fix-post-check-json-path",
            str(fix_post_check_json_path),
            "--bundle-index-path",
            str(bundle_index_path),
        ]
    )

    assert exit_code == 0
    lines = output.getvalue().splitlines()
    assert "requested_target: session_triage_smoke" in lines
    assert "selected_targets: session_triage_smoke" in lines
    assert f"artifact_root: {output_root}" in lines
    assert f"source_readme_path: {readme_path}" in lines
    assert f"drifted_readme_path: {drifted_readme_path}" in lines
    assert f"render_output_dir: {render_output_dir}" in lines
    assert f"render_manifest_path: {render_manifest_path}" in lines
    assert f"render_diff_path: {render_diff_path}" in lines
    assert f"fix_check_json_path: {fix_check_json_path}" in lines
    assert f"fix_repair_json_path: {fix_repair_json_path}" in lines
    assert f"fix_post_check_json_path: {fix_post_check_json_path}" in lines
    assert f"bundle_index_path: {bundle_index_path}" in lines
    assert "render_manifest_summary: ### Session triage smoke bundle" in lines
    assert drifted_readme_path.exists()
    assert (render_output_dir / "session_triage_smoke.md").exists()
    assert render_manifest_path.exists()
    assert render_diff_path.exists()
    assert fix_check_json_path.exists()
    assert fix_repair_json_path.exists()
    assert fix_post_check_json_path.exists()
    assert bundle_index_path.exists()
    bundle_index_payload = json.loads(bundle_index_path.read_text(encoding="utf-8"))
    assert bundle_index_payload["requested_target_name"] == "session_triage_smoke"
    assert bundle_index_payload["selected_script_names"] == ["session_triage_smoke"]
    assert bundle_index_payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()
    assert bundle_index_payload["artifact_paths"]["source_readme_path"] == str(readme_path)
    assert bundle_index_payload["artifact_paths"]["bundle_index_path"] == str(bundle_index_path)
    assert bundle_index_payload["checks"]["render_exit"] is True
    assert bundle_index_payload["details"]["bundle_index_path"] == str(bundle_index_path)
    fix_check_payload = json.loads(fix_check_json_path.read_text(encoding="utf-8"))
    fix_repair_payload = json.loads(fix_repair_json_path.read_text(encoding="utf-8"))
    fix_post_check_payload = json.loads(fix_post_check_json_path.read_text(encoding="utf-8"))
    for payload in (fix_check_payload, fix_repair_payload, fix_post_check_payload):
        assert payload["drifted_readme_path"] == str(drifted_readme_path)
        assert payload["bundle_index_path"] == str(bundle_index_path)
        assert payload["render_output_dir"] == str(render_output_dir)
        assert payload["render_manifest_path"] == str(render_manifest_path)
        assert payload["render_diff_path"] == str(render_diff_path)



def test_smoke_cli_docs_artifacts_smoke_invalid_choice_errors_show_public_cli_choices(capsys) -> None:
    smoke_cli_docs_artifacts_smoke = _load_script_module("smoke_cli_docs_artifacts_smoke")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_artifacts_smoke.main(["docs"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target="docs",
        expected_choices=SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[
            "smoke_cli_docs_artifacts_smoke"
        ],
    )


def test_smoke_cli_doc_spec_id_returns_script_name() -> None:
    assert [smoke_cli_doc_spec_id(spec) for spec in SMOKE_CLI_DOC_SPECS] == [
        spec.script_name for spec in SMOKE_CLI_DOC_SPECS
    ]


@pytest.mark.parametrize("doc_spec", SMOKE_CLI_DOC_SPECS, ids=smoke_cli_doc_spec_id)
def test_smoke_wrapper_help_and_readme_docs_stay_in_sync(doc_spec) -> None:
    assert matches_smoke_cli_doc_parity(
        script_name=doc_spec.script_name,
        help_text=_format_script_help(doc_spec.script_name),
        markdown=README_TEXT,
    )


def test_smoke_cli_docs_smoke_build_parser_lists_public_targets_and_examples() -> None:
    _assert_script_parser_help_matches_shared_expectations("smoke_cli_docs_smoke")


def test_smoke_cli_docs_smoke_reports_doc_parity_for_all_wrappers(monkeypatch) -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_smoke.emit_smoke_results
    monkeypatch.setattr(
        smoke_cli_docs_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = smoke_cli_docs_smoke.main([])
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    assert smoke_cli_docs_smoke.DEFAULT_TARGET_NAMES == [
        doc_spec.script_name for doc_spec in SMOKE_CLI_DOC_SPECS
    ]
    for doc_spec in SMOKE_CLI_DOC_SPECS:
        prefix = doc_spec.script_name
        assert (
            f"{prefix}_diagnostic: help ok; README {doc_spec.readme_section_heading!r} ok"
            in lines
        )
        assert f"{prefix}_help_missing: none" in lines
        assert f"{prefix}_readme_missing: none" in lines
        assert f"{prefix}_readme_diff: none" in lines
        assert f"{prefix}_help= True" in lines
        assert f"{prefix}_readme= True" in lines
        assert f"{prefix}_doc_parity= True" in lines


def test_smoke_cli_docs_smoke_supports_single_wrapper_target(monkeypatch) -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_smoke.emit_smoke_results
    monkeypatch.setattr(
        smoke_cli_docs_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = smoke_cli_docs_smoke.main(["standalone_smoke"])
    lines = output.getvalue().splitlines()

    assert exit_code == 0
    assert all(line.startswith("standalone_smoke_") for line in lines)
    assert len(lines) == 7
    assert "standalone_smoke_readme_diff: none" in lines
    assert "standalone_smoke_doc_parity= True" in lines


def test_smoke_cli_docs_smoke_reports_surface_diagnostics_for_readme_drift() -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    broken_markdown = README_TEXT.replace(
        standalone_spec.readme_required_snippets[4],
        "missing standalone docs snippet",
        1,
    )

    results = dict(
        smoke_cli_docs_smoke.run_smoke_cli_docs_smoke(
            markdown=broken_markdown,
            requested_target_name="standalone_smoke",
        )
    )

    assert set(results) == {
        "rerun_hint",
        "standalone_smoke_diagnostic",
        "standalone_smoke_help_missing",
        "standalone_smoke_readme_missing",
        "standalone_smoke_readme_diff",
        "standalone_smoke_help",
        "standalone_smoke_readme",
        "standalone_smoke_doc_parity",
    }
    assert results["standalone_smoke_diagnostic"].startswith(
        f"help ok; README {standalone_spec.readme_section_heading!r} missing:"
    )
    assert standalone_spec.readme_required_snippets[4] in results["standalone_smoke_diagnostic"]
    assert results["standalone_smoke_readme_diff"].startswith("--- expected | +++ README | @@ ")
    assert results["standalone_smoke_help"] is True
    assert results["standalone_smoke_readme"] is False
    assert results["standalone_smoke_doc_parity"] is False
    assert results["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()


def test_smoke_cli_docs_smoke_emits_docs_parity_rerun_hint_for_failures(monkeypatch) -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    broken_markdown = README_TEXT.replace(
        standalone_spec.readme_required_snippets[4],
        "missing standalone docs snippet",
        1,
    )
    output = StringIO()
    real_emit_smoke_results = smoke_cli_docs_smoke.emit_smoke_results
    monkeypatch.setattr(smoke_cli_docs_smoke, "load_readme_text", lambda: broken_markdown)
    monkeypatch.setattr(
        smoke_cli_docs_smoke,
        "emit_smoke_results",
        lambda results: real_emit_smoke_results(results, stdout=output),
    )

    exit_code = smoke_cli_docs_smoke.main(["standalone_smoke"])
    lines = output.getvalue().splitlines()

    assert exit_code == 1
    assert any(
        line.startswith(
            "standalone_smoke_diagnostic: help ok; README 'Standalone local smoke bundle' missing:"
        )
        for line in lines
    )
    assert any(
        line.startswith("standalone_smoke_readme_diff: --- expected | +++ README | @@ ") for line in lines
    )
    assert f"rerun_hint: {smoke_cli_docs_parity_rerun_hint()}" in lines
    assert lines.index(f"rerun_hint: {smoke_cli_docs_parity_rerun_hint()}") < lines.index(
        "standalone_smoke_doc_parity= False"
    )
    assert "standalone_smoke_help= True" in lines
    assert "standalone_smoke_readme= False" in lines
    assert "standalone_smoke_doc_parity= False" in lines



def test_smoke_cli_docs_smoke_invalid_choice_errors_show_public_cli_choices(capsys) -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_smoke.main(["docs"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target="docs",
        expected_choices=SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[
            "smoke_cli_docs_smoke"
        ],
    )



def test_smoke_cli_docs_render_build_parser_lists_public_targets_examples_and_flags() -> None:
    _assert_script_parser_help_matches_shared_expectations("smoke_cli_docs_render")



def test_smoke_cli_docs_render_supports_single_wrapper_body_preview(capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")

    exit_code = smoke_cli_docs_render.main(["standalone_smoke", "--body-only"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == render_smoke_cli_readme_section("standalone_smoke", body_only=True) + "\n"



def test_smoke_cli_docs_render_exports_selected_sections(tmp_path, capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")

    exit_code = smoke_cli_docs_render.main(["all", "--output-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    rendered_sections = render_smoke_cli_readme_sections(requested_target_name="all")
    output_lines = captured.out.splitlines()
    assert output_lines[-1] == (
        f"wrote {len(rendered_sections)} rendered smoke README sections to {tmp_path}"
    )
    for script_name, text in rendered_sections:
        path = tmp_path / f"{script_name}.md"
        assert str(path) in output_lines
        assert path.read_text(encoding="utf-8") == text + "\n"


def test_smoke_cli_docs_render_drift_only_prints_only_drifted_sections(tmp_path, capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_render.main(
        ["all", "--drift-only", "--readme-path", str(readme_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == render_smoke_cli_readme_section("standalone_smoke") + "\n"


def test_smoke_cli_docs_render_drift_only_exports_only_drifted_sections(tmp_path, capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    exit_code = smoke_cli_docs_render.main(
        [
            "all",
            "--drift-only",
            "--readme-path",
            str(readme_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    output_lines = captured.out.splitlines()
    expected_path = output_dir / "standalone_smoke.md"
    assert output_lines == [
        str(expected_path),
        f"wrote 1 rendered smoke README sections to {output_dir}",
    ]
    assert expected_path.read_text(encoding="utf-8") == render_smoke_cli_readme_section("standalone_smoke") + "\n"
    assert not (output_dir / "session_triage_smoke.md").exists()


def test_smoke_cli_docs_render_drift_only_review_artifacts_write_manifest_and_diff_outputs(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    output_dir = tmp_path / "rendered"
    manifest_path = tmp_path / "artifacts" / "smoke-cli-docs-preview.json"
    diff_path = tmp_path / "artifacts" / "smoke-cli-docs-review.patch"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_render.main(
        [
            "all",
            "--drift-only",
            "--readme-path",
            str(readme_path),
            "--output-dir",
            str(output_dir),
            "--manifest-output",
            str(manifest_path),
            "--diff-output",
            str(diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    expected_path = output_dir / "standalone_smoke.md"
    assert captured.out.splitlines() == [
        str(expected_path),
        f"wrote 1 rendered smoke README sections to {output_dir}",
    ]
    rendered_text = render_smoke_cli_readme_section("standalone_smoke")
    assert expected_path.read_text(encoding="utf-8") == rendered_text + "\n"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_render_manifest_payload(
        manifest_payload,
        requested_target_name="all",
        markdown=drifted_markdown,
        readme_path=readme_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        diff_path=diff_path,
        written_paths=(expected_path,),
    )
    diff_text = diff_path.read_text(encoding="utf-8")
    assert diff_text.startswith("### standalone_smoke\n--- expected\n+++ README\n@@ ")
    assert diff_text.endswith("\n")


def test_smoke_cli_docs_render_drift_only_review_artifacts_can_report_up_to_date_readme(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")
    readme_path = tmp_path / "README.md"
    manifest_path = tmp_path / "artifacts" / "smoke-cli-docs-preview.json"
    diff_path = tmp_path / "artifacts" / "smoke-cli-docs-review.patch"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_render.main(
        [
            "all",
            "--drift-only",
            "--readme-path",
            str(readme_path),
            "--manifest-output",
            str(manifest_path),
            "--diff-output",
            str(diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == f"smoke README already up to date: {readme_path}\n"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_render_manifest_payload(
        manifest_payload,
        requested_target_name="all",
        markdown=README_TEXT,
        readme_path=readme_path,
        output_dir=None,
        manifest_path=manifest_path,
        diff_path=diff_path,
        written_paths=(),
    )
    assert diff_path.read_text(encoding="utf-8") == ""


def test_smoke_cli_docs_render_drift_only_reports_when_readme_is_up_to_date(tmp_path, capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_render.main(
        ["all", "--drift-only", "--readme-path", str(readme_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == f"smoke README already up to date: {readme_path}\n"


def test_smoke_cli_docs_render_rejects_manifest_output_without_drift_only(capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_render.main(["all", "--manifest-output", "artifacts/smoke-cli-docs-preview.json"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--manifest-output requires --drift-only" in captured.err


def test_smoke_cli_docs_render_rejects_diff_output_without_drift_only(capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_render.main(["all", "--diff-output", "artifacts/smoke-cli-docs-review.patch"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--diff-output requires --drift-only" in captured.err



def test_smoke_cli_docs_render_invalid_choice_errors_show_public_cli_choices(capsys) -> None:
    smoke_cli_docs_render = _load_script_module("smoke_cli_docs_render")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_render.main(["docs"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target="docs",
        expected_choices=SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[
            "smoke_cli_docs_render"
        ],
    )


def test_smoke_cli_docs_fix_build_parser_lists_public_targets_examples_and_flags() -> None:
    _assert_script_parser_help_matches_shared_expectations("smoke_cli_docs_fix")


def test_smoke_cli_docs_fix_stdout_prints_repaired_readme_without_writing(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        ["standalone_smoke", "--readme-path", str(readme_path), "--stdout"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == README_TEXT
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown


def test_smoke_cli_docs_fix_diff_previews_selected_section_without_writing(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(["standalone_smoke", "--readme-path", str(readme_path), "--diff"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.startswith("### standalone_smoke\n--- expected\n+++ README\n@@ ")
    assert "+broken standalone docs" in captured.out
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown


def test_smoke_cli_docs_fix_check_reports_drift_without_writing(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(["standalone_smoke", "--readme-path", str(readme_path), "--check"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"smoke README drift detected in 1 section(s) for {readme_path}: standalone_smoke",
        smoke_cli_docs_parity_rerun_hint(),
    ]
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown


def test_smoke_cli_docs_fix_diff_and_check_report_drift_without_writing(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        ["standalone_smoke", "--readme-path", str(readme_path), "--diff", "--check"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.startswith("### standalone_smoke\n--- expected\n+++ README\n@@ ")
    assert captured.out.rstrip().endswith(smoke_cli_docs_parity_rerun_hint())
    assert (
        f"smoke README drift detected in 1 section(s) for {readme_path}: standalone_smoke\n"
        in captured.out
    )
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown



def test_smoke_cli_docs_fix_check_json_reports_machine_readable_drift_without_writing(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        ["standalone_smoke", "--readme-path", str(readme_path), "--check", "--json"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown
    payload = json.loads(captured.out)
    _assert_smoke_cli_doc_drift_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        markdown=drifted_markdown,
        readme_path=readme_path,
        include_diff_lines=False,
        check=True,
    )
    assert payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()



def test_smoke_cli_docs_fix_diff_and_check_json_include_machine_readable_diffs(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        ["standalone_smoke", "--readme-path", str(readme_path), "--diff", "--check", "--json"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown
    payload = json.loads(captured.out)
    _assert_smoke_cli_doc_drift_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        markdown=drifted_markdown,
        readme_path=readme_path,
        include_diff_lines=True,
        check=True,
    )
    assert payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()
    assert payload["drifted_sections"][0]["diff_lines"][0] == "--- expected"
    assert payload["drifted_sections"][0]["diff_lines"][1] == "+++ README"
    assert any(line.startswith("@@ ") for line in payload["drifted_sections"][0]["diff_lines"])



def test_smoke_cli_docs_fix_check_json_output_writes_machine_readable_report_alongside_console_summary(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    json_path = tmp_path / "artifacts" / "smoke-cli-docs-fix.json"
    drifted_readme_path = tmp_path / "artifacts" / "README-drifted.md"
    bundle_index_path = tmp_path / "artifacts" / "bundle-index.json"
    render_output_dir = tmp_path / "artifacts" / "rendered"
    render_manifest_path = tmp_path / "artifacts" / "render-manifest.json"
    render_diff_path = tmp_path / "artifacts" / "render-review.patch"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        [
            "standalone_smoke",
            "--readme-path",
            str(readme_path),
            "--check",
            "--json-output",
            str(json_path),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--bundle-index-path",
            str(bundle_index_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"smoke README drift detected in 1 section(s) for {readme_path}: standalone_smoke",
        smoke_cli_docs_parity_rerun_hint(),
    ]
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_drift_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        markdown=drifted_markdown,
        readme_path=readme_path,
        include_diff_lines=False,
        check=True,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )
    assert payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()



def test_smoke_cli_docs_fix_repair_json_output_writes_machine_readable_result(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    json_path = tmp_path / "artifacts" / "smoke-cli-docs-fix.json"
    drifted_readme_path = tmp_path / "artifacts" / "README-drifted.md"
    bundle_index_path = tmp_path / "artifacts" / "bundle-index.json"
    render_output_dir = tmp_path / "artifacts" / "rendered"
    render_manifest_path = tmp_path / "artifacts" / "render-manifest.json"
    render_diff_path = tmp_path / "artifacts" / "render-review.patch"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        [
            "standalone_smoke",
            "--readme-path",
            str(readme_path),
            "--json-output",
            str(json_path),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--bundle-index-path",
            str(bundle_index_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert (
        captured.out
        == f"repaired 1 smoke README section(s) in {readme_path}: standalone_smoke\n"
    )
    repaired_text = readme_path.read_text(encoding="utf-8")
    assert repaired_text != drifted_markdown
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_repair_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        original_markdown=drifted_markdown,
        repaired_markdown=repaired_text,
        readme_path=readme_path,
        stdout=False,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )
    repaired_sections = (("standalone_smoke", render_smoke_cli_readme_section("standalone_smoke")),)
    drift_sections = collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name="standalone_smoke",
    )
    assert payload["rendered_bundle_sha256"] == rendered_bundle_sha256(repaired_sections)
    assert payload["diff_bundle_sha256"] == diff_bundle_sha256(drift_sections)
    assert payload["sections"][0]["rendered_sha256"] == sha256_text(repaired_sections[0][1])
    assert payload["sections"][0]["diff_sha256"] == sha256_text(
        "\n".join(drift_sections[0][1])
    )
    assert payload["rerun_hint"] == smoke_cli_docs_parity_rerun_hint()


def test_smoke_cli_docs_fix_clean_repair_json_output_keeps_rerun_hint_null(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    readme_path = tmp_path / "README.md"
    json_path = tmp_path / "artifacts" / "smoke-cli-docs-fix.json"
    drifted_readme_path = tmp_path / "artifacts" / "README-drifted.md"
    bundle_index_path = tmp_path / "artifacts" / "bundle-index.json"
    render_output_dir = tmp_path / "artifacts" / "rendered"
    render_manifest_path = tmp_path / "artifacts" / "render-manifest.json"
    render_diff_path = tmp_path / "artifacts" / "render-review.patch"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        [
            "standalone_smoke",
            "--readme-path",
            str(readme_path),
            "--json-output",
            str(json_path),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--bundle-index-path",
            str(bundle_index_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == f"smoke README already up to date: {readme_path}\n"
    assert readme_path.read_text(encoding="utf-8") == README_TEXT
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_repair_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        original_markdown=README_TEXT,
        repaired_markdown=README_TEXT,
        readme_path=readme_path,
        stdout=False,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )
    assert payload["changed"] is False
    assert payload["diff_bundle_sha256"] is None
    assert payload["mode"] == "repair"
    assert payload["repaired_targets"] == []
    assert payload["rendered_bundle_sha256"] is None
    assert payload["sections"] == []
    assert payload["rerun_hint"] is None
    assert payload["up_to_date"] is True
    assert payload["wrote_readme"] is False



def test_smoke_cli_docs_fix_stdout_json_output_writes_machine_readable_result_without_writing_readme(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    readme_path = tmp_path / "README.md"
    json_path = tmp_path / "artifacts" / "smoke-cli-docs-fix.json"
    drifted_readme_path = tmp_path / "artifacts" / "README-drifted.md"
    bundle_index_path = tmp_path / "artifacts" / "bundle-index.json"
    render_output_dir = tmp_path / "artifacts" / "rendered"
    render_manifest_path = tmp_path / "artifacts" / "render-manifest.json"
    render_diff_path = tmp_path / "artifacts" / "render-review.patch"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        [
            "standalone_smoke",
            "--readme-path",
            str(readme_path),
            "--stdout",
            "--json-output",
            str(json_path),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--bundle-index-path",
            str(bundle_index_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == README_TEXT
    assert readme_path.read_text(encoding="utf-8") == drifted_markdown
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_repair_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        original_markdown=drifted_markdown,
        repaired_markdown=README_TEXT,
        readme_path=readme_path,
        stdout=True,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )
    repaired_sections = (("standalone_smoke", render_smoke_cli_readme_section("standalone_smoke")),)
    drift_sections = collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name="standalone_smoke",
    )
    assert payload["rendered_bundle_sha256"] == rendered_bundle_sha256(repaired_sections)
    assert payload["diff_bundle_sha256"] == diff_bundle_sha256(drift_sections)
    assert payload["sections"][0]["rendered_sha256"] == sha256_text(repaired_sections[0][1])
    assert payload["sections"][0]["diff_sha256"] == sha256_text(
        "\n".join(drift_sections[0][1])
    )


def test_smoke_cli_docs_fix_clean_stdout_json_output_keeps_rerun_hint_null(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    readme_path = tmp_path / "README.md"
    json_path = tmp_path / "artifacts" / "smoke-cli-docs-fix.json"
    drifted_readme_path = tmp_path / "artifacts" / "README-drifted.md"
    bundle_index_path = tmp_path / "artifacts" / "bundle-index.json"
    render_output_dir = tmp_path / "artifacts" / "rendered"
    render_manifest_path = tmp_path / "artifacts" / "render-manifest.json"
    render_diff_path = tmp_path / "artifacts" / "render-review.patch"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        [
            "standalone_smoke",
            "--readme-path",
            str(readme_path),
            "--stdout",
            "--json-output",
            str(json_path),
            "--drifted-readme-path",
            str(drifted_readme_path),
            "--bundle-index-path",
            str(bundle_index_path),
            "--render-output-dir",
            str(render_output_dir),
            "--render-manifest-path",
            str(render_manifest_path),
            "--render-diff-path",
            str(render_diff_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == README_TEXT
    assert readme_path.read_text(encoding="utf-8") == README_TEXT
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _assert_smoke_cli_doc_repair_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        original_markdown=README_TEXT,
        repaired_markdown=README_TEXT,
        readme_path=readme_path,
        stdout=True,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        bundle_index_path=bundle_index_path,
    )
    assert payload["changed"] is False
    assert payload["diff_bundle_sha256"] is None
    assert payload["mode"] == "stdout"
    assert payload["repaired_targets"] == []
    assert payload["rendered_bundle_sha256"] is None
    assert payload["sections"] == []
    assert payload["rerun_hint"] is None
    assert payload["up_to_date"] is True
    assert payload["wrote_readme"] is False



def test_smoke_cli_docs_fix_repairs_selected_section_in_place(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    standalone_spec = smoke_cli_doc_spec("standalone_smoke")
    triage_spec = smoke_cli_doc_spec("session_triage_smoke")
    readme_path = tmp_path / "README.md"
    drifted_markdown = replace_markdown_section(
        README_TEXT,
        heading=standalone_spec.readme_section_heading,
        body="broken standalone docs",
    )
    readme_path.write_text(drifted_markdown, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(["standalone_smoke", "--readme-path", str(readme_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert (
        captured.out
        == f"repaired 1 smoke README section(s) in {readme_path}: standalone_smoke\n"
    )
    repaired_text = readme_path.read_text(encoding="utf-8")
    assert repaired_text != drifted_markdown
    assert matches_markdown_section(
        repaired_text,
        heading=standalone_spec.readme_section_heading,
        required_snippets=[render_smoke_cli_readme_section("standalone_smoke", body_only=True)],
    )
    assert matches_markdown_section(
        repaired_text,
        heading=triage_spec.readme_section_heading,
        required_snippets=[
            render_smoke_cli_readme_section("session_triage_smoke", body_only=True)
        ],
    )


def test_smoke_cli_docs_fix_diff_reports_when_readme_is_already_up_to_date(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(["standalone_smoke", "--readme-path", str(readme_path), "--diff"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == f"smoke README already up to date: {readme_path}\n"
    assert readme_path.read_text(encoding="utf-8") == README_TEXT


def test_smoke_cli_docs_fix_check_reports_when_readme_is_already_up_to_date(tmp_path, capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(["standalone_smoke", "--readme-path", str(readme_path), "--check"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == f"smoke README already up to date: {readme_path}\n"
    assert readme_path.read_text(encoding="utf-8") == README_TEXT



def test_smoke_cli_docs_fix_check_json_reports_when_readme_is_already_up_to_date(
    tmp_path, capsys
) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(README_TEXT, encoding="utf-8")

    exit_code = smoke_cli_docs_fix.main(
        ["standalone_smoke", "--readme-path", str(readme_path), "--check", "--json"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert readme_path.read_text(encoding="utf-8") == README_TEXT
    payload = json.loads(captured.out)
    _assert_smoke_cli_doc_drift_report_payload(
        payload,
        requested_target_name="standalone_smoke",
        markdown=README_TEXT,
        readme_path=readme_path,
        include_diff_lines=False,
        check=True,
    )



def test_smoke_cli_docs_fix_rejects_diff_stdout_combination(capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_fix.main(["standalone_smoke", "--diff", "--stdout"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--diff cannot be combined with --stdout" in captured.err


def test_smoke_cli_docs_fix_rejects_check_stdout_combination(capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_fix.main(["standalone_smoke", "--check", "--stdout"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--check cannot be combined with --stdout" in captured.err



def test_smoke_cli_docs_fix_rejects_json_stdout_combination(capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_fix.main(["standalone_smoke", "--json", "--stdout"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--json cannot be combined with --stdout" in captured.err



def test_smoke_cli_docs_fix_rejects_json_without_check_or_diff(capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_fix.main(["standalone_smoke", "--json"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--json requires --check and/or --diff" in captured.err



def test_smoke_cli_docs_fix_invalid_choice_errors_show_public_cli_choices(capsys) -> None:
    smoke_cli_docs_fix = _load_script_module("smoke_cli_docs_fix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_cli_docs_fix.main(["docs"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target="docs",
        expected_choices=SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[
            "smoke_cli_docs_fix"
        ],
    )



def test_smoke_cli_doc_specs_follow_shared_wrapper_registry_order() -> None:
    assert [doc_spec.script_name for doc_spec in SMOKE_CLI_DOC_SPECS] == [
        spec.script_name for spec in SMOKE_WRAPPER_CLI_SPECS
    ]



def _expected_smoke_matrix_review_metadata_line(*, artifact_root: str, target_name: str) -> str:
    return build_smoke_matrix_review_metadata_line(
        artifact_root=artifact_root,
        target_name=target_name,
    )


def _expected_smoke_matrix_review_artifact_location_lines(
    *,
    artifact_root: str,
    rerun_hint: str | None = None,
) -> list[str]:
    return list(
        build_smoke_matrix_review_artifact_location_lines(
            artifact_root=artifact_root,
            rerun_hint=rerun_hint or smoke_cli_docs_parity_rerun_hint(),
            success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
        )
    )


def test_smoke_matrix_uses_shared_wrapper_summary_prefixes() -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    assert smoke_matrix.SUPPRESSED_NESTED_SUMMARY_PREFIXES == NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES


def test_smoke_matrix_hides_internal_bundle_names_from_cli_choices(capsys) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    with pytest.raises(SystemExit) as exc_info:
        smoke_matrix.main(["standalone-all"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target="standalone-all",
        expected_choices=SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[
            "smoke_matrix"
        ],
    )


def test_smoke_cli_docs_smoke_reports_exact_section_diffs_without_missing_snippets() -> None:
    smoke_cli_docs_smoke = _load_script_module("smoke_cli_docs_smoke")
    spec = smoke_cli_doc_spec("standalone_smoke")
    drifted_markdown = README_TEXT.replace("Operator shortcuts:", "Shortcut notes:", 1)

    results = dict(
        smoke_cli_docs_smoke.run_smoke_cli_docs_smoke(
            markdown=drifted_markdown,
            requested_target_name="standalone_smoke",
        )
    )

    assert results["standalone_smoke_help_missing"] == "none"
    assert results["standalone_smoke_readme_missing"] == "none"
    assert results["standalone_smoke_readme_diff"].startswith("--- expected | +++ README | @@ ")
    assert "-Operator shortcuts:" in results["standalone_smoke_readme_diff"]
    assert "+Shortcut notes:" in results["standalone_smoke_readme_diff"]
    assert results["standalone_smoke_diagnostic"].startswith(
        f"help ok; README {spec.readme_section_heading!r} diff: --- expected | +++ README | @@ "
    )
    assert results["standalone_smoke_readme"] is False
    assert results["standalone_smoke_doc_parity"] is False


@pytest.mark.parametrize(
    ("script_name", "invalid_target"),
    [
        ("standalone_smoke", "standalone-local"),
        ("session_triage_smoke", "local"),
        ("session_recovery_smoke", "both"),
    ],
)
def test_smoke_wrapper_invalid_choice_errors_show_public_cli_choices(
    script_name: str,
    invalid_target: str,
    capsys,
) -> None:
    module = _load_script_module(script_name)

    with pytest.raises(SystemExit) as exc_info:
        module.main([invalid_target])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert matches_public_cli_invalid_choice(
        captured.err,
        invalid_target=invalid_target,
        expected_choices=SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME[script_name],
    )


@pytest.mark.parametrize("doc_spec", SMOKE_CLI_DOC_SPECS, ids=smoke_cli_doc_spec_id)
def test_smoke_script_main_help_exits_zero_and_prints_expected_text(doc_spec, capsys) -> None:
    module = _load_script_module(doc_spec.script_name)

    with pytest.raises(SystemExit) as exc_info:
        module.main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert matches_public_cli_help(captured.out, required_snippets=doc_spec.help_required_snippets)


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


def test_smoke_matrix_review_adds_docs_review_lane(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main(["review"])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-local", "triage", "recovery", "docs-review"],
        "args": [
            (),
            (),
            (),
            (
                "all",
                "--output-dir",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review",
                "--bundle-index-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/index.json",
                "--drifted-readme-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/README-drifted.md",
                "--render-output-dir",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/rendered",
                "--render-manifest-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-manifest.json",
                "--render-diff-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-review.patch",
                "--fix-check-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-check.json",
                "--fix-repair-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-repair.json",
                "--fix-post-check-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-post-check.json",
            ),
        ],
    }


def test_smoke_matrix_all_review_combines_live_inclusive_and_docs_review(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 0
    assert seen == {
        "names": ["standalone-all", "triage", "recovery", "docs-review-all"],
        "args": [
            ("all",),
            (),
            (),
            (
                "all",
                "--output-dir",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
                "--bundle-index-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/index.json",
                "--drifted-readme-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/README-drifted.md",
                "--render-output-dir",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/rendered",
                "--render-manifest-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-manifest.json",
                "--render-diff-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-review.patch",
                "--fix-check-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-check.json",
                "--fix-repair-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-repair.json",
                "--fix-post-check-json-path",
                "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-post-check.json",
            ),
        ],
    }


def test_smoke_matrix_review_emits_artifact_location_after_docs_review_success(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)
    perf_values = iter([0.0, 1.0, 1.2, 1.4, 1.8, 2.0, 2.5, 2.6, 3.4, 4.0])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main(["review"])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.2),
        summary_metadata.running_line(item_name="triage"),
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.4),
        summary_metadata.running_line(item_name="recovery"),
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=0.5),
        summary_metadata.running_line(item_name="docs-review"),
        summary_metadata.passed_line(item_name="docs-review", elapsed_seconds=0.8),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-review",
            target_name="docs-review",
        ),
        *_expected_smoke_matrix_review_artifact_location_lines(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-review"
        ),
        summary_metadata.success_summary_line(passed_count=4, total_count=4, elapsed_seconds=4.0),
    ]


def test_smoke_matrix_all_review_emits_distinct_artifact_location_after_docs_review_success(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)
    perf_values = iter([0.0, 1.0, 1.2, 1.4, 1.8, 2.0, 2.5, 2.6, 3.4, 4.0])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.2),
        summary_metadata.running_line(item_name="triage"),
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.4),
        summary_metadata.running_line(item_name="recovery"),
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=0.5),
        summary_metadata.running_line(item_name="docs-review"),
        summary_metadata.passed_line(item_name="docs-review", elapsed_seconds=0.8),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
            target_name="docs-review-all",
        ),
        *_expected_smoke_matrix_review_artifact_location_lines(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
        ),
        summary_metadata.success_summary_line(passed_count=4, total_count=4, elapsed_seconds=4.0),
    ]


@pytest.mark.parametrize("case", SMOKE_MATRIX_SELECTION_CASES, ids=smoke_wrapper_selection_case_id)
def test_smoke_matrix_single_bundle_target_selection(monkeypatch, case: SmokeWrapperSelectionCase) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    seen = {}

    def _run_smoke_target(target, **_kwargs):
        seen.setdefault("names", []).append(target.name)
        seen.setdefault("args", []).append(target.args)
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)

    exit_code = smoke_matrix.main(list(case.argv))

    assert exit_code == 0
    assert seen == {
        "names": list(case.expected_target_names),
        "args": list(case.expected_target_args),
    }


def test_smoke_matrix_docs_review_artifact_messages_honor_explicit_override_paths() -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    target = smoke_matrix.SmokeScriptTarget(
        name="docs-review",
        script_path=SCRIPT_DIR / "smoke_cli_docs_artifacts_smoke.py",
        args=(
            "all",
            "--output-dir",
            "artifacts/review",
            "--bundle-index-path",
            "artifacts/review/index.json",
            "--drifted-readme-path",
            "artifacts/custom/README-review.md",
            "--render-output-dir",
            "artifacts/custom/rendered-sections",
            "--render-manifest-path",
            "artifacts/custom/render.json",
            "--render-diff-path",
            "artifacts/custom/review.patch",
            "--fix-check-json-path",
            "artifacts/custom/fix-check.json",
            "--fix-repair-json-path",
            "artifacts/custom/fix-repair.json",
            "--fix-post-check-json-path",
            "artifacts/custom/fix-post-check.json",
        ),
        display_name="docs-review",
    )

    assert smoke_matrix._docs_review_artifact_metadata(target) == build_smoke_matrix_review_metadata_payload(
        artifact_root="artifacts/review",
        bundle_index_path="artifacts/review/index.json",
        drifted_readme_path="artifacts/custom/README-review.md",
        render_output_dir="artifacts/custom/rendered-sections",
        render_manifest_path="artifacts/custom/render.json",
        render_diff_path="artifacts/custom/review.patch",
        fix_check_json_path="artifacts/custom/fix-check.json",
        fix_repair_json_path="artifacts/custom/fix-repair.json",
        fix_post_check_json_path="artifacts/custom/fix-post-check.json",
    )
    assert smoke_matrix._docs_review_artifact_location_messages(target) == build_smoke_matrix_review_artifact_location_messages(
        artifact_root="artifacts/review",
        bundle_index_path="artifacts/review/index.json",
        drifted_readme_path="artifacts/custom/README-review.md",
        render_output_dir="artifacts/custom/rendered-sections",
        render_manifest_path="artifacts/custom/render.json",
        render_diff_path="artifacts/custom/review.patch",
        fix_check_json_path="artifacts/custom/fix-check.json",
        fix_repair_json_path="artifacts/custom/fix-repair.json",
        fix_post_check_json_path="artifacts/custom/fix-post-check.json",
        rerun_hint=smoke_cli_docs_parity_rerun_hint(),
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    )



def test_smoke_matrix_docs_review_artifact_messages_prefer_bundle_index_rerun_hint(
    tmp_path: Path,
) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    artifact_root = tmp_path / "review"
    artifact_root.mkdir(parents=True)
    bundle_index_path = artifact_root / "index.json"
    bundle_index_path.write_text(
        json.dumps({"rerun_hint": "hint: rerun the focused docs bundle"}) + "\n",
        encoding="utf-8",
    )
    target = smoke_matrix.SmokeScriptTarget(
        name="docs-review",
        script_path=SCRIPT_DIR / "smoke_cli_docs_artifacts_smoke.py",
        display_name="docs-review",
        metadata={
            "artifact_root": str(artifact_root),
            "bundle_index_path": str(bundle_index_path),
            "matrix_summary_path": str(artifact_root / "matrix-summary.json"),
        },
    )

    assert smoke_matrix._docs_review_artifact_metadata(target)["bundle_index_rerun_hint"] == (
        "hint: rerun the focused docs bundle"
    )
    assert smoke_matrix._docs_review_artifact_location_messages(target) == build_smoke_matrix_review_artifact_location_messages(
        artifact_root=str(artifact_root),
        bundle_index_path=str(bundle_index_path),
        matrix_summary_path=str(artifact_root / "matrix-summary.json"),
        rerun_hint="hint: rerun the focused docs bundle",
        success_defaults=SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS,
    )



def test_smoke_matrix_writes_review_metadata_summary_artifact_on_success(monkeypatch, tmp_path: Path) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    artifact_root = tmp_path / "review"
    target = smoke_matrix.SmokeScriptTarget(
        name="docs-review",
        script_path=SCRIPT_DIR / "smoke_cli_docs_artifacts_smoke.py",
        display_name="docs-review",
        metadata={
            "artifact_root": str(artifact_root),
            "bundle_index_path": str(artifact_root / "index.json"),
            "drifted_readme_path": str(artifact_root / "README-drifted.md"),
            "render_output_dir": str(artifact_root / "rendered"),
            "render_manifest_path": str(artifact_root / "render-manifest.json"),
            "render_diff_path": str(artifact_root / "render-review.patch"),
            "fix_check_json_path": str(artifact_root / "fix-check.json"),
            "fix_repair_json_path": str(artifact_root / "fix-repair.json"),
            "fix_post_check_json_path": str(artifact_root / "fix-post-check.json"),
            "matrix_summary_path": str(artifact_root / "matrix-summary.json"),
        },
    )
    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)

    stdout = StringIO()
    exit_code = smoke_matrix.run_smoke_matrix([target], stdout=stdout, stderr=StringIO())

    assert exit_code == 0
    summary_path = artifact_root / "matrix-summary.json"
    assert summary_path.exists()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == build_smoke_matrix_review_metadata_payload(
        artifact_root=artifact_root,
        bundle_index_path=artifact_root / "index.json",
        drifted_readme_path=artifact_root / "README-drifted.md",
        render_output_dir=artifact_root / "rendered",
        render_manifest_path=artifact_root / "render-manifest.json",
        render_diff_path=artifact_root / "render-review.patch",
        fix_check_json_path=artifact_root / "fix-check.json",
        fix_repair_json_path=artifact_root / "fix-repair.json",
        fix_post_check_json_path=artifact_root / "fix-post-check.json",
        matrix_summary_path=summary_path,
    )
    assert f"[smoke-matrix] review matrix summary: {summary_path}" in stdout.getvalue().splitlines()
    assert (
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line(
            smoke_cli_docs_parity_rerun_hint()
        )
        in stdout.getvalue().splitlines()
    )



def test_smoke_matrix_writes_review_metadata_summary_artifact_on_failure(monkeypatch, tmp_path: Path) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    artifact_root = tmp_path / "review-failure"
    target = smoke_matrix.SmokeScriptTarget(
        name="docs-review",
        script_path=SCRIPT_DIR / "smoke_cli_docs_artifacts_smoke.py",
        display_name="docs-review",
        metadata={
            "artifact_root": str(artifact_root),
            "bundle_index_path": str(artifact_root / "index.json"),
            "drifted_readme_path": str(artifact_root / "README-drifted.md"),
            "render_output_dir": str(artifact_root / "rendered"),
            "render_manifest_path": str(artifact_root / "render-manifest.json"),
            "render_diff_path": str(artifact_root / "render-review.patch"),
            "fix_check_json_path": str(artifact_root / "fix-check.json"),
            "fix_repair_json_path": str(artifact_root / "fix-repair.json"),
            "fix_post_check_json_path": str(artifact_root / "fix-post-check.json"),
            "matrix_summary_path": str(artifact_root / "matrix-summary.json"),
        },
    )
    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 1)

    stderr = StringIO()
    exit_code = smoke_matrix.run_smoke_matrix([target], stdout=StringIO(), stderr=stderr)

    assert exit_code == 1
    summary_path = artifact_root / "matrix-summary.json"
    assert summary_path.exists()
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary_payload == build_smoke_matrix_review_metadata_payload(
        artifact_root=artifact_root,
        bundle_index_path=artifact_root / "index.json",
        drifted_readme_path=artifact_root / "README-drifted.md",
        render_output_dir=artifact_root / "rendered",
        render_manifest_path=artifact_root / "render-manifest.json",
        render_diff_path=artifact_root / "render-review.patch",
        fix_check_json_path=artifact_root / "fix-check.json",
        fix_repair_json_path=artifact_root / "fix-repair.json",
        fix_post_check_json_path=artifact_root / "fix-post-check.json",
        matrix_summary_path=summary_path,
    )
    assert f"[smoke-matrix] review matrix summary: {summary_path}" in stderr.getvalue().splitlines()
    assert (
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line(
            smoke_cli_docs_parity_rerun_hint()
        )
        in stderr.getvalue().splitlines()
    )



def test_smoke_matrix_emits_bundle_timing_summary(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)

    perf_values = iter([0.0, 1.0, 1.3, 2.0, 2.6, 3.0, 3.9, 4.5])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main([])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.3),
        summary_metadata.running_line(item_name="triage"),
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.6),
        summary_metadata.running_line(item_name="recovery"),
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=0.9),
        summary_metadata.success_summary_line(passed_count=3, total_count=3, elapsed_seconds=4.5),
    ]


def test_smoke_matrix_all_bundle_uses_public_standalone_label(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 0)

    perf_values = iter([0.0, 1.0, 1.4, 2.0, 2.7, 3.0, 4.0, 4.8])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = smoke_matrix.main(["all"])

    assert exit_code == 0
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.4),
        summary_metadata.running_line(item_name="triage"),
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.7),
        summary_metadata.running_line(item_name="recovery"),
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=1.0),
        summary_metadata.success_summary_line(passed_count=3, total_count=3, elapsed_seconds=4.8),
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
    summary_metadata = SMOKE_MATRIX_WRAPPER

    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        "standalone-local_check= True",
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.25),
        summary_metadata.running_line(item_name="triage"),
        "triage_check= True",
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.5),
        summary_metadata.running_line(item_name="recovery"),
        "recovery_check= True",
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=0.75),
        summary_metadata.success_summary_line(passed_count=3, total_count=3, elapsed_seconds=4.0),
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
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.2),
        summary_metadata.running_line(item_name="triage"),
    ]

    assert stderr.getvalue().splitlines() == [
        summary_metadata.failed_line(item_name="triage", elapsed_seconds=0.5),
        summary_metadata.failure_summary_line(passed_count=1, total_count=3, elapsed_seconds=2.5),
    ]


def test_smoke_matrix_docs_review_failure_emits_artifact_location_before_summary(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", lambda target, **_kwargs: 1)
    perf_values = iter([0.0, 1.0, 1.6, 2.5])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["docs-review"])

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="docs-review")]
    assert stderr.getvalue().splitlines() == [
        summary_metadata.failed_line(item_name="docs-review", elapsed_seconds=0.6),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-review",
            target_name="docs-review",
        ),
        (
            "[smoke-matrix] review artifacts: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review "
            "(index: artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/index.json)"
        ),
        (
            "[smoke-matrix] review matrix summary: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/matrix-summary.json"
        ),
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line(
            smoke_cli_docs_parity_rerun_hint()
        ),
        (
            "[smoke-matrix] review drifted README: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/README-drifted.md"
        ),
        (
            "[smoke-matrix] review rendered sections: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/rendered"
        ),
        (
            "[smoke-matrix] review render manifest: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-manifest.json"
        ),
        (
            "[smoke-matrix] review render diff: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-review.patch"
        ),
        (
            "[smoke-matrix] review fix-check JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-check.json"
        ),
        (
            "[smoke-matrix] review fix-repair JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-repair.json"
        ),
        (
            "[smoke-matrix] review fix-post-check JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-post-check.json"
        ),
        (
            "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
            "`standalone_smoke.py docs-review-only`; rerun "
            "`.venv/bin/python scripts/standalone_smoke.py docs-review-only` to recheck the docs-review lane "
            "without the broader docs parity bundle or the rest of the matrix."
        ),
        summary_metadata.failure_summary_line(passed_count=0, total_count=1, elapsed_seconds=2.5),
    ]


def test_smoke_matrix_all_review_docs_review_failure_emits_docs_focused_hint(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")
    summary_metadata = SMOKE_MATRIX_WRAPPER

    def _run_smoke_target(target, **_kwargs):
        return 1 if target.name == "docs-review-all" else 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.3, 2.0, 2.4, 3.0, 3.5, 4.2, 5.0, 5.8])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [
        summary_metadata.running_line(item_name="standalone"),
        summary_metadata.passed_line(item_name="standalone", elapsed_seconds=0.3),
        summary_metadata.running_line(item_name="triage"),
        summary_metadata.passed_line(item_name="triage", elapsed_seconds=0.4),
        summary_metadata.running_line(item_name="recovery"),
        summary_metadata.passed_line(item_name="recovery", elapsed_seconds=0.5),
        summary_metadata.running_line(item_name="docs-review"),
    ]
    assert stderr.getvalue().splitlines() == [
        summary_metadata.failed_line(item_name="docs-review", elapsed_seconds=0.8),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
            target_name="docs-review-all",
        ),
        (
            "[smoke-matrix] review artifacts: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review "
            "(index: artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/index.json)"
        ),
        (
            "[smoke-matrix] review matrix summary: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/matrix-summary.json"
        ),
        SMOKE_MATRIX_ARTIFACT_ROOTS_SUCCESS_DEFAULTS.format_rerun_hint_line(
            smoke_cli_docs_parity_rerun_hint()
        ),
        (
            "[smoke-matrix] review drifted README: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/README-drifted.md"
        ),
        (
            "[smoke-matrix] review rendered sections: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/rendered"
        ),
        (
            "[smoke-matrix] review render manifest: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-manifest.json"
        ),
        (
            "[smoke-matrix] review render diff: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-review.patch"
        ),
        (
            "[smoke-matrix] review fix-check JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-check.json"
        ),
        (
            "[smoke-matrix] review fix-repair JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-repair.json"
        ),
        (
            "[smoke-matrix] review fix-post-check JSON: "
            "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-post-check.json"
        ),
        (
            "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
            "`standalone_smoke.py docs-review-only`; rerun "
            "`.venv/bin/python scripts/standalone_smoke.py docs-review-only` to recheck the docs-review lane "
            "without the broader docs parity bundle or the rest of the matrix."
        ),
        summary_metadata.failure_summary_line(passed_count=3, total_count=4, elapsed_seconds=5.8),
    ]


def test_smoke_matrix_preserves_public_bundle_labels_in_fail_fast_stderr(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        if target.name == "standalone-all":
            return build_smoke_matrix_public_label_fail_fast_fixture(
                display_label=target.display_label,
            ).emit_failed_target_run(
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                output_line_observer=kwargs.get("output_line_observer"),
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.6, 2.2])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all"])

    assert exit_code == 1
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="standalone")]

    assert stderr.getvalue().splitlines() == [
        "standalone smoke failed fast: standalone_check= False",
        summary_metadata.failed_line(item_name="standalone", elapsed_seconds=0.6),
        summary_metadata.failure_summary_line(passed_count=0, total_count=3, elapsed_seconds=2.2),
    ]


def test_smoke_matrix_all_failure_emits_live_runtime_export_hint(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        observer = kwargs["output_line_observer"]
        if target.name == "standalone-all":
            observer("provider=fake-strands mode=fake\n")
            return SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE.emit_failed_target_run(
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                output_line_observer=observer,
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.6, 2.4])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all"])

    assert exit_code == 1
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="standalone")]
    assert stderr.getvalue().splitlines() == [
        *SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE.stderr_lines,
        summary_metadata.failed_line(item_name="standalone", elapsed_seconds=0.6),
        (
            "[smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`; "
            "export `STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
            "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning the live-inclusive matrix."
        ),
        summary_metadata.failure_summary_line(passed_count=0, total_count=3, elapsed_seconds=2.4),
    ]


def test_smoke_matrix_all_failure_emits_missing_api_key_hint(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        observer = kwargs["output_line_observer"]
        stderr = kwargs["stderr"]
        if target.name == "standalone-all":
            return SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_FIXTURE.emit_target_run(
                stdout=kwargs["stdout"],
                stderr=stderr,
                exit_code=1,
                output_line_observer=observer,
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.5, 2.1])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all"])

    assert exit_code == 1
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="standalone")]
    assert stderr.getvalue().splitlines() == [
        "standalone smoke exited with status 1",
        summary_metadata.failed_line(item_name="standalone", elapsed_seconds=0.5),
        (
            "[smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but `OPENAI_API_KEY` "
            "was missing; export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) "
            "before rerunning."
        ),
        summary_metadata.failure_summary_line(passed_count=0, total_count=3, elapsed_seconds=2.1),
    ]


def test_smoke_matrix_all_review_failure_emits_live_runtime_hint(monkeypatch) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        if target.name == "standalone-all":
            return SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE.emit_failed_target_run(
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                output_line_observer=kwargs["output_line_observer"],
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.3, 2.0])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 1
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="standalone")]
    assert stderr.getvalue().splitlines() == [
        *SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE.stderr_lines,
        summary_metadata.failed_line(item_name="standalone", elapsed_seconds=0.3),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
            target_name="docs-review-all",
        ),
        *_expected_smoke_matrix_review_artifact_location_lines(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
        ),
        (
            "[smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`; "
            "export `STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
            "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning the live-inclusive matrix."
        ),
        (
            "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
            "`standalone_smoke.py docs-review-only`; rerun "
            "`.venv/bin/python scripts/standalone_smoke.py docs-review-only` to recheck the docs-review lane "
            "without the broader docs parity bundle or the rest of the matrix."
        ),
        summary_metadata.failure_summary_line(passed_count=0, total_count=4, elapsed_seconds=2.0),
    ]


def test_smoke_matrix_all_review_failure_emits_missing_api_key_hint_and_docs_focused_rerun(
    monkeypatch,
) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        observer = kwargs["output_line_observer"]
        stderr = kwargs["stderr"]
        if target.name == "standalone-all":
            return SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_FIXTURE.emit_target_run(
                stdout=kwargs["stdout"],
                stderr=stderr,
                exit_code=1,
                output_line_observer=observer,
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    perf_values = iter([0.0, 1.0, 1.4, 2.2])
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: next(perf_values))

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 1
    summary_metadata = SMOKE_MATRIX_WRAPPER
    assert stdout.getvalue().splitlines() == [summary_metadata.running_line(item_name="standalone")]
    assert stderr.getvalue().splitlines() == [
        "standalone smoke exited with status 1",
        summary_metadata.failed_line(item_name="standalone", elapsed_seconds=0.4),
        _expected_smoke_matrix_review_metadata_line(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
            target_name="docs-review-all",
        ),
        *_expected_smoke_matrix_review_artifact_location_lines(
            artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
        ),
        (
            "[smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but `OPENAI_API_KEY` "
            "was missing; export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) "
            "before rerunning."
        ),
        (
            "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
            "`standalone_smoke.py docs-review-only`; rerun "
            "`.venv/bin/python scripts/standalone_smoke.py docs-review-only` to recheck the docs-review lane "
            "without the broader docs parity bundle or the rest of the matrix."
        ),
        summary_metadata.failure_summary_line(passed_count=0, total_count=4, elapsed_seconds=2.2),
    ]


def test_smoke_matrix_all_review_failure_persists_pending_review_metadata_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    smoke_matrix = _load_script_module("smoke_matrix")

    def _run_smoke_target(target, **kwargs):
        if target.name == "standalone-all":
            return SMOKE_MATRIX_ALL_REVIEW_LIVE_RUNTIME_FAILURE_FIXTURE.emit_failed_target_run(
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                output_line_observer=kwargs["output_line_observer"],
                output_line_filter=kwargs.get("output_line_filter"),
            )
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(smoke_matrix, "run_smoke_target", _run_smoke_target)
    monkeypatch.setattr(smoke_matrix, "perf_counter", lambda: 0.0)

    exit_code = smoke_matrix.main(["all-review"])

    assert exit_code == 1
    summary_path = tmp_path / "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/matrix-summary.json"
    assert summary_path.exists()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == build_smoke_matrix_review_metadata_payload(
        artifact_root="artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
        target_name="docs-review-all",
    )


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
        required=[
            "workspace lanes: edit",
            "Workspace edit queue mix: pending-only: 2 sessions | restored pending-only: 1 session",
        ],
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
        required=[
            "| overlap: mixed 1 session",
            "Shell test queue mix: pending-only: 3 sessions | restored pending-only: 1 session",
        ],
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
        required=[
            "workspace lanes: edit",
            "| overlap: mixed 1 session",
            "Workspace edit queue mix: pending-only: 2 sessions | restored pending-only: 1 session",
        ],
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
        required=[
            "| overlap: mixed 1 session",
            "Shell test queue mix: pending-only: 3 sessions | restored pending-only: 1 session",
        ],
    )
