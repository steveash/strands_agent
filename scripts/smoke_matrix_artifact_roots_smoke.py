from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from typing import Iterator

from strands_agent_tui.testing import emit_smoke_results

SCRIPT_DIR = Path(__file__).resolve().parent
SMOKE_MATRIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_matrix.py"
SUCCESS_SUMMARY_PREFIX = "[smoke-matrix] summary: 4/4 bundles passed in "


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


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
            resolved_path = _resolve_checkout_path(value, checkout_root=checkout_root)
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
    spec = spec_from_file_location("scripts.smoke_matrix_artifact_roots_smoke_target", SMOKE_MATRIX_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_checkout_path(path_text: str, *, checkout_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return checkout_root / path


def _capture_success_summary_line(stdout_text: str) -> str:
    for line in stdout_text.splitlines():
        if line.startswith(SUCCESS_SUMMARY_PREFIX):
            return line
    return ""


def _run_matrix_alias(smoke_matrix_module, alias: str, *, checkout_root: Path) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with _pushd(checkout_root), redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = smoke_matrix_module.main([alias])
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _resolved_docs_review_paths(smoke_matrix_module, requested_target_name: str, *, checkout_root: Path) -> dict[str, Path]:
    target = smoke_matrix_module.CLI_SPEC.resolve_targets(
        script_dir=smoke_matrix_module.SCRIPT_DIR,
        requested_target_name=requested_target_name,
    )[-1]
    metadata = smoke_matrix_module._docs_review_artifact_metadata(target)
    assert metadata is not None
    return {key: _resolve_checkout_path(value, checkout_root=checkout_root) for key, value in metadata.items() if key not in {"display_name", "target_name"}}


def run_smoke_matrix_artifact_roots_smoke() -> list[tuple[str, object]]:
    smoke_matrix_module = _load_smoke_matrix_module()
    with tempfile.TemporaryDirectory(prefix="smoke-matrix-artifact-roots-") as temp_dir:
        checkout_root = Path(temp_dir)
        review_paths = _resolved_docs_review_paths(smoke_matrix_module, "docs-review", checkout_root=checkout_root)
        all_review_paths = _resolved_docs_review_paths(smoke_matrix_module, "all-review", checkout_root=checkout_root)

        with _patched_run_smoke_target(smoke_matrix_module, checkout_root):
            review_exit_code, review_stdout, review_stderr = _run_matrix_alias(
                smoke_matrix_module,
                "review",
                checkout_root=checkout_root,
            )
            review_index_before = review_paths["bundle_index_path"].read_text(encoding="utf-8")
            review_summary_before = review_paths["matrix_summary_path"].read_text(encoding="utf-8")
            all_review_exit_code, all_review_stdout, all_review_stderr = _run_matrix_alias(
                smoke_matrix_module,
                "all-review",
                checkout_root=checkout_root,
            )

        review_summary_payload = json.loads(review_paths["matrix_summary_path"].read_text(encoding="utf-8"))
        all_review_summary_payload = json.loads(all_review_paths["matrix_summary_path"].read_text(encoding="utf-8"))

        review_index_preserved = review_paths["bundle_index_path"].read_text(encoding="utf-8") == review_index_before
        review_summary_preserved = review_paths["matrix_summary_path"].read_text(encoding="utf-8") == review_summary_before
        review_root = review_paths["artifact_root"]
        all_review_root = all_review_paths["artifact_root"]
        artifact_roots_distinct = review_root != all_review_root
        review_files_exist = all(path.exists() for path in review_paths.values())
        all_review_files_exist = all(path.exists() for path in all_review_paths.values())
        review_summary_line = _capture_success_summary_line(review_stdout)
        all_review_summary_line = _capture_success_summary_line(all_review_stdout)

        return [
            ("checkout_root", str(checkout_root)),
            ("review_artifact_root", str(review_root)),
            ("all_review_artifact_root", str(all_review_root)),
            ("review_summary_line", review_summary_line),
            ("all_review_summary_line", all_review_summary_line),
            ("review_exit_code_zero", review_exit_code == 0),
            ("all_review_exit_code_zero", all_review_exit_code == 0),
            ("review_stderr_empty", review_stderr == ""),
            ("all_review_stderr_empty", all_review_stderr == ""),
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
                _resolve_checkout_path(review_summary_payload.get("artifact_root", ""), checkout_root=checkout_root)
                == review_root,
            ),
            (
                "all_review_summary_path_keeps_all_review_root",
                _resolve_checkout_path(all_review_summary_payload.get("artifact_root", ""), checkout_root=checkout_root)
                == all_review_root,
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
