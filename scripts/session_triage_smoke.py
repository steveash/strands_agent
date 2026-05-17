from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import is_failed_smoke_check_line

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_TARGETS = {
    "picker": SCRIPT_DIR / "session_picker_smoke.py",
    "switcher": SCRIPT_DIR / "session_switcher_smoke.py",
}


def _run_target(name: str, script_path: Path) -> int:
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    failed_line: str | None = None
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        if is_failed_smoke_check_line(line):
            failed_line = line.rstrip("\n")
            process.terminate()
            break

    return_code = process.wait()
    if failed_line is not None:
        print(f"{name} smoke failed fast: {failed_line}", file=sys.stderr)
        return 1
    if return_code != 0:
        print(f"{name} smoke exited with status {return_code}", file=sys.stderr)
        return return_code
    return 0


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

    targets = [args.target] if args.target != "both" else ["picker", "switcher"]
    for target in targets:
        exit_code = _run_target(target, SMOKE_TARGETS[target])
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
