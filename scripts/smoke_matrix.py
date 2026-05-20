from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TextIO

from strands_agent_tui.testing import SmokeCliExample, SmokeScriptTarget, build_smoke_cli_parser, run_smoke_target

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_BUNDLES = {
    "standalone-local": SmokeScriptTarget("standalone-local", SCRIPT_DIR / "standalone_smoke.py"),
    "standalone-all": SmokeScriptTarget("standalone-all", SCRIPT_DIR / "standalone_smoke.py", args=("all",)),
    "triage": SmokeScriptTarget("triage", SCRIPT_DIR / "session_triage_smoke.py"),
    "recovery": SmokeScriptTarget("recovery", SCRIPT_DIR / "session_recovery_smoke.py"),
}
LOCAL_BUNDLE_NAMES = ["standalone-local", "triage", "recovery"]
ALL_BUNDLE_NAMES = ["standalone-all", "triage", "recovery"]


def resolve_bundle_names(requested_target_name: str | None = None) -> list[str]:
    target_name = "local" if requested_target_name is None else requested_target_name
    if target_name == "standalone":
        return ["standalone-local"]
    if target_name == "triage":
        return ["triage"]
    if target_name == "recovery":
        return ["recovery"]
    if target_name == "all":
        return ALL_BUNDLE_NAMES
    if target_name == "local":
        return LOCAL_BUNDLE_NAMES
    raise ValueError(f"unknown smoke bundle {target_name!r}")


def _emit_bundle_summary(message: str, *, stream: TextIO) -> None:
    print(f"[smoke-matrix] {message}", file=stream)
    stream.flush()


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
        _emit_bundle_summary(f"running {target.name}", stream=stdout)
        started_at = perf_counter()
        exit_code = run_smoke_target(target, stdout=stdout, stderr=stderr)
        elapsed = perf_counter() - started_at
        if exit_code != 0:
            _emit_bundle_summary(f"{target.name} failed in {elapsed:.2f}s", stream=stderr)
            total_elapsed = perf_counter() - total_started_at
            _emit_bundle_summary(
                f"summary: {passed_count}/{total_count} bundles passed before failure in {total_elapsed:.2f}s",
                stream=stderr,
            )
            return exit_code
        passed_count += 1
        _emit_bundle_summary(f"{target.name} passed in {elapsed:.2f}s", stream=stdout)

    total_elapsed = perf_counter() - total_started_at
    _emit_bundle_summary(
        f"summary: {passed_count}/{total_count} bundles passed in {total_elapsed:.2f}s",
        stream=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bundle_names = resolve_bundle_names(args.target)
    return run_smoke_matrix([SMOKE_BUNDLES[bundle_name] for bundle_name in bundle_names])


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_parser(
        description=(
            "Run standalone, session-triage, and recovery smoke bundles together with fail-fast handling. "
            "The default 'local' matrix excludes the opt-in live runtime smoke target."
        ),
        choices=("standalone", "triage", "recovery", "local", "all"),
        default_target_name="local",
        resolve_target_names=resolve_bundle_names,
        item_help="Which smoke bundle or bundle matrix to run.",
        alias_target_names={
            "local": tuple(LOCAL_BUNDLE_NAMES),
            "all": tuple(ALL_BUNDLE_NAMES),
        },
        alias_heading="Bundle aliases",
        examples=(
            SmokeCliExample("smoke_matrix.py"),
            SmokeCliExample("smoke_matrix.py standalone", target_name="standalone", description="single bundle"),
            SmokeCliExample("smoke_matrix.py triage", target_name="triage", description="single bundle"),
            SmokeCliExample("smoke_matrix.py recovery", target_name="recovery", description="single bundle"),
            SmokeCliExample("smoke_matrix.py all", target_name="all"),
        ),
        single_choice_description="single bundle",
    )


if __name__ == "__main__":
    raise SystemExit(main())
