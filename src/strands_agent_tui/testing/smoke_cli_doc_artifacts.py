from __future__ import annotations

import hashlib
from pathlib import Path


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
