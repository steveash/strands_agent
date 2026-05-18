from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import TextIO


def emit_smoke_check(name: str, ok: bool, *, stdout: TextIO = sys.stdout) -> bool:
    print(f"{name}= {ok}", file=stdout)
    stdout.flush()
    return ok


def emit_smoke_checks(
    checks: Iterable[tuple[str, bool]],
    *,
    stdout: TextIO = sys.stdout,
) -> int:
    all_ok = True
    for name, ok in checks:
        all_ok = emit_smoke_check(name, ok, stdout=stdout) and all_ok
    return 0 if all_ok else 1
