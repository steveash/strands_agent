from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from typing import Iterator

from strands_agent_tui.testing import emit_smoke_results

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "
LIVE_HINT_PREFIX = "[smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`;"
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 0/4 bundles passed before failure in "
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


@contextmanager
def _unset_env(*variable_names: str) -> Iterator[None]:
    previous_values = {name: os.environ.get(name) for name in variable_names}
    for name in variable_names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _load_smoke_matrix_module():
    spec = spec_from_file_location("scripts.smoke_matrix_all_review_order_smoke_target", SMOKE_MATRIX_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _line_index(lines: list[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def _resolve_checkout_path(path_text: str, *, checkout_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return checkout_root / path


def run_smoke_matrix_all_review_order_smoke() -> list[tuple[str, object]]:
    smoke_matrix_module = _load_smoke_matrix_module()
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-all-review-order-") as temp_dir:
        checkout_root = Path(temp_dir)
        stdout = StringIO()
        stderr = StringIO()
        with _pushd(checkout_root), _unset_env("STRANDS_AGENT_RUNTIME", "OPENAI_API_KEY", "STRANDS_AGENT_OPENAI_MODEL"):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = smoke_matrix_module.main(["all-review"])

        stderr_lines = stderr.getvalue().splitlines()
        metadata_index = _line_index(stderr_lines, REVIEW_METADATA_PREFIX)
        artifacts_index = _line_index(stderr_lines, REVIEW_ARTIFACTS_PREFIX)
        matrix_summary_index = _line_index(stderr_lines, REVIEW_MATRIX_SUMMARY_PREFIX)
        hint_index = _line_index(stderr_lines, LIVE_HINT_PREFIX)
        summary_index = _line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)
        failed_line = next(
            (line for line in stderr_lines if line == "standalone smoke failed fast: live_runtime_requested= False"),
            "",
        )
        display_failed_line = failed_line.replace("= False", "=False")
        metadata_line = stderr_lines[metadata_index] if metadata_index is not None else ""
        artifacts_line = stderr_lines[artifacts_index] if artifacts_index is not None else ""
        matrix_summary_line = stderr_lines[matrix_summary_index] if matrix_summary_index is not None else ""
        hint_line = stderr_lines[hint_index] if hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""
        metadata_payload = (
            json.loads(metadata_line.removeprefix(REVIEW_METADATA_PREFIX)) if metadata_line else {}
        )
        matrix_summary_path_text = metadata_payload.get("matrix_summary_path", "")
        matrix_summary_path = (
            _resolve_checkout_path(matrix_summary_path_text, checkout_root=checkout_root)
            if matrix_summary_path_text
            else None
        )
        matrix_summary_payload = (
            json.loads(matrix_summary_path.read_text(encoding="utf-8"))
            if matrix_summary_path is not None and matrix_summary_path.exists()
            else {}
        )

        return [
            ("checkout_root", str(checkout_root)),
            ("stderr_failed_line", display_failed_line),
            ("stderr_metadata_line", metadata_line),
            ("stderr_artifacts_line", artifacts_line),
            ("stderr_matrix_summary_line", matrix_summary_line),
            ("stderr_hint_line", hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", exit_code),
            ("exit_code_non_zero", exit_code != 0),
            ("failed_line_present", bool(failed_line)),
            ("metadata_line_present", bool(metadata_line)),
            ("artifacts_line_present", bool(artifacts_line)),
            ("matrix_summary_line_present", bool(matrix_summary_line)),
            ("hint_line_present", bool(hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "metadata_targets_docs_review_all",
                metadata_payload.get("target_name") == smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME,
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
                matrix_summary_path is not None and matrix_summary_path.exists(),
            ),
            (
                "matrix_summary_targets_docs_review_all",
                matrix_summary_payload.get("target_name") == smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME,
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
                "metadata_before_hint",
                metadata_index is not None and hint_index is not None and metadata_index < hint_index,
            ),
            (
                "artifacts_before_hint",
                artifacts_index is not None and hint_index is not None and artifacts_index < hint_index,
            ),
            (
                "matrix_summary_before_hint",
                matrix_summary_index is not None and hint_index is not None and matrix_summary_index < hint_index,
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
    return emit_smoke_results(run_smoke_matrix_all_review_order_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
