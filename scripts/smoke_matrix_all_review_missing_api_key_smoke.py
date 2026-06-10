from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
    build_review_artifact_failure_results,
    build_review_artifact_matrix_summary_assertion_results,
    build_smoke_matrix_docs_review_observer_spec,
    collect_smoke_matrix_docs_review_failure_output,
    emit_smoke_results,
    load_script_module,
    observe_script_module_main_via_driver_review_artifact_output,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"


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
        failure_output = collect_smoke_matrix_docs_review_failure_output(
            stderr_lines,
            review_output=review_output,
            **SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS.collect_kwargs(),
        )

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stderr_failed_line", failure_output.failed_line),
            *build_review_artifact_failure_results(
                review_output,
                review_spec,
                **review_spec.failure_result_kwargs(),
            ),
            ("stderr_missing_api_key_hint_line", failure_output.missing_api_key_hint_line),
            ("stderr_bundle_rerun_hint_line", failure_output.bundle_rerun_hint_line),
            ("stderr_docs_hint_line", failure_output.docs_review_only_hint_line),
            ("stderr_summary_line", failure_output.failure_summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", failure_output.present("failed")),
            ("missing_api_key_hint_line_present", failure_output.present("missing_api_key_hint")),
            ("bundle_rerun_hint_line_present", failure_output.present("bundle_rerun_hint")),
            ("docs_hint_line_present", failure_output.present("docs_review_only_hint")),
            ("summary_line_present", failure_output.present("failure_summary")),
            *build_review_artifact_matrix_summary_assertion_results(
                review_output,
                review_spec,
                **review_spec.result_naming.matrix_summary_assertion_result_name_bundle_kwargs(
                    "all_review_missing_api_key_failure",
                    result_prefix="",
                ),
                bundle_rerun_hint_line=failure_output.bundle_rerun_hint_line,
                bundle_rerun_hint_defaults=SMOKE_MATRIX_ALL_REVIEW_MISSING_API_KEY_FAILURE_DEFAULTS,
            ),
            (
                "metadata_before_missing_api_key_hint",
                failure_output.appears_before("metadata", "missing_api_key_hint"),
            ),
            (
                "artifacts_before_missing_api_key_hint",
                failure_output.appears_before("artifacts", "missing_api_key_hint"),
            ),
            (
                "matrix_summary_before_missing_api_key_hint",
                failure_output.appears_before("matrix_summary", "missing_api_key_hint"),
            ),
            (
                "bundle_rerun_hint_before_missing_api_key_hint",
                failure_output.appears_before("bundle_rerun_hint", "missing_api_key_hint"),
            ),
            (
                "bundle_rerun_hint_before_docs_hint",
                failure_output.appears_before("bundle_rerun_hint", "docs_review_only_hint"),
            ),
            (
                "missing_api_key_hint_before_docs_hint",
                failure_output.appears_before("missing_api_key_hint", "docs_review_only_hint"),
            ),
            (
                "docs_hint_before_failure_summary",
                failure_output.appears_before("docs_review_only_hint", "failure_summary"),
            ),
            (
                "metadata_before_failure_summary",
                failure_output.appears_before("metadata", "failure_summary"),
            ),
            (
                "artifacts_before_failure_summary",
                failure_output.appears_before("artifacts", "failure_summary"),
            ),
            (
                "matrix_summary_before_failure_summary",
                failure_output.appears_before("matrix_summary", "failure_summary"),
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_all_review_missing_api_key_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
