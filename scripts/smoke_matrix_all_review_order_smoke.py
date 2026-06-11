from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
    build_smoke_matrix_docs_review_failure_results,
    collect_smoke_matrix_docs_review_failure_output,
    emit_smoke_results,
    load_smoke_matrix_docs_review_module_and_spec,
    observe_review_artifact_output_in_temp_checkout,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"


def run_smoke_matrix_all_review_order_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    smoke_matrix_module, review_spec = load_smoke_matrix_docs_review_module_and_spec(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_all_review_order_smoke_target",
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

        return build_smoke_matrix_docs_review_failure_results(
            smoke_run,
            failure_output,
            review_spec,
            failure_defaults=SMOKE_MATRIX_ALL_REVIEW_ORDER_FAILURE_DEFAULTS,
            matrix_summary_bundle="all_review_order_failure",
            extra_line_result_names=(
                ("stderr_hint_line", "live_runtime_hint"),
                ("stderr_docs_hint_line", "docs_review_only_hint"),
            ),
            extra_present_result_names=(
                ("hint_line_present", "live_runtime_hint"),
                ("docs_hint_line_present", "docs_review_only_hint"),
            ),
            ordering_result_names=(
                ("metadata_before_hint", "metadata", "live_runtime_hint"),
                ("artifacts_before_hint", "artifacts", "live_runtime_hint"),
                ("matrix_summary_before_hint", "matrix_summary", "live_runtime_hint"),
                ("live_hint_before_docs_hint", "live_runtime_hint", "docs_review_only_hint"),
                (
                    "docs_hint_before_failure_summary",
                    "docs_review_only_hint",
                    "failure_summary",
                ),
                ("metadata_before_failure_summary", "metadata", "failure_summary"),
                ("artifacts_before_failure_summary", "artifacts", "failure_summary"),
                (
                    "matrix_summary_before_failure_summary",
                    "matrix_summary",
                    "failure_summary",
                ),
            ),
            failed_line_detail_safe=True,
        )
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_all_review_order_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
