from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_CLI_DOC_SPECS,
    SmokeCliExample,
    SmokeScriptTarget,
    SmokeTargetSelector,
    build_smoke_cli_doc_drift_report_payload,
    build_smoke_cli_doc_render_manifest_payload,
    build_smoke_cli_doc_repair_report_payload,
    build_smoke_cli_parser,
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
DEFAULT_TARGET_NAME = "standalone_smoke"
RENDER_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_render.py"
FIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_fix.py"
ARTIFACT_TARGET_SELECTOR = SmokeTargetSelector(
    targets={
        spec.script_name: SmokeScriptTarget(spec.script_name, Path(f"{spec.script_name}.py"))
        for spec in SMOKE_CLI_DOC_SPECS
    },
    default_target_name=DEFAULT_TARGET_NAME,
    alias_target_names={"all": tuple(spec.script_name for spec in SMOKE_CLI_DOC_SPECS)},
)
ARTIFACT_SCRIPT_EXAMPLES = (
    SmokeCliExample("smoke_cli_docs_artifacts_smoke.py"),
    SmokeCliExample(
        "smoke_cli_docs_artifacts_smoke.py smoke_matrix",
        target_name="smoke_matrix",
        description="single smoke wrapper artifact contract",
    ),
    SmokeCliExample(
        "smoke_cli_docs_artifacts_smoke.py all --output-dir artifacts/smoke-cli-docs-artifacts",
        target_name="all",
        description=(
            "persist drifted README plus render/fix JSON review artifacts for every public smoke wrapper"
        ),
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = build_smoke_cli_parser(
        description=(
            "Exercise the smoke CLI docs render/fix artifact contract against drifted README sections "
            "and fail on any contract mismatch."
        ),
        choices=ARTIFACT_TARGET_SELECTOR.choices,
        default_target_name=ARTIFACT_TARGET_SELECTOR.default_target_name,
        resolve_target_names=ARTIFACT_TARGET_SELECTOR.resolve_target_names,
        resolve_display_names=ARTIFACT_TARGET_SELECTOR.resolve_display_names,
        item_help="Which public smoke-wrapper docs artifact contract to exercise.",
        alias_target_names=ARTIFACT_TARGET_SELECTOR.alias_target_names,
        examples=ARTIFACT_SCRIPT_EXAMPLES,
        single_choice_description="single smoke wrapper artifact contract",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Keep the drifted README plus render/fix JSON/diff artifacts in this directory "
            "instead of using a temporary directory."
        ),
    )
    return parser


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _drifted_markdown(markdown: str, *, requested_target_name: str) -> str:
    drifted_markdown = markdown
    for script_name in resolve_smoke_cli_doc_target_names(requested_target_name):
        rendered_section = render_smoke_cli_readme_section(script_name, body_only=True)
        drifted_section = rendered_section.replace("Operator shortcuts:", "Operator shortcut notes:", 1)
        if drifted_section == rendered_section:
            raise ValueError(f"unable to synthesize README drift for {script_name!r}")
        spec = smoke_cli_doc_spec(script_name)
        drifted_markdown = replace_markdown_section(
            drifted_markdown,
            heading=spec.readme_section_heading,
            body=drifted_section,
        )
    return drifted_markdown


def _run_artifact_contract(
    *,
    requested_target_name: str,
    artifact_root: Path,
) -> list[tuple[str, object]]:
    original_markdown = README_PATH.read_text(encoding="utf-8")
    drifted_markdown = _drifted_markdown(original_markdown, requested_target_name=requested_target_name)
    selected_script_names = tuple(resolve_smoke_cli_doc_target_names(requested_target_name))

    artifact_root.mkdir(parents=True, exist_ok=True)
    drifted_readme_path = artifact_root / "README-drifted.md"
    render_output_dir = artifact_root / "rendered"
    render_manifest_path = artifact_root / "render-manifest.json"
    render_diff_path = artifact_root / "render-review.patch"
    fix_check_json_path = artifact_root / "fix-check.json"
    fix_repair_json_path = artifact_root / "fix-repair.json"
    fix_post_check_json_path = artifact_root / "fix-post-check.json"

    drifted_readme_path.write_text(drifted_markdown, encoding="utf-8")

    render_result = _run_script(
        str(RENDER_SCRIPT_PATH),
        requested_target_name,
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
        requested_target_name=requested_target_name,
    )
    render_sections = tuple(
        (script_name, render_smoke_cli_readme_section(script_name))
        for script_name, _diff_lines in render_diff_sections
    )
    render_written_paths = tuple(render_output_dir / f"{script_name}.md" for script_name, _ in render_sections)
    expected_render_manifest = build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name=requested_target_name,
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
        requested_target_name,
        "--readme-path",
        str(drifted_readme_path),
        "--check",
        "--json-output",
        str(fix_check_json_path),
    )
    fix_check_payload = json.loads(fix_check_json_path.read_text(encoding="utf-8"))
    expected_fix_check_payload = build_smoke_cli_doc_drift_report_payload(
        readme_path=drifted_readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        rendered_sections=render_sections,
        diff_sections=render_diff_sections,
        include_diff_lines=False,
        check=True,
    )

    fix_repair_result = _run_script(
        str(FIX_SCRIPT_PATH),
        requested_target_name,
        "--readme-path",
        str(drifted_readme_path),
        "--json-output",
        str(fix_repair_json_path),
    )
    repaired_markdown = drifted_readme_path.read_text(encoding="utf-8")
    repaired_diff_sections = collect_smoke_cli_readme_diffs(
        repaired_markdown,
        requested_target_name=requested_target_name,
    )
    fix_repair_payload = json.loads(fix_repair_json_path.read_text(encoding="utf-8"))
    expected_fix_repair_payload = build_smoke_cli_doc_repair_report_payload(
        readme_path=drifted_readme_path,
        requested_target_name=requested_target_name,
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
        requested_target_name,
        "--readme-path",
        str(drifted_readme_path),
        "--check",
        "--json-output",
        str(fix_post_check_json_path),
    )
    fix_post_check_payload = json.loads(fix_post_check_json_path.read_text(encoding="utf-8"))
    expected_fix_post_check_payload = build_smoke_cli_doc_drift_report_payload(
        readme_path=drifted_readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        rendered_sections=(),
        diff_sections=(),
        include_diff_lines=False,
        check=True,
    )

    rendered_section_payload = render_manifest["sections"][0] if render_manifest["sections"] else {}

    return [
        ("requested_target", requested_target_name),
        ("selected_targets", ", ".join(selected_script_names)),
        ("artifact_root", str(artifact_root)),
        ("render_stdout", " | ".join(render_result.stdout.strip().splitlines())),
        ("render_manifest_drift_count", render_manifest.get("drift_count")),
        ("render_manifest_summary", rendered_section_payload.get("rendered_summary")),
        ("render_manifest_diff_stats", rendered_section_payload.get("diff_stats")),
        ("fix_check_stdout", " | ".join(fix_check_result.stdout.strip().splitlines())),
        ("fix_repair_stdout", " | ".join(fix_repair_result.stdout.strip().splitlines())),
        ("fix_post_check_stdout", " | ".join(fix_post_check_result.stdout.strip().splitlines())),
        ("render_exit", render_result.returncode == 0),
        ("render_manifest_payload", render_manifest == expected_render_manifest),
        (
            "render_outputs_written",
            render_manifest_path.exists()
            and render_diff_path.exists()
            and bool(render_written_paths)
            and all(path.exists() for path in render_written_paths),
        ),
        ("fix_check_exit", fix_check_result.returncode == 1),
        ("fix_check_payload", fix_check_payload == expected_fix_check_payload),
        ("fix_repair_exit", fix_repair_result.returncode == 0),
        ("fix_repair_payload", fix_repair_payload == expected_fix_repair_payload),
        (
            "fix_repair_applied",
            repaired_diff_sections == ()
            and normalize_text_output(repaired_markdown) != normalize_text_output(drifted_markdown),
        ),
        ("fix_post_check_exit", fix_post_check_result.returncode == 0),
        ("fix_post_check_payload", fix_post_check_payload == expected_fix_post_check_payload),
    ]


def run_smoke_cli_docs_artifacts_smoke(
    requested_target_name: str = DEFAULT_TARGET_NAME,
    *,
    output_dir: Path | None = None,
) -> list[tuple[str, object]]:
    if output_dir is None:
        with tempfile.TemporaryDirectory(prefix="smoke-cli-docs-artifacts-") as tmp_dir_name:
            return _run_artifact_contract(
                requested_target_name=requested_target_name,
                artifact_root=Path(tmp_dir_name),
            )
    return _run_artifact_contract(requested_target_name=requested_target_name, artifact_root=output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return emit_smoke_results(
        run_smoke_cli_docs_artifacts_smoke(
            args.target,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
