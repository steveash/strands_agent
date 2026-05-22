from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    STANDALONE_SMOKE_CLI_SPEC,
    run_smoke_targets,
)

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_SELECTOR = STANDALONE_SMOKE_CLI_SPEC.build_target_selector(script_dir=SCRIPT_DIR)
SMOKE_TARGETS = TARGET_SELECTOR.targets
DEFAULT_TARGET_NAMES = list(STANDALONE_SMOKE_CLI_SPEC.alias_target_names["local"])
ALL_TARGET_NAMES = list(STANDALONE_SMOKE_CLI_SPEC.alias_target_names["all"])


def build_parser() -> argparse.ArgumentParser:
    return STANDALONE_SMOKE_CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        TARGET_SELECTOR.resolve_targets(args.target),
        wrapper_metadata=STANDALONE_SMOKE_CLI_SPEC.wrapper_metadata,
    )


if __name__ == "__main__":
    raise SystemExit(main())
