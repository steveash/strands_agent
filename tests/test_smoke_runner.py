from __future__ import annotations

import sys
from io import StringIO
from textwrap import dedent

import pytest

from strands_agent_tui.testing.smoke_runner import (
    NON_MATRIX_SMOKE_WRAPPER_CLI_SPECS,
    NON_MATRIX_SMOKE_WRAPPER_METADATA,
    NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES,
    SMOKE_MATRIX_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_WRAPPER,
    SESSION_TRIAGE_SMOKE_CLI_SPEC,
    SESSION_TRIAGE_SMOKE_WRAPPER,
    SMOKE_MATRIX_WRAPPER,
    SMOKE_WRAPPER_CLI_SPECS,
    STANDALONE_SMOKE_CLI_SPEC,
    STANDALONE_SMOKE_WRAPPER,
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    SmokeWrapperMetadata,
    build_smoke_cli_parser,
    run_smoke_target,
    run_smoke_targets,
    smoke_wrapper_cli_spec,
    smoke_wrapper_metadata_from_specs,
    summary_line_prefixes,
)


def _write_script(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(dedent(body), encoding="utf-8")
    return path


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


def test_smoke_target_selector_supports_public_choices_backed_by_hidden_target_names(tmp_path) -> None:
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
            "standalone": ("standalone",),
            "triage": ("triage",),
            "local": ("standalone", "triage"),
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


def test_smoke_wrapper_cli_spec_registry_helper_resolves_defaults_and_unknown_names(tmp_path) -> None:
    spec = smoke_wrapper_cli_spec("smoke_matrix")

    assert spec.default_target_names() == ("standalone-local", "triage", "recovery")
    assert spec.default_display_names() == ("standalone", "triage", "recovery")
    assert spec.resolve_target_names("all") == ("standalone-all", "triage", "recovery")
    assert spec.resolve_display_names("all") == ("standalone (live-inclusive)", "triage", "recovery")
    assert [target.name for target in spec.default_targets(script_dir=tmp_path)] == [
        "standalone-local",
        "triage",
        "recovery",
    ]
    assert [target.name for target in spec.resolve_targets(script_dir=tmp_path, requested_target_name="standalone")] == [
        "standalone-local"
    ]

    with pytest.raises(ValueError, match="unknown smoke wrapper cli spec 'missing_smoke'"):
        smoke_wrapper_cli_spec("missing_smoke")


def test_smoke_wrapper_cli_specs_share_parser_and_readme_metadata(tmp_path) -> None:
    standalone_parser = STANDALONE_SMOKE_CLI_SPEC.build_parser(script_dir=tmp_path)
    triage_parser = SESSION_TRIAGE_SMOKE_CLI_SPEC.build_parser(script_dir=tmp_path)
    recovery_parser = SESSION_RECOVERY_SMOKE_CLI_SPEC.build_parser(script_dir=tmp_path)
    matrix_parser = SMOKE_MATRIX_CLI_SPEC.build_parser(script_dir=tmp_path)

    standalone_help = " ".join(standalone_parser.format_help().split())
    triage_help = " ".join(triage_parser.format_help().split())
    recovery_help = " ".join(recovery_parser.format_help().split())
    matrix_help = " ".join(matrix_parser.format_help().split())

    assert "standalone_smoke.py local # local alias -> summary-utils, shell-tool, replay" in standalone_help
    assert "session_triage_smoke.py both # both alias -> picker, switcher" in triage_help
    assert (
        "session_recovery_smoke.py all # all alias -> approval, approval-restart, session-state, "
        "live-restore, live-restore-denied"
    ) in recovery_help
    assert "smoke_matrix.py local # local alias -> standalone, triage, recovery" in matrix_help
    assert "smoke_matrix.py all # all alias -> standalone (live-inclusive), triage, recovery" in matrix_help

    assert STANDALONE_SMOKE_CLI_SPEC.readme_required_snippets() == (
        ".venv/bin/python scripts/standalone_smoke.py",
        "default `local` bundle runs `summary_utils`, `shell_tool`, and `replay` smokes together",
        "`.venv/bin/python scripts/standalone_smoke.py local` explicitly re-runs the default `local` alias (`summary_utils`, `shell_tool`, `replay`)",
        "`.venv/bin/python scripts/standalone_smoke.py all` runs the live-inclusive alias (`summary_utils`, `shell_tool`, `replay`, `live`)",
        "`.venv/bin/python scripts/standalone_smoke.py replay` runs just the replay smoke target",
    )
    assert SMOKE_MATRIX_CLI_SPEC.readme_required_snippets() == (
        ".venv/bin/python scripts/smoke_matrix.py",
        "default `local` matrix runs the standalone local bundle plus the session-triage and recovery bundles together",
        "Use `.venv/bin/python scripts/smoke_matrix.py all` after exporting live-runtime env vars if you want the `all` alias to swap in the live-inclusive standalone bundle.",
        "`.venv/bin/python scripts/smoke_matrix.py local` explicitly re-runs the default local matrix (`standalone`, `triage`, `recovery`)",
        "`.venv/bin/python scripts/smoke_matrix.py all` swaps in the live-inclusive standalone bundle (`standalone (live-inclusive)`, `triage`, `recovery`)",
        "`.venv/bin/python scripts/smoke_matrix.py standalone` runs only the standalone local bundle",
        "`.venv/bin/python scripts/smoke_matrix.py triage` runs only the session-triage bundle",
        "`.venv/bin/python scripts/smoke_matrix.py recovery` runs only the recovery bundle",
    )


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

    if requested_target_name is None:
        with pytest.raises(ValueError, match=expected_message):
            SmokeTargetSelector(
                targets={"first": SmokeScriptTarget("first", script_path)},
                default_target_name=default_target_name,
                alias_target_names=alias_target_names,
                choice_target_names=choice_target_names,
                choice_display_names=choice_display_names,
            )
        return

    selector = SmokeTargetSelector(
        targets={"first": SmokeScriptTarget("first", script_path)},
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
