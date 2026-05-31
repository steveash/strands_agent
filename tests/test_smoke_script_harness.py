from __future__ import annotations

import os
from pathlib import Path

from strands_agent_tui.testing import (
    build_script_driver_source,
    detail_safe_text,
    find_prefixed_line_index,
    run_python_driver_in_temp_checkout,
    run_loaded_script_module_main,
    load_script_module,
    run_script_module_main_in_temp_checkout,
)


def _write_target_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_find_prefixed_line_index_and_detail_safe_text() -> None:
    lines = ["alpha", "beta: 1", "beta: 2"]

    assert find_prefixed_line_index(lines, "beta:") == 1
    assert find_prefixed_line_index(lines, "gamma:") is None
    assert detail_safe_text("render_manifest_payload= False") == "render_manifest_payload=False"


def test_run_script_module_main_in_temp_checkout_changes_cwd_and_unsets_env(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "temp_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"keep={os.environ.get('HARNESS_KEEP', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 3
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_KEEP", "present")
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_script_module_main_in_temp_checkout(
        script_path=script_path,
        module_name="tests.temp_target",
        argv=["all-review"],
        temp_prefix="harness-module-run-",
        unset_env_names=("HARNESS_CLEAR",),
    )
    try:
        assert result.exit_code == 3
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-module-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['all-review']",
            "keep=present",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_KEEP"] == "present"
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()


def test_run_loaded_script_module_main_reuses_checkout_without_cleanup(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "loaded_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"keep={os.environ.get('HARNESS_KEEP', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 5
""".strip()
        + "\n",
    )
    checkout_root = tmp_path / "loaded-checkout"
    checkout_root.mkdir()
    monkeypatch.setenv("HARNESS_KEEP", "present")
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_loaded_script_module_main(
        load_script_module(script_path, "tests.loaded_target"),
        argv=["review"],
        checkout_root=checkout_root,
        unset_env_names=("HARNESS_CLEAR",),
    )

    assert result.exit_code == 5
    assert result.stderr == ""
    assert result.checkout_root == checkout_root
    assert result.stdout_lines == [
        "cwd_name=loaded-checkout",
        "argv=['review']",
        "keep=present",
        "clear=<missing>",
    ]
    result.cleanup()
    assert checkout_root.exists()
    assert os.environ["HARNESS_KEEP"] == "present"
    assert os.environ["HARNESS_CLEAR"] == "remove-me"


def test_build_script_driver_source_and_run_python_driver_in_temp_checkout(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "driver_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path
import os

VALUE = 'script'


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    print(f"value={VALUE}")
    print(f"set={os.environ.get('HARNESS_SET', '<missing>')}")
    print(f"clear={os.environ.get('HARNESS_CLEAR', '<missing>')}")
    return 4
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_target",
        argv=["docs-focused"],
        env_assignments={"HARNESS_SET": "enabled"},
        env_unsets=("HARNESS_CLEAR",),
        hook_source="module.VALUE = 'hooked'",
    )

    result = run_python_driver_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix="harness-driver-run-",
        driver_filename="run_driver_target.py",
    )
    try:
        assert result.exit_code == 4
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-driver-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['docs-focused']",
            "value=hooked",
            "set=enabled",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()
