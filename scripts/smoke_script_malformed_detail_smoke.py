from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    build_malformed_smoke_script_detail_results,
    emit_smoke_results,
    load_script_module,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_SCRIPT_PATH = SCRIPT_DIR / "standalone_docs_rerun_hint_smoke.py"


def run_smoke_script_malformed_detail_smoke() -> list[tuple[str, object]]:
    source_module = load_script_module(
        SOURCE_SCRIPT_PATH,
        "scripts.smoke_script_malformed_detail_source",
    )
    source_results = source_module.run_standalone_docs_rerun_hint_smoke()
    return build_malformed_smoke_script_detail_results(
        source_results,
        source_case=STANDALONE_DOCS_RERUN_HINT_SCRIPT_CONTRACT,
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_script_malformed_detail_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
