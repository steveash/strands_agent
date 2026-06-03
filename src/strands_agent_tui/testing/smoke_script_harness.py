from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from shutil import rmtree
from textwrap import dedent
from typing import Any, Callable, Iterator, Literal

from .smoke_cli_doc_artifacts import (
    load_review_matrix_summary,
    output_path_from_prefixed_lines,
    resolve_checkout_path,
    resolve_review_artifact_paths,
)

SMOKE_MATRIX_REVIEW_METADATA_PREFIX = "[smoke-matrix] review metadata: "
SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX = "[smoke-matrix] review artifacts: "
SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX = "[smoke-matrix] review matrix summary: "


@dataclass(frozen=True)
class SmokeScriptRunResult:
    checkout_root: Path
    exit_code: int
    stdout: str
    stderr: str
    cleanup_callback: Callable[[], None]

    @property
    def stdout_lines(self) -> list[str]:
        return self.stdout.splitlines()

    @property
    def stderr_lines(self) -> list[str]:
        return self.stderr.splitlines()

    def cleanup(self) -> None:
        self.cleanup_callback()


@dataclass(frozen=True)
class ReviewArtifactOutputObservation:
    checkout_root: Path
    metadata_index: int | None
    artifacts_index: int | None
    matrix_summary_index: int | None
    metadata_line: str
    artifacts_line: str
    matrix_summary_line: str
    metadata_payload: dict[str, object]
    metadata_paths: dict[str, Path]
    metadata_matrix_summary_path: Path | None
    matrix_summary_path: Path | None
    matrix_summary_payload: dict[str, object]
    matrix_summary_paths: dict[str, Path]

    @property
    def metadata_line_present(self) -> bool:
        return bool(self.metadata_line)

    @property
    def artifacts_line_present(self) -> bool:
        return bool(self.artifacts_line)

    @property
    def matrix_summary_line_present(self) -> bool:
        return bool(self.matrix_summary_line)

    @property
    def matrix_summary_artifact_exists(self) -> bool:
        return self.matrix_summary_path is not None and self.matrix_summary_path.exists()

    def metadata_targets(self, target_name: str) -> bool:
        return self.metadata_payload.get("target_name") == target_name

    def metadata_artifact_root_matches(self, artifact_root: str) -> bool:
        return self.metadata_payload.get("artifact_root") == artifact_root

    def metadata_matrix_summary_matches(self, matrix_summary_path: str) -> bool:
        return self.metadata_payload.get("matrix_summary_path") == matrix_summary_path

    def metadata_bundle_index_rerun_hint_matches(self, rerun_hint: str) -> bool:
        return self.metadata_payload.get("bundle_index_rerun_hint") == rerun_hint

    def matrix_summary_targets(self, target_name: str) -> bool:
        return self.matrix_summary_payload.get("target_name") == target_name

    def matrix_summary_artifact_root_matches(self, artifact_root: str) -> bool:
        return self.matrix_summary_payload.get("artifact_root") == artifact_root

    def matrix_summary_path_matches(self, matrix_summary_path: str) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == matrix_summary_path

    def matrix_summary_bundle_index_rerun_hint_matches(self, rerun_hint: str) -> bool:
        return self.matrix_summary_payload.get("bundle_index_rerun_hint") == rerun_hint

    def matrix_summary_path_matches_metadata(self) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == self.metadata_payload.get(
            "matrix_summary_path"
        )

    def matrix_summary_line_matches_metadata_path(self) -> bool:
        return self.matrix_summary_path == self.metadata_matrix_summary_path

    def _payload_for_source(self, source: Literal["metadata", "matrix_summary"]) -> dict[str, object]:
        if source == "metadata":
            return self.metadata_payload
        return self.matrix_summary_payload

    def _paths_for_source(self, source: Literal["metadata", "matrix_summary"]) -> dict[str, Path]:
        if source == "metadata":
            return self.metadata_paths
        return self.matrix_summary_paths

    def payload_path_matches(
        self,
        source: Literal["metadata", "matrix_summary"],
        key: str,
        expected_path: str,
    ) -> bool:
        return self._payload_for_source(source).get(key) == expected_path

    def payload_paths_match(
        self,
        source: Literal["metadata", "matrix_summary"],
        expected_paths: Mapping[str, str],
    ) -> bool:
        return all(
            self.payload_path_matches(source, key, expected_path)
            for key, expected_path in expected_paths.items()
        )

    def resolved_path_matches(
        self,
        source: Literal["metadata", "matrix_summary"],
        key: str,
        expected_path: Path,
    ) -> bool:
        return self._paths_for_source(source).get(key) == expected_path

    def resolved_paths_match(
        self,
        source: Literal["metadata", "matrix_summary"],
        expected_paths: Mapping[str, Path],
    ) -> bool:
        return all(
            self.resolved_path_matches(source, key, expected_path)
            for key, expected_path in expected_paths.items()
        )


