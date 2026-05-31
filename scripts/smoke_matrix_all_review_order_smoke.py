from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    emit_smoke_results,
    find_prefixed_line_index,
    load_script_module,
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
    resolve_checkout_path,
    run_script_module_main_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "
LIVE_HINT_PREFIX = "[smoke-matrix] hint: `smoke_matrix.py all` and `smoke_matrix.py all-review` swap in `standalone_smoke.py all`;"
DOCS_FOCUSED_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-focused`;"
)
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 0/4 bundles passed before failure in "
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


def run_smoke_matrix_all_review_order_smoke() -> list[tuple[str, object]]:
    smoke_matrix_module = load_script_module(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_all_review_order_smoke_target",
    )
    smoke_run = run_script_module_main_in_temp_checkout(
        script_path=SMOKE_MATRIX_SCRIPT_PATH,
        module_name="scripts.smoke_matrix_all_review_order_smoke_target",
        argv=["all-review"],
        temp_prefix="smoke-matrix-all-review-order-",
        unset_env_names=("STRANDS_AGENT_RUNTIME", "OPENAI_API_KEY", "STRANDS_AGENT_OPENAI_MODEL"),
    )
    try:
        checkout_root = smoke_run.checkout_root
        stderr_lines = smoke_run.stderr_lines
        metadata_index = find_prefixed_line_index(stderr_lines, REVIEW_METADATA_PREFIX)
        artifacts_index = find_prefixed_line_index(stderr_lines, REVIEW_ARTIFACTS_PREFIX)
        matrix_summary_index = find_prefixed_line_index(stderr_lines, REVIEW_MATRIX_SUMMARY_PREFIX)
        hint_index = find_prefixed_line_index(stderr_lines, LIVE_HINT_PREFIX)
        docs_hint_index = find_prefixed_line_index(stderr_lines, DOCS_FOCUSED_HINT_PREFIX)
        summary_index = find_prefixed_line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)
        failed_line = next(
            (line for line in stderr_lines if line == "standalone smoke failed fast: live_runtime_requested= False"),
            "",
        )
        display_failed_line = failed_line.replace("= False", "=False")
        metadata_line = stderr_lines[metadata_index] if metadata_index is not None else ""
        artifacts_line = stderr_lines[artifacts_index] if artifacts_index is not None else ""
        matrix_summary_line = stderr_lines[matrix_summary_index] if matrix_summary_index is not None else ""
        hint_line = stderr_lines[hint_index] if hint_index is not None else ""
        docs_hint_line = stderr_lines[docs_hint_index] if docs_hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""
        metadata_payload = json.loads(metadata_line.removeprefix(REVIEW_METADATA_PREFIX)) if metadata_line else {}
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
            ("stderr_failed_line", display_failed_line),
            ("stderr_metadata_line", metadata_line),
            ("stderr_artifacts_line", artifacts_line),
            ("stderr_matrix_summary_line", matrix_summary_line),
            ("stderr_hint_line", hint_line),
            ("stderr_docs_hint_line", docs_hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", bool(failed_line)),
            ("metadata_line_present", bool(metadata_line)),
            ("artifacts_line_present", bool(artifacts_line)),
            ("matrix_summary_line_present", bool(matrix_summary_line)),
            ("hint_line_present", bool(hint_line)),
            ("docs_hint_line_present", bool(docs_hint_line)),
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
                line_matrix_summary_path is not None and line_matrix_summary_path.exists(),
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
                "matrix_summary_line_matches_metadata_path",
                line_matrix_summary_path == metadata_matrix_summary_path,
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
                "live_hint_before_docs_hint",
                hint_index is not None and docs_hint_index is not None and hint_index < docs_hint_index,
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
                matrix_summary_index is not None and summary_index is not None and matrix_summary_index < summary_index,
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_all_review_order_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
