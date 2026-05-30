from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

REVIEW_ARTIFACT_METADATA_SKIP_KEYS = frozenset({"display_name", "target_name"})


def normalize_text_output(payload: str) -> str:
    if payload and not payload.endswith("\n"):
        payload += "\n"
    return payload


def write_text_output(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_text_output(payload), encoding="utf-8")


def format_diff_output(diff_sections: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    lines: list[str] = []
    for index, (script_name, diff_lines) in enumerate(diff_sections):
        if index:
            lines.append("")
        lines.append(f"### {script_name}")
        lines.extend(diff_lines)
    return "\n".join(lines)


def sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_stats(diff_lines: tuple[str, ...]) -> dict[str, int]:
    return {
        "added_line_count": sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        ),
        "hunk_count": sum(1 for line in diff_lines if line.startswith("@@ ")),
        "line_count": len(diff_lines),
        "removed_line_count": sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        ),
    }


def rendered_summary(text: str) -> str:
    for line in text.splitlines():
        summary = line.strip()
        if summary:
            return summary if len(summary) <= 120 else summary[:119] + "…"
    return ""


def rendered_bundle_sha256(rendered_sections: tuple[tuple[str, str], ...]) -> str | None:
    if not rendered_sections:
        return None
    return sha256_text("\n\n".join(f"### {script_name}\n{text}" for script_name, text in rendered_sections))


def diff_bundle_sha256(diff_sections: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    if not diff_sections:
        return None
    return sha256_text(normalize_text_output(format_diff_output(diff_sections)))


def resolve_checkout_path(path_text: str, *, checkout_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return checkout_root / path


def output_path_from_prefixed_lines(
    output_lines: str | Sequence[str],
    *,
    prefix: str,
    checkout_root: Path,
) -> Path | None:
    lines = output_lines.splitlines() if isinstance(output_lines, str) else output_lines
    for line in lines:
        if line.startswith(prefix):
            return resolve_checkout_path(line.removeprefix(prefix), checkout_root=checkout_root)
    return None


def resolve_review_artifact_paths(
    payload: Mapping[str, object],
    *,
    checkout_root: Path,
) -> dict[str, Path]:
    return {
        key: resolve_checkout_path(value, checkout_root=checkout_root)
        for key, value in payload.items()
        if key not in REVIEW_ARTIFACT_METADATA_SKIP_KEYS and isinstance(value, str)
    }


def load_review_matrix_summary(
    summary_path: Path | None,
    *,
    checkout_root: Path,
) -> tuple[dict[str, object], dict[str, Path]]:
    if summary_path is None or not summary_path.exists():
        return {}, {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return payload, resolve_review_artifact_paths(payload, checkout_root=checkout_root)


def build_smoke_cli_doc_section_payloads(
    *,
    rendered_sections: tuple[tuple[str, str], ...],
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...] = (),
    written_paths: tuple[Path, ...] = (),
    include_diff_lines: bool = True,
) -> list[dict[str, object]]:
    diff_lines_by_script_name = {
        script_name: tuple(diff_lines) for script_name, diff_lines in diff_sections
    }
    written_path_by_script_name = {path.stem: str(path) for path in written_paths}

    section_payloads: list[dict[str, object]] = []
    for script_name, rendered_text in rendered_sections:
        diff_lines = diff_lines_by_script_name.get(script_name)
        section: dict[str, object] = {
            "output_path": written_path_by_script_name.get(script_name),
            "rendered_char_count": len(rendered_text),
            "rendered_line_count": len(rendered_text.splitlines()),
            "rendered_sha256": sha256_text(rendered_text),
            "rendered_summary": rendered_summary(rendered_text),
            "script_name": script_name,
        }
        if diff_lines is not None:
            if include_diff_lines:
                section["diff_lines"] = list(diff_lines)
            section["diff_sha256"] = sha256_text("\n".join(diff_lines))
            section["diff_stats"] = diff_stats(diff_lines)
        section_payloads.append(section)
    return section_payloads



def build_smoke_cli_doc_render_manifest_payload(
    *,
    body_only: bool,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    rendered_sections: tuple[tuple[str, str], ...],
    written_paths: tuple[Path, ...],
    readme_path: Path,
    output_dir: Path | None,
    manifest_output: Path,
    diff_output: Path | None,
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, object]:
    return {
        "body_only": body_only,
        "diff_bundle_sha256": diff_bundle_sha256(diff_sections),
        "diff_output_path": str(diff_output) if diff_output is not None else None,
        "drift_count": len(diff_sections),
        "drift_only": True,
        "manifest_path": str(manifest_output),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "readme_path": str(readme_path),
        "rendered_bundle_sha256": rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": build_smoke_cli_doc_section_payloads(
            rendered_sections=rendered_sections,
            diff_sections=diff_sections,
            written_paths=written_paths,
        ),
        "selected_targets": list(selected_script_names),
        "up_to_date": not diff_sections,
    }



def build_smoke_cli_doc_drift_report_payload(
    *,
    readme_path: Path,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    rendered_sections: tuple[tuple[str, str], ...],
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
    include_diff_lines: bool,
    check: bool,
    drifted_readme_path: Path | None = None,
    render_output_dir: Path | None = None,
    render_manifest_path: Path | None = None,
    render_diff_path: Path | None = None,
    bundle_index_path: Path | None = None,
) -> dict[str, object]:
    drifted_sections: list[dict[str, object]] = []
    for script_name, diff_lines in diff_sections:
        section: dict[str, object] = {"script_name": script_name}
        if include_diff_lines:
            section["diff_lines"] = list(diff_lines)
        drifted_sections.append(section)
    return {
        "body_only": False,
        "check": check,
        "diff": include_diff_lines,
        "diff_bundle_sha256": diff_bundle_sha256(diff_sections),
        "drift_count": len(diff_sections),
        "drifted_readme_path": str(drifted_readme_path) if drifted_readme_path is not None else None,
        "drifted_sections": drifted_sections,
        "drifted_targets": [script_name for script_name, _ in diff_sections],
        "bundle_index_path": str(bundle_index_path) if bundle_index_path is not None else None,
        "readme_path": str(readme_path),
        "render_diff_path": str(render_diff_path) if render_diff_path is not None else None,
        "render_manifest_path": str(render_manifest_path) if render_manifest_path is not None else None,
        "render_output_dir": str(render_output_dir) if render_output_dir is not None else None,
        "rendered_bundle_sha256": rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": build_smoke_cli_doc_section_payloads(
            rendered_sections=rendered_sections,
            diff_sections=diff_sections,
            include_diff_lines=include_diff_lines,
        ),
        "selected_targets": list(selected_script_names),
        "up_to_date": not diff_sections,
    }