@dataclass(frozen=True)
class SmokeMatrixDocsReviewObserverSpec:
    requested_target_name: str
    expected_target_name: str
    expected_artifact_root: str
    expected_matrix_summary_path: str
    expected_bundle_index_rerun_hint: str
    expected_artifact_paths: dict[str, str]
    driver_filename: str
    metadata_prefix: str = SMOKE_MATRIX_REVIEW_METADATA_PREFIX
    artifacts_prefix: str = SMOKE_MATRIX_REVIEW_ARTIFACTS_PREFIX
    matrix_summary_prefix: str = SMOKE_MATRIX_REVIEW_MATRIX_SUMMARY_PREFIX

    def observer_kwargs(self) -> dict[str, str]:
        return {
            "metadata_prefix": self.metadata_prefix,
            "artifacts_prefix": self.artifacts_prefix,
            "matrix_summary_prefix": self.matrix_summary_prefix,
        }

    def expected_path(self, key: str) -> str | None:
        return self.expected_artifact_paths.get(key)

    def resolve_expected_paths(self, *, checkout_root: Path) -> dict[str, Path]:
        return {
            key: resolve_checkout_path(value, checkout_root=checkout_root)
            for key, value in self.expected_artifact_paths.items()
        }

    def metadata_artifact_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.payload_paths_match("metadata", self.expected_artifact_paths)

    def matrix_summary_artifact_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.payload_paths_match("matrix_summary", self.expected_artifact_paths)

    def metadata_resolved_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.resolved_paths_match(
            "metadata",
            self.resolve_expected_paths(checkout_root=observation.checkout_root),
        )

    def matrix_summary_resolved_paths_match(self, observation: ReviewArtifactOutputObservation) -> bool:
        return observation.resolved_paths_match(
            "matrix_summary",
            self.resolve_expected_paths(checkout_root=observation.checkout_root),
        )

    def resolved_artifact_paths_exist(self, observation: ReviewArtifactOutputObservation) -> bool:
        return all(
            path.exists()
            for path in self.resolve_expected_paths(checkout_root=observation.checkout_root).values()
        )


