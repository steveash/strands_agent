from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SESSION_TRIAGE_SMOKE_WRAPPER,
    emit_smoke_results,
    find_prefixed_line_index,
    run_script_module_main_via_driver_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SESSION_TRIAGE_SMOKE_SCRIPT_PATH = SCRIPT_DIR / "session_triage_smoke.py"


def _line_at(lines: list[str], index: int | None) -> str:
    return "" if index is None else lines[index]


def run_session_triage_intervention_mix_smoke() -> list[tuple[str, object]]:
    smoke_run = run_script_module_main_via_driver_in_temp_checkout(
        repo_root=REPO_ROOT,
        script_path=SESSION_TRIAGE_SMOKE_SCRIPT_PATH,
        module_name="scripts.session_triage_intervention_mix_smoke_target",
        argv=["both"],
        temp_prefix="session-triage-intervention-mix-",
        driver_filename="run_session_triage_intervention_mix.py",
    )
    try:
        stdout_lines = smoke_run.stdout_lines
        picker_surface_index = find_prefixed_line_index(stdout_lines, "picker_intervention_surface= ")
        picker_target_mix_index = find_prefixed_line_index(stdout_lines, "picker_intervention_target_mix= ")
        picker_continuation_mix_index = find_prefixed_line_index(
            stdout_lines,
            "picker_intervention_continuation_mix= ",
        )
        switcher_filter_index = find_prefixed_line_index(stdout_lines, "switcher_intervention_filter= ")
        switcher_target_mix_index = find_prefixed_line_index(stdout_lines, "switcher_intervention_target_mix= ")
        switcher_continuation_mix_index = find_prefixed_line_index(
            stdout_lines,
            "switcher_intervention_continuation_mix= ",
        )
        summary_index = find_prefixed_line_index(
            stdout_lines,
            SESSION_TRIAGE_SMOKE_WRAPPER.summary_line_prefix,
        )

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stdout_picker_surface_line", _line_at(stdout_lines, picker_surface_index)),
            ("stdout_picker_target_mix_line", _line_at(stdout_lines, picker_target_mix_index)),
            (
                "stdout_picker_continuation_mix_line",
                _line_at(stdout_lines, picker_continuation_mix_index),
            ),
            ("stdout_switcher_filter_line", _line_at(stdout_lines, switcher_filter_index)),
            ("stdout_switcher_target_mix_line", _line_at(stdout_lines, switcher_target_mix_index)),
            (
                "stdout_switcher_continuation_mix_line",
                _line_at(stdout_lines, switcher_continuation_mix_index),
            ),
            ("stdout_summary_line", _line_at(stdout_lines, summary_index)),
            ("stderr_summary", smoke_run.stderr.strip()),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_zero", smoke_run.exit_code == 0),
            ("stderr_empty", smoke_run.stderr == ""),
            ("picker_surface_line_present", picker_surface_index is not None),
            ("picker_target_mix_line_present", picker_target_mix_index is not None),
            ("picker_continuation_mix_line_present", picker_continuation_mix_index is not None),
            ("switcher_filter_line_present", switcher_filter_index is not None),
            ("switcher_target_mix_line_present", switcher_target_mix_index is not None),
            (
                "switcher_continuation_mix_line_present",
                switcher_continuation_mix_index is not None,
            ),
            ("summary_line_present", summary_index is not None),
            (
                "picker_target_mix_after_picker_surface",
                picker_surface_index is not None
                and picker_target_mix_index is not None
                and picker_surface_index < picker_target_mix_index,
            ),
            (
                "picker_continuation_mix_after_picker_target_mix",
                picker_target_mix_index is not None
                and picker_continuation_mix_index is not None
                and picker_target_mix_index < picker_continuation_mix_index,
            ),
            (
                "switcher_filter_after_picker_continuation_mix",
                picker_continuation_mix_index is not None
                and switcher_filter_index is not None
                and picker_continuation_mix_index < switcher_filter_index,
            ),
            (
                "switcher_target_mix_after_switcher_filter",
                switcher_filter_index is not None
                and switcher_target_mix_index is not None
                and switcher_filter_index < switcher_target_mix_index,
            ),
            (
                "switcher_continuation_mix_after_switcher_target_mix",
                switcher_target_mix_index is not None
                and switcher_continuation_mix_index is not None
                and switcher_target_mix_index < switcher_continuation_mix_index,
            ),
            (
                "summary_after_switcher_continuation_mix",
                switcher_continuation_mix_index is not None
                and summary_index is not None
                and switcher_continuation_mix_index < summary_index,
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_session_triage_intervention_mix_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
