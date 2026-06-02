from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_script_driver_source,
    detail_safe_text,
    emit_smoke_results,
    find_prefixed_line_index,
    run_python_driver_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
STANDALONE_SMOKE_SCRIPT_PATH = SCRIPT_DIR / "standalone_smoke.py"
FAILED_LINE_PREFIX = "docs-artifacts smoke failed fast: "
HINT_PREFIX = "[standalone-smoke] hint: standalone wrapper docs drift is easiest to isolate with "
SUMMARY_PREFIX = "[standalone-smoke] summary: 5/6 targets passed before failure in "
EXPECTED_FIX_SUMMARY_LINE = (
    "fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke"
)
EXPECTED_FALSE_LINE = "fix_post_check= False"


def _subprocess_driver_source() -> str:
    return build_script_driver_source(
        repo_root=REPO_ROOT,
        script_path=STANDALONE_SMOKE_SCRIPT_PATH,
        module_name="scripts.standalone_docs_rerun_hint_smoke_target",
        argv=["local"],
        hook_source="""
        from strands_agent_tui.testing import smoke_runner

        def fake_run_smoke_target(target, **kwargs):
            observer = kwargs.get('output_line_observer')
            stdout = kwargs['stdout']
            stderr = kwargs['stderr']
            if target.name == 'docs-artifacts':
                for line in (
                    'fix_check_summary: smoke README drift detected in 1 section(s) for README.md: standalone_smoke\\n',
                    'fix_post_check= False\\n',
                ):
                    if observer is not None:
                        observer(line)
                    print(line, end='', file=stdout)
                stdout.flush()
                print('docs-artifacts smoke failed fast: fix_post_check= False', file=stderr)
                return 1
            return 0

        smoke_runner.run_smoke_target = fake_run_smoke_target
        module.run_smoke_target = fake_run_smoke_target
        """,
    )


def run_standalone_docs_rerun_hint_smoke() -> list[tuple[str, object]]:
    smoke_run = run_python_driver_in_temp_checkout(
        driver_source=_subprocess_driver_source(),
        temp_prefix="standalone-docs-rerun-hint-",
        driver_filename="run_standalone_docs_rerun_hint.py",
    )
    try:
        stdout_lines = smoke_run.stdout_lines
        stderr_lines = smoke_run.stderr_lines
        failed_index = find_prefixed_line_index(stderr_lines, FAILED_LINE_PREFIX)
        hint_index = find_prefixed_line_index(stderr_lines, HINT_PREFIX)
        summary_index = find_prefixed_line_index(stderr_lines, SUMMARY_PREFIX)

        failed_line = stderr_lines[failed_index] if failed_index is not None else ""
        hint_line = stderr_lines[hint_index] if hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stdout_fix_check_summary", stdout_lines[0] if stdout_lines else ""),
            (
                "stdout_false_line",
                detail_safe_text(stdout_lines[1]) if len(stdout_lines) > 1 else "",
            ),
            ("stderr_failed_line", detail_safe_text(failed_line)),
            ("stderr_hint_line", hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("fix_check_summary_present", EXPECTED_FIX_SUMMARY_LINE in stdout_lines),
            ("false_line_present", EXPECTED_FALSE_LINE in stdout_lines),
            ("failed_line_present", bool(failed_line)),
            ("hint_line_present", bool(hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "hint_after_failed_line",
                failed_index is not None and hint_index is not None and failed_index < hint_index,
            ),
            (
                "hint_before_failure_summary",
                hint_index is not None and summary_index is not None and hint_index < summary_index,
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_standalone_docs_rerun_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
