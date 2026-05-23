from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    SMOKE_CLI_DOC_AUDIT_TARGET_NAMES,
    build_smoke_cli_doc_audit_parser,
    collect_smoke_cli_doc_parity,
    emit_smoke_results,
    resolve_smoke_cli_doc_target_names,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
README_PATH = SCRIPT_DIR.parent / "README.md"
DOC_TARGET_NAMES = SMOKE_CLI_DOC_AUDIT_TARGET_NAMES
DEFAULT_TARGET_NAMES = list(DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES)


def load_readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _render_missing_snippets(snippets: tuple[str, ...]) -> str:
    return "none" if not snippets else " | ".join(snippets)


def resolve_target_names(requested_target_name: str | None = None) -> tuple[str, ...]:
    return resolve_smoke_cli_doc_target_names(requested_target_name)


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_doc_audit_parser()


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
