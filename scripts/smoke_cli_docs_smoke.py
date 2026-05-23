from __future__ import annotations

from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_CLI_DOC_SPECS,
    collect_smoke_cli_doc_parity,
    emit_smoke_results,
    smoke_wrapper_cli_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
README_PATH = SCRIPT_DIR.parent / "README.md"


def load_readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _render_missing_snippets(snippets: tuple[str, ...]) -> str:
    return "none" if not snippets else " | ".join(snippets)


def run_smoke_cli_docs_smoke(*, markdown: str | None = None) -> list[tuple[str, object]]:
    markdown = load_readme_text() if markdown is None else markdown
    results: list[tuple[str, object]] = []

    for doc_spec in SMOKE_CLI_DOC_SPECS:
        help_text = smoke_wrapper_cli_spec(doc_spec.script_name).build_parser(script_dir=SCRIPT_DIR).format_help()
        parity = collect_smoke_cli_doc_parity(
            script_name=doc_spec.script_name,
            help_text=help_text,
            markdown=markdown,
        )
        prefix = doc_spec.script_name
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


def main() -> int:
    return emit_smoke_results(run_smoke_cli_docs_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
