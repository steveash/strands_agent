from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strands_agent_tui.testing import (
    SMOKE_CLI_DOC_ARTIFACTS_DEFAULT_TARGET_NAME,
    SMOKE_CLI_DOC_ARTIFACTS_TARGET_SELECTOR,
    build_smoke_cli_doc_drift_report_payload,
    build_smoke_cli_doc_artifacts_parser,
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
DEFAULT_TARGET_NAME = SMOKE_CLI_DOC_ARTIFACTS_DEFAULT_TARGET_NAME
RENDER_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_render.py"
FIX_SCRIPT_PATH = SCRIPT_DIR / "smoke_cli_docs_fix.py"
ARTIFACT_TARGET_SELECTOR = SMOKE_CLI_DOC_ARTIFACTS_TARGET_SELECTOR


class ArtifactContractPaths(tuple):
    __slots__ = ()
    _fields = (
        "artifact_root",
        "source_readme_path",
        "drifted_readme_path",
        "render_output_dir",
        "render_manifest_path",
        "render_diff_path",
        "fix_check_json_path",
        "fix_repair_json_path",
        "fix_post_check_json_path",
        "bundle_index_path",
    )

    def __new__(
        cls,
        artifact_root: Path,
        source_readme_path: Path,
        drifted_readme_path: Path,
        render_output_dir: Path,
        render_manifest_path: Path,
        render_diff_path: Path,
        fix_check_json_path: Path,
        fix_repair_json_path: Path,
        fix_post_check_json_path: Path,
        bundle_index_path: Path,
    ):
        return super().__new__(
            cls,
            (
                artifact_root,
                source_readme_path,
                drifted_readme_path,
                render_output_dir,
                render_manifest_path,
                render_diff_path,
                fix_check_json_path,
                fix_repair_json_path,
                fix_post_check_json_path,
                bundle_index_path,
            ),
        )

    def __getattr__(self, name: str) -> Path:
        try:
            index = self._fields.index(name)
        except ValueError as exc:
            raise AttributeError(name) from exc
        return self[index]


def build_parser() -> argparse.ArgumentParser:
    return build_smoke_cli_doc_artifacts_parser(readme_path=README_PATH)


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


def _artifact_root_from_explicit_paths(paths: Sequence[Path]) -> Path | None:
    if not paths:
        return None
    parent_strings = [str(path) for path in paths]
    return Path(os.path.commonpath(parent_strings))


def _resolve_artifact_paths(
    *,
    source_readme_path: Path,
    output_dir: Path | None,
    drifted_readme_path: Path | None,
    render_output_dir: Path | None,
    render_manifest_path: Path | None,
    render_diff_path: Path | None,
    fix_check_json_path: Path | None,
    fix_repair_json_path: Path | None,
    fix_post_check_json_path: Path | None,
    bundle_index_path: Path | None,
) -> ArtifactContractPaths:
    explicit_dirs: list[Path] = []
    if drifted_readme_path is not None:
        explicit_dirs.append(drifted_readme_path.parent)
    if render_output_dir is not None:
        explicit_dirs.append(render_output_dir)
    if render_manifest_path is not None:
        explicit_dirs.append(render_manifest_path.parent)
    if render_diff_path is not None:
        explicit_dirs.append(render_diff_path.parent)
    if fix_check_json_path is not None:
        explicit_dirs.append(fix_check_json_path.parent)
    if fix_repair_json_path is not None:
        explicit_dirs.append(fix_repair_json_path.parent)
    if fix_post_check_json_path is not None:
        explicit_dirs.append(fix_post_check_json_path.parent)
    if bundle_index_path is not None:
        explicit_dirs.append(bundle_index_path.parent)

    artifact_root = output_dir or _artifact_root_from_explicit_paths(explicit_dirs) or source_readme_path.parent

    return ArtifactContractPaths(
        artifact_root=artifact_root,
        source_readme_path=source_readme_path,
        drifted_readme_path=drifted_readme_path or artifact_root / "README-drifted.md",
        render_output_dir=render_output_dir or artifact_root / "rendered",
        render_manifest_path=render_manifest_path or artifact_root / "render-manifest.json",
        render_diff_path=render_diff_path or artifact_root / "render-review.patch",
        fix_check_json_path=fix_check_json_path or artifact_root / "fix-check.json",
        fix_repair_json_path=fix_repair_json_path or artifact_root / "fix-repair.json",
        fix_post_check_json_path=fix_post_check_json_path or artifact_root / "fix-post-check.json",
        bundle_index_path=bundle_index_path or artifact_root / "bundle-index.json",
    )


def _split_smoke_results(results: Sequence[tuple[str, object]]) -> tuple[dict[str, object], dict[str, bool]]:
    details: dict[str, object] = {}
    checks: dict[str, bool] = {}
    for name, value in results:
        if isinstance(value, bool):
            checks[name] = value
        else:
            details[name] = value
    return details, checks


def _build_bundle_index_payload(
    *,
    requested_target_name: str,
    selected_script_names: Sequence[str],
    paths: ArtifactContractPaths,
    results: Sequence[tuple[str, object]],
    rerun_hint: str | None,
) -> dict[str, object]:
    details, checks = _split_smoke_results(results)
    return {
        "requested_target_name": requested_target_name,
        "selected_script_names": list(selected_script_names),
        "rerun_hint": rerun_hint,
        "artifact_paths": {
            "artifact_root": str(paths.artifact_root),
            "source_readme_path": str(paths.source_readme_path),
            "drifted_readme_path": str(paths.drifted_readme_path),
            "render_output_dir": str(paths.render_output_dir),
            "render_manifest_path": str(paths.render_manifest_path),
            "render_diff_path": str(paths.render_diff_path),
            "fix_check_json_path": str(paths.fix_check_json_path),
            "fix_repair_json_path": str(paths.fix_repair_json_path),
            "fix_post_check_json_path": str(paths.fix_post_check_json_path),
            "bundle_index_path": str(paths.bundle_index_path),
        },
        "details": details,
        "checks": checks,
    }


def _run_artifact_contract(
    *,
    requested_target_name: str,
    paths: ArtifactContractPaths,
) -> list[tuple[str, object]]:
    original_markdown = paths.source_readme_path.read_text(encoding="utf-8")
    drifted_markdown = _drifted_markdown(original_markdown, requested_target_name=requested_target_name)
    selected_script_names = tuple(resolve_smoke_cli_doc_target_names(requested_target_name))

    paths.artifact_root.mkdir(parents=True, exist_ok=True)
    paths.drifted_readme_path.parent.mkdir(parents=True, exist_ok=True)

    paths.drifted_readme_path.write_text(drifted_markdown, encoding="utf-8")

    render_result = _run_script(
        str(RENDER_SCRIPT_PATH),
        requested_target_name,
        "--readme-path",
        str(paths.drifted_readme_path),
        "--drift-only",
        "--output-dir",
        str(paths.render_output_dir),
        "--manifest-output",
        str(paths.render_manifest_path),
        "--diff-output",
        str(paths.render_diff_path),
    )
    render_manifest = json.loads(paths.render_manifest_path.read_text(encoding="utf-8"))
    render_diff_sections = collect_smoke_cli_readme_diffs(
        drifted_markdown,
        requested_target_name=requested_target_name,
    )
    render_sections = tuple(
        (script_name, render_smoke_cli_readme_section(script_name))
        for script_name, _diff_lines in render_diff_sections
    )
    render_written_paths = tuple(
        paths.render_output_dir / f"{script_name}.md" for script_name, _ in render_sections
    )
    expected_render_manifest = build_smoke_cli_doc_render_manifest_payload(
        body_only=False,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        rendered_sections=render_sections,
        written_paths=render_written_paths,
        readme_path=paths.drifted_readme_path,
        output_dir=paths.render_output_dir,
        manifest_output=paths.render_manifest_path,
        diff_output=paths.render_diff_path,
        diff_sections=render_diff_sections,
    )

    fix_check_result = _run_script(
        str(FIX_SCRIPT_PATH),
        requested_target_name,
        "--readme-path",
        str(paths.drifted_readme_path),
        "--check",
        "--json-output",
        str(paths.fix_check_json_path),
        "--drifted-readme-path",
        str(paths.drifted_readme_path),
        "--bundle-index-path",
        str(paths.bundle_index_path),
        "--render-output-dir",
        str(paths.render_output_dir),
        "--render-manifest-path",
        str(paths.render_manifest_path),
        "--render-diff-path",
        str(paths.render_diff_path),
    )
    fix_check_payload = json.loads(paths.fix_check_json_path.read_text(encoding="utf-8"))
    expected_fix_check_payload = build_smoke_cli_doc_drift_report_payload(
        readme_path=paths.drifted_readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        rendered_sections=render_sections,
        diff_sections=render_diff_sections,
        include_diff_lines=False,
        check=True,
        drifted_readme_path=paths.drifted_readme_path,
        render_output_dir=paths.render_output_dir,
        render_manifest_path=paths.render_manifest_path,
        render_diff_path=paths.render_diff_path,
        bundle_index_path=paths.bundle_index_path,
    )

    fix_repair_result = _run_script(
        str(FIX_SCRIPT_PATH),
        requested_target_name,
        "--readme-path",
        str(paths.drifted_readme_path),
        "--json-output",
        str(paths.fix_repair_json_path),
        "--drifted-readme-path",
        str(paths.drifted_readme_path),
        "--bundle-index-path",
        str(paths.bundle_index_path),
        "--render-output-dir",
        str(paths.render_output_dir),
        "--render-manifest-path",
        str(paths.render_manifest_path),
        "--render-diff-path",
        str(paths.render_diff_path),
    )
    repaired_markdown = paths.drifted_readme_path.read_text(encoding="utf-8")
    repaired_diff_sections = collect_smoke_cli_readme_diffs(
        repaired_markdown,
        requested_target_name=requested_target_name,
    )
    fix_repair_payload = json.loads(paths.fix_repair_json_path.read_text(encoding="utf-8"))
    expected_fix_repair_payload = build_smoke_cli_doc_repair_report_payload(
        readme_path=paths.drifted_readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        repaired_script_names=tuple(script_name for script_name, _diff_lines in render_diff_sections),
        original_markdown=drifted_markdown,
        repaired_markdown=repaired_markdown,
        rendered_sections=render_sections,
        diff_sections=render_diff_sections,
        stdout=False,
        drifted_readme_path=paths.drifted_readme_path,
        render_output_dir=paths.render_output_dir,
        render_manifest_path=paths.render_manifest_path,
        render_diff_path=paths.render_diff_path,
        bundle_index_path=paths.bundle_index_path,
    )

    fix_post_check_result = _run_script(
        str(FIX_SCRIPT_PATH),
        requested_target_name,
        "--readme-path",
        str(paths.drifted_readme_path),
        "--check",
        "--json-output",
        str(paths.fix_post_check_json_path),
        "--drifted-readme-path",
        str(paths.drifted_readme_path),
        "--bundle-index-path",
        str(paths.bundle_index_path),
        "--render-output-dir",
        str(paths.render_output_dir),
        "--render-manifest-path",
        str(paths.render_manifest_path),
        "--render-diff-path",
        str(paths.render_diff_path),
    )
    fix_post_check_payload = json.loads(paths.fix_post_check_json_path.read_text(encoding="utf-8"))
    expected_fix_post_check_payload = build_smoke_cli_doc_drift_report_payload(
        readme_path=paths.drifted_readme_path,
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        rendered_sections=(),
        diff_sections=(),
        include_diff_lines=False,
        check=True,
        drifted_readme_path=paths.drifted_readme_path,
        render_output_dir=paths.render_output_dir,
        render_manifest_path=paths.render_manifest_path,
        render_diff_path=paths.render_diff_path,
        bundle_index_path=paths.bundle_index_path,
    )

    rendered_section_payload = render_manifest["sections"][0] if render_manifest["sections"] else {}

    results = [
        ("requested_target", requested_target_name),
        ("selected_targets", ", ".join(selected_script_names)),
        ("artifact_root", str(paths.artifact_root)),
        ("source_readme_path", str(paths.source_readme_path)),
        ("drifted_readme_path", str(paths.drifted_readme_path)),
        ("render_output_dir", str(paths.render_output_dir)),
        ("render_manifest_path", str(paths.render_manifest_path)),
        ("render_diff_path", str(paths.render_diff_path)),
        ("fix_check_json_path", str(paths.fix_check_json_path)),
        ("fix_repair_json_path", str(paths.fix_repair_json_path)),
        ("fix_post_check_json_path", str(paths.fix_post_check_json_path)),
        ("bundle_index_path", str(paths.bundle_index_path)),
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
            paths.render_manifest_path.exists()
            and paths.render_diff_path.exists()
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
    bundle_index_payload = _build_bundle_index_payload(
        requested_target_name=requested_target_name,
        selected_script_names=selected_script_names,
        paths=paths,
        results=results,
        rerun_hint=fix_check_payload.get("rerun_hint") if isinstance(fix_check_payload, dict) else None,
    )
    paths.bundle_index_path.parent.mkdir(parents=True, exist_ok=True)
    paths.bundle_index_path.write_text(
        json.dumps(bundle_index_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written_bundle_index_payload = json.loads(paths.bundle_index_path.read_text(encoding="utf-8"))
    results.extend(
        [
            ("bundle_index_written", paths.bundle_index_path.exists()),
            ("bundle_index_payload", written_bundle_index_payload == bundle_index_payload),
        ]
    )
    return results


def run_smoke_cli_docs_artifacts_smoke(
    requested_target_name: str = DEFAULT_TARGET_NAME,
    *,
    readme_path: Path = README_PATH,
    output_dir: Path | None = None,
    drifted_readme_path: Path | None = None,
    render_output_dir: Path | None = None,
    render_manifest_path: Path | None = None,
    render_diff_path: Path | None = None,
    fix_check_json_path: Path | None = None,
    fix_repair_json_path: Path | None = None,
    fix_post_check_json_path: Path | None = None,
    bundle_index_path: Path | None = None,
) -> list[tuple[str, object]]:
    explicit_output_paths = (
        drifted_readme_path,
        render_output_dir,
        render_manifest_path,
        render_diff_path,
        fix_check_json_path,
        fix_repair_json_path,
        fix_post_check_json_path,
        bundle_index_path,
    )
    if output_dir is None and not any(path is not None for path in explicit_output_paths):
        with tempfile.TemporaryDirectory(prefix="smoke-cli-docs-artifacts-") as tmp_dir_name:
            paths = _resolve_artifact_paths(
                source_readme_path=readme_path,
                output_dir=Path(tmp_dir_name),
                drifted_readme_path=drifted_readme_path,
                render_output_dir=render_output_dir,
                render_manifest_path=render_manifest_path,
                render_diff_path=render_diff_path,
                fix_check_json_path=fix_check_json_path,
                fix_repair_json_path=fix_repair_json_path,
                fix_post_check_json_path=fix_post_check_json_path,
                bundle_index_path=bundle_index_path,
            )
            return _run_artifact_contract(
                requested_target_name=requested_target_name,
                paths=paths,
            )
    paths = _resolve_artifact_paths(
        source_readme_path=readme_path,
        output_dir=output_dir,
        drifted_readme_path=drifted_readme_path,
        render_output_dir=render_output_dir,
        render_manifest_path=render_manifest_path,
        render_diff_path=render_diff_path,
        fix_check_json_path=fix_check_json_path,
        fix_repair_json_path=fix_repair_json_path,
        fix_post_check_json_path=fix_post_check_json_path,
        bundle_index_path=bundle_index_path,
    )
    return _run_artifact_contract(requested_target_name=requested_target_name, paths=paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return emit_smoke_results(
        run_smoke_cli_docs_artifacts_smoke(
            args.target,
            readme_path=args.readme_path,
            output_dir=args.output_dir,
            drifted_readme_path=args.drifted_readme_path,
            render_output_dir=args.render_output_dir,
            render_manifest_path=args.render_manifest_path,
            render_diff_path=args.render_diff_path,
            fix_check_json_path=args.fix_check_json_path,
            fix_repair_json_path=args.fix_repair_json_path,
            fix_post_check_json_path=args.fix_post_check_json_path,
            bundle_index_path=args.bundle_index_path,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
