from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from strands_agent_tui.testing import (
    emit_smoke_results,
    load_script_module,
    observe_loaded_review_artifact_output,
    resolve_checkout_path,
    resolve_review_artifact_paths,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
SUCCESS_SUMMARY_PREFIX = "[smoke-matrix] summary: 4/4 bundles passed in "
REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "


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
            if key in {"display_name", "target_name"}:
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


def _expected_docs_review_metadata(smoke_matrix_module, requested_target_name: str) -> dict[str, str]:
    target = smoke_matrix_module.CLI_SPEC.resolve_targets(
        script_dir=smoke_matrix_module.SCRIPT_DIR,
        requested_target_name=requested_target_name,
    )[-1]
    metadata = smoke_matrix_module._docs_review_artifact_metadata(target)
    assert metadata is not None
    return metadata


def _resolved_docs_review_paths(smoke_matrix_module, requested_target_name: str, *, checkout_root: Path) -> dict[str, Path]:
    return resolve_review_artifact_paths(
        _expected_docs_review_metadata(smoke_matrix_module, requested_target_name),
        checkout_root=checkout_root,
    )


def run_smoke_matrix_artifact_roots_smoke() -> list[tuple[str, object]]:
    smoke_matrix_module = _load_smoke_matrix_module()
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-artifact-roots-") as temp_dir:
        checkout_root = Path(temp_dir)
        expected_review_metadata = _expected_docs_review_metadata(
            smoke_matrix_module,
            "docs-review",
        )
        expected_all_review_metadata = _expected_docs_review_metadata(
            smoke_matrix_module,
            "all-review",
        )
        expected_review_paths = resolve_review_artifact_paths(
            expected_review_metadata,
            checkout_root=checkout_root,
        )
        expected_all_review_paths = resolve_review_artifact_paths(
            expected_all_review_metadata,
            checkout_root=checkout_root,
        )

        with _patched_run_smoke_target(smoke_matrix_module, checkout_root):
            review_run, review_output = observe_loaded_review_artifact_output(
                smoke_matrix_module,
                argv=["review"],
                checkout_root=checkout_root,
                metadata_prefix=REVIEW_METADATA_PREFIX,
                artifacts_prefix=REVIEW_ARTIFACTS_PREFIX,
                matrix_summary_prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
            )
            review_exit_code = review_run.exit_code
            review_stdout = review_run.stdout
            review_stderr = review_run.stderr
            review_summary_payload = review_output.matrix_summary_payload
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
                argv=["all-review"],
                checkout_root=checkout_root,
                metadata_prefix=REVIEW_METADATA_PREFIX,
                artifacts_prefix=REVIEW_ARTIFACTS_PREFIX,
                matrix_summary_prefix=REVIEW_MATRIX_SUMMARY_PREFIX,
            )
            all_review_exit_code = all_review_run.exit_code
            all_review_stdout = all_review_run.stdout
            all_review_stderr = all_review_run.stderr
            all_review_summary_payload = all_review_output.matrix_summary_payload
            all_review_paths = all_review_output.matrix_summary_paths

        review_summary_path_from_line = review_output.matrix_summary_path
        all_review_summary_path_from_line = all_review_output.matrix_summary_path
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
        review_files_exist = bool(review_paths) and all(path.exists() for path in review_paths.values())
        all_review_files_exist = bool(all_review_paths) and all(path.exists() for path in all_review_paths.values())
        review_summary_line = _capture_success_summary_line(review_stdout)
        all_review_summary_line = _capture_success_summary_line(all_review_stdout)

        return [
            ("checkout_root", str(checkout_root)),
            ("review_artifact_root", str(review_root) if review_root is not None else ""),
            ("all_review_artifact_root", str(all_review_root) if all_review_root is not None else ""),
            ("review_metadata_line", review_output.metadata_line),
            ("review_artifacts_line", review_output.artifacts_line),
            ("review_matrix_summary_line", review_output.matrix_summary_line),
            ("all_review_metadata_line", all_review_output.metadata_line),
            ("all_review_artifacts_line", all_review_output.artifacts_line),
            ("all_review_matrix_summary_line", all_review_output.matrix_summary_line),
            ("review_summary_line", review_summary_line),
            ("all_review_summary_line", all_review_summary_line),
            ("review_exit_code_zero", review_exit_code == 0),
            ("all_review_exit_code_zero", all_review_exit_code == 0),
            ("review_stderr_empty", review_stderr == ""),
            ("all_review_stderr_empty", all_review_stderr == ""),
            ("review_metadata_line_present", review_output.metadata_line_present),
            ("review_artifacts_line_present", review_output.artifacts_line_present),
            ("review_matrix_summary_line_present", review_output.matrix_summary_line_present),
            ("all_review_metadata_line_present", all_review_output.metadata_line_present),
            ("all_review_artifacts_line_present", all_review_output.artifacts_line_present),
            ("all_review_matrix_summary_line_present", all_review_output.matrix_summary_line_present),
            (
                "review_metadata_targets_docs_review",
                review_output.metadata_targets(smoke_matrix_module.DOCS_REVIEW_TARGET_NAME),
            ),
            (
                "all_review_metadata_targets_docs_review_all",
                all_review_output.metadata_targets(smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME),
            ),
            (
                "review_metadata_artifact_root_matches_review",
                review_output.metadata_artifact_root_matches(expected_review_metadata["artifact_root"]),
            ),
            (
                "all_review_metadata_artifact_root_matches_all_review",
                all_review_output.metadata_artifact_root_matches(expected_all_review_metadata["artifact_root"]),
            ),
            (
                "review_metadata_matrix_summary_matches_expected_path",
                review_output.metadata_matrix_summary_matches(expected_review_metadata["matrix_summary_path"]),
            ),
            (
                "all_review_metadata_matrix_summary_matches_expected_path",
                all_review_output.metadata_matrix_summary_matches(expected_all_review_metadata["matrix_summary_path"]),
            ),
            (
                "review_matrix_summary_line_matches_expected_path",
                review_summary_path_from_line == expected_review_paths["matrix_summary_path"],
            ),
            (
                "all_review_matrix_summary_line_matches_expected_path",
                all_review_summary_path_from_line == expected_all_review_paths["matrix_summary_path"],
            ),
            ("review_paths_loaded_from_matrix_summary", bool(review_paths)),
            ("all_review_paths_loaded_from_matrix_summary", bool(all_review_paths)),
            ("artifact_roots_distinct", artifact_roots_distinct),
            ("review_artifacts_exist", review_files_exist),
            ("all_review_artifacts_exist", all_review_files_exist),
            (
                "review_summary_targets_docs_review",
                review_summary_payload.get("target_name") == smoke_matrix_module.DOCS_REVIEW_TARGET_NAME,
            ),
            (
                "all_review_summary_targets_docs_review_all",
                all_review_summary_payload.get("target_name") == smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME,
            ),
            (
                "review_summary_path_keeps_review_root",
                resolve_review_artifact_paths(review_summary_payload, checkout_root=checkout_root).get("artifact_root")
                == review_root
                if review_root is not None
                else False,
            ),
            (
                "all_review_summary_path_keeps_all_review_root",
                resolve_review_artifact_paths(all_review_summary_payload, checkout_root=checkout_root).get("artifact_root")
                == all_review_root
                if all_review_root is not None
                else False,
            ),
            (
                "review_matrix_summary_path_matches_metadata",
                review_output.matrix_summary_path_matches_metadata(),
            ),
            (
                "all_review_matrix_summary_path_matches_metadata",
                all_review_output.matrix_summary_path_matches_metadata(),
            ),
            (
                "review_matrix_summary_line_matches_metadata_path",
                review_output.matrix_summary_line_matches_metadata_path(),
            ),
            (
                "all_review_matrix_summary_line_matches_metadata_path",
                all_review_output.matrix_summary_line_matches_metadata_path(),
            ),
            (
                "review_loaded_summary_path_matches_line",
                review_paths.get("matrix_summary_path") == review_summary_path_from_line,
            ),
            (
                "all_review_loaded_summary_path_matches_line",
                all_review_paths.get("matrix_summary_path") == all_review_summary_path_from_line,
            ),
            ("review_index_preserved_after_all_review", review_index_preserved),
            ("review_summary_preserved_after_all_review", review_summary_preserved),
            ("review_summary_line_present", review_summary_line.startswith(SUCCESS_SUMMARY_PREFIX)),
            (
                "all_review_summary_line_present",
                all_review_summary_line.startswith(SUCCESS_SUMMARY_PREFIX),
            ),
        ]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    return emit_smoke_results(run_smoke_matrix_artifact_roots_smoke(), stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
