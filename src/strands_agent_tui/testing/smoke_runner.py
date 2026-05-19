from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
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


@dataclass(frozen=True)
class SmokeTargetSelector:
    targets: Mapping[str, SmokeScriptTarget]
    default_target_name: str
    alias_target_names: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_target_names = set(self.targets)
        if self.default_target_name not in valid_target_names and self.default_target_name not in self.alias_target_names:
            raise ValueError(f"unknown default smoke target {self.default_target_name!r}")
        for alias_name, target_names in self.alias_target_names.items():
            unknown_target_names = [target_name for target_name in target_names if target_name not in valid_target_names]
            if unknown_target_names:
                raise ValueError(
                    f"alias {alias_name!r} references unknown smoke targets: {', '.join(unknown_target_names)}"
                )

    @property
    def choices(self) -> tuple[str, ...]:
        return (*self.targets.keys(), *self.alias_target_names.keys())

    def resolve_target_names(self, requested_target_name: str | None = None) -> list[str]:
        target_name = self.default_target_name if requested_target_name is None else requested_target_name
        if target_name in self.alias_target_names:
            return list(self.alias_target_names[target_name])
        if target_name not in self.targets:
            raise ValueError(f"unknown smoke target {target_name!r}")
        return [target_name]

    def resolve_targets(self, requested_target_name: str | None = None) -> list[SmokeScriptTarget]:
        return [self.targets[target_name] for target_name in self.resolve_target_names(requested_target_name)]


SmokeFailurePredicate = Callable[[str], bool]


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
        print(line, end="", file=stdout)
        stdout.flush()
        if failure_predicate(line):
            failed_line = line.rstrip("\n")
            process.terminate()
            break

    return_code = process.wait()
    if failed_line is not None:
        print(f"{target.name} smoke failed fast: {failed_line}", file=stderr)
        return 1
    if return_code != 0:
        print(f"{target.name} smoke exited with status {return_code}", file=stderr)
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
