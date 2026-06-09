from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
    build_review_artifact_failure_results,
    build_review_artifact_matrix_summary_assertion_results,
    build_smoke_matrix_docs_review_observer_spec,
    collect_smoke_matrix_docs_review_failure_output,
    detail_safe_text,
    emit_smoke_results,
    load_script_module,
    observe_review_artifact_output_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"


def run_smoke_matrix_all_review_order_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    smoke_matrix_module = load_script_module(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_all_review_order_smoke_target",
    )
    review_spec = build_smoke_matrix_docs_review_observer_spec(
        smoke_matrix_module,
        requested_target_name="all-review",
        driver_stem="smoke_matrix_all_review_order",
    )
    smoke_run, review_output = observe_review_artifact_output_in_temp_checkout(
        module=smoke_matrix_module,
        argv=[review_spec.requested_target_name],
        temp_prefix="smoke-matrix-all-review-order-",
        **review_spec.observer_kwargs(),
        unset_env_names=("STRANDS_AGENT_RUNTIME", "OPENAI_API_KEY", "STRANDS_AGENT_OPENAI_MODEL"),
        output_stream=output_stream,
    )
    try:
        stderr_lines = smoke_run.stderr_lines
        failure_output = collect_smoke_matrix_docs_review_failure_output(
            stderr_lines,
            review_output=review_output,
            **SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS.collect_kwargs(),
        )

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stderr_failed_line", detail_safe_text(failure_output.failed_line)),
            *build_review_artifact_failure_results(
                review_output,
                review_spec,
                **review_spec.failure_result_kwargs(),
            ),
            ("stderr_hint_line", failure_output.live_runtime_hint_line),
            ("stderr_docs_hint_line", failure_output.docs_review_only_hint_line),
            ("stderr_summary_line", failure_output.failure_summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", failure_output.present("failed")),
            ("hint_line_present", failure_output.present("live_runtime_hint")),
            ("docs_hint_line_present", failure_output.present("docs_review_only_hint")),
            ("summary_line_present", failure_output.present("failure_summary")),
            *build_review_artifact_matrix_summary_assertion_results(
                review_output,
                review_spec,
                **review_spec.result_naming.matrix_summary_assertion_result_name_bundle_kwargs(
                    "all_review_order_failure",
                    result_prefix="",
                ),
            ),
            (
                "metadata_before_hint",
                failure_output.appears_before("metadata", "live_runtime_hint"),
            ),
            (
                "artifacts_before_hint",
                failure_output.appears_before("artifacts", "live_runtime_hint"),
            ),
            (
                "matrix_summary_before_hint",
                failure_output.appears_before("matrix_summary", "live_runtime_hint"),
            ),
            (
                "live_hint_before_docs_hint",
                failure_output.appears_before("live_runtime_hint", "docs_review_only_hint"),
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
    return emit_smoke_results(run_smoke_matrix_all_review_order_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
