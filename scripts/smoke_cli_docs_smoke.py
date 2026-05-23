from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_CLI_DOC_SPECS,
    SmokeCliExample,
    build_smoke_cli_parser,
    collect_smoke_cli_doc_parity,
    emit_smoke_results,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
README_PATH = SCRIPT_DIR.parent / "README.md"
DOC_TARGET_NAMES = tuple(doc_spec.script_name for doc_spec in SMOKE_CLI_DOC_SPECS)
DOC_ALIAS_TARGET_NAMES = {"all": DOC_TARGET_NAMES}
DEFAULT_TARGET_NAMES = list(DOC_TARGET_NAMES)


def load_readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _render_missing_snippets(snippets: tuple[str, ...]) -> str:
    return "none" if not snippets else " | ".join(snippets)


def resolve_target_names(requested_target_name: str | None = None) -> tuple[str, ...]:
    target_name = "all" if requested_target_name is None else requested_target_name
    if target_name == "all":
        return DOC_TARGET_NAMES
    if target_name not in DOC_TARGET_NAMES:
        raise ValueError(f"unknown smoke cli docs target {target_name!r}")
    return (target_name,)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_parser(
        description=(
            "Audit smoke-wrapper `--help` text against the README and fail on missing public-doc snippets."
        ),
        choices=(*DOC_TARGET_NAMES, "all"),
        default_target_name="all",
        resolve_target_names=resolve_target_names,
        resolve_display_names=resolve_target_names,
        item_help="Which smoke-wrapper docs surface to audit.",
        alias_target_names=DOC_ALIAS_TARGET_NAMES,
        examples=(
            SmokeCliExample("smoke_cli_docs_smoke.py"),
            SmokeCliExample("smoke_cli_docs_smoke.py standalone_smoke", target_name="standalone_smoke"),
            SmokeCliExample("smoke_cli_docs_smoke.py smoke_matrix", target_name="smoke_matrix"),
        ),
        single_choice_description="single smoke wrapper",
    )


def run_smoke_cli_docs_smoke(
    *,
    markdown: str | None = None,
    requested_target_name: str | None = None,
) -> list[tuple[str, object]]:
    markdown = load_readme_text() if markdown is None else markdown
    results: list[tuple[str, object]] = []

    for script_name in resolve_target_names(requested_target_name):
        help_text = smoke_wrapper_cli_spec(script_name).build_parser(script_dir=SCRIPT_DIR).format_help()
        parity = collect_smoke_cli_doc_parity(
            script_name=script_name,
            help_text=help_text,
            markdown=markdown,
        )
        prefix = script_name
        results.extend(
            [
                (f"{prefix}_diagnostic", parity.diagnostic_summary),
                (f"{prefix}_help_missing", _render_missing_snippets(parity.missing_help_snippets)),
                (f"{prefix}_readme_missing", _render_missing_snippets(parity.missing_readme_snippets)),
                (f"{prefix}_help", parity.help_matches),
                (f"{prefix}_readme", parity.readme_matches),
                (f"{prefix}_doc_parity", parity.matches),
            ]
        )

    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return emit_smoke_results(run_smoke_cli_docs_smoke(requested_target_name=args.target))


if __name__ == "__main__":
    raise SystemExit(main())
