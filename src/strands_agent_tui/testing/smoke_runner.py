from __future__ import annotations

import subprocess
import sys
import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TextIO

from .smoke_assertions import is_failed_smoke_check_line


@dataclass(frozen=True)
class SmokeScriptTarget:
    name: str
    script_path: Path
    args: tuple[str, ...] = ()
    display_name: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def display_label(self) -> str:
        return self.display_name or self.name


@dataclass(frozen=True)
class SmokeCliExample:
    command: str
    target_name: str | None = None
    description: str | None = None
    readme_description: str | None = None

    def render_readme_snippet(self, *, format_command: Callable[[str], str]) -> str | None:
        if self.readme_description is None:
            return None
        return f"`{format_command(self.command)}` {self.readme_description}"


@dataclass(frozen=True)
class SmokeScriptTargetTemplate:
    name: str
    script_filename: str
    args: tuple[str, ...] = ()
    display_name: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def build_target(self, *, script_dir: Path) -> SmokeScriptTarget:
        return SmokeScriptTarget(
            self.name,
            script_dir / self.script_filename,
            args=self.args,
            display_name=self.display_name,
            metadata=dict(self.metadata),
        )

    def build_doc_target(self) -> SmokeScriptTarget:
        return SmokeScriptTarget(
            self.name,
            Path(self.script_filename),
            args=self.args,
            display_name=self.display_name,
            metadata=dict(self.metadata),
        )


def format_smoke_summary_message(
    *,
    passed_count: int,
    total_count: int,
    elapsed_seconds: float,
    item_label: str = "targets",
    before_failure: bool = False,
) -> str:
    if before_failure:
        return f"summary: {passed_count}/{total_count} {item_label} passed before failure in {elapsed_seconds:.2f}s"
    return f"summary: {passed_count}/{total_count} {item_label} passed in {elapsed_seconds:.2f}s"


@dataclass(frozen=True)
class SmokeWrapperMetadata:
    summary_label: str
    summary_item_label: str = "targets"

    @property
    def line_prefix(self) -> str:
        return f"[{self.summary_label}]"

    @property
    def summary_line_prefix(self) -> str:
        return f"{self.line_prefix} summary:"

    def format_line(self, message: str) -> str:
        return f"{self.line_prefix} {message}"

    def running_message(self, *, item_name: str) -> str:
        return f"running {item_name}"

    def passed_message(self, *, item_name: str, elapsed_seconds: float) -> str:
        return f"{item_name} passed in {elapsed_seconds:.2f}s"

    def failed_message(self, *, item_name: str, elapsed_seconds: float) -> str:
        return f"{item_name} failed in {elapsed_seconds:.2f}s"

    def running_line(self, *, item_name: str) -> str:
        return self.format_line(self.running_message(item_name=item_name))

    def passed_line(self, *, item_name: str, elapsed_seconds: float) -> str:
        return self.format_line(self.passed_message(item_name=item_name, elapsed_seconds=elapsed_seconds))

    def failed_line(self, *, item_name: str, elapsed_seconds: float) -> str:
        return self.format_line(self.failed_message(item_name=item_name, elapsed_seconds=elapsed_seconds))

    def success_summary_message(self, *, passed_count: int, total_count: int, elapsed_seconds: float) -> str:
        return format_smoke_summary_message(
            passed_count=passed_count,
            total_count=total_count,
            elapsed_seconds=elapsed_seconds,
            item_label=self.summary_item_label,
        )

    def failure_summary_message(self, *, passed_count: int, total_count: int, elapsed_seconds: float) -> str:
        return format_smoke_summary_message(
            passed_count=passed_count,
            total_count=total_count,
            elapsed_seconds=elapsed_seconds,
            item_label=self.summary_item_label,
            before_failure=True,
        )

    def success_summary_line(self, *, passed_count: int, total_count: int, elapsed_seconds: float) -> str:
        return self.format_line(
            self.success_summary_message(
                passed_count=passed_count,
                total_count=total_count,
                elapsed_seconds=elapsed_seconds,
            )
        )

    def failure_summary_line(self, *, passed_count: int, total_count: int, elapsed_seconds: float) -> str:
        return self.format_line(
            self.failure_summary_message(
                passed_count=passed_count,
                total_count=total_count,
                elapsed_seconds=elapsed_seconds,
            )
        )


def summary_line_prefixes(wrapper_metadata: Iterable[SmokeWrapperMetadata]) -> tuple[str, ...]:
    prefixes: list[str] = []
    for metadata in wrapper_metadata:
        prefix = metadata.summary_line_prefix
        if prefix not in prefixes:
            prefixes.append(prefix)
    return tuple(prefixes)


STANDALONE_SMOKE_WRAPPER = SmokeWrapperMetadata(summary_label="standalone-smoke")
SESSION_TRIAGE_SMOKE_WRAPPER = SmokeWrapperMetadata(summary_label="session-triage-smoke")
SESSION_RECOVERY_SMOKE_WRAPPER = SmokeWrapperMetadata(summary_label="session-recovery-smoke")
SMOKE_MATRIX_WRAPPER = SmokeWrapperMetadata(summary_label="smoke-matrix", summary_item_label="bundles")


