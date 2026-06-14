from __future__ import annotations

import sys
from io import StringIO
from textwrap import dedent

import pytest

from strands_agent_tui.testing.smoke_script_harness import (
    build_standalone_malformed_contract_failure_output_lines,
)
from strands_agent_tui.testing.smoke_runner import (
    NON_MATRIX_SMOKE_WRAPPER_CLI_SPECS,
    NON_MATRIX_SMOKE_WRAPPER_METADATA,
    NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES,
    SMOKE_MATRIX_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_SELECTION_CASES,
    SESSION_RECOVERY_SMOKE_WRAPPER,
    SESSION_TRIAGE_SMOKE_CLI_SPEC,
    SESSION_TRIAGE_SMOKE_SELECTION_CASES,
    SESSION_TRIAGE_SMOKE_WRAPPER,
    SMOKE_MATRIX_SELECTION_CASES,
    SMOKE_MATRIX_WRAPPER,
    SMOKE_WRAPPER_CLI_SPECS,
    SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME,
    STANDALONE_ALL_TARGET_NAMES,
    STANDALONE_CONTRACT_NEGATIVE_TARGET_NAMES,
    STANDALONE_DOCS_CONTRACT_TARGET_NAMES,
    STANDALONE_DOCS_FOCUSED_TARGET_NAMES,
    STANDALONE_DOCS_PARITY_FOLLOW_UP,
    STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES,
    STANDALONE_DOCS_PARITY_ONLY_TARGET_NAMES,
    STANDALONE_DOCS_REVIEW_FOLLOW_UP,
    STANDALONE_DOCS_REVIEW_FOLLOW_UP_FAILURE_FIXTURES,
    STANDALONE_DOCS_REVIEW_ONLY_TARGET_NAMES,
    STANDALONE_LOCAL_TARGET_NAMES,
    STANDALONE_MALFORMED_CONTRACT_FAILURE_FIXTURES,
    STANDALONE_SMOKE_CLI_SPEC,
    STANDALONE_SMOKE_SELECTION_CASES,
    STANDALONE_SMOKE_WRAPPER,
    StandaloneFollowUpFailureFixture,
    StandaloneFollowUpFailureFixtureSet,
    TimedStandaloneSmokeFailureCase,
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    SmokeWrapperMetadata,
    SmokeWrapperSelectionCase,
    _select_alias_target_names,
    build_smoke_cli_parser,
    build_smoke_wrapper_invalid_choice_expected_choices_registry,
    build_standalone_follow_up_failure_run_smoke_target,
    build_standalone_docs_contract_failure_cases,
    build_standalone_docs_review_follow_up_failure_cases,
    build_timed_standalone_smoke_failure_cases,
    build_timed_standalone_smoke_failure_pytest_params,
    build_standalone_malformed_contract_failure_cases,
    run_smoke_target,
    run_smoke_targets,
    smoke_wrapper_cli_spec,
    smoke_wrapper_metadata_from_specs,
    smoke_wrapper_selection_case_id,
    standalone_docs_review_follow_up_hint_for_failure,
    standalone_malformed_contract_hint_for_failure,
    standalone_smoke_failure_case_id,
    summary_line_prefixes,
)


