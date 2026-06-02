from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_script_driver_source,
    emit_smoke_results,
    find_prefixed_line_index,
    observe_review_artifact_output_in_temp_checkout,
    smoke_cli_docs_parity_rerun_hint,
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
DOCS_REVIEW_ONLY_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-review-only`;"
)
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 0/4 bundles passed before failure in "
EXPECTED_TARGET_NAME = "docs-review-all"
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


def _subprocess_driver_source() -> str:
    return build_script_driver_source(
        repo_root=REPO_ROOT,
        script_path=SMOKE_MATRIX_SCRIPT_PATH,
        module_name="scripts.smoke_matrix_all_review_missing_api_key_target",
        argv=["all-review"],
        env_assignments={"STRANDS_AGENT_RUNTIME": "live"},
        env_unsets=("OPENAI_API_KEY", "STRANDS_AGENT_OPENAI_MODEL"),
        hook_source="""
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
        """,
    )


def run_smoke_matrix_all_review_missing_api_key_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    smoke_run, review_output = observe_review_artifact_output_in_temp_checkout(
        driver_source=_subprocess_driver_source(),
        temp_prefix="smoke-matrix-all-review-missing-api-key-",
        driver_filename="run_smoke_matrix_all_review_missing_api_key.py",
        metadata_prefix=REVIEW_METADATA_PREFIX,
        artifacts_prefix=REVIEW_ARTIFACTS_PREFIX,
        matrix_summary_prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
        output_stream=output_stream,
    )
    try:
        stderr_lines = smoke_run.stderr_lines
        missing_api_key_hint_index = find_prefixed_line_index(stderr_lines, MISSING_API_KEY_HINT_PREFIX)
        docs_hint_index = find_prefixed_line_index(stderr_lines, DOCS_REVIEW_ONLY_HINT_PREFIX)
        summary_index = find_prefixed_line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)

        failed_line = next(
            (line for line in stderr_lines if line == "standalone smoke exited with status 1"),
            "",
        )
        missing_api_key_hint_line = (
            stderr_lines[missing_api_key_hint_index] if missing_api_key_hint_index is not None else ""
        )
        docs_hint_line = stderr_lines[docs_hint_index] if docs_hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stderr_failed_line", failed_line),
            ("stderr_metadata_line", review_output.metadata_line),
            ("stderr_artifacts_line", review_output.artifacts_line),
            ("stderr_matrix_summary_line", review_output.matrix_summary_line),
            ("stderr_missing_api_key_hint_line", missing_api_key_hint_line),
            ("stderr_docs_hint_line", docs_hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", bool(failed_line)),
            ("metadata_line_present", review_output.metadata_line_present),
            ("artifacts_line_present", review_output.artifacts_line_present),
            ("matrix_summary_line_present", review_output.matrix_summary_line_present),
            ("missing_api_key_hint_line_present", bool(missing_api_key_hint_line)),
            ("docs_hint_line_present", bool(docs_hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "metadata_targets_docs_review_all",
                review_output.metadata_targets(EXPECTED_TARGET_NAME),
            ),
            (
                "metadata_artifact_root_matches_all_review",
                review_output.metadata_artifact_root_matches(EXPECTED_ARTIFACT_ROOT),
            ),
            (
                "metadata_matrix_summary_matches_all_review",
                review_output.metadata_matrix_summary_matches(EXPECTED_MATRIX_SUMMARY_PATH),
            ),
            (
                "metadata_bundle_index_rerun_hint_matches",
                review_output.metadata_bundle_index_rerun_hint_matches(smoke_cli_docs_parity_rerun_hint()),
            ),
            (
                "matrix_summary_artifact_exists",
                review_output.matrix_summary_artifact_exists,
            ),
            (
                "matrix_summary_targets_docs_review_all",
                review_output.matrix_summary_targets(EXPECTED_TARGET_NAME),
            ),
            (
                "matrix_summary_artifact_root_matches_all_review",
                review_output.matrix_summary_artifact_root_matches(EXPECTED_ARTIFACT_ROOT),
            ),
            (
                "matrix_summary_path_matches_metadata",
                review_output.matrix_summary_path_matches_metadata(),
            ),
            (
                "matrix_summary_bundle_index_rerun_hint_matches",
                review_output.matrix_summary_bundle_index_rerun_hint_matches(
                    smoke_cli_docs_parity_rerun_hint()
                ),
            ),
            (
                "matrix_summary_line_matches_metadata_path",
                review_output.matrix_summary_line_matches_metadata_path(),
            ),
            (
                "metadata_before_missing_api_key_hint",
                review_output.metadata_index is not None
                and missing_api_key_hint_index is not None
                and review_output.metadata_index < missing_api_key_hint_index,
            ),
            (
                "artifacts_before_missing_api_key_hint",
                review_output.artifacts_index is not None
                and missing_api_key_hint_index is not None
                and review_output.artifacts_index < missing_api_key_hint_index,
            ),
            (
                "matrix_summary_before_missing_api_key_hint",
                review_output.matrix_summary_index is not None
                and missing_api_key_hint_index is not None
                and review_output.matrix_summary_index < missing_api_key_hint_index,
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
                review_output.metadata_index is not None
                and summary_index is not None
                and review_output.metadata_index < summary_index,
            ),
            (
                "artifacts_before_failure_summary",
                review_output.artifacts_index is not None
                and summary_index is not None
                and review_output.artifacts_index < summary_index,
            ),
            (
                "matrix_summary_before_failure_summary",
                review_output.matrix_summary_index is not None
                and summary_index is not None
                and review_output.matrix_summary_index < summary_index,
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_all_review_missing_api_key_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
