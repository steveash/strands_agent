from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SESSION_TRIAGE_SMOKE_WRAPPER,
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    build_smoke_cli_parser,
    run_smoke_targets,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET_NAMES = ["picker", "switcher"]
SMOKE_TARGETS = {
    "picker": SmokeScriptTarget("picker", SCRIPT_DIR / "session_picker_smoke.py"),
    "switcher": SmokeScriptTarget("switcher", SCRIPT_DIR / "session_switcher_smoke.py"),
}
TARGET_SELECTOR = SmokeTargetSelector(
    targets=SMOKE_TARGETS,
    default_target_name="both",
    alias_target_names={
        "both": tuple(DEFAULT_TARGET_NAMES),
        "all": tuple(DEFAULT_TARGET_NAMES),
    },
)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_parser(
        description="Run picker/switcher smoke scripts and fail fast on any emitted '= False' check.",
        choices=TARGET_SELECTOR.choices,
        default_target_name=TARGET_SELECTOR.default_target_name,
        resolve_target_names=TARGET_SELECTOR.resolve_target_names,
        item_help="Which session-triage smoke surface to run.",
        alias_target_names=TARGET_SELECTOR.alias_target_names,
        examples=(
            SmokeCliExample("session_triage_smoke.py"),
            SmokeCliExample("session_triage_smoke.py all", target_name="all"),
            SmokeCliExample("session_triage_smoke.py picker", target_name="picker"),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        TARGET_SELECTOR.resolve_targets(args.target),
        wrapper_metadata=SESSION_TRIAGE_SMOKE_WRAPPER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