def build_smoke_matrix_docs_review_observer_spec(
    smoke_matrix_module: Any,
    *,
    requested_target_name: Literal["review", "all-review"],
    driver_stem: str,
) -> SmokeMatrixDocsReviewObserverSpec:
    targets = smoke_matrix_module.CLI_SPEC.resolve_targets(
        script_dir=smoke_matrix_module.SCRIPT_DIR,
        requested_target_name=requested_target_name,
    )
    docs_review_targets = [
        target
        for target in targets
        if target.name
        in {
            smoke_matrix_module.DOCS_REVIEW_TARGET_NAME,
            smoke_matrix_module.DOCS_REVIEW_ALL_TARGET_NAME,
        }
    ]
    if len(docs_review_targets) != 1:
        raise ValueError(
            "requested_target_name must resolve to exactly one docs-review smoke-matrix target"
        )
    target = docs_review_targets[0]
    metadata = smoke_matrix_module._docs_review_artifact_metadata(target)
    if not isinstance(metadata, dict):
        raise ValueError("docs-review smoke-matrix target metadata is required")

    target_name = metadata.get("target_name")
    artifact_root = metadata.get("artifact_root")
    matrix_summary_path = metadata.get("matrix_summary_path")
    bundle_index_rerun_hint = metadata.get("bundle_index_rerun_hint")
    artifact_paths = {
        key: value
        for key, value in metadata.items()
        if key not in {"display_name", "target_name", "bundle_index_rerun_hint"}
        and isinstance(value, str)
        and value
    }

    if not isinstance(target_name, str) or not target_name:
        raise ValueError("docs-review smoke-matrix target metadata must include target_name")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ValueError("docs-review smoke-matrix target metadata must include artifact_root")
    if not isinstance(matrix_summary_path, str) or not matrix_summary_path:
        raise ValueError("docs-review smoke-matrix target metadata must include matrix_summary_path")
    if not isinstance(bundle_index_rerun_hint, str) or not bundle_index_rerun_hint:
        raise ValueError(
            "docs-review smoke-matrix target metadata must include bundle_index_rerun_hint"
        )

    normalized_driver_stem = driver_stem.removesuffix(".py")
    if not normalized_driver_stem.startswith("run_"):
        normalized_driver_stem = f"run_{normalized_driver_stem}"
    return SmokeMatrixDocsReviewObserverSpec(
        requested_target_name=requested_target_name,
        expected_target_name=target_name,
        expected_artifact_root=artifact_root,
        expected_matrix_summary_path=matrix_summary_path,
        expected_bundle_index_rerun_hint=bundle_index_rerun_hint,
        expected_artifact_paths=artifact_paths,
        driver_filename=f"{normalized_driver_stem}.py",
    )


