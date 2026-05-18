from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .smoke_assertions import is_failed_smoke_check_line


@dataclass(frozen=True)
class SmokeScriptTarget:
    name: str
    script_path: Path
    args: tuple[str, ...] = ()


SmokeFailurePredicate = Callable[[str], bool]


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
) -> int:
    for target in targets:
        exit_code = run_smoke_target(
            target,
            stdout=stdout,
            stderr=stderr,
            python_executable=python_executable,
            failure_predicate=failure_predicate,
        )
        if exit_code != 0:
            return exit_code
    return 0
