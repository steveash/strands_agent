from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .smoke_runner import SMOKE_WRAPPER_CLI_SPECS, SmokeWrapperCliSpec


def _render_missing_snippets(snippets: tuple[str, ...]) -> str:
    return " | ".join(snippets)


@dataclass(frozen=True)
class SmokeCliDocParityResult:
    script_name: str
    readme_section_heading: str
    missing_help_snippets: tuple[str, ...]
    missing_readme_snippets: tuple[str, ...]

    @property
    def help_matches(self) -> bool:
        return not self.missing_help_snippets

    @property
    def readme_matches(self) -> bool:
        return not self.missing_readme_snippets

    @property
    def matches(self) -> bool:
        return self.help_matches and self.readme_matches

    @property
    def help_diagnostic(self) -> str:
        if self.help_matches:
            return "help ok"
        return f"--help missing: {_render_missing_snippets(self.missing_help_snippets)}"

    @property
    def readme_diagnostic(self) -> str:
        if self.readme_matches:
            return f"README {self.readme_section_heading!r} ok"
        return (
            f"README {self.readme_section_heading!r} missing: "
            f"{_render_missing_snippets(self.missing_readme_snippets)}"
        )

    @property
    def diagnostic_lines(self) -> tuple[str, str]:
        return (self.help_diagnostic, self.readme_diagnostic)

    @property
    def diagnostic_summary(self) -> str:
        return "; ".join(self.diagnostic_lines)


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


def build_smoke_cli_doc_specs(specs: Iterable[SmokeWrapperCliSpec]) -> tuple[SmokeCliDocSpec, ...]:
    return tuple(build_smoke_cli_doc_spec(spec) for spec in specs)


def build_smoke_cli_doc_spec_registry(
    specs: Iterable[SmokeCliDocSpec],
) -> dict[str, SmokeCliDocSpec]:
    registry: dict[str, SmokeCliDocSpec] = {}
    for spec in specs:
        if spec.script_name in registry:
            raise ValueError(f"duplicate smoke cli doc spec {spec.script_name!r}")
        registry[spec.script_name] = spec
    return registry


SMOKE_CLI_DOC_SPECS = build_smoke_cli_doc_specs(SMOKE_WRAPPER_CLI_SPECS)
SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME = build_smoke_cli_doc_spec_registry(SMOKE_CLI_DOC_SPECS)


def smoke_cli_doc_spec(script_name: str) -> SmokeCliDocSpec:
    spec = SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME.get(script_name)
    if spec is None:
        raise ValueError(f"unknown smoke cli doc spec {script_name!r}")
    return spec


def missing_required_snippets(text: str, *, required_snippets: Iterable[str]) -> tuple[str, ...]:
    normalized = normalize_cli_text(text)
    return tuple(snippet for snippet in required_snippets if snippet not in normalized)


def missing_public_cli_help_snippets(text: str, *, required_snippets: Iterable[str]) -> tuple[str, ...]:
    return missing_required_snippets(text, required_snippets=required_snippets)


def missing_markdown_section_snippets(
    markdown: str,
    *,
    heading: str,
    required_snippets: Iterable[str],
) -> tuple[str, ...]:
    return missing_required_snippets(
        markdown_section_text(markdown, heading=heading),
        required_snippets=required_snippets,
    )


def collect_smoke_cli_doc_parity(
    *,
    script_name: str,
    help_text: str,
    markdown: str,
) -> SmokeCliDocParityResult:
    spec = smoke_cli_doc_spec(script_name)
    return SmokeCliDocParityResult(
        script_name=script_name,
        readme_section_heading=spec.readme_section_heading,
        missing_help_snippets=missing_public_cli_help_snippets(
            help_text,
            required_snippets=spec.help_required_snippets,
        ),
        missing_readme_snippets=missing_markdown_section_snippets(
            markdown,
            heading=spec.readme_section_heading,
            required_snippets=spec.readme_required_snippets,
        ),
    )


def matches_smoke_cli_help_for_script(text: str, *, script_name: str) -> bool:
    spec = smoke_cli_doc_spec(script_name)
    return not missing_public_cli_help_snippets(text, required_snippets=spec.help_required_snippets)


def matches_smoke_cli_readme_for_script(markdown: str, *, script_name: str) -> bool:
    spec = smoke_cli_doc_spec(script_name)
    return not missing_markdown_section_snippets(
        markdown,
        heading=spec.readme_section_heading,
        required_snippets=spec.readme_required_snippets,
    )


def smoke_cli_doc_parity_diagnostic(
    *,
    script_name: str,
    help_text: str,
    markdown: str,
) -> str:
    return collect_smoke_cli_doc_parity(
        script_name=script_name,
        help_text=help_text,
        markdown=markdown,
    ).diagnostic_summary



def matches_smoke_cli_doc_parity(
    *,
    script_name: str,
    help_text: str,
    markdown: str,
) -> bool:
    return collect_smoke_cli_doc_parity(
        script_name=script_name,
        help_text=help_text,
        markdown=markdown,
    ).matches


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
    return not missing_markdown_section_snippets(
        markdown,
        heading=heading,
        required_snippets=required_snippets,
    )


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
    return not missing_public_cli_help_snippets(text, required_snippets=required_snippets)
