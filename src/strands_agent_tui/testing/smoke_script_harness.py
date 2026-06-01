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
    resolve_review_artifact_paths,
)


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

    def matrix_summary_targets(self, target_name: str) -> bool:
        return self.matrix_summary_payload.get("target_name") == target_name

    def matrix_summary_artifact_root_matches(self, artifact_root: str) -> bool:
        return self.matrix_summary_payload.get("artifact_root") == artifact_root

    def matrix_summary_path_matches(self, matrix_summary_path: str) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == matrix_summary_path

    def matrix_summary_path_matches_metadata(self) -> bool:
        return self.matrix_summary_payload.get("matrix_summary_path") == self.metadata_payload.get(
            "matrix_summary_path"
        )

    def matrix_summary_line_matches_metadata_path(self) -> bool:
        return self.matrix_summary_path == self.metadata_matrix_summary_path


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
    if output_stream not in {"stdout", "stderr"}:
        raise ValueError("output_stream must be 'stdout' or 'stderr'")

    smoke_run = run_loaded_script_module_main(
        module,
        argv=argv,
        checkout_root=checkout_root,
        unset_env_names=unset_env_names,
    )
    output_lines = smoke_run.stdout_lines if output_stream == "stdout" else smoke_run.stderr_lines
    review_output = collect_review_artifact_output(
        output_lines,
        checkout_root=checkout_root,
        metadata_prefix=metadata_prefix,
        artifacts_prefix=artifacts_prefix,
        matrix_summary_prefix=matrix_summary_prefix,
    )
    return smoke_run, review_output


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