def build_smoke_cli_doc_repair_report_payload(
    *,
    readme_path: Path,
    requested_target_name: str | None,
    selected_script_names: tuple[str, ...],
    repaired_script_names: tuple[str, ...],
    original_markdown: str,
    repaired_markdown: str,
    rendered_sections: tuple[tuple[str, str], ...],
    diff_sections: tuple[tuple[str, tuple[str, ...]], ...],
    stdout: bool,
    drifted_readme_path: Path | None = None,
    render_output_dir: Path | None = None,
    render_manifest_path: Path | None = None,
    render_diff_path: Path | None = None,
    bundle_index_path: Path | None = None,
) -> dict[str, object]:
    return {
        "body_only": False,
        "changed": bool(repaired_script_names),
        "diff_bundle_sha256": diff_bundle_sha256(diff_sections),
        "drift_count": len(diff_sections),
        "drifted_readme_path": str(drifted_readme_path) if drifted_readme_path is not None else None,
        "drifted_targets": [script_name for script_name, _ in diff_sections],
        "bundle_index_path": str(bundle_index_path) if bundle_index_path is not None else None,
        "mode": "stdout" if stdout else "repair",
        "readme_path": str(readme_path),
        "readme_sha256_after": sha256_text(repaired_markdown),
        "render_diff_path": str(render_diff_path) if render_diff_path is not None else None,
        "render_manifest_path": str(render_manifest_path) if render_manifest_path is not None else None,
        "render_output_dir": str(render_output_dir) if render_output_dir is not None else None,
        "readme_sha256_before": sha256_text(original_markdown),
        "repaired_count": len(repaired_script_names),
        "repaired_targets": list(repaired_script_names),
        "rendered_bundle_sha256": rendered_bundle_sha256(rendered_sections),
        "rendered_count": len(rendered_sections),
        "rendered_targets": [script_name for script_name, _ in rendered_sections],
        "requested_target": requested_target_name,
        "sections": build_smoke_cli_doc_section_payloads(
            rendered_sections=rendered_sections,
            diff_sections=diff_sections,
            include_diff_lines=False,
        ),
        "selected_targets": list(selected_script_names),
        "up_to_date": not repaired_script_names,
        "wrote_readme": bool(repaired_script_names) and not stdout,
    }
