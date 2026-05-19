from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, run_smoke_targets

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run approval/session-state/live-restore smoke scripts and fail fast on any emitted '= False' check.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=[*SMOKE_TARGETS, "all"],
        default="all",
        help="Which recovery smoke surface to run.",
    )
    args = parser.parse_args(argv)

    target_names = [args.target] if args.target != "all" else DEFAULT_TARGET_NAMES
    return run_smoke_targets(
        [SMOKE_TARGETS[target_name] for target_name in target_names],
        summary_label=SUMMARY_LABEL,
    )


if __name__ == "__main__":
    raise SystemExit(main())
