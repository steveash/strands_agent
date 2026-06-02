from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from strands_agent_tui.testing import (
    build_script_driver_source,
    collect_review_artifact_output,
    detail_safe_text,
    find_prefixed_line_index,
    load_script_module,
    observe_loaded_review_artifact_output,
    observe_loaded_review_artifact_output_in_temp_checkout,
    observe_review_artifact_output_in_temp_checkout,
    observe_script_module_main_via_driver_review_artifact_output,
    observe_subprocess_review_artifact_output,
    run_loaded_script_module_main,
    run_loaded_script_module_main_in_temp_checkout,
    run_python_driver_in_temp_checkout,
    run_script_module_main_in_temp_checkout,
    run_script_module_main_via_driver_in_temp_checkout,
)


def _write_target_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_find_prefixed_line_index_and_detail_safe_text() -> None:
    lines = ["alpha", "beta: 1", "beta: 2"]

    assert find_prefixed_line_index(lines, "beta:") == 1
    assert find_prefixed_line_index(lines, "gamma:") is None
    assert detail_safe_text("render_manifest_payload= False") == "render_manifest_payload=False"


def test_collect_review_artifact_output_tracks_metadata_and_matrix_summary(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "bundle_index_rerun_hint": "rerun docs parity",
        "display_name": "docs-review",
        "target_name": "docs-review",
        "artifact_root": "artifacts/review",
        "bundle_index_path": "artifacts/review/index.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    metadata_payload = {
        "bundle_index_rerun_hint": "rerun docs parity",
        "display_name": "docs-review",
        "target_name": "docs-review",
        "artifact_root": "artifacts/review",
        "bundle_index_path": "artifacts/review/index.json",
        "matrix_summary_path": "artifacts/review/matrix-summary.json",
    }

    observed = collect_review_artifact_output(
        [
            f"[smoke-matrix] review metadata: {json.dumps(metadata_payload, sort_keys=True)}",
            "[smoke-matrix] review artifacts: artifacts/review",
            "[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json",
        ],
        checkout_root=checkout_root,
        metadata_prefix="[smoke-matrix] review metadata: ",
        artifacts_prefix="[smoke-matrix] review artifacts: ",
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    assert observed.metadata_index == 0
    assert observed.artifacts_index == 1
    assert observed.matrix_summary_index == 2
    assert observed.metadata_line_present is True
    assert observed.artifacts_line_present is True
    assert observed.matrix_summary_line_present is True
    assert observed.metadata_targets("docs-review") is True
    assert observed.metadata_artifact_root_matches("artifacts/review") is True
    assert observed.metadata_matrix_summary_matches("artifacts/review/matrix-summary.json") is True
    assert observed.metadata_bundle_index_rerun_hint_matches("rerun docs parity") is True
    assert observed.matrix_summary_artifact_exists is True
    assert observed.matrix_summary_targets("docs-review") is True
    assert observed.matrix_summary_artifact_root_matches("artifacts/review") is True
    assert observed.matrix_summary_path_matches("artifacts/review/matrix-summary.json") is True
    assert observed.matrix_summary_bundle_index_rerun_hint_matches("rerun docs parity") is True
    assert observed.matrix_summary_path_matches_metadata() is True
    assert observed.matrix_summary_line_matches_metadata_path() is True
    assert observed.metadata_paths == {
        "artifact_root": checkout_root / "artifacts" / "review",
        "bundle_index_path": checkout_root / "artifacts" / "review" / "index.json",
        "matrix_summary_path": summary_path,
    }
    assert observed.matrix_summary_paths == observed.metadata_paths


def test_collect_review_artifact_output_supports_matrix_summary_without_metadata(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    summary_path = checkout_root / "artifacts" / "review" / "matrix-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "bundle_index_rerun_hint": "rerun docs parity",
                "display_name": "docs-review-all",
                "target_name": "docs-review-all",
                "artifact_root": "artifacts/review",
                "matrix_summary_path": "artifacts/review/matrix-summary.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    observed = collect_review_artifact_output(
        ["[smoke-matrix] review matrix summary: artifacts/review/matrix-summary.json"],
        checkout_root=checkout_root,
        matrix_summary_prefix="[smoke-matrix] review matrix summary: ",
    )

    assert observed.metadata_index is None
    assert observed.artifacts_index is None
    assert observed.metadata_line == ""
    assert observed.artifacts_line == ""
    assert observed.matrix_summary_index == 0
    assert observed.matrix_summary_line_present is True
    assert observed.matrix_summary_artifact_exists is True
    assert observed.matrix_summary_targets("docs-review-all") is True
    assert observed.matrix_summary_artifact_root_matches("artifacts/review") is True
    assert observed.matrix_summary_path_matches("artifacts/review/matrix-summary.json") is True
    assert observed.matrix_summary_bundle_index_rerun_hint_matches("rerun docs parity") is True


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


def test_observe_loaded_review_artifact_output_reuses_loaded_module_and_shared_checkout(tmp_path: Path) -> None:
    script_path = tmp_path / "review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    args = list(argv or [])
    target_name = args[0] if args else 'review'
    stream_name = args[1] if len(args) > 1 else 'stdout'
    stream = getattr(sys, stream_name)
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    bundle_index_path = artifact_root / 'index.json'
    bundle_index_path.write_text(json.dumps({'target_name': target_name}, sort_keys=True) + '\\n', encoding='utf-8')
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'bundle_index_path': bundle_index_path.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=stream)
    print(f"[matrix] artifacts: {artifact_root.as_posix()}", file=stream)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=stream)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.review_target")
    checkout_root = tmp_path / "shared-checkout"
    checkout_root.mkdir()

    review_run, review_output = observe_loaded_review_artifact_output(
        module,
        argv=["review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        artifacts_prefix="[matrix] artifacts: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
    )
    all_review_run, all_review_output = observe_loaded_review_artifact_output(
        module,
        argv=["all-review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        artifacts_prefix="[matrix] artifacts: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
    )

    assert review_run.exit_code == 0
    assert all_review_run.exit_code == 0
    assert review_run.checkout_root == checkout_root
    assert all_review_run.checkout_root == checkout_root
    assert review_output.metadata_targets("review") is True
    assert all_review_output.metadata_targets("all-review") is True
    assert review_output.matrix_summary_artifact_exists is True
    assert all_review_output.matrix_summary_artifact_exists is True
    assert review_output.matrix_summary_path_matches_metadata() is True
    assert all_review_output.matrix_summary_path_matches_metadata() is True
    assert review_output.matrix_summary_path != all_review_output.matrix_summary_path
    assert (checkout_root / "artifacts" / "review" / "matrix-summary.json").exists()
    assert (checkout_root / "artifacts" / "all-review" / "matrix-summary.json").exists()


def test_run_loaded_script_module_main_in_temp_checkout_creates_cleanup_root(tmp_path: Path) -> None:
    script_path = tmp_path / "loaded_temp_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

from pathlib import Path


def main(argv=None):
    print(f"cwd_name={Path.cwd().name}")
    print(f"argv={list(argv or [])}")
    return 7
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.loaded_temp_target")

    result = run_loaded_script_module_main_in_temp_checkout(
        module,
        argv=["docs-review"],
        temp_prefix="loaded-temp-checkout-",
    )

    assert result.exit_code == 7
    assert result.checkout_root.name.startswith("loaded-temp-checkout-")
    assert result.stdout_lines == [
        f"cwd_name={result.checkout_root.name}",
        "argv=['docs-review']",
    ]
    assert result.checkout_root.exists()
    result.cleanup()
    assert not result.checkout_root.exists()


def test_observe_loaded_review_artifact_output_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.stderr_review_target")
    checkout_root = tmp_path / "stderr-checkout"
    checkout_root.mkdir()

    smoke_run, review_output = observe_loaded_review_artifact_output(
        module,
        argv=["review"],
        checkout_root=checkout_root,
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )

    assert smoke_run.exit_code == 0
    assert smoke_run.stdout == ""
    assert review_output.metadata_targets("stderr-review") is True
    assert review_output.matrix_summary_targets("stderr-review") is True
    assert review_output.matrix_summary_artifact_exists is True


def test_observe_loaded_review_artifact_output_in_temp_checkout_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_temp_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-temp-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.stderr_temp_review_target")

    smoke_run, review_output = observe_loaded_review_artifact_output_in_temp_checkout(
        module,
        argv=["review"],
        temp_prefix="stderr-temp-review-",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("stderr-temp-review") is True
        assert review_output.matrix_summary_targets("stderr-temp-review") is True
        assert review_output.matrix_summary_artifact_exists is True
        assert smoke_run.checkout_root.exists()
    finally:
        smoke_run.cleanup()
    assert not smoke_run.checkout_root.exists()


def test_observe_subprocess_review_artifact_output_supports_stderr_stream(tmp_path: Path) -> None:
    script_path = tmp_path / "stderr_subprocess_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'stderr-subprocess-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.stderr_subprocess_review_target",
        argv=["review"],
    )

    smoke_run, review_output = observe_subprocess_review_artifact_output(
        driver_source=driver_source,
        temp_prefix="harness-driver-review-",
        driver_filename="run_stderr_subprocess_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("stderr-subprocess-review") is True
        assert review_output.matrix_summary_targets("stderr-subprocess-review") is True
        assert review_output.matrix_summary_artifact_exists is True
    finally:
        smoke_run.cleanup()


def test_observe_review_artifact_output_in_temp_checkout_supports_loaded_and_subprocess_sources(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "generic_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'generic-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )
    module = load_script_module(script_path, "tests.generic_review_target")

    loaded_run, loaded_output = observe_review_artifact_output_in_temp_checkout(
        module=module,
        argv=["review"],
        temp_prefix="generic-loaded-review-",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert loaded_run.exit_code == 0
        assert loaded_output.metadata_targets("generic-review") is True
        assert loaded_output.matrix_summary_targets("generic-review") is True
    finally:
        loaded_run.cleanup()

    driver_source = build_script_driver_source(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.generic_review_driver_target",
        argv=["review"],
    )
    subprocess_run, subprocess_output = observe_review_artifact_output_in_temp_checkout(
        driver_source=driver_source,
        temp_prefix="generic-subprocess-review-",
        driver_filename="run_generic_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert subprocess_run.exit_code == 0
        assert subprocess_output.metadata_targets("generic-review") is True
        assert subprocess_output.matrix_summary_targets("generic-review") is True
    finally:
        subprocess_run.cleanup()


def test_observe_review_artifact_output_in_temp_checkout_validates_source_contract() -> None:
    with pytest.raises(ValueError, match="provide exactly one review artifact source: module or driver_source"):
        observe_review_artifact_output_in_temp_checkout(
            temp_prefix="missing-review-source-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="provide exactly one review artifact source: module or driver_source"):
        observe_review_artifact_output_in_temp_checkout(
            module=object(),
            driver_source="raise SystemExit(0)\n",
            argv=["review"],
            temp_prefix="duplicate-review-source-",
            driver_filename="run_duplicate_review_source.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="argv is required when observing a loaded review artifact module"):
        observe_review_artifact_output_in_temp_checkout(
            module=object(),
            temp_prefix="missing-review-argv-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )

    with pytest.raises(ValueError, match="driver_filename is required when driver_source is provided"):
        observe_review_artifact_output_in_temp_checkout(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="missing-review-driver-filename-",
            matrix_summary_prefix="[matrix] matrix summary: ",
        )


@pytest.mark.parametrize(
    "observer",
    (
        lambda tmp_path: observe_loaded_review_artifact_output(
            object(),
            argv=["review"],
            checkout_root=tmp_path,
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_loaded_review_artifact_output_in_temp_checkout(
            object(),
            argv=["review"],
            temp_prefix="harness-invalid-temp-output-stream-",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_review_artifact_output_in_temp_checkout(
            module=object(),
            argv=["review"],
            temp_prefix="harness-invalid-generic-temp-output-stream-",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_subprocess_review_artifact_output(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="harness-invalid-output-stream-",
            driver_filename="run_invalid_output_stream.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
        lambda tmp_path: observe_review_artifact_output_in_temp_checkout(
            driver_source="raise SystemExit(0)\n",
            temp_prefix="harness-invalid-generic-driver-output-stream-",
            driver_filename="run_invalid_generic_output_stream.py",
            matrix_summary_prefix="[matrix] matrix summary: ",
            output_stream="invalid",
        ),
    ),
)
def test_review_artifact_observers_reject_invalid_output_stream(
    tmp_path: Path,
    observer,
) -> None:
    with pytest.raises(ValueError, match="output_stream must be 'stdout' or 'stderr', got 'invalid'"):
        observer(tmp_path)


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



def test_run_script_module_main_via_driver_in_temp_checkout(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "driver_wrapper_target.py"
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
    return 6
""".strip()
        + "\n",
    )
    monkeypatch.setenv("HARNESS_CLEAR", "remove-me")

    result = run_script_module_main_via_driver_in_temp_checkout(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_wrapper_target",
        argv=["docs-review-only"],
        temp_prefix="harness-driver-wrapper-run-",
        driver_filename="run_driver_wrapper_target.py",
        env_assignments={"HARNESS_SET": "enabled"},
        env_unsets=("HARNESS_CLEAR",),
        hook_source="module.VALUE = 'hooked'",
    )
    try:
        assert result.exit_code == 6
        assert result.stderr == ""
        assert result.checkout_root.name.startswith("harness-driver-wrapper-run-")
        assert result.stdout_lines == [
            f"cwd_name={result.checkout_root.name}",
            "argv=['docs-review-only']",
            "value=hooked",
            "set=enabled",
            "clear=<missing>",
        ]
        assert os.environ["HARNESS_CLEAR"] == "remove-me"
    finally:
        result.cleanup()



def test_observe_script_module_main_via_driver_review_artifact_output(tmp_path: Path) -> None:
    script_path = tmp_path / "driver_wrapper_review_target.py"
    _write_target_script(
        script_path,
        """
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    target_name = 'driver-wrapper-review'
    artifact_root = Path('artifacts') / target_name
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_summary_path = artifact_root / 'matrix-summary.json'
    payload = {
        'display_name': target_name,
        'target_name': target_name,
        'artifact_root': artifact_root.as_posix(),
        'matrix_summary_path': matrix_summary_path.as_posix(),
    }
    matrix_summary_path.write_text(json.dumps(payload, sort_keys=True) + '\\n', encoding='utf-8')
    print(f"[matrix] metadata: {json.dumps(payload, sort_keys=True)}", file=sys.stderr)
    print(f"[matrix] matrix summary: {matrix_summary_path.as_posix()}", file=sys.stderr)
    return 0
""".strip()
        + "\n",
    )

    smoke_run, review_output = observe_script_module_main_via_driver_review_artifact_output(
        repo_root=tmp_path,
        script_path=script_path,
        module_name="tests.driver_wrapper_review_target",
        argv=["review"],
        temp_prefix="harness-driver-wrapper-review-",
        driver_filename="run_driver_wrapper_review_target.py",
        metadata_prefix="[matrix] metadata: ",
        matrix_summary_prefix="[matrix] matrix summary: ",
        output_stream="stderr",
    )
    try:
        assert smoke_run.exit_code == 0
        assert smoke_run.stdout == ""
        assert review_output.metadata_targets("driver-wrapper-review") is True
        assert review_output.matrix_summary_targets("driver-wrapper-review") is True
        assert review_output.matrix_summary_artifact_exists is True
    finally:
        smoke_run.cleanup()
