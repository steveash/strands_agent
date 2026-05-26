from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TextIO

from strands_agent_tui.testing import (
    NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES,
    SMOKE_MATRIX_WRAPPER,
    SmokeScriptTarget,
    run_smoke_target,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
CLI_SPEC = smoke_wrapper_cli_spec("smoke_matrix")
SMOKE_BUNDLES = CLI_SPEC.build_targets(script_dir=SCRIPT_DIR)
LOCAL_BUNDLE_NAMES = list(CLI_SPEC.default_target_names())
ALL_BUNDLE_NAMES = list(CLI_SPEC.resolve_target_names("all"))
SUPPRESSED_NESTED_SUMMARY_PREFIXES = NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES
LIVE_INCLUSIVE_STANDALONE_TARGET_NAME = "standalone-all"
LIVE_RUNTIME_REQUESTED_FALSE_LINE = "live_runtime_requested= False"
LIVE_RUNTIME_API_KEY_ERROR = "OPENAI_API_KEY is required for live runtime mode"


def _emit_matrix_line(message: str, *, stream) -> None:
    print(SMOKE_MATRIX_WRAPPER.format_line(message), file=stream)
    stream.flush()


def _should_emit_bundle_output_line(line: str) -> bool:
    normalized_line = line.rstrip("\n")
    return not any(normalized_line.startswith(prefix) for prefix in SUPPRESSED_NESTED_SUMMARY_PREFIXES)


def _live_inclusive_failure_hint(target: SmokeScriptTarget, observed_lines: Sequence[str]) -> str | None:
    if target.name != LIVE_INCLUSIVE_STANDALONE_TARGET_NAME:
        return None
    normalized_lines = [line.rstrip("\n") for line in observed_lines]
    if any(LIVE_RUNTIME_REQUESTED_FALSE_LINE in line for line in normalized_lines):
        return (
            "hint: `smoke_matrix.py all` swaps in `standalone_smoke.py all`; export "
            "`STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
            "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning the live-inclusive matrix."
        )
    if any(LIVE_RUNTIME_API_KEY_ERROR in line for line in normalized_lines):
        return (
            "hint: `smoke_matrix.py all` reached the live runtime, but `OPENAI_API_KEY` was missing; "
            "export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
        )
    return None


def run_smoke_matrix(
    targets: Sequence[SmokeScriptTarget],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    total_started_at = perf_counter()
    passed_count = 0
    total_count = len(targets)

    for target in targets:
        _emit_matrix_line(SMOKE_MATRIX_WRAPPER.running_message(item_name=target.display_label), stream=stdout)
        started_at = perf_counter()
        observed_lines: list[str] = []
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            output_line_filter=_should_emit_bundle_output_line,
            output_line_observer=observed_lines.append,
        )
        elapsed = perf_counter() - started_at
        if exit_code != 0:
            _emit_matrix_line(
                SMOKE_MATRIX_WRAPPER.failed_message(item_name=target.display_label, elapsed_seconds=elapsed),
                stream=stderr,
            )
            hint = _live_inclusive_failure_hint(target, observed_lines)
            if hint is not None:
                _emit_matrix_line(hint, stream=stderr)
            total_elapsed = perf_counter() - total_started_at
            _emit_matrix_line(
                SMOKE_MATRIX_WRAPPER.failure_summary_message(
                    passed_count=passed_count,
                    total_count=total_count,
                    elapsed_seconds=total_elapsed,
                ),
                stream=stderr,
            )
            return exit_code
        passed_count += 1
        _emit_matrix_line(
            SMOKE_MATRIX_WRAPPER.passed_message(item_name=target.display_label, elapsed_seconds=elapsed),
            stream=stdout,
        )

    total_elapsed = perf_counter() - total_started_at
    _emit_matrix_line(
        SMOKE_MATRIX_WRAPPER.success_summary_message(
            passed_count=passed_count,
            total_count=total_count,
            elapsed_seconds=total_elapsed,
        ),
        stream=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_smoke_matrix(CLI_SPEC.resolve_targets(script_dir=SCRIPT_DIR, requested_target_name=args.target))


def build_parser() -> argparse.ArgumentParser:
    return CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
