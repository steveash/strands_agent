from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
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
    describe_smoke_cli_example,
    format_cli_choices,
    format_smoke_cli_alias_help,
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


ParserArgumentBuilder = Callable[[argparse.ArgumentParser, Path | None], None]


def _no_extra_parser_arguments(parser: argparse.ArgumentParser, readme_path: Path | None) -> None:
    return None


@dataclass(frozen=True)
class SmokeCliDocParserSpec:
    script_name: str
    description: str
    selector: SmokeTargetSelector
    item_help: str
    examples: tuple[SmokeCliExample, ...]
    single_choice_description: str
    flag_snippets: tuple[str, ...] = ()
    add_arguments: ParserArgumentBuilder = _no_extra_parser_arguments

    def help_required_snippets(self) -> tuple[str, ...]:
        return _smoke_cli_doc_parser_help_snippets(
            item_help=self.item_help,
            selector=self.selector,
            examples=self.examples,
            single_choice_description=self.single_choice_description,
            flag_snippets=self.flag_snippets,
        )

    def invalid_choice_expected_choices(self) -> str:
        return self.selector.invalid_choice_expected_choices()

    def build_parser(self, *, readme_path: Path | None = None) -> argparse.ArgumentParser:
        parser = build_smoke_cli_parser(
            description=self.description,
            choices=self.selector.choices,
            default_target_name=self.selector.default_target_name,
            resolve_target_names=self.selector.resolve_target_names,
            resolve_display_names=self.selector.resolve_display_names,
            item_help=self.item_help,
            alias_target_names=self.selector.alias_target_names,
            examples=self.examples,
            single_choice_description=self.single_choice_description,
        )
        self.add_arguments(parser, readme_path)
        return parser


def smoke_cli_doc_spec_id(spec: SmokeCliDocSpec) -> str:
    return spec.script_name


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
SMOKE_CLI_DOCS_PARITY_RERUN_HINT = (
    "hint: standalone wrapper docs drift is easiest to isolate with `standalone_smoke.py docs-parity-only`; rerun "
    "`.venv/bin/python scripts/standalone_smoke.py docs-parity-only` to recheck the docs parity lane "
    "without the broader docs-review regressions or the rest of the local bundle."
)


def smoke_cli_docs_parity_rerun_hint() -> str:
    return SMOKE_CLI_DOCS_PARITY_RERUN_HINT


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
SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES = format_cli_choices(
    SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR.choices
)


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
SMOKE_CLI_DOC_FIX_SCRIPT_NAME = "smoke_cli_docs_fix"
SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME = "smoke_cli_docs_artifacts_smoke"
SMOKE_CLI_DOC_ARTIFACTS_DEFAULT_TARGET_NAME = "standalone_smoke"


def _selector_alias_help_snippet(*, item_help: str, selector: SmokeTargetSelector) -> str:
    return format_smoke_cli_alias_help(
        item_help,
        alias_target_names=selector.alias_target_names,
        resolve_display_names=selector.resolve_display_names,
    )


def _smoke_cli_doc_example_help_snippets(
    examples: Iterable[SmokeCliExample],
    *,
    selector: SmokeTargetSelector,
    single_choice_description: str,
) -> tuple[str, ...]:
    return tuple(
        f"{example.command} # "
        + describe_smoke_cli_example(
            example,
            default_target_name=selector.default_target_name,
            alias_target_names=selector.alias_target_names,
            resolve_display_names=selector.resolve_display_names,
            single_choice_description=single_choice_description,
        )
        for example in examples
    )


def _smoke_cli_doc_parser_help_snippets(
    *,
    item_help: str,
    selector: SmokeTargetSelector,
    examples: Iterable[SmokeCliExample],
    single_choice_description: str,
    flag_snippets: Iterable[str] = (),
) -> tuple[str, ...]:
    return (
        _selector_alias_help_snippet(item_help=item_help, selector=selector),
        *_smoke_cli_doc_example_help_snippets(
            examples,
            selector=selector,
            single_choice_description=single_choice_description,
        ),
        *tuple(flag_snippets),
    )


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
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_RENDER_SCRIPT_NAME}.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview",
            target_name="all",
            description="export only the drifted rendered smoke wrapper sections",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_RENDER_SCRIPT_NAME}.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview --manifest-output artifacts/smoke-cli-docs-preview.json --diff-output artifacts/smoke-cli-docs-review.patch",
            target_name="all",
            description="persist drift-only review artifacts as rendered sections plus JSON manifest summaries/checksums and unified diff files",
        ),
    )


