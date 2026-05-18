from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TextIO

from strands_agent_tui.testing import SmokeScriptTarget, run_smoke_target

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_BUNDLES = {
    "standalone-local": SmokeScriptTarget("standalone-local", SCRIPT_DIR / "standalone_smoke.py"),
    "standalone-all": SmokeScriptTarget("standalone-all", SCRIPT_DIR / "standalone_smoke.py", args=("all",)),
    "triage": SmokeScriptTarget("triage", SCRIPT_DIR / "session_triage_smoke.py"),
    "recovery": SmokeScriptTarget("recovery", SCRIPT_DIR / "session_recovery_smoke.py"),
}
LOCAL_BUNDLE_NAMES = ["standalone-local", "triage", "recovery"]
ALL_BUNDLE_NAMES = ["standalone-all", "triage", "recovery"]


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
    parser = argparse.ArgumentParser(
        description=(
            "Run standalone, session-triage, and recovery smoke bundles together with fail-fast handling. "
            "The default 'local' matrix excludes the opt-in live runtime smoke target."
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=["standalone", "triage", "recovery", "local", "all"],
        default="local",
        help="Which smoke bundle or bundle matrix to run.",
    )
    args = parser.parse_args(argv)

    if args.target == "standalone":
        bundle_names = ["standalone-local"]
    elif args.target == "triage":
        bundle_names = ["triage"]
    elif args.target == "recovery":
        bundle_names = ["recovery"]
    elif args.target == "all":
        bundle_names = ALL_BUNDLE_NAMES
    else:
        bundle_names = LOCAL_BUNDLE_NAMES

    return run_smoke_matrix([SMOKE_BUNDLES[bundle_name] for bundle_name in bundle_names])


if __name__ == "__main__":
    raise SystemExit(main())
