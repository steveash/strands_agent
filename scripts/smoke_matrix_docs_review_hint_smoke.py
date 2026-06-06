from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_review_artifact_failure_results,
    build_smoke_matrix_docs_review_observer_spec,
    collect_smoke_matrix_docs_review_failure_output,
    detail_safe_text,
    emit_smoke_results,
    load_script_module,
    observe_script_module_main_via_driver_review_artifact_output,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
DOCS_REVIEW_RUNNING_PREFIX = "[smoke-matrix] running docs-review"
FAILED_LINE_PREFIX = "docs-review smoke failed fast: "
DOCS_REVIEW_ONLY_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-review-only`;"
)
BUNDLE_RERUN_HINT_PREFIX = "[smoke-matrix] review bundle rerun hint: "
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 3/4 bundles passed before failure in "


def _docs_review_all_spec():
    smoke_matrix_module = load_script_module(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_docs_review_hint_spec_target",
    )
    return build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="all-review",
        driver_stem="smoke_matrix_docs_review_hint",
    )


def run_smoke_matrix_docs_review_hint_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    review_spec = _docs_review_all_spec()
    smoke_run, review_output = observe_script_module_main_via_driver_review_artifact_output(
        repo_root=REPO_ROOT,
        script_path=SMOKE_MATRIX_SCRIPT_PATH,
        module_name="scripts.smoke_matrix_docs_review_hint_target",
        argv=[review_spec.requested_target_name],
        temp_prefix="smoke-matrix-docs-review-hint-",
        driver_filename=review_spec.driver_filename,
        **review_spec.observer_kwargs(),
        env_unsets=("STRANDS_AGENT_RUNTIME", "OPENAI_API_KEY", "STRANDS_AGENT_OPENAI_MODEL"),
        hook_source="""
        def fake_run_smoke_target(target, **kwargs):
            stderr = kwargs['stderr']
            if target.name == module.DOCS_REVIEW_ALL_TARGET_NAME:
                print(f"{target.display_label} smoke failed fast: render_manifest_payload= False", file=stderr)
                return 1
            return 0

        module.run_smoke_target = fake_run_smoke_target
        """,
        output_stream=output_stream,
    )
    try:
        stdout_lines = smoke_run.stdout_lines
        stderr_lines = smoke_run.stderr_lines
        stdout_last_line = stdout_lines[-1] if stdout_lines else ""
        failure_output = collect_smoke_matrix_docs_review_failure_output(
            stderr_lines,
            review_output=review_output,
            failed_line_prefix=FAILED_LINE_PREFIX,
            bundle_rerun_hint_prefix=BUNDLE_RERUN_HINT_PREFIX,
            docs_review_only_hint_prefix=DOCS_REVIEW_ONLY_HINT_PREFIX,
            failure_summary_prefix=FAILURE_SUMMARY_PREFIX,
        )

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stdout_last_line", stdout_last_line),
            ("stderr_failed_line", detail_safe_text(failure_output.failed_line)),
            *build_review_artifact_failure_results(
                review_output,
                review_spec,
                **review_spec.failure_result_kwargs(),
            ),
            ("stderr_bundle_rerun_hint_line", failure_output.bundle_rerun_hint_line),
            ("stderr_hint_line", failure_output.docs_review_only_hint_line),
            ("stderr_summary_line", failure_output.failure_summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", failure_output.present("failed")),
            ("bundle_rerun_hint_line_present", failure_output.present("bundle_rerun_hint")),
            ("hint_line_present", failure_output.present("docs_review_only_hint")),
            ("summary_line_present", failure_output.present("failure_summary")),
            (
                "metadata_matrix_summary_matches_all_review",
                review_output.metadata_matrix_summary_matches(review_spec.expected_matrix_summary_path),
            ),
            (
                "matrix_summary_path_matches_all_review",
                review_output.matrix_summary_path_matches(review_spec.expected_matrix_summary_path),
            ),
            (
                "bundle_rerun_hint_line_matches_matrix_summary_hint",
                failure_output.bundle_rerun_hint_line
                == f"{BUNDLE_RERUN_HINT_PREFIX}{review_spec.expected_bundle_index_rerun_hint}",
            ),
            (
                "bundle_rerun_hint_after_matrix_summary",
                failure_output.appears_before("matrix_summary", "bundle_rerun_hint"),
            ),
            (
                "hint_after_matrix_summary",
                failure_output.appears_before("matrix_summary", "docs_review_only_hint"),
            ),
            (
                "bundle_rerun_hint_before_docs_hint",
                failure_output.appears_before("bundle_rerun_hint", "docs_review_only_hint"),
            ),
            (
                "hint_before_failure_summary",
                failure_output.appears_before("docs_review_only_hint", "failure_summary"),
            ),
            (
                "stdout_docs_review_started",
                stdout_last_line.startswith(DOCS_REVIEW_RUNNING_PREFIX),
            ),
        ]
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_docs_review_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
