from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TextIO


def emit_smoke_target_run_stdout_lines(
    stdout_lines: Sequence[str],
    *,
    stdout: TextIO,
    output_line_observer: Callable[[str], None] | None = None,
    output_line_filter: Callable[[str], bool] | None = None,
) -> None:
    for line in stdout_lines:
        rendered_line = f"{line}\n"
        if output_line_observer is not None:
            output_line_observer(rendered_line)
        if output_line_filter is None or output_line_filter(rendered_line):
            print(line, file=stdout)
    stdout.flush()
