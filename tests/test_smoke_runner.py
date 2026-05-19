from __future__ import annotations

import sys
from io import StringIO
from textwrap import dedent

from strands_agent_tui.testing.smoke_runner import SmokeScriptTarget, run_smoke_target, run_smoke_targets


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
        summary_label="bundle-smoke",
    )

    assert exit_code == 0
    assert stdout.getvalue() == (
        "first_check= True\n"
        "second_check= True\n"
        "[bundle-smoke] summary: 2/2 targets passed in 1.25s\n"
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
        summary_label="bundle-smoke",
    )

    assert exit_code == 1
    assert stdout.getvalue() == "first_check= True\nsecond_check= False\n"
    assert stderr.getvalue().splitlines() == [
        "second smoke failed fast: second_check= False",
        "[bundle-smoke] summary: 1/2 targets passed before failure in 2.50s",
    ]


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
