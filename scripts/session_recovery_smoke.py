from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    build_smoke_cli_parser,
    run_smoke_targets,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SUMMARY_LABEL = "session-recovery-smoke"
DEFAULT_TARGET_NAMES = [
    "approval",
    "approval-restart",
    "session-state",
    "live-restore",
    "live-restore-denied",
]
SMOKE_TARGETS = {
    "approval": SmokeScriptTarget("approval", SCRIPT_DIR / "approval_smoke.py"),
    "approval-restart": SmokeScriptTarget("approval-restart", SCRIPT_DIR / "approval_restart_smoke.py"),
    "session-state": SmokeScriptTarget("session-state", SCRIPT_DIR / "session_state_smoke.py"),
    "live-restore": SmokeScriptTarget("live-restore", SCRIPT_DIR / "live_restore_smoke.py"),
    "live-restore-denied": SmokeScriptTarget("live-restore-denied", SCRIPT_DIR / "live_restore_denied_smoke.py"),
}
TARGET_SELECTOR = SmokeTargetSelector(
    targets=SMOKE_TARGETS,
    default_target_name="all",
    alias_target_names={"all": tuple(DEFAULT_TARGET_NAMES)},
)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_parser(
        description="Run approval/session-state/live-restore smoke scripts and fail fast on any emitted '= False' check.",
        choices=TARGET_SELECTOR.choices,
        default_target_name=TARGET_SELECTOR.default_target_name,
        resolve_target_names=TARGET_SELECTOR.resolve_target_names,
        item_help="Which recovery smoke surface to run.",
        alias_target_names=TARGET_SELECTOR.alias_target_names,
        examples=(
            SmokeCliExample("session_recovery_smoke.py"),
            SmokeCliExample("session_recovery_smoke.py live-restore", target_name="live-restore"),
            SmokeCliExample("session_recovery_smoke.py approval", target_name="approval"),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        TARGET_SELECTOR.resolve_targets(args.target),
        summary_label=SUMMARY_LABEL,
    )


if __name__ == "__main__":
    raise SystemExit(main())
