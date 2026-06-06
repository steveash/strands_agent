from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from strands_agent_tui.testing import (
    SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX,
    SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX,
    SMOKE_MATRIX_REVIEW_METADATA_PREFIX,
    build_review_artifact_success_results,
    build_smoke_matrix_docs_review_observer_spec,
    emit_smoke_results,
    load_script_module,
    observe_loaded_review_artifact_output,
    resolve_checkout_path,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
SUCCESS_SUMMARY_PREFIX = "[smoke-matrix] summary: 4/4 bundles passed in "
RERUN_HINT_PREFIX = "[smoke-matrix] review bundle rerun hint: "


@contextmanager
def _patched_run_smoke_target(smoke_matrix_module, checkout_root: Path) -> Iterator[None]:
    original = smoke_matrix_module.run_smoke_target

    def _emit_output(line: str, *, stdout, output_line_filter, output_line_observer) -> None:
        if output_line_observer is not None:
            output_line_observer(line)
        if output_line_filter is None or output_line_filter(line):
            print(line, end="", file=stdout)
            stdout.flush()

    def _write_fake_docs_review_artifacts(target) -> None:
        metadata = smoke_matrix_module._docs_review_artifact_metadata(target)
        if metadata is None:
            return
        for key, value in metadata.items():
            if key in {"display_name", "target_name", "bundle_index_rerun_hint"}:
                continue
            resolved_path = resolve_checkout_path(value, checkout_root=checkout_root)
            if key in {"artifact_root", "render_output_dir"}:
                resolved_path.mkdir(parents=True, exist_ok=True)
                continue
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            if resolved_path.suffix == ".json":
                resolved_path.write_text(
                    json.dumps(
                        {
                            "path_key": key,
                            "target_name": target.name,
                            "display_name": target.display_label,
                            "path": value,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            else:
                resolved_path.write_text(f"{target.name}:{key}\n", encoding="utf-8")

    def _fake_run_smoke_target(target, **kwargs) -> int:
        stdout = kwargs["stdout"]
        output_line_filter = kwargs.get("output_line_filter")
        output_line_observer = kwargs.get("output_line_observer")
        if target.name == smoke_matrix_module.LIVE_INCLUSIVE_STANDALONE_TARGET_NAME:
            _emit_output(
                "provider=fake-live mode=live\n",
                stdout=stdout,
                output_line_filter=output_line_filter,
                output_line_observer=output_line_observer,
            )
            _emit_output(
                "live_runtime_requested= True\n",
                stdout=stdout,
                output_line_filter=output_line_filter,
                output_line_observer=output_line_observer,
            )
        _emit_output(
            f"{target.name}_check= True\n",
            stdout=stdout,
            output_line_filter=output_line_filter,
            output_line_observer=output_line_observer,
        )
        _write_fake_docs_review_artifacts(target)
        return 0

    smoke_matrix_module.run_smoke_target = _fake_run_smoke_target
    try:
        yield
    finally:
        smoke_matrix_module.run_smoke_target = original


def _load_smoke_matrix_module():
    return load_script_module(SMOKE_MATRIX_SCRIPT_PATH, "scripts.smoke_matrix_artifact_roots_smoke_target")


def _capture_success_summary_line(stdout_text: str) -> str:
    for line in stdout_text.splitlines():
        if line.startswith(SUCCESS_SUMMARY_PREFIX):
            return line
    return ""


def _capture_prefixed_line(stdout_text: str, prefix: str) -> str:
    for line in stdout_text.splitlines():
        if line.startswith(prefix):
            return line
    return ""


def run_smoke_matrix_artifact_roots_smoke() -> list[tuple[str, object]]:
    smoke_matrix_module = _load_smoke_matrix_module()
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-artifact-roots-") as temp_dir:
        checkout_root = Path(temp_dir)
        review_spec = build_smoke_matrix_docs_review_observer_spec(
            smoke_matrix_module,
            requested_target_name="review",
            driver_stem="smoke_matrix_artifact_roots_review",
        )
        all_review_spec = build_smoke_matrix_docs_review_observer_spec(
            smoke_matrix_module,
            requested_target_name="all-review",
            driver_stem="smoke_matrix_artifact_roots_all_review",
        )
        with _patched_run_smoke_target(smoke_matrix_module, checkout_root):
            review_run, review_output = observe_loaded_review_artifact_output(
                smoke_matrix_module,
                argv=[review_spec.requested_target_name],
                checkout_root=checkout_root,
                **review_spec.observer_kwargs(),
            )
            review_exit_code = review_run.exit_code
            review_stdout = review_run.stdout
            review_stderr = review_run.stderr
            review_paths = review_output.matrix_summary_paths
            review_index_path = review_paths.get("bundle_index_path")
            review_summary_artifact_path = review_output.matrix_summary_path
            review_index_before = (
                review_index_path.read_text(encoding="utf-8")
                if review_index_path is not None and review_index_path.exists()
                else None
            )
            review_summary_before = (
                review_summary_artifact_path.read_text(encoding="utf-8")
                if review_summary_artifact_path is not None and review_summary_artifact_path.exists()
                else None
            )
            all_review_run, all_review_output = observe_loaded_review_artifact_output(
                smoke_matrix_module,
                argv=[all_review_spec.requested_target_name],
                checkout_root=checkout_root,
                **all_review_spec.observer_kwargs(),
            )
            all_review_exit_code = all_review_run.exit_code
            all_review_stdout = all_review_run.stdout
            all_review_stderr = all_review_run.stderr
            all_review_paths = all_review_output.matrix_summary_paths

        review_index_preserved = (
            review_index_before is not None
            and review_index_path is not None
            and review_index_path.exists()
            and review_index_path.read_text(encoding="utf-8") == review_index_before
        )
        review_summary_preserved = (
            review_summary_before is not None
            and review_summary_artifact_path is not None
            and review_summary_artifact_path.exists()
            and review_summary_artifact_path.read_text(encoding="utf-8") == review_summary_before
        )
        review_root = review_paths.get("artifact_root")
        all_review_root = all_review_paths.get("artifact_root")
        artifact_roots_distinct = review_root is not None and all_review_root is not None and review_root != all_review_root
        review_files_exist = review_spec.resolved_artifact_paths_exist(review_output)
        all_review_files_exist = all_review_spec.resolved_artifact_paths_exist(all_review_output)
        review_summary_line = _capture_success_summary_line(review_stdout)
        all_review_summary_line = _capture_success_summary_line(all_review_stdout)
        review_rerun_hint_line = _capture_prefixed_line(review_stdout, RERUN_HINT_PREFIX)
        all_review_rerun_hint_line = _capture_prefixed_line(all_review_stdout, RERUN_HINT_PREFIX)

        return [
            ("checkout_root", str(checkout_root)),
            *build_review_artifact_success_results(
                review_output,
                review_spec,
                **review_spec.success_result_kwargs(),
                success_summary_line=review_summary_line,
                success_summary_prefix=SUCCESS_SUMMARY_PREFIX,
                rerun_hint_line=review_rerun_hint_line,
                rerun_hint_prefix=RERUN_HINT_PREFIX,
                exit_code=review_exit_code,
                stderr_text=review_stderr,
                artifacts_exist=review_files_exist,
            ),
            *build_review_artifact_success_results(
                all_review_output,
                all_review_spec,
                **all_review_spec.success_result_kwargs(),
                success_summary_line=all_review_summary_line,
                success_summary_prefix=SUCCESS_SUMMARY_PREFIX,
                rerun_hint_line=all_review_rerun_hint_line,
                rerun_hint_prefix=RERUN_HINT_PREFIX,
                exit_code=all_review_exit_code,
                stderr_text=all_review_stderr,
                artifacts_exist=all_review_files_exist,
            ),
            ("artifact_roots_distinct", artifact_roots_distinct),
            ("review_index_preserved_after_all_review", review_index_preserved),
            ("review_summary_preserved_after_all_review", review_summary_preserved),
        ]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_artifact_roots_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
