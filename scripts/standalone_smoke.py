from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SmokeScriptTarget,
    run_smoke_targets,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
CLI_SPEC = smoke_wrapper_cli_spec("standalone_smoke")
SMOKE_TARGETS = CLI_SPEC.build_targets(script_dir=SCRIPT_DIR)
DEFAULT_TARGET_NAMES = list(CLI_SPEC.default_target_names())
ALL_TARGET_NAMES = list(CLI_SPEC.resolve_target_names("all"))
LIVE_TARGET_NAME = "live"
LIVE_RUNTIME_REQUESTED_FALSE_LINE = "live_runtime_requested= False"
LIVE_RUNTIME_API_KEY_ERROR = "OPENAI_API_KEY is required for live runtime mode"


def _build_live_failure_hint(requested_target_name: str):
    def _live_failure_hint(target: SmokeScriptTarget, observed_lines: Sequence[str]) -> str | None:
        if target.name != LIVE_TARGET_NAME:
            return None
        normalized_lines = [line.rstrip("\n") for line in observed_lines]
        if any(LIVE_RUNTIME_REQUESTED_FALSE_LINE in line for line in normalized_lines):
            if requested_target_name == LIVE_TARGET_NAME:
                return (
                    "hint: `standalone_smoke.py live` expects `STRANDS_AGENT_RUNTIME=live`; export "
                    "`STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
                    "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
                )
            return (
                "hint: `standalone_smoke.py all` includes the live smoke target; export "
                "`STRANDS_AGENT_RUNTIME=live` and `OPENAI_API_KEY` "
                "(optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
            )
        if any(LIVE_RUNTIME_API_KEY_ERROR in line for line in normalized_lines):
            if requested_target_name == LIVE_TARGET_NAME:
                return (
                    "hint: `standalone_smoke.py live` reached the live runtime, but `OPENAI_API_KEY` was missing; "
                    "export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
                )
            return (
                "hint: `standalone_smoke.py all` reached the live smoke target, but `OPENAI_API_KEY` was missing; "
                "export `OPENAI_API_KEY` (and optionally `STRANDS_AGENT_OPENAI_MODEL`) before rerunning."
            )
        return None

    return _live_failure_hint


def build_parser() -> argparse.ArgumentParser:
    return CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    kwargs = {"wrapper_metadata": CLI_SPEC.wrapper_metadata}
    if args.target in {"all", LIVE_TARGET_NAME}:
        kwargs["failure_hint_builder"] = _build_live_failure_hint(args.target)

    return run_smoke_targets(
        CLI_SPEC.resolve_targets(script_dir=SCRIPT_DIR, requested_target_name=args.target),
        **kwargs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
