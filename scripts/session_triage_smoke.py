from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import SmokeScriptTarget, SmokeTargetSelector, run_smoke_targets

SCRIPT_DIR = Path(__file__).resolve().parent
SUMMARY_LABEL = "session-triage-smoke"
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
    parser = argparse.ArgumentParser(
        description="Run picker/switcher smoke scripts and fail fast on any emitted '= False' check.",
        epilog=(
            "Alias details:\n"
            "  both -> picker, switcher\n"
            "  all -> picker, switcher\n"
            "\n"
            "Examples:\n"
            "  session_triage_smoke.py          # default both alias -> picker, switcher\n"
            "  session_triage_smoke.py all      # alias for picker + switcher\n"
            "  session_triage_smoke.py picker   # single target"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=TARGET_SELECTOR.choices,
        default=TARGET_SELECTOR.default_target_name,
        help="Which session-triage smoke surface to run. Aliases: both -> picker, switcher; all -> picker, switcher.",
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
