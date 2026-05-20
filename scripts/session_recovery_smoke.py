from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, SmokeTargetSelector, run_smoke_targets

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
    parser = argparse.ArgumentParser(
        description="Run approval/session-state/live-restore smoke scripts and fail fast on any emitted '= False' check.",
        epilog=(
            "Alias details:\n"
            "  all -> approval, approval-restart, session-state, live-restore, live-restore-denied\n"
            "\n"
            "Examples:\n"
            "  session_recovery_smoke.py                 # default all alias -> approval, approval-restart, session-state, live-restore, live-restore-denied\n"
            "  session_recovery_smoke.py live-restore    # single target\n"
            "  session_recovery_smoke.py approval        # single target"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=TARGET_SELECTOR.choices,
        default=TARGET_SELECTOR.default_target_name,
        help="Which recovery smoke surface to run. Alias: all -> approval, approval-restart, session-state, live-restore, live-restore-denied.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        TARGET_SELECTOR.resolve_targets(args.target),
        summary_label=SUMMARY_LABEL,
    )


if __name__ == "__main__":
    raise SystemExit(main())
