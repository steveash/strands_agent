from __future__ import annotations

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
from typing import Any, Callable, Iterator


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


def find_prefixed_line_index(lines: Sequence[str], prefix: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def detail_safe_text(text: str) -> str:
    return text.replace("= False", "=False")


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