def _write_script(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(dedent(body), encoding="utf-8")
    return path


def _failure_case_positions(cases):
    return [
        (case.requested_target_name, case.failed_target_name, case.passed_count, case.total_count)
        for case in cases
    ]


def test_run_smoke_target_streams_successful_output(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "success.py",
        """
        print("check= True", flush=True)
        print("done", flush=True)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("success", script_path),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 0
    assert stdout.getvalue() == "check= True\ndone\n"
    assert stderr.getvalue() == ""


def test_run_smoke_target_fails_fast_on_false_result_line(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "failure.py",
        """
        import time

        print("check= True", flush=True)
        print("broken= False", flush=True)
        time.sleep(5)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("failure", script_path),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 1
    assert "check= True\nbroken= False\n" == stdout.getvalue()
    assert stderr.getvalue().strip() == "failure smoke failed fast: broken= False"


def test_run_smoke_target_can_filter_output_lines_without_hiding_failures(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "filtered.py",
        """
        import time

        print("[bundle-smoke] summary: 1/1 targets passed in 0.50s", flush=True)
        print("visible= True", flush=True)
        print("hidden_failure= False", flush=True)
        time.sleep(5)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("filtered", script_path),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
        output_line_filter=lambda line: not line.startswith("[") and not line.startswith("hidden_failure="),
    )

    assert exit_code == 1
    assert stdout.getvalue() == "visible= True\n"
    assert stderr.getvalue().strip() == "filtered smoke failed fast: hidden_failure= False"


def test_run_smoke_target_can_observe_filtered_output_lines(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "observed.py",
        """
        print("[bundle-smoke] summary: 1/1 targets passed in 0.50s", flush=True)
        print("visible= True", flush=True)
        print("hidden_failure= False", flush=True)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    observed_lines: list[str] = []
    exit_code = run_smoke_target(
        SmokeScriptTarget("observed", script_path),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
        output_line_filter=lambda line: not line.startswith("[") and not line.startswith("hidden_failure="),
        output_line_observer=observed_lines.append,
    )

    assert exit_code == 1
    assert stdout.getvalue() == "visible= True\n"
    assert stderr.getvalue().strip() == "observed smoke failed fast: hidden_failure= False"
    assert observed_lines == [
        "[bundle-smoke] summary: 1/1 targets passed in 0.50s\n",
        "visible= True\n",
        "hidden_failure= False\n",
    ]


def test_run_smoke_target_reports_nonzero_exit_without_false_line(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "nonzero.py",
        """
        print("starting", flush=True)
        raise SystemExit(3)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("nonzero", script_path),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 3
    assert stdout.getvalue() == "starting\n"
    assert stderr.getvalue().strip() == "nonzero smoke exited with status 3"


def test_run_smoke_target_uses_display_label_for_error_messages(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "nonzero.py",
        """
        print("starting", flush=True)
        raise SystemExit(3)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("nonzero", script_path, display_name="standalone"),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 3
    assert stdout.getvalue() == "starting\n"
    assert stderr.getvalue().strip() == "standalone smoke exited with status 3"


def test_run_smoke_targets_stops_before_later_targets_after_failure(tmp_path) -> None:
    marker_path = tmp_path / "second-ran.txt"
    failing_script = _write_script(
        tmp_path,
        "first.py",
        """
        print("first_check= False", flush=True)
        """,
    )
    second_script = _write_script(
        tmp_path,
        "second.py",
        f"""
        from pathlib import Path

        Path({str(marker_path)!r}).write_text("ran", encoding="utf-8")
        print("second_check= True", flush=True)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_targets(
        [
            SmokeScriptTarget("first", failing_script),
            SmokeScriptTarget("second", second_script),
        ],
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 1
    assert stdout.getvalue() == "first_check= False\n"
    assert stderr.getvalue().strip() == "first smoke failed fast: first_check= False"
    assert not marker_path.exists()


def test_run_smoke_targets_emits_summary_footer_on_success(tmp_path, monkeypatch) -> None:
    first_script = _write_script(
        tmp_path,
        "first.py",
        """
        print("first_check= True", flush=True)
        """,
    )
    second_script = _write_script(
        tmp_path,
        "second.py",
        """
        print("second_check= True", flush=True)
        """,
    )

    perf_values = iter([0.0, 1.25])
    monkeypatch.setattr("strands_agent_tui.testing.smoke_runner.perf_counter", lambda: next(perf_values))

    bundle_metadata = SmokeWrapperMetadata(summary_label="bundle-smoke")
    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_targets(
        [
            SmokeScriptTarget("first", first_script),
            SmokeScriptTarget("second", second_script),
        ],
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
        wrapper_metadata=bundle_metadata,
    )

    assert exit_code == 0
    assert stdout.getvalue() == (
        "first_check= True\n"
        "second_check= True\n"
        f"{bundle_metadata.success_summary_line(passed_count=2, total_count=2, elapsed_seconds=1.25)}\n"
    )
    assert stderr.getvalue() == ""


def test_run_smoke_targets_emits_failure_summary_footer(tmp_path, monkeypatch) -> None:
    first_script = _write_script(
        tmp_path,
        "first.py",
        """
        print("first_check= True", flush=True)
        """,
    )
    second_script = _write_script(
        tmp_path,
        "second.py",
        """
        print("second_check= False", flush=True)
        """,
    )

    perf_values = iter([0.0, 2.5])
    monkeypatch.setattr("strands_agent_tui.testing.smoke_runner.perf_counter", lambda: next(perf_values))

    bundle_metadata = SmokeWrapperMetadata(summary_label="bundle-smoke")
    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_targets(
        [
            SmokeScriptTarget("first", first_script),
            SmokeScriptTarget("second", second_script),
        ],
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
        wrapper_metadata=bundle_metadata,
    )

    assert exit_code == 1
    assert stdout.getvalue() == "first_check= True\nsecond_check= False\n"
    assert stderr.getvalue().splitlines() == [
        "second smoke failed fast: second_check= False",
        bundle_metadata.failure_summary_line(passed_count=1, total_count=2, elapsed_seconds=2.5),
    ]


def test_run_smoke_targets_emits_failure_hint_before_summary_footer(tmp_path, monkeypatch) -> None:
    first_script = _write_script(
        tmp_path,
        "first.py",
        """
        print("first_check= True", flush=True)
        """,
    )
    second_script = _write_script(
        tmp_path,
        "second.py",
        """
        print("detail: export live env", flush=True)
        print("second_check= False", flush=True)
        """,
    )

    perf_values = iter([0.0, 2.5])
    monkeypatch.setattr("strands_agent_tui.testing.smoke_runner.perf_counter", lambda: next(perf_values))

    bundle_metadata = SmokeWrapperMetadata(summary_label="bundle-smoke")
    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_targets(
        [
            SmokeScriptTarget("first", first_script),
            SmokeScriptTarget("second", second_script),
        ],
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
        wrapper_metadata=bundle_metadata,
        failure_hint_builder=lambda target, observed_lines: (
            "hint: export STRANDS_AGENT_RUNTIME=live"
            if target.name == "second" and "detail: export live env\n" in observed_lines
            else None
        ),
    )

    assert exit_code == 1
    assert stdout.getvalue() == "first_check= True\ndetail: export live env\nsecond_check= False\n"
    assert stderr.getvalue().splitlines() == [
        "second smoke failed fast: second_check= False",
        "[bundle-smoke] hint: export STRANDS_AGENT_RUNTIME=live",
        bundle_metadata.failure_summary_line(passed_count=1, total_count=2, elapsed_seconds=2.5),
    ]


def test_smoke_wrapper_metadata_formats_shared_summary_and_progress_lines() -> None:
    wrapper_metadata = SmokeWrapperMetadata(summary_label="bundle-smoke")
    bundle_metadata = SMOKE_MATRIX_WRAPPER

    assert wrapper_metadata.line_prefix == "[bundle-smoke]"
    assert wrapper_metadata.format_line("custom message") == "[bundle-smoke] custom message"
    assert wrapper_metadata.success_summary_line(passed_count=2, total_count=2, elapsed_seconds=1.25) == (
        "[bundle-smoke] summary: 2/2 targets passed in 1.25s"
    )
    assert wrapper_metadata.failure_summary_line(passed_count=1, total_count=2, elapsed_seconds=2.5) == (
        "[bundle-smoke] summary: 1/2 targets passed before failure in 2.50s"
    )
    assert bundle_metadata.running_line(item_name="standalone") == "[smoke-matrix] running standalone"
    assert bundle_metadata.passed_line(item_name="standalone", elapsed_seconds=0.3) == (
        "[smoke-matrix] standalone passed in 0.30s"
    )
    assert bundle_metadata.failed_line(item_name="triage", elapsed_seconds=0.5) == (
        "[smoke-matrix] triage failed in 0.50s"
    )
    assert bundle_metadata.success_summary_line(passed_count=3, total_count=3, elapsed_seconds=4.5) == (
        "[smoke-matrix] summary: 3/3 bundles passed in 4.50s"
    )



def test_summary_line_prefixes_deduplicate_shared_wrapper_metadata() -> None:
    assert STANDALONE_SMOKE_WRAPPER.summary_line_prefix == "[standalone-smoke] summary:"
    assert SESSION_TRIAGE_SMOKE_WRAPPER.summary_line_prefix == "[session-triage-smoke] summary:"
    assert SESSION_RECOVERY_SMOKE_WRAPPER.summary_line_prefix == "[session-recovery-smoke] summary:"
    assert SMOKE_MATRIX_WRAPPER.summary_line_prefix == "[smoke-matrix] summary:"
    assert summary_line_prefixes(
        [
            STANDALONE_SMOKE_WRAPPER,
            SESSION_TRIAGE_SMOKE_WRAPPER,
            STANDALONE_SMOKE_WRAPPER,
            SESSION_RECOVERY_SMOKE_WRAPPER,
            SMOKE_MATRIX_WRAPPER,
        ]
    ) == (
        "[standalone-smoke] summary:",
        "[session-triage-smoke] summary:",
        "[session-recovery-smoke] summary:",
        "[smoke-matrix] summary:",
    )



def test_run_smoke_targets_rejects_conflicting_wrapper_metadata_and_summary_label(tmp_path) -> None:
    script_path = _write_script(tmp_path, "first.py", "print('first_check= True', flush=True)\n")

    with pytest.raises(ValueError, match="wrapper_metadata.summary_label does not match summary_label"):
        run_smoke_targets(
            [SmokeScriptTarget("first", script_path)],
            python_executable=sys.executable,
            wrapper_metadata=STANDALONE_SMOKE_WRAPPER,
            summary_label="session-triage-smoke",
        )


def test_smoke_target_selector_resolves_default_alias_and_single_target(tmp_path) -> None:
    first_script = _write_script(tmp_path, "first.py", "print('first_check= True', flush=True)\n")
    second_script = _write_script(tmp_path, "second.py", "print('second_check= True', flush=True)\n")
    selector = SmokeTargetSelector(
        targets={
            "first": SmokeScriptTarget("first", first_script),
            "second": SmokeScriptTarget("second", second_script),
        },
        default_target_name="both",
        alias_target_names={
            "both": ("first", "second"),
            "all": ("first", "second"),
        },
    )

    assert selector.choices == ("first", "second", "both", "all")
    assert selector.resolve_target_names() == ["first", "second"]
    assert [target.name for target in selector.resolve_targets()] == ["first", "second"]
    assert selector.resolve_target_names("second") == ["second"]
    assert [target.name for target in selector.resolve_targets("all")] == ["first", "second"]


def test_smoke_target_selector_supports_partial_public_display_name_overrides_for_hidden_targets(tmp_path) -> None:
    local_script = _write_script(tmp_path, "local.py", "print('local_check= True', flush=True)\n")
    all_script = _write_script(tmp_path, "all.py", "print('all_check= True', flush=True)\n")
    triage_script = _write_script(tmp_path, "triage.py", "print('triage_check= True', flush=True)\n")
    selector = SmokeTargetSelector(
        targets={
            "standalone-local": SmokeScriptTarget("standalone-local", local_script, display_name="standalone"),
            "standalone-all": SmokeScriptTarget("standalone-all", all_script, display_name="standalone"),
            "triage": SmokeScriptTarget("triage", triage_script),
        },
        default_target_name="local",
        alias_target_names={
            "local": ("standalone-local", "triage"),
            "all": ("standalone-all", "triage"),
        },
        choice_target_names={
            "standalone": ("standalone-local",),
            "triage": ("triage",),
            "local": ("standalone-local", "triage"),
            "all": ("standalone-all", "triage"),
        },
        choice_display_names={
            "all": ("standalone (live-inclusive)", "triage"),
        },
    )

    assert selector.choices == ("standalone", "triage", "local", "all")
    assert selector.resolve_target_names() == ["standalone-local", "triage"]
    assert selector.resolve_display_names() == ["standalone", "triage"]
    assert [target.name for target in selector.resolve_targets("standalone")] == ["standalone-local"]
    assert selector.resolve_display_names("all") == ["standalone (live-inclusive)", "triage"]
    assert [target.name for target in selector.resolve_targets("all")] == ["standalone-all", "triage"]


def test_build_smoke_cli_parser_renders_alias_help_and_examples(tmp_path) -> None:
    first_script = _write_script(tmp_path, "first.py", "print('first_check= True', flush=True)\n")
    second_script = _write_script(tmp_path, "second.py", "print('second_check= True', flush=True)\n")
    selector = SmokeTargetSelector(
        targets={
            "first": SmokeScriptTarget("first", first_script, display_name="demofirst"),
            "second": SmokeScriptTarget("second", second_script, display_name="demosecond"),
        },
        default_target_name="both",
        alias_target_names={"both": ("first", "second")},
    )

    parser = build_smoke_cli_parser(
        description="Run the demo smoke bundle.",
        choices=selector.choices,
        default_target_name=selector.default_target_name,
        resolve_target_names=selector.resolve_target_names,
        resolve_display_names=selector.resolve_display_names,
        item_help="Which demo smoke surface to run.",
        alias_target_names=selector.alias_target_names,
        examples=(
            SmokeCliExample("demo_smoke.py"),
            SmokeCliExample("demo_smoke.py first", target_name="first"),
        ),
    )

    help_text = " ".join(parser.format_help().split())
    assert "Which demo smoke surface to run. Aliases: both -> demofirst, demosecond." in help_text
    assert "Alias details: both -> demofirst, demosecond" in help_text
    assert "demo_smoke.py # default both alias -> demofirst, demosecond" in help_text
    assert "demo_smoke.py first # single target" in help_text


def test_smoke_target_selector_invalid_choice_expected_choices_follow_choice_order(tmp_path) -> None:
    first_script = _write_script(tmp_path, "first.py", "print('first_check= True', flush=True)\n")
    second_script = _write_script(tmp_path, "second.py", "print('second_check= True', flush=True)\n")
    selector = SmokeTargetSelector(
        targets={
            "first": SmokeScriptTarget("first", first_script),
            "second": SmokeScriptTarget("second", second_script),
        },
        default_target_name="both",
        alias_target_names={"both": ("first", "second")},
    )

    assert selector.invalid_choice_expected_choices() == "{first,second,both}"


def test_smoke_wrapper_cli_spec_registry_tracks_shared_order_and_metadata() -> None:
    assert SMOKE_WRAPPER_CLI_SPECS == (
        STANDALONE_SMOKE_CLI_SPEC,
        SESSION_TRIAGE_SMOKE_CLI_SPEC,
        SESSION_RECOVERY_SMOKE_CLI_SPEC,
        SMOKE_MATRIX_CLI_SPEC,
    )
    assert tuple(smoke_wrapper_cli_spec(spec.script_name) for spec in SMOKE_WRAPPER_CLI_SPECS) == (
        STANDALONE_SMOKE_CLI_SPEC,
        SESSION_TRIAGE_SMOKE_CLI_SPEC,
        SESSION_RECOVERY_SMOKE_CLI_SPEC,
        SMOKE_MATRIX_CLI_SPEC,
    )
    assert NON_MATRIX_SMOKE_WRAPPER_CLI_SPECS == (
        STANDALONE_SMOKE_CLI_SPEC,
        SESSION_TRIAGE_SMOKE_CLI_SPEC,
        SESSION_RECOVERY_SMOKE_CLI_SPEC,
    )
    assert smoke_wrapper_metadata_from_specs(
        (
            STANDALONE_SMOKE_CLI_SPEC,
            SMOKE_MATRIX_CLI_SPEC,
            STANDALONE_SMOKE_CLI_SPEC,
            SESSION_TRIAGE_SMOKE_CLI_SPEC,
        )
    ) == (
        STANDALONE_SMOKE_WRAPPER,
        SMOKE_MATRIX_WRAPPER,
        SESSION_TRIAGE_SMOKE_WRAPPER,
    )
    assert NON_MATRIX_SMOKE_WRAPPER_METADATA == (
        STANDALONE_SMOKE_WRAPPER,
        SESSION_TRIAGE_SMOKE_WRAPPER,
        SESSION_RECOVERY_SMOKE_WRAPPER,
    )
    assert NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES == (
        "[standalone-smoke] summary:",
        "[session-triage-smoke] summary:",
        "[session-recovery-smoke] summary:",
    )
    assert SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME == (
        build_smoke_wrapper_invalid_choice_expected_choices_registry(SMOKE_WRAPPER_CLI_SPECS)
    )
    assert SMOKE_WRAPPER_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME["smoke_matrix"] == (
        "{standalone,triage,recovery,docs-review,local,all,review,all-review}"
    )


def test_smoke_wrapper_cli_spec_registry_helper_resolves_defaults_and_unknown_names(tmp_path) -> None:
    spec = smoke_wrapper_cli_spec("smoke_matrix")

    assert spec.default_target_names() == ("standalone-local", "triage", "recovery")
    assert spec.default_display_names() == ("standalone", "triage", "recovery")
    assert spec.resolve_target_names("all") == ("standalone-all", "triage", "recovery")
    assert spec.resolve_display_names("all") == ("standalone (live-inclusive)", "triage", "recovery")
    assert spec.resolve_target_names("review") == ("standalone-local", "triage", "recovery", "docs-review")
    assert spec.resolve_target_names("all-review") == ("standalone-all", "triage", "recovery", "docs-review-all")
    assert spec.resolve_display_names("all-review") == (
        "standalone (live-inclusive)",
        "triage",
        "recovery",
        "docs-review",
    )
    assert [target.name for target in spec.default_targets(script_dir=tmp_path)] == [
        "standalone-local",
        "triage",
        "recovery",
    ]
    assert [target.name for target in spec.resolve_targets(script_dir=tmp_path, requested_target_name="standalone")] == [
        "standalone-local"
    ]
    docs_review_targets = spec.resolve_targets(script_dir=tmp_path, requested_target_name="docs-review")
    assert [target.name for target in docs_review_targets] == ["docs-review"]
    assert docs_review_targets[0].args == (
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
    )
    assert docs_review_targets[0].metadata == {
        "artifact_root": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review",
        "bundle_index_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/index.json",
        "drifted_readme_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/README-drifted.md",
        "render_output_dir": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/rendered",
        "render_manifest_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-manifest.json",
        "render_diff_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/render-review.patch",
        "fix_check_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-check.json",
        "fix_repair_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-repair.json",
        "fix_post_check_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/fix-post-check.json",
        "matrix_summary_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review/matrix-summary.json",
    }
    all_review_targets = spec.resolve_targets(script_dir=tmp_path, requested_target_name="all-review")
    assert [target.name for target in all_review_targets] == ["standalone-all", "triage", "recovery", "docs-review-all"]
    assert all_review_targets[-1].args == (
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
    )
    assert all_review_targets[-1].metadata == {
        "artifact_root": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review",
        "bundle_index_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/index.json",
        "drifted_readme_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/README-drifted.md",
        "render_output_dir": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/rendered",
        "render_manifest_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-manifest.json",
        "render_diff_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/render-review.patch",
        "fix_check_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-check.json",
        "fix_repair_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-repair.json",
        "fix_post_check_json_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/fix-post-check.json",
        "matrix_summary_path": "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review/matrix-summary.json",
    }

    with pytest.raises(ValueError, match="unknown smoke wrapper cli spec 'missing_smoke'"):
        smoke_wrapper_cli_spec("missing_smoke")


def _readme_shortcuts_from_examples(spec) -> tuple[str, ...]:
    return tuple(
        snippet
        for example in spec.examples[1:]
        if (snippet := example.render_readme_snippet(format_command=spec._format_readme_command)) is not None
    )


def _readme_section_from_spec_parts(spec) -> str:
    lines = [
        f"### {spec.readme_section_heading}",
        "",
        spec.readme_section_intro,
        "",
        *spec.readme_reference_block().splitlines(),
    ]
    intro_blocks = spec.readme_intro_blocks()
    if intro_blocks:
        lines.append("")
        for index, paragraph in enumerate(intro_blocks):
            if index:
                lines.append("")
            lines.append(paragraph)
    shortcut_lines = spec.readme_operator_shortcut_lines()
    if shortcut_lines:
        lines.extend(("", spec.readme_shortcut_heading, *shortcut_lines))
    return "\n".join(lines)


def test_smoke_wrapper_cli_spec_derives_readme_shortcuts_from_examples() -> None:
    standalone_spec = STANDALONE_SMOKE_CLI_SPEC
    selector = standalone_spec._build_doc_selector()

    assert standalone_spec.readme_reference_command() == ".venv/bin/python scripts/standalone_smoke.py"
    assert tuple(selector.resolve_target_names("docs-contract")) == STANDALONE_DOCS_CONTRACT_TARGET_NAMES
    assert standalone_spec.help_alias_lines() == tuple(
        f"{name} -> {', '.join(selector.resolve_display_names(name))}"
        for name in selector.alias_target_names
    )
    assert len(standalone_spec.help_example_lines()) == len(standalone_spec.examples)
    for example, help_line in zip(standalone_spec.examples, standalone_spec.help_example_lines(), strict=True):
        assert help_line.startswith(f"{example.command} # ")
    assert standalone_spec.readme_shortcut_snippets() == _readme_shortcuts_from_examples(standalone_spec)

    expected_all_shortcuts = list(standalone_spec.readme_shortcut_snippets())
    insert_at = standalone_spec.readme_extra_shortcut_insert_at
    assert insert_at is not None
    expected_all_shortcuts[insert_at:insert_at] = list(standalone_spec.readme_extra_shortcut_snippets)
    assert standalone_spec.readme_all_shortcut_snippets() == tuple(expected_all_shortcuts)
    assert standalone_spec.readme_operator_shortcut_lines() == tuple(
        f"- {snippet}" for snippet in standalone_spec.readme_all_shortcut_snippets()
    )


def test_select_alias_target_names_supports_any_all_and_candidate_filters() -> None:
    assert _select_alias_target_names(
        required_any_target_groups=(("docs", "docs-artifacts", "docs-rerun-hint"),),
        candidate_alias_names=("local", "docs-contract", "docs-focused"),
    ) == ("local", "docs-contract", "docs-focused")
    assert _select_alias_target_names(
        required_all_target_names=(
            "matrix-artifact-roots",
            "matrix-all-review-order",
            "matrix-all-review-missing-api-key",
            "matrix-docs-review-hint",
        ),
        required_any_target_groups=(("malformed-result", "malformed-detail"),),
    ) == ("docs-contract",)


@pytest.mark.parametrize(
    ("case", "expected_id"),
    [
        (SmokeWrapperSelectionCase(argv=(), expected_target_names=("alpha",)), "default"),
        (
            SmokeWrapperSelectionCase(argv=("docs-contract",), expected_target_names=("docs-rerun-hint",)),
            "docs-contract",
        ),
    ],
)
def test_smoke_wrapper_selection_case_id_tracks_requested_target_name(
    case: SmokeWrapperSelectionCase, expected_id: str
) -> None:
    assert smoke_wrapper_selection_case_id(case) == expected_id


def test_shared_smoke_wrapper_selection_cases_track_cli_spec_resolution() -> None:
    assert [case.expected_target_names for case in STANDALONE_SMOKE_SELECTION_CASES[:8]] == [
        STANDALONE_LOCAL_TARGET_NAMES,
        STANDALONE_LOCAL_TARGET_NAMES,
        STANDALONE_ALL_TARGET_NAMES,
        STANDALONE_CONTRACT_NEGATIVE_TARGET_NAMES,
        STANDALONE_DOCS_CONTRACT_TARGET_NAMES,
        STANDALONE_DOCS_PARITY_ONLY_TARGET_NAMES,
        STANDALONE_DOCS_FOCUSED_TARGET_NAMES,
        STANDALONE_DOCS_REVIEW_ONLY_TARGET_NAMES,
    ]
    assert [case.expected_target_names for case in SESSION_TRIAGE_SMOKE_SELECTION_CASES] == [
        SESSION_TRIAGE_SMOKE_CLI_SPEC.resolve_target_names(case.requested_target_name)
        for case in SESSION_TRIAGE_SMOKE_SELECTION_CASES
    ]
    assert [case.expected_target_names for case in SESSION_RECOVERY_SMOKE_SELECTION_CASES] == [
        SESSION_RECOVERY_SMOKE_CLI_SPEC.resolve_target_names(case.requested_target_name)
        for case in SESSION_RECOVERY_SMOKE_SELECTION_CASES
    ]
    assert [case.expected_target_names for case in SMOKE_MATRIX_SELECTION_CASES] == [
        SMOKE_MATRIX_CLI_SPEC.resolve_target_names(case.requested_target_name)
        for case in SMOKE_MATRIX_SELECTION_CASES
    ]
    assert [case.expected_target_args for case in SMOKE_MATRIX_SELECTION_CASES] == [
        SMOKE_MATRIX_CLI_SPEC.resolve_target_args(case.requested_target_name)
        for case in SMOKE_MATRIX_SELECTION_CASES
    ]


def test_standalone_docs_parity_follow_up_metadata_tracks_alias_groups() -> None:
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.rerun_target_name == "docs-parity-only"
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.docs_parity_target_names == STANDALONE_DOCS_PARITY_ONLY_TARGET_NAMES
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.requested_target_names == (
        "local",
        "docs-contract",
        "docs-parity-only",
        "docs-focused",
    )
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.default_requested_target_names == ("local",)
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.contract_requested_target_names == ("docs-contract",)
    assert STANDALONE_DOCS_PARITY_FOLLOW_UP.docs_review_requested_target_names == (
        "docs-focused",
    )


def test_standalone_follow_up_failure_fixtures_expose_target_lookup_and_failed_lines() -> None:
    fixture_sets: tuple[StandaloneFollowUpFailureFixtureSet, ...] = (
        STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES,
        STANDALONE_MALFORMED_CONTRACT_FAILURE_FIXTURES,
        STANDALONE_DOCS_REVIEW_FOLLOW_UP_FAILURE_FIXTURES,
    )

    for fixture_set in fixture_sets:
        assert fixture_set.target_names
        assert fixture_set.output_lines_by_target() == {
            fixture.failed_target_name: fixture.stdout_lines
            for fixture in fixture_set.fixtures
        }
        for fixture in fixture_set.fixtures:
            assert fixture.failed_line == fixture.stdout_lines[-1]
            assert fixture_set.fixture_for_target(fixture.failed_target_name) == fixture
            assert fixture_set.require_fixture_for_target(fixture.failed_target_name) == fixture
            assert fixture.failed_fast_message() == (
                f"{fixture.failed_target_name} smoke failed fast: {fixture.failed_line}"
            )
        assert fixture_set.fixture_for_target("missing") is None


def test_standalone_malformed_contract_failure_fixtures_reuse_shared_output_lines() -> None:
    assert STANDALONE_MALFORMED_CONTRACT_FAILURE_FIXTURES.output_lines_by_target() == (
        build_standalone_malformed_contract_failure_output_lines()
    )


def test_standalone_follow_up_failure_fixture_emits_observed_stdout_lines() -> None:
    fixture = STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES.require_fixture_for_target(
        "docs-artifacts"
    )

    stdout = StringIO()
    observed_lines: list[str] = []

    fixture.emit_stdout_lines(stdout=stdout, output_line_observer=observed_lines.append)

    assert stdout.getvalue().splitlines() == list(fixture.stdout_lines)
    assert observed_lines == [f"{line}\n" for line in fixture.stdout_lines]


def test_standalone_follow_up_failure_fixture_honors_shared_filter_and_observer() -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="docs-artifacts",
        stdout_lines=(
            "[standalone-smoke] summary: 1/1 targets passed in 0.50s",
            "visible= True",
            "hidden_failure= False",
        ),
    )

    stdout = StringIO()
    observed_lines: list[str] = []

    fixture.emit_stdout_lines(
        stdout=stdout,
        output_line_observer=observed_lines.append,
        output_line_filter=lambda line: not line.startswith("[") and not line.startswith("hidden_failure="),
    )

    assert stdout.getvalue() == "visible= True\n"
    assert observed_lines == [
        "[standalone-smoke] summary: 1/1 targets passed in 0.50s\n",
        "visible= True\n",
        "hidden_failure= False\n",
    ]


def test_standalone_follow_up_failure_fixture_emit_failed_target_run_reuses_shared_stdout_stderr_path() -> None:
    fixture = STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES.require_fixture_for_target(
        "docs-artifacts"
    )

    stdout = StringIO()
    stderr = StringIO()
    observed_lines: list[str] = []

    exit_code = fixture.emit_failed_target_run(
        stdout=stdout,
        stderr=stderr,
        output_line_observer=observed_lines.append,
        output_line_filter=lambda line: not line.startswith("fix_check_summary:"),
        target_name="docs-artifacts",
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [fixture.stdout_line(-1)]
    assert stderr.getvalue().strip() == fixture.failed_fast_message()
    assert observed_lines == [f"{line}\n" for line in fixture.stdout_lines]


def test_standalone_follow_up_failure_fixture_emit_target_run_supports_custom_exit_message() -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="live",
        stdout_lines=(
            "live_runtime_error: RuntimeError: OPENAI_API_KEY is required for live runtime mode",
            "live_runtime_requested= True",
        ),
    )

    stdout = StringIO()
    stderr = StringIO()
    observed_lines: list[str] = []

    exit_code = fixture.emit_target_run(
        stdout=stdout,
        stderr=stderr,
        stderr_message=fixture.exited_with_status_message(1),
        output_line_observer=observed_lines.append,
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == list(fixture.stdout_lines)
    assert stderr.getvalue().strip() == fixture.exited_with_status_message(1)
    assert observed_lines == [f"{line}\n" for line in fixture.stdout_lines]


def test_build_standalone_follow_up_failure_run_smoke_target_reuses_fixture_emission_path(
    tmp_path,
) -> None:
    fixture = STANDALONE_DOCS_PARITY_FOLLOW_UP_FAILURE_FIXTURES.require_fixture_for_target(
        "docs-artifacts"
    )
    fake_run_smoke_target = build_standalone_follow_up_failure_run_smoke_target(fixture)

    stdout = StringIO()
    stderr = StringIO()
    observed_lines: list[str] = []

    exit_code = fake_run_smoke_target(
        SmokeScriptTarget("docs-artifacts", tmp_path / "unused.py"),
        stdout=stdout,
        stderr=stderr,
        output_line_observer=observed_lines.append,
        output_line_filter=lambda line: not line.startswith("fix_check_summary:"),
    )

    assert exit_code == 1
    assert stdout.getvalue().splitlines() == [fixture.stdout_line(-1)]
    assert stderr.getvalue().strip() == fixture.failed_fast_message()
    assert observed_lines == [f"{line}\n" for line in fixture.stdout_lines]


def test_build_standalone_follow_up_failure_run_smoke_target_supports_custom_exit_message_and_filter(
    tmp_path,
) -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="live",
        stdout_lines=(
            "provider=fake-strands mode=fake",
            "live_runtime_requested= False",
        ),
    )
    fake_run_smoke_target = build_standalone_follow_up_failure_run_smoke_target(
        fixture,
        stderr_message=fixture.exited_with_status_message(1),
        output_line_filter=lambda _line: False,
    )

    stdout = StringIO()
    stderr = StringIO()
    observed_lines: list[str] = []

    exit_code = fake_run_smoke_target(
        SmokeScriptTarget("live", tmp_path / "unused.py"),
        stdout=stdout,
        stderr=stderr,
        output_line_observer=observed_lines.append,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue().strip() == fixture.exited_with_status_message(1)
    assert observed_lines == [f"{line}\n" for line in fixture.stdout_lines]


def test_build_standalone_follow_up_failure_run_smoke_target_ignores_other_targets(tmp_path) -> None:
    fixture = StandaloneFollowUpFailureFixture(
        failed_target_name="docs-artifacts",
        stdout_lines=("docs_artifacts_check= False",),
    )
    fake_run_smoke_target = build_standalone_follow_up_failure_run_smoke_target(fixture)

    stdout = StringIO()
    stderr = StringIO()

    exit_code = fake_run_smoke_target(
        SmokeScriptTarget("docs-review-hint", tmp_path / "unused.py"),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_standalone_smoke_failure_case_build_fixture_reuses_fixture_shape() -> None:
    failure_case = build_standalone_docs_contract_failure_cases()[1]

    assert failure_case.build_fixture() == StandaloneFollowUpFailureFixture(
        failed_target_name=failure_case.failed_target_name,
        stdout_lines=failure_case.stdout_lines,
    )


def test_build_timed_standalone_smoke_failure_cases_assigns_elapsed_seconds_in_order() -> None:
    cases = build_standalone_docs_contract_failure_cases()

    timed_cases = build_timed_standalone_smoke_failure_cases(
        cases,
        first_elapsed_seconds=1.8,
    )

    assert timed_cases[:3] == (
        TimedStandaloneSmokeFailureCase(cases[0], 1.8),
        TimedStandaloneSmokeFailureCase(cases[1], 2.1),
        TimedStandaloneSmokeFailureCase(cases[2], 2.4),
    )
    assert timed_cases[-1] == TimedStandaloneSmokeFailureCase(cases[-1], 3.6)


def test_standalone_smoke_failure_case_id_supports_default_target_only_and_prefixed_formats() -> None:
    case = build_standalone_docs_contract_failure_cases()[0]

    assert standalone_smoke_failure_case_id(case) == "docs-contract-docs-rerun-hint"
    assert standalone_smoke_failure_case_id(
        case,
        include_requested_target_name=False,
    ) == "docs-rerun-hint"
    assert standalone_smoke_failure_case_id(
        case,
        requested_target_name_prefix="default-",
    ) == "default-docs-rerun-hint"


def test_build_timed_standalone_smoke_failure_pytest_params_reuses_shared_id_formats() -> None:
    cases = build_standalone_docs_contract_failure_cases()[:2]
    params = build_timed_standalone_smoke_failure_pytest_params(
        cases,
        first_elapsed_seconds=1.8,
        include_requested_target_name_in_id=False,
    )

    assert [param.id for param in params] == ["docs-rerun-hint", "malformed-result"]
    assert [param.values for param in params] == [
        (cases[0], 1.8),
        (cases[1], 2.1),
    ]


def test_standalone_docs_review_follow_up_metadata_tracks_aliases_and_hint_selection() -> None:
    assert STANDALONE_DOCS_REVIEW_FOLLOW_UP.rerun_target_name == "docs-review-only"
    assert STANDALONE_DOCS_REVIEW_FOLLOW_UP.docs_review_target_names == STANDALONE_DOCS_REVIEW_ONLY_TARGET_NAMES
    assert STANDALONE_DOCS_REVIEW_FOLLOW_UP.requested_target_names == (
        "docs-contract",
        "docs-focused",
        "docs-review-only",
    )
    assert STANDALONE_DOCS_REVIEW_FOLLOW_UP.contract_requested_target_names == (
        "docs-contract",
    )
    assert STANDALONE_DOCS_REVIEW_FOLLOW_UP.alias_requested_target_names == (
        "docs-focused",
        "docs-review-only",
    )
    assert standalone_docs_review_follow_up_hint_for_failure(
        requested_target_name="docs-focused",
        target="matrix-docs-review-hint",
    ) == STANDALONE_DOCS_REVIEW_FOLLOW_UP.rerun_hint
    assert standalone_docs_review_follow_up_hint_for_failure(
        requested_target_name="docs-focused",
        target="docs",
    ) is None
    assert standalone_docs_review_follow_up_hint_for_failure(
        requested_target_name="matrix-docs-review-hint",
        target="matrix-docs-review-hint",
    ) is None


def test_build_standalone_docs_review_follow_up_failure_cases_tracks_alias_positions() -> None:
    cases = build_standalone_docs_review_follow_up_failure_cases()

    assert _failure_case_positions(cases) == [
        (
            "docs-contract",
            "matrix-artifact-roots",
            3,
            7,
        ),
        (
            "docs-contract",
            "matrix-all-review-order",
            4,
            7,
        ),
        (
            "docs-contract",
            "matrix-all-review-missing-api-key",
            5,
            7,
        ),
        (
            "docs-contract",
            "matrix-docs-review-hint",
            6,
            7,
        ),
        (
            "docs-focused",
            "matrix-artifact-roots",
            3,
            7,
        ),
        (
            "docs-focused",
            "matrix-all-review-order",
            4,
            7,
        ),
        (
            "docs-focused",
            "matrix-all-review-missing-api-key",
            5,
            7,
        ),
        (
            "docs-focused",
            "matrix-docs-review-hint",
            6,
            7,
        ),
        (
            "docs-review-only",
            "matrix-artifact-roots",
            0,
            4,
        ),
        (
            "docs-review-only",
            "matrix-all-review-order",
            1,
            4,
        ),
        (
            "docs-review-only",
            "matrix-all-review-missing-api-key",
            2,
            4,
        ),
        (
            "docs-review-only",
            "matrix-docs-review-hint",
            3,
            4,
        ),
    ]
    for case in cases:
        fixture = STANDALONE_DOCS_REVIEW_FOLLOW_UP_FAILURE_FIXTURES.fixture_for_target(
            case.failed_target_name
        )
        assert fixture is not None
        assert case.stdout_lines == fixture.stdout_lines
        assert case.failed_line == fixture.failed_line
        assert case.expected_hint == STANDALONE_DOCS_REVIEW_FOLLOW_UP.rerun_hint



def test_build_standalone_malformed_contract_failure_cases_tracks_alias_positions_and_hints() -> None:
    docs_contract_cases = build_standalone_malformed_contract_failure_cases(
        requested_target_name="docs-contract"
    )
    contract_negative_cases = build_standalone_malformed_contract_failure_cases(
        requested_target_name="contract-negative"
    )

    assert _failure_case_positions(docs_contract_cases) == [
        (
            "docs-contract",
            "malformed-result",
            1,
            7,
        ),
        (
            "docs-contract",
            "malformed-detail",
            2,
            7,
        ),
    ]
    for case in docs_contract_cases:
        fixture = STANDALONE_MALFORMED_CONTRACT_FAILURE_FIXTURES.fixture_for_target(
            case.failed_target_name
        )
        assert fixture is not None
        assert case.stdout_lines == fixture.stdout_lines
        assert case.failed_line == fixture.failed_line
        assert case.expected_hint == standalone_malformed_contract_hint_for_failure(
            requested_target_name=case.requested_target_name,
            target=case.failed_target_name,
        )

    assert _failure_case_positions(contract_negative_cases) == [
        (
            "contract-negative",
            "malformed-result",
            0,
            2,
        ),
        (
            "contract-negative",
            "malformed-detail",
            1,
            2,
        ),
    ]
    for case in contract_negative_cases:
        fixture = STANDALONE_MALFORMED_CONTRACT_FAILURE_FIXTURES.fixture_for_target(
            case.failed_target_name
        )
        assert fixture is not None
        assert case.stdout_lines == fixture.stdout_lines
        assert case.failed_line == fixture.failed_line
        assert case.expected_hint == standalone_malformed_contract_hint_for_failure(
            requested_target_name=case.requested_target_name,
            target=case.failed_target_name,
        )


def test_build_standalone_docs_contract_failure_cases_tracks_registry_derived_alias_selection() -> None:
    cases = build_standalone_docs_contract_failure_cases()

    assert [case.requested_target_name for case in cases] == ["docs-contract"] * len(
        STANDALONE_DOCS_CONTRACT_TARGET_NAMES
    )
    assert [case.failed_target_name for case in cases] == list(STANDALONE_DOCS_CONTRACT_TARGET_NAMES)


def test_smoke_wrapper_cli_specs_share_parser_and_readme_metadata(tmp_path) -> None:
    for spec in SMOKE_WRAPPER_CLI_SPECS:
        parser = spec.build_parser(script_dir=tmp_path)
        normalized_help = " ".join(parser.format_help().split())

        for snippet in spec.help_example_lines():
            assert snippet in normalized_help

        help_alias_lines = spec.help_alias_lines()
        if help_alias_lines:
            assert f"{spec.alias_heading}: {' '.join(help_alias_lines)}" in normalized_help

        assert spec.readme_required_snippets() == (
            spec.readme_reference_block(),
            *spec.readme_intro_blocks(),
            *spec.readme_all_shortcut_snippets(),
        )


def test_smoke_wrapper_cli_specs_render_readme_sections() -> None:
    for spec in SMOKE_WRAPPER_CLI_SPECS:
        assert spec.render_readme_section() == _readme_section_from_spec_parts(spec)


@pytest.mark.parametrize(
    (
        "default_target_name",
        "alias_target_names",
        "choice_target_names",
        "choice_display_names",
        "requested_target_name",
        "expected_message",
    ),
    [
        ("missing", {}, None, None, None, "unknown default smoke target 'missing'"),
        (
            "all",
            {"all": ("missing",)},
            None,
            None,
            None,
            "alias 'all' references unknown smoke targets: missing",
        ),
        (
            "local",
            {},
            {"local": ("missing",)},
            None,
            None,
            "choice 'local' references unknown smoke targets: missing",
        ),
        (
            "first",
            {},
            None,
            {"missing": ("first",)},
            None,
            "choice display names reference unknown smoke choices: missing",
        ),
        (
            "all",
            {"all": ("first",)},
            None,
            {"all": ("first", "second")},
            None,
            "choice display names must match target counts for: all",
        ),
        ("first", {}, None, None, "missing", "unknown smoke target 'missing'"),
    ],
)
def test_smoke_target_selector_validates_configuration(
    tmp_path,
    default_target_name,
    alias_target_names,
    choice_target_names,
    choice_display_names,
    requested_target_name,
    expected_message,
) -> None:
    script_path = _write_script(tmp_path, "first.py", "print('first_check= True', flush=True)\n")
    targets = {"first": SmokeScriptTarget("first", script_path)}
    if choice_display_names == {"all": ("first", "second")}:
        second_script = _write_script(tmp_path, "second.py", "print('second_check= True', flush=True)\n")
        targets["second"] = SmokeScriptTarget("second", second_script)

    if requested_target_name is None:
        with pytest.raises(ValueError, match=expected_message):
            SmokeTargetSelector(
                targets=targets,
                default_target_name=default_target_name,
                alias_target_names=alias_target_names,
                choice_target_names=choice_target_names,
                choice_display_names=choice_display_names,
            )
        return

    selector = SmokeTargetSelector(
        targets=targets,
        default_target_name=default_target_name,
        alias_target_names=alias_target_names,
        choice_target_names=choice_target_names,
        choice_display_names=choice_display_names,
    )

    with pytest.raises(ValueError, match=expected_message):
        selector.resolve_targets(requested_target_name)


def test_run_smoke_target_passes_script_args(tmp_path) -> None:
    script_path = _write_script(
        tmp_path,
        "args.py",
        """
        import sys

        print(f"argv_tail: {sys.argv[1:]}", flush=True)
        print("args_check= True", flush=True)
        """,
    )

    stdout = StringIO()
    stderr = StringIO()
    exit_code = run_smoke_target(
        SmokeScriptTarget("args", script_path, args=("all", "--flag")),
        stdout=stdout,
        stderr=stderr,
        python_executable=sys.executable,
    )

    assert exit_code == 0
    assert stdout.getvalue() == "argv_tail: ['all', '--flag']\nargs_check= True\n"
    assert stderr.getvalue() == ""