SMOKE_CLI_DOC_RENDER_EXAMPLES = build_smoke_cli_doc_render_examples()


def build_smoke_cli_doc_fix_examples() -> tuple[SmokeCliExample, ...]:
    return (
        SmokeCliExample(f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py"),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py standalone_smoke --diff",
            target_name="standalone_smoke",
            description="preview a single smoke wrapper README section diff without writing it",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py all --check",
            target_name="all",
            description="exit non-zero when any selected smoke wrapper README section drifts",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py all --check --json",
            target_name="all",
            description="emit machine-readable JSON drift results with manifest-style summaries/checksums for CI without scraping prose",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py all --check --json-output artifacts/smoke-cli-docs-fix.json",
            target_name="all",
            description="persist the same machine-readable drift report with manifest-style summaries/checksums alongside the normal console summary",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py standalone_smoke",
            target_name="standalone_smoke",
            description="repair a single smoke wrapper README section in place",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_FIX_SCRIPT_NAME}.py all --stdout",
            target_name="all",
            description="print the fully repaired README to stdout instead of writing it",
        ),
    )


SMOKE_CLI_DOC_FIX_EXAMPLES = build_smoke_cli_doc_fix_examples()


def build_smoke_cli_doc_artifacts_selector() -> SmokeTargetSelector:
    return SmokeTargetSelector(
        targets={
            spec.script_name: SmokeScriptTarget(spec.script_name, Path(f"{spec.script_name}.py"))
            for spec in SMOKE_CLI_DOC_SPECS
        },
        default_target_name=SMOKE_CLI_DOC_ARTIFACTS_DEFAULT_TARGET_NAME,
        alias_target_names={"all": tuple(spec.script_name for spec in SMOKE_CLI_DOC_SPECS)},
    )


SMOKE_CLI_DOC_ARTIFACTS_TARGET_SELECTOR = build_smoke_cli_doc_artifacts_selector()


def build_smoke_cli_doc_artifacts_examples() -> tuple[SmokeCliExample, ...]:
    return (
        SmokeCliExample(f"{SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME}.py"),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME}.py smoke_matrix",
            target_name="smoke_matrix",
            description="single smoke wrapper artifact contract",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME}.py session_triage_smoke --output-dir artifacts/smoke-cli-docs-artifacts/session-triage",
            target_name="session_triage_smoke",
            description="persist a session-triage wrapper artifact bundle for later review",
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME}.py all --output-dir artifacts/smoke-cli-docs-artifacts --readme-path README.md",
            target_name="all",
            description=(
                "persist drifted README plus render/fix review artifacts for every public smoke wrapper"
            ),
        ),
        SmokeCliExample(
            f"{SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME}.py all --output-dir artifacts/smoke-cli-docs-artifacts --bundle-index-path artifacts/smoke-cli-docs-artifacts/index.json",
            target_name="all",
            description="persist one machine-readable bundle index for CI or later review",
        ),
    )


SMOKE_CLI_DOC_ARTIFACTS_EXAMPLES = build_smoke_cli_doc_artifacts_examples()


SMOKE_CLI_DOC_RENDER_FLAG_SNIPPETS = (
    "--body-only",
    "--output-dir OUTPUT_DIR",
    "--readme-path README_PATH",
    "--drift-only",
    "--manifest-output MANIFEST_OUTPUT",
    "--diff-output DIFF_OUTPUT",
)
SMOKE_CLI_DOC_FIX_FLAG_SNIPPETS = (
    "--readme-path README_PATH",
    "--diff",
    "--check",
    "--json",
    "--json-output JSON_OUTPUT",
    "--drifted-readme-path DRIFTED_README_PATH",
    "--bundle-index-path BUNDLE_INDEX_PATH",
    "--render-output-dir RENDER_OUTPUT_DIR",
    "--render-manifest-path RENDER_MANIFEST_PATH",
    "--render-diff-path RENDER_DIFF_PATH",
    "--stdout",
)
SMOKE_CLI_DOC_ARTIFACTS_FLAG_SNIPPETS = (
    "--output-dir OUTPUT_DIR",
    "--readme-path README_PATH",
    "--drifted-readme-path DRIFTED_README_PATH",
    "--render-output-dir RENDER_OUTPUT_DIR",
    "--render-manifest-path RENDER_MANIFEST_PATH",
    "--render-diff-path RENDER_DIFF_PATH",
    "--fix-check-json-path FIX_CHECK_JSON_PATH",
    "--fix-repair-json-path FIX_REPAIR_JSON_PATH",
    "--fix-post-check-json-path FIX_POST_CHECK_JSON_PATH",
    "--bundle-index-path BUNDLE_INDEX_PATH",
)


