from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, run_smoke_targets

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_TARGETS = {
    "summary-utils": SmokeScriptTarget("summary-utils", SCRIPT_DIR / "summary_utils_smoke.py"),
    "shell-tool": SmokeScriptTarget("shell-tool", SCRIPT_DIR / "shell_tool_smoke.py"),
    "replay": SmokeScriptTarget("replay", SCRIPT_DIR / "replay_smoke.py"),
    "live": SmokeScriptTarget("live", SCRIPT_DIR / "live_smoke.py"),
}
LOCAL_TARGET_NAMES = ["summary-utils", "shell-tool", "replay"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run standalone smoke scripts and fail fast on any emitted '= False' check. "
            "The default 'local' bundle excludes the live runtime target."
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=[*SMOKE_TARGETS, "local", "all"],
        default="local",
        help="Which standalone smoke surface to run.",
    )
    args = parser.parse_args(argv)

    if args.target == "local":
        target_names = LOCAL_TARGET_NAMES
    elif args.target == "all":
        target_names = list(SMOKE_TARGETS)
    else:
        target_names = [args.target]
    return run_smoke_targets([SMOKE_TARGETS[target_name] for target_name in target_names])


if __name__ == "__main__":
    raise SystemExit(main())