def find_prefixed_line_index(lines: Sequence[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def detail_safe_text(text: str) -> str:
    return text.replace("= False", "=False")


def collect_review_artifact_output(
    output_lines: str | Sequence[str],
    *,
    checkout_root: Path,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
) -> ReviewArtifactOutputObservation:
    lines = output_lines.splitlines() if isinstance(output_lines, str) else list(output_lines)
    metadata_index = find_prefixed_line_index(lines, metadata_prefix) if metadata_prefix is not None else None
    artifacts_index = find_prefixed_line_index(lines, artifacts_prefix) if artifacts_prefix is not None else None
    matrix_summary_index = find_prefixed_line_index(lines, matrix_summary_prefix)

    metadata_line = lines[metadata_index] if metadata_index is not None else ""
    artifacts_line = lines[artifacts_index] if artifacts_index is not None else ""
    matrix_summary_line = lines[matrix_summary_index] if matrix_summary_index is not None else ""

    metadata_payload: dict[str, object] = {}
    if metadata_line and metadata_prefix is not None:
        loaded_metadata = json.loads(metadata_line.removeprefix(metadata_prefix))
        if isinstance(loaded_metadata, dict):
            metadata_payload = loaded_metadata
    metadata_paths = (
        resolve_review_artifact_paths(metadata_payload, checkout_root=checkout_root) if metadata_payload else {}
    )
    metadata_matrix_summary_path = metadata_paths.get("matrix_summary_path")

    matrix_summary_path = output_path_from_prefixed_lines(
        lines,
        prefix=matrix_summary_prefix,
        checkout_root=checkout_root,
    )
    matrix_summary_payload, matrix_summary_paths = load_review_matrix_summary(
        matrix_summary_path,
        checkout_root=checkout_root,
    )

    return ReviewArtifactOutputObservation(
        checkout_root=checkout_root,
        metadata_index=metadata_index,
        artifacts_index=artifacts_index,
        matrix_summary_index=matrix_summary_index,
        metadata_line=metadata_line,
        artifacts_line=artifacts_line,
        matrix_summary_line=matrix_summary_line,
        metadata_payload=metadata_payload,
        metadata_paths=metadata_paths,
        metadata_matrix_summary_path=metadata_matrix_summary_path,
        matrix_summary_path=matrix_summary_path,
        matrix_summary_payload=matrix_summary_payload,
        matrix_summary_paths=matrix_summary_paths,
    )


def load_script_module(script_path: Path, module_name: str) -> Any:
    spec = spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


@contextmanager
def _unset_env(*variable_names: str) -> Iterator[None]:
    previous_values = {name: os.environ.get(name) for name in variable_names}
    for name in variable_names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_script_module_main_in_temp_checkout(
    *,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    module = load_script_module(script_path, module_name)
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    stdout = StringIO()
    stderr = StringIO()
    with _pushd(checkout_root), _unset_env(*tuple(unset_env_names)):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(list(argv))
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=0 if exit_code is None else int(exit_code),
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def run_loaded_script_module_main(
    module: Any,
    *,
    argv: Sequence[str],
    checkout_root: Path,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    stdout = StringIO()
    stderr = StringIO()
    with _pushd(checkout_root), _unset_env(*tuple(unset_env_names)):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(list(argv))
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=0 if exit_code is None else int(exit_code),
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        cleanup_callback=lambda: None,
    )


def run_loaded_script_module_main_in_temp_checkout(
    module: Any,
    *,
    argv: Sequence[str],
    temp_prefix: str,
    unset_env_names: Iterable[str] = (),
) -> SmokeScriptRunResult:
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    smoke_run = run_loaded_script_module_main(
        module,
        argv=argv,
        checkout_root=checkout_root,
        unset_env_names=unset_env_names,
    )
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=smoke_run.exit_code,
        stdout=smoke_run.stdout,
        stderr=smoke_run.stderr,
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def _validate_review_output_stream(output_stream: Literal["stdout", "stderr"] | str) -> None:
    if output_stream not in {"stdout", "stderr"}:
        raise ValueError(f"output_stream must be 'stdout' or 'stderr', got {output_stream!r}")


def _review_output_lines(
    smoke_run: SmokeScriptRunResult,
    *,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> list[str]:
    _validate_review_output_stream(output_stream)
    return smoke_run.stdout_lines if output_stream == "stdout" else smoke_run.stderr_lines


def observe_review_artifact_output_in_temp_checkout(
    *,
    temp_prefix: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
    module: Any | None = None,
    argv: Sequence[str] | None = None,
    unset_env_names: Iterable[str] = (),
    driver_source: str | None = None,
    driver_filename: str | None = None,
    python_executable: str | None = None,
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    _validate_review_output_stream(output_stream)

    module_selected = module is not None
    driver_selected = driver_source is not None
    if module_selected == driver_selected:
        raise ValueError("provide exactly one review artifact source: module or driver_source")

    if module is not None:
        if argv is None:
            raise ValueError("argv is required when observing a loaded review artifact module")
        smoke_run = run_loaded_script_module_main_in_temp_checkout(
            module,
            argv=argv,
            temp_prefix=temp_prefix,
            unset_env_names=unset_env_names,
        )
    else:
        if driver_filename is None:
            raise ValueError("driver_filename is required when driver_source is provided")
        smoke_run = run_python_driver_in_temp_checkout(
            driver_source=driver_source,
            temp_prefix=temp_prefix,
            driver_filename=driver_filename,
            python_executable=python_executable,
        )

    review_output = collect_review_artifact_output(
        _review_output_lines(smoke_run, output_stream=output_stream),
        checkout_root=smoke_run.checkout_root,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
    )
    return smoke_run, review_output


def observe_loaded_review_artifact_output(
    module: Any,
    *,
    argv: Sequence[str],
    checkout_root: Path,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    unset_env_names: Iterable[str] = (),
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    _validate_review_output_stream(output_stream)
    smoke_run = run_loaded_script_module_main(
        module,
        argv=argv,
        checkout_root=checkout_root,
        unset_env_names=unset_env_names,
    )
    review_output = collect_review_artifact_output(
        _review_output_lines(smoke_run, output_stream=output_stream),
        checkout_root=checkout_root,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
    )
    return smoke_run, review_output


def observe_loaded_review_artifact_output_in_temp_checkout(
    module: Any,
    *,
    argv: Sequence[str],
    temp_prefix: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    unset_env_names: Iterable[str] = (),
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_review_artifact_output_in_temp_checkout(
        module=module,
        argv=argv,
        temp_prefix=temp_prefix,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        unset_env_names=unset_env_names,
        output_stream=output_stream,
    )


def build_script_driver_source(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
) -> str:
    env_assignments = env_assignments or {}
    lines = [
        "from __future__ import annotations",
        "",
        "import os",
        "import sys",
        "from importlib.util import module_from_spec, spec_from_file_location",
        "from pathlib import Path",
        "",
        f"repo_root = Path({str(repo_root)!r})",
        "sys.path.insert(0, str(repo_root / 'src'))",
        f"script_path = Path({str(script_path)!r})",
        f"spec = spec_from_file_location({module_name!r}, script_path)",
        "assert spec is not None and spec.loader is not None",
        "module = module_from_spec(spec)",
        "spec.loader.exec_module(module)",
    ]
    for name, value in env_assignments.items():
        lines.append(f"os.environ[{name!r}] = {value!r}")
    for name in env_unsets:
        lines.append(f"os.environ.pop({name!r}, None)")
    body = dedent(hook_source).strip()
    if body:
        lines.extend(["", body])
    lines.extend(["", f"raise SystemExit(module.main({list(argv)!r}))", ""])
    return "\n".join(lines)


def run_python_driver_in_temp_checkout(
    *,
    driver_source: str,
    temp_prefix: str,
    driver_filename: str,
    python_executable: str | None = None,
) -> SmokeScriptRunResult:
    checkout_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    driver_path = checkout_root / driver_filename
    driver_path.write_text(driver_source, encoding="utf-8")
    result = subprocess.run(
        [python_executable or sys.executable, str(driver_path)],
        cwd=checkout_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return SmokeScriptRunResult(
        checkout_root=checkout_root,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        cleanup_callback=lambda: rmtree(checkout_root, ignore_errors=True),
    )


def run_script_module_main_via_driver_in_temp_checkout(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    driver_filename: str,
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
    python_executable: str | None = None,
) -> SmokeScriptRunResult:
    return run_python_driver_in_temp_checkout(
        driver_source=build_script_driver_source(
            repo_root=repo_root,
            script_path=script_path,
            module_name=module_name,
            argv=argv,
            env_assignments=env_assignments,
            env_unsets=env_unsets,
            hook_source=hook_source,
        ),
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        python_executable=python_executable,
    )



def observe_subprocess_review_artifact_output(
    *,
    driver_source: str,
    temp_prefix: str,
    driver_filename: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    python_executable: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_review_artifact_output_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        python_executable=python_executable,
        output_stream=output_stream,
    )



def observe_script_module_main_via_driver_review_artifact_output(
    *,
    repo_root: Path,
    script_path: Path,
    module_name: str,
    argv: Sequence[str],
    temp_prefix: str,
    driver_filename: str,
    matrix_summary_prefix: str,
    metadata_prefix: str | None = None,
    artifacts_prefix: str | None = None,
    env_assignments: Mapping[str, str] | None = None,
    env_unsets: Sequence[str] = (),
    hook_source: str = "",
    python_executable: str | None = None,
    output_stream: Literal["stdout", "stderr"] = "stdout",
) -> tuple[SmokeScriptRunResult, ReviewArtifactOutputObservation]:
    return observe_subprocess_review_artifact_output(
        driver_source=build_script_driver_source(
            repo_root=repo_root,
            script_path=script_path,
            module_name=module_name,
            argv=argv,
            env_assignments=env_assignments,
            env_unsets=env_unsets,
            hook_source=hook_source,
        ),
        temp_prefix=temp_prefix,
        driver_filename=driver_filename,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
        python_executable=python_executable,
        output_stream=output_stream,
    )
