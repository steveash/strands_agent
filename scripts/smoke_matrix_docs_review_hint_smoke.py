from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_script_driver_source,
    detail_safe_text,
    emit_smoke_results,
    find_prefixed_line_index,
    observe_subprocess_review_artifact_output,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
DOCS_REVIEW_RUNNING_PREFIX = "[smoke-matrix] running docs-review"
FAILED_LINE_PREFIX = "docs-review smoke failed fast: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "
DOCS_REVIEW_ONLY_HINT_PREFIX = (
    "[smoke-matrix] hint: docs-review drift is easiest to isolate with "
    "`standalone_smoke.py docs-review-only`;"
)
FAILURE_SUMMARY_PREFIX = "[smoke-matrix] summary: 3/4 bundles passed before failure in "
EXPECTED_ARTIFACT_ROOT = "artifacts/smoke-cli-docs-artifacts/smoke-matrix-all-review"
EXPECTED_MATRIX_SUMMARY_PATH = f"{EXPECTED_ARTIFACT_ROOT}/matrix-summary.json"


def _subprocess_driver_source() -> str:
    return build_script_driver_source(
        repo_root=REPO_ROOT,
        script_path=SMOKE_MATRIX_SCRIPT_PATH,
        module_name="scripts.smoke_matrix_docs_review_hint_target",
        argv=["all-review"],
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
    )


def run_smoke_matrix_docs_review_hint_smoke() -> list[tuple[str, object]]:
    smoke_run, review_output = observe_subprocess_review_artifact_output(
        driver_source=_subprocess_driver_source(),
        temp_prefix="smoke-matrix-docs-review-hint-",
        driver_filename="run_smoke_matrix_docs_review_hint.py",
        matrix_summary_prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
        output_stream="stderr",
    )
    try:
        stdout_lines = smoke_run.stdout_lines
        stderr_lines = smoke_run.stderr_lines
        stdout_last_line = stdout_lines[-1] if stdout_lines else ""
        failed_index = find_prefixed_line_index(stderr_lines, FAILED_LINE_PREFIX)
        hint_index = find_prefixed_line_index(stderr_lines, DOCS_REVIEW_ONLY_HINT_PREFIX)
        summary_index = find_prefixed_line_index(stderr_lines, FAILURE_SUMMARY_PREFIX)
        failed_line = stderr_lines[failed_index] if failed_index is not None else ""
        hint_line = stderr_lines[hint_index] if hint_index is not None else ""
        summary_line = stderr_lines[summary_index] if summary_index is not None else ""

        return [
            ("checkout_root", str(smoke_run.checkout_root)),
            ("stdout_last_line", stdout_last_line),
            ("stderr_failed_line", detail_safe_text(failed_line)),
            ("stderr_matrix_summary_line", review_output.matrix_summary_line),
            ("stderr_hint_line", hint_line),
            ("stderr_summary_line", summary_line),
            ("exit_code", smoke_run.exit_code),
            ("exit_code_non_zero", smoke_run.exit_code != 0),
            ("failed_line_present", bool(failed_line)),
            ("matrix_summary_line_present", review_output.matrix_summary_line_present),
            ("hint_line_present", bool(hint_line)),
            ("summary_line_present", bool(summary_line)),
            (
                "matrix_summary_artifact_exists",
                review_output.matrix_summary_artifact_exists,
            ),
            (
                "matrix_summary_targets_docs_review_all",
                review_output.matrix_summary_targets("docs-review-all"),
            ),
            (
                "matrix_summary_artifact_root_matches_all_review",
                review_output.matrix_summary_artifact_root_matches(EXPECTED_ARTIFACT_ROOT),
            ),
            (
                "matrix_summary_path_matches_all_review",
                review_output.matrix_summary_path_matches(EXPECTED_MATRIX_SUMMARY_PATH),
            ),
            (
                "hint_after_matrix_summary",
                review_output.matrix_summary_index is not None
                and hint_index is not None
                and review_output.matrix_summary_index < hint_index,
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
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_docs_review_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
