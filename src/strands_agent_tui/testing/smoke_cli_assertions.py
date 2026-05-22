from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .smoke_runner import (
    SESSION_RECOVERY_SMOKE_CLI_SPEC,
    SESSION_TRIAGE_SMOKE_CLI_SPEC,
    STANDALONE_SMOKE_CLI_SPEC,
    SmokeWrapperCliSpec,
)


@dataclass(frozen=True)
class SmokeCliDocSpec:
    script_name: str
    readme_section_heading: str
    help_required_snippets: tuple[str, ...]
    readme_required_snippets: tuple[str, ...]


def build_smoke_cli_doc_spec(spec: SmokeWrapperCliSpec) -> SmokeCliDocSpec:
    if spec.readme_section_heading is None:
        raise ValueError(f"readme_section_heading is required for {spec.script_name}")
    return SmokeCliDocSpec(
        script_name=spec.script_name,
        readme_section_heading=spec.readme_section_heading,
        help_required_snippets=spec.help_required_snippets(),
        readme_required_snippets=spec.readme_required_snippets(),
    )


SMOKE_CLI_DOC_SPECS = (
    build_smoke_cli_doc_spec(STANDALONE_SMOKE_CLI_SPEC),
    build_smoke_cli_doc_spec(SESSION_TRIAGE_SMOKE_CLI_SPEC),
    build_smoke_cli_doc_spec(SESSION_RECOVERY_SMOKE_CLI_SPEC),
    SmokeCliDocSpec(
        script_name="smoke_matrix",
        readme_section_heading="Full local smoke matrix",
        help_required_snippets=(
            "Which smoke bundle or bundle matrix to run.",
            "Bundle aliases: local -> standalone, triage, recovery all -> standalone (live-inclusive), triage, recovery",
            "default local alias -> standalone, triage, recovery",
            "The default 'local' matrix excludes the opt-in live runtime smoke target, and the 'all' alias swaps in the live-inclusive standalone bundle.",
            "smoke_matrix.py standalone # single bundle",
            "smoke_matrix.py triage # single bundle",
            "smoke_matrix.py recovery # single bundle",
            "smoke_matrix.py all # all alias -> standalone (live-inclusive), triage, recovery",
        ),
        readme_required_snippets=(
            ".venv/bin/python scripts/smoke_matrix.py",
            "default `local` matrix runs the standalone local bundle plus the session-triage and recovery bundles together",
            "`.venv/bin/python scripts/smoke_matrix.py local` explicitly re-runs the default local matrix (`standalone`, `triage`, `recovery`)",
            "`.venv/bin/python scripts/smoke_matrix.py all` swaps in the live-inclusive standalone bundle (`standalone (live-inclusive)`, `triage`, `recovery`)",
            "`.venv/bin/python scripts/smoke_matrix.py standalone` runs only the standalone local bundle",
            "`.venv/bin/python scripts/smoke_matrix.py triage` runs only the session-triage bundle",
            "`.venv/bin/python scripts/smoke_matrix.py recovery` runs only the recovery bundle",
        ),
    ),
)


def normalize_cli_text(text: str) -> str:
    return " ".join(text.split())


def markdown_section_text(markdown: str, *, heading: str) -> str:
    lines = markdown.splitlines()
    section_level: int | None = None
    start_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        hashes, _, title = stripped.partition(" ")
        if title == heading:
            section_level = len(hashes)
            start_index = index + 1
            break

    if section_level is None or start_index is None:
        raise ValueError(f"markdown heading not found: {heading!r}")

    collected: list[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes, _, title = stripped.partition(" ")
            if title and len(hashes) <= section_level:
                break
        collected.append(line)
    return "\n".join(collected).strip()


def matches_markdown_section(
    markdown: str,
    *,
    heading: str,
    required_snippets: Iterable[str],
) -> bool:
    normalized = normalize_cli_text(markdown_section_text(markdown, heading=heading))
    return all(snippet in normalized for snippet in required_snippets)


def matches_public_cli_invalid_choice(
    text: str,
    *,
    invalid_target: str,
    expected_choices: str,
) -> bool:
    normalized = normalize_cli_text(text)
    return f"invalid choice: '{invalid_target}'" in normalized and expected_choices in normalized


def matches_public_cli_help(
    text: str,
    *,
    required_snippets: Iterable[str],
) -> bool:
    normalized = normalize_cli_text(text)
    return all(snippet in normalized for snippet in required_snippets)
