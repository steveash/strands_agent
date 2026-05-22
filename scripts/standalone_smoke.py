from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    run_smoke_targets,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
CLI_SPEC = smoke_wrapper_cli_spec("standalone_smoke")
SMOKE_TARGETS = CLI_SPEC.build_targets(script_dir=SCRIPT_DIR)
DEFAULT_TARGET_NAMES = list(CLI_SPEC.default_target_names())
ALL_TARGET_NAMES = list(CLI_SPEC.resolve_target_names("all"))


def build_parser() -> argparse.ArgumentParser:
    return CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        CLI_SPEC.resolve_targets(script_dir=SCRIPT_DIR, requested_target_name=args.target),
        wrapper_metadata=CLI_SPEC.wrapper_metadata,
    )


if __name__ == "__main__":
    raise SystemExit(main())
