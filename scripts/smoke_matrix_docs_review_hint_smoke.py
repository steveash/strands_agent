from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    emit_smoke_results,
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
DOCS_REVIEW_RUNNING_PREFIX = "[smoke-matrix] running docs-review"
FAILED_LINE_PREFIX = "docs-review smoke failed fast: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "
DOCS_FOCUSED_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-focused`;"
)
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 3/4 bundles passed before failure in "
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


def _line_index(lines: list[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def _detail_safe_text(line: str) -> str:
    return line.replace("= False", "=False")


def _subprocess_driver_source() -> str:
    return f"""
from __future__ import annotations

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

repo_root = Path({str(REPO_ROOT)!r})
sys.path.insert(0, str(repo_root / 'src'))
script_path = Path({str(SMOKE_MATRIX_SCRIPT_PATH)!r})
spec = spec_from_file_location('scripts.smoke_matrix_docs_review_hint_target', script_path)
assert spec is not None and spec.loader is not None
module = module_from_spec(spec)
spec.loader.exec_module(module)
for name in ('STRANDS_AGENT_RUNTIME', 'OPENAI_API_KEY', 'STRANDS_AGENT_OPENAI_MODEL'):
    os.environ.pop(name, None)

def fake_run_smoke_target(target, **kwargs):
    stderr = kwargs['stderr']
    if target.name == module.DOCS_REVIEW_ALL_TARGET_NAME:
        print(f"{{target.display_label}} smoke failed fast: render_manifest_payload= False", file=stderr)
        return 1
    return 0

module.run_smoke_target = fake_run_smoke_target
raise SystemExit(module.main(['all-review']))
""".lstrip()


def run_smoke_matrix_docs_review_hint_smoke() -> list[tuple[str, object]]:
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-docs-review-hint-") as temp_dir:
        checkout_root = Path(temp_dir)
        driver_path = checkout_root / "run_smoke_matrix_docs_review_hint.py"
        driver_path.write_text(_subprocess_driver_source(), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(driver_path)],
            cwd=checkout_root,
            capture_output=True,
            text=True,
            check=False,
        )

        stdout_lines = result.stdout.splitlines()
        stderr_lines = result.stderr.splitlines()
        stdout_last_line = stdout_lines[-1] if stdout_lines else ""
        failed_index = _line_index(stderr_lines, FAILED_LINE_PREFIX)
        matrix_summary_index = _line_index(stderr_lines, REVIEW_MATRIX_SUMMARY_PREFIX)
        hint_index = _line_index(stderr_lines, DOCS_FOCUSED_HINT_PREFIX)
        summary_index = _line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)
        failed_line = stderr_lines[failed_index] if failed_index is not None else ""
        matrix_summary_line = stderr_lines[matrix_summary_index] if matrix_summary_index is not None else ""
        hint_line = stderr_lines[hint_index] if hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""
        matrix_summary_path = output_path_from_prefixed_lines(
            stderr_lines,
            prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
            checkout_root=checkout_root,
        )
        matrix_summary_payload, _matrix_summary_paths = load_review_matrix_summary(
            matrix_summary_path,
            checkout_root=checkout_root,
        )

        return [
            ("checkout_root", str(checkout_root)),
            ("stdout_last_line", stdout_last_line),
            ("stderr_failed_line", _detail_safe_text(failed_line)),
            ("stderr_matrix_summary_line", matrix_summary_line),
            ("stderr_hint_line", hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", result.returncode),
            ("exit_code_non_zero", result.returncode != 0),
            ("failed_line_present", bool(failed_line)),
            ("matrix_summary_line_present", bool(matrix_summary_line)),
            ("hint_line_present", bool(hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "matrix_summary_artifact_exists",
                matrix_summary_path is not None and matrix_summary_path.exists(),
            ),
            (
                "matrix_summary_targets_docs_review_all",
                matrix_summary_payload.get("target_name") == "docs-review-all",
            ),
            (
                "matrix_summary_artifact_root_matches_all_review",
                matrix_summary_payload.get("artifact_root") == EXPECTED_ARTIFACT_ROOT,
            ),
            (
                "matrix_summary_path_matches_all_review",
                matrix_summary_payload.get("matrix_summary_path") == EXPECTED_MATRIX_SUMMARY_PATH,
            ),
            (
                "hint_after_matrix_summary",
                matrix_summary_index is not None and hint_index is not None and matrix_summary_index < hint_index,
            ),
            (
                "hint_before_failure_summary",
                hint_index is not None and summary_index is not None and hint_index < summary_index,
            ),
            (
                "stdout_docs_review_started",
                stdout_last_line.startswith(DOCS_REVIEW_RUNNING_PREFIX),
            ),
        ]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_docs_review_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
