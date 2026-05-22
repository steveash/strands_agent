from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TextIO

from strands_agent_tui.testing import (
    SMOKE_MATRIX_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_WRAPPER,
    SESSION_TRIAGE_SMOKE_WRAPPER,
    SMOKE_MATRIX_WRAPPER,
    SmokeScriptTarget,
    STANDALONE_SMOKE_WRAPPER,
    run_smoke_target,
    summary_line_prefixes,
)

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_SELECTOR = SMOKE_MATRIX_CLI_SPEC.build_target_selector(script_dir=SCRIPT_DIR)
SMOKE_BUNDLES = TARGET_SELECTOR.targets
LOCAL_BUNDLE_NAMES = list(SMOKE_MATRIX_CLI_SPEC.alias_target_names["local"])
ALL_BUNDLE_NAMES = list(SMOKE_MATRIX_CLI_SPEC.alias_target_names["all"])
BUNDLE_SELECTOR = TARGET_SELECTOR
SUPPRESSED_NESTED_SUMMARY_PREFIXES = summary_line_prefixes(
    (
        STANDALONE_SMOKE_WRAPPER,
        SESSION_TRIAGE_SMOKE_WRAPPER,
        SESSION_RECOVERY_SMOKE_WRAPPER,
    )
)


def _emit_matrix_line(message: str, *, stream) -> None:
    print(SMOKE_MATRIX_WRAPPER.format_line(message), file=stream)
    stream.flush()


def _should_emit_bundle_output_line(line: str) -> bool:
    normalized_line = line.rstrip("\n")
    return not any(normalized_line.startswith(prefix) for prefix in SUPPRESSED_NESTED_SUMMARY_PREFIXES)


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
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            output_line_filter=_should_emit_bundle_output_line,
        )
        elapsed = perf_counter() - started_at
        if exit_code != 0:
            _emit_matrix_line(
                SMOKE_MATRIX_WRAPPER.failed_message(item_name=target.display_label, elapsed_seconds=elapsed),
                stream=stderr,
            )
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
    return run_smoke_matrix(BUNDLE_SELECTOR.resolve_targets(args.target))


def build_parser() -> argparse.ArgumentParser:
    return SMOKE_MATRIX_CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
