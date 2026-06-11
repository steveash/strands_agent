from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS,
    SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_RESULT_PRESET,
    collect_smoke_matrix_docs_review_failure_output,
    emit_smoke_results,
    load_smoke_matrix_docs_review_module_and_spec,
    observe_script_module_main_via_driver_review_artifact_output,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"


def _docs_review_all_spec():
    return load_smoke_matrix_docs_review_module_and_spec(
        SMOKE_MATRIX_SCRIPT_PATH,
        "scripts.smoke_matrix_docs_review_hint_spec_target",
        requested_target_name="all-review",
        driver_stem="smoke_matrix_docs_review_hint",
    )


def run_smoke_matrix_docs_review_hint_smoke(*, output_stream: str = "stderr") -> list[tuple[str, object]]:
    _smoke_matrix_module, review_spec = _docs_review_all_spec()
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
        stderr_lines = smoke_run.stderr_lines
        failure_output = collect_smoke_matrix_docs_review_failure_output(
            stderr_lines,
            review_output=review_output,
            **SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS.collect_kwargs(),
        )

        return SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_RESULT_PRESET.build_results(
            smoke_run,
            failure_output,
            review_spec,
            failure_defaults=SMOKE_MATRIX_DOCS_REVIEW_HINT_FAILURE_DEFAULTS,
        )
    finally:
        smoke_run.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_docs_review_hint_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
