from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SmokeScriptTarget,
    run_smoke_targets,
    smoke_cli_docs_parity_rerun_hint,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
CLI_SPEC = smoke_wrapper_cli_spec("standalone_smoke")
SMOKE_TARGETS = CLI_SPEC.build_targets(script_dir=SCRIPT_DIR)
DEFAULT_TARGET_NAMES = list(CLI_SPEC.default_target_names())
ALL_TARGET_NAMES = list(CLI_SPEC.resolve_target_names("all"))
LIVE_TARGET_NAME = "live"
DOCS_PARITY_TARGET_NAMES = {"docs", "docs-artifacts", "docs-rerun-hint"}
DOCS_REVIEW_TARGET_NAMES = {
    "matrix-artifact-roots",
    "matrix-all-review-order",
    "matrix-all-review-missing-api-key",
    "matrix-docs-review-hint",
}
DOCS_REVIEW_RERUN_HINT_TARGET_NAMES = {"docs-contract", "docs-focused", "docs-review-only"}
CONTRACT_NEGATIVE_TARGET_NAMES = {"malformed-result", "malformed-detail"}
LIVE_RUNTIME_REQUESTED_FALSE_LINE = "live_runtime_requested= False"
LIVE_RUNTIME_API_KEY_ERROR = "OPENAI_API_KEY is required for live runtime mode"
DOCS_REVIEW_ONLY_RERUN_HINT = (
    "hint: docs-review drift is easiest to isolate with `standalone_smoke.py docs-review-only`; rerun "
    "`.venv/bin/python scripts/standalone_smoke.py docs-review-only` to recheck the docs-review lane "
    "without the standalone docs-rerun-hint / malformed-contract regressions or the rest of the bundle."
)


def _malformed_contract_failure_hint(
    target: SmokeScriptTarget,
    *,
    requested_target_name: str,
) -> str | None:
    if target.name not in CONTRACT_NEGATIVE_TARGET_NAMES:
        return None
    return (
        f"hint: `standalone_smoke.py {requested_target_name}` failed inside "
        f"`{target.name}`; rerun `.venv/bin/python scripts/standalone_smoke.py {target.name}` "
        "to isolate the failing malformed smoke-script contract regression."
    )


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


def _build_failure_hint(requested_target_name: str):
    live_failure_hint = None
    if requested_target_name in {"all", LIVE_TARGET_NAME}:
        live_failure_hint = _build_live_failure_hint(requested_target_name)

    def _failure_hint(target: SmokeScriptTarget, observed_lines: Sequence[str]) -> str | None:
        if live_failure_hint is not None:
            hint = live_failure_hint(target, observed_lines)
            if hint is not None:
                return hint
        if requested_target_name in {"contract-negative", "docs-contract"}:
            hint = _malformed_contract_failure_hint(
                target,
                requested_target_name=requested_target_name,
            )
            if hint is not None:
                return hint
        if target.name in DOCS_PARITY_TARGET_NAMES:
            return smoke_cli_docs_parity_rerun_hint()
        if (
            requested_target_name in DOCS_REVIEW_RERUN_HINT_TARGET_NAMES
            and target.name in DOCS_REVIEW_TARGET_NAMES
        ):
            return DOCS_REVIEW_ONLY_RERUN_HINT
        return None

    return _failure_hint


def build_parser() -> argparse.ArgumentParser:
    return CLI_SPEC.build_parser(script_dir=SCRIPT_DIR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_smoke_targets(
        CLI_SPEC.resolve_targets(script_dir=SCRIPT_DIR, requested_target_name=args.target),
        wrapper_metadata=CLI_SPEC.wrapper_metadata,
        failure_hint_builder=_build_failure_hint(args.target),
    )


if __name__ == "__main__":
    raise SystemExit(main())
