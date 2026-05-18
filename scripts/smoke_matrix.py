from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, run_smoke_targets

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_BUNDLES = {
    "standalone-local": SmokeScriptTarget("standalone-local", SCRIPT_DIR / "standalone_smoke.py"),
    "standalone-all": SmokeScriptTarget("standalone-all", SCRIPT_DIR / "standalone_smoke.py", args=("all",)),
    "triage": SmokeScriptTarget("triage", SCRIPT_DIR / "session_triage_smoke.py"),
    "recovery": SmokeScriptTarget("recovery", SCRIPT_DIR / "session_recovery_smoke.py"),
}
LOCAL_BUNDLE_NAMES = ["standalone-local", "triage", "recovery"]
ALL_BUNDLE_NAMES = ["standalone-all", "triage", "recovery"]


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

    return run_smoke_targets([SMOKE_BUNDLES[bundle_name] for bundle_name in bundle_names])


if __name__ == "__main__":
    raise SystemExit(main())
