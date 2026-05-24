from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from .smoke_runner import (
    SMOKE_WRAPPER_CLI_SPECS,
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    SmokeWrapperCliSpec,
    build_smoke_cli_parser,
    smoke_wrapper_cli_spec,
)


def _render_missing_snippets(snippets: tuple[str, ...]) -> str:
    return " | ".join(snippets)


@dataclass(frozen=True)
class SmokeCliDocParityResult:
    script_name: str
    readme_section_heading: str
    missing_help_snippets: tuple[str, ...]
    missing_readme_snippets: tuple[str, ...]
    readme_diff_lines: tuple[str, ...] = ()

    @property
    def help_matches(self) -> bool:
        return not self.missing_help_snippets

    @property
    def readme_matches(self) -> bool:
        return not self.missing_readme_snippets and not self.readme_diff_lines

    @property
    def matches(self) -> bool:
        return self.help_matches and self.readme_matches

    @property
    def help_diagnostic(self) -> str:
        if self.help_matches:
            return "help ok"
        return f"--help missing: {_render_missing_snippets(self.missing_help_snippets)}"

    @property
    def readme_diff_summary(self) -> str:
        if not self.readme_diff_lines:
            return "none"
        return " | ".join(self.readme_diff_lines)

    @property
    def readme_diagnostic(self) -> str:
        if self.readme_matches:
            return f"README {self.readme_section_heading!r} ok"

        parts: list[str] = []
        if self.missing_readme_snippets:
            parts.append(f"missing: {_render_missing_snippets(self.missing_readme_snippets)}")
        if self.readme_diff_lines:
            parts.append(f"diff: {self.readme_diff_summary}")
        return f"README {self.readme_section_heading!r} " + "; ".join(parts)

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
SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME = "smoke_cli_docs_smoke"


def build_smoke_cli_doc_audit_selector() -> SmokeTargetSelector:
    return SmokeTargetSelector(
        targets={
            spec.script_name: SmokeScriptTarget(spec.script_name, Path(f"{spec.script_name}.py"))
            for spec in SMOKE_CLI_DOC_SPECS
        },
        default_target_name="all",
        alias_target_names={"all": tuple(spec.script_name for spec in SMOKE_CLI_DOC_SPECS)},
    )


SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR = build_smoke_cli_doc_audit_selector()
SMOKE_CLI_DOC_AUDIT_TARGET_NAMES = tuple(SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR.targets)
DEFAULT_SMOKE_CLI_DOC_AUDIT_TARGET_NAMES = tuple(SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR.resolve_target_names())


def build_smoke_cli_doc_audit_examples() -> tuple[SmokeCliExample, ...]:
    commands = [SmokeCliExample(f"{SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME}.py")]
    if SMOKE_CLI_DOC_AUDIT_TARGET_NAMES:
        commands.append(
            SmokeCliExample(
                f"{SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME}.py {SMOKE_CLI_DOC_AUDIT_TARGET_NAMES[0]}",
                target_name=SMOKE_CLI_DOC_AUDIT_TARGET_NAMES[0],
            )
        )
    if len(SMOKE_CLI_DOC_AUDIT_TARGET_NAMES) > 1:
        commands.append(
            SmokeCliExample(
                f"{SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME}.py {SMOKE_CLI_DOC_AUDIT_TARGET_NAMES[-1]}",
                target_name=SMOKE_CLI_DOC_AUDIT_TARGET_NAMES[-1],
            )
        )
    return tuple(commands)


SMOKE_CLI_DOC_AUDIT_EXAMPLES = build_smoke_cli_doc_audit_examples()
SMOKE_CLI_DOC_RENDER_SCRIPT_NAME = "smoke_cli_docs_render"


def build_smoke_cli_doc_render_examples() -> tuple[SmokeCliExample, ...]:
    return (
        SmokeCliExample(f"{SMOKE_CLI_DOC_RENDER_SCRIPT_NAME}.py"),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_RENDER_SCRIPT_NAME}.py standalone_smoke --body-only",
            target_name="standalone_smoke",
            description="single smoke wrapper body preview",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_RENDER_SCRIPT_NAME}.py all --output-dir artifacts/smoke-cli-docs-preview",
            target_name="all",
            description="export all rendered smoke wrapper sections",
        ),
    )


