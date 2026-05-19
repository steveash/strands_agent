from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, SmokeTargetSelector, run_smoke_targets

SCRIPT_DIR = Path(__file__).resolve().parent
SUMMARY_LABEL = "standalone-smoke"
SMOKE_TARGETS = {
    "summary-utils": SmokeScriptTarget("summary-utils", SCRIPT_DIR / "summary_utils_smoke.py"),
    "shell-tool": SmokeScriptTarget("shell-tool", SCRIPT_DIR / "shell_tool_smoke.py"),
    "replay": SmokeScriptTarget("replay", SCRIPT_DIR / "replay_smoke.py"),
    "live": SmokeScriptTarget("live", SCRIPT_DIR / "live_smoke.py"),
}
DEFAULT_TARGET_NAMES = ["summary-utils", "shell-tool", "replay"]
ALL_TARGET_NAMES = [*DEFAULT_TARGET_NAMES, "live"]
TARGET_SELECTOR = SmokeTargetSelector(
    targets=SMOKE_TARGETS,
    default_target_name="local",
    alias_target_names={
        "local": tuple(DEFAULT_TARGET_NAMES),
        "all": tuple(ALL_TARGET_NAMES),
    },
)


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
        choices=TARGET_SELECTOR.choices,
        default=TARGET_SELECTOR.default_target_name,
        help="Which standalone smoke surface to run.",
    )
    args = parser.parse_args(argv)

    return run_smoke_targets(
        TARGET_SELECTOR.resolve_targets(args.target),
        summary_label=SUMMARY_LABEL,
    )


if __name__ == "__main__":
    raise SystemExit(main())
