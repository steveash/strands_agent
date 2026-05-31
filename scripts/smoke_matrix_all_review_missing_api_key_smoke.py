from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    emit_smoke_results,
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
    resolve_checkout_path,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "
MISSING_API_KEY_HINT_PREFIX = (
    "[smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but "
    "`OPENAI_API_KEY` was missing;"
)
DOCS_FOCUSED_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-focused`;"
)
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 0/4 bundles passed before failure in "
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


def _line_index(lines: list[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


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
spec = spec_from_file_location('scripts.smoke_matrix_all_review_missing_api_key_target', script_path)
assert spec is not None and spec.loader is not None
module = module_from_spec(spec)
spec.loader.exec_module(module)
os.environ['STRANDS_AGENT_RUNTIME'] = 'live'
for name in ('OPENAI_API_KEY', 'STRANDS_AGENT_OPENAI_MODEL'):
    os.environ.pop(name, None)

def fake_run_smoke_target(target, **kwargs):
    observer = kwargs.get('output_line_observer')
    stderr = kwargs['stderr']
    if target.name == module.LIVE_INCLUSIVE_STANDALONE_TARGET_NAME:
        if observer is not None:
            observer('RuntimeError: OPENAI_API_KEY is required for live runtime mode\\n')
        print('standalone smoke exited with status 1', file=stderr)
        return 1
    return 0

module.run_smoke_target = fake_run_smoke_target
raise SystemExit(module.main(['all-review']))
""".lstrip()


def run_smoke_matrix_all_review_missing_api_key_smoke() -> list[tuple[str, object]]:
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-all-review-missing-api-key-") as temp_dir:
        checkout_root = Path(temp_dir)
        driver_path = checkout_root / "run_smoke_matrix_all_review_missing_api_key.py"
        driver_path.write_text(_subprocess_driver_source(), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(driver_path)],
            cwd=checkout_root,
            capture_output=True,
            text=True,
            check=False,
        )

        stderr_lines = result.stderr.splitlines()
        metadata_index = _line_index(stderr_lines, REVIEW_METADATA_PREFIX)
        artifacts_index = _line_index(stderr_lines, REVIEW_ARTIFACTS_PREFIX)
        matrix_summary_index = _line_index(stderr_lines, REVIEW_MATRIX_SUMMARY_PREFIX)
        missing_api_key_hint_index = _line_index(stderr_lines, MISSING_API_KEY_HINT_PREFIX)
        docs_hint_index = _line_index(stderr_lines, DOCS_FOCUSED_HINT_PREFIX)
        summary_index = _line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)

        failed_line = next(
            (line for line in stderr_lines if line == "standalone smoke exited with status 1"),
            "",
        )
        metadata_line = stderr_lines[metadata_index] if metadata_index is not None else ""
        artifacts_line = stderr_lines[artifacts_index] if artifacts_index is not None else ""
        matrix_summary_line = stderr_lines[matrix_summary_index] if matrix_summary_index is not None else ""
        missing_api_key_hint_line = (
            stderr_lines[missing_api_key_hint_index] if missing_api_key_hint_index is not None else ""
        )
        docs_hint_line = stderr_lines[docs_hint_index] if docs_hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""

        metadata_payload = (
            json.loads(metadata_line.removeprefix(REVIEW_METADATA_PREFIX)) if metadata_line else {}
        )
        matrix_summary_path_text = metadata_payload.get("matrix_summary_path", "")
        metadata_matrix_summary_path = (
            resolve_checkout_path(matrix_summary_path_text, checkout_root=checkout_root)
            if matrix_summary_path_text
            else None
        )
        line_matrix_summary_path = output_path_from_prefixed_lines(
            stderr_lines,
            prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
            checkout_root=checkout_root,
        )
        matrix_summary_payload, _matrix_summary_paths = load_review_matrix_summary(
            line_matrix_summary_path,
            checkout_root=checkout_root,
        )

        return [
            ("checkout_root", str(checkout_root)),
            ("stderr_failed_line", failed_line),
            ("stderr_metadata_line", metadata_line),
            ("stderr_artifacts_line", artifacts_line),
            ("stderr_matrix_summary_line", matrix_summary_line),
            ("stderr_missing_api_key_hint_line", missing_api_key_hint_line),
            ("stderr_docs_hint_line", docs_hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", result.returncode),
            ("exit_code_non_zero", result.returncode != 0),
            ("failed_line_present", bool(failed_line)),
            ("metadata_line_present", bool(metadata_line)),
            ("artifacts_line_present", bool(artifacts_line)),
            ("matrix_summary_line_present", bool(matrix_summary_line)),
            ("missing_api_key_hint_line_present", bool(missing_api_key_hint_line)),
            ("docs_hint_line_present", bool(docs_hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "metadata_targets_docs_review_all",
                metadata_payload.get("target_name") == "docs-review-all",
            ),
            (
                "metadata_artifact_root_matches_all_review",
                metadata_payload.get("artifact_root") == EXPECTED_ARTIFACT_ROOT,
            ),
            (
                "metadata_matrix_summary_matches_all_review",
                metadata_payload.get("matrix_summary_path") == EXPECTED_MATRIX_SUMMARY_PATH,
            ),
            (
                "matrix_summary_artifact_exists",
                line_matrix_summary_path is not None and line_matrix_summary_path.exists(),
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
                "matrix_summary_path_matches_metadata",
                matrix_summary_payload.get("matrix_summary_path") == metadata_payload.get("matrix_summary_path"),
            ),
            (
                "matrix_summary_line_matches_metadata_path",
                line_matrix_summary_path == metadata_matrix_summary_path,
            ),
            (
                "metadata_before_missing_api_key_hint",
                metadata_index is not None
                and missing_api_key_hint_index is not None
                and metadata_index < missing_api_key_hint_index,
            ),
            (
                "artifacts_before_missing_api_key_hint",
                artifacts_index is not None
                and missing_api_key_hint_index is not None
                and artifacts_index < missing_api_key_hint_index,
            ),
            (
                "matrix_summary_before_missing_api_key_hint",
                matrix_summary_index is not None
                and missing_api_key_hint_index is not None
                and matrix_summary_index < missing_api_key_hint_index,
            ),
            (
                "missing_api_key_hint_before_docs_hint",
                missing_api_key_hint_index is not None
                and docs_hint_index is not None
                and missing_api_key_hint_index < docs_hint_index,
            ),
            (
                "docs_hint_before_failure_summary",
                docs_hint_index is not None and summary_index is not None and docs_hint_index < summary_index,
            ),
            (
                "metadata_before_failure_summary",
                metadata_index is not None and summary_index is not None and metadata_index < summary_index,
            ),
            (
                "artifacts_before_failure_summary",
                artifacts_index is not None and summary_index is not None and artifacts_index < summary_index,
            ),
            (
                "matrix_summary_before_failure_summary",
                matrix_summary_index is not None
                and summary_index is not None
                and matrix_summary_index < summary_index,
            ),
        ]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_all_review_missing_api_key_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