SMOKE_CLI_DOC_RENDER_EXAMPLES = build_smoke_cli_doc_render_examples()


def resolve_smoke_cli_doc_target_names(requested_target_name: str | None = None) -> tuple[str, ...]:
    return tuple(SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR.resolve_target_names(requested_target_name))



def build_smoke_cli_doc_audit_parser() -> argparse.ArgumentParser:
    selector = SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR
    return build_smoke_cli_parser(
        description=(
            "Audit smoke-wrapper `--help` text against the README and fail on missing public-doc snippets."
        ),
        choices=selector.choices,
        default_target_name=selector.default_target_name,
        resolve_target_names=selector.resolve_target_names,
        resolve_display_names=selector.resolve_display_names,
        item_help="Which smoke-wrapper docs surface to audit.",
        alias_target_names=selector.alias_target_names,
        examples=SMOKE_CLI_DOC_AUDIT_EXAMPLES,
        single_choice_description="single smoke wrapper",
    )


def smoke_cli_doc_spec(script_name: str) -> SmokeCliDocSpec:
    spec = SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME.get(script_name)
    if spec is None:
        raise ValueError(f"unknown smoke cli doc spec {script_name!r}")
    return spec



def build_smoke_cli_doc_render_parser() -> argparse.ArgumentParser:
    selector = SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR
    parser = build_smoke_cli_parser(
        description=(
            "Render the expected smoke-wrapper README sections from shared metadata for preview or export."
        ),
        choices=selector.choices,
        default_target_name=selector.default_target_name,
        resolve_target_names=selector.resolve_target_names,
        resolve_display_names=selector.resolve_display_names,
        item_help="Which smoke-wrapper README surface to render.",
        alias_target_names=selector.alias_target_names,
        examples=SMOKE_CLI_DOC_RENDER_EXAMPLES,
        single_choice_description="single smoke wrapper body preview",
    )
    parser.add_argument(
        "--body-only",
        action="store_true",
        help="Render only the section body without the leading markdown heading.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write one <script_name>.md file per selected smoke wrapper instead of printing to stdout.",
    )
    return parser



def render_smoke_cli_readme_section(script_name: str, *, body_only: bool = False) -> str:
    spec = smoke_wrapper_cli_spec(script_name)
    if body_only:
        return spec.render_readme_section_body()
    return spec.render_readme_section()



def render_smoke_cli_readme_sections(
    *,
    requested_target_name: str | None = None,
    body_only: bool = False,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            script_name,
            render_smoke_cli_readme_section(script_name, body_only=body_only),
        )
        for script_name in resolve_smoke_cli_doc_target_names(requested_target_name)
    )


def missing_required_snippets(text: str, *, required_snippets: Iterable[str]) -> tuple[str, ...]:
    normalized = normalize_cli_text(text)
    return tuple(snippet for snippet in required_snippets if normalize_cli_text(snippet) not in normalized)


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


def expected_smoke_cli_readme_section_body(script_name: str) -> str:
    return smoke_wrapper_cli_spec(script_name).render_readme_section_body()



def smoke_cli_readme_diff_lines(markdown: str, *, script_name: str) -> tuple[str, ...]:
    spec = smoke_cli_doc_spec(script_name)
    expected = expected_smoke_cli_readme_section_body(script_name)
    actual = markdown_section_text(markdown, heading=spec.readme_section_heading)
    if actual == expected:
        return ()
    return tuple(
        unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="expected",
            tofile="README",
            lineterm="",
        )
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
        readme_diff_lines=smoke_cli_readme_diff_lines(markdown, script_name=script_name),
    )


def matches_smoke_cli_help_for_script(text: str, *, script_name: str) -> bool:
    spec = smoke_cli_doc_spec(script_name)
    return not missing_public_cli_help_snippets(text, required_snippets=spec.help_required_snippets)


def matches_smoke_cli_readme_for_script(markdown: str, *, script_name: str) -> bool:
    return not smoke_cli_readme_diff_lines(markdown, script_name=script_name)


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