@dataclass(frozen=True)
class SmokeTargetSelector:
    targets: Mapping[str, SmokeScriptTarget]
    default_target_name: str
    alias_target_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    choice_target_names: Mapping[str, tuple[str, ...]] | None = None
    choice_display_names: Mapping[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        valid_target_names = set(self.targets)
        choice_target_names = self._all_choice_target_names()
        if self.default_target_name not in choice_target_names:
            raise ValueError(f"unknown default smoke target {self.default_target_name!r}")
        for choice_name, target_names in choice_target_names.items():
            unknown_target_names = [target_name for target_name in target_names if target_name not in valid_target_names]
            if unknown_target_names:
                choice_label = "alias" if choice_name in self.alias_target_names else "choice"
                raise ValueError(
                    f"{choice_label} {choice_name!r} references unknown smoke targets: {', '.join(unknown_target_names)}"
                )
        if self.choice_display_names is not None:
            unknown_choice_names = [
                choice_name for choice_name in self.choice_display_names if choice_name not in choice_target_names
            ]
            if unknown_choice_names:
                raise ValueError(
                    "choice display names reference unknown smoke choices: "
                    + ", ".join(sorted(unknown_choice_names))
                )
            mismatched_choice_names = [
                choice_name
                for choice_name, display_names in self.choice_display_names.items()
                if len(display_names) != len(choice_target_names[choice_name])
            ]
            if mismatched_choice_names:
                raise ValueError(
                    "choice display names must match target counts for: "
                    + ", ".join(sorted(mismatched_choice_names))
                )

    def _all_choice_target_names(self) -> Mapping[str, tuple[str, ...]]:
        if self.choice_target_names is not None:
            return self.choice_target_names
        return {
            **{target_name: (target_name,) for target_name in self.targets},
            **self.alias_target_names,
        }

    def _all_choice_display_names(self) -> Mapping[str, tuple[str, ...]]:
        default_display_names = {
            choice_name: tuple(self.targets[target_name].display_label for target_name in target_names)
            for choice_name, target_names in self._all_choice_target_names().items()
        }
        if self.choice_display_names is None:
            return default_display_names
        return {
            **default_display_names,
            **self.choice_display_names,
        }

    @property
    def choices(self) -> tuple[str, ...]:
        return tuple(self._all_choice_target_names().keys())

    def resolve_target_names(self, requested_target_name: str | None = None) -> list[str]:
        target_name = self.default_target_name if requested_target_name is None else requested_target_name
        choice_target_names = self._all_choice_target_names()
        if target_name not in choice_target_names:
            raise ValueError(f"unknown smoke target {target_name!r}")
        return list(choice_target_names[target_name])

    def resolve_display_names(self, requested_target_name: str | None = None) -> list[str]:
        target_name = self.default_target_name if requested_target_name is None else requested_target_name
        choice_display_names = self._all_choice_display_names()
        if target_name not in choice_display_names:
            raise ValueError(f"unknown smoke target {target_name!r}")
        return list(choice_display_names[target_name])

    def resolve_targets(self, requested_target_name: str | None = None) -> list[SmokeScriptTarget]:
        return [self.targets[target_name] for target_name in self.resolve_target_names(requested_target_name)]


SmokeFailurePredicate = Callable[[str], bool]
SmokeOutputLineFilter = Callable[[str], bool]
SmokeOutputLineObserver = Callable[[str], None]
SmokeFailureHintBuilder = Callable[[SmokeScriptTarget, Sequence[str]], str | None]


def _describe_cli_example(
    example: SmokeCliExample,
    *,
    default_target_name: str,
    alias_target_names: Mapping[str, Sequence[str]],
    resolve_display_names: Callable[[str | None], Sequence[str]],
    single_choice_description: str,
) -> str:
    if example.description is not None:
        return example.description

    requested_target_name = default_target_name if example.target_name is None else example.target_name
    resolved_target_names = ", ".join(resolve_display_names(example.target_name))
    if requested_target_name in alias_target_names:
        if example.target_name is None:
            return f"default {requested_target_name} alias -> {resolved_target_names}"
        return f"{requested_target_name} alias -> {resolved_target_names}"
    if example.target_name is None:
        return f"default target -> {resolved_target_names}"
    return single_choice_description


def build_smoke_cli_parser(
    *,
    description: str,
    choices: Sequence[str],
    default_target_name: str,
    resolve_target_names: Callable[[str | None], Sequence[str]],
    item_help: str,
    alias_target_names: Mapping[str, Sequence[str]] | None = None,
    resolve_display_names: Callable[[str | None], Sequence[str]] | None = None,
    alias_heading: str = "Alias details",
    examples: Sequence[SmokeCliExample] = (),
    single_choice_description: str = "single target",
) -> argparse.ArgumentParser:
    alias_target_names = {} if alias_target_names is None else alias_target_names
    resolve_display_names = resolve_target_names if resolve_display_names is None else resolve_display_names
    epilog_lines: list[str] = []
    if alias_target_names:
        epilog_lines.append(f"{alias_heading}:")
        epilog_lines.extend(
            f"  {name} -> {', '.join(resolve_display_names(name))}" for name in alias_target_names
        )
    if examples:
        if epilog_lines:
            epilog_lines.append("")
        epilog_lines.append("Examples:")
        epilog_lines.extend(
            f"  {example.command}  # {_describe_cli_example(example, default_target_name=default_target_name, alias_target_names=alias_target_names, resolve_display_names=resolve_display_names, single_choice_description=single_choice_description)}"
            for example in examples
        )

    help_text = item_help
    if alias_target_names:
        help_text = (
            f"{help_text} Aliases: "
            + "; ".join(f"{name} -> {', '.join(resolve_display_names(name))}" for name in alias_target_names)
            + "."
        )

    parser = argparse.ArgumentParser(
        description=description,
        epilog="\n".join(epilog_lines) if epilog_lines else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=tuple(choices),
        default=default_target_name,
        help=help_text,
    )
    return parser


@dataclass(frozen=True)
class SmokeWrapperCliSpec:
    script_name: str
    description: str
    item_help: str
    target_templates: tuple[SmokeScriptTargetTemplate, ...]
    default_target_name: str
    alias_target_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    choice_target_names: Mapping[str, tuple[str, ...]] | None = None
    choice_display_names: Mapping[str, tuple[str, ...]] | None = None
    examples: tuple[SmokeCliExample, ...] = ()
    wrapper_metadata: SmokeWrapperMetadata | None = None
    readme_section_heading: str | None = None
    readme_section_intro: str | None = None
    help_required_snippets_extra: tuple[str, ...] = ()
    readme_intro_snippets: tuple[str, ...] = ()
    readme_intro_paragraphs: tuple[str, ...] = ()
    readme_extra_shortcut_snippets: tuple[str, ...] = ()
    readme_extra_shortcut_insert_at: int | None = None
    readme_shortcut_heading: str = "Operator shortcuts:"
    alias_heading: str = "Alias details"
    single_choice_description: str = "single target"

    def build_targets(self, *, script_dir: Path) -> dict[str, SmokeScriptTarget]:
        return {
            template.name: template.build_target(script_dir=script_dir)
            for template in self.target_templates
        }

    def build_target_selector(self, *, script_dir: Path) -> SmokeTargetSelector:
        return SmokeTargetSelector(
            targets=self.build_targets(script_dir=script_dir),
            default_target_name=self.default_target_name,
            alias_target_names=self.alias_target_names,
            choice_target_names=self.choice_target_names,
            choice_display_names=self.choice_display_names,
        )

    def _build_doc_selector(self) -> SmokeTargetSelector:
        return SmokeTargetSelector(
            targets={template.name: template.build_doc_target() for template in self.target_templates},
            default_target_name=self.default_target_name,
            alias_target_names=self.alias_target_names,
            choice_target_names=self.choice_target_names,
            choice_display_names=self.choice_display_names,
        )

    def resolve_target_names(self, requested_target_name: str | None = None) -> tuple[str, ...]:
        return tuple(self._build_doc_selector().resolve_target_names(requested_target_name))

    def resolve_display_names(self, requested_target_name: str | None = None) -> tuple[str, ...]:
        return tuple(self._build_doc_selector().resolve_display_names(requested_target_name))

    def resolve_targets(
        self,
        *,
        script_dir: Path,
        requested_target_name: str | None = None,
    ) -> tuple[SmokeScriptTarget, ...]:
        return tuple(self.build_target_selector(script_dir=script_dir).resolve_targets(requested_target_name))

    def default_target_names(self) -> tuple[str, ...]:
        return self.resolve_target_names()

    def default_display_names(self) -> tuple[str, ...]:
        return self.resolve_display_names()

    def default_targets(self, *, script_dir: Path) -> tuple[SmokeScriptTarget, ...]:
        return self.resolve_targets(script_dir=script_dir)

    def build_parser(self, *, script_dir: Path) -> argparse.ArgumentParser:
        selector = self.build_target_selector(script_dir=script_dir)
        return build_smoke_cli_parser(
            description=self.description,
            choices=selector.choices,
            default_target_name=selector.default_target_name,
            resolve_target_names=selector.resolve_target_names,
            resolve_display_names=selector.resolve_display_names,
            item_help=self.item_help,
            alias_target_names=selector.alias_target_names,
            alias_heading=self.alias_heading,
            examples=self.examples,
            single_choice_description=self.single_choice_description,
        )

    def help_alias_lines(self) -> tuple[str, ...]:
        selector = self._build_doc_selector()
        return tuple(
            f"{name} -> {', '.join(selector.resolve_display_names(name))}"
            for name in selector.alias_target_names
        )

    def help_example_lines(self) -> tuple[str, ...]:
        selector = self._build_doc_selector()
        return tuple(
            f"{example.command} # "
            + _describe_cli_example(
                example,
                default_target_name=selector.default_target_name,
                alias_target_names=selector.alias_target_names,
                resolve_display_names=selector.resolve_display_names,
                single_choice_description=self.single_choice_description,
            )
            for example in self.examples
        )

    def help_required_snippets(self) -> tuple[str, ...]:
        snippets = [self.item_help, *self.help_required_snippets_extra]
        help_alias_lines = self.help_alias_lines()
        if help_alias_lines:
            snippets.append(f"{self.alias_heading}: " + " ".join(help_alias_lines))
        snippets.extend(self.help_example_lines())
        return tuple(snippets)

    def _format_readme_command(self, command: str) -> str:
        return f".venv/bin/python scripts/{command}"

    def readme_reference_command(self) -> str:
        if self.examples:
            return self._format_readme_command(self.examples[0].command)
        return self._format_readme_command(f"{self.script_name}.py")

    def readme_reference_block(self) -> str:
        return f"```bash\n{self.readme_reference_command()}\n```"

    def readme_intro_blocks(self) -> tuple[str, ...]:
        if self.readme_intro_paragraphs:
            return self.readme_intro_paragraphs
        return self.readme_intro_snippets

    def readme_shortcut_snippets(self) -> tuple[str, ...]:
        snippets: list[str] = []
        for example in self.examples[1:]:
            snippet = example.render_readme_snippet(format_command=self._format_readme_command)
            if snippet is not None:
                snippets.append(snippet)
        return tuple(snippets)

    def readme_all_shortcut_snippets(self) -> tuple[str, ...]:
        snippets = list(self.readme_shortcut_snippets())
        if not self.readme_extra_shortcut_snippets:
            return tuple(snippets)
        insert_at = len(snippets) if self.readme_extra_shortcut_insert_at is None else self.readme_extra_shortcut_insert_at
        snippets[insert_at:insert_at] = list(self.readme_extra_shortcut_snippets)
        return tuple(snippets)

    def readme_operator_shortcut_lines(self) -> tuple[str, ...]:
        return tuple(f"- {snippet}" for snippet in self.readme_all_shortcut_snippets())

    def render_readme_section_body(self) -> str:
        if self.readme_section_intro is None:
            raise ValueError(f"readme_section_intro is required for {self.script_name}")

        lines = [self.readme_section_intro, "", *self.readme_reference_block().splitlines()]
        intro_blocks = self.readme_intro_blocks()
        if intro_blocks:
            lines.append("")
            for index, paragraph in enumerate(intro_blocks):
                if index:
                    lines.append("")
                lines.append(paragraph)

        shortcut_lines = self.readme_operator_shortcut_lines()
        if shortcut_lines:
            lines.extend(("", self.readme_shortcut_heading, *shortcut_lines))
        return "\n".join(lines)

    def render_readme_section(self) -> str:
        if self.readme_section_heading is None:
            raise ValueError(f"readme_section_heading is required for {self.script_name}")
        return f"### {self.readme_section_heading}\n\n{self.render_readme_section_body()}"

    def readme_required_snippets(self) -> tuple[str, ...]:
        return (
            self.readme_reference_block(),
            *self.readme_intro_blocks(),
            *self.readme_all_shortcut_snippets(),
        )


STANDALONE_SMOKE_CLI_SPEC = SmokeWrapperCliSpec(
    script_name="standalone_smoke",
    description=(
        "Run standalone smoke scripts and fail fast on any emitted '= False' check. "
        "The default 'local' bundle excludes the live runtime target."
    ),
    item_help="Which standalone smoke surface to run.",
    target_templates=(
        SmokeScriptTargetTemplate("summary-utils", "summary_utils_smoke.py"),
        SmokeScriptTargetTemplate("shell-tool", "shell_tool_smoke.py"),
        SmokeScriptTargetTemplate("replay", "replay_smoke.py"),
        SmokeScriptTargetTemplate("timeline", "timeline_smoke.py"),
        SmokeScriptTargetTemplate("docs", "smoke_cli_docs_smoke.py"),
        SmokeScriptTargetTemplate("docs-artifacts", "smoke_cli_docs_artifacts_smoke.py"),
        SmokeScriptTargetTemplate("docs-rerun-hint", "standalone_docs_rerun_hint_smoke.py"),
        SmokeScriptTargetTemplate("matrix-artifact-roots", "smoke_matrix_artifact_roots_smoke.py"),
        SmokeScriptTargetTemplate("matrix-all-review-order", "smoke_matrix_all_review_order_smoke.py"),
        SmokeScriptTargetTemplate(
            "matrix-all-review-missing-api-key",
            "smoke_matrix_all_review_missing_api_key_smoke.py",
        ),
        SmokeScriptTargetTemplate("matrix-docs-review-hint", "smoke_matrix_docs_review_hint_smoke.py"),
        SmokeScriptTargetTemplate("live", "live_smoke.py"),
    ),
    default_target_name="local",
    alias_target_names={
        "local": ("summary-utils", "shell-tool", "replay", "timeline", "docs", "docs-artifacts"),
        "docs-parity-only": ("docs", "docs-artifacts", "docs-rerun-hint"),
        "docs-focused": (
            "docs",
            "docs-artifacts",
            "docs-rerun-hint",
            "matrix-artifact-roots",
            "matrix-all-review-order",
            "matrix-all-review-missing-api-key",
            "matrix-docs-review-hint",
        ),
        "docs-review-only": (
            "matrix-artifact-roots",
            "matrix-all-review-order",
            "matrix-all-review-missing-api-key",
            "matrix-docs-review-hint",
        ),
        "all": ("summary-utils", "shell-tool", "replay", "timeline", "docs", "docs-artifacts", "live"),
    },
    examples=(
        SmokeCliExample("standalone_smoke.py"),
        SmokeCliExample(
            "standalone_smoke.py local",
            target_name="local",
            readme_description=(
                "explicitly re-runs the default `local` alias "
                "(`summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, `smoke_cli_docs_artifacts`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py all",
            target_name="all",
            readme_description=(
                "runs the live-inclusive alias "
                "(`summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, `smoke_cli_docs_artifacts`, `live`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py timeline",
            target_name="timeline",
            readme_description="runs just the timeline smoke target",
        ),
        SmokeCliExample(
            "standalone_smoke.py docs",
            target_name="docs",
            readme_description="runs just the smoke CLI docs parity target",
        ),
        SmokeCliExample(
            "standalone_smoke.py docs-artifacts",
            target_name="docs-artifacts",
            readme_description="runs the smoke CLI render/fix artifact contract smoke end-to-end",
        ),
        SmokeCliExample(
            "standalone_smoke.py docs-rerun-hint",
            target_name="docs-rerun-hint",
            readme_description=(
                "runs the real subprocess standalone wrapper docs-drift regression that proves the "
                "docs-parity-only rerun hint lands before the fail-fast summary"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py docs-parity-only",
            target_name="docs-parity-only",
            readme_description=(
                "re-runs only the docs parity alias "
                "(`docs`, `docs-artifacts`, `docs-rerun-hint`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py docs-focused",
            target_name="docs-focused",
            readme_description=(
                "re-runs the broader docs parity + docs-review lane alias "
                "(`docs`, `docs-artifacts`, `docs-rerun-hint`, `matrix-artifact-roots`, "
                "`matrix-all-review-order`, `matrix-all-review-missing-api-key`, "
                "`matrix-docs-review-hint`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py docs-review-only",
            target_name="docs-review-only",
            readme_description=(
                "re-runs only the docs-review lane regressions "
                "(`matrix-artifact-roots`, `matrix-all-review-order`, "
                "`matrix-all-review-missing-api-key`, `matrix-docs-review-hint`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py matrix-artifact-roots",
            target_name="matrix-artifact-roots",
            readme_description=(
                "runs the fake-live smoke-matrix artifact-root regression that proves `review` and "
                "`all-review` keep distinct docs-review bundles"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py matrix-all-review-order",
            target_name="matrix-all-review-order",
            readme_description=(
                "runs the real `all-review` smoke-matrix regression that proves pending docs-review "
                "breadcrumbs appear before the live-runtime hint and the docs-review-only rerun hint lands "
                "before the fail-fast summary"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py matrix-all-review-missing-api-key",
            target_name="matrix-all-review-missing-api-key",
            readme_description=(
                "runs the real subprocess `all-review` live-runtime failure regression that proves the "
                "missing-API-key hint lands after the persisted docs-review breadcrumbs and before the "
                "docs-review-only rerun hint"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py matrix-docs-review-hint",
            target_name="matrix-docs-review-hint",
            readme_description=(
                "runs the real subprocess docs-review failure regression that proves the docs-review-only "
                "rerun hint lands after the persisted review matrix-summary path"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py replay",
            target_name="replay",
            readme_description="runs just the replay smoke target",
        ),
    ),
    wrapper_metadata=STANDALONE_SMOKE_WRAPPER,
    readme_section_heading="Standalone local smoke bundle",
    readme_section_intro="To verify the remaining local smoke surfaces with shared fail-fast `= False` handling:",
    readme_intro_paragraphs=(
        "This default `local` bundle runs `summary_utils`, `shell_tool`, `replay`, `timeline`, `smoke_cli_docs`, and `smoke_cli_docs_artifacts` smokes together, exits non-zero on the first failing boolean result line, and ends with a concise `[standalone-smoke] summary: ...` footer. Use `.venv/bin/python scripts/standalone_smoke.py docs-parity-only` to rerun the docs parity alias plus its dedicated subprocess rerun-hint regression, `.venv/bin/python scripts/standalone_smoke.py docs-review-only` to rerun just the docs-review lane regressions, `.venv/bin/python scripts/standalone_smoke.py docs-focused` for the broader docs parity + docs-review lane bundle, or `.venv/bin/python scripts/standalone_smoke.py all` after exporting live-runtime env vars if you also want to include the live smoke target.",
    ),
    readme_extra_shortcut_snippets=(
        "`.venv/bin/python scripts/smoke_cli_docs_smoke.py standalone_smoke` audits only the standalone wrapper docs (`session_triage_smoke`, `session_recovery_smoke`, and `smoke_matrix` also work here)",
        "`.venv/bin/python scripts/smoke_cli_docs_smoke.py all` re-runs docs parity for every public smoke wrapper without the rest of the standalone bundle",
        "`.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py` exercises drifted README render/fix review artifacts end-to-end with fail-fast contract checks",
        "`.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py session_triage_smoke --output-dir artifacts/smoke-cli-docs-artifacts/session-triage` preserves a session-triage wrapper artifact bundle for later review",
        "`.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py all --output-dir artifacts/smoke-cli-docs-artifacts --readme-path README.md` preserves the all-wrapper contract bundle against a specific README copy while keeping predictable artifact paths",
        "`.venv/bin/python scripts/smoke_cli_docs_artifacts_smoke.py all --output-dir artifacts/smoke-cli-docs-artifacts --bundle-index-path artifacts/smoke-cli-docs-artifacts/index.json` persists one machine-readable bundle index for CI or later review",
        "`.venv/bin/python scripts/smoke_cli_docs_render.py standalone_smoke --body-only` previews just the rendered standalone wrapper README body before a manual docs fix",
        "`.venv/bin/python scripts/smoke_cli_docs_render.py all --output-dir artifacts/smoke-cli-docs-preview` exports rendered README sections for every public smoke wrapper",
        "`.venv/bin/python scripts/smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview` exports only the currently drifted smoke wrapper README sections",
        "`.venv/bin/python scripts/smoke_cli_docs_render.py all --drift-only --output-dir artifacts/smoke-cli-docs-preview --manifest-output artifacts/smoke-cli-docs-preview.json --diff-output artifacts/smoke-cli-docs-review.patch` persists drift-only review artifacts as rendered sections plus JSON manifest summaries/checksums and unified diff files",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py standalone_smoke --diff` previews the standalone wrapper README diff before writing metadata-backed repairs",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py all --check` exits non-zero when any public smoke wrapper README section drifts",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py all --check --json` emits machine-readable drift results with manifest-style summaries/checksums for CI without scraping prose summaries",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py all --check --json-output artifacts/smoke-cli-docs-fix.json` persists the same machine-readable drift report with manifest-style summaries/checksums alongside the normal console summary",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py standalone_smoke` repairs the standalone wrapper README section in place from shared metadata",
        "`.venv/bin/python scripts/smoke_cli_docs_fix.py all` repairs every public smoke wrapper README section in place",
    ),
    readme_extra_shortcut_insert_at=6,
)

SESSION_TRIAGE_SMOKE_CLI_SPEC = SmokeWrapperCliSpec(
    script_name="session_triage_smoke",
    description="Run picker/switcher smoke scripts and fail fast on any emitted '= False' check.",
    item_help="Which session-triage smoke surface to run.",
    target_templates=(
        SmokeScriptTargetTemplate("picker", "session_picker_smoke.py"),
        SmokeScriptTargetTemplate("switcher", "session_switcher_smoke.py"),
    ),
    default_target_name="both",
    alias_target_names={
        "both": ("picker", "switcher"),
        "all": ("picker", "switcher"),
    },
    examples=(
        SmokeCliExample("session_triage_smoke.py"),
        SmokeCliExample(
            "session_triage_smoke.py both",
            target_name="both",
            readme_description="explicitly re-runs the default picker+switcher alias",
        ),
        SmokeCliExample(
            "session_triage_smoke.py all",
            target_name="all",
            readme_description="is an explicit alias for the same picker+switcher bundle",
        ),
        SmokeCliExample(
            "session_triage_smoke.py picker",
            target_name="picker",
            readme_description="runs only the launch-time picker smoke",
        ),
    ),
    wrapper_metadata=SESSION_TRIAGE_SMOKE_WRAPPER,
    readme_section_heading="Session triage smoke bundle",
    readme_section_intro="To run the picker + switcher smoke surfaces together with shared fail-fast handling:",
    readme_intro_paragraphs=(
        "This default bundle runs both triage targets, accepts either `both` or `all` for the combined picker+switcher selection, and ends with a concise `[session-triage-smoke] summary: ...` footer.",
    ),
)

SESSION_RECOVERY_SMOKE_CLI_SPEC = SmokeWrapperCliSpec(
    script_name="session_recovery_smoke",
    description=(
        "Run approval/session-state/live-restore smoke scripts and fail fast on any emitted '= False' check."
    ),
    item_help="Which recovery smoke surface to run.",
    target_templates=(
        SmokeScriptTargetTemplate("approval", "approval_smoke.py"),
        SmokeScriptTargetTemplate("approval-restart", "approval_restart_smoke.py"),
        SmokeScriptTargetTemplate("session-state", "session_state_smoke.py"),
        SmokeScriptTargetTemplate("live-restore", "live_restore_smoke.py"),
        SmokeScriptTargetTemplate("live-restore-denied", "live_restore_denied_smoke.py"),
    ),
    default_target_name="all",
    alias_target_names={
        "all": (
            "approval",
            "approval-restart",
            "session-state",
            "live-restore",
            "live-restore-denied",
        )
    },
    examples=(
        SmokeCliExample("session_recovery_smoke.py"),
        SmokeCliExample(
            "session_recovery_smoke.py all",
            target_name="all",
            readme_description=(
                "explicitly selects the full recovery bundle "
                "(`approval`, `approval-restart`, `session-state`, `live-restore`, `live-restore-denied`)"
            ),
        ),
        SmokeCliExample(
            "session_recovery_smoke.py live-restore",
            target_name="live-restore",
            readme_description="runs only the live-restore recovery target",
        ),
        SmokeCliExample(
            "session_recovery_smoke.py approval",
            target_name="approval",
            readme_description="runs only the approval smoke target",
        ),
    ),
    wrapper_metadata=SESSION_RECOVERY_SMOKE_WRAPPER,
    readme_section_heading="Session recovery smoke bundle",
    readme_section_intro="To run the approval/session-state/live-restore smoke surfaces together with shared fail-fast handling:",
    readme_intro_paragraphs=(
        "This bundle runs all recovery targets by default and ends with a concise `[session-recovery-smoke] summary: ...` footer.",
    ),
)

SMOKE_MATRIX_REVIEW_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-review"
SMOKE_MATRIX_ALL_REVIEW_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"


def smoke_matrix_docs_review_metadata(artifact_root: str) -> dict[str, str]:
    return {
        "artifact_root": artifact_root,
        "bundle_index_path": f"{artifact_root}/index.json",
        "drifted_readme_path": f"{artifact_root}/README-drifted.md",
        "render_output_dir": f"{artifact_root}/rendered",
        "render_manifest_path": f"{artifact_root}/render-manifest.json",
        "render_diff_path": f"{artifact_root}/render-review.patch",
        "fix_check_json_path": f"{artifact_root}/fix-check.json",
        "fix_repair_json_path": f"{artifact_root}/fix-repair.json",
        "fix_post_check_json_path": f"{artifact_root}/fix-post-check.json",
        "matrix_summary_path": f"{artifact_root}/matrix-summary.json",
    }


def smoke_matrix_docs_review_args(artifact_root: str) -> tuple[str, ...]:
    metadata = smoke_matrix_docs_review_metadata(artifact_root)
    return (
        "all",
        "--output-dir",
        metadata["artifact_root"],
        "--bundle-index-path",
        metadata["bundle_index_path"],
        "--drifted-readme-path",
        metadata["drifted_readme_path"],
        "--render-output-dir",
        metadata["render_output_dir"],
        "--render-manifest-path",
        metadata["render_manifest_path"],
        "--render-diff-path",
        metadata["render_diff_path"],
        "--fix-check-json-path",
        metadata["fix_check_json_path"],
        "--fix-repair-json-path",
        metadata["fix_repair_json_path"],
        "--fix-post-check-json-path",
        metadata["fix_post_check_json_path"],
    )


SMOKE_MATRIX_DOCS_REVIEW_METADATA = smoke_matrix_docs_review_metadata(SMOKE_MATRIX_REVIEW_ARTIFACT_ROOT)
SMOKE_MATRIX_ALL_REVIEW_DOCS_REVIEW_METADATA = smoke_matrix_docs_review_metadata(
    SMOKE_MATRIX_ALL_REVIEW_ARTIFACT_ROOT
)
SMOKE_MATRIX_DOCS_REVIEW_ARGS = smoke_matrix_docs_review_args(SMOKE_MATRIX_REVIEW_ARTIFACT_ROOT)
SMOKE_MATRIX_ALL_REVIEW_DOCS_REVIEW_ARGS = smoke_matrix_docs_review_args(SMOKE_MATRIX_ALL_REVIEW_ARTIFACT_ROOT)


SMOKE_MATRIX_CLI_SPEC = SmokeWrapperCliSpec(
    script_name="smoke_matrix",
    description=(
        "Run standalone, session-triage, recovery, and optional docs-review smoke bundles together "
        "with fail-fast handling. The default 'local' matrix excludes the opt-in live runtime smoke "
        "target, the 'all' alias swaps in the live-inclusive standalone bundle, the 'review' alias "
        "adds a smoke-doc artifact review lane, and the 'all-review' alias combines both."
    ),
    item_help="Which smoke bundle or bundle matrix to run.",
    target_templates=(
        SmokeScriptTargetTemplate(
            "standalone-local",
            "standalone_smoke.py",
            display_name="standalone",
        ),
        SmokeScriptTargetTemplate(
            "standalone-all",
            "standalone_smoke.py",
            args=("all",),
            display_name="standalone",
        ),
        SmokeScriptTargetTemplate("triage", "session_triage_smoke.py", display_name="triage"),
        SmokeScriptTargetTemplate("recovery", "session_recovery_smoke.py", display_name="recovery"),
        SmokeScriptTargetTemplate(
            "docs-review",
            "smoke_cli_docs_artifacts_smoke.py",
            args=SMOKE_MATRIX_DOCS_REVIEW_ARGS,
            display_name="docs-review",
            metadata=SMOKE_MATRIX_DOCS_REVIEW_METADATA,
        ),
        SmokeScriptTargetTemplate(
            "docs-review-all",
            "smoke_cli_docs_artifacts_smoke.py",
            args=SMOKE_MATRIX_ALL_REVIEW_DOCS_REVIEW_ARGS,
            display_name="docs-review",
            metadata=SMOKE_MATRIX_ALL_REVIEW_DOCS_REVIEW_METADATA,
        ),
    ),
    default_target_name="local",
    alias_target_names={
        "local": ("standalone-local", "triage", "recovery"),
        "all": ("standalone-all", "triage", "recovery"),
        "review": ("standalone-local", "triage", "recovery", "docs-review"),
        "all-review": ("standalone-all", "triage", "recovery", "docs-review-all"),
    },
    choice_target_names={
        "standalone": ("standalone-local",),
        "triage": ("triage",),
        "recovery": ("recovery",),
        "docs-review": ("docs-review",),
        "local": ("standalone-local", "triage", "recovery"),
        "all": ("standalone-all", "triage", "recovery"),
        "review": ("standalone-local", "triage", "recovery", "docs-review"),
        "all-review": ("standalone-all", "triage", "recovery", "docs-review-all"),
    },
    choice_display_names={
        "all": ("standalone (live-inclusive)", "triage", "recovery"),
        "all-review": ("standalone (live-inclusive)", "triage", "recovery", "docs-review"),
    },
    examples=(
        SmokeCliExample("smoke_matrix.py"),
        SmokeCliExample(
            "smoke_matrix.py local",
            target_name="local",
            readme_description=(
                "explicitly re-runs the default local matrix "
                "(`standalone`, `triage`, `recovery`)"
            ),
        ),
        SmokeCliExample(
            "smoke_matrix.py all",
            target_name="all",
            readme_description=(
                "swaps in the live-inclusive standalone bundle "
                "(`standalone (live-inclusive)`, `triage`, `recovery`)"
            ),
        ),
        SmokeCliExample(
            "smoke_matrix.py review",
            target_name="review",
            readme_description=(
                "adds the optional smoke-doc artifact review lane "
                "(`standalone`, `triage`, `recovery`, `docs-review`)"
            ),
        ),
        SmokeCliExample(
            "smoke_matrix.py all-review",
            target_name="all-review",
            readme_description=(
                "combines the live-inclusive standalone bundle with the smoke-doc artifact review lane "
                "while persisting docs-review artifacts under "
                "`artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review` "
                "(`standalone (live-inclusive)`, `triage`, `recovery`, `docs-review`)"
            ),
        ),
        SmokeCliExample(
            "smoke_matrix.py triage",
            target_name="triage",
            description="single bundle",
            readme_description="runs only the session-triage bundle",
        ),
        SmokeCliExample(
            "smoke_matrix.py standalone",
            target_name="standalone",
            description="single bundle",
            readme_description="runs only the standalone local bundle",
        ),
        SmokeCliExample(
            "smoke_matrix.py recovery",
            target_name="recovery",
            description="single bundle",
            readme_description="runs only the recovery bundle",
        ),
        SmokeCliExample(
            "smoke_matrix.py docs-review",
            target_name="docs-review",
            description="single bundle",
            readme_description=(
                "runs only the smoke-doc artifact review lane with persisted artifacts under "
                "`artifacts/smoke-cli-docs-artifacts/smoke-matrix-review`"
            ),
        ),
    ),
    wrapper_metadata=SMOKE_MATRIX_WRAPPER,
    readme_section_heading="Full local smoke matrix",
    readme_section_intro="To run the current local smoke bundles together with fail-fast handling:",
    help_required_snippets_extra=(
        "The default 'local' matrix excludes the opt-in live runtime smoke target, the 'all' alias swaps in the live-inclusive standalone bundle, the 'review' alias adds a smoke-doc artifact review lane, and the 'all-review' alias combines both.",
    ),
    readme_intro_paragraphs=(
        "This default `local` matrix runs the standalone local bundle plus the session-triage and recovery bundles together, suppresses the nested wrapper summary footers so the combined output stays focused on per-check lines, prints bundle-level `running ...`, `... passed in ...s`, or `... failed in ...s` summaries, and finishes with an overall matrix summary line. Use `.venv/bin/python scripts/smoke_matrix.py all` after exporting live-runtime env vars if you want the `all` alias to swap in the live-inclusive standalone bundle, `.venv/bin/python scripts/smoke_matrix.py review` to append a smoke-doc artifact review lane that persists its bundle under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-review`, or `.venv/bin/python scripts/smoke_matrix.py all-review` to combine both in one rerun while persisting the docs-review bundle under `artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review`.",
    ),
    alias_heading="Bundle aliases",
    single_choice_description="single bundle",
)


SMOKE_WRAPPER_CLI_SPECS = (
    STANDALONE_SMOKE_CLI_SPEC,
    SESSION_TRIAGE_SMOKE_CLI_SPEC,
    SESSION_RECOVERY_SMOKE_CLI_SPEC,
    SMOKE_MATRIX_CLI_SPEC,
)
SMOKE_WRAPPER_CLI_SPECS_BY_SCRIPT_NAME = {spec.script_name: spec for spec in SMOKE_WRAPPER_CLI_SPECS}
NON_MATRIX_SMOKE_WRAPPER_CLI_SPECS = tuple(
    spec for spec in SMOKE_WRAPPER_CLI_SPECS if spec.script_name != SMOKE_MATRIX_CLI_SPEC.script_name
)


def smoke_wrapper_cli_spec(script_name: str) -> SmokeWrapperCliSpec:
    spec = SMOKE_WRAPPER_CLI_SPECS_BY_SCRIPT_NAME.get(script_name)
    if spec is None:
        raise ValueError(f"unknown smoke wrapper cli spec {script_name!r}")
    return spec


def smoke_wrapper_metadata_from_specs(
    specs: Iterable[SmokeWrapperCliSpec],
) -> tuple[SmokeWrapperMetadata, ...]:
    metadata: list[SmokeWrapperMetadata] = []
    for spec in specs:
        wrapper_metadata = spec.wrapper_metadata
        if wrapper_metadata is not None and wrapper_metadata not in metadata:
            metadata.append(wrapper_metadata)
    return tuple(metadata)


NON_MATRIX_SMOKE_WRAPPER_METADATA = smoke_wrapper_metadata_from_specs(NON_MATRIX_SMOKE_WRAPPER_CLI_SPECS)
NON_MATRIX_SMOKE_WRAPPER_SUMMARY_PREFIXES = summary_line_prefixes(NON_MATRIX_SMOKE_WRAPPER_METADATA)


def _emit_wrapper_line(metadata: SmokeWrapperMetadata, message: str, *, stream: TextIO) -> None:
    print(metadata.format_line(message), file=stream)
    stream.flush()


def run_smoke_target(
    target: SmokeScriptTarget,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    python_executable: str = sys.executable,
    failure_predicate: SmokeFailurePredicate = is_failed_smoke_check_line,
    output_line_filter: SmokeOutputLineFilter | None = None,
    output_line_observer: SmokeOutputLineObserver | None = None,
) -> int:
    process = subprocess.Popen(
        [python_executable, str(target.script_path), *target.args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    failed_line: str | None = None
    assert process.stdout is not None
    for line in process.stdout:
        if output_line_observer is not None:
            output_line_observer(line)
        if output_line_filter is None or output_line_filter(line):
            print(line, end="", file=stdout)
            stdout.flush()
        if failure_predicate(line):
            failed_line = line.rstrip("\n")
            process.terminate()
            break

    return_code = process.wait()
    if failed_line is not None:
        print(f"{target.display_label} smoke failed fast: {failed_line}", file=stderr)
        return 1
    if return_code != 0:
        print(f"{target.display_label} smoke exited with status {return_code}", file=stderr)
        return return_code
    return 0


def _resolve_wrapper_metadata(
    *,
    wrapper_metadata: SmokeWrapperMetadata | None,
    summary_label: str | None,
) -> SmokeWrapperMetadata | None:
    if wrapper_metadata is not None:
        if summary_label is not None and wrapper_metadata.summary_label != summary_label:
            raise ValueError(
                "wrapper_metadata.summary_label does not match summary_label: "
                f"{wrapper_metadata.summary_label!r} != {summary_label!r}"
            )
        return wrapper_metadata
    if summary_label is None:
        return None
    return SmokeWrapperMetadata(summary_label=summary_label)


def run_smoke_targets(
    targets: Sequence[SmokeScriptTarget],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    python_executable: str = sys.executable,
    failure_predicate: SmokeFailurePredicate = is_failed_smoke_check_line,
    wrapper_metadata: SmokeWrapperMetadata | None = None,
    summary_label: str | None = None,
    failure_hint_builder: SmokeFailureHintBuilder | None = None,
) -> int:
    summary_metadata = _resolve_wrapper_metadata(wrapper_metadata=wrapper_metadata, summary_label=summary_label)
    started_at = perf_counter()
    passed_count = 0
    total_count = len(targets)

    for target in targets:
        observed_lines: list[str] | None = [] if failure_hint_builder is not None else None
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            python_executable=python_executable,
            failure_predicate=failure_predicate,
            output_line_observer=observed_lines.append if observed_lines is not None else None,
        )
        if exit_code != 0:
            hint = None
            if failure_hint_builder is not None:
                hint = failure_hint_builder(target, () if observed_lines is None else tuple(observed_lines))
            if hint is not None:
                if summary_metadata is not None:
                    _emit_wrapper_line(summary_metadata, hint, stream=stderr)
                else:
                    print(hint, file=stderr)
                    stderr.flush()
            if summary_metadata is not None:
                elapsed = perf_counter() - started_at
                _emit_wrapper_line(
                    summary_metadata,
                    summary_metadata.failure_summary_message(
                        passed_count=passed_count,
                        total_count=total_count,
                        elapsed_seconds=elapsed,
                    ),
                    stream=stderr,
                )
            return exit_code
        passed_count += 1

    if summary_metadata is not None:
        elapsed = perf_counter() - started_at
        _emit_wrapper_line(
            summary_metadata,
            summary_metadata.success_summary_message(
                passed_count=passed_count,
                total_count=total_count,
                elapsed_seconds=elapsed,
            ),
            stream=stdout,
        )
    return 0