def _add_smoke_cli_doc_render_parser_arguments(
    parser: argparse.ArgumentParser,
    readme_path: Path | None,
) -> None:
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
    parser.add_argument(
        "--readme-path",
        type=Path,
        default=Path("README.md"),
        help=(
            "README used to decide which selected sections drift when --drift-only is set "
            "(default: README.md)."
        ),
    )
    parser.add_argument(
        "--drift-only",
        action="store_true",
        help="Render only the selected smoke-wrapper sections whose README content currently drifts.",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help=(
            "Write a machine-readable JSON manifest for the drift-only review artifact set "
            "(requires --drift-only)."
        ),
    )
    parser.add_argument(
        "--diff-output",
        type=Path,
        help="Write the drift-only unified diff review artifact to this file path (requires --drift-only).",
    )


def _add_smoke_cli_doc_fix_parser_arguments(
    parser: argparse.ArgumentParser,
    readme_path: Path | None,
) -> None:
    parser.add_argument(
        "--readme-path",
        type=Path,
        default=Path("README.md"),
        help="Path to the README file to repair in place (default: README.md).",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Print unified diffs for only the drifted selected README sections without writing changes.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when any selected README section drifts without writing changes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON drift report (requires --check and/or --diff).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help=(
            "Write the machine-readable drift or repair report to this file path while keeping the normal "
            "console output."
        ),
    )
    parser.add_argument(
        "--drifted-readme-path",
        type=Path,
        help=(
            "Record the drifted README artifact path in machine-readable JSON output so downstream tooling "
            "can chain directly into the review copy that was checked or repaired."
        ),
    )
    parser.add_argument(
        "--bundle-index-path",
        type=Path,
        help=(
            "Record the docs-review bundle-index artifact path in machine-readable JSON output so downstream "
            "tooling can chain into the broader review bundle contract."
        ),
    )
    parser.add_argument(
        "--render-output-dir",
        type=Path,
        help=(
            "Record the rendered-section review directory in machine-readable JSON output so downstream "
            "tooling can locate exported README sections without scraping console hints."
        ),
    )
    parser.add_argument(
        "--render-manifest-path",
        type=Path,
        help=(
            "Record the render-manifest artifact path in machine-readable JSON output so downstream "
            "tooling can chain directly into the drift-review manifest."
        ),
    )
    parser.add_argument(
        "--render-diff-path",
        type=Path,
        help=(
            "Record the render-diff artifact path in machine-readable JSON output so downstream tooling "
            "can chain directly into the unified review patch."
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the fully repaired README to stdout instead of writing the README path.",
    )


def _add_smoke_cli_doc_artifacts_parser_arguments(
    parser: argparse.ArgumentParser,
    readme_path: Path | None,
) -> None:
    if readme_path is None:
        raise ValueError("readme_path is required for smoke CLI docs artifact parser")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Keep the drifted README plus render/fix JSON/diff artifacts in this directory "
            "instead of using a temporary directory."
        ),
    )
    parser.add_argument(
        "--readme-path",
        type=Path,
        default=readme_path,
        help=(
            "Source README used to synthesize drift before exercising the render/fix contract "
            f"(default: {readme_path})."
        ),
    )
    parser.add_argument(
        "--drifted-readme-path",
        type=Path,
        help="Write the synthetic drifted README copy to this path instead of <artifact-root>/README-drifted.md.",
    )
    parser.add_argument(
        "--render-output-dir",
        type=Path,
        help="Directory for rendered README sections instead of <artifact-root>/rendered.",
    )
    parser.add_argument(
        "--render-manifest-path",
        type=Path,
        help="Path for the render manifest JSON instead of <artifact-root>/render-manifest.json.",
    )
    parser.add_argument(
        "--render-diff-path",
        type=Path,
        help="Path for the render review patch instead of <artifact-root>/render-review.patch.",
    )
    parser.add_argument(
        "--fix-check-json-path",
        type=Path,
        help="Path for the fix-side drift-check JSON instead of <artifact-root>/fix-check.json.",
    )
    parser.add_argument(
        "--fix-repair-json-path",
        type=Path,
        help="Path for the fix-side repair JSON instead of <artifact-root>/fix-repair.json.",
    )
    parser.add_argument(
        "--fix-post-check-json-path",
        type=Path,
        help="Path for the post-repair drift-check JSON instead of <artifact-root>/fix-post-check.json.",
    )
    parser.add_argument(
        "--bundle-index-path",
        type=Path,
        help=(
            "Path for the machine-readable bundle index instead of <artifact-root>/bundle-index.json."
        ),
    )


