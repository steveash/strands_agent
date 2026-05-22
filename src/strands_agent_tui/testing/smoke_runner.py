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

    @property
    def display_label(self) -> str:
        return self.display_name or self.name


@dataclass(frozen=True)
class SmokeCliExample:
    command: str
    target_name: str | None = None
    description: str | None = None
    readme_description: str | None = None


@dataclass(frozen=True)
class SmokeScriptTargetTemplate:
    name: str
    script_filename: str
    args: tuple[str, ...] = ()
    display_name: str | None = None

    def build_target(self, *, script_dir: Path) -> SmokeScriptTarget:
        return SmokeScriptTarget(
            self.name,
            script_dir / self.script_filename,
            args=self.args,
            display_name=self.display_name,
        )

    def build_doc_target(self) -> SmokeScriptTarget:
        return SmokeScriptTarget(
            self.name,
            Path(self.script_filename),
            args=self.args,
            display_name=self.display_name,
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

    def _all_choice_target_names(self) -> Mapping[str, tuple[str, ...]]:
        if self.choice_target_names is not None:
            return self.choice_target_names
        return {
            **{target_name: (target_name,) for target_name in self.targets},
            **self.alias_target_names,
        }

    def _all_choice_display_names(self) -> Mapping[str, tuple[str, ...]]:
        if self.choice_display_names is not None:
            return self.choice_display_names
        return {
            choice_name: tuple(self.targets[target_name].display_label for target_name in target_names)
            for choice_name, target_names in self._all_choice_target_names().items()
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
    readme_intro_snippets: tuple[str, ...] = ()
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

    def help_required_snippets(self) -> tuple[str, ...]:
        selector = self._build_doc_selector()
        snippets = [self.item_help]
        if selector.alias_target_names:
            snippets.append(
                f"{self.alias_heading}: "
                + " ".join(
                    f"{name} -> {', '.join(selector.resolve_display_names(name))}"
                    for name in selector.alias_target_names
                )
            )
        snippets.extend(
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
        return tuple(snippets)

    def _format_readme_command(self, command: str) -> str:
        return f".venv/bin/python scripts/{command}"

    def readme_required_snippets(self) -> tuple[str, ...]:
        snippets: list[str] = []
        if self.examples:
            snippets.append(self._format_readme_command(self.examples[0].command))
        else:
            snippets.append(self._format_readme_command(f"{self.script_name}.py"))
        snippets.extend(self.readme_intro_snippets)
        snippets.extend(
            f"`{self._format_readme_command(example.command)}` {example.readme_description}"
            for example in self.examples[1:]
            if example.readme_description is not None
        )
        return tuple(snippets)


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
        SmokeScriptTargetTemplate("live", "live_smoke.py"),
    ),
    default_target_name="local",
    alias_target_names={
        "local": ("summary-utils", "shell-tool", "replay"),
        "all": ("summary-utils", "shell-tool", "replay", "live"),
    },
    examples=(
        SmokeCliExample("standalone_smoke.py"),
        SmokeCliExample(
            "standalone_smoke.py local",
            target_name="local",
            readme_description=(
                "explicitly re-runs the default `local` alias "
                "(`summary_utils`, `shell_tool`, `replay`)"
            ),
        ),
        SmokeCliExample(
            "standalone_smoke.py all",
            target_name="all",
            readme_description=(
                "runs the live-inclusive alias "
                "(`summary_utils`, `shell_tool`, `replay`, `live`)"
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
    readme_intro_snippets=(
        "default `local` bundle runs `summary_utils`, `shell_tool`, and `replay` smokes together",
    ),
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
    readme_intro_snippets=("default bundle runs both triage targets",),
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
    readme_intro_snippets=("bundle runs all recovery targets by default",),
)


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
) -> int:
    summary_metadata = _resolve_wrapper_metadata(wrapper_metadata=wrapper_metadata, summary_label=summary_label)
    started_at = perf_counter()
    passed_count = 0
    total_count = len(targets)

    for target in targets:
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            python_executable=python_executable,
            failure_predicate=failure_predicate,
        )
        if exit_code != 0:
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
