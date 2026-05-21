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


@dataclass(frozen=True)
class SmokeWrapperMetadata:
    summary_label: str

    @property
    def summary_line_prefix(self) -> str:
        return f"[{self.summary_label}] summary:"


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


@dataclass(frozen=True)
class SmokeTargetSelector:
    targets: Mapping[str, SmokeScriptTarget]
    default_target_name: str
    alias_target_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    choice_target_names: Mapping[str, tuple[str, ...]] | None = None

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

    def _all_choice_target_names(self) -> Mapping[str, tuple[str, ...]]:
        if self.choice_target_names is not None:
            return self.choice_target_names
        return {
            **{target_name: (target_name,) for target_name in self.targets},
            **self.alias_target_names,
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

    def resolve_targets(self, requested_target_name: str | None = None) -> list[SmokeScriptTarget]:
        return [self.targets[target_name] for target_name in self.resolve_target_names(requested_target_name)]


SmokeFailurePredicate = Callable[[str], bool]
SmokeOutputLineFilter = Callable[[str], bool]


def _format_choice_mapping(mapping: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{name} -> {', '.join(target_names)}" for name, target_names in mapping.items())


def _describe_cli_example(
    example: SmokeCliExample,
    *,
    default_target_name: str,
    alias_target_names: Mapping[str, Sequence[str]],
    resolve_target_names: Callable[[str | None], Sequence[str]],
    single_choice_description: str,
) -> str:
    if example.description is not None:
        return example.description

    requested_target_name = default_target_name if example.target_name is None else example.target_name
    resolved_target_names = ", ".join(resolve_target_names(example.target_name))
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
    alias_heading: str = "Alias details",
    examples: Sequence[SmokeCliExample] = (),
    single_choice_description: str = "single target",
) -> argparse.ArgumentParser:
    alias_target_names = {} if alias_target_names is None else alias_target_names
    epilog_lines: list[str] = []
    if alias_target_names:
        epilog_lines.append(f"{alias_heading}:")
        epilog_lines.extend(f"  {name} -> {', '.join(target_names)}" for name, target_names in alias_target_names.items())
    if examples:
        if epilog_lines:
            epilog_lines.append("")
        epilog_lines.append("Examples:")
        epilog_lines.extend(
            f"  {example.command}  # {_describe_cli_example(example, default_target_name=default_target_name, alias_target_names=alias_target_names, resolve_target_names=resolve_target_names, single_choice_description=single_choice_description)}"
            for example in examples
        )

    help_text = item_help
    if alias_target_names:
        help_text = f"{help_text} Aliases: {_format_choice_mapping(alias_target_names)}."

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


def _emit_summary_line(summary_label: str, message: str, *, stream: TextIO) -> None:
    print(f"[{summary_label}] {message}", file=stream)
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


def run_smoke_targets(
    targets: Sequence[SmokeScriptTarget],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    python_executable: str = sys.executable,
    failure_predicate: SmokeFailurePredicate = is_failed_smoke_check_line,
    summary_label: str | None = None,
) -> int:
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
            if summary_label is not None:
                elapsed = perf_counter() - started_at
                _emit_summary_line(
                    summary_label,
                    f"summary: {passed_count}/{total_count} targets passed before failure in {elapsed:.2f}s",
                    stream=stderr,
                )
            return exit_code
        passed_count += 1

    if summary_label is not None:
        elapsed = perf_counter() - started_at
        _emit_summary_line(
            summary_label,
            f"summary: {passed_count}/{total_count} targets passed in {elapsed:.2f}s",
            stream=stdout,
        )
    return 0