SMOKE_CLI_DOC_AUDIT_PARSER_SPEC = SmokeCliDocParserSpec(
    script_name=SMOKE_CLI_DOC_AUDIT_SCRIPT_NAME,
    description=(
        "Audit smoke-wrapper `--help` text against the README and fail on missing public-doc snippets."
    ),
    selector=SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR,
    item_help="Which smoke-wrapper docs surface to audit.",
    examples=SMOKE_CLI_DOC_AUDIT_EXAMPLES,
    single_choice_description="single smoke wrapper",
)
SMOKE_CLI_DOC_RENDER_PARSER_SPEC = SmokeCliDocParserSpec(
    script_name=SMOKE_CLI_DOC_RENDER_SCRIPT_NAME,
    description=(
        "Render the expected smoke-wrapper README sections from shared metadata for preview or export."
    ),
    selector=SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR,
    item_help="Which smoke-wrapper README surface to render.",
    examples=SMOKE_CLI_DOC_RENDER_EXAMPLES,
    single_choice_description="single smoke wrapper body preview",
    flag_snippets=SMOKE_CLI_DOC_RENDER_FLAG_SNIPPETS,
    add_arguments=_add_smoke_cli_doc_render_parser_arguments,
)
SMOKE_CLI_DOC_FIX_PARSER_SPEC = SmokeCliDocParserSpec(
    script_name=SMOKE_CLI_DOC_FIX_SCRIPT_NAME,
    description="Repair smoke-wrapper README sections in place from shared metadata.",
    selector=SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR,
    item_help="Which smoke-wrapper README surface to repair.",
    examples=SMOKE_CLI_DOC_FIX_EXAMPLES,
    single_choice_description="single smoke wrapper section repair",
    flag_snippets=SMOKE_CLI_DOC_FIX_FLAG_SNIPPETS,
    add_arguments=_add_smoke_cli_doc_fix_parser_arguments,
)
SMOKE_CLI_DOC_ARTIFACTS_PARSER_SPEC = SmokeCliDocParserSpec(
    script_name=SMOKE_CLI_DOC_ARTIFACTS_SCRIPT_NAME,
    description=(
        "Exercise the smoke CLI docs render/fix artifact contract against drifted README sections "
        "and fail on any contract mismatch."
    ),
    selector=SMOKE_CLI_DOC_ARTIFACTS_TARGET_SELECTOR,
    item_help="Which public smoke-wrapper docs artifact contract to exercise.",
    examples=SMOKE_CLI_DOC_ARTIFACTS_EXAMPLES,
    single_choice_description="single smoke wrapper artifact contract",
    flag_snippets=SMOKE_CLI_DOC_ARTIFACTS_FLAG_SNIPPETS,
    add_arguments=_add_smoke_cli_doc_artifacts_parser_arguments,
)
SMOKE_CLI_DOC_PARSER_SPECS = (
    SMOKE_CLI_DOC_AUDIT_PARSER_SPEC,
    SMOKE_CLI_DOC_RENDER_PARSER_SPEC,
    SMOKE_CLI_DOC_FIX_PARSER_SPEC,
    SMOKE_CLI_DOC_ARTIFACTS_PARSER_SPEC,
)


def build_smoke_cli_doc_parser_spec_registry(
    specs: Iterable[SmokeCliDocParserSpec],
) -> dict[str, SmokeCliDocParserSpec]:
    registry: dict[str, SmokeCliDocParserSpec] = {}
    for spec in specs:
        if spec.script_name in registry:
            raise ValueError(f"duplicate smoke cli doc parser spec {spec.script_name!r}")
        registry[spec.script_name] = spec
    return registry


