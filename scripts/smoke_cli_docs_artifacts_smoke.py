from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    build_smoke_cli_doc_drift_report_payload,
    build_smoke_cli_doc_render_manifest_payload,
    build_smoke_cli_doc_repair_report_payload,
    collect_smoke_cli_readme_diffs,
    emit_smoke_results,
    normalize_text_output,
    render_smoke_cli_readme_section,
    replace_markdown_section,
    resolve_smoke_cli_doc_target_names,
    smoke_cli_doc_spec,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
README_PATH = REPO_ROOT / "README.md"
TARGET_NAME = "standalone_smoke"
RENDER_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_render.py"
FIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_fix.py"


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _drifted_markdown(markdown: str) -> str:
    rendered_section = render_smoke_cli_readme_section(TARGET_NAME, body_only=True)
    drifted_section = rendered_section.replace("Operator shortcuts:", "Operator shortcut notes:", 1)
    assert drifted_section != rendered_section
    spec = smoke_cli_doc_spec(TARGET_NAME)
    return replace_markdown_section(
        markdown,
        heading=spec.readme_section_heading,
        body=drifted_section,
    )


def run_smoke_cli_docs_artifacts_smoke() -> list[tuple[str, object]]:
    original_markdown = README_PATH.read_text(encoding="utf-8")
    drifted_markdown = _drifted_markdown(original_markdown)
    selected_script_names = tuple(resolve_smoke_cli_doc_target_names(TARGET_NAME))

    with tempfile.TemporaryDirectory(prefix="smoke-cli-docs-artifacts-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        drifted_readme_path = tmp_dir / "README-drifted.md"
        render_output_dir = tmp_dir / "rendered"
        render_manifest_path = tmp_dir / "render-manifest.json"
        render_diff_path = tmp_dir / "render-review.patch"
        fix_check_json_path = tmp_dir / "fix-check.json"
        fix_repair_json_path = tmp_dir / "fix-repair.json"
        fix_post_check_json_path = tmp_dir / "fix-post-check.json"

        drifted_readme_path.write_text(drifted_markdown, encoding="utf-8")

        render_result = _run_script(
            str(RENDER_SCRIPT_PATH),
            TARGET_NAME,
            "--readme-path",
            str(drifted_readme_path),
            "--drift-only",
            "--output-dir",
            str(render_output_dir),
            "--manifest-output",
            str(render_manifest_path),
            "--diff-output",
            str(render_diff_path),
        )
        render_manifest = json.loads(render_manifest_path.read_text(encoding="utf-8"))
        render_diff_sections = collect_smoke_cli_readme_diffs(
            drifted_markdown,
            requested_target_name=TARGET_NAME,
        )
        render_sections = tuple(
            (script_name, render_smoke_cli_readme_section(script_name))
            for script_name, _diff_lines in render_diff_sections
        )
        render_written_paths = tuple(render_output_dir.glob("*.md"))
        expected_render_manifest = build_smoke_cli_doc_render_manifest_payload(
            body_only=False,
            requested_target_name=TARGET_NAME,
            selected_script_names=selected_script_names,
            rendered_sections=render_sections,
            written_paths=render_written_paths,
            readme_path=drifted_readme_path,
            output_dir=render_output_dir,
            manifest_output=render_manifest_path,
            diff_output=render_diff_path,
            diff_sections=render_diff_sections,
        )

        fix_check_result = _run_script(
            str(FIX_SCRIPT_PATH),
            TARGET_NAME,
            "--readme-path",
            str(drifted_readme_path),
            "--check",
            "--json-output",
            str(fix_check_json_path),
        )
        fix_check_payload = json.loads(fix_check_json_path.read_text(encoding="utf-8"))
        expected_fix_check_payload = build_smoke_cli_doc_drift_report_payload(
            readme_path=drifted_readme_path,
            requested_target_name=TARGET_NAME,
            selected_script_names=selected_script_names,
            rendered_sections=render_sections,
            diff_sections=render_diff_sections,
            include_diff_lines=False,
            check=True,
        )

        fix_repair_result = _run_script(
            str(FIX_SCRIPT_PATH),
            TARGET_NAME,
            "--readme-path",
            str(drifted_readme_path),
            "--json-output",
            str(fix_repair_json_path),
        )
        repaired_markdown = drifted_readme_path.read_text(encoding="utf-8")
        fix_repair_payload = json.loads(fix_repair_json_path.read_text(encoding="utf-8"))
        expected_fix_repair_payload = build_smoke_cli_doc_repair_report_payload(
            readme_path=drifted_readme_path,
            requested_target_name=TARGET_NAME,
            selected_script_names=selected_script_names,
            repaired_script_names=tuple(script_name for script_name, _diff_lines in render_diff_sections),
            original_markdown=drifted_markdown,
            repaired_markdown=repaired_markdown,
            rendered_sections=render_sections,
            diff_sections=render_diff_sections,
            stdout=False,
        )

        fix_post_check_result = _run_script(
            str(FIX_SCRIPT_PATH),
            TARGET_NAME,
            "--readme-path",
            str(drifted_readme_path),
            "--check",
            "--json-output",
            str(fix_post_check_json_path),
        )
        fix_post_check_payload = json.loads(fix_post_check_json_path.read_text(encoding="utf-8"))
        expected_fix_post_check_payload = build_smoke_cli_doc_drift_report_payload(
            readme_path=drifted_readme_path,
            requested_target_name=TARGET_NAME,
            selected_script_names=selected_script_names,
            rendered_sections=(),
            diff_sections=(),
            include_diff_lines=False,
            check=True,
        )

        rendered_section_payload = render_manifest["sections"][0] if render_manifest["sections"] else {}

        return [
            ("render_stdout", " | ".join(render_result.stdout.strip().splitlines())),
            ("render_manifest_drift_count", render_manifest.get("drift_count")),
            ("render_manifest_summary", rendered_section_payload.get("rendered_summary")),
            ("render_manifest_diff_stats", rendered_section_payload.get("diff_stats")),
            ("fix_check_stdout", " | ".join(fix_check_result.stdout.strip().splitlines())),
            ("fix_repair_stdout", " | ".join(fix_repair_result.stdout.strip().splitlines())),
            ("fix_post_check_stdout", " | ".join(fix_post_check_result.stdout.strip().splitlines())),
            ("render_exit", render_result.returncode == 0),
            ("render_manifest_payload", render_manifest == expected_render_manifest),
            ("render_outputs_written", render_manifest_path.exists() and render_diff_path.exists() and bool(render_written_paths)),
            ("fix_check_exit", fix_check_result.returncode == 1),
            ("fix_check_payload", fix_check_payload == expected_fix_check_payload),
            ("fix_repair_exit", fix_repair_result.returncode == 0),
            ("fix_repair_payload", fix_repair_payload == expected_fix_repair_payload),
            (
                "fix_repair_applied",
                normalize_text_output(repaired_markdown) == normalize_text_output(original_markdown),
            ),
            ("fix_post_check_exit", fix_post_check_result.returncode == 0),
            ("fix_post_check_payload", fix_post_check_payload == expected_fix_post_check_payload),
        ]


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, []):
        raise SystemExit("smoke_cli_docs_artifacts_smoke.py does not accept arguments")
    return emit_smoke_results(run_smoke_cli_docs_artifacts_smoke())


if __name__ == "__main__":
    raise SystemExit(main())
