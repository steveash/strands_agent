from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, run_smoke_targets

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET_NAMES = ["picker", "switcher"]
SMOKE_TARGETS = {
    "picker": SmokeScriptTarget("picker", SCRIPT_DIR / "session_picker_smoke.py"),
    "switcher": SmokeScriptTarget("switcher", SCRIPT_DIR / "session_switcher_smoke.py"),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run picker/switcher smoke scripts and fail fast on any emitted '= False' check.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=["picker", "switcher", "both"],
        default="both",
        help="Which session-triage smoke surface to run.",
    )
    args = parser.parse_args(argv)

    target_names = [args.target] if args.target != "both" else DEFAULT_TARGET_NAMES
    return run_smoke_targets([SMOKE_TARGETS[target_name] for target_name in target_names])


if __name__ == "__main__":
    raise SystemExit(main())
