from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_matrix_docs_review_observer_spec,
    emit_smoke_results,
    find_prefixed_line_index,
    load_script_module,
    observe_script_module_main_via_driver_review_artifact_output,
    smoke_cli_docs_parity_rerun_hint,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
MISSING_API_KEY_HINT_PREFIX = (
    "[smoke-matrix] hint: `smoke_matrix.py all`/`all-review` reached the live runtime, but "
    "`OPENAI_API_KEY` was missing;"
)
DOCS_REVIEW_ONLY_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-review-only`;"
)
BUNDLE_RERUN_HINT_PREFIX = "[smoke-matrix] review bundle rerun hint: "
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 0/4 bundles passed before failure in "


def _docs_review_all_spec():
    smoke_matrix_module = load_script_module(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_all_review_missing_api_key_spec_target",
    )
    return build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="all-review",
        driver_stem="smoke_matrix_all_review_missing_api_key",
    )


def run_smoke_matrix_all_review_missing_api_key_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    review_spec = _docs_review_all_spec()
    smoke_run, review_output = observe_script_module_main_via_driver_review_artifact_output(
        repo_root=REPO_ROOT,
        script_path=SMOKE_MATRIX_SCRIPT_PATH,
        module_name="scripts.smoke_matrix_all_review_missing_api_key_target",
        argv=[review_spec.requested_target_name],
        temp_prefix="smoke-matrix-all-review-missing-api-key-",
        driver_filename=review_spec.driver_filename,
        **review_spec.observer_kwargs(),
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
        output_stream=output_stream,
    )
    try:
        stderr_lines = smoke_run.stderr_lines
        missing_api_key_hint_index = find_prefixed_line_index(stderr_lines, MISSING_API_KEY_HINT_PREFIX)
        bundle_rerun_hint_index = find_prefixed_line_index(stderr_lines, BUNDLE_RERUN_HINT_PREFIX)
        docs_hint_index = find_prefixed_line_index(stderr_lines, DOCS_REVIEW_ONLY_HINT_PREFIX)
        summary_index = find_prefixed_line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)

        failed_line = next(
            (line for line in stderr_lines if line == "standalone smoke exited with status 1"),
            "",
        )
        missing_api_key_hint_line = (
            stderr_lines[missing_api_key_hint_index] if missing_api_key_hint_index is not None else ""
        )
        bundle_rerun_hint_line = (
            stderr_lines[bundle_rerun_hint_index] if bundle_rerun_hint_index is not None else ""
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
            ("stderr_bundle_rerun_hint_line", bundle_rerun_hint_line),
            ("stderr_docs_hint_line", docs_hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", bool(failed_line)),
            ("metadata_line_present", review_output.metadata_line_present),
            ("artifacts_line_present", review_output.artifacts_line_present),
            ("matrix_summary_line_present", review_output.matrix_summary_line_present),
            ("missing_api_key_hint_line_present", bool(missing_api_key_hint_line)),
            ("bundle_rerun_hint_line_present", bool(bundle_rerun_hint_line)),
            ("docs_hint_line_present", bool(docs_hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "metadata_targets_docs_review_all",
                review_output.metadata_targets(review_spec.expected_target_name),
            ),
            (
                "metadata_artifact_root_matches_all_review",
                review_output.metadata_artifact_root_matches(review_spec.expected_artifact_root),
            ),
            (
                "metadata_matrix_summary_matches_all_review",
                review_output.metadata_matrix_summary_matches(review_spec.expected_matrix_summary_path),
            ),
            (
                "metadata_bundle_index_rerun_hint_matches",
                review_output.metadata_bundle_index_rerun_hint_matches(smoke_cli_docs_parity_rerun_hint()),
            ),
            (
                "metadata_expected_artifact_paths_match",
                review_spec.metadata_artifact_paths_match(review_output),
            ),
            (
                "metadata_resolved_paths_match_expected",
                review_spec.metadata_resolved_paths_match(review_output),
            ),
            (
                "matrix_summary_artifact_exists",
                review_output.matrix_summary_artifact_exists,
            ),
            (
                "matrix_summary_targets_docs_review_all",
                review_output.matrix_summary_targets(review_spec.expected_target_name),
            ),
            (
                "matrix_summary_artifact_root_matches_all_review",
                review_output.matrix_summary_artifact_root_matches(review_spec.expected_artifact_root),
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
                "matrix_summary_expected_artifact_paths_match",
                review_spec.matrix_summary_artifact_paths_match(review_output),
            ),
            (
                "matrix_summary_resolved_paths_match_expected",
                review_spec.matrix_summary_resolved_paths_match(review_output),
            ),
            (
                "bundle_rerun_hint_line_matches_matrix_summary_hint",
                bundle_rerun_hint_line
                == f"{BUNDLE_RERUN_HINT_PREFIX}{review_spec.expected_bundle_index_rerun_hint}",
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
                "bundle_rerun_hint_before_missing_api_key_hint",
                bundle_rerun_hint_index is not None
                and missing_api_key_hint_index is not None
                and bundle_rerun_hint_index < missing_api_key_hint_index,
            ),
            (
                "bundle_rerun_hint_before_docs_hint",
                bundle_rerun_hint_index is not None
                and docs_hint_index is not None
                and bundle_rerun_hint_index < docs_hint_index,
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