SMOKE_CLI_DOC_PARSER_SPECS_BY_SCRIPT_NAME = build_smoke_cli_doc_parser_spec_registry(
    SMOKE_CLI_DOC_PARSER_SPECS
)
SMOKE_CLI_DOC_PARSER_HELP_EXPECTED_SNIPPETS_BY_SCRIPT_NAME = {
    spec.script_name: spec.help_required_snippets() for spec in SMOKE_CLI_DOC_PARSER_SPECS
}


def build_smoke_cli_doc_invalid_choice_expected_choices_registry(
    specs: Iterable[SmokeCliDocParserSpec],
) -> dict[str, str]:
    registry: dict[str, str] = {}
    for spec in specs:
        if spec.script_name in registry:
            raise ValueError(f"duplicate smoke cli doc invalid-choice registry entry {spec.script_name!r}")
        registry[spec.script_name] = spec.invalid_choice_expected_choices()
    return registry


SMOKE_CLI_DOC_INVALID_CHOICE_EXPECTED_CHOICES_BY_SCRIPT_NAME = (
    build_smoke_cli_doc_invalid_choice_expected_choices_registry(SMOKE_CLI_DOC_PARSER_SPECS)
)


def resolve_smoke_cli_doc_target_names(requested_target_name: str | None = None) -> tuple[str, ...]:
    return tuple(SMOKE_CLI_DOC_AUDIT_TARGET_SELECTOR.resolve_target_names(requested_target_name))



def build_smoke_cli_doc_audit_parser() -> argparse.ArgumentParser:
    return SMOKE_CLI_DOC_AUDIT_PARSER_SPEC.build_parser()


def smoke_cli_doc_spec(script_name: str) -> SmokeCliDocSpec:
    spec = SMOKE_CLI_DOC_SPECS_BY_SCRIPT_NAME.get(script_name)
    if spec is None:
        raise ValueError(f"unknown smoke cli doc spec {script_name!r}")
    return spec



def build_smoke_cli_doc_render_parser() -> argparse.ArgumentParser:
    return SMOKE_CLI_DOC_RENDER_PARSER_SPEC.build_parser()


def build_smoke_cli_doc_fix_parser() -> argparse.ArgumentParser:
    return SMOKE_CLI_DOC_FIX_PARSER_SPEC.build_parser()


def build_smoke_cli_doc_artifacts_parser(*, readme_path: Path) -> argparse.ArgumentParser:
    return SMOKE_CLI_DOC_ARTIFACTS_PARSER_SPEC.build_parser(readme_path=readme_path)



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


def markdown_section_bounds(markdown: str, *, heading: str) -> tuple[int, int]:
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

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            hashes, _, title = stripped.partition(" ")
            if title and len(hashes) <= section_level:
                end_index = index
                break
    return start_index, end_index


def replace_markdown_section(markdown: str, *, heading: str, body: str) -> str:
    lines = markdown.splitlines()
    start_index, end_index = markdown_section_bounds(markdown, heading=heading)
    body_lines = body.splitlines()
    updated = "\n".join([*lines[:start_index], *body_lines, *lines[end_index:]])
    if markdown.endswith("\n"):
        updated += "\n"
    return updated


def repair_smoke_cli_readme_sections(
    markdown: str,
    *,
    requested_target_name: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    updated_markdown = markdown
    repaired_script_names: list[str] = []

    for script_name, rendered_body in render_smoke_cli_readme_sections(
        requested_target_name=requested_target_name,
        body_only=True,
    ):
        spec = smoke_cli_doc_spec(script_name)
        if markdown_section_text(updated_markdown, heading=spec.readme_section_heading) == rendered_body:
            continue
        updated_markdown = replace_markdown_section(
            updated_markdown,
            heading=spec.readme_section_heading,
            body=rendered_body,
        )
        repaired_script_names.append(script_name)

    return updated_markdown, tuple(repaired_script_names)



def collect_smoke_cli_readme_diffs(
    markdown: str,
    *,
    requested_target_name: str | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (script_name, diff_lines)
        for script_name in resolve_smoke_cli_doc_target_names(requested_target_name)
        if (diff_lines := smoke_cli_readme_diff_lines(markdown, script_name=script_name))
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
